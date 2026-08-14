import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import ai_chat_export as ae


def test_append_entry_returns_false_on_redact_failure():
    """redact 失败（marker）→ 返回 False → 调用方不入 seen（下次重试）"""
    orig = ae.redact_for_raw_log
    ae.redact_for_raw_log = lambda text, source: '[REDACT-UNAVAILABLE]'
    try:
        vault = Path(tempfile.mkdtemp())
        roll = {}
        ts = ae.dt.datetime(2026, 8, 15, 10, 0, 0, tzinfo=ae.dt.timezone.utc)
        ok = ae.append_entry(vault, 'Claude', roll, ts, 'user', '原文', Path('s.jsonl'), 1, 's1', '')
        assert ok is False, 'redact 失败应返回 False'
    finally:
        ae.redact_for_raw_log = orig


def test_append_entry_returns_true_on_success():
    """正常脱敏 → 返回 True"""
    vault = Path(tempfile.mkdtemp())
    roll = {}
    ts = ae.dt.datetime(2026, 8, 15, 10, 0, 0, tzinfo=ae.dt.timezone.utc)
    ok = ae.append_entry(vault, 'Claude', roll, ts, 'user', '正常消息', Path('s.jsonl'), 2, 's1', '')
    assert ok is True


def test_export_tool_retries_failed_redact():
    """redact 失败的消息不入 seen → 第二次运行重试"""
    import json
    tmp = Path(tempfile.mkdtemp())
    sess = tmp / '.claude' / 'projects' / 'p1'
    sess.mkdir(parents=True)
    (sess / 's1.jsonl').write_text(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': '需要重试的消息'}]}, 'timestamp': '2026-08-15T10:00:00Z', 'sessionId': 's1'}), encoding='utf-8')
    vault = tmp / 'vault'; vault.mkdir()
    state_dir = tmp / 'h' / 'data' / 'obsidian'
    state_dir.mkdir(parents=True)
    os.environ['CLAUDE_CONFIG_DIR'] = str(tmp / '.claude')
    orig = ae.redact_for_raw_log
    ae.redact_for_raw_log = lambda text, source: '[REDACT-UNAVAILABLE]'
    try:
        # 第一次：redact 失败 → 消息被写 marker 但不入 seen
        _, _, exported1 = ae.export_tool('Claude', vault, state_dir)
        assert exported1 == 1
        # 恢复 redact → 第二次应重试（seen 里没有）
        ae.redact_for_raw_log = orig
        _, _, exported2 = ae.export_tool('Claude', vault, state_dir)
        assert exported2 == 1, 'redact 失败消息应在恢复后重试导出'
        # 第三次：已入 seen → 幂等
        _, _, exported3 = ae.export_tool('Claude', vault, state_dir)
        assert exported3 == 0
    finally:
        ae.redact_for_raw_log = orig
        os.environ.pop('CLAUDE_CONFIG_DIR', None)
