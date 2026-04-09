"""
Kim et al. (2009) original CEDI implementation.

Pipeline summary
----------------
1. CEP: corrected effective precipitation with heavy-rainfall runoff correction
2. MEP/std: calendar-day climatology from fixed DS=365 CEP
3. DCEP/SEP: first-pass anomaly and standardized anomaly
4. dry_duration: consecutive days with SEP < 0
5. DS extension: DS = 365 + dry_duration - 1
6. CEP_ext: recompute CEP using the extended DS
7. Recompute MEP/DCEP from CEP_ext, then derive:
   - PRN = DCEP_final / H(DS)
   - CEDI = DCEP_final / std(DCEP_final)

This follows the paper's described sequence: extend the addition period,
recalculate EP/CEP, then calculate MEP and DEP/DCEP once again.
"""

import numpy as np
import pandas as pd


CEDI_THRESHOLD = 80.0
CEDI_DECAY = 0.5


def harmonic_array(n_max: int) -> np.ndarray:
    """H[k] = 1 + 1/2 + ... + 1/k, H[0] = 0."""
    H = np.zeros(n_max + 1)
    for k in range(1, n_max + 1):
        H[k] = H[k - 1] + 1.0 / k
    return H


def _make_cep_weights(
    ds: int, H: np.ndarray, decay: float = CEDI_DECAY
) -> tuple[np.ndarray, np.ndarray]:
    """
    Return the base and excess-weight vectors for a given DS.

    w_base[m-1]   = H(DS) - H(m-1)
    w_excess[m-1] = exp(-decay * (m-1)) * w_base[m-1]
    """
    m_idx = np.arange(ds)
    w_base = H[ds] - H[m_idx]
    w_excess = np.exp(-decay * m_idx) * w_base
    return w_base, w_excess


def compute_cep_fixed(
    precip: np.ndarray,
    ds: int,
    H: np.ndarray,
    threshold: float = CEDI_THRESHOLD,
    decay: float = CEDI_DECAY,
) -> np.ndarray:
    """
    Compute CEP with fixed DS.

    Pc_m = min(Pm, threshold) + max(Pm - threshold, 0) * exp(-decay * (m-1))
    CEP(t) = sum_{m=1..DS} Pc_m(t) * [H(DS) - H(m-1)]
    """
    n = len(precip)
    w_base, w_excess = _make_cep_weights(ds, H, decay)

    precip_base = np.minimum(precip, threshold)
    precip_excess = np.maximum(precip - threshold, 0.0)

    cep = np.full(n, np.nan)
    for t in range(ds - 1, n):
        base_lag = precip_base[t - ds + 1 : t + 1][::-1]
        excess_lag = precip_excess[t - ds + 1 : t + 1][::-1]
        cep[t] = np.dot(base_lag, w_base) + np.dot(excess_lag, w_excess)
    return cep


def compute_cep_variable(
    precip: np.ndarray,
    ds_arr: np.ndarray,
    H: np.ndarray,
    threshold: float = CEDI_THRESHOLD,
    decay: float = CEDI_DECAY,
) -> np.ndarray:
    """Compute CEP with a day-varying DS."""
    n = len(precip)
    max_ds = int(ds_arr.max()) if len(ds_arr) > 0 else 365

    precip_base = np.minimum(precip, threshold)
    precip_excess = np.maximum(precip - threshold, 0.0)

    m_idx_all = np.arange(max_ds)
    decay_all = np.exp(-decay * m_idx_all)

    cep = np.full(n, np.nan)
    for t in range(n):
        ds = int(ds_arr[t])
        if ds <= 0 or t < ds - 1:
            continue
        w_base = H[ds] - H[:ds]
        w_excess = decay_all[:ds] * w_base

        base_lag = precip_base[t - ds + 1 : t + 1][::-1]
        excess_lag = precip_excess[t - ds + 1 : t + 1][::-1]
        cep[t] = np.dot(base_lag, w_base) + np.dot(excess_lag, w_excess)
    return cep


