"""사례 빌드 — 표준 사례 4건 + 계산기 프리셋을 실데이터 기반으로 산출해
out/cases.json 을 생성한다.

- cases: run_feasibility 로 실제 계산한 결과를 포함(신축분양 3 + 재건축 1).
- presets: 계산기(site/js/calc-ui.js)의 상태 키(st, 실무단위)와 정확히 일치하는
  프리셋. applyPreset(Object.assign)이 그대로 병합할 수 있어야 한다.

데이터 근거(코드로 산출):
  분양가   = 해당 시도 HUG 최근 3개월 평균 ㎡당가 → 평당만원 환산
  공사비   = 평당 750만원 × (CCI 최신 / CCI 2023 평균)
  금리     = ECOS 최신 기준금리 + 스프레드(브릿지 +5.5%p, PF +3.5%p — 가정)
  토지비   = 사례별 합리 가정(notes 명시)

cases[].inputs 는 calc-ui.js 의 buildInputs 를 1:1 이식한 build_inputs_from_state
로 프리셋(st)에서 파생한다 → 프리셋과 사례가 항상 정합.
"""

import datetime
import json
import math
import statistics
from pathlib import Path

from src.analysis import zoning
from src.analysis.feasibility import run_feasibility

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT = ROOT / "out"

PY = 3.305785  # ㎡/평 (calc-ui.js 와 동일 상수)
EOK = 1e8      # 억원 → 원

# 공사비 기준 단가(평당만원) — CCI 로 시점보정. 근거: 스펙 고정값 750만원/평.
BASE_UNIT_COST_PY = 750.0
BRIDGE_SPREAD = 5.5  # %p (가정: 브릿지 = 기준금리 + 5.5%p)
PF_SPREAD = 3.5      # %p (가정: PF = 기준금리 + 3.5%p)
RELO_SPREAD = 2.5    # %p (가정: 이주비 대여 = 기준금리 + 2.5%p)
MEMBER_DISCOUNT = 0.85  # 조합원 분양가 = 일반분양가 × 0.85 (가정)


# --------------------------------------------------------------------------- #
# 단위 변환 (calc-ui.js 와 동일)
# --------------------------------------------------------------------------- #
def pyman_to_wonm2(x: float) -> float:
    """평당 x만원 → 원/㎡  = (x×10000) / (㎡/평)."""
    return (x * 10000) / PY


def wonm2_to_pyman(v: float) -> float:
    """원/㎡ → 평당만원  = v × (㎡/평) / 10000."""
    return v * PY / 10000.0


def _jsround(x: float) -> int:
    """JS Math.round (half-up) 를 재현 — 계산기와 pf/relo 개월 산정 일치."""
    return int(math.floor(x + 0.5))


# --------------------------------------------------------------------------- #
# 데이터 로드·파생 근거값
# --------------------------------------------------------------------------- #
def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def hug_price_py(hug: dict, sido: str) -> float:
    """해당 시도 HUG 최근 3개월 평균 ㎡당가 → 평당만원."""
    series = hug["presale_price"][sido]
    avg_wonm2 = statistics.mean(p["value"] for p in series[-3:])
    return round(wonm2_to_pyman(avg_wonm2), 1)


def cci_factor(kosis: dict) -> float:
    """CCI 최신 / CCI 2023 평균 (공사비 시점보정 계수)."""
    cci = kosis["cci"]
    latest = cci[-1]["value"]
    y2023 = [p["value"] for p in cci if p["ym"].startswith("2023")]
    return latest / statistics.mean(y2023)


def unit_cost_py(kosis: dict) -> float:
    """공사비 평당만원 = 750 × CCI 보정계수."""
    return round(BASE_UNIT_COST_PY * cci_factor(kosis), 1)


def base_rate_pct(ecos: dict) -> float:
    """ECOS 최신 기준금리(%)."""
    return ecos["base_rate"][-1]["value"]


