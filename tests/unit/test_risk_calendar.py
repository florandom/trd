"""UTC evaluation of reviewed local sessions, including DST gaps and repeated hours."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfoNotFoundError

import pytest
from pydantic import ValidationError

from backend.domain.risk_contracts import SessionCalendar, SessionWindow


def calendar(**changes):
    return SessionCalendar(
        **dict(
            timezone="Europe/Rome",
            windows=(
                SessionWindow(weekday=0, start_minute=9 * 60, end_minute=12 * 60),
                SessionWindow(weekday=0, start_minute=13 * 60, end_minute=17 * 60),
            ),
        )
        | changes
    )


@pytest.mark.parametrize(
    "hour,minute,opened",
    [
        (6, 59, False),
        (7, 0, True),
        (9, 59, True),
        (10, 0, False),
        (10, 59, False),
        (11, 0, True),
        (14, 59, True),
        (15, 0, False),
    ],
)
def test_half_open_sessions_and_intraday_break(hour, minute, opened):
    assert calendar().is_open(datetime(2026, 10, 12, hour, minute, tzinfo=UTC)) is opened


def test_holidays_use_local_date_and_closed_weekdays_remain_closed():
    assert not calendar(holidays=(date(2026, 10, 12),)).is_open(
        datetime(2026, 10, 12, 8, tzinfo=UTC)
    )
    assert not calendar().is_open(datetime(2026, 10, 13, 8, tzinfo=UTC))
    assert not calendar(windows=()).is_open(datetime(2026, 10, 12, 8, tzinfo=UTC))


@pytest.mark.parametrize("month,day,hour", [(1, 12, 8), (7, 13, 7)])
def test_session_opening_tracks_winter_and_summer_offsets(month, day, hour):
    assert calendar().is_open(datetime(2026, month, day, hour, tzinfo=UTC))
    assert not calendar().is_open(datetime(2026, month, day, hour - 1, 59, tzinfo=UTC))


def test_spring_gap_does_not_create_a_nonexistent_wall_time_session():
    session = calendar(windows=(SessionWindow(weekday=6, start_minute=120, end_minute=180),))
    assert not session.is_open(datetime(2026, 3, 29, 0, 59, tzinfo=UTC))
    assert not session.is_open(datetime(2026, 3, 29, 1, 0, tzinfo=UTC))


def test_both_autumn_folds_use_the_same_reviewed_local_window():
    session = calendar(windows=(SessionWindow(weekday=6, start_minute=120, end_minute=180),))
    assert session.is_open(datetime(2026, 10, 25, 0, 30, tzinfo=UTC))
    assert session.is_open(datetime(2026, 10, 25, 1, 30, tzinfo=UTC))
    assert not session.is_open(datetime(2026, 10, 25, 2, 0, tzinfo=UTC))


def test_overnight_sessions_are_explicitly_split_at_midnight():
    session = calendar(
        windows=(
            SessionWindow(weekday=0, start_minute=22 * 60, end_minute=1440),
            SessionWindow(weekday=1, start_minute=0, end_minute=2 * 60),
        )
    )
    assert session.is_open(datetime(2026, 10, 12, 21, tzinfo=UTC))
    assert session.is_open(datetime(2026, 10, 12, 22, tzinfo=UTC))
    assert not session.is_open(datetime(2026, 10, 13, 0, tzinfo=UTC))


def test_local_holiday_cannot_be_bypassed_by_previous_utc_date():
    session = calendar(
        holidays=(date(2026, 10, 13),),
        windows=(SessionWindow(weekday=1, start_minute=0, end_minute=120),),
    )
    assert not session.is_open(datetime(2026, 10, 12, 22, 30, tzinfo=UTC))


def test_naive_timestamp_unknown_timezone_overlap_and_inverted_window_are_rejected():
    with pytest.raises(ValueError):
        calendar().is_open(datetime(2026, 10, 12, 9))
    with pytest.raises(ZoneInfoNotFoundError):
        calendar(timezone="Uninstalled/Zone")
    with pytest.raises(ValidationError):
        calendar(
            windows=(
                SessionWindow(weekday=0, start_minute=60, end_minute=180),
                SessionWindow(weekday=0, start_minute=120, end_minute=240),
            )
        )
    with pytest.raises(ValidationError):
        SessionWindow(weekday=0, start_minute=120, end_minute=60)
