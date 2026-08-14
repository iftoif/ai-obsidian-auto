import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

from obsidian_backup import parse_frontmatter, get_tags, get_title


def test_fm_inline_list():
    fm, _ = parse_frontmatter('---\ntags: [a, b]\n---\nbody')
    assert set(get_tags(fm)) == {'a', 'b'}


def test_fm_block_list():
    # R10 修复：block 风格 tags
    fm, _ = parse_frontmatter('---\ntags:\n  - ai\n  - obsidian\n---\nbody')
    assert set(get_tags(fm)) == {'ai', 'obsidian'}


def test_fm_empty_tags():
    # 空 tags → 空列表，不污染
    fm, _ = parse_frontmatter('---\ntags:\n---\nbody')
    assert get_tags(fm) == []


def test_fm_scalar_not_overwritten_by_indent():
    # R14 修复：标量值后跟缩进行不被替换成 list
    fm, _ = parse_frontmatter('---\ntitle: note\n  - child\n---\nbody')
    assert fm['title'] == 'note'
    assert get_title(Path('x.md'), fm) == 'note'


def test_fm_bool():
    fm, _ = parse_frontmatter('---\ndraft: true\n---\nx')
    assert fm.get('draft') is True


def test_fm_no_frontmatter():
    fm, body = parse_frontmatter('纯正文')
    assert fm == {}
    assert body == '纯正文'


def test_fm_title_fallback_filename():
    # 无 title 时用文件名
    fm, _ = parse_frontmatter('---\ntags: [x]\n---\nbody')
    assert get_title(Path('my-note.md'), fm) == 'my note'


def test_fm_quoted_values():
    fm, _ = parse_frontmatter('---\ntitle: "带引号标题"\n---\nx')
    assert fm['title'] == '带引号标题'
