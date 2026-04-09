"""
Kim et al. (2009) CEDI (Corrected EDI) 원본 재현
"Evaluation, modification, and application of the Effective Drought Index
to 200-year drought climatology of Seoul, Korea"
Journal of Hydrology 378, 1–12.

CEDI = EDI에 집중호우 후 급속 유출 보정을 추가한 지수.

알고리즘 순서:
  1. CEP  : 유출보정 유효강수량 (논문 Eq.4)
              Pc_m = min(Pm, 80) + max(Pm-80, 0) × exp(-0.5×(m-1))
              CEP  = Σ(n=1→i) [(Σ(m=1→n) Pc_m) / n]
  2. MEP  : CEP의 달력일별 기후평균 (30년, 5일 평활)
  3. DCEP : CEP - MEP (편차)
  4. SEP  : DCEP / σ(DCEP)  — dry duration 판별용
  5. dry_duration : SEP < 0 연속일수
  6. DS   : 365 + dry_duration - 1
  7. CEP_ext : 확장 DS로 재계산한 CEP
  8. PRN  : DCEP_ext / H(DS)
  9. CEDI : PRN / σ(PRN)  = DCEP_ext / σ(DCEP_ext)

표준화: EDI와 동일한 정규 표준화 (z-score), 논문 Eq.(3)
임계값: 80 mm/day (논문 민감도 분석 최적값)
감쇠계수: 0.5 → 10일 후 초과분 ≈ 1% (논문 Fig.3 기준)
"""

import numpy as np
import pandas as pd


CEDI_THRESHOLD = 80.0   # mm/day, 논문 Eq.(4) 기준
CEDI_DECAY = 0.5        # 감쇠계수 (논문 e^{-0.5(m-1)})


# ── 공유 유틸리티 ────────────────────────────────────────────────────


def harmonic_array(n_max: int) -> np.ndarray:
    """H[k] = 1 + 1/2 + ... + 1/k,  H[0] = 0"""
    H = np.zeros(n_max + 1)
    for k in range(1, n_max + 1):
        H[k] = H[k - 1] + 1.0 / k
    return H


# ── STEP 1: CEP 계산 ──────────────────────────────────────────────


def _make_cep_weights(ds: int, H: np.ndarray, decay: float = CEDI_DECAY):
    """
    주어진 DS에 대한 두 가중치 벡터 반환.

    w_base[m-1]   = H(DS) - H(m-1)          조화 가중치 (기본 강수용)
    w_excess[m-1] = exp(-decay*(m-1)) × w    초과 강수용 (감쇠 × 조화)

    Returns
    -------
    w_base, w_excess : ndarray, shape (DS,)
    """
    m_idx = np.arange(ds)            # m-1 = 0, 1, ..., ds-1
    w_base = H[ds] - H[m_idx]       # H(DS) - H(m-1)
    w_excess = np.exp(-decay * m_idx) * w_base
    return w_base, w_excess


def compute_cep_fixed(precip: np.ndarray, ds: int, H: np.ndarray,
                      threshold: float = CEDI_THRESHOLD,
                      decay: float = CEDI_DECAY) -> np.ndarray:
    """
    고정 DS=365인 CEP 계산 (논문 Eq.4).

    CEP(t) = Σ(m=1→DS) Pc_m(t) × [H(DS) - H(m-1)]
    Pc_m = min(Pm, threshold) + max(Pm - threshold, 0) × exp(-decay×(m-1))

    Parameters
    ----------
    precip    : 일강수량 배열
    ds        : 합산기간 (365)
    H         : harmonic_array
    threshold : 집중호우 임계값 (80 mm)
    decay     : 초과분 감쇠계수 (0.5)
    """
    n = len(precip)
    w_base, w_excess = _make_cep_weights(ds, H, decay)

    # 강수 분리
    precip_base = np.minimum(precip, threshold)
    precip_excess = np.maximum(precip - threshold, 0.0)

    cep = np.full(n, np.nan)
    for t in range(ds - 1, n):
        # [t-ds+1 .. t]를 역순 → m=1(오늘) ~ m=DS(DS-1일 전)
        base_lag = precip_base[t - ds + 1: t + 1][::-1]
        excess_lag = precip_excess[t - ds + 1: t + 1][::-1]
        cep[t] = np.dot(base_lag, w_base) + np.dot(excess_lag, w_excess)

    return cep


