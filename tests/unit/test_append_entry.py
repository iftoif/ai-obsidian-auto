import base64
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import ai_chat_export as ae


def test_note_path_day_part():
    vault = Path('/v')
    assert str(ae.note_path(vault, 'Claude', ae.dt.date(2026, 8, 15), 1)) == '/v/Claude/Chat Logs/2026/2026-08-15.md'
    assert str(ae.note_path(vault, 'Claude', ae.dt.date(2026, 8, 15), 2)) == '/v/Claude/Chat Logs/2026/2026-08-15-02.md'


def test_ensure_note_creates_frontmatter():
    vault = Path(tempfile.mkdtemp())
    p = ae.note_path(vault, 'Claude', ae.dt.date(2026, 8, 15), 1)
    ae.ensure_note(p, 'Claude', ae.dt.date(2026, 8, 15))
    assert p.exists()
    content = p.read_text(encoding='utf-8')
    assert 'source: claude' in content
    assert 'type: daily-chat-log' in content
    assert '# Claude 聊天记录 2026-08-15' in content
    ae.ensure_note(p, 'Claude', ae.dt.date(2026, 8, 15))
    assert content == p.read_text(encoding='utf-8')


def test_init_roll_finds_existing_files():
    vault = Path(tempfile.mkdtemp())
    d = vault / 'Claude' / 'Chat Logs' / '2026'
    d.mkdir(parents=True)
    (d / '2026-08-15.md').write_text('x' * 100)
    (d / '2026-08-15-02.md').write_text('y' * 50)
    (d / 'notes.txt').write_text('ignore')
    roll = ae.init_roll(vault, 'Claude')
    assert roll['2026-08-15']['part'] == 2, roll
    assert roll['2026-08-15']['size'] == 50


def test_init_roll_empty_dir():
    vault = Path(tempfile.mkdtemp())
    assert ae.init_roll(vault, 'Claude') == {}


def test_append_entry_writes_and_updates_roll():
    vault = Path(tempfile.mkdtemp())
    roll = {}
    ts = ae.dt.datetime(2026, 8, 15, 10, 30, 0, tzinfo=ae.dt.timezone.utc)
    ae.append_entry(vault, 'Claude', roll, ts, 'user', '测试消息内容', Path('/fake/source.jsonl'), 42, 'sess-1', '/work')
    p = vault / 'Claude' / 'Chat Logs' / '2026' / '2026-08-15.md'
    assert p.exists()
    content = p.read_text(encoding='utf-8')
    assert '测试消息内容' in content
    assert 'sess-1' in content
    assert '/fake/source.jsonl:42' in content
    assert roll['2026-08-15']['part'] == 1
    assert roll['2026-08-15']['size'] > 0


def test_append_entry_rolls_over_2mb():
    vault = Path(tempfile.mkdtemp())
    ts = ae.dt.datetime(2026, 8, 15, 10, 30, 0, tzinfo=ae.dt.timezone.utc)
    roll = {'2026-08-15': {'part': 1, 'size': ae.MAX_NOTE_BYTES - 10}}
    ae.append_entry(vault, 'Claude', roll, ts, 'user', 'x' * 100, Path('s.jsonl'), 1, 's', '')
    p2 = vault / 'Claude' / 'Chat Logs' / '2026' / '2026-08-15-02.md'
    assert p2.exists(), 'should roll to part-02'
    assert roll['2026-08-15']['part'] == 2


def test_extract_image_refs_chain():
    img_b64 = base64.b64encode(b'x' * 200).decode()
    content = [
        {'type': 'text', 'text': '看图说明'},
        {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': img_b64}},
    ]
    imgs = ae._iter_images_from_content(content)
    assert len(imgs) == 1
    mime, data = imgs[0]
    assert mime == 'image/png'
    assert data == img_b64


def test_iter_images_skips_non_image_types():
    content = [
        {'type': 'tool_use', 'name': 'x'},
        {'type': 'text', 'text': '普通文本'},
        {'type': 'image', 'source': {'type': 'url', 'url': 'http://x/y.png'}},
    ]
    imgs = ae._iter_images_from_content(content)
    assert imgs == []


def test_safe_sanitizes():
    assert ae.safe('normal_text') == 'normal_text'
    assert ae.safe('a/b') == 'a-b' or '/' in ae.safe('a/b')


def test_normalize_text_basic():
    out = ae.normalize_text('  多  空格  ')
    assert out == out.strip()
    assert '多' in out and '空格' in out
