#!/usr/bin/env python3
"""Wiki 层审计（T4）：frontmatter 完整性 / 重复标题 / 悬空 wikilink / 新鲜度。

用法:
  python3 wiki_audit.py --vault V [--json] [--strict]
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

WIKI_SUBDIRS = ["Sources", "Concepts", "Entities", "Topics"]

def parse_fm(text):
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
    if not m:
        return None, None
    return m.group(1), text[m.end():]

def extract_field(fm, key):
    if not fm:
        return None
    m = re.search(r"^" + key + r":\s*(.+)$", fm, re.MULTILINE)
    return m.group(1).strip().strip('"') if m else None

def has_field(fm, key):
    if not fm:
        return False
    return bool(re.search(r"^" + key + r":", fm, re.MULTILINE))

def collect_all_titles_and_paths(vault):
    """收集整个 vault 所有 md 的 title 集合 + 相对路径集合"""
    titles = set()
    rel_paths = set()
    for p in vault.rglob("*.md"):
        s = str(p)
        if ".obsidian" in s:
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm, _ = parse_fm(txt)
        t = extract_field(fm, "title")
        if t:
            titles.add(t)
        titles.add(p.stem)
        rel_paths.add(str(p.relative_to(vault)))
        rel_paths.add(str(p.relative_to(vault)).replace(".md", ""))
    return titles, rel_paths

def scan_wiki(vault):
    files = []
    for sub in WIKI_SUBDIRS:
        d = vault / "Wiki" / sub
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            if p.name.startswith("_"):
                continue
            txt = p.read_text(encoding="utf-8", errors="replace")
            fm, body = parse_fm(txt)
            rel = str(p.relative_to(vault))
            files.append({
                "path": rel, "sub": sub, "fm": fm, "body": body or "",
                "title": extract_field(fm, "title"),
                "type": extract_field(fm, "type"),
                "updated": extract_field(fm, "updated"),
                "has_sources": has_field(fm, "sources"),
            })
    return files

def is_link_resolved(target, titles, rel_paths):
    """判断 wikilink 目标是否可解析"""
    target = target.strip().split("|")[0].strip()
    if "/" in target:
        # 带路径链接：按相对路径匹配
        return target in rel_paths or target + ".md" in rel_paths
    # 纯文件名/标题：按 title 或 stem 匹配
    return target in titles

# ── OKM 中文新鲜度 lint（T4.1，轻量版）──
# 上游 FRESH-1 依赖英文词汇，中文需定制。实测结论：本 vault 快事实密度低，
# 采用「现在时标记 + 数字 + 快名词」组合，严格过滤完成态/规则/快照。

CURRENT_ZH = ["目前", "当前", "现在", "至今", "截至", "现有", "尚未", "仍", "还剩"]
VOLATILE_ZH = ["个", "条", "笔", "项", "次", "份", "张", "件", "台", "万", "亿",
               "粉丝", "订阅", "用户", "持仓", "仓位", "余额", "订单", "工单", "任务", "待办", "版本"]
DONE_VERBS = ["修复", "合并", "删除", "下线", "废弃", "补", "排除", "恢复", "切换", "迁移",
              "改", "替换", "更新", "完成", "解决", "关闭", "停止", "停用", "清理", "重置",
              "重建", "同步", "落地", "上线", "跑", "通过", "创建", "生成", "安装", "配置",
              "启用", "接入", "写", "加", "记录", "提交", "推送", "发布", "回滚", "移除"]
# 规则/纪律/建议类（非观察声明，豁免）
RULE_MARKERS = ["只", "不把", "不将", "勿", "禁止", "应", "必须", "务必", "优先", "建议", "应该", "不要", "避免"]
# 举例/示例类（用例子解释概念，非现状声明）
EXAMPLE_MARKERS = ["比如", "例如", "举例", "如某", "某页写着", "假设", "示意", "示例"]
# 方法论/对比类（"将当前 X 与 Y 对比" 是方法，非现状）
METHOD_MARKERS = ["对比", "对照", "与...相比", "相比", "辅助判断", "衡量", "评估", "判断"]
# 完成态语气词（"推荐了"「宣传为」「提到了」的「了/为」是过去时标记）
DONE_PARTICLES = ["推荐了", "宣传为", "提到了", "说明了", "记录了", "总结了", "分析了", "描述了"]
# 教程引用/公式定义（"据 X 的实现"「质量分 = 公式」是定义/转述，非现状）
REF_MARKERS = ["据 [[", "从零实现", "的实现", "质量分 =", "候选质量分"]


def is_done_zh(line):
    """已+动词 = 完成态（过去时，豁免）"""
    return bool(re.search(r"已[" + "".join(DONE_VERBS) + r"]", line))


def is_rule_zh(line):
    """规则/纪律/建议 = 非观察声明，豁免"""
    return any(m in line for m in RULE_MARKERS)


def is_example_zh(line):
    """举例/示例句，豁免"""
    return any(m in line for m in EXAMPLE_MARKERS)


def is_method_zh(line):
    """方法论/对比语境（"当前"修饰的是方法而非现状），豁免"""
    return any(m in line for m in METHOD_MARKERS)


def is_done_particle_zh(line):
    """完成态语气词（了/为），豁免"""
    return any(m in line for m in DONE_PARTICLES)


def is_ref_zh(line):
    """教程引用/公式定义，豁免"""
    return any(m in line for m in REF_MARKERS)


def freshness_lint_zh(files):
    """FRESH-1 中文版：检测「现在时 + 数字 + 快名词」且无时间戳、非完成态、非规则。"""
    findings = []
    for f in files:
        for i, line in enumerate(f["body"].splitlines(), 1):
            ls = line.strip()
            if len(ls) < 5 or ls.startswith(("#", "|", "-", ">", "`", "%", "*")):
                continue
            has_num = bool(re.search(r"\d", ls))
            has_volatile = any(v in ls for v in VOLATILE_ZH)
            has_current = any(c in ls for c in CURRENT_ZH)
            has_stamp = bool(re.search(r"(截至|as of|202\d-\d{2})", ls, re.IGNORECASE))
            if (has_num and has_volatile and has_current
                    and not has_stamp
                    and not is_done_zh(ls)
                    and not is_rule_zh(ls)
                    and not is_example_zh(ls)
                    and not is_method_zh(ls)
                    and not is_done_particle_zh(ls)
                    and not is_ref_zh(ls)):
                findings.append((f["path"], f"freshness: 疑似无时间戳快事实 L{i}"))
    return findings


def audit(vault, strict=False):
    findings = {"critical": [], "warning": [], "info": []}
    files = scan_wiki(vault)

    # 1. frontmatter 缺失 / URL 混入
    for f in files:
        if f["fm"] is None:
            findings["critical"].append((f["path"], "no-frontmatter"))
        elif f["title"] is None:
            findings["critical"].append((f["path"], "no-title"))
        elif f["type"] is None:
            findings["critical"].append((f["path"], "no-type"))
        if f["fm"] and re.search(r"^\s*-\s*https?://", f["fm"], re.MULTILINE):
            findings["critical"].append((f["path"], "url-in-frontmatter"))

    # 2. 重复标题（同 sub 内）
    seen_titles = {}
    for f in files:
        if f["title"]:
            key = (f["sub"], f["title"])
            seen_titles.setdefault(key, []).append(f["path"])
    for key, paths in seen_titles.items():
        if len(paths) > 1:
            findings["warning"].append((", ".join(paths), "duplicate-title: " + key[1]))

    # 3. 悬空 wikilink（全 vault title + 路径集合）
    titles, rel_paths = collect_all_titles_and_paths(vault)
    for f in files:
        for link in re.findall(r"\[\[([^\]|#]+)", f["body"]):
            if not is_link_resolved(link, titles, rel_paths):
                findings["warning"].append((f["path"], "dangling-link: [[" + link.strip() + "]]"))

    # 4. 新鲜度
    now = datetime.now(timezone.utc)
    for f in files:
        upd = f["updated"]
        if upd and re.match(r"^\d{4}-\d{2}-\d{2}", upd):
            try:
                d = datetime.fromisoformat(upd[:10]).replace(tzinfo=timezone.utc)
                age = (now - d).days
                if age > 365:
                    findings["warning"].append((f["path"], f"stale-updated: {age}d"))
            except Exception:
                pass
        if "待核实" in f["body"]:
            findings["info"].append((f["path"], "open-todo: 待核实"))

    # 5. OKM 中文新鲜度 lint（FRESH-1 轻量版，T4.1）
    # 归 info 级别：疑似快事实需人工确认，不自动判错
    freshness = freshness_lint_zh(files)
    for path, reason in freshness:
        findings["info"].append((path, reason))

    if strict:
        for f in files:
            if f["sub"] != "Sources" and not f["has_sources"]:
                findings["info"].append((f["path"], "missing-sources"))

    return findings, files

def print_report(findings, files):
    c = len(findings["critical"])
    w = len(findings["warning"])
    i = len(findings["info"])
    print(f"📋 Wiki 审计报告: {len(files)} 文件 | 🔴 {c} critical, 🟡 {w} warning, ⚪ {i} info")
    print("=" * 60)
    if c:
        print("\n🔴 Critical:")
        for path, reason in findings["critical"]:
            print(f"  - {path}: {reason}")
    if w:
        print("\n🟡 Warning:")
        for path, reason in findings["warning"]:
            print(f"  - {path}: {reason}")
    if i:
        print("\n⚪ Info:")
        for path, reason in findings["info"]:
            print(f"  - {path}: {reason}")
    if not c and not w and not i:
        print("  ✅ 无问题")
    print(f"\n（critical {c}, warning {w}, info {i}）")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    vault = Path(args.vault).expanduser().resolve()
    findings, files = audit(vault, strict=args.strict)
    if args.json:
        print(json.dumps({
            "files": len(files),
            "critical": [{"path": p, "reason": r} for p, r in findings["critical"]],
            "warning": [{"path": p, "reason": r} for p, r in findings["warning"]],
            "info": [{"path": p, "reason": r} for p, r in findings["info"]],
        }, ensure_ascii=False, indent=2))
    else:
        print_report(findings, files)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
