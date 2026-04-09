"""
강릉(105) 2001~2026.03 장기 비교: 원본 EDI vs scCEDI-K v2
"""

import sys, logging
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import rcParams

rcParams["font.family"] = "AppleGothic"
rcParams["axes.unicode_minus"] = False

sys.path.insert(0, str(Path(__file__).parent))
from edi_algorithm import run_edi, harmonic_array, compute_ep_fixed, calendar_stats
from sccedik import (
    run_sccedik,
    runoff_correct_alpha,
    compute_threshold,
    compute_cep,
    rolling_mean_cep,
    nonparametric_standardize,
    compute_prn,
    harmonic_array as ha2,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).parent / "data" / "raw"
PROC_DIR = Path(__file__).parent / "data" / "processed"
PROC_DIR.mkdir(parents=True, exist_ok=True)

STN_ID = 105


def load_all() -> pd.DataFrame:
    """1970~2026.03 전체 로드"""
    frames = []
    for f in sorted(RAW_DIR.glob(f"asos_precip_{STN_ID}_*_raw.csv")):
        df = pd.read_csv(f, parse_dates=["date"])[["date", "precip_mm"]]
        frames.append(df)
    # 2025년 원본
    p25 = RAW_DIR / f"asos_precip_{STN_ID}_강릉_2025.csv"
    if p25.exists():
        frames.append(pd.read_csv(p25, parse_dates=["date"])[["date", "precip_mm"]])
    # 1990-2024 통합파일
    p_hist = RAW_DIR / f"asos_precip_{STN_ID}_1990_2024.csv"
    if p_hist.exists():
        frames.append(pd.read_csv(p_hist, parse_dates=["date"])[["date", "precip_mm"]])

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    logger.info(
        "전체: %d건 (%s ~ %s)",
        len(df),
        df["date"].min().date(),
        df["date"].max().date(),
    )
    return df


# ═════════════════════════════════════════════════════════════════
# 원본 EDI 장기 계산
# ═════════════════════════════════════════════════════════════════
def compute_edi_long(df_all, target_start, target_end, baseline=(1991, 2020)):
    """원본 EDI를 장기간 산출"""
    df = df_all.copy().sort_values("date").reset_index(drop=True)
    df["precip_mm"] = df["precip_mm"].fillna(0.0)
    dates = pd.DatetimeIndex(df["date"])
    precip = df["precip_mm"].to_numpy(dtype=float)
    n = len(precip)
    ds = 365

    H = harmonic_array(ds + 600)
    ep = compute_ep_fixed(precip, ds, H)

    baseline_mask = (dates.year >= baseline[0]) & (dates.year <= baseline[1])
    mep_by_doy, std_by_doy = calendar_stats(ep, dates, baseline_mask)

    doy = dates.dayofyear
    mep_arr = np.array([mep_by_doy[d] for d in doy])
    std_arr = np.array([std_by_doy[d] for d in doy])

    dep = ep - mep_arr
    sep = dep / std_arr

    # dry_dur & DS
    dry_dur = np.zeros(n, dtype=int)
    for t in range(1, n):
        if not np.isnan(sep[t]) and sep[t] < 0:
            dry_dur[t] = dry_dur[t - 1] + 1

    ds_arr = np.where(dry_dur > 0, ds + dry_dur - 1, ds).astype(int)

    # PRN (DS=365 고정 DEP 사용 — 검토에서 확인된 올바른 방식)
    H_ds = np.array([H[int(d)] for d in ds_arr])
    prn = np.where(H_ds > 0, dep / H_ds, np.nan)

    # σ_PRN
    prn_std_by_doy = np.full(367, np.nan)
    prn_by_doy = {d: [] for d in range(1, 367)}
    for t in range(n):
        if baseline_mask[t] and not np.isnan(prn[t]):
            prn_by_doy[doy[t]].append(prn[t])
    for d in range(1, 367):
        vals = prn_by_doy[d]
        if len(vals) >= 5:
            prn_std_by_doy[d] = np.std(vals, ddof=1)

    prn_std_arr = np.array([prn_std_by_doy[d] for d in doy])
    edi = np.where(prn_std_arr > 0, prn / prn_std_arr, np.nan)

    mask = (dates >= target_start) & (dates <= target_end)
    return pd.DataFrame({"date": dates[mask], "EDI": edi[mask]}).reset_index(drop=True)


