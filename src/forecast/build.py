"""전 시도 최종 12개월 미래 예측(5모델) + 백테스트 벤치마크 → out/forecast.json.

실행: venv/bin/python -m src.forecast.build   (또는 venv/bin/python src/forecast/build.py)
"""

import datetime
import json
from pathlib import Path

from . import backtest as bt
from . import features as ft
from . import models as md

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out" / "forecast.json"
HORIZON = 12
TARGET = "아파트 매매가격지수(2026.01=100)"
CAVEAT = (
    "소표본 한계: 시도별 월별 120개월(201607~202606) 단일 표본, 롤링 오리진 3회"
    "(오리진 96/102/108개월)로만 검증했다. 지수(가격 자체 아님) 수준 예측이며, "
    "외생 피처는 라그(1/3/6/12)만 사용해 동시점 정보를 쓰지 않는다(누출 방지). "
    "분위수는 근사(정규 근사·잔차 스프레드·모델 자체 분위수 혼재)이므로 구간은 참고용이다. "
    "구조 변화(금리·정책 급변) 구간에서는 오차가 크게 확대될 수 있다."
)


def build():
    panel = ft.build_panel()
    sidos = list(panel.keys())

    # 1) 백테스트 벤치마크
    bench = bt.run_backtest(panel, md.MODELS)

    # 2) 최종 12개월 미래 예측(전 시도, 오리진=전체 이력)
    all_train = {s: panel[s]["values"] for s in sidos}
    forecasts = {}
    for s in sidos:
        train = panel[s]["values"]
        exog = panel[s]["features"]
        last_ym = panel[s]["yms"][-1]
        out_models = {}
        for name, fn in md.MODELS.items():
            res = fn(train, exog, HORIZON, series_id=s, all_train=all_train)
            if res is None:
                continue  # Chronos 등 사용 불가 → 사유는 md.CHRONOS_STATUS
            out_models[name] = {
                "median": [round(x, 4) for x in res["median"]],
                "q10": [round(x, 4) for x in res["q10"]],
                "q90": [round(x, 4) for x in res["q90"]],
            }
        forecasts[s] = {"last_actual_ym": last_ym, "models": out_models}

    doc = {
        "benchmark": bench["benchmark"],
        "benchmark_nation": bench["nation"],
        "forecasts": forecasts,
        "horizon": HORIZON,
        "origins": bench["origins"],
        "target": TARGET,
        "caveat": CAVEAT,
        "chronos_status": md.CHRONOS_STATUS,
        "skipped_models": bench["skipped"],
        "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    return doc, bench


if __name__ == "__main__":
    doc, bench = build()
    print("=== BENCHMARK (시도평균, 전국 제외) ===")
    for r in bench["benchmark"]:
        print(f"  {r['model']:16s} MAE={r['mae']:.4f}  sMAPE={r['smape']:.4f}%")
    print("=== 전국 ===")
    for name, v in bench["nation"].items():
        print(f"  {name:16s} MAE={v['mae']:.4f}  sMAPE={v['smape']:.4f}%")
    if bench["skipped"]:
        print("=== SKIPPED ===", bench["skipped"])
    print("Chronos:", md.CHRONOS_STATUS)
    print("→", OUT)
