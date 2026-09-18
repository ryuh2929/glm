# 신규 GLM 사용 및 해석

## 범위와 구조

`tool_sample/glm.py`의 `fit_glm`은 DataFrame을 받아 계수 DataFrame과 진단 dict를 반환한다. `SeerToolbox.basic_glm`은 기존과 같은 `source`, `where`, `label` 인수를 받고, 전체 계수 관계를 materialize하고 deliverable을 등록한다. `ANALYSIS_OPS`, `SeerToolbox.specs()`, `tool_desc.description`에 등록하여 `run_analysis_step`과 `run` 경로로 실행할 수 있다. 로컬 패키지의 output schema를 읽는 fallback도 추가했다.

기존 `glm_regression`은 원본 구현이며 유지했다. 신규 구현은 **3개 분포와 고정 링크**만 지원하여 과제의 기본 기능 범위를 분명히 한다. formula 문자열, arbitrary link, 가중/군집 분산, offset/exposure, 규제화, 다중대치 pooling, 모델 저장·신규 표본 예측은 지원하지 않는다.

|family|종속변수|link|설명변수 계수의 효과 해석|주요 가정|
|---|---|---|---|---|
|gaussian|유한 연속 수치|identity|한 단위 증가당 평균 차이 β|선형 조건부 평균, 독립성, 모형 기반 추론의 등분산/정규 오차 가정|
|binomial|개별 관측 0/1, 두 값 모두 존재|logit|exp(β): 오즈비|logit 선형성, 독립 Bernoulli, 완전분리 없음|
|poisson|0 이상 정수, 양수 관측 존재|log|exp(β): 기대 count 비|log 평균 선형성, 독립성, 조건부 평균=분산|

Poisson은 관측 노출기간이 동일하거나 분석 의미가 count인 경우에 사용한다. 노출량이 다른 incidence rate 분석에는 기존 exposure 지원 GLM 등을 별도 검토해야 한다. binomial은 집계 성공/시도 수 또는 분수 비율을 받지 않는다. Gaussian GLM에서 반환하는 추론은 statsmodels의 기본 **z/Wald** 방식이며 OLS의 소표본 t 추론과 다르다.

## 입력 계약

필수: `data`(DataFrame), `outcome_column`(열 이름), `covariates`(1개 이상 중복 없는 열 이름 list). 종속변수를 설명변수에 포함할 수 없다. 절편은 자동 포함하며 상수 설명변수는 거절한다.

선택: `family='gaussian'`, `categorical=None`, `reference_levels=None`, `missing='raise'`, `max_iter=100`, `tolerance=1e-8`. adapter에서는 `source='seer'`, `where=''`, `label=''`도 사용한다. 모든 실제 인수·기본값은 분석 카탈로그에 수록했다.

- 범주형은 명시적 `categorical`로 지정한다. 숫자 코드도 지정해야 범주로 처리된다. 나머지 설명변수는 숫자 변환 가능한 값이어야 하며 자동 유형 추정을 하지 않는다.
- 범주 기준값은 `reference_levels`로 지정한다. 생략하면 완전사례의 문자열 정렬 첫 수준이다. 실제 적용 기준은 진단 JSON과 각 범주 계수 행의 reference에 기록한다. 범주형은 문자열로 표현되므로 숫자/문자 혼합 코딩은 사전에 통일한다.
- 기본은 결측 오류. `missing='drop'`은 선택 열의 NULL/NaN/공백 문자열이 하나라도 있는 행을 **인코딩 전에** 제거한다. 잘못된 수치 문자열·무한값은 drop 정책이어도 오류다. 결과에 n_input/n_used/n_dropped를 기록한다.
- n_used는 절편 포함 설계 열 수보다 커야 하고 full rank여야 한다. 수렴 여부·완전분리 경고·계수/CI의 유한성을 검사한다. 이 검사는 준완전분리, 모형 오지정, 영향점, 잔차 패턴까지 자동 판정하는 것은 아니다.
- adapter는 선택 코호트가 100,000행을 넘으면 실패한다. 임의의 앞부분만 분석하지 않는다. 출력 label은 입력 source와 달라야 하며 기존 관계명과 충돌하지 않는 고유 이름을 사용한다.

