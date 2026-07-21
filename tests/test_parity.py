"""Python 코어 ↔ JS 이식본(site/js/feasibility.js) 패리티(일치) 검증.

시드 고정(random.seed(42))으로 경계 포함 무작위 입력 50조를 만들고,
각 입력을 Python `run_feasibility` 와 node 로 실행한 JS `Feasibility.run` 에
동일하게 통과시켜 결과를 원소 단위로 비교한다.

비교 규칙(스칼라):
  math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)
  → |Δ| ≤ max(1e-9·max(|a|,|b|), 1e-6). 상대 1e-9 / 절대 1e-6 중 큰 쪽.
None(=Python) ↔ null(=JS) 은 양쪽 모두 None 일 때만 일치로 본다.
cost dict 는 키별로, cashflow_quarterly 는 원소별로 같은 기준을 적용한다.
"""

import json
import math
import os
import random
import subprocess

import pytest

from src.analysis.feasibility import run_feasibility

NODE = "/opt/homebrew/bin/node"
JS_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "site", "js", "feasibility.js")
)

N_SHINCHUK = 50           # 신축분양(경계 5 + 무작위 45)
N_REDEV = 20              # 정비사업(재개발·재건축·리모델링) 무작위
N_INCOME = 8              # 수익형(terminal 스케줄) 고정 케이스
N_CASES = N_SHINCHUK + N_REDEV + N_INCOME  # 78
REL_TOL = 1e-9
ABS_TOL = 1e-6


# --------------------------------------------------------------------------- #
# 입력 생성
# --------------------------------------------------------------------------- #
def _units(rng, n):
    """세대 n종 생성. count 는 int(경계 1·500), 나머지는 float."""
    out = []
    for _ in range(n):
        out.append(
            {
                "name": "U",
                "count": rng.randint(1, 500),
                "supply_m2": rng.uniform(40, 200),
                "price_per_m2": rng.uniform(2e6, 2e7),
            }
        )
    return out


def _rate(rng):
    return rng.uniform(0.0, 0.1)


def _random_case(rng):
    """요구된 범위에서 한 조를 생성."""
    sell_through = 0.0 if rng.random() < 0.15 else rng.uniform(0.3, 1.0)
    other_income = 0 if rng.random() < 0.4 else rng.uniform(0, 5e9)
    equity = 0 if rng.random() < 0.2 else rng.uniform(1e9, 5e10)
    bridge_amt = 0 if rng.random() < 0.3 else rng.uniform(1e8, 1e10)
    pf_amt = 0 if rng.random() < 0.3 else rng.uniform(1e9, 5e10)

    case = {
        "revenue": {
            "units": _units(rng, rng.randint(1, 4)),
            "sell_through": sell_through,
            "other_income": other_income,
        },
        "cost": {
            "land": {
                "purchase": rng.uniform(1e9, 1e11),
                "acq_tax_rate": _rate(rng),
                "misc_rate": _rate(rng),
            },
            "construction": {
                "gfa_m2": rng.uniform(1e3, 2e5),
                "unit_cost_per_m2": rng.uniform(1.5e6, 4e6),
            },
            "indirect_rate": _rate(rng),
            "marketing_rate": _rate(rng),
            "contingency_rate": _rate(rng),
        },
        "finance": {
            "equity": equity,
            "bridge": {
                "amount": bridge_amt,
                "rate": _rate(rng),
                "months": rng.randint(3, 36),
            },
            "pf": {
                "amount": pf_amt,
                "rate": _rate(rng),
                "months": rng.randint(6, 48),
                "drawdown": rng.uniform(0.0, 1.0),
            },
            "fee_rate": _rate(rng),
        },
        "schedule": {"months_total": rng.randint(6, 60)},
        "discount_rate": _rate(rng),
    }
    # 가끔 discount_rate 키를 제거 → 기본값(0.08) 경로 검증
    if rng.random() < 0.15:
        del case["discount_rate"]
    return case