# --------------------------------------------------------------------------- #
# 프리셋(st) → 수지 입력 스키마  (calc-ui.js buildInputs 의 1:1 이식)
# --------------------------------------------------------------------------- #
def build_inputs_from_state(s: dict, mode: str) -> dict:
    zi = zoning.derive(s["land_area"], s["zone"], {
        "mix": {"residential": 1 - s["nb_ratio"] / 100,
                "neighborhood": s["nb_ratio"] / 100},
        "avg_supply_m2": s["avg_supply"],
    })

    units = []
    if mode == "신축분양":
        units.append({"name": "주거", "count": zi["units_est"],
                      "supply_m2": s["avg_supply"],
                      "price_per_m2": pyman_to_wonm2(s["price_py"])})
        if zi["neighborhood_gfa_m2"] > 0:
            units.append({"name": "근생", "count": 1,
                          "supply_m2": zi["neighborhood_gfa_m2"] * 0.6,
                          "price_per_m2": pyman_to_wonm2(s["price_py"]) * 1.15})

    inputs = {
        "mode": mode,
        "revenue": {"units": units, "sell_through": s["sell_through"] / 100, "other_income": 0},
        "cost": {
            "land": {"purchase": s["land_eok"] * EOK if mode == "신축분양" else 0,
                     "acq_tax_rate": 0.046, "misc_rate": 0.01},
            "construction": {"gfa_m2": zi["buildable_gfa_m2"],
                             "unit_cost_per_m2": pyman_to_wonm2(s["unit_cost_py"])},
            "indirect_rate": s["indirect"] / 100,
            "marketing_rate": s["marketing"] / 100,
            "contingency_rate": s["contingency"] / 100,
        },
        "finance": {
            "equity": s["equity_eok"] * EOK,
            "bridge": {"amount": s["bridge_eok"] * EOK, "rate": s["bridge_rate"] / 100,
                       "months": s["bridge_mo"]},
            "pf": {"amount": s["pf_eok"] * EOK, "rate": s["pf_rate"] / 100,
                   "months": _jsround(s["months"] * 0.8), "drawdown": s["pf_draw"] / 100},
            "fee_rate": s["fee"] / 100,
        },
        "schedule": {"months_total": s["months"]},
    }
    if mode != "신축분양":
        inputs["redevelopment"] = {
            "prior_asset_value": s["prior_eok"] * EOK,
            "member_count": s["members"],
            "member_supply_m2": s["mem_supply"],
            "member_price_per_m2": pyman_to_wonm2(s["mem_price_py"]),
            "general_units": [{"name": "일반", "count": s["gen_units"],
                               "supply_m2": s["avg_supply"],
                               "price_per_m2": pyman_to_wonm2(s["price_py"])}],
            "relocation_loan": {"amount": s["relo_eok"] * EOK, "rate": s["relo_rate"] / 100,
                                "months": _jsround(s["months"] * 0.7)},
            "demolition_cost": s["demo_eok"] * EOK,
            "rental_ratio": s["rental"] / 100 if mode == "재개발" else 0,
            "cash_settlement_ratio": s["cashout"] / 100,
        }
    return inputs


