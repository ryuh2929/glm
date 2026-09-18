# 기본 GLM 분석 도구

수치형 독립변수를 사용하는 Gaussian·Binomial·Poisson GLM이다. 기존 도구의 outcome_column/covariates/family 이름과 계수표 구성을 참고한 독립 함수이며 DuckDB·S3 설정은 필요하지 않다.

## 설치 및 실행

검증 환경은 Python 3.14.5 / Windows다. 이 폴더에서 다음 명령을 실행한다.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python run_example.py
.\.venv\Scripts\python -m unittest -v test_glm.py
```

macOS/Linux에서는 `.venv/bin/python`을 사용한다. run_example.py는 자신의 폴더를 기준으로 sample_data.csv와 sample_output의 예제 파일을 다시 생성한다.

## 사용법

```python
import pandas as pd
from glm import glm_regression

data = pd.read_csv("sample_data.csv")
result = glm_regression(
    data, outcome_column="disease", covariates=["age", "smoker"], family="binomial"
)
print(result["coefficients"])
print(result["summary"])
```

|입력|필수 여부|의미|
|---|---|---|
|data|필수|pandas DataFrame|
|outcome_column|필수|종속변수 열 이름|
|covariates|필수|중복 없는 수치형 독립변수 이름 목록. 종속변수 제외|
|family|선택|gaussian(기본), binomial, poisson|

분석에 사용하는 열만 검사한다. 수치 문자열은 숫자로 변환하지만 결측·무한값은 오류로 처리하며 행을 자동 삭제하지 않는다. 범주형은 미리 인코딩해야 한다. 절편은 자동 포함한다. 상수열·정확한 선형 종속·표본 부족·분리·미수렴 등에는 ValueError를 반환한다. 불안정한 모든 모형을 자동 검출하는 것은 아니다.

## 결과 해석

반환값은 `coefficients`(DataFrame), `summary`(dict)를 가진 dict다. 예제는 이를 각각 CSV와 JSON으로 저장한다.

|계수표 열|의미|
|---|---|
|covariate|독립변수 이름; (Intercept)는 절편|
|coef|링크 척도 계수|
|se|계수 표준오차|
|z|Wald z 통계량|
|p|양측 Wald 검정 p값|
|ci_lower / ci_upper|계수 척도의 95% Wald 신뢰구간|

summary는 family, n_obs(분석 행 수), aic, deviance를 제공한다. Gaussian 계수는 평균 차이, Binomial은 로그 오즈, Poisson은 로그 평균 척도다. **Binomial/Poisson의 coef와 CI는 OR 또는 count ratio가 아니다.** 절편은 독립변수가 모두 0일 때의 링크 척도 평균이며, 샘플의 나이 0은 관측 범위 밖이라 실질적 해석에 주의한다.

Gaussian–identity, Binomial–logit, Poisson–log 링크를 자동 사용한다. Gaussian의 기본 추론도 GLM의 z/Wald 방식이며 OLS 소표본 t 추론과 구별한다. AIC는 같은 결과 정의와 같은 자료에서 적합한 모델끼리 비교한다.

## 가정과 제한

- 독립 관측, 올바른 평균 모형 및 식별 가능한 설계행렬이 필요하다.
- Gaussian: 조건부 평균의 선형성 및 모형 기반 추론을 위한 등분산·정규 오차 가정. 종속변수는 유한 수치다.
- Binomial: 개별 0/1 결과의 두 클래스, logit 선형성, 분리 없음. 집계 성공/시도 수나 비율 자료는 지원하지 않는다.
- Poisson: 비음수 정수 count, 조건부 평균=분산. 최소 한 양수 관측이 필요하다. 과산포·과도한 0이 있으면 추론이 부정확할 수 있다.
- 군집 상관·과산포에 대한 robust 분산, 자동 가정 검정, 가중치, offset/exposure, 사용자 링크, 자동 범주형 처리, 새 자료 예측은 지원하지 않는다. Poisson은 노출량이 다른 발생률 분석용으로 설계하지 않았다.
- 학습/적합은 필요하며, 한 번 호출로 실행한다. 내부에서는 최대 100회의 반복 최적화를 수행한다. 별도 배치 실행은 불필요하다.

## 합성 데이터

sample_data.csv는 난수 시드 20260918로 만든 300행이며 실제 연구자료가 아니다. age는 20~70, income은 임의 단위의 2000~8000, smoker는 0/1이다. 생성식은 run_example.py에 공개되어 있다.

- score: 나이·소득의 선형 평균에 표준편차 5의 정규 오차 추가.
- disease: 나이·흡연 여부에 따른 로지스틱 확률로 Bernoulli 생성.
- visit_count: 나이·흡연 여부에 따른 log 평균으로 Poisson 생성.

이름은 설명용이며 실제 질병·방문·흡연의 관계에 관한 근거가 아니다. 표본 추정치가 생성 계수와 정확히 같을 필요는 없다.
