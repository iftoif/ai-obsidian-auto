import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

import ai_chat_export as ae


def test_parse_time_seconds():
    # 秒级时间戳
    d = ae.parse_time(1700000000)
    assert d.year == 2023


def test_parse_time_millis():
    # 毫秒级
    d = ae.parse_time(1700000000000)
    assert d.year == 2023


def test_parse_time_micros():
    # 微秒级（BUG-2: 曾 ValueError year out of range）
    d = ae.parse_time(1_700_000_000_000_001)
    assert d.year == 2023


def test_parse_time_huge_clamped():
    # 极大值 → clamp 到当前时间，不抛异常
    d = ae.parse_time(9_999_999_999_999_999)
    assert d.year >= 2020


def test_parse_time_string():
    d = ae.parse_time('2026-08-15T10:00:00Z')
    assert d.year == 2026


def test_parse_time_none_returns_now():
    # 非法值 → 当前时间兜底
    import datetime as dt
    d = ae.parse_time('garbage')
    assert abs((d - dt.datetime.now(ae.TZ)).total_seconds()) < 60


def test_parse_time_negative():
    # 负数 → fromtimestamp 会抛异常 → 兜底当前时间
    import datetime as dt
    d = ae.parse_time(-100)
    assert d.year >= 2020


def test_event_hash_includes_line_no():
    # 相同文本不同行号 → 不同 hash（R12 修复：重复消息不丢）
    h1 = ae.event_hash('Claude', 'sess-1', 'user', '继续', 10)
    h2 = ae.event_hash('Claude', 'sess-1', 'user', '继续', 20)
    assert h1 != h2


def test_event_hash_same_line_same_hash():
    # 相同文本相同行号 → 相同 hash（幂等去重）
    h1 = ae.event_hash('Claude', 'sess-1', 'user', '继续', 10)
    h2 = ae.event_hash('Claude', 'sess-1', 'user', '继续', 10)
    assert h1 == h2


def test_event_hash_backwards_compatible():
    # 无 line_no（None）也可用
    h = ae.event_hash('Claude', 'sess-1', 'user', 'text')
    assert isinstance(h, str) and len(h) == 64
