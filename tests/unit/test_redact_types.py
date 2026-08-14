import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import redact_secrets as rs


def test_redact_all_high_value_secrets():
    cases = [
        'Authorization: Bearer abcdef1234567890abcdef12',
        'cookie=abcdef1234567890abcdef12',
        'PASSWORD=abcdef1234567890abcdef12',
        'AKIAIOSFODNN7EXAMPLE',
        'postgres://user:abcdef1234567890@host:5432/db',
        'api_key=sk-1234567890abcdefghijklmnop',
    ]
    for text in cases:
        out = rs.redact_text(text, source='t', store=False)
        assert '[SECRET:' in out, (text, out)


def test_find_secrets_authorization_header():
    fs = rs.find_secrets('Authorization: Bearer abcdef1234567890abcdef12')
    assert any(f.type == 'authorization-bearer' for f in fs)


def test_find_secrets_db_url():
    fs = rs.find_secrets('postgres://user:abcdef1234567890@host:5432/db')
    assert any(f.type == 'db-url-password' for f in fs)


def test_find_secrets_skips_short():
    assert len(rs.find_secrets('password=abc')) == 0


def test_secret_group_bearer_extracts_secret():
    fs = rs.find_secrets('Authorization: Bearer abcdef1234567890abcdef12')
    f = next(f for f in fs if f.type == 'authorization-bearer')
    assert f.secret == 'abcdef1234567890abcdef12'


def test_overlaps_logic():
    assert rs._overlaps((0, 5), (3, 8)) is True
    assert rs._overlaps((0, 5), (5, 10)) is False
    assert rs._overlaps((0, 10), (2, 3)) is True


def test_redact_no_secrets_unchanged():
    text = '这是一段完全正常的文本内容'
    assert rs.redact_text(text, source='t', store=False) == text


def test_multiple_secrets_all_redacted():
    text = 'key1=sk-1234567890abcdefghij and key2=ghp_123456789012345678901234'
    out = rs.redact_text(text, source='t', store=False)
    assert 'sk-1234567890abcdefghij' not in out
    assert 'ghp_123456789012345678901234' not in out
    assert out.count('[SECRET:') >= 2
