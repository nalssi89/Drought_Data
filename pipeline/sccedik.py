"""
scCEDI-K v2 — 3회 반복검증 확정 알고리즘 구현

알고리즘 순서 (종합검토 STEP 1-5):
  STEP 1. 입력: 일강수량 P(t)
  STEP 2. 집중호우 유출보정 → Pc(t)
  STEP 3. 보정 유효강수량 CEP (원본 식2, DS=365 고정)
  STEP 4. 고정 기준기간 기후학 + L-moment Pearson III 표준화 → scCEDI-K
  STEP 5. 보조지표 (PRN 역산보정, 지속일수, 평년비)

표준화 방법:
  - ±15일 달력일 풀링 (기준기간 × 31일 ≈ 930표본)
  - L-moment 기반 Pearson Type III 분포 피팅 (Hosking & Wallis, 1997)
  - 확률적분변환(PIT) + 정규역변환 Φ⁻¹(F)
  - 꼬리 외삽 자동 처리 (임의적 클리핑/soft-cap 불필요)
"""

import numpy as np
import pandas as pd
from scipy import special
from scipy.stats import norm, pearson3 as _p3dist


# ═══════════════════════════════════════════════════════════════════
# STEP 2. 유출보정
# ═══════════════════════════════════════════════════════════════════


def runoff_correct_alpha(
    precip: np.ndarray, threshold: float, alpha: float = 0.2
) -> np.ndarray:
    """
    α 방식 유출보정 (Kim 2009 계열)
    Pc(t) = min(P, Th) + α × max(P - Th, 0)
    """
    base = np.minimum(precip, threshold)
    excess = np.maximum(precip - threshold, 0)
    return base + alpha * excess


def runoff_correct_tau(
    precip: np.ndarray, threshold: float, tau: float = 4.0
) -> np.ndarray:
    """
    τ_fast 감쇠 방식 유출보정 (ACE-EDI/E-EDI 계열)
    초과분이 며칠에 걸쳐 점진적으로 소실.
    Pc(t) = P_base(t) + P_excess(t)·exp(0)  (당일)
    과거 lag d에서의 초과분 기여: P_excess·exp(-d/τ)
    → EP 계산 시 가중치에 추가 감쇠 적용

    단순 구현: 당일 보정만 적용 (EP 내부에서의 감쇠는 별도 확장 필요)
    """
    base = np.minimum(precip, threshold)
    excess = np.maximum(precip - threshold, 0)
    # 당일: 초과분 100% 인정, EP 가중에서 tau 감쇠가 적용되므로
    # 여기서는 base만 사용하고 excess는 EP 계산에서 별도 처리
    # Phase 1 단순 구현: α≈exp(-1/τ) 근사로 당일 보정
    alpha_approx = np.exp(-1.0 / tau)
    return base + alpha_approx * excess


def compute_threshold(
    precip: np.ndarray, fixed_min: float = 80.0, percentile: float = 95.0
) -> float:
    """
    지점별 동적 임계값: max(80mm, 우일 강수 P95)
    """
    wet_days = precip[precip > 0]
    if len(wet_days) < 30:
        return fixed_min
    p_val = np.percentile(wet_days, percentile)
    return max(fixed_min, p_val)


# ═══════════════════════════════════════════════════════════════════
# STEP 3. 보정 유효강수량 (CEP)
# ═══════════════════════════════════════════════════════════════════


def harmonic_array(n_max: int) -> np.ndarray:
    """H[k] = 1 + 1/2 + ... + 1/k, H[0] = 0"""
    H = np.zeros(n_max + 1)
    for k in range(1, n_max + 1):
        H[k] = H[k - 1] + 1.0 / k
    return H