# ═════════════════════════════════════════════════════════════════
# scCEDI-K 장기 계산
# ═════════════════════════════════════════════════════════════════
def compute_sccedik_long(
    df_all, target_start, target_end, baseline_window=30, alpha=0.2
):
    """scCEDI-K v2를 장기간 산출 — 연도별 rolling 기후학"""
    df = df_all.copy().sort_values("date").reset_index(drop=True)
    df["precip_mm"] = df["precip_mm"].fillna(0.0)
    dates = pd.DatetimeIndex(df["date"])
    precip = df["precip_mm"].to_numpy(dtype=float)
    n = len(precip)
    ds = 365

    # 유출보정
    threshold = compute_threshold(precip, 80.0, 95.0)
    pc = runoff_correct_alpha(precip, threshold, alpha)

    # CEP (DS=365 고정)
    H = ha2(ds + 600)
    cep = compute_cep(pc, ds, H)

    # 연도별 rolling 기후학 + 비모수 표준화
    target_years = range(
        pd.Timestamp(target_start).year, pd.Timestamp(target_end).year + 1
    )

    sccedik_full = np.full(n, np.nan)

    for yr in target_years:
        # rolling mean
        mean_cep = rolling_mean_cep(cep, dates, yr, baseline_window)
        doys = dates.dayofyear
        mean_arr = np.array([mean_cep[d] for d in doys])
        dcep = cep - mean_arr

        # 비모수 표준화 (이 연도만)
        sc = nonparametric_standardize(
            dcep, dates, cep, dates, yr, baseline_window, pool_half=15
        )
        yr_mask = dates.year == yr
        sccedik_full[yr_mask] = sc[yr_mask]

    # dry_dur
    dry_dur = np.zeros(n, dtype=int)
    for t in range(1, n):
        if not np.isnan(sccedik_full[t]) and sccedik_full[t] < 0:
            dry_dur[t] = dry_dur[t - 1] + 1
    ds_arr = np.where(dry_dur > 0, ds + dry_dur - 1, ds).astype(int)

    mask = (dates >= target_start) & (dates <= target_end)
    return pd.DataFrame(
        {
            "date": dates[mask],
            "scCEDI_K": sccedik_full[mask],
            "dry_dur": dry_dur[mask],
        }
    ).reset_index(drop=True)


# ═════════════════════════════════════════════════════════════════
# 시각화
# ═════════════════════════════════════════════════════════════════
def plot_longterm(edi_df, sc_df):
    dates_e = pd.DatetimeIndex(edi_df["date"])
    dates_s = pd.DatetimeIndex(sc_df["date"])
    edi = edi_df["EDI"].to_numpy()
    sc = sc_df["scCEDI_K"].to_numpy()

    fig, axes = plt.subplots(
        3,
        1,
        figsize=(20, 13),
        gridspec_kw={"height_ratios": [1.5, 1.5, 0.8], "hspace": 0.35},
    )
    fig.suptitle(
        "강릉(105) 2001~2026.03  원본 EDI vs scCEDI-K v2 장기 비교",
        fontsize=15,
        fontweight="bold",
        y=0.995,
    )

    yr_loc = mdates.YearLocator()
    yr_fmt = mdates.DateFormatter("%Y")

    # ── 패널 1: 원본 EDI ─────────────────────────────────────────
    ax = axes[0]
    _draw_bands(ax)
    e_pos = np.where(edi >= 0, edi, 0)
    e_neg = np.where(edi < 0, edi, 0)
    ax.fill_between(dates_e, 0, e_pos, color="#2196F3", alpha=0.35, step="mid")
    ax.fill_between(dates_e, 0, e_neg, color="#E53935", alpha=0.35, step="mid")
    ax.plot(dates_e, edi, color="#263238", lw=0.5, alpha=0.6)
    for y in [0, -1, -2, 1]:
        ax.axhline(y, color="gray", lw=0.5, ls=":")
    ax.set_ylabel("EDI", fontsize=11)
    ax.set_ylim(-3.5, 3.5)
    ax.set_title("원본 EDI  [기후 평년: 1991~2020 고정]", fontsize=12, loc="left")
    ax.xaxis.set_major_locator(yr_loc)
    ax.xaxis.set_major_formatter(yr_fmt)
    ax.grid(axis="both", alpha=0.2)

    # ── 패널 2: scCEDI-K ────────────────────────────────────────
    ax = axes[1]
    _draw_bands(ax)
    s_pos = np.where(sc >= 0, sc, 0)
    s_neg = np.where(sc < 0, sc, 0)
    ax.fill_between(dates_s, 0, s_pos, color="#2196F3", alpha=0.35, step="mid")
    ax.fill_between(dates_s, 0, s_neg, color="#E53935", alpha=0.35, step="mid")
    ax.plot(dates_s, sc, color="#1B5E20", lw=0.5, alpha=0.6)
    for y in [0, -1, -2, 1]:
        ax.axhline(y, color="gray", lw=0.5, ls=":")
    ax.set_ylabel("scCEDI-K", fontsize=11)
    ax.set_ylim(-3.5, 3.5)
    ax.set_title(
        "scCEDI-K v2  [Rolling 30년 기후학 + 비모수 표준화 + 유출보정 α=0.2]",
        fontsize=12,
        loc="left",
    )
    ax.xaxis.set_major_locator(yr_loc)
    ax.xaxis.set_major_formatter(yr_fmt)
    ax.grid(axis="both", alpha=0.2)

    # ── 패널 3: 차이 ────────────────────────────────────────────
    ax = axes[2]
    # 날짜 맞추기
    merged = pd.merge(edi_df[["date", "EDI"]], sc_df[["date", "scCEDI_K"]], on="date")
    md = pd.DatetimeIndex(merged["date"])
    diff = merged["scCEDI_K"].to_numpy() - merged["EDI"].to_numpy()
    ax.fill_between(
        md,
        0,
        diff,
        where=diff >= 0,
        color="#2196F3",
        alpha=0.4,
        step="mid",
        label="scCEDI-K > EDI (더 습윤)",
    )
    ax.fill_between(
        md,
        0,
        diff,
        where=diff < 0,
        color="#E53935",
        alpha=0.4,
        step="mid",
        label="scCEDI-K < EDI (더 건조)",
    )
    ax.axhline(0, color="gray", lw=0.8, ls="--")
    ax.set_ylabel("차이", fontsize=11)
    ax.set_title("scCEDI-K − EDI", fontsize=12, loc="left")
    ax.legend(loc="lower left", fontsize=9)
    ax.xaxis.set_major_locator(yr_loc)
    ax.xaxis.set_major_formatter(yr_fmt)
    ax.grid(axis="both", alpha=0.2)

    out = PROC_DIR / f"longterm_compare_{STN_ID}_2001_2026.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    logger.info("저장: %s", out)
    plt.show()
    print(f"\n그래프: {out}")


