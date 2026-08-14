import base64
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import ai_chat_export as ae


def test_save_image_unique_names_per_line():
    # R14 修复：同 session 不同行号的两张图不互相覆盖
    vault = Path(tempfile.mkdtemp())
    day = ae.dt.date(2026, 8, 15)
    b64 = base64.b64encode(b'x' * 100).decode()
    p1 = ae.save_image_to_assets(vault, 'Claude', day, 'sess-1', b64, 'image/png', 1, line_no=10)
    p2 = ae.save_image_to_assets(vault, 'Claude', day, 'sess-1', b64, 'image/png', 1, line_no=20)
    assert p1 != p2
    assert (vault / 'Claude/Chat Logs/assets/2026-08-15/sess-1-000010-01.png').exists()
    assert (vault / 'Claude/Chat Logs/assets/2026-08-15/sess-1-000020-01.png').exists()


def test_save_image_rejects_short():
    # 太短的 base64（<64 字节）拒绝落盘
    vault = Path(tempfile.mkdtemp())
    b64 = base64.b64encode(b'short').decode()
    p = ae.save_image_to_assets(vault, 'Claude', ae.dt.date(2026, 8, 15), 's1', b64, 'image/png', 1, line_no=1)
    assert p is None


def test_save_image_rejects_bad_base64():
    vault = Path(tempfile.mkdtemp())
    p = ae.save_image_to_assets(vault, 'Claude', ae.dt.date(2026, 8, 15), 's1', '!!!not-base64!!!', 'image/png', 1, line_no=1)
    assert p is None


def test_text_from_content_skips_tool_blocks():
    # 只保留可读 text，跳过 tool_use/tool_result/image
    content = [
        {'type': 'text', 'text': '用户消息内容'},

        {'type': 'tool_use', 'name': 'bash', 'input': {'command': 'ls'}},

        {'type': 'image', 'source': {'type': 'base64', 'data': 'xx'}},

    ]
    out = ae.text_from_content(content)
    assert '用户消息内容' in out
    assert 'ls' not in out


def test_is_low_value():
    assert ae.is_low_value('')
    assert ae.is_low_value('hi')
    assert ae.is_low_value('<local-command-stdout>')
    assert not ae.is_low_value('重要的排查结论')