def compute_cep(precip_corrected: np.ndarray, ds: int, H: np.ndarray) -> np.ndarray:
    """
    원본 EDI 식(2) 조화가중 CEP, DS=365 고정.

    CEP(t) = Σ(m=1→DS) Pc(t-m+1) · [H(DS) - H(m-1)]
    P_1=오늘(가장 큰 가중치), P_DS=DS-1일 전(가장 작은 가중치)
    """
    n = len(precip_corrected)
    w = H[ds] - H[:ds]  # w[0]=H(DS), w[DS-1]=1/DS
    cep = np.full(n, np.nan)
    for t in range(ds - 1, n):
        cep[t] = np.dot(precip_corrected[t - ds + 1 : t + 1][::-1], w)
    return cep


# ═══════════════════════════════════════════════════════════════════
# STEP 4. 기후학 + L-moment Pearson III 표준화
# ═══════════════════════════════════════════════════════════════════


def _fit_pearson3_lmom(data: np.ndarray) -> tuple:
    """
    L-moment 기반 Pearson Type III 파라미터 추정.

    Hosking & Wallis (1997) Regional Frequency Analysis,
    Cambridge University Press, Appendix A3.

    Parameters
    ----------
    data : 풀링된 DCEP 표본 (비정렬)

    Returns
    -------
    (skew, loc, scale) : scipy.stats.pearson3 파라미터
        skew  — 분포의 모멘트 왜도 γ₁ = 2/√α × sign(τ₃)
        loc   — 분포의 평균 (L-mean = 산술평균)
        scale — 분포의 표준편차 (L-scale 기반 추정)

    Notes
    -----
    L-moments는 MLE보다 이상치에 강건하며 소표본 꼬리 추정에 유리함.
    λ₂ = σ × Γ(α+½) / (√(πα) × Γ(α))  에서 σ를 역산.
    """
    x = np.sort(data)
    n = len(x)

    # 비편향 확률가중모멘트 (Probability Weighted Moments)
    i = np.arange(1, n + 1, dtype=float)
    b0 = np.mean(x)
    b1 = np.dot((i - 1) / (n - 1), x) / n
    b2 = np.dot((i - 1) * (i - 2) / ((n - 1) * (n - 2)), x) / n

    # L-모멘트
    l1 = b0                           # λ₁: L-mean
    l2 = 2.0 * b1 - b0                # λ₂: L-scale
    l3 = 6.0 * b2 - 6.0 * b1 + b0    # λ₃
    if abs(l2) < 1e-10:
        return 0.0, l1, 1.0
    tau3 = np.clip(l3 / l2, -0.9999, 0.9999)  # τ₃: L-왜도

    t3a = abs(tau3)

    if t3a < 1e-4:
        # 정규분포에 수렴: α → ∞, σ = λ₂√π
        return 0.0, l1, float(l2 * np.sqrt(np.pi))

    # Hosking & Wallis (1997) Table A3: τ₃ → 감마 형상 α 수치 근사
    if t3a <= 1.0 / 3.0:
        z = 3.0 * np.pi * t3a ** 2
        alpha = (1.0 + 0.2906 * z) / (z * (1.0 + z * (-0.1882 + z * 0.0442)))
    else:
        z = 1.0 - t3a
        alpha = (0.36067 / z - 0.5967 + 0.25361 * z) / (
            1.0 + z * (-2.78861 + z * (2.56096 - 0.77045 * z))
        )
    alpha = max(alpha, 0.01)

    # 모멘트 왜도 γ₁ = 2/√α (scipy pearson3 skew 파라미터)
    gamma1 = float(np.sign(tau3) * 2.0 / np.sqrt(alpha))

    # L-scale → 표준편차 변환 (log-gamma로 대형 alpha overflow 방지)
    # λ₂ = σ × Γ(α+½) / (√(πα) × Γ(α))  →  σ = λ₂ × √(πα) × Γ(α)/Γ(α+½)
    # log(σ) = log(λ₂) + ½log(πα) + logΓ(α) - logΓ(α+½)
    log_scale = (np.log(abs(l2)) + 0.5 * (np.log(np.pi) + np.log(alpha))
                 + special.gammaln(alpha) - special.gammaln(alpha + 0.5))
    scale = float(np.exp(log_scale))
    scale = max(scale, 1e-6)

    return gamma1, float(l1), scale


