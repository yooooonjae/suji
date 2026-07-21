"""HUG 지역별 ㎡당 분양가격 수집기 (khug.or.kr 자체 API).

실행: python3 src/collect/presale.py
산출: data/hug.json — {"presale_price": {"서울": [{"ym","value"}...], ...}}  value = 원/㎡
원본(천원/㎡)은 data/raw/hug/ 캐시. R-ONE 분양가(T249233134451237)와 교차검증용 이중 소스.
"""

import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collect.common import ROOT, api_get, load_config  # noqa: E402

URL = "https://www.khug.or.kr/priceDistributedPrice3dot3.do"
RAW_DIR = ROOT / "data" / "raw" / "hug"

# 실측 확정 코드 (01~17, 18+ = NO_DATA)
AREA = {"01": "서울", "02": "부산", "03": "대구", "04": "인천", "05": "광주",
        "06": "대전", "07": "경기", "08": "강원", "09": "충북", "10": "충남",
        "11": "전북", "12": "전남", "13": "경북", "14": "경남", "15": "제주",
        "16": "울산", "17": "세종"}

START = "201501"


def collect() -> dict:
    key = load_config()["hug_key"]
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    end = datetime.date.today().strftime("%Y%m")
    out = {}
    for code, name in AREA.items():
        cache = RAW_DIR / f"{code}.json"
        if cache.exists():
            rows = json.loads(cache.read_text())
        else:
            status, text = api_get(URL, {"API_KEY": key, "START_YYM": START,
                                         "END_YYM": end, "AREA_DCD": code})
            if status != 200:
                raise RuntimeError(f"HUG {name} HTTP {status}: {text[:120]}")
            rows = json.loads(text)
            if isinstance(rows, dict) or not rows:
                raise RuntimeError(f"HUG {name} 응답 이상: {str(rows)[:120]}")
            cache.write_text(json.dumps(rows, ensure_ascii=False))
            time.sleep(0.2)
        series, missing = [], 0
        for r in sorted(rows, key=lambda x: x["YEAR_MM"]):
            raw = (r.get("YEAR_VAL") or "").strip()
            if not raw:  # 결측 월 — 보간 금지 규약: 스킵하고 개수만 기록
                missing += 1
                continue
            v = float(raw) * 1000.0  # 천원/㎡ → 원/㎡ (전역 단위 규약)
            # 검증: ㎡당 100만~3천만 원 범위 (서울 최고가 감안)
            assert 1_000_000 <= v <= 30_000_000, f"{name} {r['YEAR_MM']}: {v}"
            series.append({"ym": r["YEAR_MM"], "value": v})
        assert len(series) >= 90, f"{name}: 행수 부족 {len(series)}"
        if missing:
            print(f"  [결측] {name}: {missing}개월 스킵")
        out[name] = series
    result = {"presale_price": out,
              "unit": "원/㎡",
              "collected_at": datetime.date.today().isoformat(),
              "source": "주택도시보증공사(HUG) 민간아파트 분양가격 동향"}
    path = ROOT / "data" / "hug.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return {"ok": True, "rows": sum(len(v) for v in out.values()),
            "fallback": None, "path": str(path)}


if __name__ == "__main__":
    print("HUG 분양가 수집:")
    print(collect())
