"""사이트 빌드 — 멀티파일 dist (web/) 생성 + (옵션) 단일 HTML.

기본: web/ 에 index.html + css/ + js/ + data/(JS 래핑 JSON) 산출 → 로컬호스트 서빙용.
옵션: --single 시 기존 방식의 단일 out/site.html 도 생성.

실행: python3 src/build/assemble.py [--single]
"""

import datetime
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
OUT = ROOT / "out"
WEB = ROOT / "web"

DATA_MAP = {
    "DATA_MARKET": ("market", OUT / "market.json"),
    "DATA_CASES": ("cases", OUT / "cases.json"),
    "DATA_FORECAST": ("forecast", OUT / "forecast.json"),
    "DATA_SBIZ": ("sbiz", ROOT / "data" / "sbiz.json"),
    "DATA_EDA": ("eda", OUT / "eda.json"),
    "DATA_COMMERCIAL": ("commercial", ROOT / "data" / "rone_commercial.json"),
    "DATA_ARCHUB": ("archub", ROOT / "data" / "archub.json"),
    "DATA_SEOULGU": ("seoulgu", ROOT / "data" / "rtms_seoul.json"),
    "DATA_RTMSCOM": ("rtmscom", ROOT / "data" / "rtms_commercial.json"),
    "DATA_REPORT": ("report", OUT / "report_wirye.json"),
    "DATA_REPORT2": ("report2", OUT / "report_signature.json"),
    "DATA_SITES": ("sites", ROOT / "data" / "sites.json"),
    "DATA_REPORT3": ("report3", OUT / "report_hannam.json"),
}
CSS_FILES = ["tokens.css", "base.css", "components.css", "flourish.css"]
JS_FILES = ["guard.js", "feasibility.js", "zoning.js", "charts.js", "calc-ui.js", "app.js"]
STATIC = SITE / "static"  # robots.txt, og.png 등 → web/ 루트로 복사


def _minify_json(path: Path) -> str:
    obj = json.loads(path.read_text())
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    # <script> 내 삽입 안전화 (JSON 유니코드 이스케이프 — 문법 동등)
    return (s.replace("<", "\\u003c").replace(">", "\\u003e")
             .replace("&", "\\u0026")
             .replace(" ", "\\u2028").replace(" ", "\\u2029"))


def _robots_tag() -> str:
    """검색 노출 정책. 기본=차단(noindex). --index 플래그 시 개방(링크드인 등록용).
    월간 자동 갱신은 플래그 없이 실행되므로 항상 차단 상태로 유지된다."""
    if "--index" in sys.argv:
        return '<meta name="robots" content="index, follow">'
    return '<meta name="robots" content="noindex, nofollow, noarchive">'