def compute_cep_variable(precip: np.ndarray, ds_arr: np.ndarray,
                          H: np.ndarray,
                          threshold: float = CEDI_THRESHOLD,
                          decay: float = CEDI_DECAY) -> np.ndarray:
    """
    가변 DS를 이용한 CEP 계산 (가뭄 기간 DS 확장 시 사용).

    Parameters
    ----------
    ds_arr : 날짜별 DS 배열
    """
    n = len(precip)
    max_ds = int(ds_arr.max()) if len(ds_arr) > 0 else 365

    precip_base = np.minimum(precip, threshold)
    precip_excess = np.maximum(precip - threshold, 0.0)

    # 최대 DS에 대한 가중치 미리 계산 후 슬라이싱
    m_idx_all = np.arange(max_ds)
    decay_all = np.exp(-decay * m_idx_all)

    cep = np.full(n, np.nan)
    for t in range(n):
        ds = int(ds_arr[t])
        if ds <= 0 or t < ds - 1:
            continue
        w_base = H[ds] - H[:ds]
        w_excess = decay_all[:ds] * w_base

        base_lag = precip_base[t - ds + 1: t + 1][::-1]
        excess_lag = precip_excess[t - ds + 1: t + 1][::-1]
        cep[t] = np.dot(base_lag, w_base) + np.dot(excess_lag, w_excess)

    return cep


# ── STEP 2: MEP (기후 평균) ──────────────────────────────────────


