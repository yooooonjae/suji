"""5개 예측 모델 — 통일 인터페이스.

    fit_predict(train_series, exog, horizon, series_id=None, all_train=None)
        -> {"median": [...], "q10": [...], "q90": [...]}   # 각 길이 horizon

- train_series: 타깃 값 리스트(시간순, 오리진까지)
- exog: LightGBM용 라그 피처 DataFrame(train_series 와 같은 행 순서·길이, 앞 12행 NaN). 그 외 모델은 무시.
- series_id / all_train: LSTM 풀링용(시도 임베딩 · 전 시도 학습). 그 외 모델은 무시.
- Chronos 다운로드/로드 실패 시 fit_predict 가 None 을 반환(삼키지 않고 사유는 CHRONOS_STATUS 에 기록).

모델:
 ① naive(마지막값) · seasonal_naive(12개월 전)
 ② SARIMA (1,1,1)(1,0,1,12) — 수렴 실패 시 (0,1,1)
 ③ LightGBM 직접 다중스텝(horizon별 모델, 분위수 회귀 10/50/90)
 ④ PyTorch LSTM(전 시도 풀링·시도 임베딩·입력 24개월 윈도·분위수 손실 10/50/90)
 ⑤ Chronos-Bolt-small 제로샷(분위수 출력)
"""

import numpy as np

# macOS arm64 OpenMP 충돌 회피: torch 의 libomp 를 LightGBM 보다 먼저 로드해야
# 한 프로세스에서 두 모델을 함께 쓸 때 세그폴트가 나지 않는다(순서 의존 버그).
# 따라서 torch 를 모듈 임포트 시점에 선점 로드한다.
import torch as _torch  # noqa: F401
_torch.manual_seed(42)
_torch.set_num_threads(1)

SEED = 42
Z10 = 1.2815515594457831  # 표준정규 10% 분위(음수 방향은 -Z10)
QUANTILES = (0.1, 0.5, 0.9)


def _sort_quantiles(q10, med, q90):
    """분위수 교차 방지: 각 스텝에서 q10<=median<=q90 로 정렬."""
    q10, med, q90 = list(map(list, (q10, med, q90)))
    for i in range(len(med)):
        a, b, c = sorted((q10[i], med[i], q90[i]))
        q10[i], med[i], q90[i] = a, b, c
    return {"median": med, "q10": q10, "q90": q90}


# ── ① naive / seasonal_naive ────────────────────────────────────────────────
def naive(train_series, exog=None, horizon=12, series_id=None, all_train=None):
    y = np.asarray(train_series, dtype=float)
    last = float(y[-1])
    med = [last] * horizon
    diffs = np.diff(y)
    sigma = float(np.std(diffs, ddof=1)) if len(diffs) > 1 else 0.0
    band = [Z10 * sigma * np.sqrt(h) for h in range(1, horizon + 1)]
    q10 = [last - b for b in band]
    q90 = [last + b for b in band]
    return _sort_quantiles(q10, med, q90)


def seasonal_naive(train_series, exog=None, horizon=12, series_id=None, all_train=None):
    y = np.asarray(train_series, dtype=float)
    m = 12
    med = [float(y[len(y) - m + ((h - 1) % m)]) if len(y) >= m else float(y[-1])
           for h in range(1, horizon + 1)]
    if len(y) > m:
        sd = y[m:] - y[:-m]
        sigma = float(np.std(sd, ddof=1)) if len(sd) > 1 else 0.0
    else:
        sigma = 0.0
    # 계절 스텝 수(몇 번째 계절 주기인지)에 비례해 폭 확대
    band = [Z10 * sigma * np.sqrt(int(np.ceil(h / m))) for h in range(1, horizon + 1)]
    q10 = [med[i] - band[i] for i in range(horizon)]
    q90 = [med[i] + band[i] for i in range(horizon)]
    return _sort_quantiles(q10, med, q90)


# ── ② SARIMA ────────────────────────────────────────────────────────────────
def sarima(train_series, exog=None, horizon=12, series_id=None, all_train=None):
    import warnings

    import statsmodels.api as sm

    y = np.asarray(train_series, dtype=float)

    def _fit(order, seasonal_order):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = sm.tsa.statespace.SARIMAX(
                y, order=order, seasonal_order=seasonal_order,
                enforce_stationarity=False, enforce_invertibility=False,
            )
            res = model.fit(disp=False, maxiter=200)
        if not np.isfinite(res.llf):
            raise ValueError("non-finite log-likelihood")
        return res

    try:
        res = _fit((1, 1, 1), (1, 0, 1, 12))
    except Exception:
        # 수렴 실패 → 단순 (0,1,1) 폴백
        res = _fit((0, 1, 1), (0, 0, 0, 0))

    fc = res.get_forecast(steps=horizon)
    mean = np.asarray(fc.predicted_mean, dtype=float)
    se = np.asarray(fc.se_mean, dtype=float)
    med = mean.tolist()
    q10 = (mean - Z10 * se).tolist()
    q90 = (mean + Z10 * se).tolist()
    return _sort_quantiles(q10, med, q90)


