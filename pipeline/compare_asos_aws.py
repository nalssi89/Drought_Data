"""
강릉(105) 2025년 ASOS vs AWS 일강수량 비교
"""

import logging
import sys
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib import rcParams

# 한글 폰트 설정 (macOS)
rcParams["font.family"] = "AppleGothic"
rcParams["axes.unicode_minus"] = False

sys.path.insert(0, str(Path(__file__).parent))
from asos_collector import collect_station_year
from aws_collector import collect_aws_station_year

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

STN_ID = 105
YEAR = 2025
PROCESSED_DIR = Path(__file__).parent / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def load_or_fetch_asos() -> pd.DataFrame:
    raw_path = Path(__file__).parent / "data" / "raw" / f"asos_precip_{STN_ID}_강릉_{YEAR}.csv"
    if raw_path.exists():
        df = pd.read_csv(raw_path, parse_dates=["date"])
        logger.info("ASOS 캐시 로드: %s", raw_path)
    else:
        df = collect_station_year(STN_ID, YEAR)
    return df[["date", "precip_mm"]].rename(columns={"precip_mm": "asos_mm"})


def load_or_fetch_aws() -> pd.DataFrame:
    raw_path = Path(__file__).parent / "data" / "raw" / f"aws_precip_{STN_ID}_강릉_{YEAR}.csv"
    if raw_path.exists():
        df = pd.read_csv(raw_path, parse_dates=["date"])
        logger.info("AWS 캐시 로드: %s", raw_path)
    else:
        df = collect_aws_station_year(STN_ID, YEAR)
    return df[["date", "precip_mm"]].rename(columns={"precip_mm": "aws_mm"})