def _random_redev_case(rng):
    """정비사업(재개발·재건축·리모델링) 한 조 생성.

    현금청산·임대의무·이주비·철거비·토지비 0 관행·일반분양 0종(리모델링) 등
    경계를 무작위로 포함한다. mode 는 세 정비사업 중 하나.
    """
    mode = rng.choice(["재개발", "재건축", "리모델링"])
    cash_ratio = 0.0 if rng.random() < 0.4 else rng.uniform(0.0, 0.4)
    rental = 0.0 if rng.random() < 0.5 else rng.uniform(0.0, 0.3)
    n_general = rng.randint(0, 3)  # 0 → 일반분양 없음(리모델링 극단)

    case = {
        "mode": mode,
        "revenue": {
            "sell_through": 0.0 if rng.random() < 0.1 else rng.uniform(0.3, 1.0),
            "other_income": 0 if rng.random() < 0.5 else rng.uniform(0, 5e9),
        },
        "redevelopment": {
            "prior_asset_value": rng.uniform(1e10, 2e11),
            "member_count": rng.randint(20, 500),
            "member_supply_m2": rng.uniform(60, 150),
            "member_price_per_m2": rng.uniform(3e6, 2e7),
            "general_units": _units(rng, n_general),
            "relocation_loan": {
                "amount": 0 if rng.random() < 0.3 else rng.uniform(1e9, 3e10),
                "rate": _rate(rng),
                "months": rng.randint(0, 36),
            },
            "demolition_cost": 0 if rng.random() < 0.3 else rng.uniform(1e9, 2e10),
            "rental_ratio": rental,
            "cash_settlement_ratio": cash_ratio,
        },
        "cost": {
            "land": {
                # 정비사업 관행: 토지비 0 우세
                "purchase": 0 if rng.random() < 0.6 else rng.uniform(1e9, 5e10),
                "acq_tax_rate": _rate(rng),
                "misc_rate": _rate(rng),
            },
            "construction": {
                "gfa_m2": rng.uniform(1e4, 3e5),
                "unit_cost_per_m2": rng.uniform(1.5e6, 4e6),
            },
            "indirect_rate": _rate(rng),
            "marketing_rate": _rate(rng),
            "contingency_rate": _rate(rng),
        },
        "finance": {
            "equity": 0 if rng.random() < 0.3 else rng.uniform(1e9, 5e10),
            "bridge": {
                "amount": 0 if rng.random() < 0.4 else rng.uniform(1e8, 1e10),
                "rate": _rate(rng),
                "months": rng.randint(0, 36),
            },
            "pf": {
                "amount": 0 if rng.random() < 0.4 else rng.uniform(1e9, 5e10),
                "rate": _rate(rng),
                "months": rng.randint(0, 48),
                "drawdown": rng.uniform(0.0, 1.0),
            },
            "fee_rate": _rate(rng),
        },
        "schedule": {"months_total": rng.randint(6, 60)},
        "discount_rate": _rate(rng),
    }
    if rng.random() < 0.15:
        del case["discount_rate"]
    return case


def _boundary_cases():
    """경계·특수 상황을 고정 입력으로 명시."""
    base_land = {"purchase": 1e9, "acq_tax_rate": 0.0, "misc_rate": 0.0}
    base_constr = {"gfa_m2": 1e3, "unit_cost_per_m2": 1.5e6}
    cases = []

    # 1) 전 요율 0 · 무차입 · equity 0 · 최소 규모 · 최소 기간(6개월 → 2분기, 중간분기 없음)
    cases.append(
        {
            "revenue": {
                "units": [{"name": "A", "count": 1, "supply_m2": 40.0, "price_per_m2": 2e6}],
                "sell_through": 1.0,
                "other_income": 0,
            },
            "cost": {
                "land": dict(base_land),
                "construction": dict(base_constr),
                "indirect_rate": 0.0,
                "marketing_rate": 0.0,
                "contingency_rate": 0.0,
            },
            "finance": {
                "equity": 0,
                "bridge": {"amount": 0, "rate": 0.0, "months": 0},
                "pf": {"amount": 0, "rate": 0.0, "months": 0, "drawdown": 0.0},
                "fee_rate": 0.0,
            },
            "schedule": {"months_total": 6},
            "discount_rate": 0.0,
        }
    )

    # 2) sell_through 0 → 총수입 0 (margin_on_revenue=None, 전분기 음수 → IRR None)
    cases.append(
        {
            "revenue": {
                "units": [{"name": "A", "count": 100, "supply_m2": 100.0, "price_per_m2": 1e7}],
                "sell_through": 0.0,
                "other_income": 0,
            },
            "cost": {
                "land": {"purchase": 1e10, "acq_tax_rate": 0.046, "misc_rate": 0.01},
                "construction": {"gfa_m2": 5e4, "unit_cost_per_m2": 2.5e6},
                "indirect_rate": 0.06,
                "marketing_rate": 0.035,
                "contingency_rate": 0.01,
            },
            "finance": {
                "equity": 0,
                "bridge": {"amount": 1e9, "rate": 0.1, "months": 12},
                "pf": {"amount": 4e9, "rate": 0.05, "months": 24, "drawdown": 0.5},
                "fee_rate": 0.01,
            },
            "schedule": {"months_total": 36},
            "discount_rate": 0.08,
        }
    )

    # 3) 최대 규모 상한 · 최장 기간(60개월 → 20분기) · other_income 존재
    cases.append(
        {
            "revenue": {
                "units": [
                    {"name": "A", "count": 500, "supply_m2": 200.0, "price_per_m2": 2e7},
                    {"name": "B", "count": 500, "supply_m2": 200.0, "price_per_m2": 2e7},
                ],
                "sell_through": 1.0,
                "other_income": 5e9,
            },
            "cost": {
                "land": {"purchase": 1e11, "acq_tax_rate": 0.1, "misc_rate": 0.1},
                "construction": {"gfa_m2": 2e5, "unit_cost_per_m2": 4e6},
                "indirect_rate": 0.1,
                "marketing_rate": 0.1,
                "contingency_rate": 0.1,
            },
            "finance": {
                "equity": 5e10,
                "bridge": {"amount": 1e10, "rate": 0.1, "months": 36},
                "pf": {"amount": 5e10, "rate": 0.1, "months": 48, "drawdown": 1.0},
                "fee_rate": 0.1,
            },
            "schedule": {"months_total": 60},
            "discount_rate": 0.1,
        }
    )

    # 4) discount_rate 키 제거 → 기본값 0.08 경로
    c4 = json.loads(json.dumps(cases[2]))
    del c4["discount_rate"]
    cases.append(c4)

    # 5) other_income 만 있고 sales 0 (sell_through 0) → total_inflow>0 판매비 분배 검증
    cases.append(
        {
            "revenue": {
                "units": [{"name": "A", "count": 50, "supply_m2": 84.0, "price_per_m2": 1.2e7}],
                "sell_through": 0.0,
                "other_income": 2e9,
            },
            "cost": {
                "land": {"purchase": 3e9, "acq_tax_rate": 0.046, "misc_rate": 0.01},
                "construction": {"gfa_m2": 1.2e4, "unit_cost_per_m2": 2e6},
                "indirect_rate": 0.06,
                "marketing_rate": 0.035,
                "contingency_rate": 0.01,
            },
            "finance": {
                "equity": 2e9,
                "bridge": {"amount": 5e8, "rate": 0.08, "months": 10},
                "pf": {"amount": 2e9, "rate": 0.06, "months": 20, "drawdown": 0.4},
                "fee_rate": 0.015,
            },
            "schedule": {"months_total": 9},
            "discount_rate": 0.05,
        }
    )

    return cases


