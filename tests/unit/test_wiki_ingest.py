import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import wiki_ingest as wi


def test_build_prompt_url():
    ns = argparse.Namespace(url='https://example.com/x', file=None, text=None, title=None, note=None)
    p = wi.build_prompt(ns, Path('/vault'))
    assert 'llm-wiki-ingest' in p
    assert 'https://example.com/x' in p
    assert 'Vault 根目录: /vault' in p


def test_build_prompt_text():
    ns = argparse.Namespace(url=None, file=None, text='正文内容', title='标题', note='补充要求')
    p = wi.build_prompt(ns, Path('/vault'))
    assert '正文内容' in p
    assert '标题' in p
    assert '补充要求' in p


def test_build_prompt_file_relative_to_vault():
    ns = argparse.Namespace(url=None, file='Clippings/a.md', text=None, title=None, note=None)
    p = wi.build_prompt(ns, Path('/vault'))
    assert 'Clippings/a.md' in p


def test_fetch_clean_markdown_failure_returns_empty():
    # 网络不可达/超时 → 空串（不抛异常）
    assert wi.fetch_clean_markdown('http://127.0.0.1:1/nonexistent') == ''


def test_default_vault_env_override():
    import os
    os.environ['OBSIDIAN_VAULT_PATH'] = '/custom/vault'
    assert str(wi.default_vault()) == '/custom/vault'
    os.environ.pop('OBSIDIAN_VAULT_PATH')
