"""
강릉(105) 2025년 EDI 계산 및 시계열 시각화
기후 평년: 1991~2020 (WMO 표준 노멀)
"""

import sys
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
from matplotlib import rcParams

rcParams["font.family"] = "AppleGothic"
rcParams["axes.unicode_minus"] = False

sys.path.insert(0, str(Path(__file__).parent))
from edi_algorithm import run_edi, EDI_CLASSES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

RAW_DIR   = Path(__file__).parent / "data" / "raw"
PROC_DIR  = Path(__file__).parent / "data" / "processed"
PROC_DIR.mkdir(parents=True, exist_ok=True)

STN_ID = 105


# ── 데이터 로드 ────────────────────────────────────────────────────
def load_all_precip() -> pd.DataFrame:
    """1990~2025년 강릉 일강수량 로드"""
    hist_path = RAW_DIR / f"asos_precip_{STN_ID}_1990_2024.csv"
    hist = pd.read_csv(hist_path, parse_dates=["date"])
    hist = hist[["date", "precip_mm"]]

    cur_path = RAW_DIR / f"asos_precip_{STN_ID}_강릉_2025.csv"
    cur = pd.read_csv(cur_path, parse_dates=["date"])
    cur = cur[["date", "precip_mm"]]

    df = pd.concat([hist, cur], ignore_index=True)
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    logger.info("전체 자료: %d건 (%s ~ %s)",
                len(df), df["date"].min().date(), df["date"].max().date())
    return df


# ── EDI 계산 ───────────────────────────────────────────────────────
def main():
    df_all = load_all_precip()

    print("\nEDI 계산 중...")
    result = run_edi(
        df_all,
        baseline_years=(1991, 2020),   # WMO 표준 30년 노멀
        target_years=(2025, 2025),
        ds_base=365,
    )

    # 결과 저장
    out_csv = PROC_DIR / f"edi_{STN_ID}_2025.csv"
    result.to_csv(out_csv, index=False, encoding="utf-8-sig")
    logger.info("EDI 결과 저장: %s", out_csv)

    # ── 요약 출력 ──────────────────────────────────────────────────
    print("\n" + "="*60)
    print(f"  강릉(105) 2025년 EDI 요약")
    print("="*60)
    edi = result["EDI"].dropna()
    print(f"  EDI 최소값 : {edi.min():.3f}  ({result.loc[edi.idxmin(), 'date'].strftime('%Y-%m-%d')})")
    print(f"  EDI 최대값 : {edi.max():.3f}  ({result.loc[edi.idxmax(), 'date'].strftime('%Y-%m-%d')})")
    print(f"  EDI 연평균 : {edi.mean():.3f}")

    print("\n[EDI 등급별 일수]")
    for lo, hi, label, _ in EDI_CLASSES:
        cnt = ((edi >= lo) & (edi < hi)).sum()
        print(f"  {label:<20}: {cnt:>3}일")

    print("\n[최대 dry_duration]", int(result["dry_dur"].max()), "일")

    # ── 시각화 ─────────────────────────────────────────────────────
    plot_edi_series(result, STN_ID)


