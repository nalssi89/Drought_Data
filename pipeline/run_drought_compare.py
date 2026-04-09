"""
5가지 가뭄지수 비교 실행 스크립트

  ① EDI      — Byun & Wilhite (1999) 원형
  ② CEDI     — Kim et al. (2009): 시간감쇠 유출보정 + DS확장 + z-score
  ③ scCEDI-K — 현재: α즉시보정 + DS미반영 + P3 + ±15일풀링
  ④ 개선A    — CEDI물리 + P3 + 풀링없음
  ⑤ 개선B    — CEDI물리 + P3 + ±15일풀링

설계 축별 효과 확인:
  ② vs ①: 유출보정 효과 (시간감쇠)
  ④ vs ②: 표준화 효과 (z-score → P3)
  ⑤ vs ④: 풀링 효과 (없음 → ±15일)
  ⑤ vs ③: 유출보정 방식 + DS확장 효과 (α즉시 → CEDI감쇠, PRN전용 → 메인반영)

사용법:
    python pipeline/run_drought_compare.py --station 105 --year 2025
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib as mpl

# ── 한글 폰트 설정 ────────────────────────────────────────────────
def _set_korean_font():
    import matplotlib.font_manager as fm
    candidates = ["Apple SD Gothic Neo", "AppleGothic", "NanumGothic",
                  "Malgun Gothic", "Noto Sans CJK KR"]
    available = {f.name for f in fm.fontManager.ttflist}
    for font in candidates:
        if font in available:
            mpl.rcParams["font.family"] = font
            break
    mpl.rcParams["axes.unicode_minus"] = False

_set_korean_font()

# ── 경로 설정 ─────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
PIPELINE = ROOT / "pipeline"
RAW_DIR = PIPELINE / "data" / "raw"
sys.path.insert(0, str(PIPELINE))

from edi_algorithm import run_edi
from cedi_algorithm import run_cedi
from sccedik import run_sccedik
from improved_cedi import run_improved_cedi


# ── 데이터 로드 ───────────────────────────────────────────────────
def load_data(station: int) -> pd.DataFrame:
    parts = sorted(RAW_DIR.glob(f"asos_precip_{station}_*.csv"))
    parts = [p for p in parts if "_raw" not in p.name]
    if not parts:
        raise FileNotFoundError(f"데이터 없음: {RAW_DIR}/asos_precip_{station}_*.csv")
    frames = []
    for p in parts:
        df_p = pd.read_csv(p, parse_dates=["date"])
        if "precip_mm" not in df_p.columns:
            cand = [c for c in df_p.columns
                    if "precip" in c.lower() or "rain" in c.lower()]
            if cand:
                df_p = df_p.rename(columns={cand[0]: "precip_mm"})
        frames.append(df_p[["date", "precip_mm"]])
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    df["precip_mm"] = pd.to_numeric(df["precip_mm"], errors="coerce").fillna(0.0)
    return df


# ── 통계 ──────────────────────────────────────────────────────────
def drought_stats(values: np.ndarray, label: str) -> dict:
    valid = values[~np.isnan(values)]
    return {
        "label": label,
        "mean":  float(np.mean(valid)),
        "std":   float(np.std(valid, ddof=1)),
        "min":   float(np.min(valid)),
        "max":   float(np.max(valid)),
        "pct_extreme": float(np.mean(valid < -2.0) * 100),
        "pct_drought": float(np.mean(valid < -1.0) * 100),
    }


def print_stats(stats_list: list[dict]) -> None:
    hdr = f"{'지수':<14} {'평균':>6} {'표준편차':>7} {'최솟값':>7} {'최댓값':>6} {'극심가뭄%':>9} {'가뭄%':>7}"
    print(hdr)
    print("─" * len(hdr))
    for s in stats_list:
        print(f"{s['label']:<14} {s['mean']:>6.3f} {s['std']:>7.3f} "
              f"{s['min']:>7.3f} {s['max']:>6.3f} "
              f"{s['pct_extreme']:>9.1f} {s['pct_drought']:>7.1f}")


# ── 플롯 ──────────────────────────────────────────────────────────
# 지수 설정: (컬럼명, 색상, 레이블)
INDEX_CFG = {
    "EDI":      ("EDI",          "#555555", "① EDI (1999)"),
    "CEDI":     ("CEDI",         "#1a6faf", "② CEDI (2009)"),
    "scCEDI-K": ("scCEDI_K",     "#e07b00", "③ scCEDI-K 현재"),
    "개선A":    ("ImprovedCEDI", "#9b30d0", "④ 개선A (CEDI+P3, 풀링없음)"),
    "개선B":    ("ImprovedCEDI", "#228b22", "⑤ 개선B (CEDI+P3, ±15일)"),
}

# 설계 축 효과 비교 쌍
EFFECT_PAIRS = [
    ("EDI",   "CEDI",   "유출보정 효과 (없음 → 시간감쇠)"),
    ("CEDI",  "개선A",  "표준화 효과 (z-score → P3, 풀링없음)"),
    ("개선A", "개선B",  "풀링 효과 (없음 → ±15일)"),
    ("개선B", "scCEDI-K", "α보정+DS미반영 vs CEDI+DS확장 차이"),
]


def plot_timeseries(results: dict, target_year: int, station: int,
                    out_path: Path | None = None) -> None:
    """5개 지수 시계열 비교."""
    names = list(results.keys())
    n_idx = len(names)
    fig, axes = plt.subplots(n_idx + 1, 1, figsize=(14, 3.2 * (n_idx + 1)),
                             sharex=True)
    fig.suptitle(
        f"가뭄지수 비교: 강릉({station})  {target_year}년\n"
        "① EDI  ② CEDI  ③ scCEDI-K 현재  ④ 개선A (CEDI+P3)  ⑤ 개선B (CEDI+P3+풀링)",
        fontsize=10, y=0.99
    )

    # 강수 막대
    df_ref = next(iter(results.values()))
    axes[0].bar(df_ref["date"], df_ref["precip_mm"],
                color="steelblue", alpha=0.7, width=1.0)
    axes[0].set_ylabel("강수 (mm)", fontsize=8)
    axes[0].set_ylim(bottom=0)

    for i, (name, df) in enumerate(results.items()):
        ax = axes[i + 1]
        col, color, label = INDEX_CFG[name]
        vals = df[col].values

        ax.fill_between(df["date"], np.minimum(vals, -2.0), -2.0,
                        where=vals < -2.0, color="#CC0000", alpha=0.3)
        ax.fill_between(df["date"],
                        np.clip(vals, -2.0, -1.0), -1.0,
                        where=vals < -1.0, color="#FF8C00", alpha=0.2)
        ax.plot(df["date"], vals, color=color, lw=1.0)
        ax.axhline(0,  color="gray",    lw=0.5, ls="--")
        ax.axhline(-1, color="#FF8C00", lw=0.6, ls=":")
        ax.axhline(-2, color="#CC0000", lw=0.6, ls=":")
        ax.set_ylabel(label, fontsize=8)
        ax.set_ylim(-4.5, 3.5)

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m월"))
    axes[-1].xaxis.set_major_locator(mdates.MonthLocator())
    plt.xticks(fontsize=8)
    plt.tight_layout()
    if out_path:
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        print(f"  시계열 플롯: {out_path.name}")
    else:
        plt.show()
    plt.close()


def plot_effects(results: dict, target_year: int, station: int,
                 out_path: Path | None = None) -> None:
    """설계 축별 효과 비교 (2×2 패널)."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=True)
    axes = axes.flatten()
    fig.suptitle(f"설계 축별 효과 분석: 강릉({station})  {target_year}년",
                 fontsize=11)

    colors_a = ["#555555", "#1a6faf", "#9b30d0", "#228b22"]
    colors_b = ["#1a6faf", "#9b30d0", "#228b22", "#e07b00"]

    df_ref = next(iter(results.values()))
    dates = df_ref["date"]

    for ax, (na, nb, title), ca, cb in zip(axes, EFFECT_PAIRS, colors_a, colors_b):
        col_a, _, label_a = INDEX_CFG[na]
        col_b, _, label_b = INDEX_CFG[nb]
        va = results[na][col_a].values
        vb = results[nb][col_b].values

        ax.plot(dates, va, color=ca, lw=1.0, label=label_a, alpha=0.9)
        ax.plot(dates, vb, color=cb, lw=1.0, label=label_b, ls="--", alpha=0.9)
        ax.axhline(0,  color="gray",    lw=0.4, ls="--")
        ax.axhline(-1, color="#FF8C00", lw=0.5, ls=":")
        ax.axhline(-2, color="#CC0000", lw=0.5, ls=":")
        ax.set_ylim(-4.5, 3.5)
        ax.set_title(title, fontsize=9)
        ax.legend(fontsize=7, loc="upper right")

    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m월"))
        ax.xaxis.set_major_locator(mdates.MonthLocator())
    plt.xticks(fontsize=7)
    plt.tight_layout()
    if out_path:
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        print(f"  효과 비교 플롯: {out_path.name}")
    else:
        plt.show()
    plt.close()


