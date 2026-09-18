# 연구 분석 카탈로그 및 GLM 구현 과제

기존 도구 **60개 전체**의 분석 카탈로그와 신규 **basic_glm** 구현을 포함합니다. 원본에 이미 `glm_regression`이 있어, 신규 구현은 별도 이름으로 추가했습니다.

## 제출물

|파일|내용|
|---|---|
|[분석 카탈로그](docs/analysis_catalog.md)|기존 60개 + 신규 1개: 목적, 입력/필수·선택 파라미터/실제 기본값, 출력·열 의미, 가정, 결과 검토, 처리 유형|
|[오류 및 개선사항](docs/findings.md)|확인 방법·근거·영향·개선안, 검증 범위와 한계|
|[GLM 사용 가이드](docs/glm_guide.md)|지원 분포, 예시, 결과 해석, 가정 및 예외 처리|
|[GLM 소스](tool_sample/glm.py)|Gaussian/identity, Bernoulli/logit, Poisson/log 구현|
|[GLM 정의](tool_sample/glm_desc.py)|Input / Parameter / Output 계약|
|[실행 예시](examples/run_glm.py)|합성 데이터 생성 및 직접 함수/기존 파이프라인 실행|
|[Sample CSV](examples/sample_data.csv)|300행 합성 데이터; 실제 환자 데이터 아님|
|[실행 결과](examples/output)|분포별 계수 CSV, 진단 JSON, 파이프라인 JSON|
|[카탈로그 JSON](docs/analysis_catalog.json)|기계 판독용 계약·검토·소스 위치|

## 빠른 실행

Windows PowerShell, 프로젝트 루트 기준입니다. 검증 환경은 Python 3.14.5이며 가상환경 활성화 없이 실행할 수 있습니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m examples.run_glm
.\.venv\Scripts\python -m pytest -q
```

다른 OS에서는 `.venv/Scripts/python` 대신 `.venv/bin/python`을 사용합니다. 전체 의존성 버전은 [requirements-lock.txt](requirements-lock.txt)에 보존했습니다. 원본 60개를 모두 실행하기 위한 전체 서버 환경은 포함하지 않습니다.

## 확인 결과

27개 테스트 통과. 세 분포 모두 n=300, 모형 항=3, 수렴 성공. 샘플의 `x` 효과는 다음과 같습니다(표시만 반올림).

|분포|척도|추정치|95% CI|
|---|---|---:|---|
|Gaussian|평균 차이|0.8557|0.7416–0.9697|
|Binomial|오즈비|2.3530|1.7792–3.1117|
|Poisson|count ratio|1.4029|1.2773–1.5408|

숫자는 합성 데이터 예시이며 연구 결론이 아닙니다. 원본 분석 전체의 통계적 정확성을 검증했다는 의미도 아닙니다.

## 구조 및 변경 범위

신규 핵심 계산은 `glm.py`로 분리했습니다. 기존 `SeerToolbox`에 `basic_glm` 메서드/스키마를 추가하고 `ANALYSIS_OPS`, `tool_desc`에 등록했습니다. `get_output_schema`에는 샘플의 로컬 패키지 조회 경로를 추가했습니다. 기존 분석 함수의 통계 계산은 유지했으며 발견한 결함은 별도 문서와 재현 테스트로 남겼습니다.

신규 GLM은 명시적 결측 처리, 범주 기준값, 입력 범위, 설계행렬 rank, 완전분리 경고, 수렴 여부를 검사합니다. 계수 표와 함께 n/제외수/family/link/AIC/deviance/분산/경고를 저장합니다. S3 계정이나 외부 서비스 없이 실행됩니다.

## 카탈로그 갱신

```powershell
python -m docs.build_catalog
```

함수 시그니처와 등록된 스키마를 추출하고 `docs/catalog_notes.py`의 수동 검토 내용을 결합합니다. 문서 생성기가 통계적 해석을 자동 검증하지는 않습니다. 소스 변경 시 검토 메모와 오류 문서도 함께 갱신해야 합니다.
