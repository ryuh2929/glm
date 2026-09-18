# 기본 GLM 분석 도구

Gaussian·Binomial·Poisson GLM을 실행하는 독립 함수다. 입력 조건·출력 정의·분석 가정은 [GLM 분석 도구 카탈로그](./GLM%20분석%20도구%20카탈로그.md)를 참고한다.

## 설치 및 실행

검증 환경은 Python 3.14.5 / Windows다. 이 폴더에서 다음 명령을 실행한다.

```bash
cd NewGLMAnalysisTool

python -m venv .venv
source .venv/bin/activate

python -m pip install -r requirements.txt
# 샘플 데이터 생성 및 glm 분석 코드 실행
python run_example.py
# 테스트 코드 실행
python -m unittest -v test_glm.py
```

macOS/Linux에서는 `.venv/bin/python`을 사용한다. 예제 실행 시 이 폴더의 `sample_data.csv`와 `sample_output` 내 예제 결과 파일을 다시 생성한다.

## 함수 호출 예시

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

## 파일 안내

|파일|역할|
|---|---|
|`glm.py`|GLM 구현|
|`requirements.txt`|설치할 라이브러리와 버전|
|`run_example.py`|합성 데이터 생성 및 Gaussian/Binomial/Poisson GLM 실행|
|`sample_data.csv`|고정 난수 시드 20260918로 생성한 합성 데이터 300행. 실제 연구자료가 아님|
|`sample_output/`|분포별 계수표 CSV와 모형 요약 JSON|
|`test_glm.py`|수치 결과와 기본 오류 처리 검증|

예제는 Gaussian에서 `score ~ age + income`, Binomial에서 `disease ~ age + smoker`, Poisson에서 `visit_count ~ age + smoker`를 적합한다. 데이터 생성식은 `run_example.py`에서 확인할 수 있다.

## 결과 파일 안내

`sample_output/`에 각 분포 이름(`gaussian`, `binomial`, `poisson`)을 접두사로 붙인 두 종류의 파일이 생성된다.

|파일|내용|
|---|---|
|`{family}_coefficients.csv`|변수별 GLM 회귀계수·통계량. 절편과 각 독립변수가 한 행씩 표시됨|
|`{family}_summary.json`|GLM 모형 전체 요약: 분포, 관측 수, AIC, deviance|

계수표에서 `coef`는 회귀계수, `se`는 표준오차, `z`는 Wald 검정통계량, `p`는 양측 p값, `ci_lower`·`ci_upper`는 계수의 95% 신뢰구간이다. Binomial·Poisson의 계수와 신뢰구간은 로그 척도이며 효과비로 변환된 값이 아니다.

요약의 `family`는 사용한 분포, `n_obs`는 분석한 데이터 행 수다. 예제의 `n_obs: 300`은 관측치 300개를 사용했다는 뜻이다. `aic`는 적합도와 복잡도를 함께 고려하는 모형 비교 지표로, 같은 결과변수와 같은 자료로 적합한 모형 사이에서 낮을수록 선호한다. `deviance`는 포화모형 대비 적합 차이를 나타낸다.

자세한 출력 정의와 해석 시 주의사항은 [카탈로그의 Output 및 Output 검토](./GLM%20분석%20도구%20카탈로그.md)를 참고한다.
