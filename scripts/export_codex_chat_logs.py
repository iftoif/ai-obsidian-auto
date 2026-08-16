#!/usr/bin/env python3
"""
Incrementally export readable Codex chat logs into an Obsidian vault.

The exporter intentionally skips system/developer instructions, encrypted
reasoning, raw tool payloads, and most internal event noise. It keeps user
messages, assistant visible messages, and task-complete final messages.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


# 默认 vault：优先环境变量 OBSIDIAN_VAULT_PATH，未配置回退 ~/obsidian
DEFAULT_VAULT = Path(os.environ.get("OBSIDIAN_VAULT_PATH", str(Path.home() / "obsidian")))
def _resolve_codex_home() -> Path:
    """自动发现 Codex 数据目录，支持任意换目录（不设环境变量也能发现）。

    优先级：
      1. CODEX_HOME 环境变量
      2. 默认 ~/.codex
      3. 扫描 home 下所有一级目录，识别有 sessions 子目录特征的
    返回找到的目录；找不到回退默认。
    """
    env_val = os.environ.get("CODEX_HOME", "").strip()
    if env_val:
        p = Path(env_val).expanduser()
        if (p / "sessions").exists():
            return p
    default = Path.home() / ".codex"
    if (default / "sessions").exists():
        return default
    # 扫描 home 下所有一级目录，找有 sessions 特征的
    candidates = []
    try:
        for d in Path.home().iterdir():
            if not d.is_dir():
                continue
            if d.name.startswith(".") and d.name != ".codex":
                continue
            try:
                if (d / "sessions").exists():
                    candidates.append(d)
            except OSError:
                continue
    except OSError:
        pass
    if candidates:
        for d in candidates:
            if "codex" in d.name.lower():
                return d
        try:
            return max(candidates, key=lambda p: p.stat().st_mtime)
        except OSError:
            return candidates[0]
    return default


DEFAULT_CODEX_HOME = _resolve_codex_home()
DEFAULT_TIMEZONE = "Asia/Shanghai"


# 单个聊天记录文件大小上限（字节），超过则滚动到 {date}-02.md 等新文件，
# 避免单文件无限膨胀导致 Obsidian 索引/渲染时内存溢出崩溃。
MAX_NOTE_BYTES = 2 * 1024 * 1024
# 已导出消息的去重哈希保留上限（独立紧凑存储，不再塞进 state.json）。
SEEN_LIMIT = 50_000


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


def parse_timestamp(value: str | None, tz: ZoneInfo) -> dt.datetime:
    if not value:
        return dt.datetime.now(tz)
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return dt.datetime.now(tz)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(tz)


def safe_frontmatter_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def redact_for_raw_log(text: str, source: str) -> str:
    """Store detected secrets in macOS Keychain and replace with SecretRefs."""
    try:
        scripts_dir = Path.home() / ".hermes" / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from redact_secrets import redact_text  # type: ignore
        return redact_text(text, source=source, store=True)
    except Exception:
        return text


def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text") or item.get("input_text") or item.get("output_text")
        if isinstance(text, str):
            parts.append(text)
    return "\n\n".join(parts).strip()


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<environment_context>.*?</environment_context>", "", text, flags=re.DOTALL)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def is_internal_context(text: str) -> bool:
    stripped = text.strip()
    if stripped.startswith("<environment_context>") and stripped.endswith("</environment_context>"):
        return True
    return False


def message_from_event(obj: dict[str, Any]) -> tuple[str, str] | None:
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return None

    event_type = payload.get("type")
    if obj.get("type") == "event_msg":
        # computerUse 截图：从 mcp_tool_call_end 提取图片
        if event_type == "mcp_tool_call_end":
            images = _iter_computeruse_images(obj)
            if not images:
                return None
            tool = ""
            invocation = payload.get("invocation")
            if isinstance(invocation, dict):
                tool = invocation.get("tool", "")
            elif isinstance(invocation, str):
                tool = invocation
            # 返回特殊标记，供 export 循环里识别并落盘
            return ("__image__", json.dumps(images, ensure_ascii=False))
        if event_type == "user_message":
            text = payload.get("message")
            if not isinstance(text, str):
                return None
            text = normalize_text(text)
            if not text or is_internal_context(text):
                return None
            return ("用户", text)
        if event_type == "agent_message":
            text = payload.get("message")
            phase = payload.get("phase")
            if phase == "commentary":
                return None
            label = "助手"
            return (label, normalize_text(text)) if isinstance(text, str) and text.strip() else None
        if event_type == "task_complete":
            text = payload.get("last_agent_message")
            return ("助手最终回复", normalize_text(text)) if isinstance(text, str) and text.strip() else None
        return None

    if obj.get("type") == "response_item" and payload.get("type") == "message":
        role = payload.get("role")
        if role not in {"user", "assistant"}:
            return None
        text = text_from_content(payload.get("content"))
        if not text:
            return None
        text = normalize_text(text)
        if not text or is_internal_context(text):
            return None
        label = "用户" if role == "user" else "助手"
        return (label, text)

    return None


def file_thread_id(path: Path) -> str:
    name = path.stem
    if name.startswith("rollout-"):
        return name.split("-")[-5] + "-" + "-".join(name.split("-")[-4:])
    return path.stem


def session_meta_from_file(path: Path) -> dict[str, str]:
    meta: dict[str, str] = {}
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") != "session_meta":
                    continue
                payload = obj.get("payload") or {}
                if isinstance(payload, dict):
                    for key in ("id", "session_id", "cwd", "originator", "cli_version", "model_provider"):
                        value = payload.get(key)
                        if isinstance(value, str):
                            meta[key] = value
                    break
    except FileNotFoundError:
        pass
    return meta


def ensure_daily_note(path: Path, day: dt.date) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "source: codex\n"
        "type: daily-chat-log\n"
        f"date: {day.isoformat()}\n"
        "tags:\n"
        "  - codex\n"
        "  - chat-log\n"
        "---\n\n"
        f"# Codex 聊天记录 {day.isoformat()}\n\n",
        encoding="utf-8",
    )


def daily_note_path(vault: Path, day: dt.date, part: int) -> Path:
    name = f"{day.isoformat()}.md" if part == 1 else f"{day.isoformat()}-{part:02d}.md"
    return vault / "Codex" / "Chat Logs" / f"{day:%Y}" / name


def init_roll_state(vault: Path) -> dict[str, dict[str, int]]:
    """扫描已有日志，确定每天的当前分片编号与字节数，供滚动追加复用。"""
    base = vault / "Codex" / "Chat Logs"
    roll: dict[str, dict[str, int]] = {}
    if not base.exists():
        return roll
    pat = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-(\d{2}))?\.md$")
    by_day: dict[str, list[tuple[int, Path]]] = {}
    for md in base.rglob("*.md"):
        m = pat.match(md.name)
        if not m:
            continue
        day = m.group(1)
        part = int(m.group(2)) if m.group(2) else 1
        by_day.setdefault(day, []).append((part, md))
    for day, items in by_day.items():
        items.sort()
        max_part, max_path = items[-1]
        try:
            size = max_path.stat().st_size
        except OSError:
            size = 0
        roll[day] = {"part": max_part, "size": size}
    return roll


def append_entry(
    vault: Path,
    timestamp: dt.datetime,
    role: str,
    text: str,
    source: Path,
    line_no: int,
    thread_meta: dict[str, str],
    roll_state: dict[str, dict[str, int]],
) -> None:
    day = timestamp.date()
    day_str = day.isoformat()
    st = roll_state.get(day_str)
    if st is None:
        st = {"part": 1, "size": 0}
        roll_state[day_str] = st

    thread_id = thread_meta.get("id") or thread_meta.get("session_id") or file_thread_id(source)
    cwd = thread_meta.get("cwd", "")
    source_rel = str(source)
    body = (
        f"## {timestamp:%H:%M:%S} {role}\n\n"
        f"> thread: `{safe_frontmatter_value(thread_id)}`  \n"
        f"> source: `{safe_frontmatter_value(source_rel)}:{line_no}`"
    )
    if cwd:
        body += f"  \n> cwd: `{safe_frontmatter_value(cwd)}`"
    body += "\n\n"
    text = redact_for_raw_log(text, source=f"Codex thread={thread_id} {source}:{line_no}")
    body += text.strip() + "\n\n"

    body_bytes = len(body.encode("utf-8"))
    if st["size"] > 0 and st["size"] + body_bytes > MAX_NOTE_BYTES:
        st["part"] += 1
        st["size"] = 0

    note = daily_note_path(vault, day, st["part"])
    ensure_daily_note(note, day)
    with note.open("a", encoding="utf-8") as handle:
        handle.write(body)
    st["size"] += body_bytes


def event_hash(thread_id: str, role: str, text: str) -> str:
    data = f"{thread_id}|{role}|{text}".encode("utf-8", errors="replace")
    return hashlib.sha256(data).hexdigest()


# 图片 MIME 类型 → 文件扩展名
_IMAGE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}


def save_image_to_assets(
    vault: Path,
    day: dt.date,
    thread_id: str,
    image_b64: str,
    mime_type: str,
    seq: int,
) -> str | None:
    """把 base64 图片解码保存到 Codex/Chat Logs/assets/，返回 Obsidian 嵌入链接或 None。

    返回形如 ``![[Codex/Chat Logs/assets/2026-08-09/thread-id-0001.jpg]]`` 的 wikilink。
    """
    data = image_b64 or ""
    if not data:
        return None
    try:
        raw = base64.b64decode(data)
    except Exception:
        return None
    if len(raw) < 64:  # 太小不是真实图片
        return None
    ext = _IMAGE_EXT.get(mime_type or "", ".jpg")
    safe_thread = re.sub(r"[^A-Za-z0-9._-]", "-", thread_id)[:40]
    assets_dir = vault / "Codex" / "Chat Logs" / "assets" / day.isoformat()
    assets_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{safe_thread}-{seq:04d}{ext}"
    fpath = assets_dir / fname
    fpath.write_bytes(raw)
    rel = fpath.relative_to(vault)
    return f"![[{rel.as_posix()}]]"


def _iter_computeruse_images(obj: dict[str, Any]) -> list[tuple[str, str]]:
    """从 mcp_tool_call_end 事件里提取 computerUse 截图 (mimeType, base64)。"""
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return []
    if payload.get("type") != "mcp_tool_call_end":
        return []
    result = payload.get("result")
    if not isinstance(result, dict):
        return []
    ok = result.get("Ok")
    if isinstance(ok, dict):
        content = ok.get("content")
    else:
        content = result.get("content")
    if not isinstance(content, list):
        return []
    images: list[tuple[str, str]] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "image":
            data = block.get("data") or ""
            mime = block.get("mimeType") or "image/jpeg"
            if isinstance(data, str) and data:
                images.append((mime, data))
    return images


def seen_store_path(vault: Path) -> Path:
    return vault / "Codex" / ".sync" / "seen_hashes.txt"


def load_seen(vault: Path, state: dict[str, Any]) -> set[str]:
    seen: set[str] = set()
    sp = seen_store_path(vault)
    if sp.exists():
        for line in sp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                seen.add(line)
    legacy = state.get("seen") or []
    if isinstance(legacy, list):
        seen.update(x for x in legacy if isinstance(x, str))
    return seen


def save_seen(vault: Path, seen: set[str]) -> None:
    sp = seen_store_path(vault)
    sp.parent.mkdir(parents=True, exist_ok=True)
    kept = sorted(seen)[-SEEN_LIMIT:]
    sp.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")


def export(vault: Path, codex_home: Path, timezone: str, include_archived: bool = True) -> dict[str, int]:
    tz = ZoneInfo(timezone)
    sessions_dir = codex_home / "sessions"
    state_path = vault / "Codex" / ".sync" / "codex_chat_export_state.json"
    state = load_json(state_path, {"files": {}, "seen": []})
    seen = load_seen(vault, state)
    file_state = state.setdefault("files", {})
    roll_state = init_roll_state(vault)

    stats = {"files_seen": 0, "files_changed": 0, "messages_exported": 0}
    files = sorted(sessions_dir.rglob("*.jsonl"))
    for path in files:
        stats["files_seen"] += 1
        key = str(path)
        previous_lines = int(file_state.get(key, {}).get("lines", 0))
        current_lines = 0
        thread_meta = session_meta_from_file(path)
        changed = False

        with path.open(encoding="utf-8", errors="replace") as handle:
            for current_lines, line in enumerate(handle, start=1):
                if current_lines <= previous_lines:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                msg = message_from_event(obj)
                if not msg:
                    continue
                role, text = msg
                if not text:
                    continue
                thread_id = thread_meta.get("id") or thread_meta.get("session_id") or file_thread_id(path)
                timestamp = parse_timestamp(obj.get("timestamp"), tz)

                # computerUse 截图：落盘到 assets/ 并在日志里引用
                if role == "__image__":
                    try:
                        images = json.loads(text)
                    except Exception:
                        continue
                    if not isinstance(images, list):
                        continue
                    digest = event_hash(thread_id, "image", text)
                    if digest in seen:
                        continue
                    links = []
                    for seq, (mime, data) in enumerate(images, start=1):
                        link = save_image_to_assets(vault, timestamp.date(), thread_id, data, mime, seq)
                        if link:
                            links.append(link)
                    if links:
                        body_text = "🖼️ 屏幕截图：\n\n" + "\n".join(links) + "\n"
                        append_entry(vault, timestamp, "助手", body_text, path, current_lines, thread_meta, roll_state)
                        seen.add(digest)
                        stats["messages_exported"] += 1
                        changed = True
                    continue

                digest = event_hash(thread_id, role, text)
                if digest in seen:
                    continue
                append_entry(vault, timestamp, role, text, path, current_lines, thread_meta, roll_state)
                seen.add(digest)
                stats["messages_exported"] += 1
                changed = True

        file_state[key] = {
            "lines": current_lines,
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        if changed:
            stats["files_changed"] += 1

    state.pop("seen", None)
    state["last_run_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    state["last_stats"] = stats
    save_json(state_path, state)
    save_seen(vault, seen)
    return stats


def split_one_note(note: Path) -> int:
    """把单个超大日志 md 按 `## ` 消息块切成多个不超过上限的分片，返回写入分片数。"""
    text = note.read_text(encoding="utf-8")
    front = ""
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            front = text[: end + 4] + "\n\n"
            body = text[end + 4:].lstrip("\n")
    title = ""
    tm = re.match(r"(# [^\n]+\n+)", body)
    if tm:
        title = tm.group(1)
        body = body[len(title):]
    blocks = [b for b in re.split(r"(?=^## )", body, flags=re.MULTILINE) if b.strip()]

    day = note.stem
    year_dir = note.parent

    def header(part: int) -> str:
        suffix = "" if part == 1 else f"（续 {part}）"
        return f"{front}# Codex 聊天记录 {day}{suffix}\n\n"

    parts: list[str] = []
    current = header(1)
    part_no = 1
    for b in blocks:
        if (
            current != header(part_no)
            and len(current.encode("utf-8")) + len(b.encode("utf-8")) > MAX_NOTE_BYTES
        ):
            parts.append(current)
            part_no += 1
            current = header(part_no)
        current += b
    if current != header(part_no):
        parts.append(current)

    for idx, content in enumerate(parts, start=1):
        name = f"{day}.md" if idx == 1 else f"{day}-{idx:02d}.md"
        (year_dir / name).write_text(content, encoding="utf-8")
    return len(parts)


def migrate_large_notes(vault: Path) -> dict[str, int]:
    """就地切分所有超过大小上限的 {date}.md 日志（分片命名为 {date}-NN.md）。"""
    base = vault / "Codex" / "Chat Logs"
    pat = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
    out = {"split_files": 0, "created_parts": 0}
    if not base.exists():
        return out
    for md in sorted(base.rglob("*.md")):
        if not pat.match(md.name):
            continue
        try:
            size = md.stat().st_size
        except OSError:
            continue
        if size <= MAX_NOTE_BYTES:
            continue
        out["created_parts"] += split_one_note(md)
        out["split_files"] += 1
    return out


def rebuild(vault: Path, codex_home: Path, timezone: str) -> dict[str, int]:
    """清空现有 Chat Logs 并重置导出状态后全量重新导出（用于彻底重建/清理）。"""
    base = vault / "Codex" / "Chat Logs"
    removed = 0
    if base.exists():
        for md in base.rglob("*.md"):
            md.unlink()
            removed += 1
    state_path = vault / "Codex" / ".sync" / "codex_chat_export_state.json"
    save_json(state_path, {"files": {}, "seen": []})
    seen_path = seen_store_path(vault)
    if seen_path.exists():
        seen_path.unlink()
    stats = export(vault, codex_home, timezone)
    stats["notes_removed"] = removed
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", default=str(DEFAULT_VAULT), help="Obsidian vault path")
    parser.add_argument("--codex-home", default=str(DEFAULT_CODEX_HOME), help="Codex home path")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="Timezone for daily notes")
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="先把现有超过大小上限的日志切成多个小文件，再执行增量导出",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="清空现有日志与导出状态后全量重新导出",
    )
    args = parser.parse_args()

    vault = Path(args.vault).expanduser()
    if args.rebuild:
        stats = rebuild(vault, Path(args.codex_home).expanduser(), args.timezone)
        print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
        return 0
    if args.migrate:
        mig = migrate_large_notes(vault)
        print(json.dumps({"migrate": mig}, ensure_ascii=False, sort_keys=True))

    stats = export(vault, Path(args.codex_home).expanduser(), args.timezone)
    print(json.dumps(stats, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
