"""
CEDI vs CEDI+PIT 비교

CEDI 원본: Kim et al. (2009) — CEP(DS=365) + DS확장 + z-score
CEDI+PIT:  CEP(DS=365 고정) + DCEP에 경험적 PIT → N(0,1)

사용법:
    cd pipeline
    python run_cedi_pit.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib as mpl
from scipy.stats import norm

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

# ── 경로 ──────────────────────────────────────────────────────────────
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

STATION = 105
YEAR = 2025
BASELINE = (1991, 2020)
POOL_HALF = 15
STATION_NAMES = {105: "강릉", 108: "서울"}


# ── SPI 계산 ──────────────────────────────────────────────────────────
def compute_spi(df_all: pd.DataFrame,
                scale_months: int,
                baseline_years=(1991, 2020),
                target_year=2025) -> pd.DataFrame:
    """
    SPI 계산: n개월 누적강수 → 감마분포 피팅 → PIT.
    Kim et al. (2009) p.4에 서술된 SPI 절차를 따름.

    Parameters
    ----------
    scale_months : 1, 3, 6 등
    """
    from scipy.stats import gamma as gamma_dist

    df = df_all.copy().sort_values("date").reset_index(drop=True)
    df["precip_mm"] = df["precip_mm"].fillna(0.0)
    df["year"]  = df["date"].dt.year
    df["month"] = df["date"].dt.month

    # 월별 강수합
    monthly = df.groupby(["year", "month"])["precip_mm"].sum().reset_index()
    monthly = monthly.sort_values(["year", "month"]).reset_index(drop=True)
    monthly["precip_sum"] = monthly["precip_mm"].rolling(scale_months, min_periods=scale_months).sum()

    # 기준기간
    bl = monthly[(monthly["year"] >= baseline_years[0]) & (monthly["year"] <= baseline_years[1])]

    # 월별 감마 피팅 + PIT
    spi_vals = []
    for _, row in monthly.iterrows():
        yr, mo, psum = int(row["year"]), int(row["month"]), row["precip_sum"]
        if np.isnan(psum):
            spi_vals.append(np.nan)
            continue

        # 해당 월의 기준기간 값
        ref = bl[bl["month"] == mo]["precip_sum"].dropna().values
        ref = ref[ref > 0]  # 감마는 양수만

        if len(ref) < 10:
            spi_vals.append(np.nan)
            continue

        # 0값 비율 (mixed distribution)
        all_ref = bl[bl["month"] == mo]["precip_sum"].dropna().values
        q = (all_ref == 0).sum() / len(all_ref)  # P(X=0)

        if psum == 0:
            prob = q
        else:
            try:
                a, loc, scale = gamma_dist.fit(ref, floc=0)
                prob = q + (1 - q) * gamma_dist.cdf(psum, a, loc=0, scale=scale)
            except Exception:
                spi_vals.append(np.nan)
                continue

        prob = np.clip(prob, 0.001, 0.999)
        spi_vals.append(float(norm.ppf(prob)))

    monthly["SPI"] = spi_vals

    # target year만 추출, 일별로 확장 (월 내 동일값)
    target = monthly[monthly["year"] == target_year][["year", "month", "SPI"]].copy()
    dates_target = pd.date_range(f"{target_year}-01-01", f"{target_year}-12-31", freq="D")
    df_daily = pd.DataFrame({"date": dates_target})
    df_daily["month"] = df_daily["date"].dt.month
    df_daily = df_daily.merge(target[["month", "SPI"]], on="month", how="left")

    return df_daily[["date", "SPI"]]


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


# ── CEDI+PIT 계산 ────────────────────────────────────────────────────
def run_cedi_pit(df_all: pd.DataFrame,
                 baseline_years=(1991, 2020),
                 target_year=2025,
                 ds=365,
                 threshold=CEDI_THRESHOLD,
                 decay=CEDI_DECAY,
                 pool_half=15) -> pd.DataFrame:
    """
    CEDI+PIT: DS=365 고정, DCEP에 경험적 PIT 적용.
    """
    df = df_all.copy().sort_values("date").reset_index(drop=True)
    df["precip_mm"] = df["precip_mm"].fillna(0.0)
    dates = pd.DatetimeIndex(df["date"])
    precip = df["precip_mm"].to_numpy(dtype=float)
    n = len(precip)

    H = harmonic_array(ds + 10)

    # 1. CEP (DS=365 고정)
    print("  [1/3] CEP (DS=365, threshold=80mm)...")
    cep = compute_cep_fixed(precip, ds, H, threshold, decay)

    # 2. MEP (5일 평활)
    print("  [2/3] MEP + DCEP...")
    baseline_mask = (
        (dates.year >= baseline_years[0]) & (dates.year <= baseline_years[1])
    )
    mep_by_doy, _ = calendar_stats(cep, dates, baseline_mask)
    doy = dates.dayofyear
    mep_arr = np.array([mep_by_doy[d] for d in doy])
    dcep = cep - mep_arr

    # 3. PIT: 달력일 ±pool_half 풀링, 경험적 CDF → Phi^-1
    print(f"  [3/3] PIT 표준화 (+-{pool_half}일 풀링)...")
    cedi_pit = np.full(n, np.nan)

    # 기준기간 DCEP 풀링 테이블 구축
    for d in range(1, 367):
        target_days = set()
        for offset in range(-pool_half, pool_half + 1):
            target_days.add((d - 1 + offset) % 366 + 1)

        pool_mask = np.array([dd in target_days for dd in doy]) & baseline_mask & ~np.isnan(dcep)
        pool_vals = dcep[pool_mask]

        if len(pool_vals) < 20:
            continue

        # 대상연도 해당 doy
        day_mask = (doy == d) & (dates.year == target_year) & ~np.isnan(dcep)
        for idx in np.where(day_mask)[0]:
            v = dcep[idx]
            rank = (pool_vals < v).sum() + 0.5 * (pool_vals == v).sum()
            ecdf = rank / len(pool_vals)
            ecdf = np.clip(ecdf, 0.001, 0.999)
            cedi_pit[idx] = norm.ppf(ecdf)

    # 결과 정리
    target_mask = dates.year == target_year
    result = pd.DataFrame({
        "date":       dates[target_mask],
        "precip_mm":  precip[target_mask],
        "CEP":        cep[target_mask],
        "MEP":        mep_arr[target_mask],
        "DCEP":       dcep[target_mask],
        "CEDI_PIT":   cedi_pit[target_mask],
    }).reset_index(drop=True)

    return result


# ── 통계 ──────────────────────────────────────────────────────────────
def print_stats(vals, label):
    v = vals[~np.isnan(vals)]
    print(f"\n  [{label}]")
    print(f"    유효일수: {len(v)}")
    print(f"    평균: {v.mean():.4f}   표준편차: {v.std(ddof=1):.4f}   왜도: {pd.Series(v).skew():.4f}")
    for thr in [-1.0, -1.5, -2.0]:
        n_days = (v < thr).sum()
        pct = (v < thr).mean() * 100
        pct_theory = norm.cdf(thr) * 100
        print(f"    < {thr}: {n_days}일 ({pct:.1f}%)  [N(0,1) 이론: {pct_theory:.1f}%]")


# ── 플롯 ──────────────────────────────────────────────────────────────
def plot_comparison(df_cedi, df_pit, df_spi3, df_spi6, station, year, out_path):
    stn_name = STATION_NAMES.get(station, str(station))

    # 저수율 로드
    cands = sorted(OUT_DIR.glob("저수율_강릉오봉_*.csv"))
    df_res = None
    if cands:
        df_r = pd.read_csv(cands[-1], parse_dates=["date"])
        df_r = df_r[df_r["date"].dt.year == year].reset_index(drop=True)
        if len(df_r) > 0:
            df_res = df_r

    fig, axes = plt.subplots(5, 1, figsize=(14, 16), sharex=True,
                             gridspec_kw={"height_ratios": [1.2, 2, 2, 2, 1]})
    fig.suptitle(
        f"CEDI vs CEDI+PIT vs SPI -- {stn_name}({station})  {year}\n"
        f"CEDI: Kim 2009 (DS extend + z-score)  |  CEDI+PIT: DS=365 fix + PIT  |  SPI: gamma+PIT\n"
        f"baseline: {BASELINE[0]}-{BASELINE[1]}  |  pool: +-{POOL_HALF}d",
        fontsize=10, y=1.005
    )

    # 패널 0: 강수(역방향) + 저수율
    ax0 = axes[0]
    precip = df_pit["precip_mm"].values
    p_max = max(precip.max() * 1.1, 10)
    ax0.bar(df_pit["date"], precip, color="steelblue", alpha=0.7, width=1.0, label="precip (mm)")
    ax0.set_ylim(p_max, 0)
    ax0.set_ylabel("precip (mm)", fontsize=9, color="steelblue")
    ax0.tick_params(axis="y", labelcolor="steelblue", labelsize=8)

    if df_res is not None:
        ax0r = ax0.twinx()
        ax0r.plot(df_res["date"], df_res["storage_rate"],
                  color="#c0392b", lw=1.5, label="Obong reservoir (%)")
        ax0r.set_ylim(0, 110)
        ax0r.set_ylabel("storage %", fontsize=9, color="#c0392b")
        ax0r.tick_params(axis="y", labelcolor="#c0392b", labelsize=8)
        h1, l1 = ax0.get_legend_handles_labels()
        h2, l2 = ax0r.get_legend_handles_labels()
        ax0.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper right")
    else:
        ax0.legend(fontsize=8, loc="upper right")
    ax0.set_title("precip + Obong reservoir", fontsize=9, loc="left")

    # 패널 1: CEDI 원본
    ax1 = axes[1]
    cedi_v = df_cedi["CEDI"].values
    _draw_panel(ax1, df_cedi["date"], cedi_v, "#1a6faf", "CEDI")
    ax1.set_title("CEDI -- Kim 2009 (DS extend + z-score)", fontsize=9, loc="left")
    ax1.set_ylabel("CEDI", fontsize=9)

    # 패널 2: CEDI+PIT
    ax2 = axes[2]
    pit_v = df_pit["CEDI_PIT"].values
    _draw_panel(ax2, df_pit["date"], pit_v, "#228b22", "CEDI+PIT")
    ax2.set_title(f"CEDI+PIT -- DS=365 fix + empirical PIT (+-{POOL_HALF}d pool)", fontsize=9, loc="left")
    ax2.set_ylabel("CEDI+PIT", fontsize=9)

    # 패널 3: SPI3 + SPI6 (하나의 패널)
    ax3 = axes[3]
    spi3_v = df_spi3["SPI"].values
    spi6_v = df_spi6["SPI"].values
    ax3.step(df_spi3["date"], spi3_v, color="#9b30d0", lw=1.2, label="SPI-3", where="post")
    ax3.step(df_spi6["date"], spi6_v, color="#e07b00", lw=1.2, label="SPI-6", where="post", ls="--")
    # 가뭄 영역 (SPI6 기준)
    ax3.fill_between(df_spi6["date"], np.minimum(spi6_v, -2.0), -2.0,
                     where=spi6_v < -2.0, color="#CC0000", alpha=0.25, step="post")
    ax3.fill_between(df_spi6["date"], np.clip(spi6_v, -2.0, -1.0), -1.0,
                     where=spi6_v < -1.0, color="#FFA500", alpha=0.15, step="post")
    ax3.axhline(0, color="gray", lw=0.5, ls="--")
    ax3.axhline(-1.0, color="#FFA500", lw=0.6, ls=":")
    ax3.axhline(-1.5, color="#FF4500", lw=0.6, ls=":")
    ax3.axhline(-2.0, color="#CC0000", lw=0.6, ls=":")
    ax3.set_ylim(-4.5, 3.5)
    ax3.legend(fontsize=8, loc="lower right")
    ax3.set_title("SPI-3 / SPI-6 (gamma+PIT, monthly)", fontsize=9, loc="left")
    ax3.set_ylabel("SPI", fontsize=9)

    # 패널 4: CEDI+PIT vs SPI6 차이
    ax4 = axes[4]
    merged = df_pit[["date", "CEDI_PIT"]].copy()
    merged["month"] = merged["date"].dt.month
    spi6_monthly = df_spi6.drop_duplicates("date")[["date", "SPI"]].copy()
    spi6_monthly["month"] = spi6_monthly["date"].dt.month
    spi6_map = spi6_monthly.groupby("month")["SPI"].first()
    merged["SPI6"] = merged["month"].map(spi6_map)
    diff = merged["CEDI_PIT"].values - merged["SPI6"].values
    ax4.bar(merged["date"], diff,
            color=np.where(diff > 0, "#228b22", "#9b30d0"), alpha=0.5, width=1.0)
    ax4.axhline(0, color="black", lw=0.5)
    ax4.set_ylabel("CEDI+PIT - SPI6", fontsize=9)
    ax4.set_title("CEDI+PIT - SPI-6 (+ = CEDI+PIT more wet)", fontsize=9, loc="left")

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m"))
    axes[-1].xaxis.set_major_locator(mdates.MonthLocator())
    plt.setp(axes[-1].get_xticklabels(), fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  plot: {out_path.name}")


def _draw_panel(ax, dates, vals, color, label):
    ax.fill_between(dates, np.minimum(vals, -2.0), -2.0,
                    where=vals < -2.0, color="#CC0000", alpha=0.35)
    ax.fill_between(dates, np.clip(vals, -2.0, -1.5), -1.5,
                    where=vals < -1.5, color="#FF4500", alpha=0.25)
    ax.fill_between(dates, np.clip(vals, -1.5, -1.0), -1.0,
                    where=vals < -1.0, color="#FFA500", alpha=0.18)
    ax.plot(dates, vals, color=color, lw=0.9, label=label)
    ax.axhline(0, color="gray", lw=0.5, ls="--")
    ax.axhline(-1.0, color="#FFA500", lw=0.6, ls=":")
    ax.axhline(-1.5, color="#FF4500", lw=0.6, ls=":")
    ax.axhline(-2.0, color="#CC0000", lw=0.6, ls=":")
    ax.set_ylim(-4.5, 3.5)
    ax.legend(fontsize=7, loc="lower right")


# ── 메인 ──────────────────────────────────────────────────────────────
def main():
    stn_name = STATION_NAMES.get(STATION, str(STATION))
    tag = f"{stn_name}{STATION}_{YEAR}"

    print(f"\n{'='*55}")
    print(f"  CEDI vs CEDI+PIT: {stn_name}({STATION})  {YEAR}")
    print(f"{'='*55}\n")

    df = load_data(STATION)

    print("1) CEDI (Kim 2009)")
    df_cedi = run_cedi(df, baseline_years=BASELINE, target_years=(YEAR, YEAR))

    print("\n2) CEDI+PIT (DS=365 fix)")
    df_pit = run_cedi_pit(df, baseline_years=BASELINE, target_year=YEAR,
                          pool_half=POOL_HALF)

    print("\n3) SPI-3")
    df_spi3 = compute_spi(df, scale_months=3, baseline_years=BASELINE, target_year=YEAR)

    print("4) SPI-6")
    df_spi6 = compute_spi(df, scale_months=6, baseline_years=BASELINE, target_year=YEAR)

    # 통계
    print(f"\n{'='*55}")
    print("  statistics")
    print(f"{'='*55}")
    print_stats(df_cedi["CEDI"].values, "CEDI (z-score, DS extend)")
    print_stats(df_pit["CEDI_PIT"].values, "CEDI+PIT (DS=365 fix)")
    print_stats(df_spi3["SPI"].values, "SPI-3")
    print_stats(df_spi6["SPI"].values, "SPI-6")

    # 상관
    m = df_cedi[["date", "CEDI"]].merge(df_pit[["date", "CEDI_PIT"]], on="date").dropna()
    r = np.corrcoef(m["CEDI"].values, m["CEDI_PIT"].values)[0, 1]
    rmse = np.sqrt(np.mean((m["CEDI"].values - m["CEDI_PIT"].values) ** 2))
    print(f"\n  CEDI <-> CEDI+PIT  r={r:.4f}  RMSE={rmse:.4f}")

    # CSV
    csv_pit = OUT_DIR / f"CEDI_PIT_{tag}.csv"
    df_pit.to_csv(csv_pit, index=False, encoding="utf-8-sig")
    print(f"\n  csv: {csv_pit.name}")

    # 플롯
    plot_comparison(
        df_cedi, df_pit, df_spi3, df_spi6, STATION, YEAR,
        OUT_DIR / f"CEDI_vs_CEDI_PIT_SPI_{tag}.png"
    )

    print(f"\n  output: {OUT_DIR}")


if __name__ == "__main__":
    main()
