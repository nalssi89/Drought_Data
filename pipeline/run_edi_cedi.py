"""
EDI (Byun & Wilhite 1999) vs CEDI (Kim et al. 2009) 비교 실행

사용법:
    cd pipeline
    python run_edi_cedi.py                        # 기본: 강릉 105, 2025
    python run_edi_cedi.py --station 108 --year 2024
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib as mpl

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

from edi_algorithm  import run_edi
from cedi_algorithm import run_cedi

# ── 가뭄 등급 ─────────────────────────────────────────────────────────
DROUGHT_LEVELS = [
    (-np.inf, -2.0, "극심",   "#CC0000", 0.35),
    (-2.0,    -1.5, "심한",   "#FF4500", 0.25),
    (-1.5,    -1.0, "보통",   "#FFA500", 0.18),
]

STATION_NAMES = {105: "강릉", 108: "서울"}


# ── 데이터 로드 ───────────────────────────────────────────────────────
def load_data(station: int) -> pd.DataFrame:
    parts = sorted(RAW_DIR.glob(f"asos_precip_{station}_*.csv"))
    parts = [p for p in parts if "_raw" not in p.name]
    if not parts:
        raise FileNotFoundError(f"데이터 없음: {RAW_DIR}/asos_precip_{station}_*.csv")
    frames = []
    for p in parts:
        df_p = pd.read_csv(p, parse_dates=["date"])
        if "precip_mm" not in df_p.columns:
            cand = [c for c in df_p.columns if "precip" in c.lower() or "rain" in c.lower()]
            if cand:
                df_p = df_p.rename(columns={cand[0]: "precip_mm"})
        frames.append(df_p[["date", "precip_mm"]])
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    df["precip_mm"] = pd.to_numeric(df["precip_mm"], errors="coerce").fillna(0.0)
    return df


# ── 가뭄 통계 ─────────────────────────────────────────────────────────
def drought_stats(values: np.ndarray, label: str) -> None:
    v = values[~np.isnan(values)]
    n = len(v)
    print(f"\n  [{label}]")
    print(f"    유효일수: {n}일")
    print(f"    평균 / 표준편차: {v.mean():.3f} / {v.std(ddof=1):.3f}")
    print(f"    최솟값 / 최댓값: {v.min():.3f} / {v.max():.3f}")
    print(f"    가뭄일 (< -1.0): {(v < -1.0).sum()}일  ({(v < -1.0).mean()*100:.1f}%)")
    print(f"    심한가뭄(< -1.5): {(v < -1.5).sum()}일  ({(v < -1.5).mean()*100:.1f}%)")
    print(f"    극심가뭄(< -2.0): {(v < -2.0).sum()}일  ({(v < -2.0).mean()*100:.1f}%)")


# ── 플롯: 시계열 비교 ─────────────────────────────────────────────────
def _load_reservoir(year: int) -> pd.DataFrame | None:
    """outputs/ 에서 오봉저수지 CSV 로드 후 해당 연도만 반환."""
    cands = sorted(OUT_DIR.glob("저수율_강릉오봉_*.csv"))
    if not cands:
        return None
    df = pd.read_csv(cands[-1], parse_dates=["date"])
    df = df[df["date"].dt.year == year].reset_index(drop=True)
    return df if len(df) > 0 else None


def plot_timeseries(df_edi: pd.DataFrame, df_cedi: pd.DataFrame,
                    station: int, year: int, out_path: Path) -> None:
    stn_name = STATION_NAMES.get(station, str(station))
    df_res = _load_reservoir(year)

    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True,
                             gridspec_kw={"height_ratios": [1.4, 2, 2]})
    fig.suptitle(
        f"EDI vs CEDI 비교 — {stn_name}({station})  {year}년\n"
        "EDI: Byun & Wilhite (1999)  |  CEDI: Kim et al. (2009)\n"
        "기준기간: 1991-2020  |  유출보정 임계값: 80 mm  |  감쇠계수: exp(-0.5*(m-1))",
        fontsize=10, y=1.01
    )

    # ── 패널 0: 강수량(위→아래) + 저수율 ────────────────────────────
    ax0 = axes[0]

    # 강수량: 위에서 아래로 (y축 반전)
    precip = df_edi["precip_mm"].values
    p_max  = max(precip.max() * 1.1, 10)
    ax0.bar(df_edi["date"], precip, color="steelblue", alpha=0.7,
            width=1.0, label="일강수량 (mm)")
    ax0.set_ylim(p_max, 0)          # 반전: 0이 위, max가 아래
    ax0.set_ylabel("강수량 (mm)", fontsize=9, color="steelblue")
    ax0.tick_params(axis="y", labelcolor="steelblue", labelsize=8)

    # 저수율: 오른쪽 축 (정방향)
    if df_res is not None:
        ax0r = ax0.twinx()
        ax0r.plot(df_res["date"], df_res["storage_rate"],
                  color="#c0392b", lw=1.5, label="오봉저수지 저수율 (%)")
        ax0r.set_ylim(0, 110)
        ax0r.set_ylabel("저수율 (%)", fontsize=9, color="#c0392b")
        ax0r.tick_params(axis="y", labelcolor="#c0392b", labelsize=8)
        ax0r.axhline(50, color="#c0392b", lw=0.5, ls=":", alpha=0.5)

        # 범례 합치기
        h1, l1 = ax0.get_legend_handles_labels()
        h2, l2 = ax0r.get_legend_handles_labels()
        ax0.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper right")
    else:
        ax0.legend(fontsize=8, loc="upper right")

    ax0.set_title("일강수량 (위→아래)  /  오봉저수지 저수율", fontsize=9, loc="left")

    # ── 패널 1: EDI ──────────────────────────────────────────────────
    ax1 = axes[1]
    edi_vals = df_edi["EDI"].values
    _draw_index_panel(ax1, df_edi["date"], edi_vals,
                      color="#333333", label="EDI")
    ax1.set_ylabel("EDI", fontsize=9)
    ax1.set_title("EDI — Byun & Wilhite (1999)  [유출보정 없음, z-score]",
                  fontsize=9, loc="left")

    # ── 패널 2: CEDI ─────────────────────────────────────────────────
    ax2 = axes[2]
    cedi_vals = df_cedi["CEDI"].values
    _draw_index_panel(ax2, df_cedi["date"], cedi_vals,
                      color="#1a6faf", label="CEDI")
    ax2.set_ylabel("CEDI", fontsize=9)
    ax2.set_title("CEDI — Kim et al. (2009)  [80mm 시간감쇠 유출보정, z-score, DS확장]",
                  fontsize=9, loc="left")

    # x축 포맷
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m월"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator())
    plt.setp(ax2.get_xticklabels(), fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  저장: {out_path.name}")


def _draw_index_panel(ax, dates, vals, color, label):
    """가뭄 지수 패널 공통 그리기."""
    for lo, hi, name, clr, alpha in DROUGHT_LEVELS:
        mask = (vals < hi) & (vals >= lo)
        if mask.any():
            ax.fill_between(dates, np.clip(vals, lo, hi), hi,
                            where=mask, color=clr, alpha=alpha, label=f"{name}가뭄")

    ax.plot(dates, vals, color=color, lw=0.9, label=label)
    ax.axhline(0,    color="gray",    lw=0.6, ls="--", alpha=0.6)
    ax.axhline(-1.0, color="#FFA500", lw=0.7, ls=":",  alpha=0.8, label="-1.0")
    ax.axhline(-1.5, color="#FF4500", lw=0.7, ls=":",  alpha=0.8, label="-1.5")
    ax.axhline(-2.0, color="#CC0000", lw=0.7, ls=":",  alpha=0.8, label="-2.0")
    ax.set_ylim(-4.5, 3.5)
    ax.legend(fontsize=7, loc="lower right", ncol=4)


# ── 플롯: DS 확장 + 유출보정 세부 ────────────────────────────────────
def plot_detail(df_edi: pd.DataFrame, df_cedi: pd.DataFrame,
                station: int, year: int, out_path: Path) -> None:
    stn_name = STATION_NAMES.get(station, str(station))
    fig, axes = plt.subplots(4, 1, figsize=(14, 12), sharex=True,
                             gridspec_kw={"height_ratios": [1, 1.5, 1.5, 1]})
    fig.suptitle(
        f"EDI / CEDI 내부 변수 비교 — {stn_name}({station})  {year}년",
        fontsize=10, y=1.01
    )

    dates_e = df_edi["date"]
    dates_c = df_cedi["date"]

    # EP vs CEP
    ax0 = axes[0]
    ax0.plot(dates_e, df_edi["EP"],  color="#333333", lw=0.9, label="EP (EDI)")
    ax0.plot(dates_c, df_cedi["CEP"], color="#1a6faf", lw=0.9, ls="--", label="CEP (CEDI)")
    ax0.set_ylabel("EP / CEP", fontsize=8)
    ax0.legend(fontsize=7)
    ax0.set_title("유효강수량 EP vs 보정유효강수량 CEP", fontsize=9, loc="left")

    # DS 확장
    ax1 = axes[1]
    ax1.step(dates_e, df_edi["DS"],  color="#333333", lw=0.9, label="DS (EDI)", where="post")
    ax1.step(dates_c, df_cedi["DS"], color="#1a6faf", lw=0.9, ls="--", label="DS (CEDI)", where="post")
    ax1.axhline(365, color="gray", lw=0.6, ls=":")
    ax1.set_ylabel("DS (일)", fontsize=8)
    ax1.legend(fontsize=7)
    ax1.set_title("합산기간 DS 확장 (가뭄 지속 시 연장)", fontsize=9, loc="left")

    # EDI vs CEDI 오버레이
    ax2 = axes[2]
    ax2.plot(dates_e, df_edi["EDI"],   color="#333333", lw=1.0, label="EDI",  alpha=0.85)
    ax2.plot(dates_c, df_cedi["CEDI"], color="#1a6faf", lw=1.0, label="CEDI", ls="--", alpha=0.85)
    ax2.axhline(-1.0, color="#FFA500", lw=0.6, ls=":")
    ax2.axhline(-2.0, color="#CC0000", lw=0.6, ls=":")
    ax2.axhline(0, color="gray", lw=0.5, ls="--")
    ax2.set_ylim(-4.5, 3.5)
    ax2.set_ylabel("가뭄지수", fontsize=8)
    ax2.legend(fontsize=7)
    ax2.set_title("EDI vs CEDI 오버레이", fontsize=9, loc="left")

    # CEDI - EDI 차이
    ax3 = axes[3]
    merged = df_edi[["date", "EDI"]].merge(
        df_cedi[["date", "CEDI"]], on="date")
    diff = merged["CEDI"].values - merged["EDI"].values
    ax3.bar(merged["date"], diff, color=np.where(diff > 0, "#1a6faf", "#CC4400"),
            alpha=0.6, width=1.0)
    ax3.axhline(0, color="black", lw=0.5)
    ax3.set_ylabel("CEDI − EDI", fontsize=8)
    ax3.set_title("차이 (양수: CEDI가 더 습윤 판정, 음수: CEDI가 더 건조 판정)", fontsize=9, loc="left")

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m월"))
    axes[-1].xaxis.set_major_locator(mdates.MonthLocator())
    plt.setp(axes[-1].get_xticklabels(), fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  저장: {out_path.name}")


# ── 메인 ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--station",        type=int, default=105)
    parser.add_argument("--year",           type=int, default=2025)
    parser.add_argument("--baseline_start", type=int, default=1991)
    parser.add_argument("--baseline_end",   type=int, default=2020)
    args = parser.parse_args()

    station  = args.station
    year     = args.year
    baseline = (args.baseline_start, args.baseline_end)
    target   = (year, year)
    stn_name = STATION_NAMES.get(station, str(station))
    tag      = f"{stn_name}{station}_{year}"

    print(f"\n{'='*60}")
    print(f"  EDI vs CEDI: {stn_name}({station})  {year}년")
    print(f"  기준기간: {baseline[0]}–{baseline[1]}")
    print(f"{'='*60}\n")

    df = load_data(station)

    print("① EDI (Byun & Wilhite 1999)")
    df_edi = run_edi(df, baseline_years=baseline, target_years=target)

    print("\n② CEDI (Kim et al. 2009)")
    df_cedi = run_cedi(df, baseline_years=baseline, target_years=target)

    # ── 통계 ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  가뭄 통계")
    print(f"{'='*60}")
    drought_stats(df_edi["EDI"].values,   "EDI  (Byun & Wilhite 1999)")
    drought_stats(df_cedi["CEDI"].values, "CEDI (Kim et al. 2009)")

    # 상관
    merged = df_edi[["date", "EDI"]].merge(df_cedi[["date", "CEDI"]], on="date").dropna()
    r = np.corrcoef(merged["EDI"].values, merged["CEDI"].values)[0, 1]
    rmse = np.sqrt(np.mean((merged["EDI"].values - merged["CEDI"].values) ** 2))
    print(f"\n  EDI ↔ CEDI 상관계수: {r:.4f}  RMSE: {rmse:.4f}")

    # ── CSV 저장 ──────────────────────────────────────────────────────
    csv_edi  = OUT_DIR / f"EDI_Byun1999_{tag}.csv"
    csv_cedi = OUT_DIR / f"CEDI_Kim2009_{tag}.csv"
    df_edi.to_csv(csv_edi,   index=False, encoding="utf-8-sig")
    df_cedi.to_csv(csv_cedi, index=False, encoding="utf-8-sig")
    print(f"\n  저장: {csv_edi.name}")
    print(f"  저장: {csv_cedi.name}")

    # ── 플롯 ──────────────────────────────────────────────────────────
    plot_timeseries(
        df_edi, df_cedi, station, year,
        OUT_DIR / f"EDI_CEDI_시계열비교_{tag}.png"
    )
    plot_detail(
        df_edi, df_cedi, station, year,
        OUT_DIR / f"EDI_CEDI_내부변수비교_{tag}.png"
    )

    print(f"\n  출력 디렉토리: {OUT_DIR}")


if __name__ == "__main__":
    main()
