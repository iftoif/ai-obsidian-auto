import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import ai_chat_export as ae

try:
    import zstandard
    HAVE_ZSTD = True
except ImportError:
    HAVE_ZSTD = False


def _make_dsh_session(tmp: Path, session_id: str, messages: list) -> Path:
    """造假 DSH 会话：session 头 + user/assistant 消息，zstd 压缩"""
    sess_dir = tmp / '.dsh' / 'sessions' / ('--tmp--') / ('session-' + session_id)
    sess_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({'type': 'session', 'id': session_id, 'cwd': '/tmp/work', 'createdAt': 1700000000000}),
    ]
    lines.extend(json.dumps(m) for m in messages)
    raw = '\n'.join(lines).encode('utf-8')
    f = sess_dir / 'session.jsonl.zstd'
    with open(f, 'wb') as fh:
        cctx = zstandard.ZstdCompressor()
        fh.write(cctx.compress(raw))
    return f


def test_dsh_records_parse_basic():
    """基础：session + user + assistant 被正确解析"""
    if not HAVE_ZSTD:
        import pytest; pytest.skip('zstandard not available')
    tmp = Path(tempfile.mkdtemp())
    f = _make_dsh_session(tmp, 'abc', [
        {'type': 'user/message', 'time': 1700000000001, 'data': {'role': 'user', 'content': [{'type': 'text', 'text': '你好'}]}},
        {'type': 'assistant/message', 'time': 1700000000002, 'data': {'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': '你好，有什么可以帮你'}]}}},
    ])
    records = list(ae.dsh_records(Path.home()))
    # 注意 dsh_records 用 _resolve_client_dir(home,...) 找 ~/.dsh，这里需要直接测试内部逻辑
    # 用临时 HOME
    old_home = Path.home()
    os.environ['DSH_HOME'] = str(tmp / '.dsh')
    try:
        records = list(ae.dsh_records(Path(tmp)))
        assert len(records) == 2, f'expected 2 records, got {len(records)}'
        roles = [r[3] for r in records]
        assert roles == ['user', 'assistant']
        texts = [r[4] for r in records]
        assert '你好' in texts[0]
    finally:
        os.environ.pop('DSH_HOME', None)


def test_dsh_records_skips_plugin_injection():
    """插件注入消息（source.kind=plugin）被过滤（R4 修复）"""
    if not HAVE_ZSTD:
        import pytest; pytest.skip('zstandard not available')
    tmp = Path(tempfile.mkdtemp())
    _make_dsh_session(tmp, 'def', [
        {'type': 'user/message', 'time': 1700000000001, 'data': {'role': 'user', 'content': [{'type': 'text', 'text': '系统注入内容'}], 'source': {'kind': 'plugin', 'plugin': 'system-prompt'}}},
        {'type': 'user/message', 'time': 1700000000002, 'data': {'role': 'user', 'content': [{'type': 'text', 'text': '真实用户输入'}]}},
    ])
    os.environ['DSH_HOME'] = str(tmp / '.dsh')
    try:
        records = list(ae.dsh_records(Path(tmp)))
        assert len(records) == 1
        assert '真实用户输入' in records[0][4]
    finally:
        os.environ.pop('DSH_HOME', None)


def test_dsh_records_skips_reasoning_toolcall():
    """assistant 消息里的 reasoning/tool-call 被过滤，只留 text"""
    if not HAVE_ZSTD:
        import pytest; pytest.skip('zstandard not available')
    tmp = Path(tempfile.mkdtemp())
    _make_dsh_session(tmp, 'ghi', [
        {'type': 'assistant/message', 'time': 1700000000001, 'data': {'message': {'role': 'assistant', 'content': [
            {'type': 'reasoning', 'text': '隐藏推理过程'},

            {'type': 'tool-call', 'name': 'bash', 'arguments': 'ls'},

            {'type': 'text', 'text': '最终回复文本'},

        ]}}},
    ])
    os.environ['DSH_HOME'] = str(tmp / '.dsh')
    try:
        records = list(ae.dsh_records(Path(tmp)))
        assert len(records) == 1
        text = records[0][4]
        assert '最终回复文本' in text
        assert '隐藏推理过程' not in text
        assert 'ls' not in text
    finally:
        os.environ.pop('DSH_HOME', None)


def test_dsh_records_corrupt_zstd_skipped():
    """损坏的 zstd 文件被跳过而不是崩溃"""
    if not HAVE_ZSTD:
        import pytest; pytest.skip('zstandard not available')
    tmp = Path(tempfile.mkdtemp())
    sess_dir = tmp / '.dsh' / 'sessions' / 'x' / 'session-bad'
    sess_dir.mkdir(parents=True, exist_ok=True)
    (sess_dir / 'session.jsonl.zstd').write_bytes(b'not zstd data at all')
    os.environ['DSH_HOME'] = str(tmp / '.dsh')
    try:
        records = list(ae.dsh_records(Path(tmp)))
        assert records == []
    finally:
        os.environ.pop('DSH_HOME', None)
