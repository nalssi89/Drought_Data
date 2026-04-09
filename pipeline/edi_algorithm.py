"""
Byun & Wilhite (1999) 원형 EDI 알고리즘 구현
"Objective Quantification of Drought Severity and Duration"

알고리즘 순서:
  1. EP   : 유효강수량 (조화가중 누적형, 식 2)
  2. MEP  : EP의 달력일별 기후평균 (5일 이동평균 평활)
  3. DEP  : EP 편차 (EP - MEP)
  4. SEP  : 표준화 EP 편차 (DEP / σ_EP)
  5. dry_duration : SEP < 0 연속일수
  6. DS   : 합산기간 확장 (365 + dry_duration - 1)
  7. EP_ext : 확장 DS로 재계산한 EP
  8. PRN  : 정상화에 필요한 일강수량 (DEP / H(DS))
  9. EDI  : PRN 표준화 가뭄지수 (PRN / σ_PRN)
"""

import numpy as np
import pandas as pd

# ── 가뭄 등급 분류 ────────────────────────────────────────────────
EDI_CLASSES = [
    (2.00, np.inf,  "Extremely Wet",   "#0000FF"),
    (1.50, 2.00,    "Very Wet",        "#4169E1"),
    (1.00, 1.50,    "Moderately Wet",  "#87CEEB"),
    (-1.00, 1.00,   "Near Normal",     "#FFFFFF"),
    (-1.50, -1.00,  "Moderate Drought","#FFFF00"),
    (-2.00, -1.50,  "Severe Drought",  "#FFA500"),
    (-np.inf, -2.00,"Extreme Drought", "#FF0000"),
]


def harmonic_array(n_max: int) -> np.ndarray:
    """H[k] = 1 + 1/2 + ... + 1/k, H[0] = 0"""
    H = np.zeros(n_max + 1)
    for k in range(1, n_max + 1):
        H[k] = H[k-1] + 1.0 / k
    return H


def compute_ep_fixed(precip: np.ndarray, ds: int, H: np.ndarray) -> np.ndarray:
    """
    EP(t, DS) = Σ(m=1→DS) P_m * [H(DS) - H(m-1)]
    P_1 = today, P_2 = yesterday, ..., P_DS = DS-1 days ago.
    H는 harmonic_array(max_ds) 결과.
    """
    n = len(precip)
    # w[j] = H(DS) - H(j) for j=0..DS-1  (j=m-1)
    w = H[ds] - H[:ds]     # shape (DS,)
    ep = np.full(n, np.nan)
    for t in range(ds - 1, n):
        # precip[t], precip[t-1], ..., precip[t-ds+1]  →  P_1..P_DS
        ep[t] = np.dot(precip[t - ds + 1: t + 1][::-1], w)
    return ep


def compute_ep_variable(precip: np.ndarray, ds_arr: np.ndarray,
                         H: np.ndarray) -> np.ndarray:
    """
    EP(t) = Σ(k=1→DS[t]) S_k(t) / k
    여기서 S_k(t) = Σ(j=0→k-1) precip[t-j]  (k일 누적강수)
    누적합으로 S_k를 O(1)에 계산.
    """
    n = len(precip)
    cumsum = np.zeros(n + 1)
    cumsum[1:] = np.cumsum(precip)

    ep = np.full(n, np.nan)
    for t in range(n):
        ds = int(ds_arr[t])
        if ds <= 0 or t < ds - 1:
            continue
        ep_val = 0.0
        for k in range(1, ds + 1):
            s_k = cumsum[t + 1] - cumsum[t - k + 1]
            ep_val += s_k / k
        ep[t] = ep_val
    return ep


