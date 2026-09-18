import numpy as np
import pandas as pd
import pytest

from pipeline import metrics as m


def weeks(n):
    return pd.date_range("2025-09-15", periods=n, freq="7D")


def test_blended_price_weights_prompt_tokens():
    assert m.blended_price(1.0, 10.0, ratio=9) == pytest.approx(1.9)


def test_rolling_elasticity_recovers_known_value():
    rng = np.random.default_rng(0)
    n = 60
    price = pd.Series(np.exp(np.cumsum(rng.normal(-0.03, 0.05, n))), index=weeks(n))
    volume = pd.Series(np.exp(-1.5 * np.log(price) + rng.normal(0, 0.005, n)), index=weeks(n))
    e = m.rolling_elasticity(volume, price, window=12).dropna()
    assert len(e) > 0
    assert e.median() == pytest.approx(-1.5, abs=0.1)


def test_arc_elasticity_constant_elasticity_curve():
    price = pd.Series([10.0, 8.0, 6.0, 5.0], index=weeks(4))
    volume = price ** -2.0
    assert m.arc_elasticity(volume, price, lag=1).dropna().to_numpy() == pytest.approx([-2.0] * 3)


def _prices(rows):
    return pd.DataFrame(rows, columns=["snapshot", "slug", "prompt_usd_per_m", "completion_usd_per_m"]).assign(
        snapshot=lambda d: pd.to_datetime(d["snapshot"])
    )


def test_price_as_of_uses_latest_prior_snapshot_and_launch_price_before_first():
    p = _prices([("2025-09-01", "a/x", 1.0, 1.0), ("2025-11-01", "a/x", 0.5, 0.5)])
    assert m.price_as_of(p, "a/x", pd.Timestamp("2025-10-15"))["prompt_usd_per_m"] == 1.0
    assert m.price_as_of(p, "a/x", pd.Timestamp("2025-12-01"))["prompt_usd_per_m"] == 0.5
    assert m.price_as_of(p, "a/x", pd.Timestamp("2025-01-01"))["prompt_usd_per_m"] == 1.0
    assert m.price_as_of(p, "a/x:free", pd.Timestamp("2025-12-01")) is not None
    assert m.price_as_of(p, "b/y", pd.Timestamp("2025-12-01")) is None


def test_attach_prices_free_models_zero_and_others_dropped():
    w = weeks(1)[0]
    tokens = pd.DataFrame({"week": [w, w, w], "series": ["a/x", "a/x:free", "Others"], "tokens": [10.0, 5.0, 100.0]})
    p = _prices([("2025-09-01", "a/x", 2.0, 2.0)])
    out = m.attach_prices(tokens, p, ratio=3)
    assert list(out["series"]) == ["a/x", "a/x:free"]
    assert list(out["blended_price"]) == [2.0, 0.0]


def test_like_for_like_index_isolates_price_changes_from_mix():
    w0, w1 = weeks(2)
    priced = pd.DataFrame({
        "week": [w0, w0, w1, w1],
        "series": ["cheap", "pricey", "cheap", "pricey"],
        "tokens": [50.0, 50.0, 90.0, 10.0],   # mix shifts toward cheap model
        "blended_price": [1.0, 9.0, 1.0, 9.0],  # but list prices unchanged
    })
    totals = pd.Series({w0: 100.0, w1: 100.0})
    out = m.weekly_price_metrics(priced, totals).set_index("week")
    assert out.loc[w1, "like_for_like_index"] == pytest.approx(100.0)
    assert out.loc[w0, "effective_price"] == pytest.approx(5.0)
    assert out.loc[w1, "effective_price"] == pytest.approx(1.8)


def test_like_for_like_index_tracks_real_price_cut():
    w0, w1 = weeks(2)
    priced = pd.DataFrame({
        "week": [w0, w1], "series": ["a", "a"], "tokens": [10.0, 10.0], "blended_price": [4.0, 3.0],
    })
    out = m.weekly_price_metrics(priced, pd.Series({w0: 10.0, w1: 10.0}))
    assert out["like_for_like_index"].iloc[-1] == pytest.approx(75.0)
    assert out["price_coverage"].tolist() == [1.0, 1.0]


def test_spend_identity_and_index():
    vol = pd.Series([100.0, 200.0, 400.0], index=weeks(3))
    price = pd.Series([2.0, 1.5, 1.0], index=weeks(3))
    spend = vol * price
    assert m.index_to_100(spend).tolist() == pytest.approx([100.0, 150.0, 200.0])
    assert (m.index_to_100(vol) * m.index_to_100(price) / 100).tolist() == pytest.approx(m.index_to_100(spend).tolist())


def test_volume_metrics_growth():
    v = m.volume_metrics(pd.Series([100.0, 110.0], index=weeks(2)), ma_weeks=4)
    assert v["wow_pct"].iloc[-1] == pytest.approx(10.0)


def test_fit_logistic_recovers_saturation():
    dates = pd.Series(pd.date_range("2023-01-01", periods=30, freq="45D"))
    t = (dates - dates.iloc[0]).dt.days.to_numpy(float)
    y = m.logistic(t, 60.0, 0.004, 800.0)
    fit = m.fit_logistic(dates, pd.Series(y))
    assert fit is not None
    assert fit["saturation"] == pytest.approx(60.0, rel=0.05)
    assert fit["pp_per_quarter"] > 0
