from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import rcParams

rcParams["font.family"] = "AppleGothic"
rcParams["axes.unicode_minus"] = False

BASE_DIR = Path(__file__).parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROC_DIR = BASE_DIR / "data" / "processed"

STN_ID = 108
STN_NAME = "서울"

CASES = [
    ("2006-07-01", "2006-12-31", "2006: 7월 집중호우 후 가을 재건조"),
    ("2014-07-01", "2015-12-31", "2014H2-2015: 장기 서울 가뭄"),
]


def load_precip() -> pd.DataFrame:
    frames = []
    for file_path in sorted(RAW_DIR.glob(f"asos_precip_{STN_ID}_*_raw.csv")):
        frames.append(
            pd.read_csv(file_path, parse_dates=["date"])[["date", "precip_mm"]]
        )
    if not frames:
        raise FileNotFoundError(
            f"No raw precipitation files found for station {STN_ID}"
        )

    df = pd.concat(frames, ignore_index=True)
    return df.sort_values("date").drop_duplicates("date").reset_index(drop=True)


def load_indices() -> pd.DataFrame:
    edi = pd.read_csv(
        PROC_DIR / f"edi_long_{STN_ID}_1990_2025.csv", parse_dates=["date"]
    )
    sc = pd.read_csv(
        PROC_DIR / f"sccedik_long_{STN_ID}_1990_2025.csv", parse_dates=["date"]
    )
    return edi.merge(sc, on="date", how="inner")


def draw_bands(ax) -> None:
    bands = [
        (-3.5, -2.0, "#FF0000"),
        (-2.0, -1.5, "#FFA500"),
        (-1.5, -1.0, "#FFD700"),
        (-1.0, 1.0, "#F0F8F0"),
        (1.0, 1.5, "#87CEEB"),
        (1.5, 2.0, "#4169E1"),
        (2.0, 3.5, "#0000FF"),
    ]
    for lo, hi, color in bands:
        ax.axhspan(lo, hi, alpha=0.08, color=color, zorder=0)


def set_case_axis_format(ax, start: str, end: str) -> None:
    span_days = (pd.Timestamp(end) - pd.Timestamp(start)).days
    if span_days <= 220:
        locator = mdates.MonthLocator(interval=1)
        formatter = mdates.DateFormatter("%Y-%m")
    else:
        locator = mdates.MonthLocator(interval=2)
        formatter = mdates.DateFormatter("%Y-%m")
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)


def main() -> None:
    precip = load_precip()
    merged = load_indices().merge(precip, on="date", how="left")

    fig = plt.figure(figsize=(18, 14))
    fig.suptitle(
        f"{STN_NAME}({STN_ID}) ASOS 기반 사례 비교: 일강수량 + 원본 EDI vs scCEDI-K",
        fontsize=16,
        fontweight="bold",
        y=0.995,
    )

    gs = fig.add_gridspec(4, 1, height_ratios=[0.9, 1.4, 0.9, 1.4], hspace=0.28)
    axes = [fig.add_subplot(gs[i]) for i in range(4)]

    for idx, (start, end, title) in enumerate(CASES):
        case_df = merged[(merged["date"] >= start) & (merged["date"] <= end)].copy()
        date_vals = list(case_df["date"])
        precip_vals = [0.0 if pd.isna(v) else float(v) for v in case_df["precip_mm"]]
        edi_vals = [np.nan if pd.isna(v) else float(v) for v in case_df["EDI"]]
        sc_vals = [np.nan if pd.isna(v) else float(v) for v in case_df["scCEDI_K"]]

        ax_p = axes[idx * 2]
        ax_i = axes[idx * 2 + 1]

        ax_p.bar(
            date_vals,
            precip_vals,
            width=1.0,
            color="#4C9BE8",
            alpha=0.8,
            label="일강수량 (ASOS)",
        )
        ax_p.set_ylabel("강수량 (mm)")
        ax_p.set_title(title, loc="left", fontsize=12, fontweight="bold")
        ax_p.legend(loc="upper right", fontsize=9)
        ax_p.grid(axis="y", alpha=0.25)
        set_case_axis_format(ax_p, start, end)

        draw_bands(ax_i)
        ax_i.plot(
            date_vals,
            edi_vals,
            color="#666666",
            lw=1.2,
            ls="--",
            label="원본 EDI",
        )
        ax_i.plot(
            date_vals,
            sc_vals,
            color="#1B5E20",
            lw=1.5,
            label="scCEDI-K",
        )
        ax_i.axhline(0, color="gray", lw=0.8, ls="--")
        ax_i.axhline(-1.0, color="#FFA500", lw=0.8, ls=":")
        ax_i.axhline(-2.0, color="#FF0000", lw=0.8, ls=":")
        ax_i.set_ylabel("지수값")
        ax_i.set_ylim(-3.5, 3.5)
        ax_i.legend(loc="upper right", fontsize=9)
        ax_i.grid(alpha=0.25)
        set_case_axis_format(ax_i, start, end)

        if idx == 0:
            plt.setp(ax_p.get_xticklabels(), visible=False)
            plt.setp(ax_i.get_xticklabels(), visible=False)
        elif idx == 1:
            plt.setp(ax_p.get_xticklabels(), visible=False)

    out_path = PROC_DIR / "seoul_108_case_compare_with_daily_precip.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"saved {out_path}")


if __name__ == "__main__":
    main()
