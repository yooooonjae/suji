"""디지털트윈국토(VWorld) 대상지 조회 체인 — 대상지·법규 탭의 원료.

실행: python3 src/collect/vworld.py
산출: data/sites.json — 등록된 대상지들의 {좌표, 용도지역, PNU, 지번, 공시지가}

체인: 지오코더(주소→좌표) → 용도지역도(LT_C_UQ111, 점 포함 폴리곤)
     → 연속지적도(LP_PA_CBND_BUBUN, PNU·지번) → 개별공시지가(NED, PNU)
주의: 도로명 지오코딩 점이 실제 대상 필지와 다른 필지에 떨어질 수 있다 —
     결과에 지번을 함께 저장해 사람이 대조하게 한다(자동 신뢰 금지).
"""

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 조회 대상지 (리포트·사례) — 도로명 or 지번 주소
SITES = [
    {"id": "signature", "name": "시그니쳐타워 (리포트 №2)",
     "address": "서울특별시 중구 청계천로 100", "type": "road"},
    {"id": "hannam3", "name": "한남3구역 (리포트 №3 후보)",
     "address": "서울특별시 용산구 한남동 686", "type": "parcel"},
]


def _get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params, safe="%(),:|")
    req = urllib.request.Request(f"{url}?{qs}", headers={"User-Agent": "suji/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def lookup(key: str, address: str, addr_type: str = "road") -> dict:
    out = {"address": address}
    g = _get("https://api.vworld.kr/req/address", {
        "service": "address", "request": "getcoord", "version": "2.0",
        "crs": "EPSG:4326", "address": address, "refine": "true",
        "format": "json", "type": addr_type, "key": key})
    pt = g.get("response", {}).get("result", {}).get("point", {})
    if not pt:
        out["error"] = "지오코딩 실패"
        return out
    x, y = pt["x"], pt["y"]
    out["lon"], out["lat"] = float(x), float(y)
    time.sleep(0.2)

    z = _get("https://api.vworld.kr/req/data", {
        "service": "data", "request": "GetFeature", "data": "LT_C_UQ111",
        "key": key, "geomFilter": f"POINT({x} {y})", "size": "5",
        "format": "json", "geometry": "false", "crs": "EPSG:4326"})
    feats = z.get("response", {}).get("result", {}).get("featureCollection", {}).get("features", [])
    out["zones"] = sorted({f.get("properties", {}).get("uname", "") for f in feats} - {""})
    time.sleep(0.2)

    p = _get("https://api.vworld.kr/req/data", {
        "service": "data", "request": "GetFeature", "data": "LP_PA_CBND_BUBUN",
        "key": key, "geomFilter": f"POINT({x} {y})", "size": "2",
        "format": "json", "geometry": "false", "crs": "EPSG:4326"})
    pf = p.get("response", {}).get("result", {}).get("featureCollection", {}).get("features", [])
    props = pf[0].get("properties", {}) if pf else {}
    out["pnu"], out["jibun"] = props.get("pnu"), props.get("addr") or props.get("jibun")
    time.sleep(0.2)

    if out.get("pnu"):
        try:
            l = _get("https://api.vworld.kr/ned/data/getIndvdLandPriceAttr", {
                "key": key, "pnu": out["pnu"], "stdrYear": "2025",
                "format": "json", "numOfRows": "3", "pageNo": "1"})
            rows = (l.get("indvdLandPrices") or {}).get("field") or []
            if rows:
                r0 = rows[0]
                out["land_price_won_m2"] = int(r0.get("pblntfPclnd", 0) or 0)
                out["land_price_year"] = r0.get("stdrYear")
        except Exception as e:
            out["land_price_error"] = str(e)[:80]
    return out


def main():
    key = json.load(open(ROOT / "config.json"))["vworld_key"]
    results = {}
    for s in SITES:
        r = lookup(key, s["address"], s.get("type", "road"))
        r["name"] = s["name"]
        results[s["id"]] = r
        pp = r.get("land_price_won_m2")
        print(f"  {s['name']}: {r.get('zones')} · {r.get('jibun')} · "
              f"공시지가 {pp:,}원/㎡ ({r.get('land_price_year')})" if pp else f"  {s['name']}: {r}")
    (ROOT / "data" / "sites.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장: data/sites.json")


if __name__ == "__main__":
    main()
