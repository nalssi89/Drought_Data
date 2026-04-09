# 기상 가뭄지수 연구 파이프라인

한국 기상 가뭄지수 개선 연구 — EDI → CEDI → scCEDI-K v2 알고리즘 구현 및 비교

---

## 프로젝트 개요

기상청 ASOS 일강수량 자료를 이용해 가뭄지수를 계산하고 비교하는 연구용 파이프라인입니다.

**목표**: 현업 가뭄지수(EDI/CEDI)의 한계를 파악하고 통계적으로 개선된 지수(scCEDI-K v2)를 개발

**대상 지수**:
| 지수 | 논문 | 핵심 특징 |
|------|------|-----------|
| EDI | Byun & Wilhite (1999) | 조화급수 가중 유효강수량, z-score 표준화 |
| CEDI | Kim et al. (2009) | EDI + 집중호우 유출보정 + DS 확장 |
| scCEDI-K v2 | 본 연구 | CEDI + L-moment P3 표준화 |
| CEDI+pool | 본 연구 | CEDI + 달력일 풀링 z-score |
| SPI | McKee et al. (1993) | 감마분포 PIT, n개월 누적강수량 |

---

## 디렉터리 구조

```
Drought_Data/
├── pipeline/                   # 전체 소스코드
│   ├── config.py               # API 키, ASOS 지점 목록
│   ├── asos_collector.py       # ASOS API 일강수량 수집
│   ├── aws_collector.py        # AWS(방재기상) 수집
│   ├── collect_historical.py   # 장기 과거 자료 수집 (1973~현재)
│   ├── collect_reservoir_obong.py  # 오봉저수지 저수율 수집
│   │
│   ├── edi_algorithm.py        # EDI 원본 알고리즘 (Byun 1999)
│   ├── cedi_algorithm.py       # CEDI 알고리즘 (Kim 2009)
│   ├── sccedik.py              # scCEDI-K v2 (확정 알고리즘)
│   ├── improved_cedi.py        # Improved CEDI (실험용)
│   │
│   ├── run_edi_2025.py         # EDI 단독 실행
│   ├── run_sccedik_2025.py     # scCEDI-K v2 실행
│   ├── run_edi_cedi.py         # EDI vs CEDI 비교
│   ├── run_drought_compare.py  # 전체 지수 비교
│   ├── run_longterm_compare.py # 장기 비교
│   ├── run_longterm_cedi_pit.py  # CEDI / 풀링 / PIT / SPI 장기비교 (메인)
│   │
│   ├── plot_comparison.py      # 시각화 유틸
│   ├── compare_asos_aws.py     # ASOS/AWS 자료 비교
│   │
│   ├── data/
│   │   ├── raw/                # ASOS 원시 CSV (지점별·연도별)
│   │   └── processed/          # 계산 결과 CSV, PNG
│
├── outputs/                    # 최종 결과물 (PNG, CSV)
├── docs/
│   ├── papers/                 # 참고 논문 PDF
│   ├── notes/                  # 알고리즘 개념 정리
│   ├── reports/                # 검증 보고서
│   └── brainstorming/          # 분석 노트
└── README.md
```

---

## 환경 설정

### 요구 사항

```bash
Python >= 3.10
pip install pandas numpy scipy matplotlib
```

### API 키 설정

`pipeline/config.py`의 `SERVICE_KEY_ENCODED`를 공공데이터포털에서 발급받은 키로 교체합니다.

```
https://www.data.go.kr → 기상청 지상(종관) ASOS 일자료 조회서비스 신청
```

---

## 빠른 시작

모든 스크립트는 `pipeline/` 디렉터리에서 실행합니다.

```bash
cd pipeline
```

### Step 1. 과거 강수량 수집

```bash
# 1973~2024년 일강수량 수집 (강릉 105번 지점)
python collect_historical.py
# → data/raw/asos_precip_105_{year}_raw.csv 생성 (연도별 캐시)
```

### Step 2. 당해연도 자료 수집

```bash
# 당해연도 실시간 수집
python asos_collector.py
# → data/raw/asos_precip_105_{year}_raw.csv
```

### Step 3. 장기 비교 실행 (메인)

```bash
python run_longterm_cedi_pit.py
# → outputs/CEDI_PIT_SPI_longterm_강릉105_{YEAR_S}-{YEAR_E}.png
# → outputs/CEDI_PIT_longterm_강릉105_{YEAR_S}-{YEAR_E}.csv
```

### Step 4. 기타 비교

```bash
# EDI vs CEDI 내부 변수 비교
python run_edi_cedi.py

# scCEDI-K v2 단독 실행
python run_sccedik_2025.py

# 전체 지수 나란히 비교
python run_drought_compare.py --station 105 --year 2025
```

