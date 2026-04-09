"""
개선 CEDI (Improved CEDI)
= CEDI 시간감쇠 유출보정 + DS=365 고정 + L-moment Pearson III 표준화

설계 원칙:
  - DS 확장과 P3 꼬리 표현은 동일한 역할(극단 가뭄 강조)이므로 중복 사용 않음
  - DS=365 고정으로 기준기간-대상기간 스케일 일관성 유지
  - 유출보정만 α즉시 → CEDI 시간감쇠로 개선 (scCEDI-K 대비 핵심 개선점)

scCEDI-K 현재와의 차이:
  유출보정: α=0.2 즉시 → e^{-0.5(m-1)} 시간감쇠 (EP 내부에서 처리)

pipeline:
  1. CEP(DS=365, CEDI 시간감쇠)  Pc_m = min(Pm,80) + max(Pm-80,0)·e^{-0.5(m-1)}
  2. MEP = 기준기간 달력일별 평균 (5일 원형 평활)
  3. DCEP = CEP - MEP
  4. PRN  = DCEP / H(365)          ← DS=365 고정
  5. L-moment P3 PIT → Φ⁻¹(F)     ← pool_half=0 or 15
"""

import numpy as np
import pandas as pd

from cedi_algorithm import (
    harmonic_array,
    compute_cep_fixed,
    calendar_stats,
    CEDI_THRESHOLD,
    CEDI_DECAY,
)
from sccedik import lmom_pearson3_standardize


def run_improved_cedi(
    df_all: pd.DataFrame,
    baseline_years: tuple[int, int] = (1991, 2020),
    target_years: tuple[int, int] = (2025, 2025),
    ds_base: int = 365,
    threshold: float = CEDI_THRESHOLD,
    decay: float = CEDI_DECAY,
    pool_half: int = 15,
) -> pd.DataFrame:
    """
    개선 CEDI 파이프라인.

    Parameters
    ----------
    pool_half : 0  → 개선A: 달력일 정확 (~30 표본)
                15 → 개선B: ±15일 풀링  (~930 표본)
    """
    df = df_all.copy().sort_values("date").reset_index(drop=True)
    df["precip_mm"] = df["precip_mm"].fillna(0.0)
    dates = pd.DatetimeIndex(df["date"])
    precip = df["precip_mm"].to_numpy(dtype=float)
    n = len(precip)

    pool_label = "풀링없음" if pool_half == 0 else f"±{pool_half}일풀링"

    # ── 1. CEP (DS=365, CEDI 시간감쇠) ─────────────────────────────
    print(f"  [1/5] CEP (DS={ds_base}, CEDI감쇠 {threshold:.0f}mm)...")
    H = harmonic_array(ds_base + 10)
    cep = compute_cep_fixed(precip, ds_base, H, threshold, decay)

    # ── 2. MEP (기준기간, 5일 원형 평활) ────────────────────────────
    print(f"  [2/5] MEP 계산...")
    baseline_mask = (
        (dates.year >= baseline_years[0]) & (dates.year <= baseline_years[1])
    )
    mep_by_doy, _ = calendar_stats(cep, dates, baseline_mask)
    doy = dates.dayofyear
    mep_arr = np.array([mep_by_doy[d] for d in doy])

    # ── 3. DCEP, PRN (DS=365 고정) ──────────────────────────────────
    print(f"  [3/5] DCEP → PRN (DS=365 고정)...")
    dcep = cep - mep_arr
    prn = dcep / H[ds_base]   # H(365) 상수 — 스케일 일관성 보장

    # ── 4. L-moment P3 표준화 ───────────────────────────────────────
    print(f"  [4/5] L-moment P3 표준화 ({pool_label})...")
    result_vals = np.full(n, np.nan)
    for yr in range(target_years[0], target_years[1] + 1):
        yr_result = lmom_pearson3_standardize(
            prn, dates, yr,
            pool_half=pool_half,
            fixed_baseline=baseline_years,
        )
        yr_mask = dates.year == yr
        result_vals[yr_mask] = yr_result[yr_mask]

    # ── 5. 보조지표 (dry_duration, DS) ──────────────────────────────
    print(f"  [5/5] 보조지표...")
    dry_dur = np.zeros(n, dtype=int)
    for t in range(1, n):
        if not np.isnan(result_vals[t]) and result_vals[t] < 0.0:
            dry_dur[t] = dry_dur[t - 1] + 1
        else:
            dry_dur[t] = 0
    ds_arr = np.where(dry_dur > 0, ds_base + dry_dur - 1, ds_base).astype(int)

    result = pd.DataFrame({
        "date":         dates,
        "precip_mm":    precip,
        "CEP":          cep,
        "MEP":          mep_arr,
        "DCEP":         dcep,
        "PRN":          prn,
        "ImprovedCEDI": result_vals,
        "dry_dur":      dry_dur,
        "DS":           ds_arr,
    })

    mask = (
        (result["date"].dt.year >= target_years[0]) &
        (result["date"].dt.year <= target_years[1])
    )
    return result[mask].reset_index(drop=True)
