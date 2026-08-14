#!/usr/bin/env python3
"""Detect secrets, store them in macOS Login Keychain, and replace with SecretRefs.

Scheme A: local macOS Login Keychain. No plaintext secrets are written to
Obsidian Raw Chat Logs when this redactor is used by exporters.

SecretRef format:
  [SECRET:<type>:<sec_id>]

CLI examples:
  redact_secrets.py scan --path ".../Obsidian/Hermes/Chat Logs" --dry-run
  redact_secrets.py redact --path ".../Obsidian/Hermes/Chat Logs" --apply
  echo 'OPENAI_API_KEY=sk-...' | redact_secrets.py text --source manual
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
KEYCHAIN = SCRIPT_DIR / "keychain_secret.swift"
SECRET_REF_RE = re.compile(r"\[SECRET:[a-zA-Z0-9_-]+:(?:sec_[a-zA-Z0-9_-]+|UNSTORED-[a-f0-9]+|DRYRUN-[a-f0-9]+)\]")


@dataclasses.dataclass(frozen=True)
class Finding:
    type: str
    start: int
    end: int
    secret: str
    replacement_template: str | None = None


# Conservative patterns: catch common high-value secrets while avoiding ordinary prose.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "private-key",
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |)?PRIVATE KEY-----.*?-----END (?:RSA |OPENSSH |EC |DSA |)?PRIVATE KEY-----", re.DOTALL),
    ),
    (
        "authorization-bearer",
        re.compile(r"(?i)(Authorization\s*:\s*Bearer\s+)([A-Za-z0-9._~+/=-]{16,})"),
    ),
    (
        "cookie",
        re.compile(r"(?i)((?:Cookie|Set-Cookie)\s*:\s*)([^\n]{20,})"),
    ),
    (
        "api-key",
        re.compile(
            r"\b(sk-[A-Za-z0-9_-]{20,}|sk-proj-[A-Za-z0-9_-]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|"
            r"tvly-[A-Za-z0-9_-]{20,}|rk-live-[A-Za-z0-9_-]{20,}|rk-prod-[A-Za-z0-9_-]{20,}|"
            r"ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{40,}|xox[baprs]-[A-Za-z0-9-]{20,}|"
            r"AKIA[0-9A-Z]{16}|AIza[A-Za-z0-9_-]{30,}|sk_live_[A-Za-z0-9]{20,}|sk_test_[A-Za-z0-9]{20,})\b"
        ),
    ),
    (
        "jwt",
        re.compile(r"\b(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b"),
    ),
    (
        "db-url-password",
        re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.-]{2,}://[^\s:/@]+:)([^\s/@]{6,})(@[^\s]+)"),
    ),
    (
        "assignment-secret",
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|COOKIE|SESSION)[A-Z0-9_]*\s*[:=]\s*)(['\"]?)([^\s'\"`]{8,})(\2)"
        ),
    ),
    (
        "password",
        re.compile(r"(?i)((?:password|passwd|pwd|密码|口令)\s*(?:是|为|:|=)\s*)(['\"]?)([^\s'\"`，。；;]{6,})(\2)"),
    ),
]


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _secret_group(match: re.Match[str], typ: str) -> tuple[int, int, str, str | None]:
    """Return absolute secret span, secret, and replacement template."""
    if typ in {"authorization-bearer", "cookie", "db-url-password", "assignment-secret", "password"}:
        if typ == "db-url-password":
            idx = 2
        elif typ in {"assignment-secret", "password"}:
            idx = 3
        else:
            idx = 2
        start, end = match.span(idx)
        secret = match.group(idx)
        return start, end, secret, None
    start, end = match.span(0)
    return start, end, match.group(0), None


def find_secrets(text: str) -> list[Finding]:
    if not text or "[SECRET:" in text:
        # Existing refs are skipped, but still scan other text around them.
        existing = [m.span() for m in SECRET_REF_RE.finditer(text)]
    else:
        existing = []

    findings: list[Finding] = []
    occupied: list[tuple[int, int]] = existing[:]
    for typ, pat in PATTERNS:
        for m in pat.finditer(text):
            start, end, secret, tmpl = _secret_group(m, typ)
            if len(secret.strip()) < 6:
                continue
            span = (start, end)
            if any(_overlaps(span, o) for o in occupied):
                continue
            # Avoid redacting obvious placeholders.
            if "REDACTED" in secret.upper() or secret.startswith("[SECRET:"):
                continue
            findings.append(Finding(typ, start, end, secret, tmpl))
            occupied.append(span)
    findings.sort(key=lambda f: f.start)
    return findings


_keychain_warned = False


def keychain_available() -> bool:
    global _keychain_warned
    ok = platform.system() == "Darwin" and KEYCHAIN.exists()
    if not ok and not _keychain_warned:
        # keychain_secret.swift 位于私有 Hermes 仓库，公开版未附带。
        # 缺失时降级为 UNSTORED-（fail-closed，不落明文），但密钥不会被保存到 Keychain。
        print(
            "⚠️ keychain_secret.swift 缺失（该文件在私有 Hermes 仓库中，公开版未附带）。"
            "密钥将以 UNSTORED- 引用处理（不落明文，但不可还原）。",
            file=sys.stderr,
        )
        _keychain_warned = True
    return ok


def put_secret(secret: str, typ: str, source: str = "", hint: str = "") -> str:
    if not keychain_available():
        raise RuntimeError("macOS Keychain helper unavailable")
    cmd = [str(KEYCHAIN), "put", "--type", typ, "--hint", hint or typ, "--source", source]
    proc = subprocess.run(cmd, input=secret, text=True, capture_output=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "keychain put failed")
    sec_id = proc.stdout.strip().splitlines()[-1].strip()
    if not sec_id.startswith("sec_"):
        raise RuntimeError(f"unexpected keychain id: {sec_id!r}")
    return sec_id


def redact_text(text: str, source: str = "", store: bool = True) -> str:
    findings = find_secrets(text)
    if not findings:
        return text
    out: list[str] = []
    last = 0
    for f in findings:
        out.append(text[last:f.start])
        digest = hashlib.sha256(f.secret.encode("utf-8", errors="replace")).hexdigest()[:10]
        if store:
            try:
                sec_id = put_secret(f.secret, f.type, source=source, hint=f.type)
                out.append(f"[SECRET:{f.type}:{sec_id}]")
            except Exception:
                # Fail closed: never write a detected secret back to Raw logs in
                # plaintext. UNSTORED refs mean the original secret was not
                # preserved in Keychain and should be treated as redacted-only.
                out.append(f"[SECRET:{f.type}:UNSTORED-{digest}]")
        else:
            out.append(f"[SECRET:{f.type}:DRYRUN-{digest}]")
        last = f.end
    out.append(text[last:])
    return "".join(out)


def iter_markdown(paths: Iterable[Path]) -> Iterable[Path]:
    for p in paths:
        p = p.expanduser()
        if p.is_file() and p.suffix.lower() == ".md":
            yield p
        elif p.is_dir():
            yield from sorted(p.rglob("*.md"))


def scan_paths(paths: list[Path]) -> int:
    total = 0
    for p in iter_markdown(paths):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        findings = find_secrets(text)
        if not findings:
            continue
        for f in findings:
            line = text.count("\n", 0, f.start) + 1
            print(f"{p}:{line}: {f.type} len={len(f.secret)}")
            total += 1
    print(f"TOTAL findings={total}")
    return 0  # scan 是只读检查，有无发现都正常退出


def redact_paths(paths: list[Path], apply: bool) -> int:
    changed = 0
    findings_total = 0
    for p in iter_markdown(paths):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        findings = find_secrets(text)
        if not findings:
            continue
        findings_total += len(findings)
        print(f"{p}: findings={len(findings)}")
        if apply:
            new = redact_text(text, source=str(p), store=True)
            if new != text:
                # Do not create plaintext backups inside the vault: that would
                # defeat the purpose of removing secrets from Obsidian/iCloud.
                p.write_text(new, encoding="utf-8")
                changed += 1
    print(f"TOTAL findings={findings_total} files_changed={changed}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_text = sub.add_parser("text")
    p_text.add_argument("--source", default="stdin")
    p_text.add_argument("--dry-run", action="store_true")
    p_scan = sub.add_parser("scan")
    p_scan.add_argument("--path", action="append", required=True)
    p_scan.add_argument("--dry-run", action="store_true", help="兼容参数：scan 本身只读，此参数无额外效果")
    p_redact = sub.add_parser("redact")
    p_redact.add_argument("--path", action="append", required=True)
    p_redact.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if args.cmd == "text":
        src = sys.stdin.read()
        print(redact_text(src, source=args.source, store=not args.dry_run), end="")
        return 0
    if args.cmd == "scan":
        return scan_paths([Path(x) for x in args.path])
    if args.cmd == "redact":
        return redact_paths([Path(x) for x in args.path], apply=args.apply)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
