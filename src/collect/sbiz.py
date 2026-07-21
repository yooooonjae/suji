"""소상공인시장진흥공단 상가(상권)정보 수집기: 시도×업종 업소수 매트릭스 + 주요상권현황.

실행: python3 src/collect/sbiz.py
산출: data/sbiz.json
  {"upjong_large": [{"code","name"}...],
   "counts": {"서울": {"음식": 138558, ...}, ...},           # 시도 × 업종대분류 업소수
   "counts_mid": {"서울": {"음식": {"한식": ..., ...}}, ...}, # 서울·경기·부산만(업종중분류)
   "zones": {"by_sido": {"서울": 176, ...}, "list": [{"name","sido","sigungu","center":[lon,lat]}...]},
   "collected_at": "...", "source": "소상공인시장진흥공단 상가(상권)정보"}

엔드포인트(프로브 실측, base=.../B553077/api/open/sdsc2):
  - largeUpjongList / middleUpjongList : 업종 대·중분류 코드목록(indsLclsCd/indsMclsCd)
  - storeListInDong : divId=ctprvnCd, key=<시도코드>, [indsLclsCd|indsMclsCd] 필터
                      → body.totalCount 로 업소수 취득 (numOfRows=1)
  시도코드는 행정표준 2자리(common.SIDO)를 쓰되 개편 신코드만 인식:
  강원 42→51, 전북 45→52 (구코드는 NODATA).
"""

import csv
import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collect.common import ROOT, SIDO, api_get, load_config  # noqa: E402

BASE = "https://apis.data.go.kr/B553077/api/open/sdsc2"
RAW_DIR = ROOT / "data" / "raw" / "sbiz"
PAUSE = 0.25
MID_SIDO = ["서울", "경기", "부산"]  # 중분류까지 확장할 시도

CSV_PATH = (ROOT / "자료" / "_extracted" / "sbiz"
            / "소상공인시장진흥공단_주요상권현황_20240101.csv")

# storeListInDong 가 인식하는 시도코드: common.SIDO 기준, 개편 신코드로 보정
SIDO_API_CODE = {name: code for code, name in SIDO.items()}
SIDO_API_CODE["강원"] = "51"  # 강원특별자치도 (구 42 → NODATA)
SIDO_API_CODE["전북"] = "52"  # 전북특별자치도 (구 45 → NODATA)

# CSV 시도명(정식) → common.SIDO 축약명
SIDO_FULLNAME = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
    "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종",
    "경기도": "경기", "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북",
    "전라남도": "전남", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주",
    "강원특별자치도": "강원",
}


def _get(endpoint: str, params: dict) -> dict:
    """sdsc2 호출 → 파싱된 dict. 게이트웨이 5xx는 백오프 재시도, 그 외 오류는 예외."""
    p = {"serviceKey": load_config()["service_key"], "type": "json"}
    p.update(params)
    status, text = -1, ""
    for attempt in range(5):
        status, text = api_get(f"{BASE}/{endpoint}", p)
        # 간헐 502 Bad Gateway(13분 지점 실측)·네트워크 단절(-1)은 백오프 후 재시도
        if (500 <= status < 600 or status == -1) and attempt < 4:
            time.sleep(2 ** attempt)
            continue
        break
    if status != 200:
        raise RuntimeError(f"sbiz HTTP {status} {endpoint} {params}: {text[:150]}")
    data = json.loads(text)
    time.sleep(PAUSE)
    return data


def fetch_upjong(endpoint: str, params: dict, code_key: str, name_key: str):
    """업종 코드목록(대/중분류). 목록 엔드포인트는 numOfRows 무시하고 전량 반환."""
    data = _get(endpoint, {**params, "numOfRows": "1000", "pageNo": "1"})
    rc = data.get("header", {}).get("resultCode")
    if rc == "03":  # NODATA — 해당 대분류에 중분류 없음
        return []
    if rc not in ("00", "000"):
        raise RuntimeError(f"{endpoint} {params} 응답오류: {data.get('header')}")
    items = data.get("body", {}).get("items") or []
    return [{"code": it[code_key], "name": it[name_key]} for it in items]


def count(sido_api: str, upjong_param: str, upjong_code: str) -> tuple:
    """storeListInDong totalCount. (count, resultCode) 반환. NODATA→0."""
    params = {"divId": "ctprvnCd", "key": sido_api, "numOfRows": "1", "pageNo": "1"}
    if upjong_param:
        params[upjong_param] = upjong_code
    data = _get("storeListInDong", params)
    rc = data.get("header", {}).get("resultCode")
    if rc == "03":  # NODATA_ERROR — 업소 0건
        return 0, rc
    if rc not in ("00", "000"):
        raise RuntimeError(f"count 응답오류 sido={sido_api} {upjong_param}={upjong_code}: {data.get('header')}")
    total = data.get("body", {}).get("totalCount")
    return int(total), rc


