# GLM 분석 도구 카탈로그

### 일반화선형모형(GLM)

`glm_regression`

#### 1. Description

Gaussian·Binomial·Poisson 분포의 일반화선형모형으로 종속변수와 수치형 공변량의 관계를 분석한다. 절편을 포함하여 회귀계수를 적합하고 계수표와 모형 요약을 반환한다.

#### 2. Input

**필요한 데이터:** 한 행이 하나의 관측인 pandas DataFrame. 선택한 분포에 맞는 결과 열과 수치형 공변량이 필요하다.

|Parameter|필수/선택|형식|기본값|의미·조건|
|---|---|---|---|---|
|`data`|필수|DataFrame|없음|분석 데이터. 열 이름 중복 불가.|
|`outcome_column`|필수|열 이름|없음|종속변수 열 이름.|
|`covariates`|필수|열 이름 목록(list)|없음|한 개 이상의 독립변수. 중복 및 종속변수 포함 불가.|
|`family`|선택|문자열|`'gaussian'`|`gaussian`, `binomial`, `poisson` 중 하나.|

- 지정한 열은 모두 존재하고 숫자로 변환 가능해야 한다. 수치 문자열은 변환하며 범주형은 사전에 인코딩한다.
- 분석 열의 결측·무한값은 오류로 처리한다. 행을 자동 삭제하지 않는다.
- Gaussian 결과는 유한 수치, Binomial은 0/1이며 두 값 모두 존재, Poisson은 비음수 정수이며 적어도 하나의 양수 관측이 필요하다.
- 절편은 자동 추가한다. 상수열·정확한 선형 종속을 허용하지 않으며 관측 수는 절편 포함 계수 수보다 커야 한다.
- 링크는 Gaussian=identity, Binomial=logit, Poisson=log로 고정한다.

#### 3. Output

**형태:** Python dict — `coefficients`(DataFrame)와 `summary`(dict). 함수 자체는 파일을 생성하지 않는다.

**생성 결과:** 절편과 독립변수별 계수표 및 모형 요약.

|주요 Column|의미|
|---|---|
|`covariate`|독립변수 이름. `(Intercept)`는 절편|
|`coef`|링크 척도의 회귀계수|
|`se`|모형 기반 계수 표준오차|
|`z`|Wald z 통계량|
|`p`|계수=0에 대한 양측 Wald 검정 p값|
|`ci_lower`|계수 척도의 95% Wald 신뢰구간 하한|
|`ci_upper`|계수 척도의 95% Wald 신뢰구간 상한|

요약에는 `family`(분포), `n_obs`(분석 관측 수), `aic`(적합도와 복잡도를 고려한 비교 지표), `deviance`(포화모형 대비 적합 차이)를 제공한다.

#### 4. Output 검토

- 계수표와 모형 요약을 분리하며 기본 계수 추론에 필요한 결과를 제공한다.
- Gaussian 계수는 평균 차이, Binomial은 로그 오즈 차이, Poisson은 로그 평균 차이다. Binomial·Poisson의 계수와 CI는 지수 변환한 효과비가 아니다.
- Gaussian도 z/Wald 추론을 사용하므로 OLS의 소표본 t 추론과 다르다. AIC는 같은 결과 정의와 같은 자료에 적합한 모형 간에 비교한다.
- 잔차·영향점·과산포 진단은 제공하지 않는다. 수렴한 결과라도 분석 가정의 충족을 보장하지 않는다.

#### 5. Assumptions

관측의 독립성, 링크 척도에서의 평균 모형 적절성, 설계행렬 full rank 및 충분한 표본이 필요하다. Gaussian은 조건부 등분산·정규 오차, Binomial은 완전·준완전분리 없음, Poisson은 조건부 평균=분산을 가정한다.

위반 시: 비선형성·이분산·분리·과산포 등은 계수 또는 표준오차·CI를 불안정하게 만들 수 있다. 자료와 모형을 재검토한다. 군집 상관·robust 분산·가중치·offset/exposure는 지원하지 않으므로 해당 보정이 필요한 분석에 그대로 사용하지 않는다.

#### 6. Processing Type

|항목|여부 및 처리 방식|
|---|---|
|모델 학습(Training)|필요. 현재 입력 자료에서 회귀계수 적합.|
|Batch Processing|불필요. 한 입력 데이터 분석에 별도 다중 작업 배치 실행이 요구되지 않음.|
|단일 실행|가능. 한 번 호출하여 결과 반환. 내부 IRLS 적합은 최대 100회 반복.|

#### 7. 관리 정보

- 구현: [glm.py](./glm.py)의 `glm_regression`.
- 주요 의존성: statsmodels, pandas, NumPy, SciPy.
- 오류 처리: 입력 조건 위반, 감지된 Binomial 분리, 적합 실패·미수렴, 유효하지 않은 추론 결과는 `ValueError` 발생. 모든 불안정 모형을 자동 검출하지는 않는다.
- 설치·실행 안내: [README.md](./README.md).