---

## 알고리즘 상세

### 1. EDI — Byun & Wilhite (1999)

유효강수량(EP)을 조화급수 가중치로 누적한 뒤 z-score 표준화.

```
EP(t) = Σ(n=1→DS) [ Σ(m=1→n) P(t-m+1) / n ]
      = Σ(m=1→DS) P(t-m+1) × [H(DS) - H(m-1)]

H(k) = 1 + 1/2 + ... + 1/k  (조화급수)
DS   = 365 (기본), 가뭄 시 확장

EDI = (EP - MEP) / σ_EP
```

`edi_algorithm.py` → `run_edi()`

---

### 2. CEDI — Kim et al. (2009)

EDI에 **집중호우 유출보정**과 **DS 확장** 추가.

```
[유출보정]
Pc(m) = min(P, 80) + max(P-80, 0) × exp(-0.5×(m-1))
  → 집중호우 초과분을 시간감쇠로 처리 (80mm 임계값)

[CEP 계산]  DS=365 고정
CEP(t) = Σ(m=1→DS) Pc(t-m+1) × [H(DS) - H(m-1)]

[표준화]
SEP = (CEP - MEP) / σ_CEP
dry_duration: SEP < 0 연속일수
DS_ext = 365 + dry_duration - 1  ← 가뭄 시 창 확장

CEP_ext: 확장 DS로 재계산
CEDI = (CEP_ext - MEP) / σ_PRN
```

`cedi_algorithm.py` → `run_cedi()`

**DS 확장의 한계**: 과거 습윤기를 포함하게 되어 CEP가 과대 추정될 수 있음 → 2022년 강릉 사례에서 실제 가뭄을 음폐하는 문제 확인

---

### 3. CEDI+pool — 본 연구

CEDI 파이프라인에서 표준화 단계만 교체. DS 확장은 유지.

```
[기존 CEDI 표준화]
σ_PRN(d): 달력일 d의 기준기간 표본만 사용 (~52개)

[CEDI+pool 표준화]
pool_days = {d-15, ..., d, ..., d+15}  (원형, 연말/연초 처리)
pool_vals = 기준기간 × pool_days의 PRN값 (~1612개)

mu    = pool_vals.mean()
sigma = pool_vals.std(ddof=1)
CEDI_pool = (PRN - mu) / sigma
```

**장점**: 표본 수 증가(52→1612)로 σ 추정 안정화, 날짜 간 불연속 감소

`run_longterm_cedi_pit.py` → `run_cedi_pool()`

---

### 4. scCEDI-K v2 — 본 연구 (확정 알고리즘)

CEDI의 DS 확장을 제거하고 L-moment Pearson III 표준화 적용.

```
[유출보정]  α 방식
Pc(t) = min(P, Th) + α × max(P-Th, 0)
Th = max(80mm, P95 of wet days), α = 0.2

[CEP]  DS=365 고정 (확장 없음)
[DCEP] = CEP - MEP  (기준기간 달력일 평균)
[PRN]  = DCEP / H(365)

[L-moment Pearson III 표준화]
- 달력일 ±15일 풀링 (~930 표본)
- L-moment 추정 (Hosking & Wallis 1997)
  λ1 = 평균, λ2 = L-scale, τ3 = L-skewness
- Pearson III 분포 피팅 → PIT → Φ⁻¹(F)

scCEDI-K = Φ⁻¹( F_P3(PRN) )
```

`sccedik.py` → `run_sccedik()`

---

### 5. SPI — McKee et al. (1993)

n개월 누적강수량에 감마분포를 피팅하여 표준정규로 변환.

```
rolling_sum(t) = Σ P(t-n×30+1 → t)

기준기간 rolling_sum에 감마분포 피팅:
  P(X=0) = q  (영강수 처리)
  gamma(a, scale) 피팅 (양수 강수 대상)

prob = q + (1-q) × F_gamma(x)
SPI  = Φ⁻¹(prob)
```

`run_longterm_cedi_pit.py` → `compute_spi_daily()`

---

## 핵심 파라미터

| 파라미터 | 값 | 설명 |
|----------|-----|------|
| DS 기본값 | 365일 | 조화급수 합산 기간 |
| 집중호우 임계값 | 80mm | 유출보정 기준 (Kim 2009 최적값) |
| 시간감쇠계수 | 0.5 | exp(-0.5×(m-1)), 10일 후 초과분 ≈ 1% |
| 기준기간 | 1973 ~ 전년도 | 롤링 기준기간 (ASOS 가용 전 기간) |
| 풀링 창 | ±15일 | 달력일 ±15일 (균등) |
| 가뭄 임계값 | < -1.0 | 약한 가뭄 |
| 심한 가뭄 | < -1.5 | |
| 극한 가뭄 | < -2.0 | |

