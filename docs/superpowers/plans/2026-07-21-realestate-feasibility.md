# 부동산 개발 수지분석 연구 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 전국 부동산 시장 데이터를 API로 수집·분석하고, 검증된 개발사업 수지분석 모델과 함께 작품 수준의 아티팩트 웹사이트로 발표한다.

**Architecture:** 수집(collect) → 분석(analysis) → 베이크(build) 3단 파이프라인. 수지모델은 Python 코어를 TDD로 만들고 JS로 이식해 일치 테스트로 묶는다. 사이트는 site/ 소스(섹션·CSS·JS)를 build 스크립트로 단일 HTML에 조립하고 out/의 베이크 JSON을 임베드한다.

**Tech Stack:** Python 3.13 (stdlib + requests), pytest, 바닐라 JS/SVG(외부 라이브러리 금지 — 아티팩트 CSP), Chrome headless(렌더 검증).

## Global Constraints

- 아티팩트는 단일 HTML, 외부 요청 0건(폰트·CDN·fetch 금지), 라이트/다크 완전 대응
- API 오류·쿼터 초과를 침묵으로 삼키지 않는다: 모든 수집기는 (status, 사유)를 로그하고 폴백 전환을 명시적으로 기록
- 모든 금액 단위는 내부적으로 **원(KRW)**, 면적은 **㎡** (표시 시 억원·평 변환) — 단위 혼재 금지
- 수치 검증: 집계값마다 원본 대비 검증 스크립트, 수지모델은 Python↔JS 결과 일치(허용오차 1e-6)
- 커밋 메시지에 Co-Authored-By 트레일러 금지
- 사이트 데이터에는 출처·수집일 명시

---

### Task 1: 셋업 + API 키 프로브

**Files:**
- Create: `config.json` (git 제외), `src/collect/probe.py`, `src/collect/common.py`

**Interfaces:**
- Produces: `common.load_config() -> dict` (service_key, ecos_key, kosis_key), `common.api_get(url, params, timeout=15) -> (status_code, text)` — 재시도 1회, 오류 시 예외 아닌 상태 반환

- [ ] config.json 생성: `~/.g2b/config.json`의 service_key 복사, ecos_key/kosis_key는 빈 값
- [ ] probe.py: 아래 4개 엔드포인트에 실제 호출을 날려 결과 코드(정상/NOT_REGISTERED/기타)를 표로 출력
  - 실거래가: `https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade` (LAWD_CD=11680, DEAL_YMD=202606)
  - 건축인허가(건축HUB): `https://apis.data.go.kr/1613000/ArchPmsHubService/getApBasisOulnInfo`
  - HUG 분양가: data.go.kr에서 "민간아파트 분양가격" 서비스 URL 확인 후 호출
  - 주택인허가통계: 국토부 통계 서비스 확인 후 호출
- [ ] 프로브 결과를 `docs/api-status.md`에 기록(어떤 키·활용신청이 필요한지 사용자 안내 겸용)
- [ ] 커밋: `feat: 프로젝트 셋업 + API 키 프로브`

### Task 2: 수지분석 모델 코어 (Python, TDD)

**Files:**
- Create: `src/analysis/feasibility.py`, Test: `tests/test_feasibility.py`

**Interfaces:**
- Produces: `run_feasibility(inputs: dict) -> dict` — 입력·출력 스키마는 아래 고정. 이후 JS 이식·사이트가 이 스키마에 의존한다.

입력 스키마(단위: 원, ㎡, 연이율은 소수):
```python
inputs = {
  "revenue": {"units": [{"name":"84A","count":100,"supply_m2":112.4,"price_per_m2":9_500_000}],
               "sell_through": 0.95, "other_income": 0},
  "cost": {"land": {"purchase": 30_000_000_000, "acq_tax_rate": 0.046, "misc_rate": 0.01},
            "construction": {"gfa_m2": 15_000, "unit_cost_per_m2": 2_600_000},
            "indirect_rate": 0.06,       # 공사비 대비 (설계·감리·인허가부담금)
            "marketing_rate": 0.035,     # 분양수입 대비
            "contingency_rate": 0.01},   # 직접비 합 대비
  "finance": {"equity": 10_000_000_000, "bridge": {"amount": 20_000_000_000, "rate": 0.085, "months": 8},
               "pf": {"amount": 60_000_000_000, "rate": 0.065, "months": 24, "drawdown": 0.55},
               "fee_rate": 0.015},
  "schedule": {"months_total": 30}
}
```
출력: `{"revenue_total", "cost": {...항목별}, "cost_total", "profit", "margin_on_revenue", "margin_on_cost", "roe", "cashflow_quarterly": [...], "npv": {...}, "irr_annual"}`

