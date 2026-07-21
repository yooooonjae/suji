"""롤링 오리진 백테스트.

오리진 {96, 102, 108}개월 시점에서 각 12개월 예측(오리진 108이 최종 12개월).
실측 대비 MAE·sMAPE 를 집계 — 시도 평균(전국 제외 17개)·전국 별도.

메트릭 함수(mae/smape)와 run_backtest 는 순수 함수라 작은 합성 패널로 재현 가능하다
(tests/test_backtest.py). 모델은 models.MODELS 를 그대로 쓰거나 외부에서 주입한다.
"""

import numpy as np

ORIGINS = (96, 102, 108)
HORIZON = 12
NATION = "전국"


def mae(actual, pred):
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    return float(np.mean(np.abs(a - p)))


def smape(actual, pred):
    """대칭 MAPE(%) — 0~200 범위. 분모 0 스텝은 제외."""
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    denom = np.abs(a) + np.abs(p)
    mask = denom > 0
    if not mask.any():
        return 0.0
    return float(np.mean(200.0 * np.abs(a[mask] - p[mask]) / denom[mask]))


def run_backtest(panel, models, origins=ORIGINS, horizon=HORIZON):
    """롤링 오리진 백테스트 실행.

    panel: {sido: {"values": [...], "features": DataFrame|None}}
    models: {name: fit_predict(train, exog, horizon, series_id, all_train) -> dict|None}

    반환:
      {"benchmark": [{"model","mae","smape"} ...],          # 시도평균(전국 제외) 헤드라인
       "detail": {model: {sido: {"mae","smape"}}},          # 시도별
       "nation": {model: {"mae","smape"}},                  # 전국
       "origins": [...], "horizon": h, "skipped": {model: reason}}
    """
    sidos = list(panel.keys())
    # 모델별 (sido -> [origin별 (mae,smape)])
    acc = {name: {s: [] for s in sidos} for name in models}
    skipped = {}

    for origin in origins:
        all_train = {s: panel[s]["values"][:origin] for s in sidos}
        for name, fn in models.items():
            if name in skipped:
                continue
            for s in sidos:
                vals = panel[s]["values"]
                if origin + horizon > len(vals):
                    continue
                train = vals[:origin]
                feats = panel[s].get("features")
                exog = feats.iloc[:origin] if feats is not None else None
                actual = vals[origin:origin + horizon]
                out = fn(train, exog, horizon, series_id=s, all_train=all_train)
                if out is None:  # 모델 사용 불가(예: Chronos 로드 실패) → 전체 스킵
                    from . import models as _m
                    skipped[name] = _m.CHRONOS_STATUS.get("reason", "모델 사용 불가")
                    break
                med = out["median"]
                acc[name][s].append((mae(actual, med), smape(actual, med)))

    for name in skipped:
        acc.pop(name, None)

    detail, nation, benchmark = {}, {}, []
    for name in acc:
        per_sido = {}
        for s in sidos:
            rows = acc[name][s]
            if not rows:
                continue
            per_sido[s] = {
                "mae": float(np.mean([r[0] for r in rows])),
                "smape": float(np.mean([r[1] for r in rows])),
            }
        detail[name] = per_sido
        region = [v for s, v in per_sido.items() if s != NATION]
        head_mae = float(np.mean([v["mae"] for v in region])) if region else float("nan")
        head_smape = float(np.mean([v["smape"] for v in region])) if region else float("nan")
        benchmark.append({"model": name, "mae": round(head_mae, 4), "smape": round(head_smape, 4)})
        if NATION in per_sido:
            nation[name] = {
                "mae": round(per_sido[NATION]["mae"], 4),
                "smape": round(per_sido[NATION]["smape"], 4),
            }

    benchmark.sort(key=lambda r: r["mae"])
    return {
        "benchmark": benchmark,
        "detail": detail,
        "nation": nation,
        "origins": list(origins),
        "horizon": horizon,
        "skipped": skipped,
    }
