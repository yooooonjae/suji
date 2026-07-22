"""딜 리포트 №3 — 한남3구역 재개발 (디에이치 한남, 2026 일반분양 예정).

실행: venv/bin/python -m src.analysis.report_hannam
산출: out/report_hannam.json

유형: 정비사업형 — №1(토지 역산)·№2(요구수익률 역산)에 이어 세 번째 문법:
  관리처분(2023-06)의 두 기준점(비례율 100.195% · 공사비 546만원/3.3㎡)이
  2026 일반분양 변수 앞에서 얼마나 움직이는가 — 민감도 계수의 리포트.

공개 확인사항(정비사업 정보몽땅·용산구 고시·언론, 스카우트 검증):
  구역 386,395.5㎡ · 신축 연면적 1,048,998.5㎡ · 총 5,988세대
  (조합원 986 · 임대 238 · 보류 21 · 일반분양 약 831) · 시공 현대건설
  관리처분인가 2023-06 · 반영 공사비 3.3㎡당 546만원 · 비례율 100.195%
  예상 일반분양가 5,500~6,000만원/3.3㎡ (2026 분상제 심사 전)
비공개(시나리오 처리): 종전자산평가액 총액 — 4/5/6조 시나리오.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = 3.305785

FACT = {
    "area_m2": 386_395.5, "gfa_m2": 1_048_998.5,
    "units_total": 5_988, "units_member": 986, "units_rental": 238,
    "units_reserve": 21, "units_general": 831,
    "cost_py_3p3": 546, "rate_base_pct": 100.195,
    "price_range": [5_500, 6_000],
    "avg_supply_py_general": 25.4,   # 일반분양 평균 공급 84㎡(25.4평) 가정 — 중소형 위주
}
PRIOR_SCENARIOS_JO = [4, 5, 6]       # 종전자산 총액(조원) — 비공개라 시나리오


def main():
    gfa_py = FACT["gfa_m2"] / PY
    cost_total_eok = gfa_py * FACT["cost_py_3p3"] * 1e4 / 1e8  # 공사비 총액(억)

    # 지렛대 ①: 일반분양가 +1,000만원/3.3㎡ → 추가 수입
    d_rev_per_1000 = FACT["units_general"] * FACT["avg_supply_py_general"] * 1_000 * 1e4 / 1e8  # 억
    # 지렛대 ②: 공사비 +10% → 추가 비용
    d_cost_10pct = cost_total_eok * 0.10

    levers = []
    for jo in PRIOR_SCENARIOS_JO:
        prior_eok = jo * 1e4
        levers.append({
            "prior_jo": jo,
            "d_rate_per_price1000": round(d_rev_per_1000 / prior_eok * 100, 2),   # %p
            "d_rate_cost10": round(-d_cost_10pct / prior_eok * 100, 2),           # %p
            "avg_rights_eok": round(prior_eok / FACT["units_member"], 1),          # 평균 권리가액(억/세대) 근사
        })

    # 일반분양 수입 규모감
    rev_general_mid_eok = FACT["units_general"] * FACT["avg_supply_py_general"] * 5_750 * 1e4 / 1e8

    out = {
        "fact": FACT,
        "cost_total_eok": round(cost_total_eok),
        "d_rev_per_1000_eok": round(d_rev_per_1000),
        "d_cost_10pct_eok": round(d_cost_10pct),
        "rev_general_mid_eok": round(rev_general_mid_eok),
        "general_share_pct": round(FACT["units_general"] / FACT["units_total"] * 100, 1),
        "levers": levers,
        "vworld": {"zone": "제2종일반주거지역", "land_price_won_m2": 8_365_000,
                   "jibun": "서울특별시 용산구 한남동 686-1", "year": "2025"},
    }
    (ROOT / "out" / "report_hannam.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"공사비 총액(546만/평): {out['cost_total_eok']:,}억 · 일반분양 중간값 수입: {out['rev_general_mid_eok']:,}억 (전체 세대의 {out['general_share_pct']}%)")
    print(f"지렛대: 분양가 +1,000만/평 → +{out['d_rev_per_1000_eok']:,}억 · 공사비 +10% → -{out['d_cost_10pct_eok']:,}억")
    for l in levers:
        print(f"  종전자산 {l['prior_jo']}조 가정: 분양가 1,000만↑ = 비례율 {l['d_rate_per_price1000']:+}%p · 공사비 10%↑ = {l['d_rate_cost10']:+}%p · 평균 권리가액 {l['avg_rights_eok']}억")


if __name__ == "__main__":
    main()