def calendar_stats(ep: np.ndarray, dates: pd.DatetimeIndex,
                   baseline_mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    달력일별(doy 1~366) 기후평균(MEP)과 표준편차(σ) 계산.
    MEP는 5일 원형 이동평균으로 평활.
    baseline_mask: True인 날짜만 통계에 사용.
    """
    doy = dates.dayofyear  # 1~366

    mep_raw = np.full(367, np.nan)   # index 1..366
    std_raw = np.full(367, np.nan)

    for d in range(1, 367):
        mask = baseline_mask & (doy == d) & (~np.isnan(ep))
        vals = ep[mask]
        if len(vals) >= 5:
            mep_raw[d] = vals.mean()
            std_raw[d] = vals.std(ddof=1)

    # 5일 원형 이동평균
    mep_sm = np.full(367, np.nan)
    valid = np.arange(1, 367)
    for d in valid:
        idx = [(d - 2 + i - 1) % 365 + 1 for i in range(5)]  # 원형 ±2
        vals = [mep_raw[i] for i in idx if not np.isnan(mep_raw[i])]
        mep_sm[d] = np.mean(vals) if vals else np.nan

    return mep_sm, std_raw


def run_edi(df_all: pd.DataFrame,
            baseline_years: tuple[int, int] = (1991, 2020),
            target_years: tuple[int, int] = (2025, 2025),
            ds_base: int = 365) -> pd.DataFrame:
    """
    전체 EDI 계산 파이프라인.

    Parameters
    ----------
    df_all         : date(DatetimeIndex), precip_mm 컬럼을 가진 DataFrame
    baseline_years : MEP/σ 계산에 사용할 기간 (시작, 끝 연도 포함)
    target_years   : EDI 출력할 기간
    ds_base        : 기본 합산기간 (default 365)

    Returns
    -------
    pd.DataFrame with columns: date, precip_mm, EP, DEP, SEP,
                                dry_dur, DS, EP_ext, PRN, EDI
    """
    df = df_all.copy()
    df = df.sort_values("date").reset_index(drop=True)
    df["precip_mm"] = df["precip_mm"].fillna(0.0)  # 결측 → 0

    dates = pd.DatetimeIndex(df["date"])
    precip = df["precip_mm"].to_numpy(dtype=float)
    n = len(precip)

    # ── 1. EP (DS=365 고정) ───────────────────────────────────────
    max_ds_possible = ds_base + 400        # 최대 연장치 여유
    H = harmonic_array(max_ds_possible)

    print("  [1/6] EP 계산 (DS=365)...")
    ep365 = compute_ep_fixed(precip, ds_base, H)

    # ── 2. MEP, σ_EP (기후 평년값) ──────────────────────────────
    print("  [2/6] 기후 평년값 계산 (MEP, σ_EP)...")
    baseline_mask = (dates.year >= baseline_years[0]) & (dates.year <= baseline_years[1])
    mep_by_doy, std_by_doy = calendar_stats(ep365, dates, baseline_mask)

    # ── 3. DEP, SEP ──────────────────────────────────────────────
    print("  [3/6] DEP, SEP 계산...")
    doy = dates.dayofyear
    mep_arr = np.array([mep_by_doy[d] for d in doy])
    std_arr = np.array([std_by_doy[d] for d in doy])

    dep365 = ep365 - mep_arr
    sep = dep365 / std_arr

    # ── 4. dry_duration ──────────────────────────────────────────
    print("  [4/6] dry_duration 계산...")
    dry_dur = np.zeros(n, dtype=int)
    for t in range(1, n):
        if not np.isnan(sep[t]) and sep[t] < 0.0:
            dry_dur[t] = dry_dur[t - 1] + 1
        else:
            dry_dur[t] = 0

    # ── 5. 확장 DS, EP_ext ───────────────────────────────────────
    print("  [5/6] 확장 DS / EP_ext 계산...")
    ds_arr = np.where(dry_dur > 0,
                      ds_base + dry_dur - 1,
                      ds_base).astype(int)

    # DS=365 구간은 이미 계산된 ep365 재사용,
    # 확장이 필요한 날만 variable 계산
    ep_ext = ep365.copy()
    needs_ext = ds_arr > ds_base
    if needs_ext.any():
        ep_var = compute_ep_variable(precip, ds_arr, H)
        ep_ext[needs_ext] = ep_var[needs_ext]

    # ── 6. PRN 계산 ───────────────────────────────────────────────
    dep_ext = ep_ext - mep_arr
    H_ds = np.array([H[int(d)] for d in ds_arr])
    prn = np.where(H_ds > 0, dep_ext / H_ds, np.nan)

    # ── 7. σ_PRN (기후 평년값 기반) ──────────────────────────────
    # 평년 기간의 PRN로 σ_PRN 계산 (EDI 표준화용)
    # 동일한 ds_arr를 baseline 기간에도 적용하면 복잡하므로,
    # baseline 기간의 sep 기반 dry_dur을 다시 계산
    print("  [6/6] σ_PRN 계산 및 EDI 산출...")
    prn_std_by_doy = np.full(367, np.nan)
    # baseline 전체 PRN 수집 후 doy별 std
    prn_by_doy: dict[int, list] = {d: [] for d in range(1, 367)}
    for t in range(n):
        if baseline_mask[t] and not np.isnan(prn[t]):
            prn_by_doy[doy[t]].append(prn[t])
    for d in range(1, 367):
        vals = prn_by_doy[d]
        if len(vals) >= 5:
            prn_std_by_doy[d] = np.std(vals, ddof=1)

    prn_std_arr = np.array([prn_std_by_doy[d] for d in doy])
    edi = np.where(prn_std_arr > 0, prn / prn_std_arr, np.nan)

    # ── 결과 정리 ─────────────────────────────────────────────────
    result = pd.DataFrame({
        "date":      dates,
        "precip_mm": precip,
        "EP":        ep365,
        "MEP":       mep_arr,
        "DEP":       dep365,
        "SEP":       sep,
        "dry_dur":   dry_dur,
        "DS":        ds_arr,
        "EP_ext":    ep_ext,
        "PRN":       prn,
        "EDI":       edi,
    })

    # target 기간만 반환
    mask_target = (result["date"].dt.year >= target_years[0]) & \
                  (result["date"].dt.year <= target_years[1])
    return result[mask_target].reset_index(drop=True)
