"""
한국농어촌공사 전국 저수지 일별 저수율 API
강릉 오봉저수지 데이터 수집 (2021~2025)

Base URL: api.odcloud.kr/api/15113475/v1
"""

import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

# ── 설정 ──────────────────────────────────────────────────────────────
SERVICE_KEY = (
    "srSOK9cObNO3sLOLvEgLZKnNAVRD2akPvPP67gxM4k2QHE3TNEhdn71RKjNtWmKg4"
    "wT5iNiUDgCkdakcC8%2Fxog%3D%3D"
)

ENDPOINTS = {
    2021: "uddi:5e710667-f395-4e69-bbc8-83a722145f37",
    2022: "uddi:da54b980-2ba1-46fa-8778-87ed219c87bc",
    2023: "uddi:b83ab95d-bc69-40b7-bd9f-9453ae6a6fa7",
    2024: "uddi:9f7a9d8f-4424-4c03-b33b-dd316abf8b68",
    2025: "uddi:3be0a754-1099-4dff-bdf0-e4902de3f2f7",
}

BASE_URL = "https://api.odcloud.kr/api/15113475/v1"
PER_PAGE = 500
TARGET_NAME = "오봉"
TARGET_LOC  = "강릉"

OUT_DIR = Path(__file__).parent.parent / "outputs"
OUT_DIR.mkdir(exist_ok=True)


# ── API 호출 ──────────────────────────────────────────────────────────
def fetch_all_pages(endpoint: str, year: int) -> list[dict]:
    """한 연도 엔드포인트의 전체 레코드 수집."""
    records = []
    page = 1
    while True:
        url = (f"{BASE_URL}/{endpoint}"
               f"?page={page}&perPage={PER_PAGE}&serviceKey={SERVICE_KEY}")
        with urllib.request.urlopen(url, timeout=30) as resp:
            d = json.load(resp)
        batch = d.get("data", [])
        records.extend(batch)
        total = d.get("totalCount", 0)
        if len(records) >= total or not batch:
            break
        page += 1
        time.sleep(0.2)
    return records


def find_reservoir(records: list[dict], name: str, loc: str) -> dict | None:
    """저수지명 + 위치로 레코드 탐색."""
    for r in records:
        if name in r.get("저수지명", "") and loc in r.get("위치", ""):
            return r
    return None


# ── 변환: wide → long ─────────────────────────────────────────────────
def record_to_series(record: dict) -> pd.DataFrame:
    """레코드(날짜별 저수율 wide 형식) → (date, storage_rate) long 형식."""
    rows = []
    for k, v in record.items():
        if k.startswith("20"):          # 날짜 컬럼
            try:
                rows.append({
                    "date":         pd.Timestamp(k),
                    "storage_rate": float(v) if v not in (None, "", "-") else None,
                })
            except (ValueError, TypeError):
                pass
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return df


# ── 메인 ──────────────────────────────────────────────────────────────
def main():
    print(f"\n{'='*55}")
    print(f"  한국농어촌공사 저수율 수집: {TARGET_LOC} {TARGET_NAME}저수지")
    print(f"{'='*55}\n")

    frames = []

    for year, endpoint in ENDPOINTS.items():
        print(f"[{year}] 수집 중...", end=" ", flush=True)
        records = fetch_all_pages(endpoint, year)
        row = find_reservoir(records, TARGET_NAME, TARGET_LOC)

        if row is None:
            print(f"→ {TARGET_NAME}저수지 없음 (건너뜀)")
            continue

        loc  = row.get("위치", "")
        cap  = row.get("유효저수량(천m3)", "")
        df_y = record_to_series(row)
        frames.append(df_y)
        valid = df_y["storage_rate"].notna().sum()
        print(f"→ {valid}일  |  위치: {loc}  |  유효저수량: {cap}천m3")

    if not frames:
        print("수집된 데이터 없음")
        return

    # 병합 및 중복 제거
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)

    # 기간 요약
    start = df["date"].min().date()
    end   = df["date"].max().date()
    total = len(df)
    missing = df["storage_rate"].isna().sum()

    print(f"\n  수집 기간: {start} ~ {end}  ({total}일)")
    print(f"  결측: {missing}일  ({missing/total*100:.1f}%)")
    print(f"\n  저수율 통계:")
    desc = df["storage_rate"].describe()
    print(f"    평균: {desc['mean']:.1f}%  |  최솟값: {desc['min']:.1f}%  |  최댓값: {desc['max']:.1f}%")
    print(f"    25%: {desc['25%']:.1f}%  |  중앙값: {desc['50%']:.1f}%  |  75%: {desc['75%']:.1f}%")

    # 저장
    out_path = OUT_DIR / f"저수율_강릉오봉_{start.year}-{end.year}.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n  저장: {out_path.name}")


if __name__ == "__main__":
    main()
