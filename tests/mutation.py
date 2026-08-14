#!/usr/bin/env python3
"""变异验证器：注入已知 bug 变异体，验证测试能抓住（kill rate 100%）。"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORK = Path(tempfile.mkdtemp(prefix='qa-mut.'))

def setup():
    shutil.copytree(REPO / 'scripts', WORK / 'scripts')
    shutil.copytree(REPO / 'tests', WORK / 'tests')
    (WORK / '.env.example').write_text((REPO / '.env.example').read_text())

def run_pytest(keys):
    r = subprocess.run([sys.executable, '-m', 'pytest', str(WORK / 'tests/unit'), '-q', '-k', keys],
                       capture_output=True, text=True, cwd=str(WORK))
    return r

# 变异体：(名称, 文件相对路径, 目标串, 变异串, 测试选择器, 应抓住的测试名)
MUTATIONS = [
    ('parse-time', 'scripts/ai_chat_export.py',
     'if ts < 0 or ts > 4_000_000_000:', 'if ts > 4_000_000_000:',
     'parse_time', 'test_parse_time_negative'),
    ('event-hash', 'scripts/ai_chat_export.py',
     'line_no if line_no is not None else ', '',
     'event_hash', 'test_event_hash_includes_line_no'),
    ('image', 'scripts/ai_chat_export.py',
     'f"{safe_session}-{line_no:06d}-{seq:02d}{ext}"', 'f"{safe_session}-{seq:02d}{ext}"',
     'save_image', 'test_save_image_unique_names_per_line'),
    ('ref-hyphen', 'scripts/redact_secrets.py',
     'sec_[a-zA-Z0-9_-]+', 'sec_[a-zA-Z0-9_]+',
     'existing_ref_with_hyphen', 'test_existing_ref_with_hyphen_not_double_redacted'),
    ('frontmatter', 'scripts/obsidian_backup.py',
     '# 标量值后的缩进续行属畸形 YAML，直接忽略', 'else:\n                                fm[current_key] = [item]  # bug: 标量被覆盖成 list',
     'scalar', 'test_fm_scalar_not_overwritten_by_indent'),
    ('search-like', 'scripts/obsidian_backup.py',
     'WHERE content LIKE ? ESCAPE', 'WHERE 1=0  # bug: LIKE fallback 被禁',
     'search', 'test_search_like_fallback'),
    ('chroma-size-order', 'scripts/obsidian_backup.py',
     'if self.size > CHROMA_MAX_RAW_BYTES:', 'if False:',
     'chroma_skips_large_raw', 'test_chroma_skips_large_raw'),
    ('chroma-raw-prefix', 'scripts/obsidian_backup.py',
     'CHROMA_RAW_CHAT_PREFIXES = (', 'CHROMA_RAW_CHAT_PREFIXES = ()',
     'chroma_skips_low_value', 'test_chroma_skips_low_value_raw_chat'),
    ('dsh-text-io', 'scripts/ai_chat_export.py',
     'text_io', 'text',
     'dsh_records_parse_basic', 'test_dsh_records_parse_basic'),
    ('dsh-hello', 'scripts/ai_chat_export.py',
     's in {"hi", "hello", "say hi"}', 's in {"hi", "hello", "你好", "say hi"}',
     'dsh_records_parse_basic', 'test_dsh_records_parse_basic'),
]

def main():
    setup()
    print('▸ 变异验证')
    killed = survived = skipped = 0
    for name, rel, old, new, selector, target_test in MUTATIONS:
        target = WORK / rel
        s = target.read_text()
        if old not in s:
            print(f'  ⚠️ {name}: 锚点未找到，跳过')
            skipped += 1
            continue
        target.write_text(s.replace(old, new, 1))
        r = run_pytest(selector)
        # 应被抓住：变异后目标测试失败，或 collection error（变异破坏代码结构）
        failed = (target_test in r.stdout and ' failed' in r.stdout) or \
                 ('Interrupted:' in r.stdout and 'errors during collection' in r.stdout)
        if failed:
            print(f'  ✅ {name}: 变异被测试抓住 (killed)')
            killed += 1
        else:
            print(f'  ❌ {name}: 变异未被抓住 (survived)')
            print(f'     pytest输出尾部: {r.stdout.strip()[-200:]}')
            survived += 1
        target.write_text(s)  # 还原
    print(f'\n===== 变异验证：{killed} killed / {survived} survived / {skipped} skipped =====')
    shutil.rmtree(WORK, ignore_errors=True)
    sys.exit(1 if survived else 0)

if __name__ == '__main__':
    main()