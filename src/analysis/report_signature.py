"""딜 리포트 №2 — 시그니쳐타워 (KB자산운용 매입, 2025-11 거래종결).

실행: venv/bin/python -m src.analysis.report_signature
산출: out/report_signature.json

유형: 수익형 매입 사후채점 — 위례(№1, 개발형 토지 역산)와 다른 문법.
공개 팩트(딜사이트·thebell·서울경제, 2025):
  서울 중구 청계천로 100 (을지로3가, CBD) · 연면적 99,997.1㎡(32,491평) · 지하6~지상17
  매매가 1조 346억 (3.3㎡당 3,420만원) · 직전 거래 2017년 7,200억(이지스)
  자본구조: 대출 7,445억(선순위 6,773 + 후순위 672) · 에쿼티 2,936억 · 보증금 314억
  앵커: 금호석유화학 장기임차.
질문 둘: ① KB는 몇 %의 수익률(cap)로 산 것인가 — 임대료 시나리오 역산
        ② 직전 소유자의 8년은 남는 장사였나 — 보유 성과 분해
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = 3.305785

FACT = {
    "price_eok": 10_346, "price_py_3p3": 3_420,
    "gfa_m2": 99_997.1, "gfa_py": 30_247,      # 연면적 평 (99,997.1/3.3058)
    "loan_eok": 7_445, "loan_senior": 6_773, "loan_junior": 672,
    "equity_eok": 2_936, "deposit_eok": 314,
    "prev_price_eok": 7_200, "prev_year": 2017.75, "deal_year": 2025.9,
}

# 역산 프레임: "이 가격이 성립하려면 얼마를 벌어야 하는가"
# 임대료 추정의 단위 함정(전용 vs 임대면적, 명목 vs 실질)을 피하기 위해
# 수익률 시나리오 → 필요 NOI → 필요 실질 임대수익(평당)을 역산한다.
YIELD_SCENARIOS = [3.0, 3.83, 4.5]   # 3.83 = 부동산원 서울 오피스 소득수익률 연환산(순환 Ⅲ장)
GLA_RATIO = 0.90                      # 임대면적 ≈ 연면적 × 0.9 (한국 오피스 임대 관행 기준)


def required_rent(yield_pct: float) -> tuple:
    """필요 NOI(억)와, 그것을 만들기 위한 임대면적 평당 월 실질수익(만원)."""
    noi = FACT["price_eok"] * yield_pct / 100
    gla_py = FACT["gfa_py"] * GLA_RATIO
    rent_py_month = noi * 1e8 / gla_py / 12 / 1e4
    return round(noi), round(rent_py_month, 1)


def main():
    # ① 수익률 시나리오 → 필요 NOI·필요 실질 임대수익 역산
    scenarios = []
    for y in YIELD_SCENARIOS:
        noi, rent = required_rent(y)
        scenarios.append({"yield_pct": y, "noi_eok": noi, "rent_py_month": rent})

    # 시장 대조(순환 Ⅲ장): 서울 오피스 소득수익률 연환산
    rone = json.load(open(ROOT / "data" / "rone_commercial.json"))
    seoul_inc_ann = round(rone["office_yield"]["서울"][-1]["income"] * 4, 2)
    t10 = json.load(open("/Users/iseul/순환/data/treasury10y.json"))["series"][-1]["rate"]

    # ② 8년 보유 성과 분해 (직전 소유자 관점, 총자산 기준)
    hold_yrs = FACT["deal_year"] - FACT["prev_year"]
    price_cagr = ((FACT["price_eok"] / FACT["prev_price_eok"]) ** (1 / hold_yrs) - 1) * 100
    # 보유기간 운영수익률: 시장 소득수익률 범위(3.3~4.0%)를 평균 자산가치에 적용한 근사
    avg_yield_on_prev = 3.6
    total_return_ann = price_cagr + avg_yield_on_prev

    # Sources & Uses 점검
    sources = FACT["loan_eok"] + FACT["equity_eok"] + FACT["deposit_eok"]
    acq_cost_implied = sources - FACT["price_eok"]  # 취득 부대(취득세·수수료 등) 내재액
    ltv = FACT["loan_eok"] / FACT["price_eok"] * 100

    out = {
        "fact": FACT, "assump": {"gla_ratio": GLA_RATIO},
        "cap_scenarios": scenarios,
        "market": {"seoul_income_ann": seoul_inc_ann, "t10": round(t10, 2),
                   "spread_market": round(seoul_inc_ann - t10, 2)},
        "hold": {"years": round(hold_yrs, 1), "price_cagr": round(price_cagr, 1),
                 "avg_yield_on_prev": round(avg_yield_on_prev, 1),
                 "total_return_ann": round(total_return_ann, 1)},
        "structure": {"sources_eok": sources, "acq_cost_implied_eok": round(acq_cost_implied),
                      "ltv_pct": round(ltv, 1)},
    }
    (ROOT / "out" / "report_signature.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("필요 역산:", [(s["yield_pct"], s["noi_eok"], s["rent_py_month"]) for s in scenarios])
    print(f"시장 소득수익률 {seoul_inc_ann}% · 국고 {t10}% · 시장 스프레드 {out['market']['spread_market']}%p")
    print(f"8년 성과: 가격 CAGR {out['hold']['price_cagr']}% + 운영 {out['hold']['avg_yield_on_prev']}% ≈ 연 {out['hold']['total_return_ann']}% (총자산)")
    print(f"구조: LTV {out['structure']['ltv_pct']}% · 내재 부대비 {out['structure']['acq_cost_implied_eok']}억")


if __name__ == "__main__":
    main()
