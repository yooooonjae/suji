"""토지·용도지역 모듈 — 용적률 → 지상 연면적 → 세대수 산출 코어.

단위: 면적=㎡, 건폐율/용적률/비율=소수(예 60%→0.60, 200%→2.0).
이후 JS(site/js/zoning.js)로 1:1 이식되므로 연산 순서를 고정하고 구조를 단순히 유지한다.

용도지역 상수 테이블(단일 출처, 아래 ZONES 가 유일한 근거값):

| 코드 | 명칭             | 건폐율 상한 | 용적률 범위      | 서울 조례 용적률       |
|------|------------------|------------|------------------|-----------------------|
| R1   | 제1종일반주거지역 | 60%        | 100~200%         | 150%                  |
| R2   | 제2종일반주거지역 | 60%        | 100~250%         | 200%                  |
| R3   | 제3종일반주거지역 | 50%        | 100~300%         | 250%                  |
| RS   | 준주거지역        | 70%        | 200~500%         | 400%                  |
| CG   | 일반상업지역      | 80%        | 200~1300%        | 800% (4대문 밖 기준)   |
| IS   | 준공업지역        | 70%        | 150~400%         | 400%                  |

출처:
  - 건폐율 상한: 국토의 계획 및 이용에 관한 법률 시행령 제84조
  - 용적률 범위: 국토의 계획 및 이용에 관한 법률 시행령 제85조
  - 서울 조례 용적률: 서울특별시 도시계획조례 제54조(건폐율)·제55조(용적률)
  (실제 적용 용적률은 지구단위계획·인센티브·구역별 세부로 달라질 수 있어 far_override 로 직접 지정 가능)

산출식(스펙 고정):
  buildable_gfa_m2   = site_area_m2 × far_applied           (지상 연면적, 지하주차장 제외)
  residential_gfa_m2 = buildable_gfa_m2 × mix.residential
  neighborhood_gfa_m2= buildable_gfa_m2 × mix.neighborhood
  units_est          = floor(residential_gfa_m2 × efficiency / avg_supply_m2)

  far_applied 우선순위:
    1) far_override 가 주어지면 그 값(조례 세부·인센티브 반영). 시행령 상한 초과 시 경고만.
    2) use_seoul=True(기본) → 서울 조례 대표값(far_seoul)
    3) use_seoul=False       → 시행령 상한(far_legal_max)
"""

import math


# --------------------------------------------------------------------------- #
# 용도지역 상수 테이블 (단일 출처 — 위 docstring 의 출처 참조)
# 값은 모두 소수: bcr=건폐율, far_legal_min/max=시행령 용적률 범위, far_seoul=서울 조례.
# --------------------------------------------------------------------------- #
ZONES = {
    "R1": {"name": "제1종일반주거지역", "bcr_legal": 0.60, "far_legal_min": 1.0, "far_legal_max": 2.0,  "far_seoul": 1.5},
    "R2": {"name": "제2종일반주거지역", "bcr_legal": 0.60, "far_legal_min": 1.0, "far_legal_max": 2.5,  "far_seoul": 2.0},
    "R3": {"name": "제3종일반주거지역", "bcr_legal": 0.50, "far_legal_min": 1.0, "far_legal_max": 3.0,  "far_seoul": 2.5},
    "RS": {"name": "준주거지역",        "bcr_legal": 0.70, "far_legal_min": 2.0, "far_legal_max": 5.0,  "far_seoul": 4.0},
    "CG": {"name": "일반상업지역",      "bcr_legal": 0.80, "far_legal_min": 2.0, "far_legal_max": 13.0, "far_seoul": 8.0},
    "IS": {"name": "준공업지역",        "bcr_legal": 0.70, "far_legal_min": 1.5, "far_legal_max": 4.0,  "far_seoul": 4.0},
}

# 기본 가정값
DEFAULT_AVG_SUPPLY_M2 = 84.9   # 평균 공급면적(전용 59~84 혼합의 표준적 대표값)
DEFAULT_EFFICIENCY = 0.75      # 전용률 아님 — 지상 연면적 중 공급면적 합 비율 근사

