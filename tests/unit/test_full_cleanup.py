import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

import obsidian_backup as ob


def _setup(tmp):
    vault = Path(tmp) / 'vault'
    (vault / 'Wiki').mkdir(parents=True)
    (vault / 'Wiki' / 'a.md').write_text('---\ntitle: A\n---\n内容A', encoding='utf-8')
    (vault / 'Wiki' / 'b.md').write_text('---\ntitle: B\n---\n内容B', encoding='utf-8')
    os.environ['OBSIDIAN_VAULT_PATH'] = str(vault)
    os.environ['HERMES_HOME'] = str(Path(tmp) / 'hermes')
    os.environ['OBSIDIAN_CHROMA_ENABLED'] = '0'
    ob.VAULT_PATH = vault
    ob.DATA_DIR = Path(tmp) / 'hermes' / 'data' / 'obsidian'
    ob.DATA_DIR.mkdir(parents=True, exist_ok=True)
    ob.DB_PATH = ob.DATA_DIR / 'obsidian_fts.db'
    ob.STATE_FILE = ob.DATA_DIR / 'state.json'
    return vault


def test_full_cleans_stale_entries():
    tmp = tempfile.mkdtemp()
    vault = _setup(tmp)
    r = subprocess.run([sys.executable, str(ROOT / 'scripts/obsidian_backup.py')], capture_output=True, text=True, env=os.environ.copy(), cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
    (vault / 'Wiki' / 'b.md').unlink()
    r = subprocess.run([sys.executable, str(ROOT / 'scripts/obsidian_backup.py'), '--full'], capture_output=True, text=True, env=os.environ.copy(), cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
    conn = sqlite3.connect(str(ob.DB_PATH))
    rows = conn.execute('SELECT path FROM notes').fetchall()
    conn.close()
    paths = [x[0] for x in rows]
    assert 'Wiki/b.md' not in paths, f'b.md 残留: {paths}'
    assert 'Wiki/a.md' in paths


def test_search_limit_works():
    tmp = tempfile.mkdtemp()
    vault = _setup(tmp)
    (vault / 'Wiki' / 'c.md').write_text('---\ntitle: C\n---\n内容A 重复关键词', encoding='utf-8')
    (vault / 'Wiki' / 'd.md').write_text('---\ntitle: D\n---\n内容A 再重复', encoding='utf-8')
    env = os.environ.copy()
    r = subprocess.run([sys.executable, str(ROOT / 'scripts/obsidian_backup.py')], capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
    r1 = subprocess.run([sys.executable, str(ROOT / 'scripts/obsidian_backup.py'), '--search', '内容A', '--limit', '1'], capture_output=True, text=True, env=env, cwd=str(ROOT))
    r3 = subprocess.run([sys.executable, str(ROOT / 'scripts/obsidian_backup.py'), '--search', '内容A'], capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert r1.stdout.count('📄') == 1, 'limit=1 应返回 1 条'
    assert r3.stdout.count('📄') >= 2, '默认应返回多条'


def test_search_like_wildcard_escaped():
    tmp = tempfile.mkdtemp()
    vault = _setup(tmp)
    (vault / 'Wiki' / 'pct.md').write_text('---\ntitle: 百分比\n---\n进度 50% 完成', encoding='utf-8')
    env = os.environ.copy()
    r = subprocess.run([sys.executable, str(ROOT / 'scripts/obsidian_backup.py')], capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert r.returncode == 0
    rp = subprocess.run([sys.executable, str(ROOT / 'scripts/obsidian_backup.py'), '--search', '%'], capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert rp.stdout.count('📄') == 1, '搜索 % 应只命中含%的笔记'
