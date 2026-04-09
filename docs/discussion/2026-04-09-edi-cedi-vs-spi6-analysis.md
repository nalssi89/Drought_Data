# 2026-04-09 EDI/CEDI vs SPI6 Analysis

## 메타

- 상태: round-1 완료, round-2 진행 중
- 주제: `docs/papers`의 EDI, CEDI 논문을 기준으로 SPI6 비교 분석을 수행하고, 3개 알고리즘을 재구현한 뒤 강릉/서울/광주 자료로 실제 가뭄 탐지력을 검증한다.
- 관련 라운드:
  - `docs/discussion/2026-04-09-edi-cedi-vs-spi6-analysis-round-1.md`
  - `docs/discussion/2026-04-09-edi-cedi-vs-spi6-analysis-round-2.md`

## 현재 이해한 요청

이번 논의의 최종 목표는 다음 네 가지를 하나의 재현 가능한 작업 흐름으로 묶는 것이다.

1. 논문 기반으로 EDI, CEDI, SPI6를 다시 구현한다.
2. 강릉(105), 서울(108), 광주(156) 자료로 세 지수를 같은 축에서 비교한다.
3. 지수의 수치 비교를 넘어서 실제 가뭄 상황을 더 잘 탐지하는지 검증한다.
4. 토론-합의-문서 업데이트 루프를 `docs/discussion/` 아래에 라운드별로 남긴다.

## 현재 전제와 해석

- 전제 1: "3개 알고리즘"은 EDI, CEDI, SPI6를 뜻하는 것으로 우선 해석한다.
- 전제 2: "새롭게 구현"은 기존 산출물을 그대로 인용하는 것이 아니라, 논문 정의를 기준으로 재현 가능한 코드 경로를 분리해 검증 가능하게 만드는 것을 뜻한다.
- 전제 3: 비교 지점은 저장소에 이미 산출물이 존재하는 강릉 105, 서울 108, 광주 156을 우선 대상으로 삼는다.
- 전제 4: "실제 가뭄 상황" 검증은 단순 극값 비교가 아니라, 알려진 가뭄 구간과 지수의 onset, persistence, recovery를 함께 보는 사례 검증이 필요하다.

## 현재 확인한 저장소 맥락

### 문헌

- `docs/papers/Objective_Quantification_extracted.txt`
- `docs/papers/Kim2009_CEDI_extracted.txt`

### 기존 구현

- `pipeline/edi_algorithm.py`
- `pipeline/cedi_algorithm.py`
- `pipeline/run_final_station_plot.py`
- `pipeline/run_longterm_cedi_pit.py`

### 기존 산출물

- `outputs/final_figure_data_gangneung_105_2010-2025.csv`
- `outputs/final_figure_data_seoul_108_2010-2025.csv`
- `outputs/final_figure_data_gwangju_156_2010-2025.csv`

## 초기 관찰

- 저장소에는 이미 EDI, CEDI, SPI3, SPI6 비교용 코드와 산출물이 일부 존재한다.
- 현재 토론의 핵심은 "새 분석을 처음부터 만들 것인가"보다 "논문 충실 재구현, 실험 설계, 실제 가뭄 검증을 어떻게 엄밀하게 닫을 것인가"에 더 가깝다.
- 산출물 극값만 보면 서울과 광주는 2022년, 강릉은 2015-2016년이 핵심 사례 구간일 가능성이 높다.

## 라운드 진행 규칙

1. 각 라운드는 서브에이전트 3인의 의견 수렴으로 시작한다.
2. 라운드 문서에는 관점별 의견, 메인 에이전트 종합, 잠정 합의, 남은 쟁점을 함께 기록한다.
3. 합의가 생기면 이 원본 문서에 반영한다.
4. 합의되지 않은 쟁점은 다음 라운드 문서로 넘긴다.

## 현재 열린 쟁점

- 논문 충실 재구현의 기준선을 어디까지로 둘 것인가
- 검증용 기준 사건을 어떤 외부/내부 근거로 고정할 것인가
- 기존 코드 수정과 신규 재구현 코드를 어떻게 분리할 것인가
- 최종 보고서의 형태를 연구노트, 재현 스크립트, 사용자용 요약 중 어디에 무게를 둘 것인가

## round-1 합의 요약

- 세 관점 모두 비교 스펙을 먼저 고정해야 한다는 데 동의했다.
- 이번 과업의 핵심은 코드 수를 늘리는 것이 아니라, EDI/CEDI/SPI6를 동일 기준으로 비교하고 실제 가뭄 사건 기반으로 설명 가능한 검증 결과를 만드는 것이다.
- round-2에서는 알고리즘 범위, baseline, 사건 윈도우, 평가지표, 산출물 구조를 문장 수준으로 고정한다.

## round-2 합의 스펙

- primary comparison은 `EDI`, `CEDI`, `SPI6`로 한정한다.
- 평가기간은 `2010-01-01 ~ 2025-12-31`로 고정한다.
- baseline은 원칙적으로 `1973-01-01 ~ 2009-12-31`의 고정 기후평년을 사용한다.
- 특정 지점이 1973년보다 늦게 시작하면 해당 지점의 최초 가용일부터 `2009-12-31`까지를 baseline으로 사용하고 그 사실을 `manifest`와 보고서에 명시한다.
- 실제 가뭄 검증은 사건 단위 윈도우 테이블로 수행하며, 최소 필드는 `event_id`, `station`, `start_date`, `end_date`, `anchor_date`, `source`, `note`로 둔다.
- 핵심 평가지표는 `event recall(POD)`, `false alarm rate(FAR)`, `onset delay`, `peak-date error`, `event overlap ratio`다.
- 결과 저장의 기본 단위는 station별 `series.csv`, `metrics.csv`, `event_windows.csv`, `manifest.json`, plot 세트다.
- 본편 판정 기준은 "최저값이 더 작다"가 아니라 "실제 사건을 더 빠르고 일관되게 탐지한다"이다.

## 현재 결론

- 토론 단계의 1차 합의는 round-2에서 종료한다.
- 구현 단계로 넘어가기 전 추가로 필요한 것은 사건 윈도우의 실제 날짜와 근거 source를 채우는 일이다.
- 필요하면 구현 과정에서 새 쟁점이 생길 때에만 `round-3`를 연다.

## 라운드 로그

- round-1: 완료
- round-2: 완료
