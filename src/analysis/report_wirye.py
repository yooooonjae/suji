"""딜 리포트 №1 — SH 위례 복합용지 E1-1 (반도건설 낙찰, 2025-12).

실행: venv/bin/python -m src.analysis.report_wirye
산출: out/report_wirye.json — Ⅸ장(리포트) 데이터 바인딩용.

구조: 낙찰가 미공개 → 정공법 대신 실무 정석인 "토지 잔여가치(Land Residual) 역산".
  수지가 허용하는 토지 상한(이익 0 / 마진 10% / 15%)을 역산해 예정가 2,613.1억과 대조한다.

공개 팩트(출처: SH 공고·언론 보도, 2025-12):
  대지 20,631㎡ · 공동주택 656세대(전용 60~85) + 상업·문화 복합 · 예정가 261,312,246,000원
  최고가 경쟁입찰 → 반도건설 낙찰(낙찰가 미공개) · 총사업비 약 6,000억 보도.

가정(전부 명시·민감도 대상):
  분양가 시나리오: 3.3㎡당 3,500 / 4,000 / 4,500만원 (공공택지 분상제 감안, 자체 벤치마크 참조)
  평균 공급면적 84㎡ · 공사비 연면적(지하 포함) 95,000㎡ × 평당 920만원(서울 890 × 주상복합 할증)
  상업·문화: 분양 수입 180억 상당(보수적 — 주거 수입 대비 약 6~8%)을 other_income 처리
  금융: 자본 800억 · 브릿지 1,500억(7.5%, 12М) · PF 3,500억(6.0%, 34М, 인출 55%) · 수수료 1.5%
  기간 42개월 · 간접 6% · 판촉 3.5% · 예비 1%
"""

import json
from pathlib import Path

from src.analysis.feasibility import run_feasibility

ROOT = Path(__file__).resolve().parents[2]
PY = 3.305785
EOK = 1e8

FACT = {
    "site_m2": 20_631, "units": 656, "avg_supply_m2": 84.0,
    "reserve_price_eok": 2_613.1,          # SH 예정가(입찰 하한)
    "gfa_construction_m2": 95_000,          # 공사비 산정용(지하 포함) — 총사업비 6,000억 보도와 정합
    "unit_cost_py": 920,                    # 만원/평(주상복합 할증 반영)
    "commercial_income_eok": 180,
    "months": 42,
}
PRICE_SCENARIOS = [3500, 4000, 4500]        # 3.3㎡당 만원


def build_inputs(land_eok: float, price_py_3p3: float, cost_mult: float = 1.0) -> dict:
    price_per_m2 = price_py_3p3 * 1e4 / PY  # 3.3㎡당 만원 → 원/㎡
    return {
        "mode": "신축분양",
        "revenue": {
            "units": [{"name": "주거", "count": FACT["units"],
                       "supply_m2": FACT["avg_supply_m2"], "price_per_m2": price_per_m2}],
            "sell_through": 1.0,
            "other_income": FACT["commercial_income_eok"] * EOK,
        },
        "cost": {
            "land": {"purchase": land_eok * EOK, "acq_tax_rate": 0.046, "misc_rate": 0.01},
            "construction": {"gfa_m2": FACT["gfa_construction_m2"],
                             "unit_cost_per_m2": FACT["unit_cost_py"] * cost_mult * 1e4 / PY},
            "indirect_rate": 0.06, "marketing_rate": 0.035, "contingency_rate": 0.01,
        },
        "finance": {
            "equity": 800 * EOK,
            "bridge": {"amount": 1_500 * EOK, "rate": 0.075, "months": 12},
            "pf": {"amount": 3_500 * EOK, "rate": 0.060, "months": 34, "drawdown": 0.55},
            "fee_rate": 0.015,
        },
        "schedule": {"months_total": FACT["months"]},
    }