## 실행 예시

프로젝트 루트에서 아래 명령으로 합성 CSV/Parquet와 3분포 결과를 재생성한다.

```powershell
.\.venv\Scripts\python -m examples.run_glm
```

독립 함수 사용:

```python
import pandas as pd
from tool_sample.glm import fit_glm

df = pd.read_csv("examples/sample_data.csv")
result = fit_glm(
    df, outcome_column="binary", covariates=["x", "group"],
    family="binomial", categorical=["group"],
    reference_levels={"group": "control"},
)
print(result.coefficients)
print(result.diagnostics)
```

기존 파이프라인 사용:

```python
from tool_sample.tool_sample import run_analysis_step

payload = run_analysis_step("examples/sample_data.parquet", {
    "op": "basic_glm", "output": "glm_binary", "inputs": ["seer"],
    "params": {
        "outcome_column": "binary", "covariates": ["x", "group"],
        "family": "binomial", "categorical": ["group"],
        "reference_levels": {"group": "control"},
    },
})
if payload["error"]:
    raise RuntimeError(payload["error"])
print(payload["preview"])
print(payload["deliverable"]["diagnostics"])
```

## 결과 및 검토

계수 표는 절편 포함 설계 항별 한 행이다. `coef/se/z/p/coef_lower95/coef_upper95`는 링크 척도 계수 및 양측 95% Wald 추론이다. `estimate/lower95/upper95/estimate_type`은 해석용 효과 척도다. p값을 반올림해 0으로 저장하지 않는다. 범주 항에는 `variable/level/reference`를 함께 저장하여 표시명만 파싱할 필요가 없다.

절편은 효과비가 아니다. Gaussian 절편은 모든 수치 설명변수가 0이고 범주가 기준일 때 baseline_mean, binomial 절편의 exp는 baseline_odds, poisson 절편의 exp는 baseline_count로 구분한다. 이 기준점이 관측 범위 밖이면 절편의 실질적 해석에 유의한다.

진단에는 family/link, n_input/n_used/n_dropped, n_parameters, df_resid, converged, deviance, pearson_dispersion, aic, reference_levels, missing, covariance, confidence_level, warnings를 저장한다. AIC는 같은 자료·같은 결과 정의의 비교에 사용한다. Poisson dispersion>1.5 경고는 정식 검정이 아닌 탐색적 기준이다. 과산포·군집 상관이 있으면 제공 CI를 그대로 보고하지 말고 적합한 모형/분산 추정을 선택한다. Gaussian dispersion은 잔차분산 척도이며 무조건 1과 비교하면 안 된다.

Sample Data는 seed 20260918의 **합성 관측 300개**이며 실제 임상자료가 아니다. 연속 결과는 `2 + 0.8*x + 0.5*treated + N(0,1)`, 이진 결과는 `logit(p)=-0.4+0.8*x+0.5*treated`, count는 `log(mu)=0.2+0.3*x+0.4*treated`로 생성한다. 계수 추정은 생성 계수와 정확히 같을 필요가 없다. `subject_id`는 식별용으로 모델에 넣지 않는다. group은 control/treated로 코딩한다.

## 오류 처리와 제한

독립 함수는 잘못된 입력/불안정 적합에서 `ValueError`를 발생시킨다. adapter는 기존 인터페이스와 맞춰 `Error: basic_glm: ...`를 반환하며 파이프라인은 error 필드로 전달한다. 존재하지 않는 열, 빈 코호트, 범위 위반, 결측, 공선성, 분리, 미수렴을 테스트했다. 학습 중 일반 경고는 diagnostics에 보존한다. 통계적 독립성·분포·선형성·결측 메커니즘은 연구자가 확인해야 한다.

표준 결과는 Table+JSON이며 Figure와 fitted model 파일은 범위 밖이다. 샘플 스크립트는 CSV/JSON/Parquet를 로컬에 저장한다. 신규 도구 자체는 S3에 업로드하지 않는다.
