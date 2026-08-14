import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

import ai_chat_export as ae


def _setup_tools(tmp: Path):
    # Claude 会话
    c = tmp / '.claude' / 'projects' / 'p1'
    c.mkdir(parents=True)
    (c / 's1.jsonl').write_text(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': 'Claude消息'}]}, 'timestamp': '2026-08-15T10:00:00Z', 'sessionId': 's1'}), encoding='utf-8')
    # Pi 会话
    p = tmp / '.pi' / 'agent' / 'sessions'
    p.mkdir(parents=True)
    (p / 'session_s1.jsonl').write_text(json.dumps({'type': 'message', 'message': {'role': 'user', 'content': 'Pi消息'}, 'timestamp': '2026-08-15T10:00:00Z'}), encoding='utf-8')
    os.environ['CLAUDE_CONFIG_DIR'] = str(tmp / '.claude')
    os.environ['PI_HOME'] = str(tmp / '.pi')
    os.environ['DSH_HOME'] = str(tmp / '.dsh-nonexistent')
    return tmp / 'vault', tmp / 'hermes' / 'data' / 'obsidian'


def test_export_tool_all_tools():
    """--tool all 导出 Claude + Pi（DSH 无目录跳过）"""
    tmp = Path(tempfile.mkdtemp())
    vault, state_dir = _setup_tools(tmp)
    vault.mkdir(exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        # main 层把 all 展开为三个工具，这里模拟正确用法
        total = 0
        for tool in ('Claude', 'Pi', 'DSH'):
            seen, changed, exported = ae.export_tool(tool, vault, state_dir)
            total += exported
        # Claude 1 条 + Pi 1 条（DSH 无目录 0 条）
        assert total >= 2, f'total={total}'
        assert (vault / 'Claude' / 'Chat Logs' / '2026' / '2026-08-15.md').exists()
        assert (vault / 'Pi' / 'Chat Logs' / '2026' / '2026-08-15.md').exists()
    finally:
        os.environ.pop('CLAUDE_CONFIG_DIR', None)
        os.environ.pop('PI_HOME', None)
        os.environ.pop('DSH_HOME', None)


def test_export_tool_unknown_tool():
    """未知 tool 名 → 空 records 安全返回"""
    tmp = Path(tempfile.mkdtemp())
    vault = tmp / 'vault'; vault.mkdir()
    state_dir = tmp / 'h' / 'data' / 'obsidian'
    state_dir.mkdir(parents=True)
    seen, changed, exported = ae.export_tool('Unknown', vault, state_dir)
    assert exported == 0


def test_cli_main_dry_run_flag():
    """ai_chat_export.py 支持 --tool 参数（argparse 入口）"""
    tmp = Path(tempfile.mkdtemp())
    vault = tmp / 'vault'; vault.mkdir()
    env = os.environ.copy()
    env['OBSIDIAN_VAULT_PATH'] = str(vault)
    env['HERMES_HOME'] = str(tmp / 'h')
    env['CLAUDE_CONFIG_DIR'] = str(tmp / '.claude-empty')
    (tmp / '.claude-empty' / 'projects').mkdir(parents=True)
    r = subprocess.run([sys.executable, str(ROOT / 'scripts/ai_chat_export.py'), '--tool', 'Claude'],
                       capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
    assert '无新消息' in r.stdout or '导出完成' in r.stdout


def test_put_secret_fails_closed_on_linux():
    """keychain 不可用时 put_secret 抛 RuntimeError（fail-closed）"""
    import redact_secrets as rs
    if rs.keychain_available():
        import pytest; pytest.skip('keychain available on this platform')
    try:
        rs.put_secret('sometestsecret', 'api-key')
        assert False, '应抛异常'
    except RuntimeError:
        pass


def test_redact_paths_corrupt_file_skipped():
    """损坏文件（无法解码）跳过不崩溃"""
    import redact_secrets as rs
    import io, contextlib
    tmp = Path(tempfile.mkdtemp())
    (tmp / 'bad.md').write_bytes(b'\xff\xfe\x00 binary garbage')
    (tmp / 'ok.md').write_text('正常内容', encoding='utf-8')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rs.scan_paths([tmp])
    assert 'TOTAL findings=' in buf.getvalue()
