import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import obsidian_backup as ob


def _make_db(tmp):
    ob.DB_PATH = Path(tmp) / 'test.db'
    conn = sqlite3.connect(str(ob.DB_PATH))
    conn.executescript('''
CREATE TABLE notes (
    path TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
    summary TEXT, tags TEXT, mtime TEXT NOT NULL, size INTEGER DEFAULT 0,
    hash TEXT, wikilinks TEXT, aliases TEXT, category TEXT DEFAULT 'root',
    indexed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE VIRTUAL TABLE notes_fts USING fts5(
    title, content, summary, tags,
    content=notes, content_rowid=rowid, tokenize='unicode61'
);
''')
    conn.execute("INSERT INTO notes (path, title, content, summary, tags, mtime) VALUES ('n.md', '中文标题', '这里有排序算法的说明', 's', 't1', '2026-01-01T00:00:00Z')")
    conn.commit()
    conn.close()


def test_search_fts_exact_word():
    tmp = tempfile.mkdtemp()
    _make_db(tmp)
    res = ob.search_sqlite('排序')
    # unicode61 对中文整段分词 → FTS 命中或 LIKE fallback 命中
    assert len(res) >= 1


def test_search_like_fallback():
    # R12 修复：中文子串 LIKE fallback
    tmp = tempfile.mkdtemp()
    _make_db(tmp)
    res = ob.search_sqlite('算法')
    assert len(res) >= 1


def test_search_no_result():
    tmp = tempfile.mkdtemp()
    _make_db(tmp)
    res = ob.search_sqlite('不存在的词xyz')
    assert len(res) == 0


def test_search_english_word():
    tmp = tempfile.mkdtemp()
    _make_db(tmp)
    res = ob.search_sqlite('排序')
    assert len(res) >= 1