def plot_edi_series(df: pd.DataFrame, stn_id: int):
    dates = pd.DatetimeIndex(df["date"])
    precip = df["precip_mm"].to_numpy()
    edi    = df["EDI"].to_numpy()
    sep    = df["SEP"].to_numpy()
    ds     = df["DS"].to_numpy()
    prn    = df["PRN"].to_numpy()

    fig = plt.figure(figsize=(16, 14))
    fig.suptitle(f"강릉(105) 2025년 EDI 시계열  [기후 평년: 1991~2020]",
                 fontsize=14, fontweight="bold", y=0.98)

    # 그리드: 4행
    gs = fig.add_gridspec(4, 1, hspace=0.45,
                          height_ratios=[1.4, 1.2, 1.0, 0.8])
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax3 = fig.add_subplot(gs[2], sharex=ax1)
    ax4 = fig.add_subplot(gs[3], sharex=ax1)

    month_fmt = mdates.DateFormatter("%m월")
    month_loc = mdates.MonthLocator()

    # ── 패널 1: 일강수량 ──────────────────────────────────────────
    ax1.bar(dates, precip, color="#4C9BE8", width=1, alpha=0.85, label="일강수량")
    ax1.set_ylabel("강수량 (mm)", fontsize=10)
    ax1.set_title("일강수량", fontsize=11)
    ax1.yaxis.set_major_locator(plt.MaxNLocator(5))
    ax1.legend(loc="upper left", fontsize=9)
    ax1.grid(axis="y", alpha=0.3)

    # 우측 축: 누적강수량
    ax1r = ax1.twinx()
    cum = np.nancumsum(precip)
    ax1r.plot(dates, cum, color="#1a5276", lw=1.2, ls="--", alpha=0.7, label="누적강수")
    ax1r.set_ylabel("누적강수량 (mm)", fontsize=9, color="#1a5276")
    ax1r.tick_params(axis="y", colors="#1a5276")
    ax1r.legend(loc="upper center", fontsize=9)

    # ── 패널 2: EDI 시계열 ────────────────────────────────────────
    # 등급 배경색
    class_colors = {
        "Extreme Drought": "#FF0000",
        "Severe Drought":  "#FFA500",
        "Moderate Drought":"#FFFF00",
        "Near Normal":     "#E8F5E9",
        "Moderately Wet":  "#87CEEB",
        "Very Wet":        "#4169E1",
        "Extremely Wet":   "#0000FF",
    }
    thresholds = [(-np.inf, -2.0), (-2.0, -1.5), (-1.5, -1.0),
                  (-1.0,  1.0),  (1.0,  1.5),  (1.5, 2.0), (2.0, np.inf)]
    labels_short = ["극심 가뭄", "심한 가뭄", "보통 가뭄",
                    "정상",      "약한 홍수", "심한 홍수", "극심 홍수"]
    color_map = {
        "극심 가뭄": "#FF0000", "심한 가뭄": "#FFA500", "보통 가뭄": "#FFFF00",
        "정상":      "#E8F5E9", "약한 홍수": "#87CEEB",  "심한 홍수": "#4169E1",
        "극심 홍수": "#0000FF",
    }
    bg_alpha = 0.15
    for (lo, hi), lbl in zip(thresholds, labels_short):
        c_hi = min(hi,  2.5)
        c_lo = max(lo, -2.5)
        ax2.axhspan(c_lo, c_hi, alpha=bg_alpha, color=color_map[lbl], zorder=0)

    # EDI 값 표시
    edi_pos = np.where(edi >= 0, edi, 0)
    edi_neg = np.where(edi <  0, edi, 0)
    ax2.fill_between(dates, 0, edi_pos, color="#1a7fc4", alpha=0.6, step="mid", label="습윤")
    ax2.fill_between(dates, 0, edi_neg, color="#c0392b", alpha=0.6, step="mid", label="건조")
    ax2.plot(dates, edi, color="black", lw=0.8, alpha=0.5)
    ax2.axhline(0,    color="gray",   lw=0.8, ls="--")
    ax2.axhline(-1.0, color="#FFA500", lw=1.0, ls=":")
    ax2.axhline(-2.0, color="#FF0000", lw=1.0, ls=":")
    ax2.axhline(1.0,  color="#4169E1", lw=1.0, ls=":", alpha=0.5)
    ax2.set_ylabel("EDI", fontsize=10)
    ax2.set_title("Effective Drought Index (EDI)", fontsize=11)
    ax2.set_ylim(-3.5, 3.5)

    # 등급 레이블 (우측)
    for (lo, hi), lbl in zip(thresholds, labels_short):
        mid = max(min((lo + hi) / 2, 2.3), -2.3)
        if abs(mid) > 0.3 or lbl == "정상":
            ax2.text(dates[-1], mid, f" {lbl}", va="center", fontsize=7.5,
                     color="dimgray", ha="left",
                     transform=ax2.get_yaxis_transform() if False else ax2.transData,
                     clip_on=False)

    ax2.legend(loc="upper left", fontsize=9)
    ax2.grid(axis="y", alpha=0.3)

    # ── 패널 3: SEP & dry_duration ────────────────────────────────
    ax3.axhline(0, color="gray", lw=0.8, ls="--")
    ax3.plot(dates, sep, color="#8e44ad", lw=1.0, label="SEP")
    ax3.fill_between(dates, sep, 0, where=(sep < 0),
                     color="#e74c3c", alpha=0.3, label="SEP<0 (건조)")
    ax3.fill_between(dates, sep, 0, where=(sep >= 0),
                     color="#2980b9", alpha=0.2, label="SEP≥0")
    ax3b = ax3.twinx()
    ax3b.bar(dates, ds - 365, color="#e67e22", alpha=0.4, width=1,
             label="DS 연장일수")
    ax3b.set_ylabel("DS 연장 (일)", fontsize=9, color="#e67e22")
    ax3b.tick_params(axis="y", colors="#e67e22")
    ax3.set_ylabel("SEP", fontsize=10)
    ax3.set_title("표준화 유효강수 편차 (SEP) 및 합산기간 확장 (DS)", fontsize=11)
    ax3.legend(loc="upper left", fontsize=9)
    ax3.grid(axis="y", alpha=0.3)

    # ── 패널 4: PRN ───────────────────────────────────────────────
    prn_pos = np.where(prn >= 0, prn, 0)
    prn_neg = np.where(prn <  0, prn, 0)
    ax4.fill_between(dates, 0, prn_pos, color="#1a7fc4", alpha=0.5, step="mid")
    ax4.fill_between(dates, 0, prn_neg, color="#c0392b", alpha=0.5, step="mid")
    ax4.plot(dates, prn, color="black", lw=0.8, alpha=0.5)
    ax4.axhline(0, color="gray", lw=0.8, ls="--")
    ax4.set_ylabel("PRN (mm/day)", fontsize=10)
    ax4.set_title("정상화에 필요한 일강수량 (PRN)", fontsize=11)
    ax4.grid(axis="y", alpha=0.3)

    # X축 공통
    for ax in [ax1, ax2, ax3, ax4]:
        ax.xaxis.set_major_locator(month_loc)
        ax.xaxis.set_major_formatter(month_fmt)
        ax.tick_params(axis="x", labelsize=9)

    plt.setp(ax1.get_xticklabels(), visible=False)
    plt.setp(ax2.get_xticklabels(), visible=False)
    plt.setp(ax3.get_xticklabels(), visible=False)

    out_png = PROC_DIR / f"edi_{stn_id}_2025.png"
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    logger.info("그래프 저장: %s", out_png)
    plt.show()
    print(f"\n그래프: {out_png}")


if __name__ == "__main__":
    main()
