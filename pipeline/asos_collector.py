"""
ASOS 일강수량 수집기
기상청 지상(종관, ASOS) 일자료 조회서비스를 통해 지점별 일강수량을 수집한다.
"""

import time
import logging
from datetime import date, timedelta
from pathlib import Path

import requests
import pandas as pd

from config import API_BASE_URL, API_ENDPOINT, SERVICE_KEY_ENCODED, NUM_OF_ROWS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent / "data" / "processed"


def fetch_daily_precip(stn_id: int, start_dt: str, end_dt: str) -> pd.DataFrame:
    """
    단일 지점의 기간 내 일강수량을 조회한다.

    Parameters
    ----------
    stn_id   : 지점번호 (예: 105)
    start_dt : 조회 시작일 'YYYYMMDD'
    end_dt   : 조회 종료일 'YYYYMMDD'

    Returns
    -------
    pd.DataFrame : columns = [stn_id, stn_nm, tm, sumRn]
    """
    # 서비스키는 이미 인코딩된 값을 URL에 직접 삽입 (requests의 이중 인코딩 방지)
    base_url = f"{API_BASE_URL}{API_ENDPOINT}?serviceKey={SERVICE_KEY_ENCODED}"
    params = {
        "numOfRows": NUM_OF_ROWS,
        "pageNo": 1,
        "dataCd": "ASOS",
        "dateCd": "DAY",
        "startDt": start_dt,
        "endDt": end_dt,
        "stnIds": stn_id,
        "dataType": "JSON",
    }

    rows = []
    page = 1
    total_count = None

    while True:
        params["pageNo"] = page
        try:
            resp = requests.get(base_url, params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("API 요청 실패 (지점=%s, 페이지=%d): %s", stn_id, page, e)
            break

        data = resp.json()
        header = data["response"]["header"]
        if header["resultCode"] != "00":
            logger.error("API 오류 (지점=%s): %s", stn_id, header["resultMsg"])
            break

        body = data["response"]["body"]
        if total_count is None:
            total_count = int(body.get("totalCount", 0))
            logger.info("지점 %s: 총 %d건 조회", stn_id, total_count)

        items = body.get("items", {})
        if not items:
            break
        item_list = items.get("item", [])
        if isinstance(item_list, dict):
            item_list = [item_list]

        for item in item_list:
            rows.append({
                "stn_id": item.get("stnId", ""),
                "stn_nm": item.get("stnNm", ""),
                "date": item.get("tm", ""),
                "precip_mm": item.get("sumRn", ""),
            })

        fetched = (page - 1) * NUM_OF_ROWS + len(item_list)
        if fetched >= total_count:
            break
        page += 1
        time.sleep(0.2)  # API 호출 간 대기

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    df["precip_mm"] = pd.to_numeric(df["precip_mm"].replace("", None), errors="coerce")
    df = df.sort_values("date").reset_index(drop=True)
    return df


def collect_station_year(stn_id: int, year: int, save_raw: bool = True) -> pd.DataFrame:
    """
    단일 지점의 연간 일강수량을 수집하고 CSV로 저장한다.

    Parameters
    ----------
    stn_id   : 지점번호
    year     : 수집 연도
    save_raw : True이면 raw CSV 저장

    Returns
    -------
    pd.DataFrame
    """
    start_dt = f"{year}0101"
    end_dt_date = min(date(year, 12, 31), date.today() - timedelta(days=1))
    end_dt = end_dt_date.strftime("%Y%m%d")

    logger.info("수집 시작 | 지점: %s, 기간: %s ~ %s", stn_id, start_dt, end_dt)
    df = fetch_daily_precip(stn_id, start_dt, end_dt)

    if df.empty:
        logger.warning("수집된 데이터 없음 (지점=%s, 연도=%d)", stn_id, year)
        return df

    if save_raw:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        stn_nm = df["stn_nm"].iloc[0] if not df.empty else str(stn_id)
        raw_path = RAW_DIR / f"asos_precip_{stn_id}_{stn_nm}_{year}.csv"
        df.to_csv(raw_path, index=False, encoding="utf-8-sig")
        logger.info("저장 완료: %s", raw_path)

    return df


def summarize_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """일강수량 DataFrame을 월별 합계로 집계한다."""
    if df.empty:
        return df
    monthly = (
        df.assign(year_month=df["date"].dt.to_period("M"))
        .groupby(["stn_id", "stn_nm", "year_month"], as_index=False)["precip_mm"]
        .sum()
    )
    monthly["year_month"] = monthly["year_month"].astype(str)
    return monthly


if __name__ == "__main__":
    # 강릉(105) 2025년 강수량 수집 및 확인
    STN_ID = 105
    YEAR = 2025

    df_daily = collect_station_year(STN_ID, YEAR)

    if not df_daily.empty:
        print("\n===== 강릉(105) 2025년 일강수량 (상위 20건) =====")
        print(df_daily[["date", "precip_mm"]].head(20).to_string(index=False))

        # 강수 발생일만 필터
        rainy = df_daily[df_daily["precip_mm"] > 0].copy()
        print(f"\n강수 발생일 수: {len(rainy)}일")
        print(f"연간 누적 강수량: {rainy['precip_mm'].sum():.1f} mm")
        print(f"최대 일강수량: {rainy['precip_mm'].max():.1f} mm ({rainy.loc[rainy['precip_mm'].idxmax(), 'date'].strftime('%Y-%m-%d')})")

        print("\n===== 월별 강수량 집계 =====")
        monthly = summarize_monthly(df_daily)
        print(monthly[["year_month", "precip_mm"]].to_string(index=False))

        # 처리 결과 저장
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        out_path = PROCESSED_DIR / f"precip_monthly_{STN_ID}_{YEAR}.csv"
        monthly.to_csv(out_path, index=False, encoding="utf-8-sig")
        logger.info("월별 집계 저장: %s", out_path)
