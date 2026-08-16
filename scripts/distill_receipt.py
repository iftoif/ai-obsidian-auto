#!/usr/bin/env python3
"""Distill write-intent receipt.

Snapshot the knowledge layer (Wiki + per-tool Lessons) before distillation,
diff after, and emit a receipt of actually-changed files. Catches "hallucinated
ingest" where an agent reports success but wrote nothing, and phantom writes
where a reported file does not exist on disk.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

KNOWLEDGE_ROOTS = [
    "Wiki",
    "Hermes/Lessons",
    "Codex/Lessons",
    "Claude/Lessons",
    "Pi/Lessons",
    "Shared/Lessons",
]


def scan(vault: Path) -> dict:
    entries: dict = {}
    for root in KNOWLEDGE_ROOTS:
        d = vault / root
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.md")):
            rel = str(p.relative_to(vault))
            try:
                data = p.read_bytes()
            except OSError:
                continue
            entries[rel] = {
                "size": len(data),
                "mtime_ns": p.stat().st_mtime_ns,
                "hash": hashlib.sha256(data).hexdigest(),
            }
    return entries


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def snapshot(vault: Path, state_dir: Path) -> int:
    snap = scan(vault)
    out = state_dir / "distill_receipt_snapshot.json"
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n")
    print(f"📸 已快照 {len(snap)} 个知识层文件 -> {out}")
    return 0


def verify(vault: Path, state_dir: Path, manifest_text: str, provider: str, model: str) -> int:
    snap_path = state_dir / "distill_receipt_snapshot.json"
    if not snap_path.exists():
        print("⚠️ 无快照文件，跳过回执验证（蒸馏前可能未快照）")
        return 2
    try:
        before = json.loads(snap_path.read_text())
    except Exception:
        print("⚠️ 快照损坏，跳过回执验证")
        return 2

    after = scan(vault)
    added = []
    modified = []
    deleted = []
    for path, meta in after.items():
        b = before.get(path)
        if b is None:
            added.append((path, meta))
        elif b["hash"] != meta["hash"]:
            modified.append((path, meta))
    for path in before:
        if path not in after:
            deleted.append(path)

    phantom = []
    for path, meta in added + modified:
        p = vault / path
        if not p.exists():
            phantom.append((path, "missing"))
        elif p.stat().st_size == 0:
            phantom.append((path, "empty"))

    manifest_lines = [ln.strip() for ln in manifest_text.splitlines() if ln.strip()]

    receipt = {
        "run_id": file_stamp(),
        "provider": provider,
        "model": model,
        "finished_at": timestamp(),
        "manifest_files": len(manifest_lines),
        "added": [{"path": p, "hash": m["hash"], "size": m["size"]} for p, m in added],
        "modified": [{"path": p, "hash": m["hash"], "size": m["size"]} for p, m in modified],
        "deleted": deleted,
        "phantom": [{"path": p, "reason": r} for p, r in phantom],
    }

    receipts_dir = state_dir / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipts_dir / f"distill-{file_stamp()}.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")

    total_change = len(added) + len(modified)
    print(f"📋 蒸馏回执: +{len(added)} 新增, ~{len(modified)} 修改, -{len(deleted)} 删除")
    for p, _ in added:
        print(f"   ➕ {p}")
    for p, _ in modified:
        print(f"   ✏️  {p}")
    for p in deleted:
        print(f"   🗑️  {p}")
    if phantom:
        for p, r in phantom:
            print(f"   👻 幻影写入: {p} ({r})")
    print(f"   回执文件: {receipt_path}")

    if total_change == 0 and not deleted and manifest_lines:
        print("⚠️ 幻觉入库信号：本轮蒸馏有输入 manifest 但知识层无任何文件变化，疑似「报告成功但未写入」")
        return 1
    if phantom:
        print("⚠️ 幻影写入：存在声称写入但磁盘上缺失/为空的文件")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["snapshot", "verify"])
    ap.add_argument("--vault", required=True)
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--provider", default="")
    ap.add_argument("--model", default="")
    args = ap.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    state_dir = Path(args.state_dir).expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True)

    if args.action == "snapshot":
        return snapshot(vault, state_dir)
    manifest_text = sys.stdin.read()
    return verify(vault, state_dir, manifest_text, args.provider, args.model)


if __name__ == "__main__":
    raise SystemExit(main())