- [ ] 실패 테스트 작성: 수기로 계산한 소형 사례(세대 2·단순 수치)의 총수입·총지출·이익 기대값 assert
- [ ] 테스트 실패 확인 (`pytest tests/test_feasibility.py -v`)
- [ ] 최소 구현: 수입부·지출부(토지비=매입+취득세+부대, 공사비, 간접비, 판매비=수입×요율, 금융비=브릿지 amount×rate×months/12 + PF amount×drawdown×rate×months/12 + fee, 예비비) → 이익·마진·ROE
- [ ] 분기 현금흐름 생성(토지비 t0, 공사비 S-curve 균등 근사, 분양수입은 계약금10%·중도금60% 균등·잔금30% 준공월) → NPV(할인율 입력, 기본 연8%)·IRR(이분법, 해 없으면 None)
- [ ] 경계 테스트: 분양률 0, 금융비 0, IRR 해 없음 케이스
- [ ] 전체 통과 확인 후 커밋: `feat: 수지분석 모델 코어 + 테스트`

### Task 3: 수집기 (소스별 병렬 가능)

**Files:**
- Create: `src/collect/rtms.py`(실거래가), `src/collect/rone.py`(부동산원 통계), `src/collect/ecos.py`(금리), `src/collect/permits.py`(인허가), `src/collect/presale.py`(분양가), `src/collect/cci.py`(공사비지수)
- 공통: 원본 응답을 `data/raw/<source>/`에 저장(캐시, 재실행 시 스킵), 파싱 결과는 `data/<source>.json`

**Interfaces:**
- Produces: 각 모듈 `collect() -> {"ok": bool, "rows": int, "fallback": str|None, "path": str}`
- 시도 17개 코드표는 `common.SIDO`(KOSIS/행안부 코드) 단일 출처

- [ ] rtms: 시도별 대표 시군구 1~2개(서울 강남·노원, 경기 수원팔달·화성 등 17시도 커버) × 최근 36개월 매매 실거래 수집 → 월별 중위 ㎡당가·거래량 집계. 응답 필드: dealAmount(만원, 콤마)·excluUseAr·dealYear/Month·aptNm — 만원→원 변환 검증 필수
- [ ] rone 또는 KOSIS: 시도별 아파트 매매가격지수·미분양주택수 월별 시계열(최근 10년). R-ONE 키 없으면 KOSIS API, 그것도 없으면 공표 파일 폴백을 코드로 명시
- [ ] ecos: 기준금리·주택담보대출금리 시계열 (키 발급 후)
- [ ] permits: 시도별 주택 인허가·착공·준공 물량 연/월별
- [ ] presale: 시도별 ㎡당 분양가격 시계열 (HUG)
- [ ] cci: 건설공사비지수 월별 (KOSIS 통계표)
- [ ] 각 수집기마다: 수집 직후 검증(행수>0, 단위 범위 체크, 결측 로그) + `docs/api-status.md` 갱신 + 개별 커밋

### Task 4: 시장 분석 + 사례 파라미터

**Files:**
- Create: `src/analysis/market.py`, `src/analysis/cases.py`, Test: `tests/test_market.py`

**Interfaces:**
- Produces: `market.build() -> out/market.json` (시도별: 매매지수 시계열, 미분양, 인허가, 분양가, 실거래 중위가; 전국: 금리, 공사비지수, 마진스퀴즈 = 분양가상승률-공사비상승률), `cases.build() -> out/cases.json` (표준 사례 3건의 수지모델 입력·출력 전체)

- [ ] market.py: 수집 JSON → 시도별 표준화 시계열(결측은 null 유지, 보간 금지), 사이클 국면 판정(지수 YoY × 미분양 증감 2축 사분면)
- [ ] cases.py: 사례 3건 입력값을 실데이터에서 산출(분양가=해당 시도 최근 분양가, 공사비=공사비지수 반영 평당가, 금리=최근 PF 관행 스프레드+기준금리) → run_feasibility 실행 결과 포함
- [ ] 집계 검증 테스트(표본 수치 원본 대조) 후 커밋

### Task 5: JS 이식 + 일치 검증

**Files:**
- Create: `site/js/feasibility.js`, `tests/test_parity.py`

**Interfaces:**
- Produces: `window.Feasibility.run(inputs) -> outputs` — Task 2와 동일 스키마

- [ ] feasibility.js: Python 코어를 1:1 이식 (동일 함수 구조)
- [ ] test_parity.py: 무작위 입력 50조를 Python과 node(또는 JXA/osascript JS 엔진, node 없으면 `plutil`? → **node 없으면 Chrome headless로 실행**)로 각각 실행해 전 출력 필드 |Δ|<1e-6 assert
- [ ] 통과 후 커밋

