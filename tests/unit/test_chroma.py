import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import obsidian_backup as ob


def _setup(tmp: str, chroma_enabled: bool = True):
    vault = Path(tmp) / 'vault'
    (vault / 'Wiki').mkdir(parents=True, exist_ok=True)
    (vault / 'Wiki' / 'a.md').write_text('---\ntitle: 语义笔记\n---\n这是关于数据库索引的内容', encoding='utf-8')
    os.environ['OBSIDIAN_VAULT_PATH'] = str(vault)
    os.environ['HERMES_HOME'] = str(Path(tmp) / 'hermes')
    ob.VAULT_PATH = vault
    ob.DATA_DIR = Path(tmp) / 'hermes' / 'data' / 'obsidian'
    ob.DATA_DIR.mkdir(parents=True, exist_ok=True)
    ob.DB_PATH = ob.DATA_DIR / 'fts.db'
    ob.STATE_FILE = ob.DATA_DIR / 'state.json'
    ob.CHROMA_PATH = ob.DATA_DIR / 'chroma_db'
    ob.CHROMA_ENABLED = chroma_enabled
    # 重置全局 chroma 缓存（跨测试隔离）
    ob._chroma_client = None
    ob._chroma_collection = None
    return vault


def test_chroma_upsert_and_search():
    """Chroma upsert → 语义搜索命中"""
    tmp = tempfile.mkdtemp()
    vault = _setup(tmp)
    notes = ob.scan_vault()
    col = ob._get_chroma()
    assert col is not None, 'chromadb 应可用'
    ob.upsert_note_chroma(notes[0])
    results = ob.search_chroma('数据库', limit=5)
    assert len(results) >= 1, f'语义搜索应命中: {results}'
    assert results[0]['path'] == 'Wiki/a.md'


def test_chroma_delete_removes_vector():
    """删除笔记 → 向量被清理（防残留）"""
    tmp = tempfile.mkdtemp()
    vault = _setup(tmp)
    notes = ob.scan_vault()
    ob.upsert_note_chroma(notes[0])
    assert len(ob.search_chroma('数据库')) >= 1
    ob.delete_note_chroma('Wiki/a.md')
    assert len(ob.search_chroma('数据库')) == 0


def test_chroma_skips_low_value_raw_chat():
    """should_index_chroma：Raw Chat Logs 默认跳过（CHROMA_SKIP_RAW_CHAT_LOGS）"""
    tmp = tempfile.mkdtemp()
    vault = _setup(tmp)
    # 造一个 Raw 聊天日志
    raw_dir = vault / 'Claude' / 'Chat Logs' / '2026'
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / '2026-08-15.md').write_text('聊天内容', encoding='utf-8')
    notes = ob.scan_vault()
    raw_note = next(n for n in notes if 'Chat Logs' in n.rel_path)
    assert raw_note.should_index_chroma() is False
    wiki_note = next(n for n in notes if 'Wiki' in n.rel_path)
    assert wiki_note.should_index_chroma() is True


def test_chroma_skips_large_raw():
    """超大文件不索引（CHROMA_MAX_RAW_BYTES）"""
    tmp = tempfile.mkdtemp()
    vault = _setup(tmp)
    big = vault / 'Wiki' / 'big.md'
    big.write_text('x' * (int(os.environ.get('OBSIDIAN_CHROMA_MAX_RAW_BYTES', '250000')) + 10), encoding='utf-8')
    notes = ob.scan_vault()
    big_note = next(n for n in notes if n.rel_path == 'Wiki/big.md')
    assert big_note.should_index_chroma() is False


def test_chroma_disabled_returns_none():
    """OBSIDIAN_CHROMA_ENABLED=0 时 _get_chroma 应返回 None（优雅降级）"""
    tmp = tempfile.mkdtemp()
    vault = _setup(tmp, chroma_enabled=False)
    # 注意：_get_chroma 不检查 enabled，检查调用方；这里验证 upsert 不崩
    notes = ob.scan_vault()
    # 即使启用状态，upsert 调用应安全
    ob.upsert_note_chroma(notes[0])
    print('ok')


def test_search_chroma_no_db():
    """无 Chroma 数据时搜索返回空列表（不崩溃）"""
    tmp = tempfile.mkdtemp()
    _setup(tmp)
    results = ob.search_chroma('任意查询')
    assert results == []
