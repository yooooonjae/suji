"""API 키 프로브: 어떤 서비스가 현재 키로 열리는지 실측한다.

실행: python3 src/collect/probe.py
결과 해석 (data.go.kr 공통 오류):
  - resultCode 00/000 + item        → 정상 (활용신청 완료 상태)
  - SERVICE_KEY_IS_NOT_REGISTERED   → 키는 유효하나 이 API에 활용신청 안 됨
  - SERVICE ACCESS DENIED / 30      → 활용신청 필요
  - HTTP 404                        → 엔드포인트 URL 재확인 필요
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collect.common import api_get, load_config  # noqa: E402

PROBES = [
    ("아파트 매매 실거래가 (RTMS)",
     "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade",
     {"LAWD_CD": "11680", "DEAL_YMD": "202606", "numOfRows": "3", "pageNo": "1"}),
    ("아파트 분양권 실거래가 (RTMS)",
     "https://apis.data.go.kr/1613000/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade",
     {"LAWD_CD": "11680", "DEAL_YMD": "202606", "numOfRows": "3", "pageNo": "1"}),
    ("건축HUB 건축인허가 기본개요",
     "https://apis.data.go.kr/1613000/ArchPmsHubService/getApBasisOulnInfo",
     {"sigunguCd": "11680", "bjdongCd": "10300", "numOfRows": "3", "pageNo": "1"}),
    ("HUG 민간아파트 분양가격(월별 평균분양가격)",
     "https://apis.data.go.kr/B551982/psale/rtn_avg_ps",
     {"page": "1", "perPage": "3"}),
]


def classify(status: int, text: str) -> str:
    t = text[:400]
    if status == -1:
        return f"네트워크 오류: {t[:120]}"
    if status == 404:
        return "404 — 엔드포인트 URL 재확인 필요"
    if re.search(r"NOT_REGISTERED|ACCESS.?DENIED|등록되지 않은", t, re.I):
        return "키는 접수됐으나 이 API 활용신청 필요"
    if re.search(r"<resultCode>0+0?</resultCode>|\"resultCode\"\s*:\s*\"?0+", t) or "<item>" in t or '"currentCount"' in t:
        return "정상 ✓"
    if re.search(r"LIMITED|EXCEED", t, re.I):
        return "쿼터 초과"
    return f"기타 응답 (앞부분): {t[:150]!r}"


def main():
    key = load_config()["service_key"]
    print(f"{'서비스':<34} 결과")
    print("-" * 78)
    results = []
    for name, url, params in PROBES:
        p = dict(params)
        p["serviceKey"] = key
        status, text = api_get(url, p)
        verdict = classify(status, text)
        results.append((name, status, verdict))
        print(f"{name:<34} [{status}] {verdict}")
    return results


if __name__ == "__main__":
    main()
