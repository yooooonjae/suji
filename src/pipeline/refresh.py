"""월간 자동 갱신 파이프라인 — 수집 → 분석 → (분기: 예측) → 빌드 → 검증.

실행:
  python3 src/pipeline/refresh.py                 # 전체 (예측은 1·4·7·10월에만)
  python3 src/pipeline/refresh.py --skip-collect  # 분석·빌드만
  python3 src/pipeline/refresh.py --only ecos     # 특정 수집기만 + 분석·빌드
  python3 src/pipeline/refresh.py --with-forecast # 예측 강제 포함 (--no-forecast 반대)

원칙 (G2B 운영 교훈):
- 소스별 독립: 한 수집기가 실패해도 나머지는 진행. 실패한 소스는 기존 data/*.json이
  유지되어 사이트는 직전 데이터로 빌드된다 — 대신 status·알림으로 실패를 반드시 드러낸다
  (조용한 최신 위장 금지).
- 분석·빌드 실패는 전체 실패로 종료: web/ 덮어쓰기 전에 멈추므로 직전 정상 사이트가 남는다.
- 기록: logs/refresh-YYYYMMDD-HHMM.log(전체 출력) + logs/refresh-status.json(기계 판독).
- 알림: 성공/실패 모두 macOS 알림(월 1회 주기라 소음 아님). launchd: com.suji.refresh.
"""

import datetime
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "logs"
PY = sys.executable or "python3"
VENV_PY = ROOT / "venv" / "bin" / "python"

# (이름, 스크립트, 타임아웃초) — 원본 캐시(data/raw/) 덕에 재실행은 대부분 증분
COLLECTORS = [
    ("ecos",     "src/collect/ecos.py",     900),
    ("rone",     "src/collect/rone.py",     1800),
    ("rone_sub", "src/collect/rone_sub.py", 3600),
    ("kosis",    "src/collect/kosis.py",    1800),
    ("presale",  "src/collect/presale.py",  900),
    ("sbiz",     "src/collect/sbiz.py",     3600),
    ("rtms",     "src/collect/rtms.py",     5400),
]
ANALYSIS = [
    ("market", [PY, "src/analysis/market.py"], 600),
    ("cases",  [PY, "-m", "src.analysis.cases"], 600),  # 패키지 import라 -m 필수
    ("eda",    [PY, "src/analysis/eda.py"],    600),
]
FORECAST_MONTHS = {1, 4, 7, 10}  # 분기 재학습 (백테스트 포함이라 수십 분)


def notify(title: str, msg: str):
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{msg}" with title "{title}"'],
                       capture_output=True, timeout=10)
    except Exception:
        pass  # 알림 실패가 파이프라인을 죽이면 안 됨


def run_step(name: str, cmd: list, timeout: int, log) -> dict:
    t0 = datetime.datetime.now()
    log.write(f"\n===== {name} — {t0:%H:%M:%S} =====\n$ {' '.join(map(str, cmd))}\n")
    log.flush()
    try:
        r = subprocess.run(cmd, cwd=ROOT, timeout=timeout,
                           stdout=log, stderr=subprocess.STDOUT)
        ok = r.returncode == 0
        detail = f"exit={r.returncode}"
    except subprocess.TimeoutExpired:
        ok, detail = False, f"timeout>{timeout}s"
    except Exception as e:  # 실행 자체 실패도 기록
        ok, detail = False, f"error: {e}"
    dur = (datetime.datetime.now() - t0).total_seconds()
    log.write(f"----- {name}: {'OK' if ok else 'FAIL'} ({detail}, {dur:.0f}s)\n")
    log.flush()
    return {"ok": ok, "detail": detail, "seconds": round(dur)}


def validate() -> list:
    """빌드 산출물 신선도·무결성. 실패 사유 리스트 반환(비면 통과)."""
    probs = []
    today = datetime.date.today()
    idx = ROOT / "web" / "index.html"
    if not idx.exists() or idx.stat().st_size < 20_000:
        probs.append("web/index.html 없음 또는 비정상 크기")
    elif datetime.date.fromtimestamp(idx.stat().st_mtime) != today:
        probs.append("web/index.html이 오늘 빌드되지 않음")
    for f in ["out/market.json", "out/cases.json", "out/forecast.json", "out/eda.json"]:
        p = ROOT / f
        try:
            json.loads(p.read_text())
        except Exception as e:
            probs.append(f"{f} 파싱 실패: {e}")
    return probs


def main():
    args = sys.argv[1:]
    only = args[args.index("--only") + 1] if "--only" in args else None
    skip_collect = "--skip-collect" in args
    now = datetime.datetime.now()
    do_forecast = ("--with-forecast" in args or now.month in FORECAST_MONTHS) \
        and "--no-forecast" not in args

    LOGS.mkdir(exist_ok=True)
    log_path = LOGS / f"refresh-{now:%Y%m%d-%H%M}.log"
    status = {"started": now.isoformat(timespec="seconds"), "stages": {}, "failures": []}

    with open(log_path, "w") as log:
        # 1) 수집 — 소스별 독립
        if not skip_collect:
            for name, script, to in COLLECTORS:
                if only and name != only:
                    continue
                res = run_step(f"collect:{name}", [PY, script], to, log)
                status["stages"][f"collect:{name}"] = res
                if not res["ok"]:
                    status["failures"].append(f"collect:{name} ({res['detail']}) — 직전 데이터로 빌드됨")
        # 2) 분석 — 실패 시 전체 중단 (직전 web/ 보존)
        aborted = False
        for name, cmd, to in ANALYSIS:
            res = run_step(f"analysis:{name}", cmd, to, log)
            status["stages"][f"analysis:{name}"] = res
            if not res["ok"]:
                status["failures"].append(f"analysis:{name} ({res['detail']}) — 빌드 중단, 직전 사이트 유지")
                aborted = True
                break
        # 3) 예측 (분기)
        if not aborted and do_forecast:
            if VENV_PY.exists():
                res = run_step("forecast", [str(VENV_PY), "-m", "src.forecast.build"], 5400, log)
                status["stages"]["forecast"] = res
                if not res["ok"]:
                    status["failures"].append(f"forecast ({res['detail']}) — 직전 예측 유지")
            else:
                status["failures"].append("forecast: venv 없음 — 건너뜀")
        # 4) 빌드
        if not aborted:
            res = run_step("assemble", [PY, "src/build/assemble.py"], 600, log)
            status["stages"]["assemble"] = res
            if not res["ok"]:
                status["failures"].append(f"assemble ({res['detail']}) — 직전 사이트 유지")
                aborted = True
        # 5) 검증
        if not aborted:
            probs = validate()
            status["stages"]["validate"] = {"ok": not probs, "detail": "; ".join(probs) or "clean"}
            status["failures"].extend(probs)

    status["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    status["ok"] = not status["failures"]
    status["log"] = str(log_path)
    (LOGS / "refresh-status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=1))

    n_ok = sum(1 for v in status["stages"].values() if v["ok"])
    if status["ok"]:
        notify("수지 갱신 완료", f"{n_ok}단계 정상 · {now:%m월 %d일}")
    else:
        notify("수지 갱신 실패 ⚠️", f"{len(status['failures'])}건 — logs/refresh-status.json 확인")
    print(json.dumps(status, ensure_ascii=False, indent=1))
    sys.exit(0 if status["ok"] else 1)


if __name__ == "__main__":
    main()