def main():
    # ── 데이터 로드 ──────────────────────────────────────────────
    asos = load_or_fetch_asos()
    aws = load_or_fetch_aws()

    # 병합
    df = pd.merge(asos, aws, on="date", how="outer").sort_values("date").reset_index(drop=True)
    df["month"] = df["date"].dt.to_period("M")

    # ASOS NaN → 0 처리 (강수 없음으로 간주)
    df["asos_fill"] = df["asos_mm"].fillna(0.0)

    # ── 기술통계 ──────────────────────────────────────────────────
    print("\n" + "="*60)
    print(f"  강릉(105) {YEAR}년 ASOS vs AWS 일강수량 비교")
    print("="*60)

    diff = df["asos_fill"] - df["aws_mm"]
    print(f"\n[전체 통계]")
    print(f"  ASOS 연간 합계  : {df['asos_fill'].sum():.1f} mm")
    print(f"  AWS  연간 합계  : {df['aws_mm'].sum():.1f} mm")
    print(f"  차이 (ASOS-AWS) : {diff.sum():.1f} mm")
    print(f"  RMSE            : {((diff**2).mean())**0.5:.3f} mm")
    print(f"  MAE             : {diff.abs().mean():.3f} mm")
    print(f"  상관계수        : {df['asos_fill'].corr(df['aws_mm']):.4f}")

    discrepancy = df[diff.abs() > 0.1][["date", "asos_fill", "aws_mm"]].copy()
    discrepancy["diff"] = discrepancy["asos_fill"] - discrepancy["aws_mm"]
    print(f"\n[차이 > 0.1mm 날 수] {len(discrepancy)}일")
    if not discrepancy.empty:
        print(discrepancy.to_string(index=False))

    # ── 월별 집계 ─────────────────────────────────────────────────
    monthly = df.groupby("month").agg(
        asos_mm=("asos_fill", "sum"),
        aws_mm=("aws_mm", "sum"),
    ).reset_index()
    monthly["diff"] = monthly["asos_mm"] - monthly["aws_mm"]
    monthly["month"] = monthly["month"].astype(str)

    print("\n[월별 강수량 비교 (mm)]")
    print(f"{'월':<10} {'ASOS':>10} {'AWS':>10} {'차이':>10}")
    print("-" * 42)
    for _, row in monthly.iterrows():
        print(f"{row['month']:<10} {row['asos_mm']:>10.1f} {row['aws_mm']:>10.1f} {row['diff']:>+10.1f}")

    # CSV 저장
    out_path = PROCESSED_DIR / f"compare_asos_aws_{STN_ID}_{YEAR}.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    logger.info("비교 데이터 저장: %s", out_path)

    # ── 시각화 ────────────────────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(14, 13))
    fig.suptitle(f"강릉(105) {YEAR}년 일강수량 비교: ASOS vs AWS", fontsize=15, fontweight="bold")

    months = df["date"].dt.month
    month_colors = plt.cm.tab10(months / 12)

    # --- 패널 1: 일강수량 시계열 ---
    ax1 = axes[0]
    ax1.bar(df["date"], df["aws_mm"], color="#4C9BE8", alpha=0.7, label="AWS", width=1)
    ax1.bar(df["date"], df["asos_fill"], color="#E84C4C", alpha=0.5, label="ASOS", width=1)
    ax1.set_ylabel("일강수량 (mm)")
    ax1.set_title("일강수량 시계열")
    ax1.legend(loc="upper left")
    ax1.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%m월"))
    ax1.xaxis.set_major_locator(plt.matplotlib.dates.MonthLocator())
    ax1.grid(axis="y", alpha=0.3)

    # --- 패널 2: 월별 누적 강수량 막대 비교 ---
    ax2 = axes[1]
    x = range(len(monthly))
    w = 0.35
    bars1 = ax2.bar([i - w/2 for i in x], monthly["asos_mm"], width=w, color="#E84C4C", alpha=0.8, label="ASOS")
    bars2 = ax2.bar([i + w/2 for i in x], monthly["aws_mm"], width=w, color="#4C9BE8", alpha=0.8, label="AWS")
    ax2.set_xticks(list(x))
    ax2.set_xticklabels([m[-2:] + "월" for m in monthly["month"]])
    ax2.set_ylabel("월 강수량 (mm)")
    ax2.set_title("월별 누적 강수량 비교")
    ax2.legend()
    ax2.grid(axis="y", alpha=0.3)
    for bar in bars1:
        h = bar.get_height()
        if h > 5:
            ax2.text(bar.get_x() + bar.get_width()/2, h + 2, f"{h:.0f}", ha="center", va="bottom", fontsize=7, color="#E84C4C")
    for bar in bars2:
        h = bar.get_height()
        if h > 5:
            ax2.text(bar.get_x() + bar.get_width()/2, h + 2, f"{h:.0f}", ha="center", va="bottom", fontsize=7, color="#4C9BE8")

    # --- 패널 3: 1:1 산점도 ---
    ax3 = axes[2]
    rainy = df[(df["asos_fill"] > 0) | (df["aws_mm"] > 0)]
    sc = ax3.scatter(rainy["aws_mm"], rainy["asos_fill"],
                     c=rainy["date"].dt.month, cmap="tab10",
                     alpha=0.7, s=40, edgecolors="none")
    max_val = max(rainy["asos_fill"].max(), rainy["aws_mm"].max()) * 1.05
    ax3.plot([0, max_val], [0, max_val], "k--", lw=1, label="1:1 line")
    ax3.set_xlabel("AWS 일강수량 (mm)")
    ax3.set_ylabel("ASOS 일강수량 (mm)")
    ax3.set_title("일강수량 1:1 산점도 (강수 발생일)")
    cbar = plt.colorbar(sc, ax=ax3)
    cbar.set_label("월")
    cbar.set_ticks(range(1, 13))
    ax3.legend()
    ax3.grid(alpha=0.3)

    plt.tight_layout()
    fig_path = PROCESSED_DIR / f"compare_asos_aws_{STN_ID}_{YEAR}.png"
    plt.savefig(fig_path, dpi=150, bbox_inches="tight")
    logger.info("그래프 저장: %s", fig_path)
    plt.show()
    print(f"\n그래프 저장: {fig_path}")


if __name__ == "__main__":
    main()
