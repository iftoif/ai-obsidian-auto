import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import obsidian_backup as ob


def _has_st() -> bool:
    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction  # noqa
        return True
    except Exception:
        return False


def _mknote(path, title, text):
    import datetime
    return type('N', (), {
        'rel_path': path,
        'title': title,
        'tags': ['x'],
        'mtime': datetime.datetime.now(),
        'size': 100,
        'should_index_chroma': lambda self: True,
        'to_chroma_text': lambda self, t=text: t,
    })()


def _setup(tmp):
    os.environ['HERMES_HOME'] = str(Path(tmp) / 'h')
    ob.DATA_DIR = Path(tmp) / 'h' / 'data' / 'obsidian'
    ob.DATA_DIR.mkdir(parents=True)
    ob.CHROMA_PATH = ob.DATA_DIR / 'chroma_db'
    ob._chroma_client = None
    ob._chroma_collection = None


@pytest.mark.skipif(not _has_st(), reason='sentence-transformers 未安装')
def test_chinese_semantic_ranking():
    """中文语义搜索：相关笔记排第一（bge-small-zh）"""
    tmp = tempfile.mkdtemp()
    _setup(tmp)
    os.environ['OBSIDIAN_CHROMA_EMBEDDING_MODEL'] = 'BAAI/bge-small-zh-v1.5'
    try:
        ob.upsert_note_chroma(_mknote('Wiki/semantic.md', '向量检索', '向量检索 语义搜索 embedding 相似度计算 相关技术笔记'))
        ob.upsert_note_chroma(_mknote('Wiki/weather.md', '普通笔记', '今天天气很好 出门散步 午饭吃了面条'))
        results = ob.search_chroma('向量检索', limit=2)
        assert len(results) >= 1
        assert results[0]['path'] == 'Wiki/semantic.md', f'相关笔记应排第一: {[r["path"] for r in results]}'
    finally:
        os.environ.pop('OBSIDIAN_CHROMA_EMBEDDING_MODEL', None)
