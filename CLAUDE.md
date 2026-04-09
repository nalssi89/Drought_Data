# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Korean meteorological drought index research project** implementing and comparing multiple drought indices:
- **EDI** — Byun & Wilhite (1999) original algorithm
- **CEDI** — Kim et al. (2009) corrected EDI with time-decay runoff correction
- **scCEDI-K v2** — The project's confirmed algorithm: statistically-corrected CEDI for Korea

All code lives in `pipeline/`. Directory layout:
- `docs/papers/` — 원본 PDF 논문
- `docs/notes/` — 논문 요약 및 개념 정리 MD
- `docs/reports/` — 검증 보고서 MD
- `docs/brainstorming/` — AI 브레인스토밍 노트

## Running the Pipeline

All scripts must be run from inside the `pipeline/` directory (imports use relative paths):

```bash
cd pipeline

# 1. Collect historical precipitation (1990–2024) for a station
python collect_historical.py       # defaults to station 105 (강릉)

# 2. Collect current year data
python asos_collector.py           # defaults to station 105, current year

# 3. Compute scCEDI-K v2 and compare with original EDI
python run_sccedik_2025.py         # station 105 (강릉), 2025

# 4. Compare all 5 drought indices side-by-side
python run_drought_compare.py --station 105 --year 2025

# 5. Compute original EDI only
python run_edi_2025.py

# 6. Long-term comparison across stations/years
python run_longterm_compare.py
```

Data is stored under `pipeline/data/raw/` (CSV per station/year) and `pipeline/data/processed/` (computed indices, plots).

## Architecture

### Core Algorithm: scCEDI-K v2 (`sccedik.py`)

Five-step pipeline in `run_sccedik()`:
1. **Input**: Daily precipitation `P(t)`
2. **Runoff correction** → `Pc(t)`: threshold = `max(80mm, P95 of wet days)`; method `"alpha"` (Kim 2009) or `"tau"` (ACE-EDI style)
3. **CEP** (Corrected Effective Precipitation): harmonic-weighted accumulation over DS=365 days fixed
4. **Standardization**: DCEP = CEP − calendar mean; L-moment Pearson III fit on ±15-day calendar pooling of the baseline period; PIT → `Φ⁻¹(F)` = scCEDI-K
5. **Auxiliary**: PRN (precipitation needed to normalize), 90-day precipitation ratio, dry duration

Key design decisions:
- DS=365 is **fixed** (no extension during drought) — avoids double-counting with P3 tail representation
- Baseline: WMO standard 1991–2020 (fixed) or rolling 30-year
- L-moment fitting (`_fit_pearson3_lmom`) uses Hosking & Wallis (1997) numerical approximation for robustness against outliers

### Algorithm Variants (`cedi_algorithm.py`, `improved_cedi.py`, `edi_algorithm.py`)

| Module | Algorithm | Runoff correction | Standardization |
|--------|-----------|-------------------|-----------------|
| `edi_algorithm.py` | EDI (원형) | None | z-score |
| `cedi_algorithm.py` | CEDI | Time-decay `e^{-0.5(m-1)}` | z-score |
| `improved_cedi.py` | Improved CEDI | Time-decay (CEDI) | L-moment P3 |
| `sccedik.py` | scCEDI-K v2 | α instantaneous | L-moment P3 |

`improved_cedi.py` imports from both `cedi_algorithm.py` and `sccedik.py`.

### Data Collection (`asos_collector.py`, `collect_historical.py`, `aws_collector.py`)

- Source: KMA ASOS API (`apis.data.go.kr`) — API key stored in `config.py`
- Station IDs (Korean KMA numbers) defined in `config.py::STATIONS`
- Raw CSVs: `data/raw/asos_precip_{stn_id}_{year}_raw.csv`
- Historical combined: `data/raw/asos_precip_{stn_id}_1990_2024.csv`
- CEP computation needs 364 days of lead-in, so historical data starts from 1990 even when the baseline is 1991–2020

## Key Conventions

- All drought index DataFrames output columns: `date, precip_mm, precip_corrected, CEP, MEP_rolling, DCEP, scCEDI_K, dry_dur, DS, PRN, precip_ratio_90d`
- Korean fonts required for plots: `matplotlib.rcParams["font.family"] = "AppleGothic"` (macOS)
- CSV encoding: `utf-8-sig` (for Korean Excel compatibility)
- Drought thresholds: `< -2.0` extreme, `< -1.5` severe, `< -1.0` moderate

## Scope Constraints

Per project decisions:
- Focus is on **meteorological drought improvement only** (강수량 기반)
- Flash drought indicators are **excluded** from the main index
- No coupling with agricultural or water resource capacity data
