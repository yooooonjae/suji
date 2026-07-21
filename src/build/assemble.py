"""사이트 조립: site/ 소스 + out/·data/ JSON → 단일 HTML (out/site.html).

플레이스홀더:
  {{CSS:파일명}}  → site/css/파일명 내용 인라인
  {{JS:파일명}}   → site/js/파일명 내용 인라인
  {{DATA_MARKET}} {{DATA_CASES}} {{DATA_FORECAST}} {{DATA_SBIZ}} → JSON 임베드
  {{BUILT_AT}}   → 조립일

실행: python3 src/build/assemble.py
"""

import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
OUT = ROOT / "out"

DATA_MAP = {
    "DATA_MARKET": OUT / "market.json",
    "DATA_CASES": OUT / "cases.json",
    "DATA_FORECAST": OUT / "forecast.json",
    "DATA_SBIZ": ROOT / "data" / "sbiz.json",
}


def _minify_json(path: Path) -> str:
    obj = json.loads(path.read_text())
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def assemble() -> Path:
    tpl = (SITE / "index.template.html").read_text()

    def sub(m):
        kind, name = m.group(1), m.group(2)
        if kind == "CSS":
            return (SITE / "css" / name).read_text()
        if kind == "JS":
            return (SITE / "js" / name).read_text()
        raise KeyError(m.group(0))

    html = re.sub(r"\{\{(CSS|JS):([\w.\-]+)\}\}", sub, tpl)

    for key, path in DATA_MAP.items():
        token = "{{" + key + "}}"
        if token in html:
            if not path.exists():
                raise FileNotFoundError(f"{key}: {path} 없음 — 파이프라인 선행 실행 필요")
            html = html.replace(token, _minify_json(path))

    html = html.replace("{{BUILT_AT}}", datetime.date.today().isoformat())

    leftover = re.findall(r"\{\{[A-Z_]+\}\}", html)
    if leftover:
        raise RuntimeError(f"미치환 플레이스홀더: {leftover}")

    OUT.mkdir(exist_ok=True)
    out_path = OUT / "site.html"
    out_path.write_text(html)
    size = out_path.stat().st_size
    print(f"조립 완료: {out_path} ({size/1024:.0f} KB)")
    if size > 4_500_000:
        print("경고: 4.5MB 초과 — 데이터 다이어트 필요")
    return out_path


if __name__ == "__main__":
    assemble()
