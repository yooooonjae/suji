/**
 * 토지·용도지역 모듈 코어 (JavaScript 이식본).
 *
 * src/analysis/zoning.py 의 1:1 이식이다. 동일 상수 테이블·동일 수식·동일 연산
 * 순서·동일 assumptions 문자열을 유지하여 Python 결과와 부동소수 수준까지 일치시킨다.
 *   - 곱셈/나눗셈 순서를 Python 과 좌→우 동일 유지
 *   - Math.floor ↔ math.floor
 *   - Python None ↔ JS null (far_override 기본 null)
 *
 * 브라우저/노드 겸용. import/export 없이 global.Zoning 에 노출한다.
 * (아티팩트 인라인 삽입을 위해 모듈 구문 금지)
 */
(function (global) {
  "use strict";

  // 용도지역 상수 테이블 (단일 출처 — zoning.py ZONES 와 값 동일)
  // 출처: 국토계획법 시행령 §84(건폐율)·§85(용적률), 서울시 도시계획조례 §54·§55
  var ZONES = {
    R1: { name: "제1종일반주거지역", bcr_legal: 0.60, far_legal_min: 1.0, far_legal_max: 2.0,  far_seoul: 1.5 },
    R2: { name: "제2종일반주거지역", bcr_legal: 0.60, far_legal_min: 1.0, far_legal_max: 2.5,  far_seoul: 2.0 },
    R3: { name: "제3종일반주거지역", bcr_legal: 0.50, far_legal_min: 1.0, far_legal_max: 3.0,  far_seoul: 2.5 },
    RS: { name: "준주거지역",        bcr_legal: 0.70, far_legal_min: 2.0, far_legal_max: 5.0,  far_seoul: 4.0 },
    CG: { name: "일반상업지역",      bcr_legal: 0.80, far_legal_min: 2.0, far_legal_max: 13.0, far_seoul: 8.0 },
    IS: { name: "준공업지역",        bcr_legal: 0.70, far_legal_min: 1.5, far_legal_max: 4.0,  far_seoul: 4.0 },
  };

  var DEFAULT_AVG_SUPPLY_M2 = 84.9;
  var DEFAULT_EFFICIENCY = 0.75;

  // 정적 assumptions 문구 (zoning.py 와 문자열 완전 일치 → 패리티 보장)
  var A_GFA_BASIS = "용적률은 지상 연면적 기준 — 지하주차장·지하층은 연면적에서 제외(근사).";
  var A_UNITS =
    "세대수 추정 = 주거 지상연면적 × efficiency ÷ 평균 공급면적(내림). " +
    "efficiency 는 전용률이 아니라 지상연면적 중 공급면적 합 비율 근사 가정.";
  var A_FAR_OVERRIDE = "적용 용적률 = far_override(사용자 지정: 조례 세부·인센티브 반영).";
  var A_FAR_SEOUL = "적용 용적률 = 서울특별시 도시계획조례 대표값(구역·지구별 세부 상이 가능).";
  var A_FAR_LEGAL = "적용 용적률 = 국토계획법 시행령 상한값(지자체 조례로 하향 가능).";
  var A_OVERRIDE_EXCEEDS =
    "경고: far_override 가 해당 용도지역 시행령 상한을 초과 — " +
    "인센티브(공공기여·특별계획구역 등) 전제 여부 확인 필요.";

  // 용도지역·대지면적 → 용적률→지상연면적→세대수. 스키마는 Python 과 동일.
  function derive(site_area_m2, zone_code, options) {
    if (!Object.prototype.hasOwnProperty.call(ZONES, zone_code)) {
      throw new Error(
        "미지원 용도지역 코드: " + JSON.stringify(zone_code) +
          " (지원: " + Object.keys(ZONES).sort().join(", ") + ")"
      );
    }
    var z = ZONES[zone_code];
    var opts = options || {};

    // far_override: 명시적으로 준 경우만 사용(null/undefined → 미지정)
    var far_override =
      opts.far_override === undefined || opts.far_override === null
        ? null
        : opts.far_override;
    var use_seoul = opts.use_seoul === undefined ? true : opts.use_seoul;
    var mix = opts.mix || {};
    var res_ratio = mix.residential === undefined ? 1.0 : mix.residential;
    var nbh_ratio = mix.neighborhood === undefined ? 0.0 : mix.neighborhood;
    if (res_ratio + nbh_ratio > 1 + 1e-9) throw new Error("용도 혼합비 합(residential+neighborhood)이 1을 초과");
    var avg_supply_m2 =
      opts.avg_supply_m2 === undefined ? DEFAULT_AVG_SUPPLY_M2 : opts.avg_supply_m2;
    var efficiency = opts.efficiency === undefined ? DEFAULT_EFFICIENCY : opts.efficiency;

    var far_legal_max = z.far_legal_max;

    var assumptions = [];
    var far_applied;
    if (far_override !== null) {
      far_applied = far_override;
      assumptions.push(A_FAR_OVERRIDE);
      if (far_override > far_legal_max) {
        assumptions.push(A_OVERRIDE_EXCEEDS);
      }
    } else if (use_seoul) {
      far_applied = z.far_seoul;
      assumptions.push(A_FAR_SEOUL);
    } else {
      far_applied = far_legal_max;
      assumptions.push(A_FAR_LEGAL);
    }
    assumptions.push(A_GFA_BASIS);
    assumptions.push(A_UNITS);

    var buildable_gfa_m2 = site_area_m2 * far_applied;
    var residential_gfa_m2 = buildable_gfa_m2 * res_ratio;
    var neighborhood_gfa_m2 = buildable_gfa_m2 * nbh_ratio;
    var units_est = Math.floor((residential_gfa_m2 * efficiency) / avg_supply_m2);

    return {
      zone_name: z.name,
      bcr_legal: z.bcr_legal,
      far_legal_max: far_legal_max,
      far_applied: far_applied,
      buildable_gfa_m2: buildable_gfa_m2,
      residential_gfa_m2: residential_gfa_m2,
      neighborhood_gfa_m2: neighborhood_gfa_m2,
      units_est: units_est,
      assumptions: assumptions,
    };
  }

  global.Zoning = {
    derive: derive,
    ZONES: ZONES,
  };
})(typeof window !== "undefined" ? window : globalThis);