def load_zones() -> dict:
    """주요상권현황 CSV → by_sido 개수 + 상권 리스트(중심좌표=폴리곤 평균)."""
    csv.field_size_limit(sys.maxsize)  # 폴리곤 필드가 131072 초과
    by_sido, zlist = {}, []
    with open(CSV_PATH, encoding="cp949") as f:
        r = csv.reader(f)
        next(r)  # 헤더
        for row in r:
            zone_name, ztype = row[1], row[2]
            sido_full, sigungu = row[4], row[6]
            poly = row[8]
            sido = SIDO_FULLNAME.get(sido_full)
            if sido is None:
                raise RuntimeError(f"미매핑 시도명: {sido_full!r}")
            # 폴리곤 "lon,lat|lon,lat|..." → 중심(단순평균)
            # 멀티폴리곤은 링을 ")|(" 로 구분 — 토큰의 괄호를 벗겨 전 링 평균
            lons, lats = [], []
            for pt in poly.split("|"):
                if "," not in pt:
                    continue
                lon, lat = pt.strip("()").split(",")[:2]
                lons.append(float(lon))
                lats.append(float(lat))
            center = [round(sum(lons) / len(lons), 6), round(sum(lats) / len(lats), 6)] if lons else None
            by_sido[sido] = by_sido.get(sido, 0) + 1
            zlist.append({"name": zone_name, "type": ztype.strip(),
                          "sido": sido, "sigungu": sigungu, "center": center})
    return {"by_sido": by_sido, "list": zlist}


def collect() -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # 1) 업종 대분류
    large = fetch_upjong("largeUpjongList", {}, "indsLclsCd", "indsLclsNm")
    (RAW_DIR / "large.json").write_text(json.dumps(large, ensure_ascii=False))
    print(f"  업종 대분류 {len(large)}개")

    # 2) 시도 × 대분류 업소수 — 시도 단위 캐시로 중단 지점부터 재개(쿼터 절약)
    matrix_path = RAW_DIR / "counts_matrix.json"
    raw_matrix = json.loads(matrix_path.read_text()) if matrix_path.exists() else {}
    counts = {}
    code2name = {u["code"]: u["name"] for u in large}
    for sido_name in SIDO.values():
        api_code = SIDO_API_CODE[sido_name]
        cached = raw_matrix.get(sido_name)
        if cached and set(cached) == set(code2name):
            counts[sido_name] = {code2name[c]: v["count"] for c, v in cached.items()}
            print(f"  {sido_name}(코드{api_code}): 총 {sum(counts[sido_name].values()):,} [캐시]", flush=True)
            continue
        row, raw_row = {}, {}
        for up in large:
            c, rc = count(api_code, "indsLclsCd", up["code"])
            row[up["name"]] = c
            raw_row[up["code"]] = {"count": c, "rc": rc}
        counts[sido_name] = row
        raw_matrix[sido_name] = raw_row
        matrix_path.write_text(json.dumps(raw_matrix, ensure_ascii=False))
        print(f"  {sido_name}(코드{api_code}): 총 {sum(row.values()):,}", flush=True)

    # 3) 서울·경기·부산 × 업종 중분류 — 시도 단위 캐시로 재개
    mid_path = RAW_DIR / "counts_mid.json"
    counts_mid = json.loads(mid_path.read_text()) if mid_path.exists() else {}
    mid_lists = {}  # 대분류코드 → [{code,name}]
    for sido_name in MID_SIDO:
        if sido_name in counts_mid:
            print(f"  [중분류] {sido_name}: 캐시 재사용", flush=True)
            continue
        api_code = SIDO_API_CODE[sido_name]
        smid = {}
        for up in large:
            if counts[sido_name].get(up["name"], 0) == 0:
                continue  # 해당 시도에 업소 0인 대분류는 중분류 조회 생략(쿼터절약)
            if up["code"] not in mid_lists:
                mid_lists[up["code"]] = fetch_upjong(
                    "middleUpjongList", {"indsLclsCd": up["code"]}, "indsMclsCd", "indsMclsNm")
            block = {}
            for mid in mid_lists[up["code"]]:
                c, _ = count(api_code, "indsMclsCd", mid["code"])
                block[mid["name"]] = c
            if block:
                smid[up["name"]] = block
                print(f"    {sido_name}/{up['name']}: {len(block)}개 중분류, 합 {sum(block.values()):,}", flush=True)
        counts_mid[sido_name] = smid
        mid_path.write_text(json.dumps(counts_mid, ensure_ascii=False))
        print(f"  [중분류] {sido_name}: {sum(len(v) for v in smid.values())}개 중분류 집계", flush=True)

    # 4) 주요상권현황
    zones = load_zones()
    print(f"  주요상권 {len(zones['list'])}개, 시도 {len(zones['by_sido'])}곳")

    # 검증
    assert len(counts) == 17, f"시도 {len(counts)}개 (17 아님)"
    low = {s: sum(v.values()) for s, v in counts.items() if sum(v.values()) <= 10_000}
    assert not low, f"시도 총합 10,000 미달(코드매핑 의심): {low}"
    assert len(zones["list"]) == 1227, f"상권 {len(zones['list'])}개 (1227 아님)"

    result = {
        "upjong_large": large,
        "counts": counts,
        "counts_mid": counts_mid,
        "zones": zones,
        "collected_at": datetime.date.today().isoformat(),
        "source": "소상공인시장진흥공단 상가(상권)정보",
    }
    path = ROOT / "data" / "sbiz.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return {"ok": True, "sido": len(counts), "upjong": len(large),
            "zones": len(zones["list"]), "path": str(path)}


if __name__ == "__main__":
    print("상가(상권)정보 수집:")
    print(collect())
