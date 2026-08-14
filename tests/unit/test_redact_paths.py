import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import redact_secrets as rs


def test_scan_paths_detects_secrets_in_md():
    tmp = Path(tempfile.mkdtemp())
    f = tmp / 'note.md'
    f.write_text('密码是 sk-1234567890abcdefghij，勿外传', encoding='utf-8')
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = rs.scan_paths([tmp])
    out = buf.getvalue()
    # scan 输出类型+长度（不打印原文——防泄露设计），且统计正确
    assert 'api-key' in out
    assert 'len=' in out
    assert 'TOTAL findings=1' in out
    # scan 只读不修改
    assert 'sk-1234567890abcdefghij' in f.read_text(encoding='utf-8')


def test_scan_paths_skips_non_md():
    tmp = Path(tempfile.mkdtemp())
    (tmp / 'data.txt').write_text('sk-1234567890abcdefghij 在这个txt里', encoding='utf-8')
    (tmp / 'x.md').write_text('干净的笔记', encoding='utf-8')
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = rs.scan_paths([tmp])
    # 只扫 md：txt 不被扫
    assert 'TOTAL findings=0' in buf.getvalue()


def test_redact_paths_dry_run_no_apply():
    """redact --path 不 --apply 时不修改文件"""
    tmp = Path(tempfile.mkdtemp())
    f = tmp / 'n.md'
    f.write_text('key=sk-1234567890abcdefghij123456', encoding='utf-8')
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = rs.redact_paths([tmp], apply=False)
    assert 'sk-1234567890abcdefghij123456' in f.read_text(encoding='utf-8')


def test_redact_paths_apply_replaces():
    """--apply 时文件被改写为 SECRET 引用"""
    tmp = Path(tempfile.mkdtemp())
    f = tmp / 'n.md'
    f.write_text('key=sk-1234567890abcdefghij123456', encoding='utf-8')
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = rs.redact_paths([tmp], apply=True)
    content = f.read_text(encoding='utf-8')
    assert 'sk-1234567890abcdefghij123456' not in content
    assert '[SECRET:' in content


def test_iter_markdown_recursive():
    tmp = Path(tempfile.mkdtemp())
    (tmp / 'a.md').write_text('x', encoding='utf-8')
    sub = tmp / 'sub'
    sub.mkdir()
    (sub / 'b.md').write_text('y', encoding='utf-8')
    (sub / 'c.txt').write_text('z', encoding='utf-8')
    files = list(rs.iter_markdown([tmp]))
    names = sorted(f.name for f in files)
    assert names == ['a.md', 'b.md']