# --------------------------------------------------------------------------- #
# 프리셋 구성 (실무단위 · calc-ui.js st 키와 일치)
# --------------------------------------------------------------------------- #
def build_presets(hug: dict, kosis: dict, ecos: dict) -> dict:
    ucp = unit_cost_py(kosis)                       # 공사비 평당만원(CCI 보정)
    base = base_rate_pct(ecos)                      # 기준금리 %
    br = round(base + BRIDGE_SPREAD, 2)             # 브릿지 금리 %
    pr = round(base + PF_SPREAD, 2)                 # PF 금리 %
    rr = round(base + RELO_SPREAD, 2)              # 이주비 금리 %
    gg = hug_price_py(hug, "경기")                  # 경기 분양가 평당만원
    bs = hug_price_py(hug, "부산")                  # 부산 분양가 평당만원
    su = hug_price_py(hug, "서울")                  # 서울 분양가 평당만원

    presets = {
        # ① 수도권 아파트(경기)
        "수도권아파트": {
            "land_area": 15000, "zone": "R3", "nb_ratio": 0,
            "avg_supply": 84.9, "price_py": gg, "sell_through": 95,
            "land_eok": 380, "unit_cost_py": ucp, "months": 36,
            "indirect": 6, "marketing": 3.5, "contingency": 1,
            "equity_eok": 350, "bridge_eok": 600, "bridge_rate": br, "bridge_mo": 12,
            "pf_eok": 2000, "pf_rate": pr, "pf_draw": 55, "fee": 1.5,
        },
        # ② 지방 광역시 아파트(부산)
        "지방아파트": {
            "land_area": 18000, "zone": "R3", "nb_ratio": 0,
            "avg_supply": 84.9, "price_py": bs, "sell_through": 90,
            "land_eok": 480, "unit_cost_py": ucp, "months": 34,
            "indirect": 6, "marketing": 4, "contingency": 1,
            "equity_eok": 300, "bridge_eok": 500, "bridge_rate": br, "bridge_mo": 12,
            "pf_eok": 1800, "pf_rate": pr, "pf_draw": 55, "fee": 1.5,
        },
        # ③ 오피스텔(서울, 근생 혼합)
        "오피스텔": {
            "land_area": 3000, "zone": "RS", "nb_ratio": 20,
            "avg_supply": 44.0, "price_py": su, "sell_through": 92,
            "land_eok": 700, "unit_cost_py": ucp, "months": 30,
            "indirect": 6.5, "marketing": 4, "contingency": 1,
            "equity_eok": 350, "bridge_eok": 500, "bridge_rate": br, "bridge_mo": 12,
            "pf_eok": 900, "pf_rate": pr, "pf_draw": 60, "fee": 1.5,
        },
        # ④ 서울 재건축
        "서울재건축": {
            "__mode": "재건축",
            "land_area": 32000, "zone": "R3", "nb_ratio": 0,
            "avg_supply": 84.9, "price_py": su, "sell_through": 95,
            "land_eok": 0, "unit_cost_py": ucp, "months": 42,
            "indirect": 6, "marketing": 3, "contingency": 1,
            "equity_eok": 500, "bridge_eok": 500, "bridge_rate": br, "bridge_mo": 12,
            "pf_eok": 3000, "pf_rate": pr, "pf_draw": 55, "fee": 1.5,
            # 정비
            "prior_eok": 4800, "members": 500, "mem_supply": 84.9,
            "mem_price_py": round(su * MEMBER_DISCOUNT, 1),
            "gen_units": 200, "relo_eok": 800, "relo_rate": rr, "demo_eok": 150,
            "rental": 0, "cashout": 5,
        },
    }
    return presets