### Task 6: 사이트 구현 (디자인 시스템 → 섹션 → 인터랙션)

**Files:**
- Create: `site/index.template.html`, `site/css/*.css`, `site/js/{charts.js,calc-ui.js,app.js}`, `src/build/assemble.py`

**Interfaces:**
- Consumes: `out/market.json`, `out/cases.json`, `site/js/feasibility.js`
- Produces: `out/site.html` (단일 파일, `{{DATA_MARKET}}` 등 플레이스홀더 치환 조립)

- [ ] **artifact-design·dataviz 스킬 로드 후** 디자인 토큰 확정(색·타이포 스케일·간격, 도면 그리드 모티프, 라이트/다크 듀얼)
- [ ] 섹션 순서: 서장 히어로(카운터 애니메이션) → Ⅰ시장(시도 스몰멀티플+국면 맵) → Ⅱ구조(수지 워터폴 해부) → Ⅲ계산기(프리셋 3종·슬라이더·시나리오 A/B·실시간 워터폴·IRR 게이지) → Ⅳ민감도(토네이도·2변수 히트맵) → Ⅴ사례 3건 → Ⅵ방법론(출처·기준일·가정·한계)
- [ ] charts.js: 라인·스몰멀티플·워터폴·토네이도·히트맵·게이지를 인라인 SVG로 자작(dataviz 팔레트)
- [ ] calc-ui.js: 입력↔Feasibility.run 바인딩, requestAnimationFrame 디바운스, A/B 시나리오 스냅샷
- [ ] assemble.py: 조립+데이터 임베드, 결과물 크기 로그
- [ ] Chrome headless 스크린샷(라이트/다크×데스크톱/모바일)으로 렌더 실측 → 디자인 자체 리뷰 체크리스트(타이포 위계·간격 리듬·대비·차트 가독성) 통과까지 반복
- [ ] 커밋(디자인 시스템/섹션별 분할 커밋)

### Task 7: 검수 + 배포

- [ ] codex 교차 리뷰 1회(`codex exec ... < /dev/null`) — 모델 수식·JS 이식·데이터 임베드 검증
- [ ] 계산기 실동작 시나리오 테스트(Chrome headless에서 입력 변경→출력 변화 assert)
- [ ] Artifact 배포(favicon 지정, 제목 고정) → 사용자 확인
- [ ] 메모리·체크포인트 기록

## Self-Review 결과

- 스펙 §4 전 소스가 Task 1·3에, §5 모델이 Task 2·5에, §6 콘텐츠가 Task 4에, §7 사이트가 Task 6에, §8 품질이 Task 5·6·7에 매핑됨 — 누락 없음
- 수지모델 입력·출력 스키마를 Task 2에 고정해 Task 4·5·6이 동일 참조 — 시그니처 일관
- API 가용성은 Task 1 프로브로 확정 후 Task 3 폴백 경로가 흡수 — 플레이스홀더성 불확실성은 프로브+폴백 구조로 명시 처리

---

## 확장 태스크 (2026-07-21 사용자 지시: 정비사업·상권·컨설팅)

### Task 8: 정비사업 모델 확장 (재개발·재건축·리모델링)

**Files:** Modify `src/analysis/feasibility.py`, `site/js/feasibility.js`, Test: `tests/test_redevelopment.py`, `tests/test_parity.py`(케이스 추가)

**Interfaces:** `run_feasibility(inputs)` — `inputs["mode"] ∈ {"신축분양"(기본), "재개발", "재건축", "리모델링"}`.
정비사업 추가 입력: `"redevelopment": {"prior_asset_value"(종전자산평가액), "member_count", "member_price_per_m2"(조합원분양가), "member_supply_m2", "general_units"[...신축과 동일 구조], "relocation_loan"{amount,rate,months}(이주비), "demolition_cost", "rental_ratio"(재개발 임대의무, 수입 제외 비율), "cash_settlement_ratio"}`
추가 출력: `"proportion_rate"(비례율), "member_contribution"(세대당 분담금), "rights_value"(권리가액)`

- [ ] 실패 테스트: 수기 검산 재건축 소형 사례(비례율·분담금 기대값) → 구현 → 통과
- [ ] 리모델링: general_units 소량+분담금 중심 케이스 테스트
- [ ] JS 이식 동기화 + 패리티 케이스 20조 추가(mode 혼합) → 통과 → 커밋

### Task 9: 상권 데이터 수집·분석

