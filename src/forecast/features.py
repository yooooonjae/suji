"""부동산 예측 피처 파이프라인.

시도별 아파트 매매가격지수(타깃)에 외생 피처(미분양·착공·금리·CCI·분양가)를
ym 기준으로 정렬 병합하고 라그(1,3,6,12) 피처를 만든다. 결측은 해당 행 드롭(보간 금지).
전국 포함 18계열.

- 타깃: rone.json `sale_index` (전국+17시도, 201607~202606, 지수 2026.01=100)
- 외생(시도별): 미분양 unsold, 착공 starts (kosis) · 분양가 presale (rone)
- 외생(전국 브로드캐스트): CCI cci (kosis) · 기준금리 base_rate · 주담대금리 mortgage_rate (ecos)

라그만 피처로 사용한다(동시점 외생은 미래값이 없어 예측에 못 씀). 이렇게 하면
최종월(202606)도 라그가 모두 존재해 예측 오리진으로 쓸 수 있다.
"""

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

LAGS = (1, 3, 6, 12)
# 시도별 외생(각 시도 고유 계열) / 전국 외생(단일 계열을 전 시도에 브로드캐스트)
EXOG_SIDO = ["unsold", "starts", "presale"]
EXOG_NATION = ["cci", "base_rate", "mortgage_rate"]
EXOG = EXOG_SIDO + EXOG_NATION


def _series_to_map(rows):
    """[{"ym","value"}, ...] → {ym: value} (float)."""
    return {r["ym"]: float(r["value"]) for r in rows}


def load_raw():
    rone = json.load(open(DATA / "rone.json"))
    kosis = json.load(open(DATA / "kosis.json"))
    ecos = json.load(open(DATA / "ecos.json"))
    return rone, kosis, ecos


def sido_list(rone):
    """전국+17시도 (타깃 계열 기준, 18개)."""
    return list(rone["sale_index"].keys())


def build_sido_frame(sido, rone, kosis, ecos):
    """한 시도의 타깃+외생을 ym 정렬로 병합한 원본 프레임(라그 이전)."""
    y = _series_to_map(rone["sale_index"][sido])
    idx = sorted(y.keys())
    df = pd.DataFrame({"ym": idx})
    df["y"] = df["ym"].map(y)
    # 시도별 외생
    df["unsold"] = df["ym"].map(_series_to_map(kosis["unsold"].get(sido, [])))
    df["starts"] = df["ym"].map(_series_to_map(kosis["starts"].get(sido, [])))
    df["presale"] = df["ym"].map(_series_to_map(rone["presale_price"].get(sido, [])))
    # 전국 브로드캐스트
    df["cci"] = df["ym"].map(_series_to_map(kosis["cci"]))
    df["base_rate"] = df["ym"].map(_series_to_map(ecos["base_rate"]))
    df["mortgage_rate"] = df["ym"].map(_series_to_map(ecos["mortgage_rate"]))
    return df


def add_lags(df):
    """타깃·외생의 라그(1,3,6,12) 컬럼을 추가하고 피처 컬럼명 목록을 돌려준다."""
    feat_cols = []
    for col in ["y"] + EXOG:
        for lag in LAGS:
            name = f"{col}_lag{lag}"
            df[name] = df[col].shift(lag)
            feat_cols.append(name)
    return df, feat_cols


def build_panel():
    """전 시도 패널.

    반환: {sido: {"yms": [...], "values": [...타깃...], "features": DataFrame,
                  "feat_cols": [...]}}
      - values/yms: 타깃 전체(라그 드롭 이전) — naive/SARIMA/LSTM/Chronos용
      - features: values 와 같은 행 순서·길이의 라그 피처 프레임(앞 12행은 NaN)
                  — LightGBM 이 내부에서 유효행만 사용
    """
    rone, kosis, ecos = load_raw()
    panel = {}
    for sido in sido_list(rone):
        df = build_sido_frame(sido, rone, kosis, ecos)
        df, feat_cols = add_lags(df)
        panel[sido] = {
            "yms": df["ym"].tolist(),
            "values": df["y"].astype(float).tolist(),
            "features": df[feat_cols].reset_index(drop=True),
            "feat_cols": feat_cols,
        }
    return panel


if __name__ == "__main__":
    p = build_panel()
    print(f"계열 수: {len(p)}")
    for s in ["전국", "서울"]:
        d = p[s]
        print(f"{s}: {len(d['values'])}개월 {d['yms'][0]}~{d['yms'][-1]}, "
              f"피처 {len(d['feat_cols'])}개, "
              f"유효행(라그 드롭 후) {d['features'].dropna().shape[0]}")
