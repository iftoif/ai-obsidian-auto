#!/usr/bin/env python3
"""Rebuild a focused ChromaDB index for Aaron's Obsidian LLM Wiki layer.

Default input roots (relative to vault):
- Wiki/
- Context/
- Hermes/Lessons/
- Codex/Lessons/
- Shared/Lessons/
- Skills/

This intentionally excludes raw long chat logs. SQLite FTS5 remains the full
vault keyword index; this script maintains a high-signal semantic index.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_ROOTS = [
    "Wiki",
    "Context",
    "Hermes/Lessons",
    "Codex/Lessons",
    "Shared/Lessons",
    "Skills",
]

DEFAULT_MAX_CHARS = 4000
DEFAULT_OVERLAP = 400


def default_vault() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Documents/ObsidianVault"
    return Path(os.environ.get("OBSIDIAN_VAULT_PATH", str(Path.home() / "obsidian")))


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    raw, body = parts[1], parts[2].lstrip()
    fm: dict[str, object] = {}
    current_key = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.startswith("  - ") and current_key:
            fm.setdefault(current_key, [])
            if isinstance(fm[current_key], list):
                fm[current_key].append(line.strip()[2:].strip())
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            current_key = key
            if val == "":
                fm[key] = []
            elif val.startswith("[") and val.endswith("]"):
                try:
                    fm[key] = json.loads(val)
                except Exception:
                    fm[key] = [x.strip() for x in val[1:-1].split(",") if x.strip()]
            else:
                fm[key] = val
    return fm, body


def title_for(path: Path, fm: dict, body: str) -> str:
    for key in ("title", "Title", "标题"):
        if fm.get(key):
            return str(fm[key])
    m = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
    if m:
        return m.group(1).strip()
    return path.stem


def iter_notes(vault: Path, roots: Iterable[str]) -> list[Path]:
    notes: list[Path] = []
    for root in roots:
        base = vault / root
        if not base.exists():
            continue
        if base.is_file() and base.suffix == ".md":
            notes.append(base)
            continue
        notes.extend(sorted(p for p in base.rglob("*.md") if ".obsidian" not in p.parts))
    # stable unique order
    seen = set()
    out = []
    for p in notes:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            out.append(p)
    return out


def chunk_text(text: str, max_chars: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # Prefer splitting on markdown headings/paragraphs, then merge.
    blocks = re.split(r"(?=\n#{1,4}\s+)", text)
    merged: list[str] = []
    current = ""
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if len(current) + len(block) + 2 <= max_chars:
            current = f"{current}\n\n{block}".strip()
        else:
            if current:
                merged.append(current)
            if len(block) <= max_chars:
                current = block
            else:
                start = 0
                while start < len(block):
                    merged.append(block[start:start + max_chars])
                    start += max(1, max_chars - overlap)
                current = ""
    if current:
        merged.append(current)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild focused ChromaDB index for Obsidian Wiki/Lessons")
    parser.add_argument("--vault", default=str(default_vault()), help="Obsidian vault path")
    parser.add_argument("--db", default=str(hermes_home() / "data" / "obsidian" / "chroma_wiki_db"), help="ChromaDB path")
    parser.add_argument("--collection", default="obsidian_wiki_chunks")
    parser.add_argument("--root", action="append", help="Relative root to index; repeatable. Defaults to Wiki/Context/Lessons/Skills")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    parser.add_argument("--no-reset", action="store_true", help="Do not delete existing DB directory before rebuild")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    db_path = Path(args.db).expanduser().resolve()
    roots = args.root or DEFAULT_ROOTS

    if not vault.exists():
        print(f"❌ vault not found: {vault}", file=sys.stderr)
        return 1

    try:
        import chromadb
    except ImportError:
        print("❌ chromadb not installed. Install it in obsidian-backup-env.", file=sys.stderr)
        return 1

    if db_path.exists() and not args.no_reset:
        shutil.rmtree(db_path)
    db_path.mkdir(parents=True, exist_ok=True)

    def _get_embedding_function():
        """return multilingual embedding (bge-small-zh for Chinese), None fallback"""
        model = os.environ.get("OBSIDIAN_CHROMA_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
        try:
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
            return SentenceTransformerEmbeddingFunction(model_name=model)
        except Exception as e:
            print(f"⚠️ [chroma] chinese embedding unavailable ({e}), fallback english", file=sys.stderr)
            return None
    client = chromadb.PersistentClient(path=str(db_path))
    collection = client.get_or_create_collection(args.collection, metadata={"hnsw:space": "cosine"}, embedding_function=_get_embedding_function())

    notes = iter_notes(vault, roots)
    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []

    for p in notes:
        rel = p.relative_to(vault).as_posix()
        raw = p.read_text(encoding="utf-8", errors="replace")
        fm, body = parse_frontmatter(raw)
        title = title_for(p, fm, body)
        tags = fm.get("tags", [])
        if isinstance(tags, str):
            tags_s = tags
        elif isinstance(tags, list):
            tags_s = ",".join(str(t) for t in tags)
        else:
            tags_s = ""
        category = rel.split("/", 1)[0]
        base_text = f"# {title}\nPath: {rel}\nCategory: {category}\nTags: {tags_s}\n\n{body.strip()}"
        chunks = chunk_text(base_text, args.max_chars, args.overlap)
        for idx, chunk in enumerate(chunks):
            ids.append(f"{rel}#chunk-{idx:04d}")
            docs.append(chunk)
            metas.append({
                "path": rel,
                "title": title,
                "category": category,
                "tags": tags_s,
                "chunk_index": idx,
                "mtime": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
            })

    batch = 96
    for start in range(0, len(ids), batch):
        collection.upsert(
            ids=ids[start:start + batch],
            documents=docs[start:start + batch],
            metadatas=metas[start:start + batch],
        )

    manifest = {
        "rebuilt_at": datetime.now(timezone.utc).isoformat(),
        "vault": str(vault),
        "db": str(db_path),
        "collection": args.collection,
        "roots": roots,
        "notes": len(notes),
        "chunks": len(ids),
    }
    (db_path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.quiet:
        print(f"✅ Wiki Chroma rebuild complete")
        print(f"   vault: {vault}")
        print(f"   db: {db_path}")
        print(f"   notes: {len(notes)}")
        print(f"   chunks: {len(ids)}")
    else:
        print(f"✅ Wiki Chroma: {len(notes)} notes / {len(ids)} chunks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
