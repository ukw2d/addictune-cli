from datetime import UTC, datetime, timedelta


from addictune_cli.src.tui.utils import next_event_delay


def _future(seconds: float) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=seconds)


def _past(seconds: float) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=seconds)


def test_empty_returns_max_delay():
    assert next_event_delay([]) == 60.0


def test_empty_respects_custom_max():
    assert next_event_delay([], max_delay=30.0) == 30.0


def test_past_event_ignored_returns_max():
    assert next_event_delay([_past(100)]) == 60.0


def test_single_future_event():
    delay = next_event_delay([_future(30)])
    assert 28.0 < delay < 32.0


def test_multiple_events_picks_nearest():
    delay = next_event_delay([_future(50), _future(20), _future(100)])
    assert 18.0 < delay < 22.0


def test_clamps_at_max_delay():
    delay = next_event_delay([_future(120)], max_delay=60.0)
    assert delay == 60.0


def test_clamps_at_min_delay():
    delay = next_event_delay([_future(2)], min_delay=10.0)
    assert delay == 10.0


def test_past_events_ignored_future_wins():
    delay = next_event_delay([_past(50), _future(25)])
    assert 23.0 < delay < 27.0


def test_custom_min_and_max():
    delay = next_event_delay([_future(45)], max_delay=30.0, min_delay=5.0)
    assert delay == 30.0
    delay = next_event_delay([_future(3)], max_delay=30.0, min_delay=5.0)
    assert delay == 5.0
