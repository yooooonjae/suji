"""토지·용도지역 모듈 테스트.

용적률 → 지상 연면적 → 세대수 파이프라인을 수기(hand-calc) 검산으로 assert 한다.
후반부는 Python 코어 ↔ JS 이식본(site/js/zoning.js) 패리티를 node 로 교차검증한다.
"""

import json
import os
import subprocess

import pytest

from src.analysis.zoning import derive, ZONES


# --------------------------------------------------------------------------- #
# 수기(hand-calc) 검산 사례
# --------------------------------------------------------------------------- #
def test_r2_seoul_hand_calc():
    """R2·서울 조례·대지 10,000㎡, mix 0.9/0.1, avg 84.9·eff 0.75.

    far_applied = 2.0(서울 조례 200%)
    buildable   = 10,000 × 2.0 = 20,000㎡
    residential = 20,000 × 0.9 = 18,000㎡, neighborhood = 2,000㎡
    units_est   = floor(18,000 × 0.75 / 84.9) = floor(159.010…) = 159
    """
    r = derive(
        10_000,
        "R2",
        {"mix": {"residential": 0.9, "neighborhood": 0.1}, "avg_supply_m2": 84.9, "efficiency": 0.75},
    )
    assert r["zone_name"] == "제2종일반주거지역"
    assert r["bcr_legal"] == 0.60
    assert r["far_legal_max"] == 2.5
    assert r["far_applied"] == 2.0
    assert r["buildable_gfa_m2"] == pytest.approx(20_000.0)
    assert r["residential_gfa_m2"] == pytest.approx(18_000.0)
    assert r["neighborhood_gfa_m2"] == pytest.approx(2_000.0)
    assert r["units_est"] == 159
    assert isinstance(r["units_est"], int)
    assert isinstance(r["assumptions"], list) and r["assumptions"]


def test_r3_legal_ceiling_hand_calc():
    """R3·시행령 상한(use_seoul=False)·대지 5,000㎡·주거 100%.

    far_applied = 3.0(시행령 상한 300%)
    buildable   = 5,000 × 3.0 = 15,000㎡, residential = 15,000㎡, neighborhood = 0
    units_est   = floor(15,000 × 0.75 / 84.9) = floor(132.508…) = 132
    """
    r = derive(5_000, "R3", {"use_seoul": False})
    assert r["zone_name"] == "제3종일반주거지역"
    assert r["bcr_legal"] == 0.50
    assert r["far_legal_max"] == 3.0
    assert r["far_applied"] == 3.0
    assert r["buildable_gfa_m2"] == pytest.approx(15_000.0)
    assert r["residential_gfa_m2"] == pytest.approx(15_000.0)
    assert r["neighborhood_gfa_m2"] == pytest.approx(0.0)
    assert r["units_est"] == 132


def test_r1_far_override_exceeds_ceiling_hand_calc():
    """R1·far_override 2.5(시행령 상한 2.0 초과)·대지 3,000㎡·mix 0.8/0.2.

    far_applied = 2.5(override), buildable = 3,000 × 2.5 = 7,500㎡
    residential = 6,000㎡, neighborhood = 1,500㎡
    units_est   = floor(6,000 × 0.75 / 84.9) = floor(53.003…) = 53
    override 가 시행령 상한을 초과 → 경고 문자열이 assumptions 에 포함(막지는 않음).
    """
    r = derive(
        3_000,
        "R1",
        {"far_override": 2.5, "mix": {"residential": 0.8, "neighborhood": 0.2}},
    )
    assert r["zone_name"] == "제1종일반주거지역"
    assert r["far_legal_max"] == 2.0
    assert r["far_applied"] == 2.5
    assert r["buildable_gfa_m2"] == pytest.approx(7_500.0)
    assert r["residential_gfa_m2"] == pytest.approx(6_000.0)
    assert r["neighborhood_gfa_m2"] == pytest.approx(1_500.0)
    assert r["units_est"] == 53
    assert any("초과" in a for a in r["assumptions"]), "override 상한 초과 경고 누락"


def test_unknown_zone_raises_valueerror():
    with pytest.raises(ValueError):
        derive(10_000, "ZZ")


