"""수집 공통: 설정 로드, HTTP 호출(오류 삼킴 금지), 시도 코드표."""

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 행정표준코드(법정동 시도 2자리) — 전국 17개 시도 단일 출처
SIDO = {
    "11": "서울", "26": "부산", "27": "대구", "28": "인천", "29": "광주",
    "30": "대전", "31": "울산", "36": "세종", "41": "경기", "43": "충북",
    "44": "충남", "45": "전북", "46": "전남", "47": "경북", "48": "경남",
    "50": "제주", "42": "강원",
}


def load_config() -> dict:
    return json.load(open(ROOT / "config.json"))


def api_get(url: str, params: dict, timeout: int = 15, retries: int = 1):
    """GET 호출. (status_code, text) 반환 — 예외도 상태로 환원해 호출자가 반드시 보게 한다."""
    qs = urllib.parse.urlencode(params, safe="%")
    full = f"{url}?{qs}"
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": "dev-research/0.1"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")
        except Exception as e:  # URLError, timeout 등
            last_err = e
            if attempt < retries:
                time.sleep(1.5)
    return -1, f"NETWORK_ERROR: {last_err}"
