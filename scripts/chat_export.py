#!/usr/bin/env python3
"""
Hermes 对话导出 → Obsidian（Codex 风格）

参照 Codex 的 export_codex_chat_logs.py 模式：
- 输出到 Hermes/Chat Logs/2026/YYYY-MM-DD.md（按日）
- 过滤掉 system 消息、tool calls、tool results、调试噪声
- 保留完整的用户消息和助手消息（不截断）
- 增量同步（不重复导出）
- 单文件超过 2MB 自动滚动到 -02.md

用法:
  python3 chat_export.py                     # 导出所有 Profile
  python3 chat_export.py --profile default   # 只导出 default
  python3 chat_export.py --list              # 查看导出状态
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

IS_MAC = sys.platform == "darwin"
if IS_MAC:
    VAULT = Path(os.environ.get(
        "OBSIDIAN_VAULT_PATH",
        str(Path.home() / "Documents/ObsidianVault"),
    ))
    HERMES_HOME = Path.home() / ".hermes"
else:
    VAULT = Path(os.environ.get("OBSIDIAN_VAULT_PATH", str(Path.home() / "obsidian")))
    HERMES_HOME = Path.home() / ".hermes"

CHAT_LOGS = VAULT / "Hermes" / "Chat Logs"
STATE_FILE = HERMES_HOME / "data" / "obsidian" / "chat_export_state.json"
SEEN_HASHES_FILE = HERMES_HOME / "data" / "obsidian" / "chat_export_seen.json"
TZ = ZoneInfo("Asia/Shanghai")

MAX_NOTE_BYTES = 2 * 1024 * 1024
SEEN_LIMIT = 50_000

HERMES_HOME.mkdir(parents=True, exist_ok=True)
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def discover_profiles():
    profiles = ["default"]
    profiles_dir = HERMES_HOME / "profiles"
    if profiles_dir.exists():
        for d in sorted(profiles_dir.iterdir()):
            if d.is_dir() and (d / "config.yaml").exists():
                profiles.append(d.name)
    return profiles


def get_profile_db(profile):
    if profile == "default":
        return HERMES_HOME / "state.db"
    return HERMES_HOME / "profiles" / profile / "state.db"


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def msg_hash(msg):
    """Stable hash for dedup"""
    raw = f'{msg["role"]}:{msg["ts"]}:{msg["content"][:200]}'
    return hashlib.md5(raw.encode()).hexdigest()


# ── 噪声过滤 ──

NOISE_PATTERNS = [
    # System model-change notifications
    r'^\[System:.*model.*has changed.*\]',
    r'^\[System:.*provider.*\]',
    # Context warnings
    r'^--- Context Warnings',
    r'^- @file:.*file not found',
    r'^- @url:.*no content extracted',
    # Out-of-band markers (keep content, strip marker)
    # (handled separately)
]


def is_noise(content):
    """Check if a message is pure noise that should be skipped entirely"""
    stripped = content.strip()
    if not stripped:
        return True

    # Skip tool calls / tool results
    if stripped.startswith('{"tool_calls"'):
        return True
    if stripped.startswith('[{"type":'):
        return True
    if stripped.startswith('{"type":'):
        return True

    # Skip system notifications
    for pattern in NOISE_PATTERNS:
        if re.match(pattern, stripped):
            return True

    # Skip if it's ONLY a system notification with nothing else
    if stripped.startswith('[System:') and len(stripped) < 200:
        return True

    return False


def redact_for_raw_log(text, source="hermes"):
    """Store detected secrets in macOS Keychain and replace with SecretRefs."""
    try:
        scripts_dir = Path(__file__).resolve().parent
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from redact_secrets import redact_text  # type: ignore
        return redact_text(text, source=source, store=True)
    except Exception:
        # Export must not fail because secret redaction is unavailable.
        # The daily distiller still treats Wiki/Lessons as no-plaintext zones.
        return text


def clean_content(content):
    """Remove inline noise markers, clean up content"""
    # Remove OUT-OF-BAND markers but keep the content
    content = re.sub(
        r'\[OUT-OF-BAND USER MESSAGE.*?\n(.*?)\n\[/OUT-OF-BAND USER MESSAGE\]',
        r'\1',
        content,
        flags=re.DOTALL,
    )
    # Remove context warnings blocks
    content = re.sub(r'\n--- Context Warnings ---.*?(?=\n\n|\Z)', '', content, flags=re.DOTALL)
    # Remove @file/@url not-found warnings
    content = re.sub(r'- @file:`[^`]+`: file not found\n?', '', content)
    content = re.sub(r'- @url:`[^`]+`: no content extracted\n?', '', content)

    return content.strip()


def load_messages(db_path, since_ts=0):
    """Load messages from state.db"""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    messages = []
    try:
        rows = conn.execute(
            """SELECT id, session_id, role, content, created_at
               FROM messages
               WHERE created_at > ? AND role IN ('user', 'assistant')
               ORDER BY created_at ASC""",
            (since_ts,),
        ).fetchall()
        for r in rows:
            content = r["content"] or ""
            if is_noise(content):
                continue
            content = clean_content(content)
            if not content.strip():
                continue
            messages.append({
                "id": r["id"],
                "session_id": r["session_id"],
                "role": r["role"],
                "content": content,
                "ts": r["created_at"],
            })
    except sqlite3.OperationalError:
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [t["name"] for t in tables]
            messages = _try_alt_schema(conn, table_names, since_ts)
        except Exception:
            pass
    finally:
        conn.close()
    return messages


def _try_alt_schema(conn, table_names, since_ts):
    messages = []
    for tname in ["messages", "chat_messages", "conversation_messages"]:
        if tname not in table_names:
            continue
        try:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tname})").fetchall()]
            role_col = "role" if "role" in cols else cols[2] if len(cols) > 2 else "role"
            content_col = "content" if "content" in cols else "text"
            ts_col = "created_at" if "created_at" in cols else ("ts" if "ts" in cols else "timestamp")
            id_col = "id" if "id" in cols else cols[0]
            rows = conn.execute(
                f"SELECT {id_col}, {role_col}, {content_col}, {ts_col} FROM {tname} "
                f"WHERE {ts_col} > ? AND {role_col} IN ('user', 'assistant') ORDER BY {ts_col} ASC",
                (since_ts,),
            ).fetchall()
            for r in rows:
                content = r[2] or ""
                if is_noise(content):
                    continue
                content = clean_content(content)
                if not content.strip():
                    continue
                messages.append({
                    "id": r[0], "role": r[1], "content": content, "ts": r[3],
                })
            break
        except Exception:
            continue
    return messages


def ts_to_dt(ts):
    try:
        ts_float = float(ts)
        if ts_float > 1e12:
            ts_float /= 1000
        return dt.datetime.fromtimestamp(ts_float, tz=TZ)
    except (ValueError, TypeError):
        return dt.datetime.now(tz=TZ)


def _convert_image_refs(content: str) -> str:
    """把微信图片缓存路径转成 Obsidian 图片嵌入。

    微信图片落盘到 vault/assets/weixin（通过 cache/images 软链）。消息
    content 里图片路径出现在两种位置：
    1. `vision_analyze with image_url: /path ~`（模型提示词里）
    2. `[The user sent an image~ ...]`（vision 描述，不含路径）
    这里把含缓存路径的片段重写为 assets/weixin 相对路径，让 Obsidian 和
    蒸馏（vision）都能看到图片。
    """
    def _repl(m):
        full = m.group(0)
        path = full.split("image_url:", 1)[1].strip()
        fname = path.rsplit("/", 1)[-1]
        # 生成 Obsidian wikilink 嵌入，Obsidian 里直接显示图片
        return "![[assets/weixin/%s]]" % fname
    return re.sub(r"image_url: /[^\s~]+", _repl, content)


def render_message(msg):
    """Render a single message as markdown"""
    d = ts_to_dt(msg["ts"])
    time_str = d.strftime("%H:%M:%S")
    role_label = "🧑 用户" if msg["role"] == "user" else "🤖 助手"

    lines = [
        f"## {time_str} {role_label}",
        "",
    ]

    content = redact_for_raw_log(
        msg["content"],
        source=f"Hermes session={msg.get('session_id', '')} id={msg.get('id', '')}",
    )

    # 把图片缓存路径转成 Obsidian 图片嵌入（微信图片已落盘到 assets/weixin）
    content = _convert_image_refs(content)

    # User messages: blockquote
    if msg["role"] == "user":
        for line in content.splitlines():
            lines.append(f"> {line}" if line.strip() else ">")
    else:
        # Assistant: full content, no truncation
        lines.append(content)

    lines.append("")
    return "\n".join(lines)


def find_rollover_filepath(base_path, date_str):
    """Find the next available file path for rollover (date-02.md, etc.)"""
    filepath = base_path / f"{date_str}.md"
    if not filepath.exists():
        return filepath
    seq = 2
    while True:
        filepath = base_path / f"{date_str}-{seq:02d}.md"
        if not filepath.exists() or filepath.stat().st_size < MAX_NOTE_BYTES:
            return filepath
        seq += 1


def append_to_chat_log(profile, msgs):
    """Append messages to chat log files, grouped by date"""
    written = 0
    by_date = {}
    for m in msgs:
        d = ts_to_dt(m["ts"])
        date_str = d.strftime("%Y-%m-%d")
        by_date.setdefault(date_str, []).append(m)

    year_dir = CHAT_LOGS / "2026"
    year_dir.mkdir(parents=True, exist_ok=True)

    for date_str, day_msgs in by_date.items():
        filepath = find_rollover_filepath(year_dir, date_str)
        is_new = not filepath.exists() or filepath.stat().st_size == 0

        new_lines = []
        if is_new:
            new_lines.extend([
                "---",
                f"source: hermes-{profile}",
                "type: daily-chat-log",
                f"date: {date_str}",
                "tags:",
                "  - hermes",
                "  - chat-log",
                f"  - profile-{profile}",
                "---",
                "",
                f"# Hermes 聊天记录 {date_str}",
                "",
            ])

        for m in day_msgs:
            rendered = render_message(m)
            # Check if adding this would exceed max size
            current_size = filepath.stat().st_size if filepath.exists() else 0
            rendered_size = len(rendered.encode("utf-8"))
            if current_size + rendered_size > MAX_NOTE_BYTES and current_size > 0:
                # Rollover to next file
                filepath = find_rollover_filepath(year_dir, date_str)
                new_lines.extend([
                    "---",
                    f"source: hermes-{profile}",
                    "type: daily-chat-log",
                    f"date: {date_str}",
                    "tags:",
                    "  - hermes",
                    "  - chat-log",
                    f"  - profile-{profile}",
                    "---",
                    "",
                    f"# Hermes 聊天记录 {date_str}（续）",
                    "",
                ])
            new_lines.append(rendered)

        mode = "a" if filepath.exists() and filepath.stat().st_size > 0 else "w"
        with open(filepath, mode, encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")

        written += len(day_msgs)

    return written


def sync_to_server():
    if not IS_MAC:
        return
    try:
        import subprocess
        server_user = os.environ.get("SERVER_USER", "")
        server_host = os.environ.get("SERVER_HOSTNAME", "")
        server_vault = os.environ.get("OBSIDIAN_VAULT_PATH", str(Path.home() / "obsidian"))
        if not server_user or not server_host:
            return
        subprocess.run(
            ["rsync", "-q", "--update",
             str(CHAT_LOGS) + "/",
             f"{server_user}@{server_host}:{server_vault}/Hermes/Chat Logs/"],
            capture_output=True, timeout=30,
        )
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="导出 Hermes 对话到 Obsidian Hermes/Chat Logs")
    parser.add_argument("--profile", help="只导出指定 Profile")
    parser.add_argument("--list", action="store_true", help="查看导出状态")
    args = parser.parse_args()

    if args.list:
        state = load_json(STATE_FILE, {})
        if not state:
            print("无导出记录")
        for profile, info in sorted(state.items()):
            print(f"  {profile:15s} last_id={info.get('last_id', '?')} msgs_exported={info.get('count', 0)}")
        return

    profiles = discover_profiles()
    if args.profile:
        profiles = [p for p in profiles if p == args.profile]
        if not profiles:
            print(f"Profile '{args.profile}' 不存在")
            return 1

    state = load_json(STATE_FILE, {})
    seen_hashes = set(load_json(SEEN_HASHES_FILE, []))
    total_written = 0

    for profile in profiles:
        db_path = get_profile_db(profile)
        if not db_path.exists():
            continue

        last_id = state.get(profile, {}).get("last_id", 0)
        msgs = load_messages(db_path, since_ts=0)

        # Dedup by hash + filter by last_id
        new_msgs = []
        for m in msgs:
            if m["id"] <= last_id:
                continue
            h = msg_hash(m)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            new_msgs.append(m)

        if not new_msgs:
            continue

        written = append_to_chat_log(profile, new_msgs)

        max_id = max(m["id"] for m in new_msgs)
        prev_count = state.get(profile, {}).get("count", 0)
        state[profile] = {"last_id": max_id, "count": prev_count + written}

        print(f"✅ {profile:15s} +{written} 条 → Hermes/Chat Logs/")
        total_written += written

    # Trim seen hashes
    seen_list = sorted(seen_hashes)[-SEEN_LIMIT:]
    save_json(SEEN_HASHES_FILE, seen_list)
    save_json(STATE_FILE, state)

    if total_written > 0:
        sync_to_server()
        print(f"\n📦 共导出 {total_written} 条消息，已同步到服务器")
    else:
        print("无新消息")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
