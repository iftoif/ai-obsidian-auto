#!/usr/bin/env python3
"""Export Claude Code and Pi readable chat logs into the Obsidian vault.

This is the Raw Exporter layer for the unified AI-chat ingestion pipeline.
It intentionally keeps only readable user/assistant text plus provenance, and
skips system events, tool payloads, attachments, hidden/internal noise.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("TZ", "Asia/Shanghai"))
MAX_NOTE_BYTES = 2 * 1024 * 1024
SEEN_LIMIT = 80_000


def default_vault() -> Path:
    # 优先环境变量 OBSIDIAN_VAULT_PATH；未配置时回退 ~/obsidian
    # （iCloud 用户可在 .env 中显式指定 Mac 上的 iCloud 路径）
    return Path(os.environ.get("OBSIDIAN_VAULT_PATH", str(Path.home() / "obsidian")))


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_time(value: Any) -> dt.datetime:
    if isinstance(value, (int, float)):
        ts = float(value)
        # 按量级归一化到秒：微秒(>1e15) /1e6，毫秒(>1e12) /1e3，
        # 极大值直接 clamp 到可解析范围（异常时间戳不丢消息，用当前时间兜底）
        if ts > 1e15:
            ts /= 1e6
        elif ts > 1e12:
            ts /= 1000
        # 负数或超出合理范围（>2096 年）→ 脏数据，兜底当前时间
        if ts < 0 or ts > 4_000_000_000:
            return dt.datetime.now(TZ)
        try:
            return dt.datetime.fromtimestamp(ts, TZ)
        except (ValueError, OverflowError, OSError):
            return dt.datetime.now(TZ)
    if isinstance(value, str) and value:
        try:
            s = value.replace("Z", "+00:00")
            d = dt.datetime.fromisoformat(s)
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
            return d.astimezone(TZ)
        except Exception:
            pass
    return dt.datetime.now(TZ)


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<environment_context>.*?</environment_context>", "", text, flags=re.DOTALL)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def safe(value: str) -> str:
    return value.replace("\\", "\\\\").replace("`", "\\`")


def redact_for_raw_log(text: str, source: str) -> tuple[str, bool]:
    """Store detected secrets in macOS Keychain and replace with SecretRefs.

    返回 (text, ok)：ok=False 表示脱敏不可用（fail-closed），调用方
    不应标记为已导出（下次重试）。用元组显式信号，不用文本嗅探。
    """
    try:
        scripts_dir = Path(__file__).resolve().parent
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from redact_secrets import redact_text  # type: ignore
        return redact_text(text, source=source, store=True), True
    except Exception as e:
        # fail-closed：脱敏不可用时绝不把可能含密钥的原文写进 Raw
        print(f"⚠️ redact_for_raw_log 失败（{e}），消息以 [REDACT-UNAVAILABLE] 标记",
              file=sys.stderr)
        return "[REDACT-UNAVAILABLE]（脱敏不可用，原文未写入 Raw）", False


def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return normalize_text(content)
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        typ = item.get("type")
        # Keep only human-readable text. Skip tool_use/tool_result/images/attachments.
        if typ in {"tool_use", "tool_result", "image", "image_url", "input_image"}:
            continue
        text = item.get("text") or item.get("input_text") or item.get("output_text")
        if isinstance(text, str):
            parts.append(text)
    return normalize_text("\n\n".join(parts))


# ── 图片落盘 ──
_IMAGE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}


def _iter_images_from_content(content: Any) -> list[tuple[str, str]]:
    """从 content 里提取图片 (mime_type, base64)。兼容 Claude 和 Pi 两种格式。

    Claude: {type: image, source: {type: base64, media_type, data}}
    Pi:     {type: image, data, mimeType}
    """
    if not isinstance(content, list):
        return []
    images: list[tuple[str, str]] = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "image":
            continue
        # Claude 格式
        source = item.get("source")
        if isinstance(source, dict):
            data = source.get("data") or ""
            mime = source.get("media_type") or source.get("mediaType") or "image/png"
            if isinstance(data, str) and data:
                images.append((mime, data))
            continue
        # Pi 格式
        data = item.get("data") or ""
        mime = item.get("mimeType") or item.get("mime_type") or "image/png"
        if isinstance(data, str) and data:
            images.append((mime, data))
    return images


def _extract_image_refs(source, line_no, vault, tool, ts, session, line_cache=None) -> list[str]:
    """从明文 jsonl 源文件取指定行内容，提取图片并落盘（DSH 等二进制源不适用）。

    line_cache: {source_path: {line_no: line_text}}，由调用方缓存整文件内容，
    避免每条消息都重读整个源文件（O(n²) → O(n)）。
    """
    refs: list[str] = []
    try:
        _line = None
        if line_cache is not None and source in line_cache:
            _line = line_cache[source].get(line_no)
        else:
            with source.open(encoding="utf-8", errors="replace") as _fh:
                for _i, _l in enumerate(_fh, 1):
                    if _i == line_no:
                        _line = _l
                        break
        if _line is None:
            return refs
        _obj = json.loads(_line)
        _msg = _obj.get("message") if isinstance(_obj.get("message"), dict) else {}
        _imgs = _iter_images_from_content(_msg.get("content"))
        for _seq, (_mime, _data) in enumerate(_imgs, start=1):
            _link = save_image_to_assets(vault, tool, ts.date(), session, _data, _mime, _seq, line_no)
            if _link:
                refs.append(_link)
    except Exception:
        pass
    return refs


def save_image_to_assets(
    vault: Path,
    tool: str,
    day: dt.date,
    session: str,
    image_b64: str,
    mime_type: str,
    seq: int,
    line_no: int = 0,
) -> str | None:
    """把 base64 图片解码保存到 {tool}/Chat Logs/assets/，返回 Obsidian wikilink。

    fname 含 line_no：同一会话多条消息各带图片时不会互相覆盖
    （seq 只是单条消息内的图片序号，不含行号会导致后写覆盖先写）。
    """
    if not image_b64:
        return None
    try:
        raw = base64.b64decode(image_b64)
    except Exception:
        return None
    if len(raw) < 64:
        return None
    ext = _IMAGE_EXT.get(mime_type or "", ".png")
    safe_session = re.sub(r"[^A-Za-z0-9._-]", "-", session)[:40]
    assets_dir = vault / tool / "Chat Logs" / "assets" / day.isoformat()
    assets_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{safe_session}-{line_no:06d}-{seq:02d}{ext}"
    fpath = assets_dir / fname
    fpath.write_bytes(raw)
    rel = fpath.relative_to(vault)
    return f"![[{rel.as_posix()}]]"


def is_low_value(text: str) -> bool:
    s = text.strip()
    if not s:
        return True
    if s.startswith("<local-command-stdout>") or s.startswith("<command-name>"):
        return True
    if s in {"hi", "hello", "say hi"}:
        # Still export short greetings? For Raw logs, skip obvious smoke tests.
        return True
    return False


def note_path(vault: Path, tool: str, day: dt.date, part: int) -> Path:
    name = f"{day.isoformat()}.md" if part == 1 else f"{day.isoformat()}-{part:02d}.md"
    return vault / tool / "Chat Logs" / f"{day:%Y}" / name


def ensure_note(path: Path, tool: str, day: dt.date) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"source: {tool.lower()}\n"
        "type: daily-chat-log\n"
        f"date: {day.isoformat()}\n"
        "tags:\n"
        f"  - {tool.lower().replace(' ', '-')}\n"
        "  - chat-log\n"
        "---\n\n"
        f"# {tool} 聊天记录 {day.isoformat()}\n\n",
        encoding="utf-8",
    )


def init_roll(vault: Path, tool: str) -> dict[str, dict[str, int]]:
    base = vault / tool / "Chat Logs"
    roll: dict[str, dict[str, int]] = {}
    if not base.exists():
        return roll
    pat = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-(\d{2}))?\.md$")
    by_day: dict[str, list[tuple[int, Path]]] = {}
    for md in base.rglob("*.md"):
        m = pat.match(md.name)
        if not m:
            continue
        part = int(m.group(2)) if m.group(2) else 1
        by_day.setdefault(m.group(1), []).append((part, md))
    for day, items in by_day.items():
        items.sort()
        part, p = items[-1]
        roll[day] = {"part": part, "size": p.stat().st_size if p.exists() else 0}
    return roll


def event_hash(tool: str, session: str, role: str, text: str, line_no: int | None = None) -> str:
    # 含行号：同一 session 内两条完全相同文本但不同位置的消息都会被保留
    # （不含行号时第二条被当作重复吞掉——信息丢失）
    key = f"{tool}|{session}|{role}|{line_no if line_no is not None else ''}|{text}"
    return hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()


def append_entry(vault: Path, tool: str, roll: dict[str, dict[str, int]], ts: dt.datetime, role: str, text: str, source: Path, line_no: int, session: str, cwd: str) -> bool:
    day = ts.date()
    day_s = day.isoformat()
    st = roll.setdefault(day_s, {"part": 1, "size": 0})
    label = "用户" if role == "user" else "助手"
    body = (
        f"## {ts:%H:%M:%S} {label}\n\n"
        f"> session: `{safe(session)}`  \n"
        f"> source: `{safe(str(source))}:{line_no}`"
    )
    if cwd:
        body += f"  \n> cwd: `{safe(cwd)}`"
    text, redact_ok = redact_for_raw_log(text, source=f"{tool} session={session} {source}:{line_no}")
    body += "\n\n" + text.strip() + "\n\n"
    b = len(body.encode("utf-8"))
    # 滚动：当前文件已有内容且追加后超限，或单条消息本身就超限（避免单文件无限膨胀）
    if (st["size"] > 0 and st["size"] + b > MAX_NOTE_BYTES) or (st["size"] == 0 and b > MAX_NOTE_BYTES):
        st["part"] += 1
        st["size"] = 0
    p = note_path(vault, tool, day, st["part"])
    ensure_note(p, tool, day)
    with p.open("a", encoding="utf-8") as h:
        h.write(body)
    st["size"] += b
    return redact_ok


def _resolve_client_dir(home: Path, env_var: str, default_rel: str, probe: str, name_hint: str = "") -> Path:
    """自动发现客户端数据目录，支持任意换目录（不设环境变量也能发现）。

    客户端卸载重装、换目录后，数据目录可能不在默认位置。
    按优先级：
      1. 环境变量（CLAUDE_CONFIG_DIR / CODEX_HOME 等）
      2. 默认位置（~/.claude 等）
      3. 扫描 home 下所有一级目录，识别有 probe 子目录特征的
         （优先目录名含 name_hint 的，否则取最近修改的）
    返回找到的目录；找不到则回退默认。
    """
    # 1. 环境变量
    env_val = os.environ.get(env_var, "").strip()
    if env_val:
        p = Path(env_val).expanduser()
        if (p / probe).exists():
            return p
    # 2. 默认位置
    default = home / default_rel
    if (default / probe).exists():
        return default
    # 3. 扫描 home 下所有一级目录，找有 probe 特征的（支持任意换目录）
    candidates: list[Path] = []
    try:
        for d in home.iterdir():
            if not d.is_dir():
                continue
            # 跳过隐藏目录（除默认位置外）和明显无关的系统目录
            if d.name.startswith(".") and d.name not in {default_rel, default_rel.lstrip(".")}:
                continue
            try:
                if (d / probe).exists():
                    candidates.append(d)
            except OSError:
                continue
    except OSError:
        pass
    if candidates:
        # 优先目录名含 name_hint 的（如 claude/codex/pi）
        if name_hint:
            for d in candidates:
                if name_hint in d.name.lower():
                    return d
        # 否则取最近修改的（最可能是当前活跃的）
        try:
            return max(candidates, key=lambda p: p.stat().st_mtime)
        except OSError:
            return candidates[0]
    # 4. 回退默认（即使不存在，保持向后兼容）
    return default


def claude_records(home: Path) -> Iterable[tuple[Path, int, dt.datetime, str, str, str, str]]:
    claude_dir = _resolve_client_dir(home, "CLAUDE_CONFIG_DIR", ".claude", "projects", name_hint="claude")
    for path in sorted((claude_dir / "projects").rglob("*.jsonl")):
        with path.open(encoding="utf-8", errors="replace") as h:
            for line_no, line in enumerate(h, 1):
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                typ = obj.get("type")
                if typ not in {"user", "assistant"}:
                    continue
                msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
                role = msg.get("role") or typ
                if role not in {"user", "assistant"}:
                    continue
                text = text_from_content(msg.get("content"))
                if is_low_value(text):
                    continue
                yield path, line_no, parse_time(obj.get("timestamp")), role, text, str(obj.get("sessionId") or path.stem), str(obj.get("cwd") or "")


def pi_records(home: Path) -> Iterable[tuple[Path, int, dt.datetime, str, str, str, str]]:
    pi_dir = _resolve_client_dir(home, "PI_HOME", ".pi", "agent/sessions", name_hint="pi")
    for path in sorted((pi_dir / "agent" / "sessions").rglob("*.jsonl")):
        session = path.stem.split("_")[-1]
        cwd = ""
        with path.open(encoding="utf-8", errors="replace") as h:
            for line_no, line in enumerate(h, 1):
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") == "session":
                    session = str(obj.get("id") or session)
                    cwd = str(obj.get("cwd") or cwd)
                    continue
                if obj.get("type") != "message" or not isinstance(obj.get("message"), dict):
                    continue
                msg = obj["message"]
                role = msg.get("role")
                if role not in {"user", "assistant"}:
                    continue
                text = text_from_content(msg.get("content"))
                if is_low_value(text):
                    continue
                yield path, line_no, parse_time(obj.get("timestamp") or msg.get("timestamp")), role, text, session, cwd


def dsh_text_from_content(content: Any) -> str:
    """DSH content 只保留可读 text 块（跳过 reasoning / tool-call / tool-result）。"""
    if isinstance(content, str):
        return normalize_text(content)
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        t = item.get("text")
        if isinstance(t, str):
            parts.append(t)
    return normalize_text("\n\n".join(parts))


def dsh_records(home: Path) -> Iterable[tuple[Path, int, dt.datetime, str, str, str, str]]:
    """DeepSeek Harness (DSH) 会话 → Raw 记录。

    DSH 会话存储在 ~/.dsh/sessions/<cwd-hash>/session-<id>/session.jsonl.zstd
    （zstd 压缩 jsonl，需 zstandard 库流式解压）。核心行类型：
      - session:       {id, cwd, createdAt}
      - user/message:      {time, data:{content, role, id}}
      - assistant/message: {time, data:{turn, step, message:{role, content}}}
    content 元素 type 含 text / reasoning / tool-call / tool-result，只保留 text。
    """
    try:
        import zstandard  # type: ignore
    except ImportError:
        print("⚠️ zstandard 未安装，跳过 DSH 导出")
        return
    dsh_dir = _resolve_client_dir(home, "DSH_HOME", ".dsh", "sessions", name_hint="dsh")
    if not dsh_dir.exists():
        return
    for path in sorted(dsh_dir.rglob("session.jsonl.zstd")):
        session = path.parent.name  # session-<uuid>
        cwd = ""
        # 流式逐行解压：避免大会话文件全量读入内存（OOM 防护）
        try:
            fh = path.open("rb")
            reader = zstandard.ZstdDecompressor().stream_reader(fh)
            text_io = io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
        except Exception:
            continue
        try:
            try:
                for line_no, line in enumerate(text_io, 1):
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    typ = obj.get("type")
                    if typ == "session":
                        session = str(obj.get("id") or session)
                        cwd = str(obj.get("cwd") or cwd)
                        continue
                    if typ not in {"user/message", "assistant/message"}:
                        continue
                    d = obj.get("data") if isinstance(obj.get("data"), dict) else {}
                    msg = d.get("message") if isinstance(d.get("message"), dict) else {}
                    role = msg.get("role") or d.get("role")
                    if role not in {"user", "assistant"}:
                        continue
                    # 过滤插件/系统注入的 user 消息（runtime context、system-reminder、policy 快照等）
                    src = d.get("source") if isinstance(d.get("source"), dict) else {}
                    if role == "user" and src.get("kind") not in (None, "user"):
                        continue
                    content = msg.get("content") if msg else d.get("content")
                    text = dsh_text_from_content(content)
                    if is_low_value(text):
                        continue
                    ts = parse_time(obj.get("time") or d.get("time"))
                    yield path, line_no, ts, role, text, session, cwd
            except Exception:
                # 损坏/截断的 zstd 文件：跳过该文件，不中断整批导出
                continue
        finally:
            text_io.close()
            fh.close()


def export_tool(tool: str, vault: Path, state_dir: Path) -> tuple[int, int, int]:
    home = Path.home()
    if tool == "Claude":
        records = claude_records(home)
    elif tool == "Pi":
        records = pi_records(home)
    elif tool == "DSH":
        records = dsh_records(home)
    else:
        records = ()
    seen_path = state_dir / f"{tool.lower()}_chat_export_seen.json"
    seen: list[str] = load_json(seen_path, [])
    seen_set = set(seen)
    roll = init_roll(vault, tool)
    files_seen: set[str] = set()
    changed: set[Path] = set()
    exported = 0
    # 图片重读的行缓存：按源文件惰性缓存全部行，避免每条消息 O(n) 重读（O(n²)→O(n)）
    line_cache: dict[Path, dict[int, str]] = {}
    for source, line_no, ts, role, text, session, cwd in records:
        files_seen.add(str(source))
        h = event_hash(tool, session, role, text, line_no)
        if h in seen_set:
            continue
        # 提取图片：重新读原始行，落盘到 assets 并追加引用。
        # DSH 源文件是 zstd 压缩二进制，open(utf-8) 读出来是垃圾，跳过图片重读
        # （DSH 的图片引用由导出层另行处理，不影响文本内容导出）。
        image_refs: list[str] = []
        if tool != "DSH":
            # 惰性填充该源文件的行缓存（每个文件只读一次，O(n²)→O(n)）
            if source not in line_cache:
                try:
                    with source.open(encoding="utf-8", errors="replace") as _fh:
                        line_cache[source] = {_i: _l for _i, _l in enumerate(_fh, 1)}
                except Exception:
                    line_cache[source] = {}
            image_refs = _extract_image_refs(source, line_no, vault, tool, ts, session, line_cache)
        if image_refs:
            text = text.strip() + "\n\n" + "\n".join(image_refs) if text.strip() else "\n".join(image_refs)

        before = dict(roll.get(ts.date().isoformat(), {}))
        ok = append_entry(vault, tool, roll, ts, role, text, source, line_no, session, cwd)
        after = roll.get(ts.date().isoformat(), {})
        changed.add(note_path(vault, tool, ts.date(), int(after.get("part") or before.get("part") or 1)))
        if ok:
            # 脱敏成功才标记已导出；失败的消息下次重试（避免原文永久丢失）
            seen.append(h)
            seen_set.add(h)
        exported += 1
    if len(seen) > SEEN_LIMIT:
        seen = seen[-SEEN_LIMIT:]
    save_json(seen_path, seen)
    return len(files_seen), len(changed), exported


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=str(default_vault()))
    ap.add_argument("--tool", choices=["Claude", "Pi", "DSH", "all"], default="all")
    args = ap.parse_args()
    vault = Path(args.vault).expanduser().resolve()
    state_dir = hermes_home() / "data" / "obsidian"
    tools = ["Claude", "Pi", "DSH"] if args.tool == "all" else [args.tool]
    for tool in tools:
        files_seen, files_changed, exported = export_tool(tool, vault, state_dir)
        if exported:
            print(f"✅ {tool} 导出完成: files_seen={files_seen}, files_changed={files_changed}, messages_exported={exported}")
        else:
            print(f"{tool}: 无新消息")
    # 增量导出语义：无新消息也是正常完成（exit 0）
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