def calendar_stats(cep: np.ndarray, dates: pd.DatetimeIndex,
                   baseline_mask: np.ndarray,
                   smooth: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """
    달력일별(doy 1~366) MEP와 σ(DCEP) 계산.
    MEP는 smooth-일 원형 이동평균으로 평활.

    Returns
    -------
    mep_sm  : ndarray(367,)  — index 1..366
    std_raw : ndarray(367,)
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

    # 원형 이동평균 (±half)
    half = smooth // 2
    mep_sm = np.full(367, np.nan)
    for d in range(1, 367):
        idx = [(d - 1 + offset) % 366 + 1 for offset in range(-half, half + 1)]
        vals = [mep_raw[i] for i in idx if not np.isnan(mep_raw[i])]
        mep_sm[d] = np.mean(vals) if vals else np.nan

    return mep_sm, std_raw


# ── 메인 파이프라인 ──────────────────────────────────────────────


def run_cedi(df_all: pd.DataFrame,
             baseline_years: tuple[int, int] = (1991, 2020),
             target_years: tuple[int, int] = (2025, 2025),
             ds_base: int = 365,
             threshold: float = CEDI_THRESHOLD,
             decay: float = CEDI_DECAY) -> pd.DataFrame:
    """
    Kim et al. (2009) CEDI 전체 파이프라인.

    Parameters
    ----------
    df_all         : date(DatetimeIndex), precip_mm 컬럼 DataFrame
    baseline_years : MEP/σ 계산 기준기간 (시작, 끝 연도 포함)
    target_years   : CEDI 출력 기간
    ds_base        : 기본 합산기간 (365)
    threshold      : 집중호우 임계값 mm (논문 최적값 80)
    decay          : 초과분 감쇠계수 (논문 0.5)

    Returns
    -------
    pd.DataFrame with columns:
        date, precip_mm, CEP, MEP, DCEP, SEP,
        dry_dur, DS, CEP_ext, PRN, CEDI
    """
    df = df_all.copy().sort_values("date").reset_index(drop=True)
    df["precip_mm"] = df["precip_mm"].fillna(0.0)

    dates = pd.DatetimeIndex(df["date"])
    precip = df["precip_mm"].to_numpy(dtype=float)
    n = len(precip)

    max_ds_buf = ds_base + 500
    H = harmonic_array(max_ds_buf)

    # ── 1. CEP (DS=365 고정) ─────────────────────────────────────
    print("  [1/6] CEP 계산 (DS=365, threshold={:.0f}mm)...".format(threshold))
    cep365 = compute_cep_fixed(precip, ds_base, H, threshold, decay)

    # ── 2. MEP, σ (기후 평년값) ──────────────────────────────────
    print("  [2/6] 기후 평년값 계산 (MEP, σ_DCEP)...")
    baseline_mask = (
        (dates.year >= baseline_years[0]) & (dates.year <= baseline_years[1])
    )
    mep_by_doy, std_by_doy = calendar_stats(cep365, dates, baseline_mask)

    # ── 3. DCEP, SEP ─────────────────────────────────────────────
    print("  [3/6] DCEP, SEP 계산...")
    doy = dates.dayofyear
    mep_arr = np.array([mep_by_doy[d] for d in doy])
    std_arr = np.array([std_by_doy[d] for d in doy])

    dcep365 = cep365 - mep_arr
    sep = np.where(std_arr > 0, dcep365 / std_arr, np.nan)

    # ── 4. dry_duration ──────────────────────────────────────────
    print("  [4/6] dry_duration 계산...")
    dry_dur = np.zeros(n, dtype=int)
    for t in range(1, n):
        if not np.isnan(sep[t]) and sep[t] < 0.0:
            dry_dur[t] = dry_dur[t - 1] + 1
        else:
            dry_dur[t] = 0

    # ── 5. 확장 DS, CEP_ext ──────────────────────────────────────
    print("  [5/6] 확장 DS / CEP_ext 계산...")
    ds_arr = np.where(dry_dur > 0,
                      ds_base + dry_dur - 1,
                      ds_base).astype(int)

    cep_ext = cep365.copy()
    needs_ext = ds_arr > ds_base
    if needs_ext.any():
        cep_var = compute_cep_variable(precip, ds_arr, H, threshold, decay)
        cep_ext[needs_ext] = cep_var[needs_ext]

    # ── 6. PRN, CEDI ─────────────────────────────────────────────
    print("  [6/6] PRN 및 CEDI 산출...")
    dcep_ext = cep_ext - mep_arr
    H_ds = np.array([H[int(d)] for d in ds_arr])
    prn = np.where(H_ds > 0, dcep_ext / H_ds, np.nan)

    # σ_PRN (기준기간 기반, 달력일별)
    prn_std_by_doy = np.full(367, np.nan)
    prn_by_doy: dict[int, list] = {d: [] for d in range(1, 367)}
    for t in range(n):
        if baseline_mask[t] and not np.isnan(prn[t]):
            prn_by_doy[doy[t]].append(prn[t])
    for d in range(1, 367):
        vals = prn_by_doy[d]
        if len(vals) >= 5:
            prn_std_by_doy[d] = np.std(vals, ddof=1)

    prn_std_arr = np.array([prn_std_by_doy[d] for d in doy])
    cedi = np.where(prn_std_arr > 0, prn / prn_std_arr, np.nan)

    # ── 결과 정리 ────────────────────────────────────────────────
    result = pd.DataFrame({
        "date":      dates,
        "precip_mm": precip,
        "CEP":       cep365,
        "MEP":       mep_arr,
        "DCEP":      dcep365,
        "SEP":       sep,
        "dry_dur":   dry_dur,
        "DS":        ds_arr,
        "CEP_ext":   cep_ext,
        "PRN":       prn,
        "CEDI":      cedi,
    })

    mask_target = (
        (result["date"].dt.year >= target_years[0]) &
        (result["date"].dt.year <= target_years[1])
    )
    return result[mask_target].reset_index(drop=True)