# ── ③ LightGBM 직접 다중스텝 · 분위수 회귀 ──────────────────────────────────
def lightgbm(train_series, exog, horizon=12, series_id=None, all_train=None):
    import lightgbm as lgb

    y = np.asarray(train_series, dtype=float)
    feat = np.asarray(exog.to_numpy(dtype=float))
    n = len(y)
    valid_start = 12  # 앞 12행은 라그 NaN
    x_last = feat[n - 1:n]  # 오리진 시점 피처(라그만이므로 모두 유효)

    preds = {"q10": [], "median": [], "q90": []}
    key_for = {"q10": 0.1, "median": 0.5, "q90": 0.9}
    for h in range(1, horizon + 1):
        t_idx = np.arange(valid_start, n - h)  # 피처 유효 & 타깃 존재
        if len(t_idx) < 24:
            for k in preds:
                preds[k].append(float(y[-1]))  # 표본 부족 → 마지막값
            continue
        x_tr = feat[t_idx]
        y_tr = y[t_idx + h]
        for k, alpha in key_for.items():
            reg = lgb.LGBMRegressor(
                objective="quantile", alpha=alpha,
                n_estimators=150, learning_rate=0.05, num_leaves=15,
                min_child_samples=5, subsample=0.9, subsample_freq=1,
                colsample_bytree=0.9, reg_lambda=1.0,
                random_state=SEED, n_jobs=1, verbosity=-1,
                deterministic=True, force_row_wise=True,
            )
            reg.fit(x_tr, y_tr)
            preds[k].append(float(reg.predict(x_last)[0]))
    return _sort_quantiles(preds["q10"], preds["median"], preds["q90"])


