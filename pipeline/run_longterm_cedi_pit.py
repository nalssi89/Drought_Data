"""
CEDI / CEDI+PIT / SPI-3 / SPI-6 장기 비교 (2001-2025)
강릉(105) + 오봉저수지(가용 자료: 2021-2025)

사용법:
    cd pipeline
    python run_longterm_cedi_pit.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib as mpl
from scipy.stats import norm, gamma as gamma_dist

# ── 한글 폰트 ─────────────────────────────────────────────────────────
def _set_korean_font():
    import matplotlib.font_manager as fm
    for font in ["Apple SD Gothic Neo", "AppleGothic", "NanumGothic",
                 "Malgun Gothic", "Noto Sans CJK KR"]:
        if font in {f.name for f in fm.fontManager.ttflist}:
            mpl.rcParams["font.family"] = font
            break
    mpl.rcParams["axes.unicode_minus"] = False

_set_korean_font()

# ── 경로 / 설정 ───────────────────────────────────────────────────────
ROOT     = Path(__file__).parent.parent
PIPELINE = ROOT / "pipeline"
RAW_DIR  = PIPELINE / "data" / "raw"
OUT_DIR  = ROOT / "outputs"
OUT_DIR.mkdir(exist_ok=True)
sys.path.insert(0, str(PIPELINE))

from cedi_algorithm import (
    harmonic_array, compute_cep_fixed, calendar_stats,
    run_cedi, CEDI_THRESHOLD, CEDI_DECAY,
)
from sccedik import _fit_pearson3_lmom
from scipy.stats import pearson3

STATION   = 105
YEAR_S    = 2010
YEAR_E    = 2025
BASELINE  = (1973, YEAR_E - 1)   # 대상기간 마지막 전년도까지 롤링 기준기간


# ── 데이터 로드 ───────────────────────────────────────────────────────
def load_data(station: int) -> pd.DataFrame:
    parts = sorted(RAW_DIR.glob(f"asos_precip_{station}_*.csv"))
    parts = [p for p in parts if "_raw" not in p.name]
    frames = []
    for p in parts:
        df_p = pd.read_csv(p, parse_dates=["date"])
        if "precip_mm" not in df_p.columns:
            cand = [c for c in df_p.columns if "precip" in c.lower()]
            if cand:
                df_p = df_p.rename(columns={cand[0]: "precip_mm"})
        frames.append(df_p[["date", "precip_mm"]])
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    df["precip_mm"] = pd.to_numeric(df["precip_mm"], errors="coerce").fillna(0.0)
    return df


# ── CEDI + ±pool_half 풀링 표준화 (PIT 없음) ─────────────────────────
def run_cedi_pool(df_all, baseline_years, year_s, year_e,
                  pool_half=15, gauss_sigma=7.0):
    """
    CEDI DS 확장은 그대로 유지하되, 표준화 시 가우시안 가중 풀링을 적용.

    gauss_sigma > 0 : 거리 δ에 대해 w(δ) = exp(-δ²/2σ²) 가중 평균/표준편차
    gauss_sigma = 0 : 균등 풀링 (기존 방식)
    """
    df_full = run_cedi(df_all, baseline_years=baseline_years,
                       target_years=(baseline_years[0], year_e))

    dates    = pd.DatetimeIndex(df_full["date"])
    prn_vals = df_full["PRN"].to_numpy(dtype=float)
    doy      = dates.dayofyear
    n        = len(prn_vals)

    bl_mask  = (dates.year >= baseline_years[0]) & (dates.year <= baseline_years[1])
    tgt_mask = (dates.year >= year_s) & (dates.year <= year_e)

    weight_label = f"Gaussian σ={gauss_sigma:.0f}d" if gauss_sigma > 0 else "균등"
    n_samp = (baseline_years[1] - baseline_years[0] + 1) * (2 * pool_half + 1)
    print(f"  [CEDI-pool] PRN 풀링 표준화 (±{pool_half}d, {weight_label}, ~{n_samp} samples)...")

    # 달력일 거리 배열 (pool_half 내 각 offset의 가우시안 가중치)
    offsets = np.arange(-pool_half, pool_half + 1)
    if gauss_sigma > 0:
        gauss_w = np.exp(-offsets**2 / (2 * gauss_sigma**2))
    else:
        gauss_w = np.ones(len(offsets))

    cedi_pool = np.full(n, np.nan)

    for d in range(1, 367):
        # pool 날짜별 가중치 매핑
        pool_day_list = [(d - 1 + o) % 366 + 1 for o in offsets]
        day_to_w = {pd: w for pd, w in zip(pool_day_list, gauss_w)}

        p_mask = bl_mask & np.array([dd in day_to_w for dd in doy]) & ~np.isnan(prn_vals)
        if p_mask.sum() < 20:
            continue

        pool_vals = prn_vals[p_mask]
        w_arr = np.array([day_to_w[dd] for dd in doy[p_mask]])
        w_arr = w_arr / w_arr.sum()   # 정규화

        # 가중 평균
        mu = np.dot(w_arr, pool_vals)

        # 가중 표준편차 (reliability weights 보정)
        v1 = w_arr.sum()          # = 1.0 (정규화 후)
        v2 = (w_arr**2).sum()
        denom = v1**2 - v2
        if denom <= 0:
            continue
        sigma = np.sqrt(v1 / denom * np.dot(w_arr, (pool_vals - mu)**2))
        if sigma <= 0:
            continue

        day_mask = (doy == d) & tgt_mask & ~np.isnan(prn_vals)
        for idx in np.where(day_mask)[0]:
            cedi_pool[idx] = (prn_vals[idx] - mu) / sigma

    tgt_df = df_full[tgt_mask].copy().reset_index(drop=True)
    tgt_df["CEDI_pool"] = cedi_pool[tgt_mask]
    return tgt_df[["date", "precip_mm", "CEDI", "DS", "CEDI_pool"]]


# ── CEDI+PIT (다년) ──────────────────────────────────────────────────
def run_cedi_pit_dsext(df_all, baseline_years, year_s, year_e,
                       pool_half=15):
    """
    CEDI+PIT (DS 확장 유지).
    run_cedi()의 CEDI z-score 값 자체에 PIT를 적용한다.
    DS별 MEP_ext/σ_ext로 이미 스케일이 보정된 CEDI 값이 PIT 입력 → DS 혼합 문제 없음.
    """
    # 기준기간 포함 전체 CEDI 계산
    df_full = run_cedi(df_all, baseline_years=baseline_years,
                       target_years=(baseline_years[0], year_e))
    dates = pd.DatetimeIndex(df_full["date"])
    cedi_vals = df_full["CEDI"].to_numpy(dtype=float)
    doy = dates.dayofyear
    n = len(cedi_vals)

    bl_mask  = (dates.year >= baseline_years[0]) & (dates.year <= baseline_years[1])
    tgt_mask = (dates.year >= year_s) & (dates.year <= year_e)

    print(f"  [PIT] CEDI z-score PIT (+-{pool_half}d pool, {year_s}-{year_e})...")
    cedi_pit = np.full(n, np.nan)

    for d in range(1, 367):
        pool_days = set()
        for offset in range(-pool_half, pool_half + 1):
            pool_days.add((d - 1 + offset) % 366 + 1)

        p_mask = np.array([dd in pool_days for dd in doy]) & bl_mask & ~np.isnan(cedi_vals)
        pool_vals = cedi_vals[p_mask]
        if len(pool_vals) < 20:
            continue

        day_mask = (doy == d) & tgt_mask & ~np.isnan(cedi_vals)
        for idx in np.where(day_mask)[0]:
            v = cedi_vals[idx]
            rank = (pool_vals < v).sum() + 0.5 * (pool_vals == v).sum()
            ecdf = np.clip(rank / len(pool_vals), 0.001, 0.999)
            cedi_pit[idx] = norm.ppf(ecdf)

    tgt_df = df_full[tgt_mask].copy().reset_index(drop=True)
    tgt_df["CEDI_PIT_ext"] = cedi_pit[tgt_mask]
    return tgt_df[["date", "precip_mm", "CEDI", "DS", "CEDI_PIT_ext"]]


def run_cedi_pit_parametric(df_all, baseline_years, year_s, year_e, pool_half=0):
    """
    CEDI+PIT (파라메트릭 L-moment Pearson III).

    달력일 ±pool_half 풀링 표본에 L-moment P3를 피팅 →
    P3 CDF → Φ⁻¹(F). 경험적 방법의 플로어/실링 문제 없음.
    """
    df_full = run_cedi(df_all, baseline_years=baseline_years,
                       target_years=(baseline_years[0], year_e))
    dates     = pd.DatetimeIndex(df_full["date"])
    cedi_vals = df_full["CEDI"].to_numpy(dtype=float)
    doy       = dates.dayofyear
    n         = len(cedi_vals)

    bl_mask  = (dates.year >= baseline_years[0]) & (dates.year <= baseline_years[1])
    tgt_mask = (dates.year >= year_s) & (dates.year <= year_e)

    n_samples = (BASELINE[1] - BASELINE[0] + 1) * (2 * pool_half + 1)
    print(f"  [PIT-P3] L-mom P3 parametric PIT (pool=±{pool_half}d, ~{n_samples} samples, {year_s}-{year_e})...")
    cedi_pit = np.full(n, np.nan)

    for d in range(1, 367):
        pool_days = set((d - 1 + o) % 366 + 1 for o in range(-pool_half, pool_half + 1))
        p_mask    = bl_mask & np.array([dd in pool_days for dd in doy]) & ~np.isnan(cedi_vals)
        ref_vals  = cedi_vals[p_mask]
        if len(ref_vals) < 10:
            continue

        try:
            skew, loc, scale = _fit_pearson3_lmom(ref_vals)
            day_mask = (doy == d) & tgt_mask & ~np.isnan(cedi_vals)
            for idx in np.where(day_mask)[0]:
                prob = pearson3.cdf(cedi_vals[idx], skew, loc=loc, scale=scale)
                cedi_pit[idx] = norm.ppf(np.clip(prob, 1e-6, 1 - 1e-6))
        except Exception:
            continue

    tgt_df = df_full[tgt_mask].copy().reset_index(drop=True)
    tgt_df["CEDI_PIT_P3"] = cedi_pit[tgt_mask]
    return tgt_df[["date", "precip_mm", "CEDI", "DS", "CEDI_PIT_P3"]]


def run_cedi_pit_multi(df_all, baseline_years, year_s, year_e,
                       ds=365, threshold=CEDI_THRESHOLD,
                       decay=CEDI_DECAY, pool_half=15):
    df = df_all.copy().sort_values("date").reset_index(drop=True)
    df["precip_mm"] = df["precip_mm"].fillna(0.0)
    dates = pd.DatetimeIndex(df["date"])
    precip = df["precip_mm"].to_numpy(dtype=float)
    n = len(precip)

    H = harmonic_array(ds + 10)

    print("  [1/3] CEP (DS=365)...")
    cep = compute_cep_fixed(precip, ds, H, threshold, decay)

    print("  [2/3] MEP + DCEP...")
    bl_mask = (dates.year >= baseline_years[0]) & (dates.year <= baseline_years[1])
    mep_by_doy, _ = calendar_stats(cep, dates, bl_mask)
    doy = dates.dayofyear
    mep_arr = np.array([mep_by_doy[d] for d in doy])
    dcep = cep - mep_arr

    print(f"  [3/3] PIT (+-{pool_half}d pool, {year_s}-{year_e})...")
    cedi_pit = np.full(n, np.nan)
    target_mask = (dates.year >= year_s) & (dates.year <= year_e)

    for d in range(1, 367):
        pool_days = set()
        for offset in range(-pool_half, pool_half + 1):
            pool_days.add((d - 1 + offset) % 366 + 1)

        p_mask = np.array([dd in pool_days for dd in doy]) & bl_mask & ~np.isnan(dcep)
        pool_vals = dcep[p_mask]
        if len(pool_vals) < 20:
            continue

        day_mask = (doy == d) & target_mask & ~np.isnan(dcep)
        for idx in np.where(day_mask)[0]:
            v = dcep[idx]
            rank = (pool_vals < v).sum() + 0.5 * (pool_vals == v).sum()
            ecdf = np.clip(rank / len(pool_vals), 0.001, 0.999)
            cedi_pit[idx] = norm.ppf(ecdf)

    result = pd.DataFrame({
        "date": dates[target_mask],
        "precip_mm": precip[target_mask],
        "CEDI_PIT": cedi_pit[target_mask],
    }).reset_index(drop=True)
    return result


# ── SPI 일단위 (n개월 ≈ n×30일 롤링합 + 달력일별 감마피팅 + PIT) ────
def compute_spi_daily(df_all, scale_months, baseline_years, year_s, year_e,
                      pool_half=15):
    """
    일단위 SPI: n개월치 일수(scale_months×30)를 롤링창으로 사용.
    각 달력일의 기준기간 롤링합에 감마분포 피팅 → PIT.
    """
    scale_days = scale_months * 30

    df = df_all.copy().sort_values("date").reset_index(drop=True)
    df["precip_mm"] = df["precip_mm"].fillna(0.0)
    dates = pd.DatetimeIndex(df["date"])
    precip = df["precip_mm"].to_numpy(dtype=float)
    n = len(precip)

    # 롤링 누적합
    rolling_sum = np.full(n, np.nan)
    for i in range(scale_days - 1, n):
        rolling_sum[i] = precip[i - scale_days + 1 : i + 1].sum()

    doy = dates.dayofyear
    bl_mask  = (dates.year >= baseline_years[0]) & (dates.year <= baseline_years[1])
    tgt_mask = (dates.year >= year_s) & (dates.year <= year_e)

    spi = np.full(n, np.nan)

    for d in range(1, 367):
        # ±pool_half 달력일 풀링
        pool_days = set()
        for offset in range(-pool_half, pool_half + 1):
            pool_days.add((d - 1 + offset) % 366 + 1)

        p_mask = np.array([dd in pool_days for dd in doy]) & bl_mask & ~np.isnan(rolling_sum)
        ref_all = rolling_sum[p_mask]
        if len(ref_all) < 10:
            continue

        ref_pos = ref_all[ref_all > 0]
        q = (ref_all == 0).sum() / len(ref_all)  # P(X=0)

        # 감마 피팅
        try:
            a, _, sc = gamma_dist.fit(ref_pos, floc=0)
        except Exception:
            continue

        # 대상기간 해당 doy
        day_tgt = (doy == d) & tgt_mask & ~np.isnan(rolling_sum)
        for idx in np.where(day_tgt)[0]:
            v = rolling_sum[idx]
            if v == 0:
                prob = q
            else:
                prob = q + (1 - q) * gamma_dist.cdf(v, a, loc=0, scale=sc)
            spi[idx] = norm.ppf(np.clip(prob, 0.001, 0.999))

    result = pd.DataFrame({
        "date": dates[tgt_mask],
        "SPI":  spi[tgt_mask],
    }).reset_index(drop=True)
    return result


# ── 플롯 ──────────────────────────────────────────────────────────────
def plot_longterm(df_cedi, df_cedi_pool15, df_cedi_pool7, df_pit15, df_spi3, df_spi6, out_path):
    stn_name = "강릉"

    # 저수율
    cands = sorted(OUT_DIR.glob("저수율_강릉오봉_*.csv"))
    df_res = None
    if cands:
        df_r = pd.read_csv(cands[-1], parse_dates=["date"])
        df_r = df_r[(df_r["date"].dt.year >= YEAR_S) &
                     (df_r["date"].dt.year <= YEAR_E)].reset_index(drop=True)
        if len(df_r) > 0:
            df_res = df_r

    x_start = pd.Timestamp(f"{YEAR_S}-01-01")
    x_end   = pd.Timestamp(f"{YEAR_E}-12-31")

    FS_TITLE  = 13
    FS_LABEL  = 12
    FS_TICK   = 10
    FS_LEGEND = 10
    FS_XTICK  = 9

    fig, axes = plt.subplots(7, 1, figsize=(22, 28), sharex=False,
                             gridspec_kw={"height_ratios": [1, 2, 2, 2, 2, 2, 2]})
    fig.suptitle(
        f"{stn_name}({STATION})  {YEAR_S}-{YEAR_E}\n"
        f"CEDI / CEDI+PIT(±15d) / SPI  |  baseline: {BASELINE[0]}-{BASELINE[1]} (rolling)",
        fontsize=15, y=1.005
    )

    def _month_fmt(x, pos):
        dt = mdates.num2date(x)
        return f"{dt.month}\n{dt.year}" if dt.month == 1 else str(dt.month)

    def _set_xaxis(ax):
        ax.set_xlim(x_start, x_end)
        ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=range(1, 13, 2)))
        ax.xaxis.set_major_formatter(mpl.ticker.FuncFormatter(_month_fmt))
        ax.tick_params(axis="x", which="major", labelsize=FS_XTICK, rotation=0)
        ax.grid(axis="x", which="major", color="gray", lw=0.3, alpha=0.4)

    # ── 패널 0: 강수 + 저수율 ────────────────────────────────────────
    ax0 = axes[0]
    ax0.bar(df_cedi["date"], df_cedi["precip_mm"],
            color="steelblue", alpha=0.6, width=1.0, label="precip")
    p_max = max(df_cedi["precip_mm"].max() * 1.1, 10)
    ax0.set_ylim(p_max, 0)
    ax0.set_ylabel("precip (mm)", fontsize=FS_LABEL, color="steelblue")
    ax0.tick_params(axis="y", labelcolor="steelblue", labelsize=FS_TICK)
    if df_res is not None:
        ax0r = ax0.twinx()
        ax0r.plot(df_res["date"], df_res["storage_rate"],
                  color="#c0392b", lw=1.0, label="Obong reservoir (%)")
        ax0r.set_ylim(0, 110)
        ax0r.set_ylabel("storage %", fontsize=FS_LABEL, color="#c0392b")
        ax0r.tick_params(axis="y", labelcolor="#c0392b", labelsize=FS_TICK)
        h1, l1 = ax0.get_legend_handles_labels()
        h2, l2 = ax0r.get_legend_handles_labels()
        ax0.legend(h1 + h2, l1 + l2, fontsize=FS_LEGEND, loc="upper right")
    else:
        ax0.legend(fontsize=FS_LEGEND, loc="upper right")
    ax0.set_title("precip + Obong reservoir (2021-)", fontsize=FS_TITLE, loc="left")
    _set_xaxis(ax0)

    # ── 패널 1: CEDI ─────────────────────────────────────────────────
    ax1 = axes[1]
    _draw(ax1, df_cedi["date"], df_cedi["CEDI"].values, "#1a6faf", "CEDI")
    ax1.set_title("CEDI -- Kim 2009 (DS extend + z-score)", fontsize=FS_TITLE, loc="left")
    ax1.set_ylabel("CEDI", fontsize=FS_LABEL)
    _set_xaxis(ax1)

    # ── 패널 2: CEDI ±15d 풀링 표준화 ────────────────────────────────
    ax2 = axes[2]
    n_samp15 = (BASELINE[1] - BASELINE[0] + 1) * 31
    _draw(ax2, df_cedi_pool15["date"], df_cedi_pool15["CEDI_pool"].values, "#8b6914", "CEDI+pool±15d")
    ax2.set_title(f"CEDI+pool±15d -- DS extend + pooled z-score  (±15d, ~{n_samp15} samples)",
                  fontsize=FS_TITLE, loc="left")
    ax2.set_ylabel("CEDI+pool±15d", fontsize=FS_LABEL)
    _set_xaxis(ax2)

    # ── 패널 3: CEDI ±7d 풀링 표준화 ─────────────────────────────────
    ax3 = axes[3]
    n_samp7 = (BASELINE[1] - BASELINE[0] + 1) * 15
    _draw(ax3, df_cedi_pool7["date"], df_cedi_pool7["CEDI_pool"].values, "#b05000", "CEDI+pool±7d")
    ax3.set_title(f"CEDI+pool±7d -- DS extend + pooled z-score  (±7d, ~{n_samp7} samples)",
                  fontsize=FS_TITLE, loc="left")
    ax3.set_ylabel("CEDI+pool±7d", fontsize=FS_LABEL)
    _set_xaxis(ax3)

    # ── 패널 4: CEDI+PIT empirical ±15d ──────────────────────────────
    ax4 = axes[4]
    _draw(ax4, df_pit15["date"], df_pit15["CEDI_PIT_ext"].values, "#228b22", "CEDI+PIT")
    ax4.set_title(f"CEDI+PIT -- DS extend + empirical PIT  (pool=±15d, ~{n_samp15} samples)",
                  fontsize=FS_TITLE, loc="left")
    ax4.set_ylabel("CEDI+PIT", fontsize=FS_LABEL)
    _set_xaxis(ax4)

    # ── 패널 5: SPI-3 ────────────────────────────────────────────────
    ax5 = axes[5]
    spi3_v = df_spi3["SPI"].values
    ax5.plot(df_spi3["date"], spi3_v, color="#9b30d0", lw=0.8, label="SPI-3", alpha=0.9)
    ax5.fill_between(df_spi3["date"], np.minimum(spi3_v, -1.0), -1.0,
                     where=spi3_v < -1.0, color="#FFA500", alpha=0.15)
    ax5.fill_between(df_spi3["date"], np.minimum(spi3_v, -2.0), -2.0,
                     where=spi3_v < -2.0, color="#CC0000", alpha=0.25)
    ax5.axhline(0, color="gray", lw=0.4, ls="--")
    ax5.axhline(-1.0, color="#FFA500", lw=0.5, ls=":")
    ax5.axhline(-2.0, color="#CC0000", lw=0.5, ls=":")
    ax5.set_ylim(-4.5, 3.5)
    ax5.legend(fontsize=FS_LEGEND, loc="lower right")
    ax5.set_title("SPI-3 (daily rolling + gamma PIT, pool=±15d)",
                  fontsize=FS_TITLE, loc="left")
    ax5.set_ylabel("SPI-3", fontsize=FS_LABEL)
    _set_xaxis(ax5)

    # ── 패널 6: SPI-6 ────────────────────────────────────────────────
    ax6 = axes[6]
    spi6_v = df_spi6["SPI"].values
    ax6.plot(df_spi6["date"], spi6_v, color="#e07b00", lw=0.8, label="SPI-6", alpha=0.9)
    ax6.fill_between(df_spi6["date"], np.minimum(spi6_v, -1.0), -1.0,
                     where=spi6_v < -1.0, color="#FFA500", alpha=0.15)
    ax6.fill_between(df_spi6["date"], np.minimum(spi6_v, -2.0), -2.0,
                     where=spi6_v < -2.0, color="#CC0000", alpha=0.25)
    ax6.axhline(0, color="gray", lw=0.4, ls="--")
    ax6.axhline(-1.0, color="#FFA500", lw=0.5, ls=":")
    ax6.axhline(-2.0, color="#CC0000", lw=0.5, ls=":")
    ax6.set_ylim(-4.5, 3.5)
    ax6.legend(fontsize=FS_LEGEND, loc="lower right")
    ax6.set_title("SPI-6 (daily rolling + gamma PIT, pool=±15d)",
                  fontsize=FS_TITLE, loc="left")
    ax6.set_ylabel("SPI-6", fontsize=FS_LABEL)
    _set_xaxis(ax6)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  plot: {out_path.name}")


def _draw(ax, dates, vals, color, label):
    ax.fill_between(dates, np.minimum(vals, -2.0), -2.0,
                    where=vals < -2.0, color="#CC0000", alpha=0.30)
    ax.fill_between(dates, np.clip(vals, -2.0, -1.0), -1.0,
                    where=vals < -1.0, color="#FFA500", alpha=0.15)
    ax.plot(dates, vals, color=color, lw=0.6, label=label, alpha=0.9)
    ax.axhline(0, color="gray", lw=0.4, ls="--")
    ax.axhline(-1.0, color="#FFA500", lw=0.5, ls=":")
    ax.axhline(-2.0, color="#CC0000", lw=0.5, ls=":")
    ax.set_ylim(-4.5, 3.5)
    ax.tick_params(axis="y", labelsize=10)
    ax.legend(fontsize=10, loc="lower right")


# ── 메인 ──────────────────────────────────────────────────────────────
def main():
    tag = f"강릉{STATION}_{YEAR_S}-{YEAR_E}"

    print(f"\n{'='*55}")
    print(f"  장기비교: 강릉({STATION})  {YEAR_S}-{YEAR_E}")
    print(f"{'='*55}\n")

    df = load_data(STATION)

    print("1) CEDI (Kim 2009)")
    df_cedi = run_cedi(df, baseline_years=BASELINE,
                       target_years=(YEAR_S, YEAR_E))

    print("\n2) CEDI+pool±15d (풀링 표준화)")
    df_cedi_pool15 = run_cedi_pool(df, BASELINE, YEAR_S, YEAR_E, pool_half=15, gauss_sigma=0)

    print("\n3) CEDI+pool±7d (풀링 표준화)")
    df_cedi_pool7 = run_cedi_pool(df, BASELINE, YEAR_S, YEAR_E, pool_half=7, gauss_sigma=0)

    print("\n4) CEDI+PIT empirical (pool=±15d)")
    df_pit_ext15 = run_cedi_pit_dsext(df, BASELINE, YEAR_S, YEAR_E, pool_half=15)

    print("\n5) SPI-3")
    df_spi3 = compute_spi_daily(df, 3, BASELINE, YEAR_S, YEAR_E)

    print("6) SPI-6")
    df_spi6 = compute_spi_daily(df, 6, BASELINE, YEAR_S, YEAR_E)

    # CSV
    csv_path = OUT_DIR / f"CEDI_PIT_longterm_{tag}.csv"
    merged = df_cedi[["date", "precip_mm", "CEDI"]].merge(
        df_cedi_pool15[["date", "CEDI_pool"]].rename(columns={"CEDI_pool": "CEDI_pool15d"}),
        on="date", how="left"
    ).merge(
        df_cedi_pool7[["date", "CEDI_pool"]].rename(columns={"CEDI_pool": "CEDI_pool7d"}),
        on="date", how="left"
    ).merge(
        df_pit_ext15[["date", "CEDI_PIT_ext"]].rename(columns={"CEDI_PIT_ext": "CEDI_PIT_15d"}),
        on="date", how="left"
    ).merge(
        df_spi3.rename(columns={"SPI": "SPI3"}), on="date", how="left"
    ).merge(
        df_spi6.rename(columns={"SPI": "SPI6"}), on="date", how="left"
    )
    merged.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n  csv: {csv_path.name}")

    # 플롯
    plot_longterm(
        df_cedi, df_cedi_pool15, df_cedi_pool7, df_pit_ext15, df_spi3, df_spi6,
        OUT_DIR / f"CEDI_PIT_SPI_longterm_{tag}.png"
    )

    print(f"  output: {OUT_DIR}")


if __name__ == "__main__":
    main()
