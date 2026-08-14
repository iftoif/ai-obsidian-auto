import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import redact_secrets as rs


def test_redact_sk_key():
    out = rs.redact_text('my key sk-1234567890abcdefghij here', source='t', store=False)
    assert 'sk-1234567890abcdefghij' not in out
    assert '[SECRET:' in out


def test_redact_ghp_token():
    out = rs.redact_text('token ghp_123456789012345678901234 here', source='t', store=False)
    assert 'ghp_123456789012345678901234' not in out


def test_existing_ref_not_double_redacted():
    # R13 修复：已脱敏引用不被二次污染
    c = '[SECRET:api-key:sec_xyz]'
    out = rs.redact_text(c, source='t', store=False)
    assert out == c


def test_existing_ref_with_hyphen_not_double_redacted():
    # R13 修复：sec_id 含连字符时不被二次污染（SECRET_REF_RE 含 -）
    c = '[SECRET:api-key:sec_xy-z]'
    out = rs.redact_text(c, source='t', store=False)
    assert out == c


def test_redact_skips_redacted_placeholder():
    # 显式 REDACTED 占位符跳过
    out = rs.redact_text('key = REDACTED_12345', source='t', store=False)
    assert 'REDACTED_12345' in out


def test_find_secrets_jwt():
    findings = rs.find_secrets('token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c')
    assert len(findings) >= 1


def test_find_secrets_private_key_block():
    pk = '-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA\n-----END RSA PRIVATE KEY-----'
    findings = rs.find_secrets(pk)
    assert any(f.type == 'private-key' for f in findings)


def test_unstored_fail_closed_when_no_keychain():
    # 无 keychain 时 fail-closed → UNSTORED- 引用（不抛异常）
    out = rs.redact_text('api key sk-1234567890abcdefghij1234567890', source='t', store=True)
    assert 'sk-1234567890abcdefghij' not in out
    assert 'UNSTORED-' in out or 'sec_' in out
