"""
Generate the final 2010-2025 figure for Gangneung(105):
precipitation, EDI, CEDI, SPI-6, and SPI-3.
"""

from pathlib import Path

import matplotlib as mpl
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from cedi_algorithm import run_cedi
from edi_algorithm import run_edi
from run_longterm_cedi_pit import compute_spi_daily, load_data


STATION = 105
YEAR_S = 2010
YEAR_E = 2025
BASELINE = (1973, YEAR_E - 1)

ROOT = Path(__file__).parent.parent
OUT_DIR = ROOT / "outputs"
OUT_DIR.mkdir(exist_ok=True)


def set_korean_font() -> None:
    import matplotlib.font_manager as fm

    installed = {font.name for font in fm.fontManager.ttflist}
    for name in [
        "Malgun Gothic",
        "Apple SD Gothic Neo",
        "AppleGothic",
        "NanumGothic",
        "Noto Sans CJK KR",
    ]:
        if name in installed:
            mpl.rcParams["font.family"] = name
            break
    mpl.rcParams["axes.unicode_minus"] = False


def add_index_panel(ax, dates: pd.Series, values: np.ndarray, color: str, label: str, title: str) -> None:
    ax.fill_between(
        dates,
        np.minimum(values, -2.0),
        -2.0,
        where=values < -2.0,
        color="#cc0000",
        alpha=0.30,
    )
    ax.fill_between(
        dates,
        np.clip(values, -2.0, -1.0),
        -1.0,
        where=values < -1.0,
        color="#ffa500",
        alpha=0.18,
    )
    ax.plot(dates, values, color=color, lw=0.8, label=label, alpha=0.95)
    ax.axhline(0, color="gray", lw=0.5, ls="--")
    ax.axhline(-1.0, color="#ffa500", lw=0.6, ls=":")
    ax.axhline(-2.0, color="#cc0000", lw=0.6, ls=":")
    ax.set_ylim(-4.5, 3.5)
    ax.set_ylabel(label, fontsize=11)
    ax.set_title(title, fontsize=12, loc="left")
    ax.legend(loc="lower right", fontsize=10)
    ax.grid(axis="y", alpha=0.25)


def set_xaxis(ax, x_start: pd.Timestamp, x_end: pd.Timestamp, show_labels: bool) -> None:
    ax.set_xlim(x_start, x_end)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[1, 7]))
    ax.tick_params(axis="x", labelsize=9, labelbottom=show_labels)
    ax.grid(axis="x", which="major", color="gray", lw=0.35, alpha=0.4)
    ax.grid(axis="x", which="minor", color="gray", lw=0.2, alpha=0.2)


def main() -> None:
    set_korean_font()

    print(f"\n{'=' * 60}")
    print(f"  Final figure: Gangneung({STATION}) {YEAR_S}-{YEAR_E}")
    print(f"  Variables: precipitation, EDI, CEDI, SPI-6, SPI-3")
    print(f"  Baseline: {BASELINE[0]}-{BASELINE[1]}")
    print(f"{'=' * 60}\n")

    df = load_data(STATION)

    print("1) EDI")
    df_edi = run_edi(df, baseline_years=BASELINE, target_years=(YEAR_S, YEAR_E))

    print("\n2) CEDI")
    df_cedi = run_cedi(df, baseline_years=BASELINE, target_years=(YEAR_S, YEAR_E))

    print("\n3) SPI-6")
    df_spi6 = compute_spi_daily(df, 6, BASELINE, YEAR_S, YEAR_E)

    print("\n4) SPI-3")
    df_spi3 = compute_spi_daily(df, 3, BASELINE, YEAR_S, YEAR_E)

    merged = (
        df_cedi[["date", "precip_mm", "CEDI"]]
        .merge(df_edi[["date", "EDI"]], on="date", how="left")
        .merge(df_spi6.rename(columns={"SPI": "SPI6"}), on="date", how="left")
        .merge(df_spi3.rename(columns={"SPI": "SPI3"}), on="date", how="left")
    )

    csv_path = OUT_DIR / f"final_figure_data_강릉{STATION}_{YEAR_S}-{YEAR_E}.csv"
    merged.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n  csv: {csv_path.name}")

    x_start = pd.Timestamp(f"{YEAR_S}-01-01")
    x_end = pd.Timestamp(f"{YEAR_E}-12-31")

    fig, axes = plt.subplots(
        5,
        1,
        figsize=(22, 20),
        sharex=True,
        gridspec_kw={"height_ratios": [1.0, 2.0, 2.0, 2.0, 2.0], "hspace": 0.28},
    )

    fig.suptitle(
        f"강릉({STATION}) {YEAR_S}-{YEAR_E} 강수량 / EDI / CEDI / SPI6 / SPI3\n"
        f"baseline: {BASELINE[0]}-{BASELINE[1]}",
        fontsize=16,
        y=0.995,
    )

    ax0 = axes[0]
    ax0.bar(merged["date"], merged["precip_mm"], color="steelblue", alpha=0.65, width=1.0, label="강수량")
    ax0.set_ylim(max(merged["precip_mm"].max() * 1.1, 10), 0)
    ax0.set_ylabel("강수량\n(mm)", fontsize=11, color="steelblue")
    ax0.tick_params(axis="y", labelcolor="steelblue", labelsize=10)
    ax0.legend(loc="upper right", fontsize=10)
    ax0.set_title("강수량", fontsize=12, loc="left")
    set_xaxis(ax0, x_start, x_end, show_labels=False)

    add_index_panel(axes[1], merged["date"], merged["EDI"].to_numpy(), "#4c78a8", "EDI", "EDI")
    set_xaxis(axes[1], x_start, x_end, show_labels=False)

    add_index_panel(axes[2], merged["date"], merged["CEDI"].to_numpy(), "#1f7a8c", "CEDI", "CEDI")
    set_xaxis(axes[2], x_start, x_end, show_labels=False)

    add_index_panel(axes[3], merged["date"], merged["SPI6"].to_numpy(), "#e07a00", "SPI6", "SPI-6")
    set_xaxis(axes[3], x_start, x_end, show_labels=False)

    add_index_panel(axes[4], merged["date"], merged["SPI3"].to_numpy(), "#7b2cbf", "SPI3", "SPI-3")
    set_xaxis(axes[4], x_start, x_end, show_labels=True)

    out_path = OUT_DIR / f"final_figure_강릉{STATION}_{YEAR_S}-{YEAR_E}.png"
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)

    print(f"  plot: {out_path.name}")


if __name__ == "__main__":
    main()