def plot_scatter_matrix(results: dict, out_path: Path | None = None) -> None:
    """주요 쌍의 산점도 (2×2)."""
    fig, axes = plt.subplots(2, 2, figsize=(11, 10))
    axes = axes.flatten()

    pairs = [
        ("EDI",   "CEDI"),
        ("CEDI",  "개선B"),
        ("개선A", "개선B"),
        ("개선B", "scCEDI-K"),
    ]
    pair_colors = ["#1a6faf", "#228b22", "#9b30d0", "#e07b00"]

    for ax, (na, nb), c in zip(axes, pairs, pair_colors):
        col_a = INDEX_CFG[na][0]
        col_b = INDEX_CFG[nb][0]
        la = INDEX_CFG[na][2]
        lb = INDEX_CFG[nb][2]

        da = results[na][["date", col_a]].rename(columns={col_a: "_a"})
        db = results[nb][["date", col_b]].rename(columns={col_b: "_b"})
        merged = da.merge(db, on="date").dropna()
        x = merged["_a"].values
        y = merged["_b"].values
        r = np.corrcoef(x, y)[0, 1]
        rmse = float(np.sqrt(np.mean((x - y) ** 2)))

        ax.scatter(x, y, s=5, alpha=0.35, color=c)
        lim = (-4.5, 3.5)
        ax.plot(lim, lim, "k--", lw=0.7, alpha=0.4)
        ax.axhline(-1, color="gray", lw=0.4, ls=":")
        ax.axvline(-1, color="gray", lw=0.4, ls=":")
        ax.set_xlim(lim); ax.set_ylim(lim)
        ax.set_xlabel(la, fontsize=8)
        ax.set_ylabel(lb, fontsize=8)
        ax.set_title(f"r={r:.3f}  RMSE={rmse:.3f}", fontsize=9)

    plt.tight_layout()
    if out_path:
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        print(f"  산점도: {out_path.name}")
    else:
        plt.show()
    plt.close()


