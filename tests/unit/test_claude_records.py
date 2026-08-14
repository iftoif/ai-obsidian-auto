import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import ai_chat_export as ae


def _make_claude_session(tmp: Path, sid: str, msgs: list) -> Path:
    f = tmp / '.claude' / 'projects' / ('p-' + sid) / (sid + '.jsonl')
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, 'w') as fh:
        for m in msgs:
            fh.write(json.dumps(m) + '\n')
    return f


def test_claude_records_basic():
    tmp = Path(tempfile.mkdtemp())
    _make_claude_session(tmp, 's1', [
        {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': '帮我写个脚本'}]}, 'timestamp': '2026-08-15T10:00:00Z', 'sessionId': 's1'},
        {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': '好的，这是脚本'}]}, 'timestamp': '2026-08-15T10:00:01Z', 'sessionId': 's1'},
    ])
    os.environ['CLAUDE_CONFIG_DIR'] = str(tmp / '.claude')
    try:
        records = list(ae.claude_records(tmp))
        assert len(records) == 2
        roles = [r[3] for r in records]
        assert roles == ['user', 'assistant']
        texts = [r[4] for r in records]
        assert '帮我写个脚本' in texts[0]
        assert '好的，这是脚本' in texts[1]
    finally:
        os.environ.pop('CLAUDE_CONFIG_DIR', None)


def test_claude_records_skips_tool_result():
    """tool_use/tool_result 不进入正文"""
    tmp = Path(tempfile.mkdtemp())
    _make_claude_session(tmp, 's2', [
        {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
            {'type': 'tool_use', 'id': 't1', 'name': 'Bash', 'input': {'command': 'ls'}},

            {'type': 'text', 'text': '我先看看目录'},

        ]}, 'timestamp': '2026-08-15T10:00:00Z', 'sessionId': 's2'},
        {'type': 'user', 'message': {'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': 't1', 'content': 'file1 file2'},

        ]}, 'timestamp': '2026-08-15T10:00:01Z', 'sessionId': 's2'},
    ])
    os.environ['CLAUDE_CONFIG_DIR'] = str(tmp / '.claude')
    try:
        records = list(ae.claude_records(tmp))
        texts = [r[4] for r in records]
        assert '我先看看目录' in texts[0]
        assert not any('file1 file2' in t for t in texts)
        assert not any('ls' in t for t in texts)
    finally:
        os.environ.pop('CLAUDE_CONFIG_DIR', None)


def test_claude_records_corrupt_line_skipped():
    """损坏的 jsonl 行被跳过而不是崩溃"""
    tmp = Path(tempfile.mkdtemp())
    f = _make_claude_session(tmp, 's3', [
        {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': '正常消息'}]}, 'timestamp': '2026-08-15T10:00:00Z', 'sessionId': 's3'},
    ])
    with open(f, 'a') as fh:
        fh.write('{corrupt json line\n')
    os.environ['CLAUDE_CONFIG_DIR'] = str(tmp / '.claude')
    try:
        records = list(ae.claude_records(tmp))
        assert len(records) == 1
        assert '正常消息' in records[0][4]
    finally:
        os.environ.pop('CLAUDE_CONFIG_DIR', None)


def test_claude_records_empty_content():
    """content 缺失/为空的消息被安全跳过"""
    tmp = Path(tempfile.mkdtemp())
    _make_claude_session(tmp, 's4', [
        {'type': 'user', 'message': {'role': 'user', 'content': None}, 'timestamp': '2026-08-15T10:00:00Z', 'sessionId': 's4'},
        {'type': 'user', 'message': {'role': 'user', 'content': []}, 'timestamp': '2026-08-15T10:00:01Z', 'sessionId': 's4'},
        {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': '有效消息'}]}, 'timestamp': '2026-08-15T10:00:02Z', 'sessionId': 's4'},
    ])
    os.environ['CLAUDE_CONFIG_DIR'] = str(tmp / '.claude')
    try:
        records = list(ae.claude_records(tmp))
        assert len(records) == 1
        assert '有效消息' in records[0][4]
    finally:
        os.environ.pop('CLAUDE_CONFIG_DIR', None)
