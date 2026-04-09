"""
강릉(105) 2025년 scCEDI-K v2 계산 및 원본 EDI 비교 시각화
"""

import sys
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import rcParams

rcParams["font.family"] = "AppleGothic"
rcParams["axes.unicode_minus"] = False

sys.path.insert(0, str(Path(__file__).parent))
from sccedik import run_sccedik

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

RAW_DIR  = Path(__file__).parent / "data" / "raw"
PROC_DIR = Path(__file__).parent / "data" / "processed"
PROC_DIR.mkdir(parents=True, exist_ok=True)

STN_ID = 105


def load_all_precip() -> pd.DataFrame:
    hist = pd.read_csv(RAW_DIR / f"asos_precip_{STN_ID}_1990_2024.csv",
                       parse_dates=["date"])[["date", "precip_mm"]]
    cur = pd.read_csv(RAW_DIR / f"asos_precip_{STN_ID}_강릉_2025.csv",
                      parse_dates=["date"])[["date", "precip_mm"]]
    df = pd.concat([hist, cur], ignore_index=True)
    return df.sort_values("date").drop_duplicates("date").reset_index(drop=True)


def main():
    df_all = load_all_precip()
    logger.info("전체 자료: %d건 (%s ~ %s)",
                len(df_all), df_all["date"].min().date(), df_all["date"].max().date())

    # ── scCEDI-K 계산 (α 방식) ──────────────────────────────────
    print("\n╔══════════════════════════════════════════════╗")
    print("║  scCEDI-K v2 계산 (α 방식, α=0.2)           ║")
    print("╚══════════════════════════════════════════════╝\n")

    result = run_sccedik(
        df_all,
        target_year=2025,
        fixed_baseline=(1991, 2020),  # WMO 표준 고정 기준기간
        runoff_method="alpha",
        alpha=0.2,
    )

    out_csv = PROC_DIR / f"sccedik_{STN_ID}_2025.csv"
    result.to_csv(out_csv, index=False, encoding="utf-8-sig")
    logger.info("저장: %s", out_csv)

    # ── 원본 EDI 로드 (비교용) ───────────────────────────────────
    edi_path = PROC_DIR / f"edi_{STN_ID}_2025.csv"
    edi_df = pd.read_csv(edi_path, parse_dates=["date"]) if edi_path.exists() else None

    # ── 요약 ─────────────────────────────────────────────────────
    sc = result["scCEDI_K"].dropna()
    print(f"\n{'='*60}")
    print(f"  강릉(105) 2025년 scCEDI-K v2 요약")
    print(f"{'='*60}")
    print(f"  최소값 : {sc.min():.3f}  ({result.loc[sc.idxmin(), 'date'].strftime('%Y-%m-%d')})")
    print(f"  최대값 : {sc.max():.3f}  ({result.loc[sc.idxmax(), 'date'].strftime('%Y-%m-%d')})")
    print(f"  연평균 : {sc.mean():.3f}")

    thresholds = [(-np.inf, -2.0), (-2.0, -1.5), (-1.5, -1.0),
                  (-1.0, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, np.inf)]
    labels = ["극심 가뭄", "심한 가뭄", "보통 가뭄",
              "정상",     "약한 습윤", "심한 습윤", "극심 습윤"]
    print("\n[등급별 일수]")
    for (lo, hi), lbl in zip(thresholds, labels):
        cnt = ((sc >= lo) & (sc < hi)).sum()
        print(f"  {lbl:<10}: {cnt:>3}일")

    print(f"\n[최대 dry_duration] {int(result['dry_dur'].max())}일")

    if edi_df is not None:
        edi_v = edi_df["EDI"].dropna()
        corr = sc.corr(edi_v.iloc[:len(sc)])
        print(f"\n[원본 EDI 대비]")
        print(f"  상관계수 : {corr:.4f}")
        print(f"  원본 EDI 최소: {edi_v.min():.3f} vs scCEDI-K 최소: {sc.min():.3f}")

    # ── 시각화 ───────────────────────────────────────────────────
    plot_comparison(result, edi_df)


