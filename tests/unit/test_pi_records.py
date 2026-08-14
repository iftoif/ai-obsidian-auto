import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import ai_chat_export as ae


def _make_pi_session(tmp: Path, sid: str, msgs: list) -> Path:
    f = tmp / '.pi' / 'agent' / 'sessions' / ('session_' + sid + '.jsonl')
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, 'w', encoding='utf-8') as fh:
        for m in msgs:
            fh.write(json.dumps(m) + '\n')
    return f


def test_pi_records_basic():
    tmp = Path(tempfile.mkdtemp())
    _make_pi_session(tmp, 's1', [
        {'type': 'session', 'id': 's1', 'cwd': '/work'},

        {'type': 'message', 'message': {'role': 'user', 'content': '用户问题'}, 'timestamp': '2026-08-15T10:00:00Z'},

        {'type': 'message', 'message': {'role': 'assistant', 'content': '助手回答'}, 'timestamp': '2026-08-15T10:00:01Z'},

    ])
    os.environ['PI_HOME'] = str(tmp / '.pi')
    try:
        records = list(ae.pi_records(tmp))
        assert len(records) == 2
        texts = [r[4] for r in records]
        assert '用户问题' in texts[0]
        assert '助手回答' in texts[1]
        assert records[0][5] == 's1'  # session id 从 session 行取
    finally:
        os.environ.pop('PI_HOME', None)


def test_pi_records_skips_non_message_types():
    """非 message 类型的行（tool_result 等）被跳过"""
    tmp = Path(tempfile.mkdtemp())
    _make_pi_session(tmp, 's2', [
        {'type': 'tool_result', 'message': {'role': 'user', 'content': '工具输出'}},

        {'type': 'message', 'message': {'role': 'user', 'content': '有效消息'}, 'timestamp': '2026-08-15T10:00:00Z'},

    ])
    os.environ['PI_HOME'] = str(tmp / '.pi')
    try:
        records = list(ae.pi_records(tmp))
        assert len(records) == 1
        assert '有效消息' in records[0][4]
    finally:
        os.environ.pop('PI_HOME', None)


def test_pi_records_content_list_form():
    """content 是 list 形式（与 Claude 相同）也支持"""
    tmp = Path(tempfile.mkdtemp())
    _make_pi_session(tmp, 's3', [
        {'type': 'message', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': '列表内容消息'}]}, 'timestamp': '2026-08-15T10:00:00Z'},

    ])
    os.environ['PI_HOME'] = str(tmp / '.pi')
    try:
        records = list(ae.pi_records(tmp))
        assert len(records) == 1
        assert '列表内容消息' in records[0][4]
    finally:
        os.environ.pop('PI_HOME', None)


def test_pi_records_empty_dir():
    """无会话目录时安全返回空"""
    tmp = Path(tempfile.mkdtemp())
    (tmp / '.pi').mkdir(exist_ok=True)
    os.environ['PI_HOME'] = str(tmp / '.pi')
    try:
        records = list(ae.pi_records(tmp))
        assert records == []
    finally:
        os.environ.pop('PI_HOME', None)
