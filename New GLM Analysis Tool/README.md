# 기본 GLM 분석 도구

Gaussian·Binomial·Poisson GLM을 실행하는 독립 함수다. 입력 조건·출력 정의·분석 가정은 [GLM 분석 도구 카탈로그](./GLM%20분석%20도구%20카탈로그.md)를 참고한다.

## 설치 및 실행

검증 환경은 Python 3.14.5 / Windows다. 이 폴더에서 다음 명령을 실행한다.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python run_example.py
.\.venv\Scripts\python -m unittest -v test_glm.py
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
|`run_example.py`|합성 데이터 생성 및 세 분포 실행|
|`sample_data.csv`|고정 난수 시드 20260918로 생성한 합성 데이터 300행. 실제 연구자료가 아님|
|`sample_output/`|분포별 계수표 CSV와 모형 요약 JSON|
|`test_glm.py`|수치 결과와 기본 오류 처리 검증|

예제는 Gaussian에서 `score ~ age + income`, Binomial에서 `disease ~ age + smoker`, Poisson에서 `visit_count ~ age + smoker`를 적합한다. 데이터 생성식은 `run_example.py`에서 확인할 수 있다.