def build_dist() -> Path:
    """web/ 멀티파일 산출 — index.html은 링크 참조, 데이터는 JS 래핑."""
    tpl = (SITE / "index.template.html").read_text()

    # CSS/JS 인라인 플레이스홀더 → 링크/스크립트 태그
    css_links = "\n".join(f'<link rel="stylesheet" href="css/{f}">' for f in CSS_FILES)
    tpl = re.sub(r"<style>\s*(?:\{\{CSS:[\w.\-]+\}\}\s*)+</style>", css_links, tpl)

    data_tags = "\n".join(f'<script src="data/{name}.js"></script>' for name, _ in DATA_MAP.values())
    js_tags = "\n".join(f'<script src="js/{f}"></script>' for f in JS_FILES)
    tpl = re.sub(r"<script>\s*window\.__DATA_MARKET[\s\S]*?</script>", data_tags, tpl)
    tpl = re.sub(r"<script>\s*(?:\{\{JS:[\w.\-]+\}\}\s*)+</script>", js_tags, tpl)
    tpl = tpl.replace("{{BUILT_AT}}", datetime.date.today().isoformat())
    tpl = tpl.replace("{{ROBOTS}}", _robots_tag())


    # 조사 분리 검사 — 강조 태그 닫힘과 조사 사이 공백/개행은 실화면 띄어쓰기가 된다 (5차 리뷰 채택)
    import re as _re
    _bad = _re.findall(r"</(?:b|strong|em|i)>[ \t]*\n[ \t]*(?:이|가|을|를|은|는|의|와|과|로|다|이다|한다|된다)[ .,<]", tpl)
    if _bad:
        raise RuntimeError(f"조사 분리 의심 {len(_bad)}건 — 태그와 조사를 붙이거나 조사를 태그 안으로: {_bad[:3]}")
    leftover = re.findall(r"\{\{[A-Z_:.\w\-]+\}\}", tpl)
    if leftover:
        raise RuntimeError(f"미치환 플레이스홀더: {leftover}")

    # 배치 — 임시 디렉토리에 전부 빌드 후 원자적 스왑
    # (terser 등 후속 단계가 실패해도 기존 web/은 손대지 않는다 — codex 적대검증 치명 지적)
    TMP = ROOT / "web.tmp"
    if TMP.exists():
        shutil.rmtree(TMP)
    (TMP / "css").mkdir(parents=True)
    (TMP / "js").mkdir()
    (TMP / "data").mkdir()
    WEB = TMP  # 이하 산출은 전부 임시 디렉토리로
    doc = "<!DOCTYPE html>\n<html lang=\"ko\">\n<head>\n" + \
          re.search(r'^([\s\S]*?)(?=<div id="progress")', tpl).group(1).strip() + \
          "\n</head>\n<body>\n" + tpl[tpl.index('<div id="progress"'):] + "\n</body>\n</html>\n"
    (WEB / "index.html").write_text(doc)
    protect = "--no-protect" not in sys.argv
    for f in CSS_FILES:
        src = (SITE / "css" / f).read_text()
        if protect:  # 간이 CSS 최소화 (주석·불필요 공백 제거)
            src = re.sub(r"/\*[\s\S]*?\*/", "", src)
            src = re.sub(r"\s*([{}:;,>])\s*", r"\1", src)
            src = re.sub(r";}", "}", src)
        (WEB / "css" / f).write_text(src)
    for f in JS_FILES:
        dst = WEB / "js" / f
        if protect:  # terser 압축·난독 (실패 시 명시적 중단 — 침묵 폴백 금지)
            import subprocess
            r = subprocess.run(["npx", "--yes", "terser", str(SITE / "js" / f),
                                "-c", "-m", "--comments", "false"],
                               capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                raise RuntimeError(f"terser 실패 {f}: {r.stderr[:200]}")
            dst.write_text(r.stdout)
        else:
            shutil.copy(SITE / "js" / f, dst)
    if STATIC.exists():
        for f in STATIC.iterdir():
            shutil.copy(f, WEB / f.name)
    for key, (name, path) in DATA_MAP.items():
        if not path.exists():
            raise FileNotFoundError(f"{name}: {path} 없음")
        (WEB / "data" / f"{name}.js").write_text(
            f"window.__{key} = {_minify_json(path)};\n")
    # 전 단계 성공 — 이제서야 기존 web/ 교체 (원자적 스왑)
    FINAL = ROOT / "web"
    if FINAL.exists():
        shutil.rmtree(FINAL)
    TMP.rename(FINAL)
    WEB = FINAL
    total = sum(p.stat().st_size for p in WEB.rglob("*") if p.is_file())
    print(f"dist 빌드: {WEB} ({total/1024:.0f} KB, {len(list(WEB.rglob('*')))}개 파일)")
    return WEB


def build_single() -> Path:
    """기존 단일 HTML (out/site.html) — 아카이브·오프라인 공유용."""
    tpl = (SITE / "index.template.html").read_text()

    def sub(m):
        kind, name = m.group(1), m.group(2)
        if kind == "CSS":
            return (SITE / "css" / name).read_text()
        if kind == "JS":
            return (SITE / "js" / name).read_text()
        raise KeyError(m.group(0))

    html = re.sub(r"\{\{(CSS|JS):([\w.\-]+)\}\}", sub, tpl)
    for key, (name, path) in DATA_MAP.items():
        html = html.replace("{{" + key + "}}", _minify_json(path))
    html = html.replace("{{BUILT_AT}}", datetime.date.today().isoformat())
    html = html.replace("{{ROBOTS}}", _robots_tag())
    OUT.mkdir(exist_ok=True)
    out_path = OUT / "site.html"
    out_path.write_text(html)
    print(f"단일 빌드: {out_path} ({out_path.stat().st_size/1024:.0f} KB)")
    return out_path


if __name__ == "__main__":
    build_dist()
    if "--single" in sys.argv:
        build_single()