def rolling_mean_cep(
    cep: np.ndarray,
    dates: pd.DatetimeIndex,
    target_year: int,
    window: int = 30,
    smooth: int = 5,
    fixed_baseline: tuple | None = None,
) -> np.ndarray:
    """
    Rolling 30년 달력일별 CEP 기후평균 (5일 원형 평활).
    target_year 직전 window년 사용.
    fixed_baseline=(start, end) 지정 시 고정 기준기간 사용 (rolling 무시).
    Returns: array(367,) — index 1~366이 doy별 평균.
    """
    if fixed_baseline is not None:
        start_year, end_year = fixed_baseline
    else:
        end_year = target_year - 1
        start_year = end_year - window + 1

    mask = (dates.year >= start_year) & (dates.year <= end_year) & (~np.isnan(cep))
    doys = dates.dayofyear

    mean_raw = np.full(367, np.nan)
    for d in range(1, 367):
        vals = cep[mask & (doys == d)]
        if len(vals) >= 5:
            mean_raw[d] = vals.mean()

    # 5일 원형 평활 (366일 기준)
    mean_sm = np.full(367, np.nan)
    half = smooth // 2
    for d in range(1, 367):
        indices = [(d - 1 + offset) % 366 + 1 for offset in range(-half, half + 1)]
        vals = [mean_raw[i] for i in indices if not np.isnan(mean_raw[i])]
        mean_sm[d] = np.mean(vals) if vals else np.nan

    return mean_sm


def lmom_pearson3_standardize(
    dcep: np.ndarray,
    dates: pd.DatetimeIndex,
    target_year: int,
    window: int = 30,
    pool_half: int = 15,
    fixed_baseline: tuple | None = None,
) -> np.ndarray:
    """
    L-moment Pearson III 기반 표준화 (확률적분변환).

    각 달력일 ±pool_half일 창에서 기준기간의 DCEP를 풀링,
    Pearson Type III 분포를 L-moment로 피팅한 뒤
    PIT(확률적분변환) → Φ⁻¹(F) = scCEDI-K 를 산출.

    Parameters
    ----------
    dcep           : 전체 기간 DCEP 배열
    dates          : 전체 기간 날짜 인덱스
    target_year    : 산출 대상 연도
    window         : Rolling 기준기간 연 수 (fixed_baseline 미지정 시)
    pool_half      : ±풀링 반창 (일)
    fixed_baseline : (start_year, end_year) 고정 기준기간

    References
    ----------
    Hosking & Wallis (1997) Regional Frequency Analysis,
        Cambridge University Press.
    McKee et al. (1993) The relationship of drought frequency and
        duration to time scales, 8th AMS Conf. Applied Climatology.
    """
    if fixed_baseline is not None:
        start_year, end_year = fixed_baseline
    else:
        end_year = target_year - 1
        start_year = end_year - window + 1

    hist_mask = (dates.year >= start_year) & (dates.year <= end_year)
    hist_doys = dates.dayofyear[hist_mask]
    hist_dcep = dcep[hist_mask]

    valid_hist = ~np.isnan(hist_dcep)
    hist_doys_valid = hist_doys[valid_hist]
    hist_dcep_valid = hist_dcep[valid_hist]

    target_mask = dates.year == target_year
    result = np.full(len(dates), np.nan)

    for idx in np.where(target_mask)[0]:
        if np.isnan(dcep[idx]):
            continue
        doy = dates[idx].dayofyear
        dcep_val = dcep[idx]

        # ±pool_half 일 풀링 (달력일 원형)
        pool_mask = np.zeros(len(hist_doys_valid), dtype=bool)
        for offset in range(-pool_half, pool_half + 1):
            target_doy = (doy - 1 + offset) % 366 + 1
            pool_mask |= hist_doys_valid == target_doy

        pool_vals = hist_dcep_valid[pool_mask]
        if len(pool_vals) < 30:
            continue

        # L-moment Pearson III 피팅 → 확률적분변환(PIT)
        skew_p3, loc_p3, scale_p3 = _fit_pearson3_lmom(pool_vals)
        F = _p3dist.cdf(dcep_val, skew_p3, loc=loc_p3, scale=scale_p3)

        # 수치 안정성 클리핑 (F=0 또는 1이면 Φ⁻¹ 발산)
        F = np.clip(F, 1e-6, 1.0 - 1e-6)

        result[idx] = norm.ppf(F)

    return result


