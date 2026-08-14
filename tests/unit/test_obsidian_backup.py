import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import obsidian_backup as ob


def _setup(tmp: str):
    vault = Path(tmp) / 'vault'
    (vault / 'Wiki').mkdir(parents=True, exist_ok=True)
    (vault / 'Wiki' / 'a.md').write_text('---\ntitle: 笔记A\ntags:\n  - 测试\n---\n内容A', encoding='utf-8')
    (vault / 'Wiki' / 'b.md').write_text('---\ntitle: 笔记B\n---\n内容B', encoding='utf-8')
    os.environ['OBSIDIAN_VAULT_PATH'] = str(vault)
    os.environ['HERMES_HOME'] = str(Path(tmp) / 'hermes')
    ob.VAULT_PATH = vault
    ob.DATA_DIR = Path(tmp) / 'hermes' / 'data' / 'obsidian'
    ob.DATA_DIR.mkdir(parents=True, exist_ok=True)
    ob.DB_PATH = ob.DATA_DIR / 'fts.db'
    ob.STATE_FILE = ob.DATA_DIR / 'state.json'
    ob.CHROMA_ENABLED = False
    return vault


def test_scan_vault_finds_notes():
    tmp = tempfile.mkdtemp()
    vault = _setup(tmp)
    notes = ob.scan_vault()
    paths = sorted(n.rel_path for n in notes)
    assert paths == ['Wiki/a.md', 'Wiki/b.md']
    # Note 字段
    a = next(n for n in notes if n.rel_path == 'Wiki/a.md')
    assert a.title == '笔记A'
    assert set(a.tags) == {'测试'}
    assert '内容A' in a.body


def test_find_changed_notes_new_and_deleted():
    tmp = tempfile.mkdtemp()
    vault = _setup(tmp)
    notes = ob.scan_vault()
    # 空 state：全部算 changed
    changed, deleted, current = ob.find_changed_notes(notes, {})
    assert len(changed) == 2
    assert deleted == []
    assert current == ['Wiki/a.md', 'Wiki/b.md']
    # 有 state：b 被删
    state = {'Wiki/a.md': {'hash': changed[0].content_hash}, 'Wiki/b.md': {'hash': 'old'}}
    changed2, deleted2, _ = ob.find_changed_notes(notes, state)
    # a 未变，b 哈希变（content_hash 不同）
    assert deleted2 == []
    assert len(changed2) == 1


def test_find_changed_detects_deleted_file():
    tmp = tempfile.mkdtemp()
    vault = _setup(tmp)
    notes = ob.scan_vault()
    state = {n.rel_path: {'hash': n.content_hash} for n in notes}
    state['Wiki/gone.md'] = {'hash': 'x'}  # 已删文件仍在 state
    changed, deleted, current = ob.find_changed_notes(notes, state)
    assert deleted == ['Wiki/gone.md']


def test_sqlite_upsert_delete_search_roundtrip():
    tmp = tempfile.mkdtemp()
    vault = _setup(tmp)
    notes = ob.scan_vault()
    conn = ob.init_sqlite()
    for n in notes:
        ob.upsert_note_sqlite(conn, n)
    # FTS 搜索命中
    res = ob.search_sqlite('内容A')
    assert len(res) >= 1
    assert res[0]['path'] == 'Wiki/a.md'
    # 删除
    ob.delete_note_sqlite(conn, 'Wiki/a.md')
    res2 = ob.search_sqlite('内容A')
    assert len(res2) == 0
    conn.close()


def test_state_roundtrip():
    tmp = tempfile.mkdtemp()
    vault = _setup(tmp)
    notes = ob.scan_vault()
    st = {n.rel_path: {'hash': n.content_hash, 'mtime': n.mtime.isoformat(), 'title': n.title} for n in notes}
    ob.save_state(st)
    loaded = ob.load_state()
    assert loaded == st
    # 损坏的 state 安全降级
    ob.STATE_FILE.write_text('{corrupt', encoding='utf-8')
    assert ob.load_state() == {}


def test_note_hash_changes_on_edit():
    tmp = tempfile.mkdtemp()
    vault = _setup(tmp)
    notes = ob.scan_vault()
    a = next(n for n in notes if n.rel_path == 'Wiki/a.md')
    h1 = a.content_hash
    # 修改文件后重新扫描
    (vault / 'Wiki' / 'a.md').write_text('---\ntitle: 笔记A\n---\n内容A改了', encoding='utf-8')
    notes2 = ob.scan_vault()
    a2 = next(n for n in notes2 if n.rel_path == 'Wiki/a.md')
    assert a2.content_hash != h1
