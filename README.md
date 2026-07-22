# 수지(收支) — 대한민국 부동산 개발의 손익 구조

개인 연구 포트폴리오. 전국 부동산 시장 데이터를 공공 API로 수집하고, 실무 구조의
개발사업 수지분석 모델(신축분양·재건축·재개발·리모델링·수익형)과 6모델 예측 벤치마크,
탐색적 데이터 분석(EDA)을 하나의 인터랙티브 정적 사이트로 발표한다.

## 구성

```
src/collect/    8종 수집기 — R-ONE·KOSIS·ECOS·HUG·RTMS(매매·분양권)·상가상권 (원본 캐시·검증 assert)
src/analysis/   시장 통합(market)·표준 사례(cases)·수지/토지 모델 검증셋·EDA(eda)
src/forecast/   6모델 벤치마크 — Naive·계절 Naive·SARIMA·LightGBM·LSTM·Chronos-Bolt (롤링 백테스트)
src/build/      사이트 조립(assemble) — site/ 소스 + out/·data/ JSON → web/ 정적 산출
src/pipeline/   월간 자동 갱신(refresh) — launchd com.suji.refresh, 매월 28일 07:30
site/           사이트 소스 — 8챕터 에디토리얼, 수지 계산기 4모드, 차트 라이브러리(외부 의존 0)
tests/          176 단위테스트 — 수지모델 수기검산 대조, 골든(절대값 기준정답), Python↔JS 패리티(|Δ|<1e-6)
```

## 실행

```bash
python3 src/pipeline/refresh.py --skip-collect   # 분석→빌드 (수집 생략)
python3 src/pipeline/refresh.py                  # 전체 갱신 (config.json에 API 키 필요)
python3 src/analysis/eda.py                      # EDA 재현
./serve.sh                                       # http://localhost:8765 (봇필터·보안헤더)
python3 -m pytest tests/ -q                      # 모델 검증
```

`config.json`(API 키)은 커밋되지 않는다 — 공공데이터포털·ECOS·KOSIS·R-ONE·HUG에서 발급.

## 원칙

- **오류 삼킴 금지**: 수집 실패는 status·알림으로 드러내고, 직전 정상 산출물을 보존한다.
- **검증 우선**: 수지모델은 수기검산과 대조하고, 웹 계산기는 Python 코어와 무작위 입력
  패리티 테스트로 묶는다. 패리티(둘이 같음)만으론 둘 다 틀린 경우를 못 잡으므로,
  외부 검증한 **절대값 골든 사례**(개발이익률·NOI÷cap 자본환원·IRR/NPV — 표는
  `tests/test_golden.py` 상단)를 Python·JS 양쪽에 못박는다. 모든 수치는 재현 스크립트로 재산출 가능하다.
- **정직한 고지**: 상관≠인과, 소표본 한계, 결측 처리 방식을 사이트 방법론 장에 명시한다.