# ═══════════════════════════════════════════════════════════════════
# STEP 5. 보조지표
# ═══════════════════════════════════════════════════════════════════


def compute_prn(
    dcep: np.ndarray, ds_arr: np.ndarray, H: np.ndarray, retention_rate: float = 1.0
) -> np.ndarray:
    """
    PRN = -DCEP / H(DS), 유출보정 역산 적용.
    PRN_actual = PRN_raw / retention_rate
    retention_rate = 1 - runoff_fraction (유출보정으로 깎이는 비율)
    """
    prn_raw = np.full(len(dcep), np.nan)
    for t in range(len(dcep)):
        if not np.isnan(dcep[t]) and int(ds_arr[t]) <= len(H) - 1:
            h = H[int(ds_arr[t])]
            if h > 0:
                prn_raw[t] = -dcep[t] / h

    if retention_rate > 0 and retention_rate != 1.0:
        return prn_raw / retention_rate
    return prn_raw


def compute_precip_normal_ratio(
    precip: np.ndarray,
    dates: pd.DatetimeIndex,
    target_year: int,
    days: int = 90,
    window: int = 30,
) -> np.ndarray:
    """최근 N일 강수 평년비 (%)"""
    end_year = target_year - 1
    start_year = end_year - window + 1

    # 달력일별 N일 누적 기후평균
    hist_mask = (dates.year >= start_year) & (dates.year <= end_year)
    n = len(precip)
    cumsum = np.zeros(n + 1)
    cumsum[1:] = np.cumsum(np.nan_to_num(precip))

    ratio = np.full(n, np.nan)
    target_mask = dates.year == target_year

    # 기후 평균: 달력일별 N일 합계의 30년 평균
    doys = dates.dayofyear
    clim = {}
    for t in np.where(hist_mask)[0]:
        if t < days:
            continue
        s = cumsum[t + 1] - cumsum[t - days + 1]
        d = doys[t]
        clim.setdefault(d, []).append(s)
    mean_clim = {d: np.mean(v) for d, v in clim.items() if len(v) >= 5}

    for t in np.where(target_mask)[0]:
        if t < days:
            continue
        s = cumsum[t + 1] - cumsum[t - days + 1]
        d = doys[t]
        if d in mean_clim and mean_clim[d] > 0:
            ratio[t] = s / mean_clim[d] * 100
    return ratio


# ═══════════════════════════════════════════════════════════════════
# 메인 파이프라인
# ═══════════════════════════════════════════════════════════════════


