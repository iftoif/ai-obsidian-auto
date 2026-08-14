#!/usr/bin/env python3
"""
Obsidian Vault → 增量双备份管道

用法:
  python3 obsidian_backup.py                  # 默认增量备份（只处理新/改过的文件）
  python3 obsidian_backup.py --full            # 全量重建
  python3 obsidian_backup.py --stats           # 只查看库统计
  python3 obsidian_backup.py --search "关键词"  # 搜索笔记内容

环境变量:
  OBSIDIAN_VAULT_PATH  — Obsidian 库路径（默认 ~/Documents/Obsidian Vault）
  HERMES_HOME          — Hermes 数据目录（默认 ~/.hermes）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── 路径 ──────────────────────────────────────────────

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
VAULT_PATH = Path(
    os.environ.get(
        "OBSIDIAN_VAULT_PATH",
        str(Path.home() / "Documents/Obsidian Vault"),
    )
)
SCRIPTS_DIR = HERMES_HOME / "scripts"
DATA_DIR = HERMES_HOME / "data" / "obsidian"
STATE_FILE = DATA_DIR / "state.json"
DB_PATH = DATA_DIR / "obsidian_fts.db"
CHROMA_PATH = DATA_DIR / "chroma_db"

# ChromaDB is most useful for high-density knowledge pages. Very large raw chat
# logs slow down embedding and often hurt semantic retrieval quality, so keep
# them searchable in SQLite FTS5 but skip/limit vector indexing by default.
CHROMA_MAX_RAW_BYTES = int(os.environ.get("OBSIDIAN_CHROMA_MAX_RAW_BYTES", "250000"))
CHROMA_SKIP_RAW_CHAT_LOGS = os.environ.get("OBSIDIAN_CHROMA_SKIP_RAW_CHAT_LOGS", "1") != "0"
CHROMA_PRIORITY_PREFIXES = ("Wiki/", "Context/", "Hermes/Lessons/", "Codex/Lessons/", "Shared/Lessons/", "Skills/")
CHROMA_RAW_CHAT_PREFIXES = (
    "Hermes/Chat Logs/", "Codex/Chat Logs/", "Claude/Chat Logs/",
    "Pi/Chat Logs/", "DSH/Chat Logs/",
)
CHROMA_ENABLED = os.environ.get("OBSIDIAN_CHROMA_ENABLED", "1") != "0"

DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── 笔记模型 ──────────────────────────────────────────

def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """提取 YAML frontmatter 和正文。

    支持两种写法：
      tags: [a, b]           # 内联列表
      tags:                  # block 列表（缩进 - 项）
        - a
        - b
    """
    fm: dict[str, Any] = {}
    body = text

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            raw_fm = parts[1].strip()
            body = parts[2].strip()
            current_key: str | None = None
            for line in raw_fm.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if not line.startswith((" ", "\t")):
                    # 顶层 key: value
                    if ":" in line:
                        key, _, val = line.partition(":")
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        current_key = key
                        if val:
                            # 内联值
                            if val.startswith("[") and val.endswith("]"):
                                try:
                                    fm[key] = json.loads(val)
                                except json.JSONDecodeError:
                                    fm[key] = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",") if v.strip()]
                            elif val.lower() in ("true", "false"):
                                fm[key] = val.lower() == "true"
                            else:
                                fm[key] = val
                        else:
                            # 值为空 → block 列表，值在后续缩进行
                            fm[key] = []
                else:
                    # 缩进行：归属 current_key 的列表项（YAML block 风格）
                    if current_key is not None:
                        item = stripped
                        if item.startswith("- "):
                            item = item[2:]
                        item = item.strip().strip('"').strip("'")
                        if item:
                            cur = fm.get(current_key)
                            if isinstance(cur, list):
                                cur.append(item)
                            # 关键：已有标量值时跳过缩进行（不覆盖标量，
                            # 避免 title 被替换成 list 导致 get_title 返回 "['x']" 字面量）
                            # 标量值后的缩进续行属畸形 YAML，直接忽略
    return fm, body


def get_title(filepath: Path, fm: dict) -> str:
    """从 frontmatter、文件名、内容首行获取标题"""
    for key in ("title", "Title", "标题"):
        if key in fm and fm[key]:
            return str(fm[key])
    # 从文件名取
    stem = filepath.stem
    # 去掉 Obsidian wikilink 中的特殊字符
    return stem.replace("-", " ").replace("_", " ").strip()


def get_tags(fm: dict) -> list[str]:
    """从 frontmatter 提取标签"""
    tags = []
    for key in ("tags", "Tags", "tag", "标签"):
        val = fm.get(key)
        if isinstance(val, list):
            tags.extend(val)
        elif isinstance(val, str) and val.strip():
            tags.append(val.strip())
    return list(set(t for t in tags if t))


def extract_wikilinks(body: str) -> list[str]:
    """提取 [[Wikilink]] 引用"""
    return re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", body)


def extract_aliases(body: str) -> list[str]:
    """提取正文中的 alias: 标记"""
    aliases = []
    for match in re.findall(r"(?:^|\n)\s*alias(?:es)?:\s*(.+)$", body, re.MULTILINE):
        raw = match.strip()
        if raw.startswith("[") and raw.endswith("]"):
            try:
                aliases.extend(json.loads(raw))
            except json.JSONDecodeError:
                pass
        else:
            aliases.append(raw.strip('"').strip("'"))
    return aliases


class Note:
    """单篇笔记的完整信息"""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.rel_path = filepath.relative_to(VAULT_PATH).as_posix()
        self.stat = filepath.stat()
        self.mtime = datetime.fromtimestamp(self.stat.st_mtime, tz=timezone.utc)
        self.size = self.stat.st_size
        self.content_hash = self._hash_file()

        raw_text = filepath.read_text(encoding="utf-8", errors="replace")
        self.fm, self.body = parse_frontmatter(raw_text)
        self.title = get_title(filepath, self.fm)
        self.tags = get_tags(self.fm)
        self.wikilinks = extract_wikilinks(self.body)
        self.aliases = extract_aliases(raw_text)

        # 生成摘要（前 300 字）
        self.summary = self.body.strip()[:300].replace("\n", " ").strip()

    def _hash_file(self) -> str:
        h = hashlib.sha256()
        h.update(self.filepath.read_bytes())
        return h.hexdigest()

    def to_record(self) -> dict:
        return {
            "path": self.rel_path,
            "title": self.title,
            "content": self.body,
            "summary": self.summary,
            "tags": ",".join(self.tags),
            "mtime": self.mtime.isoformat(),
            "size": self.size,
            "hash": self.content_hash,
            "wikilinks": ",".join(self.wikilinks),
            "aliases": ",".join(self.aliases),
            "category": self.rel_path.split("/")[0] if "/" in self.rel_path else "root",
        }

    def should_index_chroma(self) -> bool:
        """Whether this note should be embedded into ChromaDB.

        SQLite FTS5 still indexes every note. ChromaDB is kept focused on
        structured/high-density knowledge to avoid long raw chat logs causing
        slow incremental backups and noisy semantic retrieval.
        """
        # 硬限制优先：超大文件/超长原文不索引（避免拖慢增量备份）
        if self.size > CHROMA_MAX_RAW_BYTES:
            return False
        if self.rel_path.startswith(CHROMA_PRIORITY_PREFIXES):
            return True
        if CHROMA_SKIP_RAW_CHAT_LOGS and self.rel_path.startswith(CHROMA_RAW_CHAT_PREFIXES):
            return False
        return True

    def to_chroma_text(self) -> str:
        """ChromaDB 用：含元数据的纯文本"""
        parts = [
            f"# {self.title}",
            f"Path: {self.rel_path}",
            f"Category: {self.rel_path.split('/')[0] if '/' in self.rel_path else 'root'}",
        ]
        if self.tags:
            parts.append(f"Tags: {', '.join(self.tags)}")
        parts.append("")
        parts.append(self.body)
        return "\n".join(parts)


# ── 状态跟踪（增量） ──────────────────────────────

def load_state() -> dict:
    """读取 state.json；损坏/截断时备份现场并安全降级为空（触发全量重扫）。"""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception as e:
            # 单点恢复：损坏文件改名保留，不影响下次备份
            try:
                corrupt = STATE_FILE.with_name(
                    f"state.json.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"
                )
                STATE_FILE.replace(corrupt)
                print(
                    f"⚠️ state.json 损坏（{e}），已改名备份为 {corrupt.name}，本轮全量重建",
                    file=sys.stderr,
                )
            except Exception:
                pass
            return {}
    return {}


def save_state(state: dict):
    """原子写：先写临时文件再 rename，避免进程中断产生半截 state.json。"""
    tmp = STATE_FILE.with_name("state.json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    tmp.replace(STATE_FILE)


def scan_vault() -> list[Note]:
    """扫描 vault 中所有 .md 文件，返回 Note 列表"""
    notes: list[Note] = []
    for md_file in sorted(VAULT_PATH.rglob("*.md")):
        # 跳过 .obsidian 配置目录
        if ".obsidian" in md_file.parts:
            continue
        notes.append(Note(md_file))
    return notes


def find_changed_notes(notes: list[Note], state: dict) -> tuple[list[Note], list[str], list[str]]:
    """
    返回 (新/改的笔记, 已删除的路径列表, 所有当前路径列表)
    """
    current_paths: set[str] = set()
    changed: list[Note] = []
    deleted: list[str] = []

    for note in notes:
        current_paths.add(note.rel_path)
        prev = state.get(note.rel_path)
        if prev is None or prev.get("hash") != note.content_hash:
            changed.append(note)

    # 找出已删除的文件
    for path in state:
        if path not in current_paths:
            deleted.append(path)

    return changed, deleted, sorted(current_paths)


# ── SQLite FTS5 ──────────────────────────────────────

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    path TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT,
    tags TEXT,
    mtime TEXT NOT NULL,
    size INTEGER DEFAULT 0,
    hash TEXT,
    wikilinks TEXT,
    aliases TEXT,
    category TEXT DEFAULT 'root',
    indexed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    title, content, summary, tags,
    content=notes,
    content_rowid=rowid,
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, title, content, summary, tags)
    VALUES (new.rowid, new.title, new.content, new.summary, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, content, summary, tags)
    VALUES ('delete', old.rowid, old.title, old.content, old.summary, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, content, summary, tags)
    VALUES ('delete', old.rowid, old.title, old.content, old.summary, old.tags);
    INSERT INTO notes_fts(rowid, title, content, summary, tags)
    VALUES (new.rowid, new.title, new.content, new.summary, new.tags);
END;
"""


