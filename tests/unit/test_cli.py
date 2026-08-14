import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _make_vault(tmp: str):
    vault = Path(tmp) / 'vault'
    (vault / 'Wiki').mkdir(parents=True, exist_ok=True)
    (vault / 'Wiki' / 'a.md').write_text('---\ntitle: CLI测试\ntags: [测试]\n---\n命令行备份内容', encoding='utf-8')
    (vault / 'CLAUDE.md').write_text('# 项目说明', encoding='utf-8')
    return vault


def _run(args: list, tmp: str):
    env = os.environ.copy()
    env['OBSIDIAN_VAULT_PATH'] = str(Path(tmp) / 'vault')
    env['HERMES_HOME'] = str(Path(tmp) / 'hermes')
    env['OBSIDIAN_CHROMA_ENABLED'] = '0'
    r = subprocess.run([sys.executable, str(ROOT / 'scripts/obsidian_backup.py')] + args,
                       capture_output=True, text=True, env=env, cwd=str(ROOT))
    return r


def test_cli_backup_default():
    """obsidian_backup.py（默认增量）退出 0 且输出完成"""
    tmp = tempfile.mkdtemp()
    _make_vault(tmp)
    r = _run([], tmp)
    assert r.returncode == 0, r.stderr
    assert '备份完成' in r.stdout or '无变更' in r.stdout


def test_cli_stats():
    """--stats 输出统计（笔记量/标签/DB）"""
    tmp = tempfile.mkdtemp()
    vault = _make_vault(tmp)
    _run([], tmp)  # 先备份
    r = _run(['--stats'], tmp)
    assert r.returncode == 0
    assert '笔记总量' in r.stdout
    assert 'Wiki' in r.stdout


def test_cli_search_fts():
    """--search 命中内容"""
    tmp = tempfile.mkdtemp()
    _make_vault(tmp)
    _run([], tmp)
    r = _run(['--search', '命令行'], tmp)
    assert r.returncode == 0
    assert 'CLI测试' in r.stdout


def test_cli_full_rebuild():
    """--full 全量重建退出 0"""
    tmp = tempfile.mkdtemp()
    _make_vault(tmp)
    r = _run(['--full'], tmp)
    assert r.returncode == 0, r.stderr


def test_cli_no_db_search_graceful():
    """无 DB 时 --search 给提示而不是崩溃"""
    tmp = tempfile.mkdtemp()
    _make_vault(tmp)
    r = _run(['--search', 'x'], tmp)
    assert r.returncode == 0
    assert '数据库不存在' in r.stdout or '无结果' in r.stdout