---

## 주요 설정 변경

`run_longterm_cedi_pit.py` 상단:

```python
STATION = 105           # ASOS 지점번호 (config.py 참조)
YEAR_S  = 2010          # 표출 시작연도
YEAR_E  = 2025          # 표출 종료연도
BASELINE = (1973, YEAR_E - 1)  # 기준기간 (롤링)
```

다른 지점 적용 예시:
```python
STATION = 108   # 서울
```

---

## 데이터 출처

| 자료 | 출처 | API |
|------|------|-----|
| ASOS 일강수량 | 기상청 | `apis.data.go.kr/1360000/AsosDalyInfoService` |
| AWS 강수량 | 기상청 | `apis.data.go.kr/1360000/AwsRltmInfoService` |
| 오봉저수지 저수율 | 한국농어촌공사 | `api.odcloud.kr/api/15113475/v1` |

---

## 출력 결과

### CSV 컬럼 설명

`CEDI_PIT_longterm_강릉105_{YEAR_S}-{YEAR_E}.csv`

| 컬럼 | 설명 |
|------|------|
| date | 날짜 |
| precip_mm | 일강수량 (mm) |
| CEDI | CEDI 원본 지수 |
| CEDI_pool15d | CEDI+pool±15d |
| CEDI_pool7d | CEDI+pool±7d |
| CEDI_PIT_15d | CEDI+PIT(±15d 경험적) |
| SPI3 | SPI-3 (90일 누적) |
| SPI6 | SPI-6 (180일 누적) |

---

## API 키 발급 방법 (신규 직원 필독)

### 1. 공공데이터포털 가입 및 키 발급

