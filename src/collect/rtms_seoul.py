"""서울 25개 구 전체 아파트 매매 실거래 — 구별 ㎡당 분위수 (data/rtms_seoul.json).

배경(2026-07-21 사용자 지적): 시도 표본(강남구+노원구 혼합)의 서울 중위는
강남3구와 외곽의 격차를 뭉갠다. 25개 구 전수를 수집해 구별 분포로 분해한다.

실행: python3 src/collect/rtms_seoul.py
rtms.py 인프라(캐시·백오프·유효범위 필터)를 그대로 재사용 — 강남구·노원구는
기존 캐시 적중, 나머지 23개 구만 신규 호출(약 830콜 × 36개월 페이지네이션).
"""

import datetime
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.collect.common import load_config          # noqa: E402
from src.collect import rtms as R                   # noqa: E402

SEOUL_GU = [
    ("종로구", "11110"), ("중구", "11140"), ("용산구", "11170"), ("성동구", "11200"),
    ("광진구", "11215"), ("동대문구", "11230"), ("중랑구", "11260"), ("성북구", "11290"),
    ("강북구", "11305"), ("도봉구", "11320"), ("노원구", "11350"), ("은평구", "11380"),
    ("서대문구", "11410"), ("마포구", "11440"), ("양천구", "11470"), ("강서구", "11500"),
    ("구로구", "11530"), ("금천구", "11545"), ("영등포구", "11560"), ("동작구", "11590"),
    ("관악구", "11620"), ("서초구", "11650"), ("강남구", "11680"), ("송파구", "11710"),
    ("강동구", "11740"),
]
GANGNAM3 = {"강남구", "서초구", "송파구"}


def main():
    key = load_config()["service_key"]
    months = R._months(R.SALE_MONTHS)
    out, excluded = {}, 0
    for gu, code in SEOUL_GU:
        vals, n_raw = [], 0
        for ym in months:
            items = R._fetch_month("sale", R.SALE_URL, code, ym, key)
            n_raw += len(items)
            for it in items:
                v, reason = R._price_per_m2(it)
                if v is None:
                    excluded += 1
                else:
                    vals.append(v)
        vals.sort()
        if len(vals) >= 30:
            q = lambda p: vals[min(len(vals) - 1, int(p * len(vals)))]
            out[gu] = {"n": len(vals), "n_raw": n_raw,
                       "p10": round(q(.10)), "p25": round(q(.25)),
                       "median": round(statistics.median(vals)),
                       "p75": round(q(.75)), "p90": round(q(.90))}
        else:  # 표본 부족은 숨기지 않고 사유 기록
            out[gu] = {"n": len(vals), "n_raw": n_raw, "note": "유효 표본 부족(<30)"}
        print(f"  {gu}: 유효 {len(vals):,}건 · 중위 "
              f"{out[gu].get('median', 0) / 1e4:,.0f}만원/㎡" if "median" in out[gu]
              else f"  {gu}: 유효 {len(vals)}건 — 표본 부족", flush=True)

    # 검증 — 25개 구 전수·물리 범위·강남3구 존재
    assert len(out) == 25, f"구 수 {len(out)} != 25"
    meds = {g: v["median"] for g, v in out.items() if "median" in v}
    assert all(2_000_000 <= m <= 50_000_000 for m in meds.values()), "㎡당가 범위 위반"
    assert all(g in meds for g in GANGNAM3), "강남3구 표본 부족"

    g3 = statistics.mean(meds[g] for g in GANGNAM3)
    rest = statistics.mean(v for g, v in meds.items() if g not in GANGNAM3)
    res = {
        "by_gu": out,
        "gangnam3_median_avg": round(g3), "non_gangnam3_median_avg": round(rest),
        "months": f"{months[0]}~{months[-1]}",
        "note": "구별 전수(법정 시군구코드) · ㎡당가 = dealAmount/excluUseAr · "
                "rtms.py와 동일 유효범위(200만~5,000만원/㎡) 필터 · 제외 " + f"{excluded:,}건",
        "collected_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": "국토교통부 RTMS 아파트 매매 신고",
    }
    (R.ROOT / "data" / "rtms_seoul.json").write_text(json.dumps(res, ensure_ascii=False))
    print(f"저장: data/rtms_seoul.json · 강남3구 평균중위 {g3/1e4:,.0f}만 vs "
          f"비강남 {rest/1e4:,.0f}만 (배율 {g3/rest:.2f}×)")


if __name__ == "__main__":
    main()