# ── 메인 ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--station",        type=int, default=105)
    parser.add_argument("--year",           type=int, default=2025)
    parser.add_argument("--baseline_start", type=int, default=1991)
    parser.add_argument("--baseline_end",   type=int, default=2020)
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()

    station  = args.station
    year     = args.year
    baseline = (args.baseline_start, args.baseline_end)
    target   = (year, year)

    print(f"\n{'='*62}")
    print(f"  가뭄지수 비교: 지점 {station}, {year}년  기준기간 {baseline[0]}-{baseline[1]}")
    print(f"{'='*62}\n")

    df = load_data(station)

    print("① EDI (Byun & Wilhite 1999)")
    df_edi = run_edi(df, baseline_years=baseline, target_years=target)

    print("\n② CEDI (Kim et al. 2009)")
    df_cedi = run_cedi(df, baseline_years=baseline, target_years=target)

    print("\n③ scCEDI-K (현재)")
    df_sc = run_sccedik(df, target_year=year, fixed_baseline=baseline)

    print("\n④ 개선A (CEDI물리 + P3, 풀링 없음)")
    df_impA = run_improved_cedi(df, baseline_years=baseline, target_years=target,
                                pool_half=0)

    print("\n⑤ 개선B (CEDI물리 + P3, ±15일 풀링)")
    df_impB = run_improved_cedi(df, baseline_years=baseline, target_years=target,
                                pool_half=15)

    results = {
        "EDI":      df_edi,
        "CEDI":     df_cedi,
        "scCEDI-K": df_sc,
        "개선A":    df_impA,
        "개선B":    df_impB,
    }

    # ── 통계 ─────────────────────────────────────────────────────
    print(f"\n{'='*62}")
    print("  기초 통계")
    print(f"{'='*62}")
    stats = [
        drought_stats(df_edi["EDI"].values,            "① EDI"),
        drought_stats(df_cedi["CEDI"].values,           "② CEDI"),
        drought_stats(df_sc["scCEDI_K"].values,         "③ scCEDI-K"),
        drought_stats(df_impA["ImprovedCEDI"].values,   "④ 개선A"),
        drought_stats(df_impB["ImprovedCEDI"].values,   "⑤ 개선B"),
    ]
    print_stats(stats)

    # ── 상관계수 ─────────────────────────────────────────────────
    print(f"\n{'='*62}")
    print("  설계 축별 효과 (상관계수 / RMSE)")
    print(f"{'='*62}")
    for na, nb, desc in EFFECT_PAIRS:
        col_a = INDEX_CFG[na][0]
        col_b = INDEX_CFG[nb][0]
        da = results[na][["date", col_a]].rename(columns={col_a: "_a"})
        db = results[nb][["date", col_b]].rename(columns={col_b: "_b"})
        m = da.merge(db, on="date").dropna()
        x, y = m["_a"].values, m["_b"].values
        r    = np.corrcoef(x, y)[0, 1]
        rmse = np.sqrt(np.mean((x - y) ** 2))
        print(f"  {desc}")
        print(f"    {na} vs {nb}: r={r:.4f}  RMSE={rmse:.4f}")

    # ── 플롯 ─────────────────────────────────────────────────────
    if not args.no_plot:
        out_dir = PIPELINE / "data"
        out_dir.mkdir(exist_ok=True)
        tag = f"{station}_{year}"
        plot_timeseries(results, year, station,
                        out_path=out_dir / f"compare_{tag}.png")
        plot_effects(results, year, station,
                     out_path=out_dir / f"effects_{tag}.png")
        plot_scatter_matrix(results,
                            out_path=out_dir / f"scatter_{tag}.png")

    return results


if __name__ == "__main__":
    main()