# --------------------------------------------------------------------------- #
# 기본값·옵션 경로
# --------------------------------------------------------------------------- #
def test_defaults_residential_100pct_and_seoul():
    """options=None → 서울 조례·주거 100%·avg 84.9·eff 0.75 기본."""
    r = derive(1_000, "R2")
    assert r["far_applied"] == 2.0            # 서울 조례 기본
    assert r["residential_gfa_m2"] == pytest.approx(2_000.0)
    assert r["neighborhood_gfa_m2"] == pytest.approx(0.0)


def test_override_within_ceiling_no_warning():
    r = derive(1_000, "CG", {"far_override": 10.0})  # CG 상한 13.0 → 이내
    assert r["far_applied"] == 10.0
    assert not any("초과" in a for a in r["assumptions"])


def test_zone_table_is_single_source():
    """상수 테이블이 스펙 값과 일치(단일 출처)."""
    assert set(ZONES) == {"R1", "R2", "R3", "RS", "CG", "IS"}
    assert ZONES["CG"]["bcr_legal"] == 0.80
    assert ZONES["CG"]["far_legal_max"] == 13.0
    assert ZONES["CG"]["far_seoul"] == 8.0
    assert ZONES["IS"]["far_seoul"] == 4.0


# --------------------------------------------------------------------------- #
# Python ↔ JS 패리티 (node 교차검증)
# --------------------------------------------------------------------------- #
NODE = "/opt/homebrew/bin/node"
JS_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "site", "js", "zoning.js")
)

REL_TOL = 0.0
ABS_TOL = 1e-9


def _parity_cases():
    """무작위(시드 고정) 대지면적 × 전 지역코드 10조 + 옵션 변주."""
    import random

    rng = random.Random(7)
    zones = ["R1", "R2", "R3", "RS", "CG", "IS"]
    cases = []
    for i in range(10):
        zone = zones[i % len(zones)]
        site = rng.uniform(300.0, 50_000.0)
        opts = {
            "mix": {
                "residential": round(rng.uniform(0.5, 1.0), 4),
                "neighborhood": round(rng.uniform(0.0, 0.3), 4),
            },
            "use_seoul": (i % 2 == 0),
        }
        # 일부 케이스는 far_override(상한 초과 포함)로 경고 경로도 탐
        if i % 3 == 0:
            opts["far_override"] = round(rng.uniform(1.0, 15.0), 3)
        cases.append({"site_area_m2": site, "zone_code": zone, "options": opts})
    return cases


PARITY_CASES = _parity_cases()


def _run_node(cases):
    runner = (
        "require(" + json.dumps(JS_PATH) + ");"
        "const fs=require('fs');"
        "const data=JSON.parse(fs.readFileSync(0,'utf8'));"
        "const out=data.map(function(x){"
        "return global.Zoning.derive(x.site_area_m2, x.zone_code, x.options);});"
        "process.stdout.write(JSON.stringify(out));"
    )
    proc = subprocess.run(
        [NODE, "-e", runner],
        input=json.dumps(PARITY_CASES),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError("node 실행 실패:\n" + proc.stderr)
    return json.loads(proc.stdout)


def test_js_python_parity():
    js = _run_node(PARITY_CASES)
    assert len(js) == len(PARITY_CASES)
    for i, case in enumerate(PARITY_CASES):
        py = derive(case["site_area_m2"], case["zone_code"], case["options"])
        j = js[i]
        assert py["zone_name"] == j["zone_name"], f"case[{i}] zone_name"
        assert py["units_est"] == j["units_est"], f"case[{i}] units_est {py['units_est']}≠{j['units_est']}"
        for k in ("bcr_legal", "far_legal_max", "far_applied",
                  "buildable_gfa_m2", "residential_gfa_m2", "neighborhood_gfa_m2"):
            assert abs(py[k] - j[k]) < ABS_TOL, f"case[{i}].{k} py={py[k]} js={j[k]} Δ={py[k]-j[k]}"
        assert py["assumptions"] == j["assumptions"], f"case[{i}] assumptions 불일치"
