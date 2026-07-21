"""한국은행 ECOS 수집기: 기준금리(일별→월말), 예금은행 대출금리(월별).

실행: python3 src/collect/ecos.py
산출: data/ecos.json
  {"base_rate": [{"ym": "201607", "value": 1.25}, ...],          # 월말 기준
   "mortgage_rate": [...], "corp_loan_rate": [...],              # 신규취급액 가중평균
   "collected_at": "...", "source": "한국은행 ECOS"}
"""

import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collect.common import ROOT, api_get, load_config  # noqa: E402

RAW_DIR = ROOT / "data" / "raw" / "ecos"

SERIES = [
    # (키, 통계코드, 주기, 항목코드, 설명)
    ("base_rate", "722Y001", "D", "0101000", "한국은행 기준금리"),
    ("mortgage_rate", "121Y006", "M", "BECBLA0302", "예금은행 주택담보대출 금리(신규)"),
    ("corp_loan_rate", "121Y006", "M", "BECBLA02", "예금은행 기업대출 금리(신규)"),
]

YEARS = 12  # 수집 기간


def _fetch(key: str, stat: str, cycle: str, item: str):
    today = datetime.date.today()
    if cycle == "D":
        start = (today.replace(year=today.year - YEARS)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")
    else:
        start = f"{today.year - YEARS}{today.month:02d}"
        end = today.strftime("%Y%m")
    rows, page, per = [], 1, 1000
    while True:
        s = (page - 1) * per + 1
        e = page * per
        url = (f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/"
               f"{s}/{e}/{stat}/{cycle}/{start}/{end}/{item}")
        status, text = api_get(url, {})
        if status != 200:
            raise RuntimeError(f"ECOS HTTP {status}: {text[:200]}")
        data = json.loads(text)
        if "RESULT" in data:  # INFO-200 등 — 데이터 없음/오류를 명시적으로 드러낸다
            raise RuntimeError(f"ECOS 응답 오류 {stat}/{cycle}/{item}: {data['RESULT']}")
        body = data["StatisticSearch"]
        rows.extend(body["row"])
        if len(rows) >= int(body["list_total_count"]):
            break
        page += 1
    return rows


def _to_monthly_last(daily_rows):
    """일별 계열 → 각 월의 마지막 관측값."""
    by_month = {}
    for r in sorted(daily_rows, key=lambda x: x["TIME"]):
        ym = r["TIME"][:6]
        by_month[ym] = float(r["DATA_VALUE"])
    return [{"ym": ym, "value": v} for ym, v in sorted(by_month.items())]


def collect() -> dict:
    key = load_config()["ecos_key"]
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, stat, cycle, item, desc in SERIES:
        rows = _fetch(key, stat, cycle, item)
        (RAW_DIR / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False))
        if cycle == "D":
            series = _to_monthly_last(rows)
        else:
            series = [{"ym": r["TIME"], "value": float(r["DATA_VALUE"])}
                      for r in sorted(rows, key=lambda x: x["TIME"])]
        # 검증: 행수·값 범위(금리 0~20%)
        assert len(series) >= YEARS * 10, f"{name}: 행수 부족 {len(series)}"
        bad = [p for p in series if not (0.0 <= p["value"] <= 20.0)]
        assert not bad, f"{name}: 범위 밖 값 {bad[:3]}"
        out[name] = series
        print(f"  {name:<14} {len(series):>4}개월  최신 {series[-1]['ym']}={series[-1]['value']}% ({desc})")
    result = {**out,
              "collected_at": datetime.date.today().isoformat(),
              "source": "한국은행 경제통계시스템(ECOS)"}
    path = ROOT / "data" / "ecos.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return {"ok": True, "rows": sum(len(v) for v in out.values()), "fallback": None, "path": str(path)}


if __name__ == "__main__":
    print("ECOS 수집:")
    print(collect())
