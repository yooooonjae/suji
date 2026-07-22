# 수지(收支) — 대한민국 부동산 개발의 손익 구조

개인 연구 포트폴리오. 전국 부동산 시장 데이터를 공공 API로 수집·검증하고, 실무 구조의
개발사업 수지분석 모델(신축분양·재건축·재개발·리모델링·수익형)과 6모델 예측 벤치마크,
탐색적 데이터 분석(EDA)을 하나의 인터랙티브 정적 사이트로 발표한다.

## 질문

- 토지의 용적률과 조합의 비례율은 개발사업의 손익을 어떻게 결정하는가?
- 분양가·공사비·금리·사업기간 중 무엇이 사업성을 가장 크게 흔드는가(민감도)?
- 지역마다 다른 시장 국면을, 검증된 모델로 얼마나 예측할 수 있는가?

## 라이브

- **사이트**: https://yoonjae.pages.dev (링크트리 경유)
- **30초 사업성 검토**: Ⅲ장 수지 계산기 — 입력 즉시 재계산, [투자심의표 인쇄]로 A4 1~2쪽 요약 출력
- 검색 노출은 기본 차단(noindex). 모든 데이터가 로컬 내장이라 페이지는 외부 요청이 없다.

## 출처

7개 기관 · 14종 공공 데이터셋. 원천별 최신 **관측월**·**수집일**·건수는 빌드 시
`src/build/manifest.py`가 `data/` 에서 자동 산출해 `DATA_MANIFEST.json`으로 기록하고,
방법론 장 「데이터 상태」 표에 렌더한다(손입력 없음).

| 기관 | 데이터셋 |
|---|---|
| 한국부동산원 R-ONE | 주택가격동향(매매·전세·분양가)·상업용 임대동향 |
| 국토교통부 RTMS | 아파트 매매·분양권·서울 25구 전수·상업업무·오피스텔·토지 실거래 |
| 통계청 KOSIS·KICT | 미분양·인허가·착공·준공·건설공사비지수 |
| 국토교통부 건축HUB | 공동주택 인허가 세대 |
| 한국은행 ECOS | 기준금리·대출금리 |
| 주택도시보증공사 HUG | 민간아파트 분양가격 |
| 소상공인시장진흥공단 | 상가업소 상권정보 |

## 방법론

- **검증 우선**: 수지모델은 수기검산과 대조하고, 웹 계산기는 Python 코어와 무작위 입력
  패리티(|Δ|<1e-6)로 묶는다. 패리티만으론 둘 다 틀린 경우를 못 잡으므로, 외부 검증한
  **절대값 골든 사례**(개발이익률·NOI÷cap 자본환원·IRR/NPV)를 Python·JS 양쪽에 못박는다.
- **정직한 고지**: 상관≠인과, 소표본 한계, 결측 처리 방식을 방법론 장에 명시한다.
- **오류 삼킴 금지**: 수집 실패는 status·알림으로 드러내고, 직전 정상 산출물을 보존한다.

## 설치

```bash
make setup            # 가상환경(venv) + requirements.txt
cp .env.example .env  # 선택(경로 변수)
# API 키는 config.json에 넣는다:
cp config.example.json config.json 2>/dev/null || true  # 키 이름 확인용 — 실제 값은 config.json 에 채운다
```

`config.json`(API 키)은 커밋되지 않는다. 키 이름은 `.env.example` 참조,
공공데이터포털·ECOS·KOSIS·R-ONE·HUG·브이월드에서 무료 발급.

## 빌드

```bash
make collect   # 공공 API 원천 수집 → data/*.json   (키 필요)
make analyze   # 분석 산출물 → out/*.json
make build     # 사이트 조립 → web/  (DATA_MANIFEST·빌드 스탬프 포함)
make refresh   # 위 전 과정 오케스트레이션 (수집→분석→빌드→검증)
make serve     # http://localhost:8765
```

빌드 산출물 푸터에 `Commit <해시> · Data cutoff <관측월> · Built <빌드일>` 스탬프가 박힌다.

## 테스트

```bash
make test      # 176 단위테스트 (수기검산·골든 절대값·Python↔JS 패리티)
```

## 구조

```
src/collect/    8종 수집기 — R-ONE·KOSIS·ECOS·HUG·RTMS(매매·분양권)·상가상권 (원본 캐시·검증 assert)
src/analysis/   시장 통합(market)·표준 사례(cases)·수지/토지 모델·EDA(eda)
src/forecast/   6모델 벤치마크 — Naive·계절 Naive·SARIMA·LightGBM·LSTM·Chronos-Bolt (롤링 백테스트)
src/build/      manifest(데이터 원장) + assemble(사이트 조립) — site/ 소스 + out/·data/ JSON → web/
src/pipeline/   월간 자동 갱신(refresh) — launchd com.suji.refresh
site/           사이트 소스 — 9장 에디토리얼, 수지 계산기 4모드, 차트 라이브러리(외부 의존 0), 인쇄 심의표
tests/          176 단위테스트
```

## 한계

- 산출은 초기 검토용 추정이며 감정평가·회계·세무·법률 자문을 대체하지 않는다(세전 모델).
- 실거래 표본은 시도별 대표 시군구·㎡당 200만원 이상 중위값이라 지방 시도는 상향 편향 가능.
- 예측구간(80%)은 모델 불확실성의 하한이다 — 정책·금리 충격 같은 구조 변화는 담지 못한다.

## 라이선스

포트폴리오 열람 목적 공개. 사전 서면 동의 없는 복제·수정·재배포·상업적 이용을 허락하지 않는다.
자세한 내용은 [LICENSE](LICENSE).

## 자매 프로젝트

부동산 연구 시리즈 — 收支 수지(개별 사업의 손익) · [循環 순환](https://sunhwan.pages.dev)(시장과 자본의 구조) · [時差 시차](https://sicha.pages.dev)(신호의 전달시간).