# --------------------------------------------------------------------------- #
# 사례 notes (실데이터 근거 문자열)
# --------------------------------------------------------------------------- #
def _notes(kind: str, s: dict, kosis: dict) -> list:
    fac = cci_factor(kosis)
    common = [
        f"공사비: 평당 {BASE_UNIT_COST_PY:.0f}만원 × CCI 보정(최신/2023평균={fac:.3f}) "
        f"= 평당 {s['unit_cost_py']:.0f}만원 (한국건설기술연구원 건설공사비지수)",
        f"금융: ECOS 최신 기준금리 기준 — 브릿지 {s['bridge_rate']:.2f}%(+{BRIDGE_SPREAD}%p), "
        f"PF {s['pf_rate']:.2f}%(+{PF_SPREAD}%p) 가정",
        "취득세 4.6%·기타 1.0%·간접비·판매비·예비비는 실무 표준 요율 가정",
    ]
    if kind == "수도권":
        return [
            f"분양가: 경기 HUG 최근 3개월 평균 ㎡당가 → 평당 {s['price_py']:.0f}만원 "
            f"(주택도시보증공사 민간아파트 분양가)",
            f"토지비 {s['land_eok']:.0f}억(대지 {s['land_area']:,}㎡, 3종일반주거 가정) — "
            f"㎡당 약 {s['land_eok']*1e8/s['land_area']/1e4:.0f}만원",
            f"용적률·세대수는 용도지역 모듈(서울 조례 대표값)로 산정, 분양률 {s['sell_through']}% 가정",
        ] + common
    if kind == "지방":
        return [
            f"분양가: 부산 HUG 최근 3개월 평균 ㎡당가 → 평당 {s['price_py']:.0f}만원 "
            f"(주택도시보증공사 민간아파트 분양가)",
            f"토지비 {s['land_eok']:.0f}억(대지 {s['land_area']:,}㎡) — 수도권 대비 낮은 지가 가정, "
            f"분양률 {s['sell_through']}%(지방 흡수율 보수적)",
        ] + common
    if kind == "오피스텔":
        return [
            f"분양가: 서울 HUG 최근 3개월 평균 ㎡당가 → 평당 {s['price_py']:.0f}만원 "
            f"(오피스텔 대용치로 서울 분양가 사용)",
            f"준주거 근생 혼합 {s['nb_ratio']}% — 근생부는 주거 대비 +15% 단가·전용 60% 가정",
            f"토지비 {s['land_eok']:.0f}억(도심 소규모 대지 {s['land_area']:,}㎡), "
            f"평균 공급 {s['avg_supply']}㎡(소형 위주)",
        ] + common
    if kind == "재건축":
        return [
            f"일반분양가: 서울 HUG 최근 3개월 평균 → 평당 {s['price_py']:.0f}만원, "
            f"조합원분양가는 그 {MEMBER_DISCOUNT:.0%} (평당 {s['mem_price_py']:.0f}만원) 가정",
            f"종전자산평가액 {s['prior_eok']:,}억·조합원 {s['members']}명·일반분양 {s['gen_units']}세대 "
            f"(비례율·분담금 산출 기준)",
            f"이주비 대여 {s['relo_eok']:.0f}억({s['relo_rate']:.2f}%, +{RELO_SPREAD}%p)·"
            f"철거명도 {s['demo_eok']:.0f}억·현금청산 {s['cashout']}% 가정",
        ] + common
    return common


# --------------------------------------------------------------------------- #
# 사례 4건 조립
# --------------------------------------------------------------------------- #
_CASE_SPEC = [
    ("신축분양", "수도권 공동주택 표준 사례", "수도권아파트", "수도권"),
    ("신축분양", "지방 광역시 공동주택 표준 사례(부산)", "지방아파트", "지방"),
    ("신축분양", "오피스텔 표준 사례(서울, 근생 혼합)", "오피스텔", "오피스텔"),
    ("재건축", "서울 재건축 표준 사례", "서울재건축", "재건축"),
]


def build() -> dict:
    hug = _load("hug.json")
    kosis = _load("kosis.json")
    ecos = _load("ecos.json")

    presets = build_presets(hug, kosis, ecos)

    cases = []
    for type_, name, preset_key, note_kind in _CASE_SPEC:
        s = presets[preset_key]
        mode = s.get("__mode", "신축분양")
        inputs = build_inputs_from_state(s, mode)
        result = run_feasibility(inputs)
        cases.append({
            "type": type_,
            "name": name,
            "preset": preset_key,
            "inputs": inputs,
            "result": result,
            "notes": _notes(note_kind, s, kosis),
        })

    return {
        "cases": cases,
        "presets": presets,
        "meta": {
            "sources": [hug.get("source"), kosis.get("source"), ecos.get("source")],
            "cci_factor": round(cci_factor(kosis), 4),
            "base_rate_pct": base_rate_pct(ecos),
            "built_at": datetime.date.today().isoformat(),
        },
    }


def main() -> Path:
    data = build()
    OUT.mkdir(exist_ok=True)
    path = OUT / "cases.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"cases.json 생성: {path}")
    for c in data["cases"]:
        r = c["result"]
        prof_eok = r["profit"] / EOK
        margin = (r["margin_on_revenue"] or 0) * 100
        extra = ""
        if r["proportion_rate"] is not None:
            extra = f" · 비례율 {r['proportion_rate']*100:.1f}%"
        print(f"  [{c['type']}] {c['name']}: 이익 {prof_eok:,.0f}억 · "
              f"마진 {margin:.1f}%{extra}")
    return path


if __name__ == "__main__":
    main()
