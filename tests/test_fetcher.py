from metadata.fetcher import format_duration, format_views, size_human


def test_format_duration_minutes_seconds():
    assert format_duration(125) == "2:05"


def test_format_duration_hours_minutes_seconds():
    assert format_duration(3665) == "1:01:05"


def test_format_views_units():
    assert format_views(123) == "123"
    assert format_views(4_500) == "4K"
    assert format_views(2_500_000) == "2.5M"
    assert format_views(5_000_000_000) == "5.0B"


def test_size_human_bytes():
    assert size_human(800) == "800 B"
    assert size_human(10240) == "10 KB"
    assert size_human(1_572_864) == "2 MB"
    assert size_human(2_147_483_648) == "2.0 GB"
