from datetime import date

import pytest

from app.services.analytics import range_start


def test_range_start_for_30_days() -> None:
    start = range_start("30d", date(2026, 6, 22))
    assert start == date(2026, 5, 24)


def test_range_start_rejects_unknown_range() -> None:
    with pytest.raises(ValueError):
        range_start("7d", date(2026, 6, 22))