# ── ④ PyTorch LSTM (전 시도 풀링 · 시도 임베딩) ─────────────────────────────
class _PooledLSTM:
    """전 시도 풀링 학습. 오리진(=학습 길이)별로 1회만 학습하고 캐시.

    입력: 표준화된 24개월 윈도 + 시도 임베딩 → horizon×3 분위수(표준화) 예측.
    표준화는 각 시도 학습구간 평균/표준편차 기준.
    """

    WINDOW = 24
    EMB = 8
    HIDDEN = 32
    EPOCHS = 120
    LR = 1e-3

    def __init__(self):
        self._cache = {}

    def _key(self, all_train):
        return tuple(sorted((k, len(v)) for k, v in all_train.items()))

    def _train(self, all_train, horizon):
        import torch
        import torch.nn as nn

        torch.manual_seed(SEED)
        np.random.seed(SEED)

        sidos = sorted(all_train.keys())
        sid_idx = {s: i for i, s in enumerate(sidos)}
        stats = {}
        X, S, Y = [], [], []
        for s in sidos:
            v = np.asarray(all_train[s], dtype=float)
            mu, sd = float(v.mean()), float(v.std() + 1e-8)
            stats[s] = (mu, sd)
            vz = (v - mu) / sd
            for i in range(len(vz) - self.WINDOW - horizon + 1):
                X.append(vz[i:i + self.WINDOW])
                Y.append(vz[i + self.WINDOW:i + self.WINDOW + horizon])
                S.append(sid_idx[s])
        Xt = torch.tensor(np.array(X), dtype=torch.float32).unsqueeze(-1)
        St = torch.tensor(np.array(S), dtype=torch.long)
        Yt = torch.tensor(np.array(Y), dtype=torch.float32)

        qs = torch.tensor(QUANTILES, dtype=torch.float32)

        class Net(nn.Module):
            def __init__(self, n_sido, emb, hidden, horizon, nq):
                super().__init__()
                self.emb = nn.Embedding(n_sido, emb)
                self.lstm = nn.LSTM(1, hidden, batch_first=True)
                self.head = nn.Sequential(
                    nn.Linear(hidden + emb, 64), nn.ReLU(),
                    nn.Linear(64, horizon * nq),
                )
                self.horizon, self.nq = horizon, nq

            def forward(self, x, sid):
                out, _ = self.lstm(x)
                z = torch.cat([out[:, -1, :], self.emb(sid)], dim=1)
                return self.head(z).view(-1, self.horizon, self.nq)

        net = Net(len(sidos), self.EMB, self.HIDDEN, horizon, len(QUANTILES))
        opt = torch.optim.Adam(net.parameters(), lr=self.LR)
        gen = torch.Generator().manual_seed(SEED)
        net.train()
        for _ in range(self.EPOCHS):
            perm = torch.randperm(len(Xt), generator=gen)
            for b in range(0, len(perm), 256):
                bi = perm[b:b + 256]
                opt.zero_grad()
                pred = net(Xt[bi], St[bi])           # (B,H,Q)
                tgt = Yt[bi].unsqueeze(-1)            # (B,H,1)
                err = tgt - pred                     # (B,H,Q)
                loss = torch.max(qs * err, (qs - 1) * err).mean()
                loss.backward()
                opt.step()
        net.eval()
        return {"net": net, "stats": stats, "sid_idx": sid_idx, "horizon": horizon}

    def fit_predict(self, train_series, exog, horizon=12, series_id=None, all_train=None):
        import torch

        if all_train is None or series_id is None:
            all_train = {"_solo": list(train_series)}
            series_id = "_solo"
        key = (self._key(all_train), horizon)
        if key not in self._cache:
            self._cache[key] = self._train(all_train, horizon)
        st = self._cache[key]
        net, stats, sid_idx = st["net"], st["stats"], st["sid_idx"]

        v = np.asarray(train_series, dtype=float)
        mu, sd = stats.get(series_id, (float(v.mean()), float(v.std() + 1e-8)))
        window = v[-self.WINDOW:]
        if len(window) < self.WINDOW:  # 앞을 첫값으로 패딩
            window = np.concatenate([np.full(self.WINDOW - len(window), window[0]), window])
        wz = (window - mu) / sd
        sid = sid_idx.get(series_id, 0)
        with torch.no_grad():
            x = torch.tensor(wz, dtype=torch.float32).view(1, self.WINDOW, 1)
            s = torch.tensor([sid], dtype=torch.long)
            out = net(x, s)[0].numpy()  # (H,Q)
        real = out * sd + mu
        return _sort_quantiles(real[:, 0].tolist(), real[:, 1].tolist(), real[:, 2].tolist())


_LSTM = _PooledLSTM()


def lstm(train_series, exog=None, horizon=12, series_id=None, all_train=None):
    return _LSTM.fit_predict(train_series, exog, horizon, series_id, all_train)


# ── ⑤ Chronos-Bolt-small 제로샷 ─────────────────────────────────────────────
CHRONOS_STATUS = {"available": None, "reason": ""}
_CHRONOS = None


def _get_chronos():
    global _CHRONOS
    if _CHRONOS is not None:
        return _CHRONOS if _CHRONOS != "FAILED" else None
    try:
        import torch
        from chronos import BaseChronosPipeline
        _CHRONOS = BaseChronosPipeline.from_pretrained(
            "amazon/chronos-bolt-small", device_map="cpu", torch_dtype=torch.float32,
        )
        CHRONOS_STATUS.update(available=True, reason="amazon/chronos-bolt-small 로드 성공")
    except Exception as e:  # noqa: BLE001 (사유를 삼키지 않고 기록)
        _CHRONOS = "FAILED"
        CHRONOS_STATUS.update(available=False, reason=f"{type(e).__name__}: {e}")
        return None
    return _CHRONOS


def chronos(train_series, exog=None, horizon=12, series_id=None, all_train=None):
    import torch

    pipe = _get_chronos()
    if pipe is None:
        return None  # 사유는 CHRONOS_STATUS 에 기록됨
    ctx = torch.tensor(np.asarray(train_series, dtype=np.float32))
    q, _mean = pipe.predict_quantiles(
        inputs=ctx, prediction_length=horizon, quantile_levels=list(QUANTILES),
    )
    arr = q[0].cpu().numpy()  # (H, 3)
    return _sort_quantiles(arr[:, 0].tolist(), arr[:, 1].tolist(), arr[:, 2].tolist())


# 모델 레지스트리(백테스트·빌드 공용). 실행 순서 고정.
MODELS = {
    "naive": naive,
    "seasonal_naive": seasonal_naive,
    "sarima": sarima,
    "lightgbm": lightgbm,
    "lstm": lstm,
    "chronos": chronos,
}