**Files:** Create `src/collect/sbiz.py`, Modify `src/analysis/market.py`

- [ ] 소상공인시장진흥공단 상가(상권)정보 API(활용신청 후) — 시도별 업소수·업종 대분류 구성 집계 (전수 좌표 수집은 과도 — 집계 API/표본 사용, 쿼터 존중)
- [ ] out/market.json에 `commerce` 블록 추가: 시도별 업종 구성·인구·주거 대비 밀도
- [ ] 검증(합계 대조)·커밋

### Task 6 갱신: 사이트 IA는 스펙 §7 개정판(Ⅰ~Ⅷ장, 계산기 4모드·상권·컨설팅 챕터)을 따른다

컨설팅 챕터 콘텐츠(정적): 정비사업 절차(정비구역지정→조합설립→사업시행인가→관리처분→이주·철거→착공·분양→준공·이전고시), 단계별 핵심 리스크(비례율 하락·공사비 증액·분양경기·인허가 지연·조합 갈등), 시장 국면×사업유형 전략 매트릭스(확장기/둔화기/침체기/회복기 × 4유형)

### Task 10: 토지·용도지역 모듈 (2026-07-21 추가 지시)

**Files:** Create `src/analysis/zoning.py`, `site/js/zoning.js`, Test: `tests/test_zoning.py`

**Interfaces:**
- `zoning.derive(site_area_m2, zone_code, mix) -> {"bcr_legal", "far_legal", "far_seoul", "buildable_gfa_m2", "units_est", "nonres_gfa_m2"}`
- 용도지역 테이블(단일 출처, 법령 명시): 국토계획법 시행령 §84·§85 상한 + 서울시 도시계획조례 대표값
  - 1종일반주거(건폐 60/용적 100~200, 서울 150) · 2종일반주거(60/100~250, 서울 200) · 3종일반주거(50/100~300, 서울 250)
  - 준주거(70/200~500, 서울 400) · 일반상업(80/200~1300, 서울 800) · 준공업(70/150~400, 서울 400)
- mix: {"residential": 0.9, "neighborhood": 0.1} — 근생 혼합 비율, 근생 분양가는 별도 단가 입력

- [ ] 용도지역 테이블 + derive() TDD (연면적 = 대지 × 용적률, 지상 기준 근사; 세대수 = 주거 연면적 × 전용률 근사 / 평균 전용면적 — 가정 명시)
- [ ] 계산기 UI: "① 토지" 스텝 추가 — 대지면적·용도지역·근생비율 입력 → 연면적·세대수 자동 산출(수동 오버라이드 가능) → 수지 입력에 주입
- [ ] 근생 분양수입: units에 "근생" 타입으로 합류 (단가 별도, 상권 챕터와 상호 링크)
- [ ] 사이트 Ⅱ장(구조)에 "대지에서 연면적까지" 단계 시각화(대지→법정한도→매스→세대) 추가
- [ ] JS 이식 + 패리티 케이스 추가, 법령 출처 각주
- [ ] (선택·키) 토지 실거래가 API "토지 매매 신고 자료" 활용신청 시 시도별 토지 ㎡당가 참고 계열 수집

### Task 11: 예측 모델링 벤치마크 (2026-07-21 추가 지시 — 라이브러리 생태계·딥러닝)

**Files:** Create `venv/`(전용, git 제외), `requirements.txt`, `src/forecast/{features.py,models.py,backtest.py,build.py}`, Test: `tests/test_backtest.py`
**Interfaces:** `build.py` → `out/forecast.json`: 시도별 매매가격지수 12개월 예측(중앙값+80% 구간) + 모델 벤치마크 표

- [ ] 전용 venv 구성: numpy·pandas·scikit-learn·statsmodels·lightgbm·torch(MPS)·chronos-forecasting(HuggingFace)
- [ ] 대상: 시도별 아파트 매매가격지수(120개월) — 보조 피처: 미분양·인허가·금리·공사비지수·분양가
- [ ] 모델 벤치마크(동일 홀드아웃): ①naive/계절naive ②SARIMA(statsmodels) ③LightGBM(라그·외생 피처)
      ④PyTorch LSTM(시도 풀링 학습) ⑤HuggingFace Chronos-Bolt 제로샷 — 롤링 오리진 백테스트, MAE·sMAPE
- [ ] 소데이터 한계 명시(120개월×17): 홀드아웃 12개월 고정, 구간 예측은 분위수
- [ ] out/forecast.json 베이크 + 사이트 챕터 "예측" (팬차트+모델 비교표+방법론 각주)
- [ ] 검증: 백테스트 지표 재현 테스트, 커밋