def calendar_stats(
    cep: np.ndarray,
    dates: pd.DatetimeIndex,
    baseline_mask: np.ndarray,
    smooth: int = 5,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute calendar-day climatology mean and standard deviation from CEP.

    Returns arrays indexed by day-of-year 1..366. The mean is smoothed with
    a running mean, matching the existing implementation.
    """
    doy = dates.dayofyear

    mep_raw = np.full(367, np.nan)
    std_raw = np.full(367, np.nan)

    for d in range(1, 367):
        mask = baseline_mask & (doy == d) & (~np.isnan(cep))
        vals = cep[mask]
        if len(vals) >= 5:
            mep_raw[d] = vals.mean()
            std_raw[d] = vals.std(ddof=1)

    half = smooth // 2
    mep_sm = np.full(367, np.nan)
    for d in range(1, 367):
        idx = [(d - 1 + offset) % 366 + 1 for offset in range(-half, half + 1)]
        vals = [mep_raw[i] for i in idx if not np.isnan(mep_raw[i])]
        mep_sm[d] = np.mean(vals) if vals else np.nan

    return mep_sm, std_raw


def run_cedi(
    df_all: pd.DataFrame,
    baseline_years: tuple[int, int] = (1991, 2020),
    target_years: tuple[int, int] = (2025, 2025),
    ds_base: int = 365,
    threshold: float = CEDI_THRESHOLD,
    decay: float = CEDI_DECAY,
) -> pd.DataFrame:
    """
    Run the full CEDI pipeline.

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
    threshold:
        Heavy-rainfall threshold in mm/day.
    decay:
        Exponential runoff-decay coefficient for excess rainfall.
    """
    df = df_all.copy().sort_values("date").reset_index(drop=True)
    df["precip_mm"] = df["precip_mm"].fillna(0.0)

    dates = pd.DatetimeIndex(df["date"])
    precip = df["precip_mm"].to_numpy(dtype=float)
    doy = dates.dayofyear
    n = len(precip)

    H = harmonic_array(ds_base + n)

    print(f"  [1/6] CEP 계산 (DS=365, threshold={threshold:.0f}mm)...")
    cep365 = compute_cep_fixed(precip, ds_base, H, threshold, decay)

    print("  [2/6] 기후 평년값 계산 (MEP, sigma_DCEP)...")
    baseline_mask = (dates.year >= baseline_years[0]) & (
        dates.year <= baseline_years[1]
    )
    mep_by_doy, std_by_doy = calendar_stats(cep365, dates, baseline_mask)

    print("  [3/6] DCEP, SEP 계산...")
    mep_arr = np.array([mep_by_doy[d] for d in doy])
    std_arr = np.array([std_by_doy[d] for d in doy])
    dcep365 = cep365 - mep_arr
    sep = np.where(std_arr > 0, dcep365 / std_arr, np.nan)

    print("  [4/6] dry_duration 계산...")
    dry_dur = np.zeros(n, dtype=int)
    for t in range(1, n):
        if not np.isnan(sep[t]) and sep[t] < 0.0:
            dry_dur[t] = dry_dur[t - 1] + 1
        else:
            dry_dur[t] = 0

    print("  [5/6] 확장 DS / CEP_ext 계산...")
    ds_arr = np.where(dry_dur > 0, ds_base + dry_dur - 1, ds_base).astype(int)

    cep_ext = cep365.copy()
    needs_ext = ds_arr > ds_base
    if needs_ext.any():
        cep_var = compute_cep_variable(precip, ds_arr, H, threshold, decay)
        cep_ext[needs_ext] = cep_var[needs_ext]

    print("  [6/6] CEP_ext 기준 재표준화 및 CEDI 산출...")
    mep_ext_by_doy, std_ext_by_doy = calendar_stats(cep_ext, dates, baseline_mask)
    mep_ext_arr = np.array([mep_ext_by_doy[d] for d in doy])
    std_ext_arr = np.array([std_ext_by_doy[d] for d in doy])
    dcep_ext = cep_ext - mep_ext_arr
    H_ds = np.array([H[int(d)] for d in ds_arr])
    prn = np.where(H_ds > 0, dcep_ext / H_ds, np.nan)
    cedi = np.where(std_ext_arr > 0, dcep_ext / std_ext_arr, np.nan)

    result = pd.DataFrame(
        {
            "date": dates,
            "precip_mm": precip,
            "CEP": cep365,
            "MEP": mep_arr,
            "DCEP": dcep365,
            "SEP": sep,
            "MEP_final": mep_ext_arr,
            "DCEP_final": dcep_ext,
            "STD_final": std_ext_arr,
            "dry_dur": dry_dur,
            "DS": ds_arr,
            "CEP_ext": cep_ext,
            "PRN": prn,
            "CEDI": cedi,
        }
    )

    mask_target = (result["date"].dt.year >= target_years[0]) & (
        result["date"].dt.year <= target_years[1]
    )
    return result[mask_target].reset_index(drop=True)