def run_sccedik(
    df_all: pd.DataFrame,
    target_year: int = 2025,
    baseline_window: int = 30,
    ds_base: int = 365,
    runoff_method: str = "alpha",
    alpha: float = 0.2,
    tau: float = 4.0,
    threshold_pct: float = 95.0,
    fixed_baseline: tuple | None = None,
) -> pd.DataFrame:
    """
    scCEDI-K v2 전체 파이프라인.

    Parameters
    ----------
    df_all           : date, precip_mm 컬럼
    target_year      : 산출 대상 연도
    baseline_window  : Rolling 기후학 기간 (년)
    ds_base          : 기본 합산기간
    runoff_method    : "alpha" | "tau" | "none"
    alpha            : α 방식 계수
    tau              : τ_fast 감쇠 시간 (일)
    threshold_pct    : 우일 강수 임계 백분위
    fixed_baseline   : (start_year, end_year) 고정 기준기간, None이면 rolling 사용

    Returns
    -------
    DataFrame (target_year 기간)
    """
    df = df_all.copy().sort_values("date").reset_index(drop=True)
    df["precip_mm"] = df["precip_mm"].fillna(0.0)
    dates = pd.DatetimeIndex(df["date"])
    precip = df["precip_mm"].to_numpy(dtype=float)
    n = len(precip)

    # ── STEP 2: 유출보정 ─────────────────────────────────────────
    print("  [STEP 2] 유출보정...")
    if fixed_baseline is not None:
        start_base, end_base = fixed_baseline
        print(f"    기준기간: 고정 {start_base}-{end_base}")
    else:
        end_base = target_year - 1
        start_base = end_base - baseline_window + 1
        print(f"    기준기간: Rolling {start_base}-{end_base}")
    base_mask = (dates.year >= start_base) & (dates.year <= end_base)
    threshold = compute_threshold(precip[base_mask], 80.0, threshold_pct)
    print(f"    임계값: {threshold:.1f} mm  (max(80, P{threshold_pct:.0f}))")

    if runoff_method == "alpha":
        pc = runoff_correct_alpha(precip, threshold, alpha)
        retention = alpha  # 초과분 중 alpha 비율만 유효
        print(f"    방식: α={alpha}")
    elif runoff_method == "tau":
        pc = runoff_correct_tau(precip, threshold, tau)
        retention = np.exp(-1.0 / tau)
        print(f"    방식: τ_fast={tau}일")
    else:
        pc = precip.copy()
        retention = 1.0
        print("    방식: 보정 없음")

    # ── STEP 3: CEP (DS=365 고정) ────────────────────────────────
    print("  [STEP 3] CEP 계산 (DS=365)...")
    H = harmonic_array(ds_base + 600)
    cep = compute_cep(pc, ds_base, H)

    # ── STEP 4: 기후학 + L-moment Pearson III 표준화 ────────────
    print("  [STEP 4] 기후 평균 계산 + L-moment Pearson III 표준화...")
    mean_cep = rolling_mean_cep(cep, dates, target_year, baseline_window,
                                fixed_baseline=fixed_baseline)
    doys = dates.dayofyear
    mean_arr = np.array([mean_cep[d] for d in doys])
    dcep = cep - mean_arr

    sccedik = lmom_pearson3_standardize(
        dcep,
        dates,
        target_year,
        baseline_window,
        pool_half=15,
        fixed_baseline=fixed_baseline,
    )

    # ── dry_duration & DS ────────────────────────────────────────
    print("  [STEP 5] 보조지표 계산...")
    dry_dur = np.zeros(n, dtype=int)
    for t in range(1, n):
        if not np.isnan(sccedik[t]) and sccedik[t] < 0.0:
            dry_dur[t] = dry_dur[t - 1] + 1
        else:
            dry_dur[t] = 0

    ds_arr = np.where(dry_dur > 0, ds_base + dry_dur - 1, ds_base).astype(int)

    # PRN (유출보정 역산)
    # retention_rate: 초과분 중 유효하게 남는 비율
    # 단순 근사: 전체 강수 대비 보정 강수 비율의 평균
    if runoff_method != "none":
        heavy_mask = precip > threshold
        if heavy_mask.any():
            eff_retention = np.mean(pc[heavy_mask] / precip[heavy_mask])
        else:
            eff_retention = 1.0
    else:
        eff_retention = 1.0

    prn = compute_prn(dcep, ds_arr, H, eff_retention)

    # 90일 강수 평년비
    precip_ratio = compute_precip_normal_ratio(
        precip, dates, target_year, 90, baseline_window
    )

    # ── 결과 조립 ────────────────────────────────────────────────
    result = pd.DataFrame(
        {
            "date": dates,
            "precip_mm": precip,
            "precip_corrected": pc,
            "CEP": cep,
            "MEP_rolling": mean_arr,
            "DCEP": dcep,
            "scCEDI_K": sccedik,
            "dry_dur": dry_dur,
            "DS": ds_arr,
            "PRN": prn,
            "precip_ratio_90d": precip_ratio,
        }
    )

    mask_target = result["date"].dt.year == target_year
    return result[mask_target].reset_index(drop=True)