def _draw_bands(ax):
    bands = [
        (-3.5, -2.0, "#FF0000"),
        (-2.0, -1.5, "#FFA500"),
        (-1.5, -1.0, "#FFD700"),
        (-1.0, 1.0, "#F0F8F0"),
        (1.0, 1.5, "#87CEEB"),
        (1.5, 2.0, "#4169E1"),
        (2.0, 3.5, "#0000FF"),
    ]
    for lo, hi, c in bands:
        ax.axhspan(lo, hi, alpha=0.10, color=c, zorder=0)


# ═════════════════════════════════════════════════════════════════
# 메인
# ═════════════════════════════════════════════════════════════════
def main():
    df_all = load_all()

    target_start = "2001-01-01"
    target_end = "2026-03-31"

    print("\n[1/2] 원본 EDI 계산 (2001~2026.03)...")
    edi_df = compute_edi_long(df_all, target_start, target_end, baseline=(1991, 2020))
    print(
        f"  EDI: {len(edi_df)}건, 범위 {edi_df['EDI'].min():.2f} ~ {edi_df['EDI'].max():.2f}"
    )

    print("\n[2/2] scCEDI-K v2 계산 (2001~2026.03)...")
    sc_df = compute_sccedik_long(
        df_all, target_start, target_end, baseline_window=30, alpha=0.2
    )
    print(
        f"  scCEDI-K: {len(sc_df)}건, 범위 {sc_df['scCEDI_K'].min():.2f} ~ {sc_df['scCEDI_K'].max():.2f}"
    )

    # 저장
    edi_df.to_csv(
        PROC_DIR / f"edi_long_{STN_ID}_2001_2026.csv", index=False, encoding="utf-8-sig"
    )
    sc_df.to_csv(
        PROC_DIR / f"sccedik_long_{STN_ID}_2001_2026.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 요약 통계
    merged = pd.merge(edi_df, sc_df[["date", "scCEDI_K"]], on="date")
    e = merged["EDI"].dropna()
    s = merged["scCEDI_K"].dropna()
    common = merged.dropna(subset=["EDI", "scCEDI_K"])

    print(f"\n{'=' * 60}")
    print(f"  강릉(105) 2001~2026.03 장기 비교 요약")
    print(f"{'=' * 60}")
    print(f"  {'':15} {'원본 EDI':>12} {'scCEDI-K':>12}")
    print(f"  {'최소값':15} {e.min():>12.3f} {s.min():>12.3f}")
    print(f"  {'최대값':15} {e.max():>12.3f} {s.max():>12.3f}")
    print(f"  {'평균':15} {e.mean():>12.3f} {s.mean():>12.3f}")
    print(f"  {'상관계수':15} {common['EDI'].corr(common['scCEDI_K']):>12.4f}")

    thresholds = [
        (-np.inf, -2.0),
        (-2.0, -1.5),
        (-1.5, -1.0),
        (-1.0, 1.0),
        (1.0, np.inf),
    ]
    labels = ["극심 가뭄(<-2)", "심한 가뭄", "보통 가뭄", "정상", "습윤(>1)"]
    print(f"\n[등급별 일수]")
    print(f"  {'등급':15} {'원본 EDI':>10} {'scCEDI-K':>10}")
    for (lo, hi), lbl in zip(thresholds, labels):
        ce = ((e >= lo) & (e < hi)).sum()
        cs = ((s >= lo) & (s < hi)).sum()
        print(f"  {lbl:15} {ce:>10} {cs:>10}")

    # 시각화
    plot_longterm(edi_df, sc_df)


if __name__ == "__main__":
    main()
