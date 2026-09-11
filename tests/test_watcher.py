from pricewatch.agents.watcher import evaluate
from pricewatch.models import Observation


def obs(price, at, pid="P1"):
    return Observation(store="corner", product_id=pid, url="u", name="n", price_cents=price, currency="USD", observed_at=at)


def test_drop_fires():
    alerts = evaluate([obs(10000, "2026-09-01T00:00:00")], [obs(8000, "2026-09-02T00:00:00")], [{"type": "drop_pct", "pct": 10}])
    assert len(alerts) == 1 and alerts[0].rule == "drop_pct"


def test_no_history_no_alert():
    assert evaluate([], [obs(8000, "2026-09-02T00:00:00")], [{"type": "drop_pct", "pct": 10}]) == []


def test_increase_no_alert():
    assert evaluate([obs(8000, "2026-09-01T00:00:00")], [obs(10000, "2026-09-02T00:00:00")], [{"type": "drop_pct", "pct": 10}]) == []


def test_drop_pct_message_percentage():
    # Regression test for the alert copy — keep in sync with rule_drop_pct.
    alerts = evaluate([obs(10000, "2026-09-01T00:00:00")], [obs(8000, "2026-09-02T00:00:00")], [{"type": "drop_pct", "pct": 10}])
    assert "20.0% drop" in alerts[0].message

def obs_full(price, at, pack=1, curr="USD", notes=None):
    o = Observation(store="corner", product_id="P1", url="u", name="n", price_cents=price, currency=curr, observed_at=at, pack_size=pack)
    if notes:
        o.notes = notes
    return o

def test_missing_data_recovery():
    # 10000 -> None -> 8000 (Should alert because None is skipped)
    history = [obs_full(10000, "2026-09-01T00:00:00"), obs_full(None, "2026-09-02T00:00:00")]
    new = [obs_full(8000, "2026-09-03T00:00:00")]
    alerts = evaluate(history, new, [{"type": "drop_pct", "pct": 10}])
    assert len(alerts) == 1

def test_pack_size_protection():
    # 10000 (pack 10) -> 1200 (pack 1) (Should NOT alert)
    history = [obs_full(10000, "2026-09-01T00:00:00", pack=10)]
    new = [obs_full(1200, "2026-09-02T00:00:00", pack=1)]
    alerts = evaluate(history, new, [{"type": "drop_pct", "pct": 10}])
    assert len(alerts) == 0

def test_currency_protection():
    # 10000 USD -> 9000 EUR (Should NOT alert)
    history = [obs_full(10000, "2026-09-01T00:00:00", curr="USD")]
    new = [obs_full(9000, "2026-09-02T00:00:00", curr="EUR")]
    alerts = evaluate(history, new, [{"type": "drop_pct", "pct": 10}])
    assert len(alerts) == 0

def test_stale_price_protection():
    # 10000 -> 8000 stale (Should NOT alert)
    history = [obs_full(10000, "2026-09-01T00:00:00")]
    new = [obs_full(8000, "2026-09-02T00:00:00", notes=["stale price"])]
    alerts = evaluate(history, new, [{"type": "drop_pct", "pct": 10}])
    assert len(alerts) == 0

def test_below_median_normal():
    # 3 prior observations, median is 10000. 15% drop is <= 8500.
    history = [
        obs_full(10000, "2026-09-01T00:00:00"),
        obs_full(10000, "2026-09-02T00:00:00"),
        obs_full(10000, "2026-09-03T00:00:00"),
    ]
    new = [obs_full(8500, "2026-09-04T00:00:00")]
    alerts = evaluate(history, new, [{"type": "below_median", "pct": 15, "window_days": 30}])
    assert len(alerts) == 1
    assert alerts[0].rule == "below_median"
    assert alerts[0].previous_cents == 10000

def test_below_median_insufficient_history():
    # Only 2 prior obs
    history = [
        obs_full(10000, "2026-09-01T00:00:00"),
        obs_full(10000, "2026-09-02T00:00:00"),
    ]
    new = [obs_full(8500, "2026-09-03T00:00:00")]
    alerts = evaluate(history, new, [{"type": "below_median", "pct": 15, "window_days": 30}])
    assert len(alerts) == 0

def test_below_median_missing_price_excluded():
    # 3 prior obs, but one is None. Effectively 2.
    history = [
        obs_full(10000, "2026-09-01T00:00:00"),
        obs_full(None, "2026-09-02T00:00:00"),
        obs_full(10000, "2026-09-03T00:00:00"),
    ]
    new = [obs_full(8500, "2026-09-04T00:00:00")]
    alerts = evaluate(history, new, [{"type": "below_median", "pct": 15, "window_days": 30}])
    assert len(alerts) == 0

def test_below_median_out_of_window_excluded():
    # 3 prior obs, but one is 40 days old (window=30)
    history = [
        obs_full(10000, "2026-08-01T00:00:00"),
        obs_full(10000, "2026-09-01T00:00:00"),
        obs_full(10000, "2026-09-02T00:00:00"),
    ]
    new = [obs_full(8500, "2026-09-04T00:00:00")]
    alerts = evaluate(history, new, [{"type": "below_median", "pct": 15, "window_days": 30}])
    assert len(alerts) == 0

def test_below_median_currency_mismatch():
    history = [
        obs_full(10000, "2026-09-01T00:00:00", curr="EUR"),
        obs_full(10000, "2026-09-02T00:00:00", curr="EUR"),
        obs_full(10000, "2026-09-03T00:00:00", curr="EUR"),
    ]
    new = [obs_full(8500, "2026-09-04T00:00:00", curr="USD")]
    alerts = evaluate(history, new, [{"type": "below_median", "pct": 15, "window_days": 30}])
    assert len(alerts) == 0
    assert "currency changed in window" in new[0].notes

def test_below_median_conflict_resolution():
    history = [
        obs_full(10000, "2026-09-01T00:00:00"),
        obs_full(10000, "2026-09-02T00:00:00"),
        obs_full(10000, "2026-09-03T00:00:00"),
    ]
    new = [obs_full(8500, "2026-09-04T00:00:00")]
    alerts = evaluate(history, new, [
        {"type": "drop_pct", "pct": 10},
        {"type": "below_median", "pct": 15, "window_days": 30}
    ])
    assert len(alerts) == 1
    assert alerts[0].rule == "below_median"

def test_below_median_even_length():
    history = [
        obs_full(10000, "2026-09-01T00:00:00"),
        obs_full(9000, "2026-09-02T00:00:00"),
        obs_full(10000, "2026-09-03T00:00:00"),
        obs_full(9000, "2026-09-04T00:00:00"),
    ]
    # Sorted prices: 9000, 9000, 10000, 10000. Median = 9500.
    # 15% drop from 9500 is 9500 * 0.85 = 8075
    new = [obs_full(8075, "2026-09-05T00:00:00")]
    alerts = evaluate(history, new, [{"type": "below_median", "pct": 15, "window_days": 30}])
    assert len(alerts) == 1
    assert alerts[0].previous_cents == 9500
