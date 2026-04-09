"""
ASOS 장기 일강수량 수집 (기후 평년값 계산용)
기간: 1990~2024 (EP 계산에 선행 364일이 필요하므로 1990년부터 수집)
"""

import logging
import time
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).parent))
from asos_collector import fetch_daily_precip

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


def collect_long_term(stn_id: int, start_year: int, end_year: int) -> pd.DataFrame:
    """
    여러 연도에 걸쳐 일강수량을 수집한다.
    ASOS API가 한 번에 최대 999건이므로 연도별로 분할 요청한다.
    """
    frames = []
    for year in range(start_year, end_year + 1):
        out_path = RAW_DIR / f"asos_precip_{stn_id}_{year}_raw.csv"
        if out_path.exists():
            df = pd.read_csv(out_path, parse_dates=["date"])
            logger.info("캐시 로드: %s (%d건)", out_path.name, len(df))
        else:
            df = fetch_daily_precip(stn_id, f"{year}0101", f"{year}1231")
            if df.empty:
                logger.warning("데이터 없음: %d년", year)
                continue
            df.to_csv(out_path, index=False, encoding="utf-8-sig")
            logger.info("저장: %s (%d건)", out_path.name, len(df))
            time.sleep(0.3)

        frames.append(df)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    return combined


if __name__ == "__main__":
    STN_ID = 105
    df = collect_long_term(STN_ID, 1990, 2024)
    logger.info("수집 완료: %d건 (%s ~ %s)",
                len(df), df["date"].min().date(), df["date"].max().date())

    out = RAW_DIR / f"asos_precip_{STN_ID}_1990_2024.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    logger.info("저장: %s", out)
