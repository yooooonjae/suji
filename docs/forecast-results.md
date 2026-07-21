# 부동산 매매가격지수 예측 벤치마크 결과

- 타깃: **아파트 매매가격지수(2026.01=100)** — R-ONE 아파트 매매가격지수, 전국+17시도 18계열, 201607~202606 월별 120개월
- 백테스트: 롤링 오리진 [96, 102, 108] 개월 시점에서 각 12개월 예측(오리진 108=최종 12개월)
- 지표: MAE·sMAPE(%) — 예측 median vs 실측, 오리진 3회 평균 후 계열 집계
- 생성: `2026-07-21T09:36:44` · Chronos: amazon/chronos-bolt-small 로드 성공

## 벤치마크 — 시도 평균(전국 제외 17개)

| 순위 | 모델 | MAE | sMAPE(%) |
|---|---|---|---|
| 1 | SARIMA | 0.6800 | 0.6916 |
| 2 | Chronos-Bolt-small | 0.9217 | 0.9325 |
| 3 | naive | 1.0876 | 1.0986 |
| 4 | LightGBM | 1.6144 | 1.6215 |
| 5 | seasonal_naive | 1.8692 | 1.8785 |
| 6 | LSTM(풀링) | 3.0462 | 2.9622 |

## 벤치마크 — 전국 (별도)

| 모델 | MAE | sMAPE(%) |
|---|---|---|
| SARIMA | 0.4821 | 0.4871 |
| Chronos-Bolt-small | 0.4964 | 0.4998 |
| seasonal_naive | 0.6722 | 0.6784 |
| naive | 0.7326 | 0.7398 |
| LightGBM | 0.7710 | 0.7790 |
| LSTM(풀링) | 3.4945 | 3.4326 |

## 최우수 모델

**SARIMA** — 시도평균 MAE 0.6800/sMAPE 0.6916%, 전국 MAE 0.4821로 두 집계 모두 최소. 지수 수준(75~135)에서 sMAPE 1% 미만. **Chronos-Bolt-small 제로샷**이 학습 없이 근소한 2위(시도평균 MAE 0.9217)로 강력한 폴백. 소표본(계열당 ~100개월)에서 고전 계절 ARIMA·시계열 파운데이션 모델이 풀링 LSTM(최하위)을 앞선다 — 딥러닝은 표본 부족으로 naive 대비 열세.

## 소표본 한계

소표본 한계: 시도별 월별 120개월(201607~202606) 단일 표본, 롤링 오리진 3회(오리진 96/102/108개월)로만 검증했다. 지수(가격 자체 아님) 수준 예측이며, 외생 피처는 라그(1/3/6/12)만 사용해 동시점 정보를 쓰지 않는다(누출 방지). 분위수는 근사(정규 근사·잔차 스프레드·모델 자체 분위수 혼재)이므로 구간은 참고용이다. 구조 변화(금리·정책 급변) 구간에서는 오차가 크게 확대될 수 있다.


## 재현

```bash
python3.13 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python -m pytest tests/test_backtest.py -q   # 하네스 검증
venv/bin/python -m src.forecast.build                 # out/forecast.json 재생성
```
- 시드 42 고정(torch·numpy·lightgbm) — LightGBM·LSTM 재실행 동일 결과 확인.
- macOS arm64: torch 의 OpenMP 를 LightGBM 보다 먼저 로드해야 세그폴트 회피(models.py 에서 torch 선점 임포트).
