"""백테스트 하네스 재현성 검증 — 작은 합성 계열로 메트릭·롤링오리진을 확인.

실행: venv/bin/python -m pytest tests/test_backtest.py -q
"""

import math

import pandas as pd

from src.forecast import backtest as bt
from src.forecast.models import naive, seasonal_naive


# ── 메트릭 순수함수 ──────────────────────────────────────────────────────────
def test_mae_known():
    assert bt.mae([1, 2, 3], [1, 2, 3]) == 0.0
    assert bt.mae([1, 2, 3], [2, 2, 2]) == (1 + 0 + 1) / 3


def test_smape_range_and_identity():
    assert bt.smape([10, 20, 30], [10, 20, 30]) == 0.0
    s = bt.smape([10, 20, 30], [12, 18, 33])
    assert 0.0 <= s <= 200.0
    # 부호가 완전히 반대(최대 괴리)면 200에 근접
    assert abs(bt.smape([1, 1], [-1, -1]) - 200.0) < 1e-9


def test_smape_skips_zero_denominator():
    # 실측·예측 모두 0인 스텝은 제외되고 나머지로만 계산
    assert bt.smape([0, 20], [0, 20]) == 0.0


# ── 합성 패널 ────────────────────────────────────────────────────────────────
def _seasonal_panel(n=48, period=12):
    """period-주기로 완전 반복되는 계열 2개 — seasonal_naive 가 정확히 맞아야 함."""
    pat_a = [100 + 5 * math.sin(2 * math.pi * i / period) for i in range(period)]
    pat_b = [50 + 3 * math.cos(2 * math.pi * i / period) for i in range(period)]
    va = [pat_a[i % period] for i in range(n)]
    vb = [pat_b[i % period] for i in range(n)]
    return {
        "A": {"values": va, "features": None},
        "전국": {"values": vb, "features": None},
    }


def _trend_panel(n=48, period=12):
    """추세+계절 계열 — naive/seasonal_naive 가 유한한 양의 오차를 내야 함."""
    va = [80 + 0.4 * i + 4 * math.sin(2 * math.pi * i / period) for i in range(n)]
    vb = [120 + 0.2 * i + 6 * math.sin(2 * math.pi * i / period) for i in range(n)]
    return {
        "A": {"values": va, "features": None},
        "전국": {"values": vb, "features": None},
    }


def test_seasonal_naive_is_exact_on_periodic_series():
    panel = _seasonal_panel()
    res = bt.run_backtest(panel, {"seasonal_naive": seasonal_naive},
                          origins=(24, 30), horizon=6)
    row = next(r for r in res["benchmark"] if r["model"] == "seasonal_naive")
    assert row["mae"] < 1e-6
    assert row["smape"] < 1e-6
    # 전국은 별도 집계에 들어간다
    assert "seasonal_naive" in res["nation"]
    assert res["nation"]["seasonal_naive"]["mae"] < 1e-6


def test_run_backtest_shape_and_ranges():
    panel = _trend_panel()
    models = {"naive": naive, "seasonal_naive": seasonal_naive}
    res = bt.run_backtest(panel, models, origins=(24, 30, 36), horizon=6)
    assert res["horizon"] == 6
    assert res["origins"] == [24, 30, 36]
    names = {r["model"] for r in res["benchmark"]}
    assert names == {"naive", "seasonal_naive"}
    for r in res["benchmark"]:
        assert r["mae"] >= 0
        assert 0.0 <= r["smape"] <= 200.0
        assert math.isfinite(r["mae"]) and math.isfinite(r["smape"])
    # 벤치마크는 MAE 오름차순 정렬
    maes = [r["mae"] for r in res["benchmark"]]
    assert maes == sorted(maes)
    # 시도별 detail 존재(전국 포함 2계열)
    assert set(res["detail"]["naive"].keys()) == {"A", "전국"}


def test_unavailable_model_is_skipped_not_swallowed():
    panel = _trend_panel(n=36)

    def broken(train, exog, horizon, series_id=None, all_train=None):
        return None  # 사용 불가 신호

    res = bt.run_backtest(panel, {"naive": naive, "broken": broken},
                          origins=(24,), horizon=6)
    assert "broken" in res["skipped"]
    assert all(r["model"] != "broken" for r in res["benchmark"])
    assert any(r["model"] == "naive" for r in res["benchmark"])


def test_lightgbm_exog_slice_alignment():
    """features 가 있는 패널에서 exog 슬라이스가 values 와 정합하는지(길이) 확인."""
    n = 40
    vals = [100 + 0.3 * i for i in range(n)]
    feats = pd.DataFrame({"f": [v - 1 for v in vals], "g": [v * 0.5 for v in vals]})
    seen = {}

    def spy(train, exog, horizon, series_id=None, all_train=None):
        seen["len_train"] = len(train)
        seen["len_exog"] = len(exog)
        return {"median": [train[-1]] * horizon,
                "q10": [train[-1]] * horizon, "q90": [train[-1]] * horizon}

    panel = {"A": {"values": vals, "features": feats}}
    bt.run_backtest(panel, {"spy": spy}, origins=(24,), horizon=6)
    assert seen["len_train"] == 24
    assert seen["len_exog"] == 24  # exog 는 오리진까지만 슬라이스