def plot_comparison(sc_df: pd.DataFrame, edi_df: pd.DataFrame | None):
    dates = pd.DatetimeIndex(sc_df["date"])
    precip = sc_df["precip_mm"].to_numpy()
    pc = sc_df["precip_corrected"].to_numpy()
    sccedik = sc_df["scCEDI_K"].to_numpy()
    prn = sc_df["PRN"].to_numpy()
    ratio90 = sc_df["precip_ratio_90d"].to_numpy()

    has_edi = edi_df is not None
    if has_edi:
        edi = edi_df["EDI"].to_numpy()

    fig = plt.figure(figsize=(16, 18))
    fig.suptitle("강릉(105) 2025년 scCEDI-K v2 vs 원본 EDI",
                 fontsize=14, fontweight="bold", y=0.99)

    gs = fig.add_gridspec(5, 1, hspace=0.5,
                          height_ratios=[1.2, 1.5, 1.2, 0.8, 0.8])
    axes = [fig.add_subplot(gs[i]) for i in range(5)]
    month_fmt = mdates.DateFormatter("%m월")
    month_loc = mdates.MonthLocator()

    # ── 패널 1: 강수량 + 유출보정 ─────────────────────────────────
    ax = axes[0]
    ax.bar(dates, precip, color="#4C9BE8", width=1, alpha=0.7, label="원본 강수량")
    # 보정으로 깎인 부분
    diff = precip - pc
    heavy = diff > 0.1
    if heavy.any():
        ax.bar(dates[heavy], diff[heavy], bottom=pc[heavy],
               color="#FF6B6B", width=1, alpha=0.8, label="유출보정 감량분")
    ax.set_ylabel("강수량 (mm)")
    ax.set_title("일강수량 및 유출보정", fontsize=11)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="y", alpha=0.3)

    # ── 패널 2: scCEDI-K vs 원본 EDI ─────────────────────────────
    ax = axes[1]
    # 등급 배경
    bands = [(-3.5, -2.0, "#FF0000", "극심 가뭄"),
             (-2.0, -1.5, "#FFA500", "심한 가뭄"),
             (-1.5, -1.0, "#FFFF00", "보통 가뭄"),
             (-1.0,  1.0, "#E8F5E9", "정상"),
             ( 1.0,  1.5, "#87CEEB", "약한 습윤"),
             ( 1.5,  2.0, "#4169E1", "심한 습윤"),
             ( 2.0,  3.5, "#0000FF", "극심 습윤")]
    for lo, hi, color, lbl in bands:
        ax.axhspan(lo, hi, alpha=0.12, color=color, zorder=0)
        if abs((lo + hi) / 2) > 0.3 or lbl == "정상":
            ax.text(dates[-1] + pd.Timedelta(days=2), (lo + hi) / 2,
                    lbl, va="center", fontsize=7.5, color="dimgray", clip_on=False)

    # scCEDI-K
    sc_pos = np.where(sccedik >= 0, sccedik, 0)
    sc_neg = np.where(sccedik < 0, sccedik, 0)
    ax.fill_between(dates, 0, sc_pos, color="#1a7fc4", alpha=0.5, step="mid")
    ax.fill_between(dates, 0, sc_neg, color="#c0392b", alpha=0.5, step="mid")
    ax.plot(dates, sccedik, color="#2c3e50", lw=1.2, label="scCEDI-K v2")

    if has_edi:
        ax.plot(dates, edi, color="#7f8c8d", lw=0.8, ls="--", alpha=0.7,
                label="원본 EDI")

    ax.axhline(0,    color="gray",    lw=0.8, ls="--")
    ax.axhline(-1.0, color="#FFA500", lw=0.8, ls=":")
    ax.axhline(-2.0, color="#FF0000", lw=0.8, ls=":")
    ax.set_ylabel("지수값")
    ax.set_ylim(-3.5, 3.5)
    ax.set_title("scCEDI-K v2 vs 원본 EDI", fontsize=11)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="y", alpha=0.3)

    # ── 패널 3: 차이 분석 ─────────────────────────────────────────
    ax = axes[2]
    if has_edi:
        diff_idx = sccedik - edi[:len(sccedik)]
        ax.fill_between(dates, 0, diff_idx, where=diff_idx >= 0,
                        color="#2980b9", alpha=0.4, step="mid", label="scCEDI-K > EDI")
        ax.fill_between(dates, 0, diff_idx, where=diff_idx < 0,
                        color="#e74c3c", alpha=0.4, step="mid", label="scCEDI-K < EDI (더 건조)")
        ax.plot(dates, diff_idx, color="black", lw=0.6, alpha=0.5)
        ax.axhline(0, color="gray", lw=0.8, ls="--")
        ax.set_ylabel("scCEDI-K − EDI")
        ax.set_title("scCEDI-K와 원본 EDI의 차이 (음수 = 더 건조하게 평가)", fontsize=11)
        ax.legend(loc="upper left", fontsize=9)
    else:
        ax.text(0.5, 0.5, "원본 EDI 결과 없음", transform=ax.transAxes,
                ha="center", va="center", fontsize=12, color="gray")
    ax.grid(axis="y", alpha=0.3)

    # ── 패널 4: PRN (역산 보정) ───────────────────────────────────
    ax = axes[3]
    prn_pos = np.where(prn >= 0, prn, 0)
    prn_neg = np.where(prn < 0, prn, 0)
    ax.fill_between(dates, 0, prn_pos, color="#1a7fc4", alpha=0.5, step="mid")
    ax.fill_between(dates, 0, prn_neg, color="#c0392b", alpha=0.5, step="mid")
    ax.plot(dates, prn, color="black", lw=0.6, alpha=0.5)
    ax.axhline(0, color="gray", lw=0.8, ls="--")
    ax.set_ylabel("PRN (mm/day)")
    ax.set_title("해갈 필요 강수량 PRN (유출보정 역산 적용)", fontsize=11)
    ax.grid(axis="y", alpha=0.3)

    # ── 패널 5: 90일 강수 평년비 ──────────────────────────────────
    ax = axes[4]
    ax.fill_between(dates, 100, ratio90, where=ratio90 >= 100,
                    color="#2980b9", alpha=0.3, step="mid")
    ax.fill_between(dates, 100, ratio90, where=ratio90 < 100,
                    color="#e74c3c", alpha=0.3, step="mid")
    ax.plot(dates, ratio90, color="#2c3e50", lw=1.0)
    ax.axhline(100, color="gray", lw=0.8, ls="--")
    ax.set_ylabel("평년비 (%)")
    ax.set_title("최근 90일 강수 평년비", fontsize=11)
    ax.grid(axis="y", alpha=0.3)

    for ax in axes:
        ax.xaxis.set_major_locator(month_loc)
        ax.xaxis.set_major_formatter(month_fmt)
    for ax in axes[:-1]:
        plt.setp(ax.get_xticklabels(), visible=False)

    out_png = PROC_DIR / f"sccedik_{STN_ID}_2025.png"
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    logger.info("그래프 저장: %s", out_png)
    plt.show()
    print(f"\n그래프: {out_png}")


if __name__ == "__main__":
    main()
