"""
KMA API Hub - AWS 일통계 자료 수집기
https://apihub.kma.go.kr/api/typ01/url/sfc_aws_day.php
"""

import io
import logging
from datetime import date, timedelta
from pathlib import Path

import requests
import pandas as pd

logger = logging.getLogger(__name__)

AWS_URL = "https://apihub.kma.go.kr/api/typ01/url/sfc_aws_day.php"
AWS_AUTH_KEY = "gLP8LnKFSC2z_C5yhTgtsw"

RAW_DIR = Path(__file__).parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent / "data" / "processed"

COLUMNS = ["date", "stn_id", "lon", "lat", "ht", "precip_mm"]


def fetch_aws_precip(stn_id: int, start_dt: str, end_dt: str) -> pd.DataFrame:
    """
    AWS 일강수량 조회 (rn_day)

    Parameters
    ----------
    stn_id   : 지점번호 (예: 105)
    start_dt : 'YYYYMMDD'
    end_dt   : 'YYYYMMDD'
    """
    params = {
        "tm1": start_dt,
        "tm2": end_dt,
        "obs": "rn_day",
        "stn": stn_id,
        "disp": 0,
        "help": 0,
        "authKey": AWS_AUTH_KEY,
    }
    resp = requests.get(AWS_URL, params=params, timeout=30)
    resp.raise_for_status()

    # EUC-KR 디코딩 후 데이터 파싱
    text = resp.content.decode("euc-kr", errors="replace")
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        rows.append({
            "date": pd.to_datetime(parts[0], format="%Y%m%d"),
            "stn_id": int(parts[1]),
            "lon": float(parts[2]),
            "lat": float(parts[3]),
            "ht": float(parts[4]),
            "precip_mm": float(parts[5]),
            "stn_nm": parts[6] if len(parts) > 6 else "",
        })

    df = pd.DataFrame(rows)
    return df.sort_values("date").reset_index(drop=True) if not df.empty else df


def collect_aws_station_year(stn_id: int, year: int, save_raw: bool = True) -> pd.DataFrame:
    start_dt = f"{year}0101"
    end_dt = min(date(year, 12, 31), date.today() - timedelta(days=1)).strftime("%Y%m%d")

    logger.info("AWS 수집 | 지점: %s, 기간: %s ~ %s", stn_id, start_dt, end_dt)
    df = fetch_aws_precip(stn_id, start_dt, end_dt)

    if df.empty:
        logger.warning("수집된 데이터 없음 (지점=%s, 연도=%d)", stn_id, year)
        return df

    if save_raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        stn_nm = df["stn_nm"].iloc[0] if "stn_nm" in df.columns else str(stn_id)
        path = RAW_DIR / f"aws_precip_{stn_id}_{stn_nm}_{year}.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
        logger.info("저장 완료: %s", path)

    return df
