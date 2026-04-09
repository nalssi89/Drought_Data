# Round 2 - EDI/CEDI vs SPI6 Analysis

## 목적

- round-1에서 남긴 쟁점을 실험 스펙 수준으로 좁힌다.
- 알고리즘 범위, baseline, 사건 윈도우, 평가 지표, 산출물 구조의 기본값을 합의한다.

## round-1에서 넘어온 쟁점

- "3개 알고리즘"을 무엇으로 고정할 것인가
- SPI6 정의를 어떤 구현으로 고정할 것인가
- 실제 가뭄 사건 윈도우를 어떤 형식으로 정의할 것인가
- 검증 표와 deliverable 범위를 어디까지로 할 것인가

## 서브에이전트 추가 질의

- 동일 세 관점에 "권장 기본값"만 다시 요청함
- 목표: round-2 종료 시점에 문서에 바로 넣을 수 있는 실험 스펙 문장 확보

## 서브에이전트 의견

### 1. LLM 관점

- 비교 대상은 `EDI`, `CEDI`, `SPI6` 세 알고리즘으로 고정하고, 변형 알고리즘은 본 실험 범위에서 제외하는 것이 스펙 안정성에 유리하다고 제안했다.
- baseline은 rolling보다 고정 공통 기간이 재현성과 해석 일관성에 낫다고 보았고, 사건 윈도우는 `event_id, station, start_date, end_date, evidence_source, note` 중심의 테이블 형식을 권장했다.
- 핵심 평가지표는 탐지 리드타임, 최저점 시점 오차, 사건 윈도우 내 임계치 이탈 지속일수, 사건별 탐지율, 지표 간 일치도다.

### 2. 소프트웨어 아키텍트 관점

- 알고리즘 범위는 `EDI`, `CEDI`, `SPI6`로 한정하고, PIT/pool/scCEDI-K 등은 후속 확장으로 미루는 것이 구조적으로 깔끔하다고 제안했다.
- 실험 기간은 `2010-01-01 ~ 2025-12-31`, 사건 윈도우는 `event_id, station, start_date, end_date, source, severity_note, peak_date` 형태를 권장했다.
- 필수 평가지표는 `event recall`, `event precision`, `detection lead time`, `minimum value at event peak`, `false alarm count`다.
- 산출물은 station별 `series.csv`, `metrics.csv`, `event_windows.csv`, `manifest.json`, plot 세트로 묶는 구성이 적절하다고 보았다.

### 3. 엔드유저 관점

- 사용자가 이해하기 쉬운 비교를 위해 `EDI`, `CEDI`, `SPI6` 세 알고리즘만 본편에 두고, 모든 지표를 동일 baseline과 평가기간에서 계산해야 한다고 제안했다.
- baseline은 고정 기후평년을 선호했고, 사건 윈도우는 `event_id / station / start_date / end_date / anchor_date / source` 형식과 `anchor_date ±30일` 기본값을 제안했다.
- 핵심 평가지표는 `탐지율(POD)`, `오경보율(FAR)`, `onset 지연일수`, `최저값 시점 오차`, `이벤트 기간 중첩률`이다.

## 메인 에이전트 종합

- 세 관점은 모두 primary comparison을 `EDI`, `CEDI`, `SPI6`로 고정하는 데 동의했다.
- 세 관점은 모두 사건 기반 검증 테이블이 필요하다는 데 동의했고, 필드 차이는 있었지만 공통 최소 집합은 `event_id`, `station`, `start_date`, `end_date`, `anchor_date`, `source`, `note`로 수렴했다.
- baseline은 의견이 갈렸지만, 비교기간이 `2010-2025`로 이미 좁혀져 있으므로 메인 에이전트는 **평가기간 누수를 피하는 고정 baseline**을 채택하기로 한다.
- 따라서 이번 토론의 기본 실험 스펙은 다음과 같이 정리한다.
  - 평가기간: `2010-01-01 ~ 2025-12-31`
  - baseline: `1973-01-01 ~ 2009-12-31`
  - 예외 규칙: 특정 지점의 자료 시작일이 1973년보다 늦으면 해당 지점의 최초 가용일부터 2009-12-31까지 사용
  - primary algorithms: `EDI`, `CEDI`, `SPI6`
  - primary outputs: `series.csv`, `metrics.csv`, `event_windows.csv`, `manifest.json`, station plot

## 잠정 합의

1. 이번 본편 비교는 `EDI`, `CEDI`, `SPI6` 3개 알고리즘으로 한정한다.
2. 모든 비교는 `2010-01-01 ~ 2025-12-31` 평가기간과 `1973-01-01 ~ 2009-12-31` 고정 baseline을 기본 규칙으로 사용한다.
3. 실제 가뭄 검증은 사건 단위 윈도우 기준으로 수행하며, onset, peak, recovery를 함께 본다.
4. 필수 평가 지표는 `event recall(POD)`, `false alarm rate(FAR)`, `onset delay`, `peak-date error`, `event overlap ratio`로 고정한다.
5. 최종 판단 기준은 단순 최저값이 아니라, 실제 가뭄 사건을 얼마나 정확하고 일관되게 탐지했는지다.

## 남은 쟁점

- 사건 윈도우의 실제 날짜와 근거 source를 어떤 자료로 채울지
- SPI6를 현 구현 그대로 둘지, 표준 정의와의 차이를 별도 주석으로 둘지
- 공식 deliverable 디렉토리 구조를 기존 `deliverables/`와 어떻게 연결할지