1. [data.go.kr](https://www.data.go.kr) 접속 → 회원가입
2. 검색창에 **"기상청 지상(종관, ASOS) 일자료 조회서비스"** 검색
3. 해당 서비스 클릭 → **활용신청** 버튼
4. 활용목적 입력 후 신청 (보통 1~2일 내 자동 승인)
5. **마이페이지 → 오픈API → 개발계정** 에서 인증키 확인

### 2. 키 적용

발급받은 키를 `pipeline/config.py`에 입력합니다.

```python
# pipeline/config.py
SERVICE_KEY_ENCODED = "여기에_발급받은_인코딩키_입력"
```

> **주의**: 공공데이터포털에서 키를 확인할 때 **인코딩** 탭의 키를 사용해야 합니다.  
> 디코딩 키를 쓰면 `%2F`, `%3D` 등의 특수문자가 이중 인코딩되어 API 오류가 발생합니다.

---

## 신규 지점 추가 방법

### Step 1. 지점번호 확인

`pipeline/config.py`의 `STATIONS` 딕셔너리에서 원하는 지점번호를 확인합니다.

```python
# 예시
STATIONS = {
    105: "강릉",
    108: "서울",
    159: "부산",
    ...
}
```

기상청 [기후자료 지점정보](https://data.kma.go.kr/sttn/obs/selectSttnList.do)에서 전체 목록 확인 가능.

### Step 2. 과거 자료 수집

```bash
cd pipeline

# collect_historical.py 내 STN_ID 수정
# STN_ID = 108  ← 서울로 변경
python collect_historical.py
```

또는 코드 수정 없이 Python 인터랙티브 사용:

```python
from collect_historical import collect_long_term
df = collect_long_term(stn_id=108, start_year=1973, end_year=2024)
```

### Step 3. 메인 스크립트 설정 변경

```python
# run_longterm_cedi_pit.py 상단
STATION = 108   # 서울
YEAR_S  = 2010
YEAR_E  = 2025
```

```bash
python run_longterm_cedi_pit.py
```

---

## 연간 업데이트 절차

매년 새해 업무 시작 시 아래 순서로 자료를 갱신합니다.

```bash
cd pipeline

# 1. 전년도 자료 수집 (예: 2025년 → 2025년 전체 수집)
#    asos_collector.py의 YEAR = 2025 확인 후 실행
python asos_collector.py

# 2. 메인 스크립트의 연도 변경
#    YEAR_E = 2026 으로 수정 (새해 기준)

# 3. 분석 실행
python run_longterm_cedi_pit.py
```

> **캐시 동작**: `data/raw/asos_precip_{지점}_{연도}_raw.csv` 파일이 이미 존재하면 API 호출 없이 캐시를 불러옵니다. 특정 연도 자료를 강제로 다시 받으려면 해당 파일을 삭제하고 실행하면 됩니다.

---

## 한글 폰트 설정

그래프에 한글이 깨지는 경우 OS별 폰트를 확인합니다.

### macOS (자동 감지됨)

`AppleGothic` 또는 `Apple SD Gothic Neo`가 자동 설정됩니다. 별도 조치 불필요.

### Windows

```python
# matplotlib 폰트 수동 설정
import matplotlib as mpl
mpl.rcParams["font.family"] = "Malgun Gothic"
mpl.rcParams["axes.unicode_minus"] = False
```

또는 `NanumGothic` 설치 후 사용:
```
https://hangeul.naver.com/font 에서 나눔고딕 다운로드 → 설치 → Python 재시작
```

### Linux

```bash
sudo apt-get install fonts-nanum
```

```python
mpl.rcParams["font.family"] = "NanumGothic"
```

---

## 자주 발생하는 오류 및 해결법

### API 오류: `resultCode != "00"`

```
원인: API 키 오류, 일일 호출 한도 초과, 서비스 점검
해결: config.py의 키 확인, 공공데이터포털 마이페이지에서 호출 횟수 확인
     일일 한도는 계정당 1,000~10,000건 (신청 시 설정)
```

### `ModuleNotFoundError`

```bash
# pipeline/ 디렉터리 밖에서 실행 시 발생
# 반드시 pipeline/ 안에서 실행
cd pipeline
python run_longterm_cedi_pit.py
```

### 그래프에 값이 없거나 빈 패널

```
원인: 데이터 기간 불일치 (YEAR_S가 수집된 자료보다 이전인 경우)
해결: data/raw/ 디렉터리에서 해당 지점의 가장 오래된 파일 연도 확인
     YEAR_S를 해당 연도 이후로 설정
```

### 오봉저수지 데이터 없음 (패널 0 저수율 미표시)

```
원인: outputs/저수율_강릉오봉_*.csv 파일 없음
해결: python collect_reservoir_obong.py 실행
     저수율은 2021년 이후만 표시됨 (API 데이터 제공 시작 연도)
```

### 수치가 극단적으로 크거나 작음 (예: ±5 이상)

```
원인: 기준기간 자료가 부족하거나 특정 달력일의 표본이 매우 적음
해결: pool_half 값을 높이거나(±15d → ±20d), 기준기간 시작연도를 앞당김
```

---

## 결과 해석 가이드

### 가뭄 단계 기준 (모든 지수 공통)

| 지수값 | 단계 | 그래프 색상 |
|--------|------|-------------|
| 0 이상 | 정상 | 흰색 배경 |
| -1.0 미만 | 약한 가뭄 | 주황색 음영 |
| -1.5 미만 | 보통 가뭄 | 주황색 음영 (진함) |
| -2.0 미만 | 심한 가뭄 | 빨간색 음영 |

### 지수별 특성 비교

| 지수 | DS 확장 | 표준화 | 집중호우 반응 | 권장 용도 |
|------|---------|--------|--------------|-----------|
| CEDI | 있음 | z-score | 감쇠 처리 | 원본 재현 |
| CEDI+pool±15d | 있음 | 풀링 z-score | 감쇠 처리 | 개선 비교 |
| CEDI+pool±7d | 있음 | 풀링 z-score | 감쇠 처리 | 계절 정밀도 우선 |
| CEDI+PIT | 있음 | 경험적 PIT | 감쇠 처리 | 분포 교정 |
| SPI-3 | 없음 | 감마 PIT | 그대로 반영 | 단기 가뭄 |
| SPI-6 | 없음 | 감마 PIT | 그대로 반영 | 중기 가뭄 |

### 기준기간 의미

기준기간(1973~전년도)은 "정상 상태"의 기준이 됩니다.
기준기간 내 해당 날짜의 평균 CEP를 빼고 표준편차로 나누기 때문에,
**지수값 0 = 기준기간 평균 수준**, **-1 = 평균보다 1표준편차 건조**를 의미합니다.

---

## 국가 가뭄지수로의 발전 가능성

### 현황 및 한계

현재 기상청 국가 가뭄정보 시스템에서 사용하는 기상 가뭄지수는 EDI/CEDI 계열입니다.
이 지수들은 다음과 같은 한계가 지적되어 왔습니다.

- **DS 확장 문제**: 가뭄 지속 시 합산 창이 수백 일까지 늘어나 과거 습윤기를 포함, 실제 가뭄을 과소평가
- **표준화 불안정**: 달력일 정확 표본(~30~52개)으로 추정한 σ가 불안정하여 날짜 간 지수 불연속 발생
- **분포 비정규성 무시**: z-score는 강수량 기반 지수의 비대칭 분포를 반영하지 못함
- **기준기간 고정**: WMO 권고(30년 갱신)를 따르지 않�� 최근 기후변화 미반영

---

### 본 연구의 개선 방향

| 문제 | 본 연구 해법 | 근거 |
|------|-------------|------|
| DS 확장 과소평가 | DS=365 고정 (scCEDI-K) | DS 확장과 P3 꼬리는 역할 중복 |
| σ 추정 불안정 | ±15일 달력일 풀링 | 표본 수 52 → 1,612개, SPI 표준 방식 |
| 비정규 분포 | L-moment Pearson III PIT | 꼬리 과장 없이 극단 가뭄 정확 표현 |
| 기준기간 고정 | 롤링 기준기간 (1973~전년도) | 매년 최신 기후 반영 |

---

### 국가 운영 지수 요건 충족 여부

국가 가뭄지수가 되려면 다음 요건을 충족해야 합니다.

| 요건 | CEDI (현행) | CEDI+pool±15d | scCEDI-K v2 |
|------|:-----------:|:-------------:|:-----------:|
| 실시간 계산 가능 | ✅ | ✅ | ✅ |
| 일별 연속 산출 | ✅ | ✅ | ✅ |
| 표준정규 분포 출력 | 부분 | 부분 | ✅ |
| 전국 지점 적용 가능 | ✅ | ✅ | ✅ |
| 기준기간 갱신 용이 | ✅ | ✅ | ✅ |
| 극한 가뭄 표현력 | 낮음 | 보통 | 높음 |
| 방법론 투명성 | 높음 | 높음 | 높음 |
| 국제 표준 정합성 | 낮음 | 보통 | 높음 (SPI 동급) |

---

### 단계적 발전 로드맵

```
Phase 1 (현재)
  └─ 단일 지점(강릉) 검증
     CEDI vs CEDI+pool vs scCEDI-K vs SPI 비교

Phase 2 (단기)
  └─ 전국 ASOS 지점 확장 (~93개 지점)
     지점별 결과 공간 분포도 생성
     과거 가뭄 사례(2015, 2017, 2022) 재현성 검증

Phase 3 (중기)
  └─ 공간 내삽 적용
     격자형 국가 가뭄지수 맵 생성 (1km 격자)
     실시간 자동화 파이프라인 구축

Phase 4 (장기)
  └─ 다중 가뭄지수 앙상블
     기상·농업·수문 가뭄 통합 지수 연계
     국가 가뭄정보 시스템 반영
```

---

### 전국 지점 확장 시 예상 소요 시간

현재 코드 기준 단일 지점 처리 시간:

| 단계 | 소요 시간 (약) |
|------|--------------|
| 과거 자료 수집 (1973~현재) | 2~5분 (API) |
| CEDI 계산 (전체 기간) | 30초 |
| 풀링 표준화 | 1분 |
| PIT 계산 | 1분 |
| SPI 계산 | 1분 |

전국 93개 지점 × 약 4분 = **약 6시간** (순차 처리 기준)
병렬 처리(`multiprocessing`) 적용 시 **30분 이내** 단축 가능.

---

### 향후 연구 과제

1. **DS 확장 대안 탐색**: DS 고정의 단점(장기 가뭄 초기 감지 지연)을 보완하는 하이브리드 방안
2. **최적 풀링 창 결정**: 계절별로 다른 풀링 창 적용 (예: 장마철 ±7일, 겨울 ±15일)
3. **기후변화 적응**: 기준기간 내 트렌드 제거(detrending) 후 표준화 적용 여부 검토
4. **검증 지표 확립**: 과거 가뭄 사례와의 정합성 정량 평가 (FAR, POD, CSI)
5. **사용자 인터페이스**: 지점 선택, 기간 입력, 결과 자동 생성 웹 대시보드 구축

---

## 참고 논문

1. Byun, H.-R. & Wilhite, D.A. (1999). Objective Quantification of Drought Severity and Duration. *Journal of Climate*, 12, 2747–2756.
2. Kim, D.-W. et al. (2009). Evaluation, modification, and application of the Effective Drought Index to 200-year drought climatology of Seoul, Korea. *Journal of Hydrology*, 378, 1–12.
3. Hosking, J.R.M. & Wallis, J.R. (1997). *Regional Frequency Analysis: An Approach Based on L-Moments*. Cambridge University Press.
4. McKee, T.B. et al. (1993). The Relationship of Drought Frequency and Duration to Time Scales. *8th Conference on Applied Climatology*.
