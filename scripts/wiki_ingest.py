#!/usr/bin/env python3
"""CLI wrapper to ingest URL/file/text into the Obsidian LLM Wiki via Hermes.

Examples:
  wiki_ingest.py --url https://example.com/article
  wiki_ingest.py --file "Clippings/some article.md"
  wiki_ingest.py --text "..." --title "Manual note"

This delegates reasoning/writing to Hermes with the llm-wiki-ingest skill.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def default_vault() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "obsidian"
    return Path(os.environ.get("OBSIDIAN_VAULT_PATH", str(Path.home() / "obsidian")))


def build_prompt(args: argparse.Namespace, vault: Path) -> str:
    parts = [
        "请使用 llm-wiki-ingest skill，把下面资料入库到 Obsidian LLM Wiki。",
        "",
        "严格执行：先读 CLAUDE.md，再读 Wiki/AGENTS.md；先搜索已有 Wiki；Raw 原文不修改；更新 Wiki/Index.md 和 Wiki/Log.md；中文输出；敏感信息脱敏。",
        "",
        f"Vault 根目录: {vault}",
        "",
    ]
    if args.url:
        parts.extend([
            "资料类型: URL / 外部文章",
            f"URL: {args.url}",
        ])
        # 优先用 defuddle 抓取干净 markdown，省 token 且去噪；失败回退让 agent 用 web 工具。
        clean = fetch_clean_markdown(args.url)
        if clean:
            parts.extend([
                "已用 defuddle 抓取到正文（优先用这段内容，必要时再补充）：",
                "",
                clean[:6000],
            ])
    if args.file:
        file_path = Path(args.file)
        if not file_path.is_absolute():
            file_path = vault / file_path
        parts.extend([
            "资料类型: Obsidian Raw 文件",
            f"文件路径: {file_path}",
        ])
    if args.text:
        parts.extend([
            "资料类型: 手动文本",
            f"标题: {args.title or '未命名资料'}",
            "正文:",
            args.text,
        ])
    if args.note:
        parts.extend(["补充要求:", args.note])
    parts.extend([
        "",
        "完成后汇报：新建页面、更新页面、关键结论、待核实事项、下一步建议。",
    ])
    return "\n".join(parts)


def fetch_clean_markdown(url: str, max_chars: int = 6000) -> str:
    """Use defuddle CLI to extract clean markdown from a URL; empty string on failure."""
    try:
        import shutil
        # 兜底：defuddle 通常装在 ~/.local/bin（用户级 npm 前缀）
        exe = shutil.which("defuddle") or str(
            Path.home() / ".local" / "bin" / "defuddle"
        )
        if not Path(exe).exists():
            return ""
        proc = subprocess.run(
            [str(exe), "parse", url, "--md"],
            capture_output=True, text=True, timeout=45,
        )
        if proc.returncode != 0:
            return ""
        out = proc.stdout.strip()
        if not out:
            return ""
        return out[:max_chars]
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest URL/file/text into Obsidian LLM Wiki via Hermes")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="URL to ingest")
    src.add_argument("--file", help="Vault-relative or absolute markdown file path")
    src.add_argument("--text", help="Inline text to ingest")
    parser.add_argument("--title", help="Title for --text")
    parser.add_argument("--note", help="Additional instruction/context")
    parser.add_argument("--vault", default=str(default_vault()))
    parser.add_argument("--provider", default=os.environ.get("WIKI_INGEST_PROVIDER", "openai-codex"))
    parser.add_argument("--model", default=os.environ.get("WIKI_INGEST_MODEL", "gpt-5.4-mini"))
    parser.add_argument("--dry-run", action="store_true", help="Print prompt only")
    parser.add_argument("--max-turns", default="80")
    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    prompt = build_prompt(args, vault)

    if args.dry_run:
        print(prompt)
        return 0

    cmd = [
        "hermes", "chat",
        "--provider", args.provider,
        "-m", args.model,
        "-s", "llm-wiki-ingest,obsidian,obsidian-vault-search",
        "-t", "file,terminal,web",
        "--in", str(vault),
        "--max-turns", args.max_turns,
        "-Q",
        "-q", prompt,
    ]
    env = os.environ.copy()
    env["OBSIDIAN_VAULT_PATH"] = str(vault)
    result = subprocess.run(cmd, text=True, env=env)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