def init_sqlite():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    # 用 executescript 一次性执行整个 schema（自动忽略已存在对象）
    conn.executescript(SQLITE_SCHEMA)
    conn.commit()
    return conn


def upsert_note_sqlite(conn, note: Note):
    conn.execute(
        """INSERT OR REPLACE INTO notes (path, title, content, summary, tags, mtime, size, hash, wikilinks, aliases, category)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            note.rel_path,
            note.title,
            note.body,
            note.summary,
            ",".join(note.tags),
            note.mtime.isoformat(),
            note.size,
            note.content_hash,
            ",".join(note.wikilinks),
            ",".join(note.aliases),
            note.rel_path.split("/")[0] if "/" in note.rel_path else "root",
        ),
    )
    conn.commit()


def delete_note_sqlite(conn, path: str):
    conn.execute("DELETE FROM notes WHERE path = ?", (path,))
    conn.commit()


def search_sqlite(query: str, limit: int = 10) -> list[dict]:
    """FTS5 全文搜索；无结果时 fallback LIKE（unicode61 分词对中文子串不友好）。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT n.path, n.title, n.summary, n.tags, n.mtime,
                      snippet(notes_fts, 1, '<mark>', '</mark>', '...', 30) AS excerpt
               FROM notes n
               JOIN notes_fts ON n.rowid = notes_fts.rowid
               WHERE notes_fts MATCH ? AND n.content != ''
               ORDER BY rank
               LIMIT ?""",
            (query, limit),
        ).fetchall()
        if rows:
            return [dict(r) for r in rows]
    except sqlite3.OperationalError as e:
        print(f"  [fts error] {e}", file=sys.stderr)

    # fallback：LIKE 子串匹配（中文等无空格语言的关键场景）
    like = f"%{query}%"
    rows = conn.execute(
        """SELECT path, title, summary, tags, mtime,
                  substr(content, 1, 200) AS excerpt
           FROM notes
           WHERE content LIKE ? OR title LIKE ?
           ORDER BY mtime DESC
           LIMIT ?""",
        (like, like, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ── ChromaDB（向量语义搜索） ─────────────────────────

# 延迟导入 chromadb（避免启动时就加载）
_chroma_client = None
_chroma_collection = None


def _get_chroma():
    global _chroma_client, _chroma_collection
    if _chroma_client is not None:
        return _chroma_collection

    try:
        import chromadb
    except ImportError:
        print("  [chromadb] NOT INSTALLED — pip install chromadb", file=sys.stderr)
        return None

    _chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    try:
        _chroma_collection = _chroma_client.get_collection("obsidian_notes")
    except Exception:
        # collection 不存在，创建它
        _chroma_collection = _chroma_client.create_collection(
            name="obsidian_notes",
            metadata={"hnsw:space": "cosine"},
        )
    return _chroma_collection


def upsert_note_chroma(note: Note):
    if not note.should_index_chroma():
        delete_note_chroma(note.rel_path)
        print(f"  [chroma] ⏭️  skipped raw/large note: {note.rel_path}", file=sys.stderr)
        return

    col = _get_chroma()
    if col is None:
        return

    text = note.to_chroma_text()
    metadata = {
        "path": note.rel_path,
        "title": note.title,
        "tags": ",".join(note.tags),
        "mtime": note.mtime.isoformat(),
        "category": note.rel_path.split("/")[0] if "/" in note.rel_path else "root",
    }

    try:
        col.upsert(
            ids=[note.rel_path],
            documents=[text],
            metadatas=[metadata],
        )
        print(f"  [chroma] ✅ upsert: {note.rel_path}", file=sys.stderr)
    except Exception as e:
        print(f"  [chroma] ⚠️  error upserting {note.rel_path}: {e}", file=sys.stderr)


def delete_note_chroma(path: str):
    col = _get_chroma()
    if col is None:
        return
    try:
        col.delete(ids=[path])
        print(f"  [chroma] 🗑️  deleted: {path}", file=sys.stderr)
    except Exception:
        pass


def search_chroma(query: str, limit: int = 10) -> list[dict]:
    """语义搜索"""
    col = _get_chroma()
    if col is None:
        return []
    try:
        results = col.query(query_texts=[query], n_results=limit)
        items = []
        if results["ids"]:
            for i, doc_id in enumerate(results["ids"][0]):
                items.append({
                    "path": doc_id,
                    "title": results["metadatas"][0][i].get("title", doc_id) if results["metadatas"] else doc_id,
                    "tags": results["metadatas"][0][i].get("tags", "") if results["metadatas"] else "",
                    "distance": results["distances"][0][i] if results["distances"] else 0,
                    "excerpt": (results["documents"][0][i] or "")[:200] if results["documents"] else "",
                })
        return items
    except Exception as e:
        print(f"  [chroma] search error: {e}", file=sys.stderr)
        return []


# ── 主流程 ──────────────────────────────────────────

def cmd_backup(full: bool = False, quiet: bool = False):
    """执行增量或全量备份"""
    if not VAULT_PATH.exists():
        print(f"❌ Obsidian vault 不存在: {VAULT_PATH}", file=sys.stderr)
        sys.exit(1)

    if not quiet:
        print(f"📂 Vault: {VAULT_PATH}")
        print(f"📦 SQLite: {DB_PATH} (FTS5 全文搜索)")
        print(f"📦 Chroma: {CHROMA_PATH} (向量语义搜索)")
        print(f"📋 State: {STATE_FILE}")
        print()

    # 1. 扫描笔记
    if not quiet:
        print("🔍 扫描 vault...")
    notes = scan_vault()
    if not quiet:
        print(f"   → 共 {len(notes)} 个笔记文件")

    # 2. 增量判断
    state = {} if full else load_state()
    if full:
        changed = notes
        deleted = []
        current_paths = [n.rel_path for n in notes]
    else:
        changed, deleted, current_paths = find_changed_notes(notes, state)

    if not quiet:
        print(f"   → 新增/修改: {len(changed)} 个")
        print(f"   → 已删除: {len(deleted)} 个")
        print()

    if not changed and not deleted:
        if not quiet:
            print("✅ 无变更，无需备份")
        return

    # 3. SQLite 备份
    if not quiet:
        print("📝 SQLite FTS5 写入...")
    conn = init_sqlite()
    for note in changed:
        upsert_note_sqlite(conn, note)
        if not quiet:
            print(f"  ✅ {note.rel_path}")
    for path in deleted:
        delete_note_sqlite(conn, path)
        if not quiet:
            print(f"  🗑️  {path}")
    conn.close()
    if not quiet:
        print()

    # 4. ChromaDB 备份
    if not quiet:
        print("🧠 ChromaDB 向量写入...")
    if not CHROMA_ENABLED:
        if not quiet:
            print("  [skipped] OBSIDIAN_CHROMA_ENABLED=0\n")
    else:
        col = _get_chroma()
        if col is not None:
            for note in changed:
                upsert_note_chroma(note)
            for path in deleted:
                delete_note_chroma(path)
            if not quiet:
                print()
        else:
            if not quiet:
                print("  [skipped] chromadb 未安装\n")

    # 5. 保存状态
    new_state = {}
    for note in notes:
        new_state[note.rel_path] = {
            "hash": note.content_hash,
            "mtime": note.mtime.isoformat(),
            "title": note.title,
        }
    save_state(new_state)

    if not quiet:
        print(f"✅ 备份完成！共处理 {len(changed)} 条变更")
        print(f"   数据库总记录: {len(new_state)} 条")


def cmd_stats():
    """查看库统计"""
    notes = scan_vault()
    total_notes = len(notes)
    total_size = sum(n.size for n in notes)
    category_count: dict[str, int] = {}
    tag_count: dict[str, int] = {}
    for n in notes:
        cat = n.rel_path.split("/")[0] if "/" in n.rel_path else "root"
        category_count[cat] = category_count.get(cat, 0) + 1
        for t in n.tags:
            tag_count[t] = tag_count.get(t, 0) + 1

    # DB 统计
    db_count = 0
    db_size = 0
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH))
        db_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        conn.close()
        db_size = DB_PATH.stat().st_size

    print(f"📊 Obsidian Vault 统计")
    print(f"{'='*50}")
    print(f"📁 Vault: {VAULT_PATH}")
    print(f"📄 笔记总量: {total_notes}")
    print(f"💾 原始大小: {total_size/1024:.1f} KB")
    print()
    print(f"📂 按目录:")
    for cat, count in sorted(category_count.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count} 篇")
    print()
    print(f"🏷️  热门标签 (Top 10):")
    for tag, count in sorted(tag_count.items(), key=lambda x: -x[1])[:10]:
        print(f"  #{tag}: {count}")
    print()
    print(f"🗄️  SQLite 数据库: {DB_PATH}")
    print(f"   记录数: {db_count} 篇")
    print(f"   大小: {db_size/1024:.1f} KB")
    chroma_exist = (CHROMA_PATH / "chroma.sqlite3").exists()
    print(f"🧠 ChromaDB 数据库: {'✅ 存在' if chroma_exist else '❌ 未初始化'}")
    state_count = len(load_state())
    print(f"📋 状态跟踪: {state_count} 篇")


def cmd_search(query: str, semantic: bool = False):
    """搜索笔记"""
    if not DB_PATH.exists():
        print("❌ 数据库不存在，请先运行备份")
        return

    if semantic:
        print(f"🔍 语义搜索: {query}")
        print("=" * 50)
        results = search_chroma(query)
        if not results:
            print("  无结果")
        for r in results:
            print(f"\n📄 {r['title']}")
            print(f"  路径: {r['path']}")
            print(f"  标签: {r['tags']}")
            print(f"  相似度: {1 - r['distance']:.3f}")
            print(f"  摘要: {r['excerpt'][:150]}...")
    else:
        print(f"🔍 FTS5 搜索: {query}")
        print("=" * 50)
        results = search_sqlite(query)
        if not results:
            print("  无结果")
        for r in results:
            print(f"\n📄 {r['title']}")
            print(f"  路径: {r['path']}")
            print(f"  标签: {r['tags']}")
            print(f"  时间: {r['mtime']}")
            print(f"  片段: {r.get('excerpt', r['summary'][:200])}")


# ── CLI 入口 ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Obsidian Vault 增量双备份管道 (SQLite FTS5 + ChromaDB)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 obsidian_backup.py               # 增量备份（只处理新/改过的）
  python3 obsidian_backup.py --full         # 全量重建
  python3 obsidian_backup.py --stats        # 查看统计
  python3 obsidian_backup.py --search "部署" # FTS5 搜索
  python3 obsidian_backup.py --search "部署" --semantic  # 语义搜索
        """,
    )

    parser.add_argument("--full", action="store_true", help="全量重建数据库")
    parser.add_argument("--quiet", action="store_true", help="安静模式，仅输出错误")
    parser.add_argument("--stats", action="store_true", help="显示 vault 统计")
    parser.add_argument("--search", type=str, help="搜索笔记内容")
    parser.add_argument("--semantic", action="store_true", help="语义搜索（ChromaDB）")
    parser.add_argument("--limit", type=int, default=10, help="搜索结果数量")

    args = parser.parse_args()

    if args.stats:
        cmd_stats()
    elif args.search:
        cmd_search(args.search, semantic=args.semantic)
    else:
        cmd_backup(full=args.full, quiet=args.quiet)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