# 정적 assumptions 문구 (JS 이식본과 문자열 완전 일치 → 패리티 보장)
_ASSUME_GFA_BASIS = "용적률은 지상 연면적 기준 — 지하주차장·지하층은 연면적에서 제외(근사)."
_ASSUME_UNITS = (
    "세대수 추정 = 주거 지상연면적 × efficiency ÷ 평균 공급면적(내림). "
    "efficiency 는 전용률이 아니라 지상연면적 중 공급면적 합 비율 근사 가정."
)
_ASSUME_FAR_OVERRIDE = "적용 용적률 = far_override(사용자 지정: 조례 세부·인센티브 반영)."
_ASSUME_FAR_SEOUL = "적용 용적률 = 서울특별시 도시계획조례 대표값(구역·지구별 세부 상이 가능)."
_ASSUME_FAR_LEGAL = "적용 용적률 = 국토계획법 시행령 상한값(지자체 조례로 하향 가능)."
_ASSUME_OVERRIDE_EXCEEDS = (
    "경고: far_override 가 해당 용도지역 시행령 상한을 초과 — "
    "인센티브(공공기여·특별계획구역 등) 전제 여부 확인 필요."
)


def derive(site_area_m2, zone_code, options=None):
    """용도지역·대지면적으로부터 용적률→지상연면적→세대수를 산출.

    Args:
      site_area_m2: 대지면적(㎡)
      zone_code: ZONES 의 키(R1/R2/R3/RS/CG/IS). 미지원 시 ValueError.
      options: 없으면 기본값. 지원 키:
        far_override: None | float — 적용 용적률 직접 지정(조례 세부·인센티브)
        use_seoul: True(기본, 서울 조례값) | False(시행령 상한)
        mix: {"residential": r, "neighborhood": n} (기본 주거 100%)
        avg_supply_m2: 세대수 추정용 평균 공급면적(기본 84.9)
        efficiency: 지상연면적 중 공급면적 비율 근사(기본 0.75)

    Returns:
      {zone_name, bcr_legal, far_legal_max, far_applied, buildable_gfa_m2,
       residential_gfa_m2, neighborhood_gfa_m2, units_est(int), assumptions[str]}
    """
    if zone_code not in ZONES:
        raise ValueError(
            f"미지원 용도지역 코드: {zone_code!r} (지원: {', '.join(sorted(ZONES))})"
        )
    z = ZONES[zone_code]
    opts = options or {}

    far_override = opts.get("far_override", None)
    use_seoul = opts.get("use_seoul", True)
    mix = opts.get("mix") or {}
    res_ratio = mix.get("residential", 1.0)
    nbh_ratio = mix.get("neighborhood", 0.0)
    if res_ratio + nbh_ratio > 1 + 1e-9:
        raise ValueError("용도 혼합비 합(residential+neighborhood)이 1을 초과")
    avg_supply_m2 = opts.get("avg_supply_m2", DEFAULT_AVG_SUPPLY_M2)
    efficiency = opts.get("efficiency", DEFAULT_EFFICIENCY)

    far_legal_max = z["far_legal_max"]

    assumptions = []
    if far_override is not None:
        far_applied = far_override
        assumptions.append(_ASSUME_FAR_OVERRIDE)
        if far_override > far_legal_max:
            assumptions.append(_ASSUME_OVERRIDE_EXCEEDS)
    elif use_seoul:
        far_applied = z["far_seoul"]
        assumptions.append(_ASSUME_FAR_SEOUL)
    else:
        far_applied = far_legal_max
        assumptions.append(_ASSUME_FAR_LEGAL)
    assumptions.append(_ASSUME_GFA_BASIS)
    assumptions.append(_ASSUME_UNITS)

    buildable_gfa_m2 = site_area_m2 * far_applied
    residential_gfa_m2 = buildable_gfa_m2 * res_ratio
    neighborhood_gfa_m2 = buildable_gfa_m2 * nbh_ratio
    units_est = math.floor(residential_gfa_m2 * efficiency / avg_supply_m2)

    return {
        "zone_name": z["name"],
        "bcr_legal": z["bcr_legal"],
        "far_legal_max": far_legal_max,
        "far_applied": far_applied,
        "buildable_gfa_m2": buildable_gfa_m2,
        "residential_gfa_m2": residential_gfa_m2,
        "neighborhood_gfa_m2": neighborhood_gfa_m2,
        "units_est": units_est,
        "assumptions": assumptions,
    }
