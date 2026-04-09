"""
원본 EDI vs scCEDI-K v2 비교 시각화
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from matplotlib import rcParams

rcParams["font.family"] = "AppleGothic"
rcParams["axes.unicode_minus"] = False

PROC_DIR = Path(__file__).parent / "data" / "processed"

# ── 데이터 로드 ──────────────────────────────────────────────────
edi_df = pd.read_csv(PROC_DIR / "edi_105_2025.csv", parse_dates=["date"])
sc_df  = pd.read_csv(PROC_DIR / "sccedik_105_2025.csv", parse_dates=["date"])

dates  = pd.DatetimeIndex(edi_df["date"])
precip = edi_df["precip_mm"].to_numpy()
edi    = edi_df["EDI"].to_numpy()
sccedik = sc_df["scCEDI_K"].to_numpy()
pc     = sc_df["precip_corrected"].to_numpy()

# ── Figure 설정 ──────────────────────────────────────────────────
fig = plt.figure(figsize=(16, 14))
fig.suptitle("강릉(105) 2025년  원본 EDI vs scCEDI-K v2 비교",
             fontsize=15, fontweight="bold", y=0.995)

gs = fig.add_gridspec(4, 1, hspace=0.42,
                      height_ratios=[1.0, 1.6, 1.0, 0.7])

month_fmt = mdates.DateFormatter("%m월")
month_loc = mdates.MonthLocator()

# ═══════════════════════════════════════════════════════════════════
# 패널 1: 일강수량 + 유출보정
# ═══════════════════════════════════════════════════════════════════
ax1 = fig.add_subplot(gs[0])
ax1.bar(dates, precip, color="#4C9BE8", width=1, alpha=0.75, label="일강수량", zorder=2)
runoff = precip - pc
heavy = runoff > 0.1
if heavy.any():
    ax1.bar(dates[heavy], runoff[heavy], bottom=pc[heavy],
            color="#FF6B6B", width=1, alpha=0.85, label="유출보정 감량분", zorder=3)
ax1.set_ylabel("mm", fontsize=10)
ax1.set_title("① 일강수량 및 유출보정 (α=0.2, 임계 80mm)", fontsize=11, loc="left")
ax1.legend(loc="upper left", fontsize=9, framealpha=0.9)
ax1.grid(axis="y", alpha=0.3)
ax1.set_xlim(dates[0], dates[-1])

# ═══════════════════════════════════════════════════════════════════
# 패널 2: EDI vs scCEDI-K 중첩
# ═══════════════════════════════════════════════════════════════════
ax2 = fig.add_subplot(gs[1], sharex=ax1)

# 등급 배경
bands = [
    (-3.5, -2.0, "#FF0000", 0.10, "극심 가뭄"),
    (-2.0, -1.5, "#FFA500", 0.10, "심한 가뭄"),
    (-1.5, -1.0, "#FFD700", 0.10, "보통 가뭄"),
    (-1.0,  1.0, "#F0F8F0", 0.15, "정상"),
    ( 1.0,  1.5, "#87CEEB", 0.10, "약한 습윤"),
    ( 1.5,  2.0, "#4169E1", 0.10, "심한 습윤"),
    ( 2.0,  3.5, "#0000FF", 0.10, "극심 습윤"),
]
for lo, hi, color, alpha, lbl in bands:
    ax2.axhspan(lo, hi, alpha=alpha, color=color, zorder=0)
    mid = (lo + hi) / 2
    ax2.text(dates[-1] + pd.Timedelta(days=3), mid, lbl,
             va="center", fontsize=8, color="dimgray", clip_on=False)

# 원본 EDI — 회색 면적
edi_pos = np.where(edi >= 0, edi, 0)
edi_neg = np.where(edi < 0, edi, 0)
ax2.fill_between(dates, 0, edi_pos, color="#B0BEC5", alpha=0.35, step="mid")
ax2.fill_between(dates, 0, edi_neg, color="#B0BEC5", alpha=0.35, step="mid")
ax2.plot(dates, edi, color="#78909C", lw=1.8, label="원본 EDI", zorder=4)

# scCEDI-K — 컬러 면적
sc_pos = np.where(sccedik >= 0, sccedik, 0)
sc_neg = np.where(sccedik < 0, sccedik, 0)
ax2.fill_between(dates, 0, sc_pos, color="#2196F3", alpha=0.25, step="mid")
ax2.fill_between(dates, 0, sc_neg, color="#E53935", alpha=0.25, step="mid")
ax2.plot(dates, sccedik, color="#1B5E20", lw=1.8, label="scCEDI-K v2", zorder=5)

# 기준선
for y, c, ls in [(0, "gray", "--"), (-1.0, "#FFA500", ":"),
                  (-2.0, "#FF0000", ":"), (1.0, "#4169E1", ":")]:
    ax2.axhline(y, color=c, lw=0.8, ls=ls, zorder=1)

# 최소값 마커
edi_min_idx = np.nanargmin(edi)
sc_min_idx  = np.nanargmin(sccedik)
ax2.annotate(f"EDI min\n{edi[edi_min_idx]:.2f}",
             xy=(dates[edi_min_idx], edi[edi_min_idx]),
             xytext=(dates[edi_min_idx] + pd.Timedelta(days=20), edi[edi_min_idx] + 0.5),
             arrowprops=dict(arrowstyle="->", color="#78909C", lw=1.2),
             fontsize=9, color="#78909C", fontweight="bold", zorder=6)
ax2.annotate(f"scCEDI-K min\n{sccedik[sc_min_idx]:.2f}",
             xy=(dates[sc_min_idx], sccedik[sc_min_idx]),
             xytext=(dates[sc_min_idx] - pd.Timedelta(days=50), sccedik[sc_min_idx] + 0.6),
             arrowprops=dict(arrowstyle="->", color="#1B5E20", lw=1.2),
             fontsize=9, color="#1B5E20", fontweight="bold", zorder=6)

ax2.set_ylabel("지수값", fontsize=10)
ax2.set_ylim(-3.5, 3.5)
ax2.set_title("② 원본 EDI vs scCEDI-K v2", fontsize=11, loc="left")
ax2.legend(loc="upper left", fontsize=10, framealpha=0.9)
ax2.grid(axis="y", alpha=0.2)

# ═══════════════════════════════════════════════════════════════════
# 패널 3: 차이 (scCEDI-K - EDI)
# ═══════════════════════════════════════════════════════════════════
ax3 = fig.add_subplot(gs[2], sharex=ax1)
diff = sccedik - edi
ax3.fill_between(dates, 0, diff, where=diff >= 0,
                 color="#2196F3", alpha=0.4, step="mid",
                 label="scCEDI-K가 더 습윤")
ax3.fill_between(dates, 0, diff, where=diff < 0,
                 color="#E53935", alpha=0.4, step="mid",
                 label="scCEDI-K가 더 건조")
ax3.plot(dates, diff, color="#263238", lw=0.7, alpha=0.6)
ax3.axhline(0, color="gray", lw=0.8, ls="--")
ax3.set_ylabel("scCEDI-K  −  EDI", fontsize=10)
ax3.set_title("③ 차이 (음수 → scCEDI-K가 가뭄을 더 심하게 평가)", fontsize=11, loc="left")
ax3.legend(loc="lower left", fontsize=9, framealpha=0.9)
ax3.grid(axis="y", alpha=0.3)

# ═══════════════════════════════════════════════════════════════════
# 패널 4: 등급별 일수 비교 (가로 막대)
# ═══════════════════════════════════════════════════════════════════
ax4 = fig.add_subplot(gs[3])

cat_labels = ["극심 가뭄\n(< −2.0)", "심한 가뭄\n(−2.0~−1.5)",
              "보통 가뭄\n(−1.5~−1.0)", "정상\n(−1.0~1.0)",
              "습윤\n(> 1.0)"]
cat_bounds = [(-np.inf, -2.0), (-2.0, -1.5), (-1.5, -1.0), (-1.0, 1.0), (1.0, np.inf)]
cat_colors = ["#FF0000", "#FFA500", "#FFD700", "#A5D6A7", "#42A5F5"]

edi_counts = []
sc_counts  = []
for lo, hi in cat_bounds:
    edi_v = edi[~np.isnan(edi)]
    sc_v  = sccedik[~np.isnan(sccedik)]
    edi_counts.append(((edi_v >= lo) & (edi_v < hi)).sum())
    sc_counts.append(((sc_v >= lo) & (sc_v < hi)).sum())

y_pos = np.arange(len(cat_labels))
bar_h = 0.35
bars1 = ax4.barh(y_pos + bar_h/2, edi_counts, bar_h,
                 color="#B0BEC5", edgecolor="white", label="원본 EDI")
bars2 = ax4.barh(y_pos - bar_h/2, sc_counts, bar_h,
                 color=[cat_colors[i] for i in range(len(cat_labels))],
                 edgecolor="white", label="scCEDI-K v2")

for bar, cnt in zip(bars1, edi_counts):
    if cnt > 0:
        ax4.text(bar.get_width() + 2, bar.get_y() + bar.get_height()/2,
                 f"{cnt}일", va="center", fontsize=9, color="#78909C", fontweight="bold")
for bar, cnt in zip(bars2, sc_counts):
    if cnt > 0:
        ax4.text(bar.get_width() + 2, bar.get_y() + bar.get_height()/2,
                 f"{cnt}일", va="center", fontsize=9, color="#263238", fontweight="bold")

ax4.set_yticks(y_pos)
ax4.set_yticklabels(cat_labels, fontsize=9)
ax4.set_xlabel("일수", fontsize=10)
ax4.set_title("④ 등급별 일수 비교", fontsize=11, loc="left")
ax4.legend(loc="center right", fontsize=9, framealpha=0.9)
ax4.grid(axis="x", alpha=0.3)
ax4.invert_yaxis()

# X축 정리
for ax in [ax1, ax2, ax3]:
    ax.xaxis.set_major_locator(month_loc)
    ax.xaxis.set_major_formatter(month_fmt)
plt.setp(ax1.get_xticklabels(), visible=False)
plt.setp(ax2.get_xticklabels(), visible=False)

# 하단 주석
fig.text(0.5, 0.005,
         "기후 평년: Rolling 30년 (1995–2024)  |  표준화: 비모수 경험적 CDF (±15일 풀링)  |  유출보정: α=0.2, 임계 80mm",
         ha="center", fontsize=9, color="dimgray", style="italic")

out = PROC_DIR / "comparison_edi_sccedik_105_2025.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
print(f"저장: {out}")
plt.show()
