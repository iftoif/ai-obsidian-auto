import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import ai_chat_export as ae


def _setup_export(tmp: Path, tool: str = 'Claude'):
    """造假环境：Claude 会话 + vault + hermes_home"""
    sess = tmp / '.claude' / 'projects' / 'p1'
    sess.mkdir(parents=True, exist_ok=True)
    (sess / 's1.jsonl').write_text('\n'.join([
        json.dumps({'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': '导出测试消息A'}]}, 'timestamp': '2026-08-15T10:00:00Z', 'sessionId': 's1'}),
        json.dumps({'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': '导出测试回复B'}]}, 'timestamp': '2026-08-15T10:00:01Z', 'sessionId': 's1'}),
    ]), encoding='utf-8')
    vault = tmp / 'vault'
    vault.mkdir(exist_ok=True)
    state_dir = tmp / 'hermes' / 'data' / 'obsidian'
    state_dir.mkdir(parents=True, exist_ok=True)
    os.environ['CLAUDE_CONFIG_DIR'] = str(tmp / '.claude')
    return vault, state_dir


def test_export_tool_full_flow():
    """完整导出流程：记录 → Raw md → seen 更新"""
    tmp = Path(tempfile.mkdtemp())
    vault, state_dir = _setup_export(tmp)
    try:
        seen, changed, exported = ae.export_tool('Claude', vault, state_dir)
        assert exported == 2
        md = vault / 'Claude' / 'Chat Logs' / '2026' / '2026-08-15.md'
        assert md.exists()
        content = md.read_text(encoding='utf-8')
        assert '导出测试消息A' in content
        assert '导出测试回复B' in content
        # seen 已保存（幂等基础）
        seen_file = state_dir / 'claude_chat_export_seen.json'
        assert seen_file.exists()
    finally:
        os.environ.pop('CLAUDE_CONFIG_DIR', None)


def test_export_tool_idempotent_second_run():
    """第二次导出无新消息（增量语义）"""
    tmp = Path(tempfile.mkdtemp())
    vault, state_dir = _setup_export(tmp)
    try:
        ae.export_tool('Claude', vault, state_dir)
        _, _, exported2 = ae.export_tool('Claude', vault, state_dir)
        assert exported2 == 0
    finally:
        os.environ.pop('CLAUDE_CONFIG_DIR', None)


def test_export_tool_rolls_over_2mb():
    """单文件超 2MB 滚动到 part-02（R5 修复）"""
    tmp = Path(tempfile.mkdtemp())
    vault, state_dir = _setup_export(tmp)
    try:
        # 注入超大消息
        sess = tmp / '.claude' / 'projects' / 'p1'
        big = 'x' * (2 * 1024 * 1024)
        with open(sess / 'big.jsonl', 'w', encoding='utf-8') as fh:
            fh.write(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': big}]}, 'timestamp': '2026-08-16T10:00:00Z', 'sessionId': 'big'}) + '\n')
        seen, changed, exported = ae.export_tool('Claude', vault, state_dir)
        # 滚动文件存在
        part2 = vault / 'Claude' / 'Chat Logs' / '2026' / '2026-08-16-02.md'
        assert part2.exists(), f'part-02 应生成: {part2}'
    finally:
        os.environ.pop('CLAUDE_CONFIG_DIR', None)


def test_export_tool_empty_source_no_crash():
    """无会话文件时安全返回"""
    tmp = Path(tempfile.mkdtemp())
    vault = tmp / 'vault'; vault.mkdir()
    state_dir = tmp / 'hermes' / 'data' / 'obsidian'
    state_dir.mkdir(parents=True, exist_ok=True)
    # 空目录必须存在（否则 _resolve_client_dir fallback 到真实 ~/.claude）
    empty = tmp / '.claude-empty'
    empty.mkdir(exist_ok=True)
    (empty / 'projects').mkdir(exist_ok=True)
    os.environ['CLAUDE_CONFIG_DIR'] = str(empty)
    try:
        seen, changed, exported = ae.export_tool('Claude', vault, state_dir)
        assert exported == 0
    finally:
        os.environ.pop('CLAUDE_CONFIG_DIR', None)
