import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import obsidian_backup as ob
import redact_secrets as rs


def _vault_with(tmp, name, fm, body):
    vault = Path(tmp) / 'vault'
    (vault / 'Wiki').mkdir(parents=True)
    (vault / 'Wiki' / name).write_text(fm + body, encoding='utf-8')
    os.environ['OBSIDIAN_VAULT_PATH'] = str(vault)
    ob.VAULT_PATH = vault
    return vault


def test_note_to_record_fields():
    tmp = tempfile.mkdtemp()
    _vault_with(tmp, 'n.md', '---\ntitle: 记录测试\ntags: [t1, t2]\n---\n', '正文内容')
    n = ob.scan_vault()[0]
    rec = n.to_record()
    assert rec['path'] == 'Wiki/n.md'
    assert rec['title'] == '记录测试'
    assert set(rec['tags'].split(',')) == {'t1', 't2'}  # 顺序不保证
    assert '正文内容' in rec['content']
    assert rec['category'] == 'Wiki'
    assert len(rec['hash']) == 64


def test_note_to_chroma_text_contains_meta():
    tmp = tempfile.mkdtemp()
    _vault_with(tmp, 'n.md', '---\ntitle: Chroma文本\ntags: [ai]\n---\n', '向量化内容')
    n = ob.scan_vault()[0]
    txt = n.to_chroma_text()
    assert 'Chroma文本' in txt
    assert '向量化内容' in txt
    assert 'ai' in txt


def test_wikilinks_extraction():
    tmp = tempfile.mkdtemp()
    _vault_with(tmp, 'n.md', '---\ntitle: x\n---\n', '链接到 [[目标笔记]] 和 [[别名|显示文本]]\n')
    n = ob.scan_vault()[0]
    assert '目标笔记' in n.wikilinks
    assert '别名' in n.wikilinks


def test_aliases_extraction():
    tmp = tempfile.mkdtemp()
    _vault_with(tmp, 'n.md', '---\ntitle: x\n---\n', '正文\nalias: [别名A, 别名B]\n')
    n = ob.scan_vault()[0]
    assert '别名A' in n.aliases


def test_secret_group_password_uses_group3():
    fs = rs.find_secrets('password=abcdef1234567890abcdef12')
    assert len(fs) >= 1
    f = fs[0]
    assert len(f.secret) >= 16


def test_redact_text_keeps_context():
    text = '我的密钥是 sk-1234567890abcdefghij1234567890，请保密'
    out = rs.redact_text(text, source='t', store=False)
    assert '我的密钥是' in out
    assert '请保密' in out
    assert 'sk-1234567890abcdefghij1234567890' not in out


def test_keychain_available_no_crash():
    # 平台相关：只验证调用不抛异常
    rs.keychain_available()
    assert True