def make_inputs():
    """고정 시드로 신축분양(경계+무작위) + 정비사업 무작위 = 총 N_CASES 조 생성.

    앞 N_SHINCHUK 조는 기존 신축분양 세트를 그대로 보존(시드·순서 동일)하고,
    이어서 N_REDEV 조의 정비사업 케이스를 덧붙인다.
    """
    rng = random.Random()
    rng.seed(42)
    bounds = _boundary_cases()
    cases = list(bounds)
    while len(cases) < N_SHINCHUK:
        cases.append(_random_case(rng))
    cases = cases[:N_SHINCHUK]
    for _ in range(N_REDEV):
        cases.append(_random_redev_case(rng))
    cases.extend(_income_cases())
    return cases


def _income_cases():
    """수익형(오피스·상업) terminal 스케줄 고정 케이스 — NOI÷cap 매각가치를
    준공 시 일시 유입으로 편성하는 경로의 Python↔JS 패리티를 고정한다."""
    def mk(exit_value, months, other=0.0, schedule="terminal", sell=1.0, land=8e10):
        return {
            "mode": "신축분양",
            "revenue": {"units": [{"name": "오피스", "count": 1, "supply_m2": 1,
                                   "price_per_m2": exit_value}],
                        "sell_through": sell, "other_income": other,
                        "schedule": schedule},
            "cost": {"land": {"purchase": land, "acq_tax_rate": 0.046, "misc_rate": 0.01},
                     "construction": {"gfa_m2": 4.2e4, "unit_cost_per_m2": 2.69e6},
                     "indirect_rate": 0.06, "marketing_rate": 0.015,
                     "contingency_rate": 0.01},
            "finance": {"equity": 8e10,
                        "bridge": {"amount": 1e11, "rate": 0.0825, "months": 10},
                        "pf": {"amount": 4e11, "rate": 0.0625, "months": 34, "drawdown": 0.55},
                        "fee_rate": 0.015},
            "schedule": {"months_total": months},
        }
    return [
        mk(4.32e11, 42),                       # 서울오피스 프리셋 규모
        mk(4.32e11, 42, other=3e9),            # 기타수입 동반 (other는 양쪽 다 qN)
        mk(1.5e11, 7),                         # 3분기 소형 — 이월 경계
        mk(2e11, 6),                           # 2분기 — middle 없음
        mk(9e10, 3),                           # 1분기 — q0=qN 동일 분기
        mk(0.0, 24),                           # 매각가치 0 (cap=0 가드 경로)
        mk(4.32e11, 42, schedule="presale"),   # 동일 입력 presale 명시 — 분기 배분 대조군
        mk(3e11, 60, sell=0.7),               # terminal 은 sell_through 반영 후 일시 유입
    ]