def land_ceiling(price_py: float, target_margin: float, cost_mult: float = 1.0) -> float:
    """목표 마진(수입 대비)을 만족하는 토지비 상한(억원) — 이분법."""
    lo, hi = 0.0, 12_000.0
    for _ in range(60):
        mid = (lo + hi) / 2
        r = run_feasibility(build_inputs(mid, price_py, cost_mult))
        m = (r["margin_on_revenue"] or -1)
        if m >= target_margin:
            lo = mid
        else:
            hi = mid
    return round(lo, 0)


def main():
    base_price = PRICE_SCENARIOS[1]
    base = run_feasibility(build_inputs(FACT["reserve_price_eok"], base_price))

    scenarios = []
    for p in PRICE_SCENARIOS:
        r = run_feasibility(build_inputs(FACT["reserve_price_eok"], p))
        scenarios.append({
            "price_py": p,
            "revenue_eok": round(r["revenue_total"] / EOK), "cost_eok": round(r["cost_total"] / EOK),
            "profit_eok": round(r["profit"] / EOK),
            "margin_pct": round((r["margin_on_revenue"] or 0) * 100, 1),
            "irr_pct": round(r["irr_annual"] * 100, 1) if r["irr_annual"] is not None else None,
            "ceiling_0": land_ceiling(p, 0.0),
            "ceiling_10": land_ceiling(p, 0.10),
            "ceiling_15": land_ceiling(p, 0.15),
        })

    # 공사비 ±10% 민감도 (기준 분양가)
    cost_sens = []
    for cm in (0.9, 1.0, 1.1):
        r = run_feasibility(build_inputs(FACT["reserve_price_eok"], base_price, cm))
        cost_sens.append({"mult": cm, "profit_eok": round(r["profit"] / EOK),
                          "margin_pct": round((r["margin_on_revenue"] or 0) * 100, 1),
                          "ceiling_10": land_ceiling(base_price, 0.10, cm)})

    # 예정가 낙찰 시 손익분기 분양가(3.3㎡당) — 이분법
    lo, hi = 2_000.0, 6_000.0
    for _ in range(50):
        mid = (lo + hi) / 2
        r = run_feasibility(build_inputs(FACT["reserve_price_eok"], mid))
        if r["profit"] >= 0:
            hi = mid
        else:
            lo = mid
    breakeven_price = round((lo + hi) / 2)

    out = {
        "fact": FACT, "base_price_py": base_price, "breakeven_price_py": breakeven_price,
        "base": {
            "revenue_eok": round(base["revenue_total"] / EOK),
            "cost": {k: round(v / EOK) for k, v in base["cost"].items()},
            "cost_eok": round(base["cost_total"] / EOK),
            "profit_eok": round(base["profit"] / EOK),
            "margin_pct": round((base["margin_on_revenue"] or 0) * 100, 1),
            "irr_pct": round(base["irr_annual"] * 100, 1) if base["irr_annual"] is not None else None,
            "npv_eok": round(base["npv"] / EOK),
        },
        "scenarios": scenarios, "cost_sens": cost_sens,
        "benchmarks": {
            "wirye_public_2020": "위례 공공분양 807~845만원/㎡ (2020, 자체 청약 DB)",
            "namwirye_2024": "남위례역 엘리프 1,284만원/㎡ = 3.3㎡당 4,245만원 (2024, 경쟁률 10.9:1)",
            "seoul_2025": "서울 2025~ 공고 38건 ㎡당 중위 2,039만원 (강남권 포함 상향)",
        },
    }
    (ROOT / "out" / "report_wirye.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("기준(4,000만/평·예정가 낙찰):",
          f"수입 {out['base']['revenue_eok']:,}억 · 지출 {out['base']['cost_eok']:,}억 · "
          f"이익 {out['base']['profit_eok']:,}억 · 마진 {out['base']['margin_pct']}% · IRR {out['base']['irr_pct']}%")
    for s in scenarios:
        print(f"  분양가 {s['price_py']:,}만/평: 이익 {s['profit_eok']:,}억({s['margin_pct']}%) · "
              f"토지상한 — 손익분기 {s['ceiling_0']:,}억 / 마진10% {s['ceiling_10']:,}억 / 15% {s['ceiling_15']:,}억")


if __name__ == "__main__":
    main()
