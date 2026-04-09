"""
Byun & Wilhite (1999) original EDI implementation.

Pipeline summary
----------------
1. EP: effective precipitation with harmonic weighting
2. MEP/std: calendar-day climatology from fixed DS=365 EP
3. DEP/SEP: first-pass anomaly and standardized anomaly
4. dry_duration: consecutive days with SEP < 0
5. DS extension: DS = 365 + dry_duration - 1
6. EP_ext: recompute EP using the extended DS
7. Recompute MEP/DEP from EP_ext, then derive:
   - PRN = DEP_final / H(DS)
   - EDI = DEP_final / std(DEP_final)

The last step follows the paper's description that after extending the
addition period, MEP and DEP should be calculated once again.
"""

import numpy as np
import pandas as pd


EDI_CLASSES = [
    (2.00, np.inf, "Extremely Wet", "#0000FF"),
    (1.50, 2.00, "Very Wet", "#4169E1"),
    (1.00, 1.50, "Moderately Wet", "#87CEEB"),
    (-1.00, 1.00, "Near Normal", "#FFFFFF"),
    (-1.50, -1.00, "Moderate Drought", "#FFFF00"),
    (-2.00, -1.50, "Severe Drought", "#FFA500"),
    (-np.inf, -2.00, "Extreme Drought", "#FF0000"),
]


def harmonic_array(n_max: int) -> np.ndarray:
    """H[k] = 1 + 1/2 + ... + 1/k, H[0] = 0."""
    H = np.zeros(n_max + 1)
    for k in range(1, n_max + 1):
        H[k] = H[k - 1] + 1.0 / k
    return H


def compute_ep_fixed(precip: np.ndarray, ds: int, H: np.ndarray) -> np.ndarray:
    """
    EP(t, DS) = sum_{m=1..DS} P_m * [H(DS) - H(m-1)].

    P_1 is today's precipitation, P_2 yesterday's, and so on.
    """
    n = len(precip)
    w = H[ds] - H[:ds]
    ep = np.full(n, np.nan)
    for t in range(ds - 1, n):
        ep[t] = np.dot(precip[t - ds + 1 : t + 1][::-1], w)
    return ep


def compute_ep_variable(
    precip: np.ndarray, ds_arr: np.ndarray, H: np.ndarray
) -> np.ndarray:
    """
    Compute EP with a day-varying DS.

    EP(t) = sum_{k=1..DS[t]} S_k(t) / k
    where S_k(t) is the k-day accumulated precipitation ending at t.
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


def calendar_stats(
    ep: np.ndarray, dates: pd.DatetimeIndex, baseline_mask: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute calendar-day climatology mean and standard deviation.

    Returns arrays indexed by day-of-year 1..366. The mean is smoothed with
    a 5-day running mean, matching the existing implementation.
    """
    doy = dates.dayofyear

    mep_raw = np.full(367, np.nan)
    std_raw = np.full(367, np.nan)

    for d in range(1, 367):
        mask = baseline_mask & (doy == d) & (~np.isnan(ep))
        vals = ep[mask]
        if len(vals) >= 5:
            mep_raw[d] = vals.mean()
            std_raw[d] = vals.std(ddof=1)

    mep_sm = np.full(367, np.nan)
    for d in range(1, 367):
        idx = [(d - 2 + i - 1) % 365 + 1 for i in range(5)]
        vals = [mep_raw[i] for i in idx if not np.isnan(mep_raw[i])]
        mep_sm[d] = np.mean(vals) if vals else np.nan

    return mep_sm, std_raw


def run_edi(
    df_all: pd.DataFrame,
    baseline_years: tuple[int, int] = (1991, 2020),
    target_years: tuple[int, int] = (2025, 2025),
    ds_base: int = 365,
) -> pd.DataFrame:
    """
    Run the full EDI pipeline.

    Parameters
    ----------
    df_all:
        DataFrame with columns `date` and `precip_mm`.
    baseline_years:
        Inclusive climatology period.
    target_years:
        Inclusive output period.
    ds_base:
        Default duration of summation.

    Returns
    -------
    DataFrame with intermediate fields plus final `PRN` and `EDI`.
    """
    df = df_all.copy().sort_values("date").reset_index(drop=True)
    df["precip_mm"] = df["precip_mm"].fillna(0.0)

    dates = pd.DatetimeIndex(df["date"])
    precip = df["precip_mm"].to_numpy(dtype=float)
    doy = dates.dayofyear
    n = len(precip)

    max_ds_possible = ds_base + n
    H = harmonic_array(max_ds_possible)

    print("  [1/6] EP 계산 (DS=365)...")
    ep365 = compute_ep_fixed(precip, ds_base, H)

    print("  [2/6] 기후 평년값 계산 (MEP, sigma_EP)...")
    baseline_mask = (dates.year >= baseline_years[0]) & (
        dates.year <= baseline_years[1]
    )
    mep_by_doy, std_by_doy = calendar_stats(ep365, dates, baseline_mask)

    print("  [3/6] DEP, SEP 계산...")
    mep_arr = np.array([mep_by_doy[d] for d in doy])
    std_arr = np.array([std_by_doy[d] for d in doy])
    dep365 = ep365 - mep_arr
    sep = np.where(std_arr > 0, dep365 / std_arr, np.nan)

    print("  [4/6] dry_duration 계산...")
    dry_dur = np.zeros(n, dtype=int)
    for t in range(1, n):
        if not np.isnan(sep[t]) and sep[t] < 0.0:
            dry_dur[t] = dry_dur[t - 1] + 1
        else:
            dry_dur[t] = 0

    print("  [5/6] 확장 DS / EP_ext 계산...")
    ds_arr = np.where(dry_dur > 0, ds_base + dry_dur - 1, ds_base).astype(int)

    ep_ext = ep365.copy()
    needs_ext = ds_arr > ds_base
    if needs_ext.any():
        ep_var = compute_ep_variable(precip, ds_arr, H)
        ep_ext[needs_ext] = ep_var[needs_ext]

    print("  [6/6] EP_ext 기준 재표준화 및 EDI 산출...")
    mep_ext_by_doy, std_ext_by_doy = calendar_stats(ep_ext, dates, baseline_mask)
    mep_ext_arr = np.array([mep_ext_by_doy[d] for d in doy])
    std_ext_arr = np.array([std_ext_by_doy[d] for d in doy])
    dep_ext = ep_ext - mep_ext_arr
    H_ds = np.array([H[int(d)] for d in ds_arr])
    prn = np.where(H_ds > 0, dep_ext / H_ds, np.nan)
    edi = np.where(std_ext_arr > 0, dep_ext / std_ext_arr, np.nan)

    result = pd.DataFrame(
        {
            "date": dates,
            "precip_mm": precip,
            "EP": ep365,
            "MEP": mep_arr,
            "DEP": dep365,
            "SEP": sep,
            "MEP_final": mep_ext_arr,
            "DEP_final": dep_ext,
            "STD_final": std_ext_arr,
            "dry_dur": dry_dur,
            "DS": ds_arr,
            "EP_ext": ep_ext,
            "PRN": prn,
            "EDI": edi,
        }
    )

    mask_target = (result["date"].dt.year >= target_years[0]) & (
        result["date"].dt.year <= target_years[1]
    )
    return result[mask_target].reset_index(drop=True)