INPUTS = make_inputs()


# --------------------------------------------------------------------------- #
# node 실행: 입력 배열 → JS 결과 배열 (단일 프로세스 왕복)
# --------------------------------------------------------------------------- #
def run_node(inputs):
    runner = (
        "const fs=require('fs');"
        "require(" + json.dumps(JS_PATH) + ");"
        "const data=JSON.parse(fs.readFileSync(0,'utf8'));"
        "const out=data.map(function(x){return global.Feasibility.run(x);});"
        "process.stdout.write(JSON.stringify(out));"
    )
    proc = subprocess.run(
        [NODE, "-e", runner],
        input=json.dumps(inputs),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("node 실행 실패:\n" + proc.stderr)
    return json.loads(proc.stdout)


PY_RESULTS = [run_feasibility(x) for x in INPUTS]
JS_RESULTS = run_node(INPUTS)


# --------------------------------------------------------------------------- #
# 비교 유틸
# --------------------------------------------------------------------------- #
def _close(a, b, path):
    """스칼라/None 일치 검사. 불일치면 상세 메시지와 함께 실패."""
    if a is None or b is None:
        assert a is None and b is None, f"{path}: None 불일치 py={a!r} js={b!r}"
        return
    assert isinstance(a, (int, float)) and isinstance(b, (int, float)), (
        f"{path}: 타입 불일치 py={a!r} js={b!r}"
    )
    assert math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL), (
        f"{path}: 수치 불일치 py={a!r} js={b!r} Δ={a - b!r}"
    )


def _compare(py, js, idx):
    p = f"case[{idx}]"

    # 스칼라들 (정비사업 지표 3종 포함 — 신축분양은 양쪽 None)
    for k in ("revenue_total", "cost_total", "profit",
              "margin_on_revenue", "margin_on_cost", "roe", "npv", "irr_annual",
              "proportion_rate", "rights_value", "member_contribution"):
        _close(py[k], js[k], f"{p}.{k}")

    # cost dict: 키집합 동일 + 키별 비교
    assert set(py["cost"].keys()) == set(js["cost"].keys()), (
        f"{p}.cost 키집합 불일치 py={set(py['cost'])} js={set(js['cost'])}"
    )
    for k in py["cost"]:
        _close(py["cost"][k], js["cost"][k], f"{p}.cost.{k}")

    # cashflow_quarterly: 길이 동일 + 원소별 비교
    pcf, jcf = py["cashflow_quarterly"], js["cashflow_quarterly"]
    assert len(pcf) == len(jcf), f"{p}.cashflow 길이 불일치 py={len(pcf)} js={len(jcf)}"
    for q in range(len(pcf)):
        _close(pcf[q], jcf[q], f"{p}.cashflow[{q}]")


# --------------------------------------------------------------------------- #
# 테스트
# --------------------------------------------------------------------------- #
def test_case_count():
    assert len(INPUTS) == N_CASES
    assert len(PY_RESULTS) == N_CASES
    assert len(JS_RESULTS) == N_CASES


@pytest.mark.parametrize("idx", range(N_CASES))
def test_parity(idx):
    _compare(PY_RESULTS[idx], JS_RESULTS[idx], idx)


def test_covers_boundaries():
    """경계 케이스가 의도한 특수값(None 마진·None IRR 등)을 실제로 유발하는지."""
    # case[1]: 총수입 0 → margin_on_revenue None, IRR None
    assert PY_RESULTS[1]["margin_on_revenue"] is None
    assert PY_RESULTS[1]["irr_annual"] is None
    assert JS_RESULTS[1]["margin_on_revenue"] is None
    assert JS_RESULTS[1]["irr_annual"] is None
    # case[0]: equity 0 → roe None
    assert PY_RESULTS[0]["roe"] is None
    assert JS_RESULTS[0]["roe"] is None
    # None 결과가 최소 1건 이상 존재(패리티가 None 경로도 실제로 탄다)
    assert any(r["irr_annual"] is None for r in PY_RESULTS)
    # 신축분양 케이스는 정비사업 지표가 None
    assert PY_RESULTS[0]["proportion_rate"] is None
    assert JS_RESULTS[0]["proportion_rate"] is None
    # 정비사업 케이스(뒤 N_REDEV 조)는 비례율이 실수로 산출됨(양쪽 일치)
    assert any(r["proportion_rate"] is not None for r in PY_RESULTS[N_SHINCHUK:])
    assert any(r["proportion_rate"] is not None for r in JS_RESULTS[N_SHINCHUK:])
