# 연구 분석 도구 카탈로그

작성일: 2026-09-18 · 버전 1.0.0 · 검토 대상: 제공된 `tool_sample/tool_sample.py`, `tool_sample/tool_desc.py`.

## 범위와 읽는 방법

기존 등록 도구 **60개 전체**와 신규 **basic_glm 1개**를 다룬다. 제공 코드에는 이미 확장형 `glm_regression`이 있으므로 이를 신규 작성으로 주장하지 않는다. 과제용 구현은 `basic_glm`으로 분리하여 기존 함수의 동작을 보존하고, 입력 검증과 결과 진단에 집중했다.

기존 도구는 구현·시그니처·결과 생성 코드의 정적 검토가 중심이다. 신규 GLM은 합성 데이터 실행 및 수치/예외/통합 테스트를 수행했다. 일부 기존 오류는 별도 회귀 재현 테스트로 확인했다. S3, 실제 연구 데이터, 외부 시스템, 모든 통계 라이브러리의 전체 도구 실행을 검증한 문서는 아니다. 제공되지 않은 모델 모듈은 실행 불가로 표시한다.

필수/선택 입력과 반환 형식은 **선언 카탈로그**, 기본값과 실제 처리에 관한 판단은 **함수 구현**을 대조했다. 원본 영문 파라미터 설명을 보존하고 한국어 목적·가정·검토를 덧붙였다. 불일치는 오류/개선사항 및 각 도구 검토에 명시한다. 소스 변경 시 `python -m docs.build_catalog`로 시그니처·열 계약을 재생성하되, `catalog_notes.py`의 해석 검토는 사람이 갱신해야 한다.

## 공통 입출력·운영 계약

- 입력: Parquet → DuckDB 관계(기본 `seer`). `source`는 선행 분석의 관계명이며 파일 경로가 아니다. `where`는 임상 코호트 필터 SQL이고, 신뢰하는 로컬 사용자가 작성하는 전제다. 임의 SQL에 대한 보안 격리 계층이 아니다.
- 실행: `SeerToolbox`의 메서드 또는 `run_analysis_step(parquet_uri, spec)`. 통계 라이브러리는 대개 실행 시 지연 import된다. 주석과 달리 모델 학습은 pandas/NumPy 메모리로 자료를 올린다.
- 반환: 메서드는 보통 **str 요약**을 반환한다. 실제 분석 산출물은 `_materialize_output`으로 등록한 **전체 DuckDB 관계**와 `deliverables`의 **최대 200행 preview**, 열 이름, row_count, 저장 경로, 선택 그림으로 전달된다. preview를 전체 결과로 간주하지 않는다.
- 출력 종류: `dataset`은 환자/관측 데이터, `table`은 집계/계수/검정 결과, `figure`는 PNG와 그 기반 수치 테이블이다. side deliverable의 SMD/대치 요약은 주 데이터 edge와 다를 수 있다.
- 저장: 기존 도구의 Parquet/PNG 내보내기는 S3 유틸/환경에 의존한다. 파일이 실제 생성되었는지는 URI를 확인한다. 신규 GLM은 로컬 DuckDB 결과와 JSON 진단을 생성하며 샘플 스크립트가 CSV/JSON을 저장한다.
- 오류: 기존에는 `Error:` 등 문자열과 예외가 혼재한다. 파이프라인은 실패 접두사·산출물 유무로 상태를 판별한다. 운영에서는 명시적 status/error_code/warnings 구조로 통일하는 것이 좋다.
- 결측: NULL, 빈 문자열, 미상 코드, 비수치 값은 구별해야 한다. 도구마다 삭제·기준범주 흡수·검열/음성 처리 등이 달라 공통 결측 정책이 없다. 다중대치 `_imputation`을 지원하지 않는 도구에 그대로 쌓아 넣지 않는다.
- 범주값: `event_values`는 사건, `outcome_values`는 양성, `treatment_values`는 처치값만 지정한다. 목록 밖 값이 검열/음성/대조군이 되는 경로가 많으므로 미상·누락 코드를 먼저 점검한다.
- 규모: 기존 여러 모델은 `_MODEL_MAX_ROWS=1,000,000` LIMIT를 사용한다. 무작위 표본추출이 아니며, 일부 경로는 초과 사실을 보고하지 않는다. 신규 basic_glm은 100,000행 초과 시 명시적으로 실패한다.
- Training은 모수/모델 적합 필요 여부이다. 통계적 추론 목적의 적합도 표시하되 예측모델 학습과 구분한다. 한 번 호출 안의 변수·군·bootstrap·CV 반복을 설명하며, 모든 도구에 외부 배치 시스템이 필요한 것은 아니다.

## 해석의 공통 원칙

관측연구의 조정된 연관은 자동으로 인과 효과가 되지 않는다. OR, HR, RR, count ratio와 절대 위험차는 서로 다르다. p값은 효과크기나 가정 충족 확률이 아니고, CI는 모형·표본설계가 타당할 때만 의미가 있다. 다중 비교와 사후 하위집단 선택을 보고해야 한다. 가중/매칭/대치 후 데이터의 독립성 및 불확실성을 무시하면 CI가 과도하게 좁아질 수 있다.

관리 권장 필드: catalog_version, 구현 파일/라인/해시, 라이브러리 버전, 입력 스키마·단위·관측 단위, 대상 모집단/estimand, 결측·범주 코딩, 표본/사건/제외수, seed, 모델 적합 설정, 수렴·경고, 실행 시간/메모리 제한, 결과 스키마 버전, 검증 상태, 담당자. 이 문서의 JSON 동반 파일은 계약·검토·소스 위치를 기계적으로 읽을 수 있게 제공한다.


## 도구 목록

|번호|도구|분류|주 출력|
|---|---|---|---|
|1|[table1](#tool-table1)|descriptive|table|
|2|[attrition_table](#tool-attrition_table)|descriptive|table|
|3|[data_quality](#tool-data_quality)|descriptive|table|
|4|[propensity_score_match](#tool-propensity_score_match)|statistics|dataset|
|5|[propensity_score_match_multi](#tool-propensity_score_match_multi)|statistics|dataset|
|6|[iptw_weight](#tool-iptw_weight)|statistics|dataset|
|7|[mann_whitney_u](#tool-mann_whitney_u)|statistics|table|
|8|[chi2_contingency](#tool-chi2_contingency)|statistics|table|
|9|[logistic_regression](#tool-logistic_regression)|statistics|table|
|10|[glm_regression](#tool-glm_regression)|statistics|table|
|11|[att_weight](#tool-att_weight)|statistics|dataset|
|12|[att_estimate](#tool-att_estimate)|statistics|table|
|13|[att_estimate_multi](#tool-att_estimate_multi)|statistics|table|
|14|[att_sensitivity](#tool-att_sensitivity)|statistics|table|
|15|[ate_weight](#tool-ate_weight)|statistics|dataset|
|16|[ate_estimate](#tool-ate_estimate)|statistics|table|
|17|[ate_estimate_multi](#tool-ate_estimate_multi)|statistics|table|
|18|[ate_sensitivity](#tool-ate_sensitivity)|statistics|table|
|19|[covariate_balance](#tool-covariate_balance)|statistics|table|
|20|[covariate_balance_multi](#tool-covariate_balance_multi)|statistics|table|
|21|[evalue](#tool-evalue)|statistics|table|
|22|[bias_sensitivity](#tool-bias_sensitivity)|statistics|table|
|23|[impute_missing](#tool-impute_missing)|statistics|dataset|
|24|[predict_breast_os](#tool-predict_breast_os)|modeling|dataset|
|25|[LogisticRegression](#tool-logisticregression)|modeling|dataset|
|26|[LogisticRegressionCV](#tool-logisticregressioncv)|modeling|dataset|
|27|[PassiveAggressiveClassifier](#tool-passiveaggressiveclassifier)|modeling|dataset|
|28|[Perceptron](#tool-perceptron)|modeling|dataset|
|29|[RidgeClassifier](#tool-ridgeclassifier)|modeling|dataset|
|30|[RidgeClassifierCV](#tool-ridgeclassifiercv)|modeling|dataset|
|31|[SGDClassifier](#tool-sgdclassifier)|modeling|dataset|
|32|[SGDOneClassSVM](#tool-sgdoneclasssvm)|modeling|dataset|
|33|[SVC](#tool-svc)|modeling|dataset|
|34|[LinearSVC](#tool-linearsvc)|modeling|dataset|
|35|[NuSVC](#tool-nusvc)|modeling|dataset|
|36|[DecisionTreeClassifier](#tool-decisiontreeclassifier)|modeling|dataset|
|37|[ExtraTreeClassifier](#tool-extratreeclassifier)|modeling|dataset|
|38|[RandomForestClassifier](#tool-randomforestclassifier)|modeling|dataset|
|39|[ExtraTreesClassifier](#tool-extratreesclassifier)|modeling|dataset|
|40|[AdaBoostClassifier](#tool-adaboostclassifier)|modeling|dataset|
|41|[GradientBoostingClassifier](#tool-gradientboostingclassifier)|modeling|dataset|
|42|[HistGradientBoostingClassifier](#tool-histgradientboostingclassifier)|modeling|dataset|
|43|[ml_train_test_split](#tool-ml_train_test_split)|modeling|dataset|
|44|[ml_classifier_performance](#tool-ml_classifier_performance)|modeling|table|
|45|[ml_roc_curve](#tool-ml_roc_curve)|modeling|figure|
|46|[ml_calibration_curve](#tool-ml_calibration_curve)|modeling|figure|
|47|[ml_decision_curve](#tool-ml_decision_curve)|modeling|figure|
|48|[ml_reclassification](#tool-ml_reclassification)|modeling|table|
|49|[ml_cv_performance](#tool-ml_cv_performance)|modeling|table|
|50|[ml_compare](#tool-ml_compare)|modeling|table|
|51|[kaplan_meier](#tool-kaplan_meier)|survival|figure|
|52|[competing_risk_cif](#tool-competing_risk_cif)|survival|figure|
|53|[logrank_test](#tool-logrank_test)|survival|table|
|54|[cox_ph](#tool-cox_ph)|survival|table|
|55|[cox_ph_univariate](#tool-cox_ph_univariate)|survival|table|
|56|[cox_ph_subgroup](#tool-cox_ph_subgroup)|survival|table|
|57|[cox_ph_assumptions](#tool-cox_ph_assumptions)|survival|table|
|58|[cox_time_varying](#tool-cox_time_varying)|survival|table|
|59|[iptw_kaplan_meier](#tool-iptw_kaplan_meier)|survival|figure|
|60|[iptw_survival_metrics](#tool-iptw_survival_metrics)|survival|table|
|61|[basic_glm](#tool-basic_glm)|statistics|table|

<a id="tool-table1"></a>

## 1. `table1`

**Description / 목적:** 코호트의 기저 특성을 전체/군별 기술통계와 SMD, p값으로 요약한다.

**구현 근거:** [tool_sample.py:11134](../tool_sample/tool_sample.py#L11134) · `table1`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|columns|list[column]|필수|None|The baseline variables to SUMMARIZE (one row-block each). Never empty. Do NOT include the groupby column here.|
|groupby|column|선택|''|Column to stratify by (produces per-group columns + p-value/SMD). Its own value is the group header, not a summarized row.|
|categorical|list[column]|선택|None|Which of `columns` are categorical (counts/%); the rest are treated as continuous.|
|nonnormal|list[column]|선택|None|Skewed continuous columns to report as median [IQR] instead of mean (SD).|
|order|Any|선택|None|범주 표시 순서|
|rename|object{column:string}|선택|None|Display-label map for Table 1 row names: {source_column: "Label"}. The source column stays the same; only the printed Variable label changes (e.g. {"BMI_23_LSY": "BMI_23"} strips a suffix). Keys must be columns already in `columns`. Omit to keep the raw column names.|
|limit|Any|선택|None|표시 수준 수 제한|
|decimals|Any|선택|None|표시 소수 자릿수|
|pval|bool|선택|True|Add a per-variable p-value column (needs groupby). Default false.|
|smd|bool|선택|True|Add a standardized-mean-difference column (needs groupby). Default false.|
|missing|bool|선택|True|결측 요약 표시 여부|
|overall|bool|선택|True|Include an overall (all-groups) column. Default false.|
|label_suffix|bool|선택|True|요약 통계 접미사 표시|
|include_null|bool|선택|False|NULL 수준 포함 여부|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|imputation_column|column|선택|''|Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default): a baseline table counts PATIENTS, so the tool narrows an `_imputation` stack to ONE draw instead of reporting m copies of the cohort as N.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 관측 단위와 분모를 통일한다. categorical/nonnormal을 데이터 의미에 맞게 지정하고, 군간 검정은 독립 관측을 전제한다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_variable_level`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|Variable|string|Baseline variable name after TableOne MultiIndex flatten|
|Level|string|Category level; empty for a continuous row|
|<groupby headers>|string|One display column per group value (n (%) / mean (SD) / median [IQR]) / 조건: groupby set|
|Overall|string|All-groups column / 조건: overall=true|
|p-value|number\|string|Per-variable p. Flattened name is `p-value` or `p` / 조건: pval=true|
|SMD|number|Standardized mean difference. Flattened name is `SMD` (sometimes prefixed by the groupby header). This is the column a love / SMD figure must plot. / 조건: smd=true|

**기존 Output 계약 메모:** A tidy characteristics table — NOT a cohort. No patient rows.

**Output 검토 / 가정 위반 시 주의:** 문자열로 포맷된 평균(SD)/중앙값[IQR]/n(%)는 표시용으로 적절하나 후속 계산용 수치 테이블이 별도로 필요하다. 문서의 pval/smd/overall 기본 false와 함수의 True가 다르다. SMD 열 이름도 동적으로 변한다. 다중대치 데이터는 한 draw만 기술한다.

**Processing Type:** 적합 없음 / 한 번 호출, 변수·군별 집계 / 배치 필수 아님. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-attrition_table"></a>

## 2. `attrition_table`

**Description / 목적:** 조건을 순서대로 누적 적용하여 포함·제외 흐름을 계산한다.

**구현 근거:** [tool_sample.py:13222](../tool_sample/tool_sample.py#L13222) · `attrition_table`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|steps|list[object]|필수|None|The loop axis: an ORDERED list of {"label": "...", "where": "<SQL boolean>"} criteria, each applied ON TOP OF the previous ones. Write them in the order the protocol states them — the table reads as the flow diagram does. Never empty.|
|distinct_column|column|선택|''|Patient/subject id, to count SUBJECTS alongside rows at each step. Optional.|
|where|string|선택|''|Filter defining the SOURCE population (step 0), before any criterion. Optional.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. steps 순서가 연구 프로토콜 순서여야 한다. 행 수와 distinct 환자 수를 구별한다. SQL NULL의 3값 논리에 유의한다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_step`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|step|integer|0 = source cohort, then 1…n criteria|
|criterion|string|조건 이름|
|expression|string|SQL WHERE applied at this step|
|n_before|integer|단계 직전 행 수|
|n_after|integer|단계 직후 행 수|
|n_excluded|integer|해당 단계 제외 행 수|
|pct_excluded|number|직전 행 수 대비 제외 백분율|
|n_subjects|integer|distinct patients when distinct_column is set|

**Output 검토 / 가정 위반 시 주의:** n_before/n_after/n_excluded가 있어 흐름 재현에 적합하다. pct_excluded는 해당 단계 직전 행 수 기준이다. n_subjects는 distinct_column이 있을 때만 의미가 있다. 중복 환자 기준 제외 수를 별도 제공하면 좋다.

**Processing Type:** 적합 없음 / 조건별 반복 집계 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-data_quality"></a>

## 3. `data_quality`

**Description / 목적:** 열별 결측·고유값 수와 날짜/숫자 선후관계 위반을 확인한다.

**구현 근거:** [tool_sample.py:13313](../tool_sample/tool_sample.py#L13313) · `data_quality`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|columns|list[column]|선택|None|Loop axis 1: the columns to profile. Each gets n, n_flagged (null or blank), pct_flagged and n_distinct.|
|date_order|list[object]|선택|None|Loop axis 2: order rules, each {"earlier": "<column>", "later": "<column>", "label": "..."}, counting the rows where `later` PRECEDES `earlier` (e.g. a treatment date before the diagnosis date). Values compare as dates when both cast, otherwise as numbers, so year-only fields work unparsed.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. columns 또는 date_order 중 하나 이상 필요. 날짜 형식·단위를 통일한다. 비교 불가능 값은 시간 규칙 분모에서 제외된다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_check`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|check|string|missingness \| temporal_order|
|variable|string|대상 변수|
|n|integer|분석/검사 분모; 도구별 관측 단위 확인|
|n_flagged|integer|위반 또는 결측 건수|
|pct_flagged|number|분모 대비 위반 백분율|
|n_distinct|integer|고유값 수 / 조건: check=missingness|
|detail|string|검사 설명 또는 오류|

**Output 검토 / 가정 위반 시 주의:** check별 분모 n의 의미가 다르다. 시간 검사는 비교 가능한 행 수이고 결측 검사는 전체 행 수이다. 소개문과 달리 일반 범위/이상치 검사는 없다. 비교 불가 수와 실패 status 추가가 필요하다.

**Processing Type:** 적합 없음 / 변수·규칙 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-propensity_score_match"></a>

## 4. `propensity_score_match`

**Description / 목적:** 이진 처치 성향점수 logit의 최근접 탐욕 매칭으로 비교 코호트를 만든다.

**구현 근거:** [tool_sample.py:5894](../tool_sample/tool_sample.py#L5894) · `propensity_score_match`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|treatment_column|column|필수|— (인수 필수)|Column that separates treated vs control (e.g. a 0/1 flag or a 2-label category).|
|treatment_values|list[value]|필수|— (인수 필수)|ONLY the value(s) of treatment_column that mark the TREATED arm — the control is everyone else, inferred automatically. NEVER list every value: for a 0/1 flag pass [1] (not [1,0]); for a labeled column pass just the treated label, copied verbatim from its real values.|
|covariates|list[column]|필수|— (인수 필수)|Baseline columns to balance on (categoricals auto one-hot encoded). EXCLUDE the treatment_column and any pure identifier. Never empty.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|caliper|number|선택|0.2|Match tolerance as a multiple of SD(PS logit); applies at every ratio. Default 0.2 (Austin's recommendation) — keep it unless the source explicitly used another value.|
|ratio|integer|선택|1|Controls matched per treated (1 = 1:1). Default 1.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 기저 공변량만 사용. 일관성·간섭 없음·조건부 교환가능성·양의 처치확률이 인과 해석에 필요하다. 처치값 이외는 대조군이므로 사전 코딩 확인.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|_treat|integer|1 = treated, 0 = control|

**Side output:** 주 output edge와 별도이며 후속 노드에서 환자 코호트처럼 연결할 수 없다. Registered as a workspace deliverable only. Downstream nodes cannot read it via inputs unless a dedicated table1(smd=true) or covariate_balance node produces it.

|Side Column|의미|
|---|---|
|covariate|모형의 공변량 또는 수준|
|smd_before|SMD on the unmatched / unweighted cohort|
|smd_after|SMD on the matched / weighted sample|

**기존 Output 계약 메모:** NODE OUTPUT is the matched PATIENT cohort (source columns + `_treat`). The SMD before/after table is a SIDE deliverable under the same node name and is NOT on the dataset edge.

**Output 검토 / 가정 위반 시 주의:** 출력 edge는 환자 코호트이며 SMD는 side deliverable이다. 매칭 세트 ID, 미매칭 이유/탈락 수, PS 분포를 추가하면 추적성이 좋아진다. 소개문은 replacement 설정을 암시하지만 함수는 비복원 매칭이다. 매칭 후 독립표본 SE를 그대로 쓰지 않는다.

**Processing Type:** 성향점수 모델 적합 / 매칭 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-propensity_score_match_multi"></a>

## 5. `propensity_score_match_multi`

**Description / 목적:** 3개 이상 처치군의 다항 성향점수로 1:1:…:1 매칭 세트를 구성한다.

**구현 근거:** [tool_sample.py:6137](../tool_sample/tool_sample.py#L6137) · `propensity_score_match_multi`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|treatment_column|column|필수|— (인수 필수)|Column whose values identify the K treatment arms (e.g. surgery type).|
|arms|list[value]|필수|— (인수 필수)|Ordered list of ≥3 distinct treatment_column values to match 1:1:…:1. Copy each label VERBATIM from the data. Do NOT use this tool for binary (2-arm) matching.|
|covariates|list[column]|필수|— (인수 필수)|Baseline columns for the multinomial propensity model (categoricals auto one-hot encoded). EXCLUDE treatment_column and pure identifiers. Never empty.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|exact_columns|list[column]|선택|None|Columns that must match exactly within each K-tuple (hard strata), e.g. histology, stage, ER status. Optional.|
|tolerance_columns|object\|list|선택|None|Numeric within-tolerance constraints: {column: tol} or [{column, tolerance}, …] — e.g. {"Age": 2, "Year of diagnosis": 2}. Every pair in a tuple must satisfy \|Δ\| ≤ tol. Optional.|
|caliper|number|선택|0.6|Per GPS-dimension caliper as a multiple of SD(logit P(arm=a) among patients in arm a). Default 0.6 (common three-group PSM / Rassen-style recipes).|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 서로 다른 arms 3개 이상, exact/tolerance 조건의 현실적 중첩, 모든 군 간 positivity 필요. 이진 도구와 구별한다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|_arm|integer|0..K-1 arm index, equal n per arm|

**Side output:** 주 output edge와 별도이며 후속 노드에서 환자 코호트처럼 연결할 수 없다. 

|Side Column|의미|
|---|---|
|covariate|모형의 공변량 또는 수준|
|smd_before|SMD on the unmatched / unweighted cohort|
|smd_after|SMD on the matched / weighted sample|
|arm_i|first arm label|
|arm_j|second arm label|

**기존 Output 계약 메모:** Matched patient cohort. Pairwise SMD before/after is a side deliverable, not the node output.

**Output 검토 / 가정 위반 시 주의:** _arm은 arms 순서 인덱스이다. 군별 수가 같아도 균형 달성을 보장하지 않는다. 쌍별 SMD는 side output이며 세트 식별자와 매칭 탈락 상세가 필요하다.

**Processing Type:** 다항 성향점수 적합 / K-tuple 탐색 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-iptw_weight"></a>

## 6. `iptw_weight`

**Description / 목적:** ATE용 IPTW 또는 ATO용 overlap 가중치를 생성한다.

**구현 근거:** [tool_sample.py:6819](../tool_sample/tool_sample.py#L6819) · `iptw_weight`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|treatment_column|column|필수|— (인수 필수)|Column that separates treated vs control (a 0/1 flag or a 2-label category).|
|treatment_values|list[value]|필수|— (인수 필수)|ONLY the value(s) marking the TREATED arm — control is everyone else, inferred automatically. NEVER list every value: for a 0/1 flag pass [1] (not [1,0]); for a labeled column pass just the treated label, copied verbatim from its real values.|
|covariates|list[column]|필수|None|Confounders the propensity model adjusts for. Typed AUTOMATICALLY: numeric columns become continuous, everything else categorical (blanks become an 'Unknown' level). EXCLUDE the treatment column, the outcome and any identifier. Never empty.|
|cont_var|list[column]|선택|None|Force these covariates to be CONTINUOUS. Needed for numeric fields stored as text that the auto-typing would otherwise treat as categories.|
|cat_var|list[column]|선택|None|Force these covariates to be CATEGORICAL.|
|binary_var|list[column]|선택|None|Force these covariates to be BINARY (exactly 2 levels).|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|weight_type|string|선택|'iptw'|"iptw" (default) targets the ATE; "overlap" targets the ATO and is far more stable when some patients have extreme propensity scores.|
|stabilized|bool|선택|True|Stabilize IPTW by the marginal treatment probability (default true). Ignored for overlap weights.|
|clip_bounds|list[number]|선택|None|Trim propensity scores to [lower, upper], e.g. [0.01, 0.99], to cap extreme weights.|
|normalize|string|선택|''|Overlap weights only: "by_group" or "overall" rescaling of the weights.|
|random_state|integer|선택|42|Seed for the propensity model. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 공변량과 처치의 정확한 코딩, 교환가능성·positivity·일관성. clip_bounds와 stabilized 설정이 추정 대상을 바꿀 수 있다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|propensity_score|number|원본 스키마의 파생 열; 이름에 표시된 지표/시점 기준|
|iptw|number|ATE weight (column name is `overlap_weight` when weight_type=overlap)|

**Side output:** 주 output edge와 별도이며 후속 노드에서 환자 코호트처럼 연결할 수 없다. 

|Side Column|의미|
|---|---|
|smd_weighted|SMD after weighting; \|SMD\|>0.1 flags residual imbalance|

**기존 Output 계약 메모:** NODE OUTPUT is the FULL weighted cohort. SMD before vs after weighting is a side deliverable (package column `smd_weighted`) — not on the edge.

**Output 검토 / 가정 위반 시 주의:** 가중 코호트와 균형표를 분리해야 한다. iptw 이름만 보고 ATE라고 해석하지 말고 weight_type을 보존한다. 극단 가중치·ESS·제외수와 추정량 메타데이터를 함께 확인한다.

**Processing Type:** 성향점수 적합 / 전체 코호트 일괄 계산 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-mann_whitney_u"></a>

## 7. `mann_whitney_u`

**Description / 목적:** 두 독립 군의 수치 결과 분포를 순위 기반 U 검정으로 비교한다.

**구현 근거:** [tool_sample.py:10792](../tool_sample/tool_sample.py#L10792) · `mann_whitney_u`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|value_column|column|필수|— (인수 필수)|The NUMERIC column to compare between the two arms.|
|group_column|column|필수|— (인수 필수)|Categorical column defining the two arms.|
|group_values|list[value]|선택|None|The TWO group labels to compare (verbatim), required when group_column has >2 labels, e.g. ["A","B"].|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|alternative|string|선택|'two-sided'|"two-sided" (default) \| "less" \| "greater".|
|use_continuity|bool|선택|True|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|method|string|선택|'auto'|"auto" (default) \| "asymptotic" \| "exact".|
|nan_policy|str|선택|'omit'|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 표본, 순서화 가능 결과. 중앙값 차이 검정으로 해석하려면 분포 형태가 유사해야 한다. 동점·소표본에서 method 선택 확인.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|value_column|string|수치 결과 열|
|group_column|string|군 구분 열|
|group_a|string|첫 비교군|
|n_a|integer|첫 군 표본 수|
|median_a|number|첫 군 중앙값|
|group_b|string|둘째 비교군|
|n_b|integer|둘째 군 표본 수|
|median_b|number|둘째 군 중앙값|
|u_statistic|number|U 검정통계량|
|p_value|number|귀무가설하 p값|
|alternative|string|대립가설 방향|
|method|string|사용 추정/검정 방법|

**Output 검토 / 가정 위반 시 주의:** 군별 n/중앙값/U/p/alternative가 있어 기본 검정에는 적합하다. 효과크기(rank-biserial 등)와 CI가 없다. p값만으로 임상적 차이를 판단하지 않는다.

**Processing Type:** 적합 없음 / 단일 검정 / 배치 불필요. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-chi2_contingency"></a>

## 8. `chi2_contingency`

**Description / 목적:** 두 범주형 변수의 독립성을 카이제곱 검정하고 Cramér’s V를 계산한다.

**구현 근거:** [tool_sample.py:10962](../tool_sample/tool_sample.py#L10962) · `chi2_contingency`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|row_column|column|필수|— (인수 필수)|First CATEGORICAL column (table rows).|
|col_column|column|필수|— (인수 필수)|Second CATEGORICAL column (table columns).|
|row_values|list[value]|선택|None|Restrict row_column to these labels (verbatim). Optional.|
|col_values|list[value]|선택|None|Restrict col_column to these labels (verbatim). Optional.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|correction|bool|선택|True|Yates' continuity correction for 2×2. Default true.|
|lambda_|Any|선택|None|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 관측, 상호 배타적 범주, 충분한 기대도수. 희소 2×2 표에서는 Fisher 검정을 고려한다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|row_column|string|교차표 행 변수|
|col_column|string|교차표 열 변수|
|n|integer|분석/검사 분모; 도구별 관측 단위 확인|
|n_rows|integer|교차표 행 범주 수|
|n_cols|integer|교차표 열 범주 수|
|chi2_statistic|number|카이제곱/선택 power-divergence 통계량|
|dof|integer|검정 자유도|
|p_value|number|귀무가설하 p값|
|cramers_v|number|범주 연관 강도|
|lambda_|string|power-divergence 파라미터|
|correction|bool|연속성 보정 설정|

**Output 검토 / 가정 위반 시 주의:** 통계량/자유도/p/V는 유용하나 실제 교차표와 기대도수·희소 셀 경고가 빠져 있다. lambda_가 Pearson 이외이면 검정 통계량과 Cramér’s V 정의가 일치하는지 확인해야 한다.

**Processing Type:** 적합 없음 / 단일 검정 / 배치 불필요. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-logistic_regression"></a>

## 9. `logistic_regression`

**Description / 목적:** 이진 결과의 다변수 로지스틱 회귀와 조정 OR을 계산한다.

**구현 근거:** [tool_sample.py:8154](../tool_sample/tool_sample.py#L8154) · `logistic_regression`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to model.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) of outcome_column counted as the POSITIVE class (=1) — the rest are 0, inferred automatically. NEVER list every value: for a 0/1 flag pass [1] (not [1,0]); for a labeled column pass just the positive label, copied verbatim, e.g. ["Yes"].|
|covariates|list[column]|필수|— (인수 필수)|Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column and pure identifiers. Never empty.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical predictors, e.g. {"Race recode": "Black"}. Every odds ratio is measured against this level, so whenever the request names a reference/baseline category you MUST set it here — otherwise the baseline is whichever level sorts first and the ORs answer a different question. Copy the level verbatim from the column's values; a level that does not occur is an error.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 두 결과군, 독립 관측, logit에서 연속변수 선형성, 충분한 사건 수, 완전분리·공선성 없음. outcome_values는 양성값만 지정한다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_term`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|covariate|string|모형의 공변량 또는 수준|
|level_type|string|coefficient \| reference \| intercept|
|coef|number|링크/log-hazard 척도 계수|
|odds_ratio|number|exp(logit 계수), 오즈비|
|or_lower95|number|OR CI 하한|
|or_upper95|number|OR CI 상한|
|z|number|Wald z|
|p|number|양측 검정 p값|

**Output 검토 / 가정 위반 시 주의:** OR/CI/기준범주가 있어 해석 가능하다. OR은 RR이 아니다. _design_matrix의 범주형 결측 기준수준 오인, 행 LIMIT, 분리/수렴 경고 처리 확인이 필요하다. 표에 분석 n·제외수·모델 진단을 추가해야 한다.

**Processing Type:** 통계모델 적합 / 한 번 호출 / 배치 불필요. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-glm_regression"></a>

## 10. `glm_regression`

**Description / 목적:** 기존 확장 GLM: Gaussian/Binomial/Poisson/음이항/Gamma/역가우시안과 링크·노출·가중치 설정으로 평균을 모델링한다.

**구현 근거:** [tool_sample.py:8289](../tool_sample/tool_sample.py#L8289) · `glm_regression`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the outcome. Read as a NUMBER (counts, cost, duration, mean) for every family except binomial.|
|covariates|list[column]|필수|— (인수 필수)|Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column, the exposure/offset column and pure identifiers. Never empty. Do NOT pass a duplicate or rescaling of another covariate (age and age_in_months), or two columns encoding the SAME partition under different labels — that is rank-deficient and is rejected. A binned version of a continuous covariate (age and age_band) is fine.|
|family|string|선택|'gaussian'|gaussian (default) \| binomial \| poisson \| negativebinomial \| gamma \| inverse_gaussian. Pick from the OUTCOME type: counts/rates → poisson, overdispersed counts → negativebinomial, skewed positive money/time → gamma.|
|link|string|선택|''|identity \| log \| logit \| probit \| cloglog \| inverse \| sqrt. Defaults to the link that family is published with (gaussian→identity, binomial→logit, poisson/negativebinomial/gamma→log).|
|outcome_values|list[value]|선택|None|ONLY for family=binomial: the value(s) counted as the POSITIVE class (=1), the rest are 0. For a 0/1 flag pass [1], never [1,0]. Ignored by other families, which read outcome_column as a number.|
|exposure_column|column|선택|''|Person-time denominator for a RATE model, in the unit the rate is reported in. Enters as log(exposure) with its coefficient fixed at 1, which is what makes the ratios incidence-RATE ratios instead of count ratios. Log link only. Must be strictly positive.|
|offset_column|column|선택|''|Raw linear-predictor offset when you already logged the denominator yourself. Pass exposure_column OR offset_column, never both.|
|weights_column|column|선택|''|Per-row weights for a WEIGHTED outcome model — the `iptw` / `overlap_weight` column produced by iptw_weight / ate_weight. Set cov_type="HC0" with it, because the model-based standard errors are too small for a weighted fit.|
|cov_type|string|선택|'nonrobust'|"nonrobust" (default) \| "HC0" \| "HC1" \| "cluster". Use HC0 for weighted or overdispersed fits; "cluster" needs cluster_column.|
|cluster_column|column|선택|''|Grouping column for cluster-robust standard errors (hospital, registry, patient with repeated rows). Required when cov_type="cluster".|
|alpha|number|선택|1.0|Negative-binomial dispersion. Default 1.0 — GLM does not estimate it, so set it when the paper reports one.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical predictors. Every ratio is measured against this level, so set it whenever the request names a reference category; otherwise the baseline is whichever level sorts first. Copy the level verbatim.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 분포의 지지집합, 링크의 유효 범위, 독립성 및 설계행렬 full rank. 음이항 alpha는 추정하지 않고 고정한다. exposure는 양수이며 log 링크에서만 사용한다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_term`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|covariate|string|모형의 공변량 또는 수준|
|level_type|string|coefficient \| reference \| intercept|
|coef|number|linear-predictor scale (log for a log link)|
|se|number|계수 표준오차|
|estimate|number|exp(coef) on a log/logit link, else the coefficient itself|
|ci_lower|number|CI 하한|
|ci_upper|number|CI 상한|
|estimate_type|string|rate_ratio \| risk_ratio \| odds_ratio \| ratio \| mean_difference — what `estimate` MEANS for the family/link that was fitted|
|z|number|Wald z|
|p|number|양측 검정 p값|

**Output 검토 / 가정 위반 시 주의:** 계수와 효과 척도를 함께 주는 구조는 좋다. 범주형 결측 처리·Binomial 범위·정수 count·완전분리 검증이 불충분하다. Poisson에서 exposure 없이도 rate_ratio 표기가 가능하고 절편을 같은 효과 라벨로 표시한다. IPTW를 freq_weights로 전달하는 것만으로 올바른 인과분산이 보장되지 않는다. 상세 개선표 참조.

**Processing Type:** 통계모델 적합 / 한 번 호출 / 배치 불필요. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-att_weight"></a>

## 11. `att_weight`

**Description / 목적:** 실제 처치군(ATT)을 목표로 성향점수 가중 코호트를 생성한다.

**구현 근거:** [tool_sample.py:11780](../tool_sample/tool_sample.py#L11780) · `att_weight`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|treatment_column|column|필수|— (인수 필수)|Column separating treated from control.|
|treatment_values|list[value]|필수|— (인수 필수)|ONLY the TREATED arm's value(s) — control is everyone else, inferred. For a 0/1 flag pass [1], not [1,0]; for a labelled column pass just the treated label, verbatim.|
|covariates|list[column]|필수|— (인수 필수)|Confounders the propensity model adjusts for (categoricals auto one-hot). EXCLUDE the treatment, the outcome and any identifier. Never empty.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|clip_bounds|list[number]|선택|None|Clip the propensity score to [lower, upper], e.g. [0.01, 0.99], so a near-0/1 score cannot produce an enormous weight.|
|trim|number|선택|0.0|Drop rows whose PS falls outside [trim, 1-trim] (0.01 / 0.05 are the usual choices). Default 0 = no trimming, which is itself a choice: trimming and `restrict_to_overlap` are DIFFERENT populations, so do not substitute one for the other when matching a locked primary spec.|
|restrict_to_overlap|bool|선택|False|true drops the non-overlap rows from the OUTPUT; false (default) keeps every row and only flags them in `overlap_flag`. Either way this must match the propensity specification the run's ATT estimators use — a weighted cohort built on a different adjustment set than the effect it feeds is the same inconsistency one step earlier.|
|weight_column|string|선택|'att_weight'|Name of the added weight column. Default "att_weight".|
|reference_levels|object|선택|None|{categorical covariate: baseline level}. Optional.|
|random_state|integer|선택|42|Propensity-model seed. Default 42.|
|imputation_column|column|선택|''|Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default): the propensity model is fitted SEPARATELY inside each `_imputation` draw, every row keeps its own draw's score/weight, and the index survives in the OUTPUT so the estimator downstream can pool. Diagnostics are then per draw (patient scale).|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 일관성·간섭 없음·조건부 교환가능성·positivity. 처치 이전 교란변수만 조정한다. trimming/overlap 제한은 대상 집단을 바꾼다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|propensity_score|number|원본 스키마의 파생 열; 이름에 표시된 지표/시점 기준|
|att_weight|number|1 for treated, PS/(1-PS) for controls (or params.weight_column)|
|overlap_flag|integer|1 = on common support|

**기존 Output 계약 메모:** Weighted patient cohort. ESS / weight-range diagnostics are a side deliverable, not the node output.

**Output 검토 / 가정 위반 시 주의:** 성향점수·가중치·overlap_flag와 원 환자 정보를 보존한다. estimand 및 사용자 weight_column 설정에 따라 열 이름이 달라진다. 효과나 CI를 계산한 결과는 아니다. 가중 분포·ESS·ASD를 함께 보고해야 한다.

**Processing Type:** 성향점수 모델 적합 / 대치 draw 반복 가능 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-att_estimate"></a>

## 12. `att_estimate`

**Description / 목적:** 실제 처치군(ATT): 한 추정법으로 잠재결과 평균과 절대 효과차 및 bootstrap CI를 추정한다.

**구현 근거:** [tool_sample.py:12137](../tool_sample/tool_sample.py#L12137) · `att_estimate`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|treatment_column|column|필수|— (인수 필수)|Column separating treated from control.|
|treatment_values|list[value]|필수|— (인수 필수)|ONLY the TREATED arm's value(s), verbatim — never list every value.|
|covariates|list[column]|필수|— (인수 필수)|Confounders to adjust for. Never empty.|
|outcome_column|column|필수|— (인수 필수)|The outcome whose ATT is estimated.|
|outcome_values|list[value]|선택|None|Positive-class value(s) for a BINARY outcome, e.g. ["Dead"] — the effect is then a risk difference and `ratio` a risk ratio. OMIT for a numeric outcome, which is read as a number and gives a mean difference.|
|method|string|선택|'ipw'|"ipw" (default, ATT weights) \| "gcomp" (outcome regression standardized to the treated) \| "psm" (nearest-neighbour matching on the PS logit) \| "aipw" (doubly robust — consistent if EITHER the propensity or the outcome model is right).|
|where|string|선택|''|SQL boolean cohort filter. Optional. A COMPLETE-CASE filter here (e.g. "menopause IS NOT NULL") does not adjust for that covariate, it deletes whichever arm rarely records it — impute instead, or expect an infeasible row.|
|clip_bounds|list[number]|선택|None|Clip the propensity score, e.g. [0.01, 0.99].|
|trim|number|선택|0.0|Drop rows whose PS falls outside [trim, 1-trim] (0.01 / 0.05 are the usual choices). Default 0 = no trimming, which is itself a choice: trimming and `restrict_to_overlap` are DIFFERENT populations, so do not substitute one for the other when matching a locked primary spec.|
|restrict_to_overlap|bool|선택|False|true restricts the estimate to COMMON SUPPORT before estimating; false (the default) estimates on everyone. NOT a formatting flag — it changes which patients the effect is defined over, so a node that omits it is not comparable with one that sets it. State it explicitly whenever the run's primary spec does.|
|match_ratio|integer|선택|1|Controls per treated unit (method="psm"). Default 1.|
|caliper|number|선택|0.2|Matching caliper in SDs of the PS logit (method="psm"). Default 0.2 (Austin).|
|n_bootstrap|integer|선택|200|Bootstrap replicates for the CI; the whole estimator (including the propensity fit) is resampled. Default 200. Set 0 to skip — do that for "psm" on a large cohort, where every replicate re-matches and the resampling dominates the runtime.|
|reference_levels|object|선택|None|{categorical covariate: baseline level}. Optional.|
|random_state|integer|선택|42|Seed. Default 42.|
|imputation_column|column|선택|''|Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default) — the tool detects `_imputation` on its own, runs the estimate INSIDE each draw and pools the m results by Rubin's rules, so every reported n counts PATIENTS. Name a column only when the index is spelled differently; pass "none" to analyse the stacked draws as one cohort, which counts every patient m times and is almost never what the protocol means.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 일관성·간섭 없음·조건부 교환가능성·positivity. 처치 이전 교란변수만 조정한다. trimming/overlap 제한은 대상 집단을 바꾼다. 결과모형/성향모형의 필요한 명세 가정은 선택한 estimator에 따라 다르다. doubly robust도 두 모형 모두 틀리면 보호되지 않는다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|estimand|string|ATT \| ATE \| ATO — the target population this row's effect is defined over|
|method|string|ipw \| gcomp \| psm \| aipw|
|feasible|bool|false when an arm has <10 patients — no estimate was produced|
|n_loaded|integer|rows before listwise deletion|
|n_complete|integer|after listwise deletion|
|n_analyzed|integer|after common-support restriction|
|n_covariate_missing|integer|kept patients with an unrecorded covariate|
|covariates_unrecorded|string|which covariates were unrecorded among kept patients|
|n_imputations|integer|m when the input is multiply imputed / 조건: MI input|
|n_treated|integer|처치군 수|
|n_control|integer|대조군 수|
|mu_treated|number|observed outcome mean in the treated|
|mu_control|number|counterfactual control mean|
|effect|number|ATT (risk difference or mean difference)|
|effect_lower95|number|평균차 CI 하한|
|effect_upper95|number|평균차 CI 상한|
|effect_se|number|평균차 표준오차|
|ratio|number|risk ratio when the outcome is binary|
|n_bootstrap|integer|bootstrap 횟수(성공 수 별도 확인)|
|significant|bool|CI excludes 0|

**기존 Output 계약 메모:** Every row also reports the cohort flow — `n_loaded` -> `n_complete` (after listwise deletion) -> `n_analyzed` (after common support) — plus `n_covariate_missing` / `covariates_unrecorded` for patients KEPT with an unrecorded covariate (one-hot encoding models them at its reference level rather than adjusting for them), and `feasible`, which is false when an arm was left with fewer than 10 patients and no estimate was produced.

**Output 검토 / 가정 위반 시 주의:** mu_treated/mu_control/effect/CI와 코호트 흐름·feasible은 유용하다. effect는 처치-대조 평균차(이진 결과는 위험차)이고 ratio와 구별한다. feasible=false의 결측 효과를 0으로 읽지 않는다. 범주형 미기록의 기준범주 흡수는 미조정 교란을 남긴다. 성공 bootstrap 수·ESS·사전 지정 primary를 보존해야 한다.

**Processing Type:** 성향/결과모형 적합(방법별 상이) / bootstrap·대치 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-att_estimate_multi"></a>

## 13. `att_estimate_multi`

**Description / 목적:** 실제 처치군(ATT): 여러 추정법의 효과를 같은 코호트에서 비교한다.

**구현 근거:** [tool_sample.py:12362](../tool_sample/tool_sample.py#L12362) · `att_estimate_multi`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|treatment_column|column|필수|— (인수 필수)|Column separating treated from control.|
|treatment_values|list[value]|필수|— (인수 필수)|ONLY the TREATED arm's value(s), verbatim.|
|covariates|list[column]|필수|— (인수 필수)|Confounders to adjust for. Never empty.|
|outcome_column|column|필수|— (인수 필수)|The outcome whose ATT is estimated.|
|methods|list[value]|필수|None|The loop axis: any of "ipw", "gcomp", "psm", "aipw" — e.g. all four when the protocol asks whether the approaches agree. Defaults to all four if omitted.|
|outcome_values|list[value]|선택|None|Positive-class value(s) for a binary outcome; omit for a numeric one.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|clip_bounds|list[number]|선택|None|Clip the propensity score, e.g. [0.01, 0.99].|
|trim|number|선택|0.0|Drop rows whose PS falls outside [trim, 1-trim] (0.01 / 0.05 are the usual choices). Default 0 = no trimming, which is itself a choice: trimming and `restrict_to_overlap` are DIFFERENT populations, so do not substitute one for the other when matching a locked primary spec.|
|restrict_to_overlap|bool|선택|False|true restricts the estimate to COMMON SUPPORT before estimating; false (the default) estimates on everyone. NOT a formatting flag — it changes which patients the effect is defined over, so a node that omits it is not comparable with one that sets it. State it explicitly whenever the run's primary spec does.|
|match_ratio|integer|선택|1|Controls per treated unit for "psm". Default 1.|
|caliper|number|선택|0.2|Matching caliper in SDs of the PS logit. Default 0.2.|
|n_bootstrap|integer|선택|200|Replicates per method (default 200). Every method pays it, so lower it — or set 0 — when "psm" is in the list. On a MULTIPLY IMPUTED input the replicates are split across the draws, so the result reports `n_bootstrap_per_draw` alongside `n_bootstrap_total` and `n_bootstrap_requested` — a per-draw count smaller than what you asked for is expected, not a failure.|
|reference_levels|object|선택|None|{categorical covariate: baseline level}. Optional.|
|random_state|integer|선택|42|Seed. Default 42.|
|imputation_column|column|선택|''|Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default) — the tool detects `_imputation` on its own, runs the estimate INSIDE each draw and pools the m results by Rubin's rules, so every reported n counts PATIENTS. Name a column only when the index is spelled differently; pass "none" to analyse the stacked draws as one cohort, which counts every patient m times and is almost never what the protocol means.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 일관성·간섭 없음·조건부 교환가능성·positivity. 처치 이전 교란변수만 조정한다. trimming/overlap 제한은 대상 집단을 바꾼다. 결과모형/성향모형의 필요한 명세 가정은 선택한 estimator에 따라 다르다. doubly robust도 두 모형 모두 틀리면 보호되지 않는다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_method`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|estimand|string|ATT \| ATE \| ATO — the target population this row's effect is defined over|
|method|string|ipw \| gcomp \| psm \| aipw|
|feasible|bool|false when an arm has <10 patients — no estimate was produced|
|n_loaded|integer|rows before listwise deletion|
|n_complete|integer|after listwise deletion|
|n_analyzed|integer|after common-support restriction|
|n_covariate_missing|integer|kept patients with an unrecorded covariate|
|covariates_unrecorded|string|which covariates were unrecorded among kept patients|
|n_imputations|integer|m when the input is multiply imputed / 조건: MI input|
|n_treated|integer|처치군 수|
|n_control|integer|대조군 수|
|mu_treated|number|observed outcome mean in the treated|
|mu_control|number|counterfactual control mean|
|effect|number|ATT (risk difference or mean difference)|
|effect_lower95|number|평균차 CI 하한|
|effect_upper95|number|평균차 CI 상한|
|effect_se|number|평균차 표준오차|
|ratio|number|risk ratio when the outcome is binary|
|n_bootstrap|integer|bootstrap 횟수(성공 수 별도 확인)|
|significant|bool|CI excludes 0|
|specification|string|method label|
|effect_minus_primary|number|difference from the primary_method row|

**Output 검토 / 가정 위반 시 주의:** mu_treated/mu_control/effect/CI와 코호트 흐름·feasible은 유용하다. effect는 처치-대조 평균차(이진 결과는 위험차)이고 ratio와 구별한다. feasible=false의 결측 효과를 0으로 읽지 않는다. 범주형 미기록의 기준범주 흡수는 미조정 교란을 남긴다. 성공 bootstrap 수·ESS·사전 지정 primary를 보존해야 한다.

**Processing Type:** 성향/결과모형 적합(방법별 상이) / 추정법×bootstrap·대치 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-att_sensitivity"></a>

## 14. `att_sensitivity`

**Description / 목적:** 실제 처치군(ATT): 코호트·공변량·절단 등 분석 설정을 바꾸어 효과 민감도를 비교한다.

**구현 근거:** [tool_sample.py:12622](../tool_sample/tool_sample.py#L12622) · `att_sensitivity`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|treatment_column|column|필수|— (인수 필수)|Column separating treated from control.|
|treatment_values|list[value]|필수|— (인수 필수)|ONLY the TREATED arm's value(s), verbatim.|
|covariates|list[column]|필수|— (인수 필수)|DEFAULT confounder set, overridable per specification.|
|outcome_column|column|필수|— (인수 필수)|The outcome whose ATT is estimated.|
|specifications|list[object]|필수|None|The loop axis: an ORDERED list of override objects; the FIRST is the PRIMARY analysis and should therefore override NOTHING. Each other entry may override this node's own arguments — {"label":"Primary"}, {"label":"Trim 1%","trim":0.01}, {"label":"Doubly robust","method":"aipw"}, {"label":"Drop stage","covariates":[...]}, {"label":"Complete cases","where":"..."}. A `method` override must be one of "ipw", "gcomp", "psm", "aipw" VERBATIM — an unknown name (e.g. "g_computation") now fails the whole node up front rather than dropping that one row. Never empty.|
|outcome_values|list[value]|선택|None|Positive-class value(s) for a binary outcome.|
|method|string|선택|'ipw'|DEFAULT estimator for specifications that do not name one — "ipw" (default) \| "gcomp" \| "psm" \| "aipw", verbatim.|
|where|string|선택|''|DEFAULT cohort filter, overridable per specification.|
|clip_bounds|list[number]|선택|None|DEFAULT propensity clip, e.g. [0.01, 0.99], overridable per specification.|
|trim|number|선택|0.0|DEFAULT trimming. Drop rows whose PS falls outside [trim, 1-trim] (0.01 / 0.05 are the usual choices). Default 0 = no trimming, which is itself a choice: trimming and `restrict_to_overlap` are DIFFERENT populations, so do not substitute one for the other when matching a locked primary spec.|
|restrict_to_overlap|bool|선택|False|DEFAULT positivity handling. true restricts the estimate to COMMON SUPPORT before estimating; false (the default) estimates on everyone. NOT a formatting flag — it changes which patients the effect is defined over, so a node that omits it is not comparable with one that sets it. State it explicitly whenever the run's primary spec does.|
|match_ratio|integer|선택|1|Controls per treated unit for "psm". Default 1.|
|caliper|number|선택|0.2|Matching caliper in SDs of the PS logit. Default 0.2.|
|n_bootstrap|integer|선택|200|Replicates per specification (default 200) — this is paid once per row, so lower it for a long specification list.|
|reference_levels|object|선택|None|{categorical covariate: baseline level}. Optional.|
|random_state|integer|선택|42|Seed. Default 42.|
|imputation_column|column|선택|''|Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default) — the tool detects `_imputation` on its own, runs the estimate INSIDE each draw and pools the m results by Rubin's rules, so every reported n counts PATIENTS. Name a column only when the index is spelled differently; pass "none" to analyse the stacked draws as one cohort, which counts every patient m times and is almost never what the protocol means.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 일관성·간섭 없음·조건부 교환가능성·positivity. 처치 이전 교란변수만 조정한다. trimming/overlap 제한은 대상 집단을 바꾼다. 결과모형/성향모형의 필요한 명세 가정은 선택한 estimator에 따라 다르다. doubly robust도 두 모형 모두 틀리면 보호되지 않는다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_spec`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|specification|string|분석 설정 식별자|
|estimand|string|ATT \| ATE \| ATO — the target population this row's effect is defined over|
|method|string|ipw \| gcomp \| psm \| aipw|
|feasible|bool|false when an arm has <10 patients — no estimate was produced|
|n_loaded|integer|rows before listwise deletion|
|n_complete|integer|after listwise deletion|
|n_analyzed|integer|after common-support restriction|
|n_covariate_missing|integer|kept patients with an unrecorded covariate|
|covariates_unrecorded|string|which covariates were unrecorded among kept patients|
|n_imputations|integer|m when the input is multiply imputed / 조건: MI input|
|n_treated|integer|처치군 수|
|n_control|integer|대조군 수|
|mu_treated|number|observed outcome mean in the treated|
|mu_control|number|counterfactual control mean|
|effect|number|ATT (risk difference or mean difference)|
|effect_lower95|number|평균차 CI 하한|
|effect_upper95|number|평균차 CI 상한|
|effect_se|number|평균차 표준오차|
|ratio|number|risk ratio when the outcome is binary|
|n_bootstrap|integer|bootstrap 횟수(성공 수 별도 확인)|
|significant|bool|CI excludes 0|
|effect_minus_primary|number|difference from the first specification|

**Output 검토 / 가정 위반 시 주의:** mu_treated/mu_control/effect/CI와 코호트 흐름·feasible은 유용하다. effect는 처치-대조 평균차(이진 결과는 위험차)이고 ratio와 구별한다. feasible=false의 결측 효과를 0으로 읽지 않는다. 범주형 미기록의 기준범주 흡수는 미조정 교란을 남긴다. 성공 bootstrap 수·ESS·사전 지정 primary를 보존해야 한다.

**Processing Type:** 성향/결과모형 적합(방법별 상이) / 설정×bootstrap·대치 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-ate_weight"></a>

## 15. `ate_weight`

**Description / 목적:** 전체 모집단(ATE), 선택 시 중첩 모집단(ATO)을 목표로 성향점수 가중 코호트를 생성한다.

**구현 근거:** [tool_sample.py:11825](../tool_sample/tool_sample.py#L11825) · `ate_weight`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|treatment_column|column|필수|— (인수 필수)|Column separating treated from control.|
|treatment_values|list[value]|필수|— (인수 필수)|ONLY the TREATED arm's value(s) — control is everyone else, inferred. For a 0/1 flag pass [1], not [1,0]; for a labelled column pass just the treated label, verbatim.|
|covariates|list[column]|필수|— (인수 필수)|Confounders the propensity model adjusts for (categoricals auto one-hot). EXCLUDE the treatment, the outcome and any identifier. Never empty.|
|estimand|string|선택|'ate'|"ate" (default) averages the effect over the WHOLE cohort — what treatment would do if everyone got it. "ato" averages it over the OVERLAP population (bounded 1-PS / PS weights) — the effect among patients who could plausibly have received either arm. Prefer "ato" when propensity scores approach 0 or 1, because the ATE's 1/PS weights then hand a handful of patients most of the estimate; say in the report that it answers the narrower question. For the effect in the TREATED use the att_* tools instead — this parameter cannot request the ATT.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|clip_bounds|list[number]|선택|None|Clip the propensity score to [lower, upper], e.g. [0.01, 0.99]. MORE important here than for the ATT: 1/PS is unbounded, so one patient with PS=0.001 carries the weight of a thousand. Set it, or use estimand="ato".|
|trim|number|선택|0.0|Drop rows whose PS falls outside [trim, 1-trim] (0.01 / 0.05 are the usual choices). Default 0 = no trimming, which is itself a choice: trimming and `restrict_to_overlap` are DIFFERENT populations, so do not substitute one for the other when matching a locked primary spec.|
|restrict_to_overlap|bool|선택|False|true drops the non-overlap rows from the OUTPUT; false (default) keeps every row and only flags them in `overlap_flag`. Must match the propensity specification the run's ate_* estimators use.|
|weight_column|string|선택|''|Name of the added weight column. Defaults to "ate_weight", or "overlap_weight" when estimand=ato.|
|reference_levels|object|선택|None|{categorical covariate: baseline level}. Optional.|
|random_state|integer|선택|42|Propensity-model seed. Default 42.|
|imputation_column|column|선택|''|Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default): the propensity model is fitted SEPARATELY inside each draw and the index survives in the OUTPUT so the downstream estimator can pool.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 일관성·간섭 없음·조건부 교환가능성·positivity. 처치 이전 교란변수만 조정한다. trimming/overlap 제한은 대상 집단을 바꾼다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|propensity_score|number|원본 스키마의 파생 열; 이름에 표시된 지표/시점 기준|
|ate_weight|number|1/PS for treated, 1/(1-PS) for controls — named `overlap_weight` when estimand=ato (1-PS treated, PS control), or params.weight_column|
|overlap_flag|integer|1 = on common support|

**기존 Output 계약 메모:** Weighted patient cohort on the SAME propensity fit the ate_* estimators use. ESS / weight-range diagnostics are a side deliverable, not the node output.

**Output 검토 / 가정 위반 시 주의:** 성향점수·가중치·overlap_flag와 원 환자 정보를 보존한다. estimand 및 사용자 weight_column 설정에 따라 열 이름이 달라진다. 효과나 CI를 계산한 결과는 아니다. 가중 분포·ESS·ASD를 함께 보고해야 한다.

**Processing Type:** 성향점수 모델 적합 / 대치 draw 반복 가능 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-ate_estimate"></a>

## 16. `ate_estimate`

**Description / 목적:** 전체 모집단(ATE), 선택 시 중첩 모집단(ATO): 한 추정법으로 잠재결과 평균과 절대 효과차 및 bootstrap CI를 추정한다.

**구현 근거:** [tool_sample.py:12188](../tool_sample/tool_sample.py#L12188) · `ate_estimate`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|treatment_column|column|필수|— (인수 필수)|Column separating treated from control.|
|treatment_values|list[value]|필수|— (인수 필수)|ONLY the TREATED arm's value(s), verbatim — never list every value.|
|covariates|list[column]|필수|— (인수 필수)|Confounders to adjust for. Never empty.|
|outcome_column|column|필수|— (인수 필수)|The outcome whose ATE is estimated.|
|outcome_values|list[value]|선택|None|Positive-class value(s) for a BINARY outcome, e.g. ["Dead"] — the effect is then a risk difference and `ratio` a risk ratio. OMIT for a numeric outcome, which is read as a number and gives a mean difference.|
|method|string|선택|'ipw'|"ipw" (default, 1/PS and 1/(1-PS) weights) \| "gcomp" (outcome regression standardized to every patient) \| "aipw" (doubly robust — consistent if EITHER the propensity or the outcome model is right). "psm" is NOT available: matching without replacement builds a control group FOR THE TREATED, so it only identifies the ATT.|
|estimand|string|선택|'ate'|"ate" (default) averages the effect over the WHOLE cohort — what treatment would do if everyone got it. "ato" averages it over the OVERLAP population (bounded 1-PS / PS weights) — the effect among patients who could plausibly have received either arm. Prefer "ato" when propensity scores approach 0 or 1, because the ATE's 1/PS weights then hand a handful of patients most of the estimate; say in the report that it answers the narrower question. For the effect in the TREATED use the att_* tools instead — this parameter cannot request the ATT.|
|where|string|선택|''|SQL boolean cohort filter. Optional. A COMPLETE-CASE filter here does not adjust for that covariate, it deletes whichever arm rarely records it — impute instead.|
|clip_bounds|list[number]|선택|None|Clip the propensity score, e.g. [0.01, 0.99]. Set it: the ATE's 1/PS weights are unbounded, so a near-deterministic patient can dominate the estimate.|
|trim|number|선택|0.0|Drop rows whose PS falls outside [trim, 1-trim] (0.01 / 0.05 are the usual choices). Default 0 = no trimming, which is itself a choice: trimming and `restrict_to_overlap` are DIFFERENT populations, so do not substitute one for the other when matching a locked primary spec.|
|restrict_to_overlap|bool|선택|False|true restricts the estimate to COMMON SUPPORT before estimating; false (the default) estimates on everyone. NOT a formatting flag — it changes which patients the effect is defined over, so a node that omits it is not comparable with one that sets it. State it explicitly whenever the run's primary spec does.|
|n_bootstrap|integer|선택|200|Bootstrap replicates for the CI; the whole estimator (including the propensity fit) is resampled. Default 200. Set 0 to skip.|
|reference_levels|object|선택|None|{categorical covariate: baseline level}. Optional.|
|random_state|integer|선택|42|Seed. Default 42.|
|imputation_column|column|선택|''|Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default) — the tool detects `_imputation` on its own, runs the estimate INSIDE each draw and pools the m results by Rubin's rules, so every reported n counts PATIENTS. Name a column only when the index is spelled differently; pass "none" to analyse the stacked draws as one cohort, which counts every patient m times and is almost never what the protocol means.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 일관성·간섭 없음·조건부 교환가능성·positivity. 처치 이전 교란변수만 조정한다. trimming/overlap 제한은 대상 집단을 바꾼다. 결과모형/성향모형의 필요한 명세 가정은 선택한 estimator에 따라 다르다. doubly robust도 두 모형 모두 틀리면 보호되지 않는다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|estimand|string|ATE \| ATO — the target population this row's effect is defined over|
|method|string|ipw \| gcomp \| aipw|
|feasible|bool|false when an arm has <10 patients — no estimate was produced|
|n_loaded|integer|rows before listwise deletion|
|n_complete|integer|after listwise deletion|
|n_analyzed|integer|after common-support restriction|
|n_covariate_missing|integer|kept patients with an unrecorded covariate|
|covariates_unrecorded|string|which covariates were unrecorded among kept patients|
|n_imputations|integer|m when the input is multiply imputed / 조건: MI input|
|n_treated|integer|처치군 수|
|n_control|integer|대조군 수|
|mu_treated|number|counterfactual mean if EVERYONE were treated (over the target population)|
|mu_control|number|counterfactual mean if NOBODY were treated (same population)|
|effect|number|ATE / ATO (risk difference or mean difference), = mu_treated - mu_control|
|effect_lower95|number|평균차 CI 하한|
|effect_upper95|number|평균차 CI 상한|
|effect_se|number|평균차 표준오차|
|ratio|number|risk ratio when the outcome is binary|
|n_bootstrap|integer|bootstrap 횟수(성공 수 별도 확인)|
|significant|bool|CI excludes 0|

**기존 Output 계약 메모:** Every row also reports the cohort flow — `n_loaded` -> `n_complete` (after listwise deletion) -> `n_analyzed` (after common support) — plus `n_covariate_missing` / `covariates_unrecorded` for patients KEPT with an unrecorded covariate (one-hot encoding models them at its reference level rather than adjusting for them), and `feasible`, which is false when an arm was left with fewer than 10 patients and no estimate was produced.

**Output 검토 / 가정 위반 시 주의:** mu_treated/mu_control/effect/CI와 코호트 흐름·feasible은 유용하다. effect는 처치-대조 평균차(이진 결과는 위험차)이고 ratio와 구별한다. feasible=false의 결측 효과를 0으로 읽지 않는다. 범주형 미기록의 기준범주 흡수는 미조정 교란을 남긴다. 성공 bootstrap 수·ESS·사전 지정 primary를 보존해야 한다.

**Processing Type:** 성향/결과모형 적합(방법별 상이) / bootstrap·대치 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-ate_estimate_multi"></a>

## 17. `ate_estimate_multi`

**Description / 목적:** 전체 모집단(ATE), 선택 시 중첩 모집단(ATO): 여러 추정법의 효과를 같은 코호트에서 비교한다.

**구현 근거:** [tool_sample.py:12406](../tool_sample/tool_sample.py#L12406) · `ate_estimate_multi`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|treatment_column|column|필수|— (인수 필수)|Column separating treated from control.|
|treatment_values|list[value]|필수|— (인수 필수)|ONLY the TREATED arm's value(s), verbatim.|
|covariates|list[column]|필수|— (인수 필수)|Confounders to adjust for. Never empty.|
|outcome_column|column|필수|— (인수 필수)|The outcome whose ATE is estimated.|
|methods|list[value]|필수|None|The loop axis: any of "ipw", "gcomp", "aipw". Defaults to all three if omitted. "psm" is REJECTED — it only identifies the ATT.|
|outcome_values|list[value]|선택|None|Positive-class value(s) for a binary outcome; omit for a numeric one.|
|estimand|string|선택|'ate'|"ate" (default) averages the effect over the WHOLE cohort — what treatment would do if everyone got it. "ato" averages it over the OVERLAP population (bounded 1-PS / PS weights) — the effect among patients who could plausibly have received either arm. Prefer "ato" when propensity scores approach 0 or 1, because the ATE's 1/PS weights then hand a handful of patients most of the estimate; say in the report that it answers the narrower question. For the effect in the TREATED use the att_* tools instead — this parameter cannot request the ATT.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|clip_bounds|list[number]|선택|None|Clip the propensity score, e.g. [0.01, 0.99].|
|trim|number|선택|0.0|Drop rows whose PS falls outside [trim, 1-trim] (0.01 / 0.05 are the usual choices). Default 0 = no trimming, which is itself a choice: trimming and `restrict_to_overlap` are DIFFERENT populations, so do not substitute one for the other when matching a locked primary spec.|
|restrict_to_overlap|bool|선택|False|true restricts the estimate to COMMON SUPPORT before estimating; false (the default) estimates on everyone. NOT a formatting flag — it changes which patients the effect is defined over, so a node that omits it is not comparable with one that sets it. State it explicitly whenever the run's primary spec does.|
|n_bootstrap|integer|선택|200|Replicates per method (default 200). On a MULTIPLY IMPUTED input the replicates are split across the draws, so a per-draw count smaller than what you asked for is expected, not a failure.|
|reference_levels|object|선택|None|{categorical covariate: baseline level}. Optional.|
|random_state|integer|선택|42|Seed. Default 42.|
|imputation_column|column|선택|''|Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default) — the tool detects `_imputation` on its own, runs the estimate INSIDE each draw and pools the m results by Rubin's rules, so every reported n counts PATIENTS. Name a column only when the index is spelled differently; pass "none" to analyse the stacked draws as one cohort, which counts every patient m times and is almost never what the protocol means.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 일관성·간섭 없음·조건부 교환가능성·positivity. 처치 이전 교란변수만 조정한다. trimming/overlap 제한은 대상 집단을 바꾼다. 결과모형/성향모형의 필요한 명세 가정은 선택한 estimator에 따라 다르다. doubly robust도 두 모형 모두 틀리면 보호되지 않는다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_method`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|estimand|string|ATE \| ATO — the target population this row's effect is defined over|
|method|string|ipw \| gcomp \| aipw|
|feasible|bool|false when an arm has <10 patients — no estimate was produced|
|n_loaded|integer|rows before listwise deletion|
|n_complete|integer|after listwise deletion|
|n_analyzed|integer|after common-support restriction|
|n_covariate_missing|integer|kept patients with an unrecorded covariate|
|covariates_unrecorded|string|which covariates were unrecorded among kept patients|
|n_imputations|integer|m when the input is multiply imputed / 조건: MI input|
|n_treated|integer|처치군 수|
|n_control|integer|대조군 수|
|mu_treated|number|counterfactual mean if EVERYONE were treated (over the target population)|
|mu_control|number|counterfactual mean if NOBODY were treated (same population)|
|effect|number|ATE / ATO (risk difference or mean difference), = mu_treated - mu_control|
|effect_lower95|number|평균차 CI 하한|
|effect_upper95|number|평균차 CI 상한|
|effect_se|number|평균차 표준오차|
|ratio|number|risk ratio when the outcome is binary|
|n_bootstrap|integer|bootstrap 횟수(성공 수 별도 확인)|
|significant|bool|CI excludes 0|
|specification|string|method label|
|effect_minus_primary|number|difference from the first method row|

**Output 검토 / 가정 위반 시 주의:** mu_treated/mu_control/effect/CI와 코호트 흐름·feasible은 유용하다. effect는 처치-대조 평균차(이진 결과는 위험차)이고 ratio와 구별한다. feasible=false의 결측 효과를 0으로 읽지 않는다. 범주형 미기록의 기준범주 흡수는 미조정 교란을 남긴다. 성공 bootstrap 수·ESS·사전 지정 primary를 보존해야 한다.

**Processing Type:** 성향/결과모형 적합(방법별 상이) / 추정법×bootstrap·대치 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-ate_sensitivity"></a>

## 18. `ate_sensitivity`

**Description / 목적:** 전체 모집단(ATE), 선택 시 중첩 모집단(ATO): 코호트·공변량·절단 등 분석 설정을 바꾸어 효과 민감도를 비교한다.

**구현 근거:** [tool_sample.py:12667](../tool_sample/tool_sample.py#L12667) · `ate_sensitivity`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|treatment_column|column|필수|— (인수 필수)|Column separating treated from control.|
|treatment_values|list[value]|필수|— (인수 필수)|ONLY the TREATED arm's value(s), verbatim.|
|covariates|list[column]|필수|— (인수 필수)|DEFAULT confounder set, overridable per specification.|
|outcome_column|column|필수|— (인수 필수)|The outcome whose ATE is estimated.|
|specifications|list[object]|필수|None|The loop axis: an ORDERED list of override objects; the FIRST is the PRIMARY analysis and should therefore override NOTHING. Each other entry may override this node's own arguments — {"label":"Primary"}, {"label":"Trim 1%","trim":0.01}, {"label":"Doubly robust","method":"aipw"}, {"label":"Overlap population","estimand":"ato"}. A `method` override must be "ipw", "gcomp" or "aipw" VERBATIM and an `estimand` override "ate" or "ato" — anything else fails the whole node up front rather than dropping one row.|
|outcome_values|list[value]|선택|None|Positive-class value(s) for a binary outcome.|
|method|string|선택|'ipw'|DEFAULT estimator. "ipw" (default, 1/PS and 1/(1-PS) weights) \| "gcomp" (outcome regression standardized to every patient) \| "aipw" (doubly robust — consistent if EITHER the propensity or the outcome model is right). "psm" is NOT available: matching without replacement builds a control group FOR THE TREATED, so it only identifies the ATT.|
|estimand|string|선택|'ate'|DEFAULT estimand. "ate" (default) averages the effect over the WHOLE cohort — what treatment would do if everyone got it. "ato" averages it over the OVERLAP population (bounded 1-PS / PS weights) — the effect among patients who could plausibly have received either arm. Prefer "ato" when propensity scores approach 0 or 1, because the ATE's 1/PS weights then hand a handful of patients most of the estimate; say in the report that it answers the narrower question. For the effect in the TREATED use the att_* tools instead — this parameter cannot request the ATT.|
|where|string|선택|''|DEFAULT cohort filter, overridable per specification.|
|clip_bounds|list[number]|선택|None|DEFAULT propensity clip, e.g. [0.01, 0.99], overridable per specification.|
|trim|number|선택|0.0|DEFAULT trimming. Drop rows whose PS falls outside [trim, 1-trim] (0.01 / 0.05 are the usual choices). Default 0 = no trimming, which is itself a choice: trimming and `restrict_to_overlap` are DIFFERENT populations, so do not substitute one for the other when matching a locked primary spec.|
|restrict_to_overlap|bool|선택|False|DEFAULT positivity handling. true restricts the estimate to COMMON SUPPORT before estimating; false (the default) estimates on everyone. NOT a formatting flag — it changes which patients the effect is defined over, so a node that omits it is not comparable with one that sets it. State it explicitly whenever the run's primary spec does.|
|n_bootstrap|integer|선택|200|Replicates per specification (default 200) — paid once per row, so lower it for a long specification list.|
|reference_levels|object|선택|None|{categorical covariate: baseline level}. Optional.|
|random_state|integer|선택|42|Seed. Default 42.|
|imputation_column|column|선택|''|Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default) — the tool detects `_imputation` on its own, runs the estimate INSIDE each draw and pools the m results by Rubin's rules, so every reported n counts PATIENTS. Name a column only when the index is spelled differently; pass "none" to analyse the stacked draws as one cohort, which counts every patient m times and is almost never what the protocol means.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 일관성·간섭 없음·조건부 교환가능성·positivity. 처치 이전 교란변수만 조정한다. trimming/overlap 제한은 대상 집단을 바꾼다. 결과모형/성향모형의 필요한 명세 가정은 선택한 estimator에 따라 다르다. doubly robust도 두 모형 모두 틀리면 보호되지 않는다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_spec`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|specification|string|분석 설정 식별자|
|estimand|string|ATE \| ATO — the target population this row's effect is defined over|
|method|string|ipw \| gcomp \| aipw|
|feasible|bool|false when an arm has <10 patients — no estimate was produced|
|n_loaded|integer|rows before listwise deletion|
|n_complete|integer|after listwise deletion|
|n_analyzed|integer|after common-support restriction|
|n_covariate_missing|integer|kept patients with an unrecorded covariate|
|covariates_unrecorded|string|which covariates were unrecorded among kept patients|
|n_imputations|integer|m when the input is multiply imputed / 조건: MI input|
|n_treated|integer|처치군 수|
|n_control|integer|대조군 수|
|mu_treated|number|counterfactual mean if EVERYONE were treated (over the target population)|
|mu_control|number|counterfactual mean if NOBODY were treated (same population)|
|effect|number|ATE / ATO (risk difference or mean difference), = mu_treated - mu_control|
|effect_lower95|number|평균차 CI 하한|
|effect_upper95|number|평균차 CI 상한|
|effect_se|number|평균차 표준오차|
|ratio|number|risk ratio when the outcome is binary|
|n_bootstrap|integer|bootstrap 횟수(성공 수 별도 확인)|
|significant|bool|CI excludes 0|
|effect_minus_primary|number|difference from the first specification|

**Output 검토 / 가정 위반 시 주의:** mu_treated/mu_control/effect/CI와 코호트 흐름·feasible은 유용하다. effect는 처치-대조 평균차(이진 결과는 위험차)이고 ratio와 구별한다. feasible=false의 결측 효과를 0으로 읽지 않는다. 범주형 미기록의 기준범주 흡수는 미조정 교란을 남긴다. 성공 bootstrap 수·ESS·사전 지정 primary를 보존해야 한다.

**Processing Type:** 성향/결과모형 적합(방법별 상이) / 설정×bootstrap·대치 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-covariate_balance"></a>

## 19. `covariate_balance`

**Description / 목적:** 처치/대조군의 변수별·범주수준별 절대 표준화 차이(ASD)를 계산한다.

**구현 근거:** [tool_sample.py:12887](../tool_sample/tool_sample.py#L12887) · `covariate_balance`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|treatment_column|column|필수|— (인수 필수)|Column separating treated from control.|
|treatment_values|list[value]|필수|— (인수 필수)|ONLY the TREATED arm's value(s), verbatim.|
|covariates|list[column]|필수|— (인수 필수)|The covariates to check. Never empty.|
|weight_column|column|선택|''|Weight column from att_weight / iptw_weight. Omit for the CRUDE (unweighted) cohort.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|cat_var|list[column]|선택|None|Force these covariates to be CATEGORICAL (one ASD row per level). Use for numeric codebook codes (T/N/grade/histology, 0/1 flags).|
|cont_var|list[column]|선택|None|Force these covariates to be CONTINUOUS (one ASD row, no levels).|
|imputation_column|column|선택|''|Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default): balance is a property of each COMPLETED dataset, so ASDs are computed inside every `_imputation` draw and averaged.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 같은 모집단·같은 변수코딩으로 비교하며 weight_column은 적절한 비음수 가중치여야 한다. 수치형/범주형 강제 지정 검토.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_variable_level`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|variable|string|대상 변수|
|level|string|category level; empty/null for a continuous covariate|
|type|string|continuous \| categorical|
|treated|number|mean or proportion in treated|
|control|number|mean or proportion in control|
|asd|number|absolute standardized difference|
|balanced|bool|asd < 0.1|
|n_imputations|integer|대치 draw 수 / 조건: MI input|

**기존 Output 계약 메모:** Tidy ASD table. Categorical covariates emit one row per level.

**Output 검토 / 가정 위반 시 주의:** treated/control/ASD/균형 여부는 균형 점검에 적절하다. 0.1은 관례적 기준이고 인과 식별의 증거가 아니다. 분산 0일 때 ASD, 가중 ESS, 결측 처리의 영향도 확인한다.

**Processing Type:** 모델 적합 없음 / 변수·수준 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-covariate_balance_multi"></a>

## 20. `covariate_balance_multi`

**Description / 목적:** 원 코호트·매칭·가중 코호트 등 시나리오별 균형을 비교한다.

**구현 근거:** [tool_sample.py:12941](../tool_sample/tool_sample.py#L12941) · `covariate_balance_multi`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|treatment_column|column|필수|— (인수 필수)|Column separating treated from control.|
|treatment_values|list[value]|필수|— (인수 필수)|ONLY the TREATED arm's value(s), verbatim.|
|covariates|list[column]|필수|— (인수 필수)|The covariates to check. Never empty.|
|scenarios|list[object]|필수|None|The loop axis: an ORDERED list of {"label", "weight_column"?, "where"?} populations; the FIRST is the reference the others are compared against. A scenario with no weight_column is the crude cohort. Never empty.|
|where|string|선택|''|DEFAULT cohort filter, overridable per scenario. Optional.|
|cat_var|list[column]|선택|None|Force these covariates to be CATEGORICAL (one ASD row per level).|
|cont_var|list[column]|선택|None|Force these covariates to be CONTINUOUS (one ASD row, no levels).|
|imputation_column|column|선택|''|Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default): every scenario's ASDs are computed inside each `_imputation` draw and averaged.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 시나리오 간 동일한 변수·분모·코딩 및 적절한 가중치. 각 source가 실제 존재해야 한다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_scenario_level`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|scenario|string|비교 시나리오|
|variable|string|대상 변수|
|level|string|category level; empty/null for a continuous covariate|
|type|string|continuous \| categorical|
|treated|number|mean or proportion in treated|
|control|number|mean or proportion in control|
|asd|number|absolute standardized difference|
|balanced|bool|asd < 0.1|
|asd_reference|number|ASD of the same variable/level in the first scenario|

**Output 검토 / 가정 위반 시 주의:** scenario와 asd_reference가 있어 비교에 적합하다. 서로 다른 환자집단의 균형 개선을 같은 모집단 효과로 해석하면 안 된다. n/ESS를 시나리오별 추가 권장.

**Processing Type:** 모델 적합 없음 / 시나리오·변수 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-evalue"></a>

## 21. `evalue`

**Description / 목적:** 보고된 효과를 설명해 없애기 위한 미측정 교란의 최소 연관 강도를 E-value로 계산한다.

**구현 근거:** [tool_sample.py:13027](../tool_sample/tool_sample.py#L13027) · `evalue`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|estimate|number|필수|— (인수 필수)|The observed effect estimate, copied from the upstream result (e.g. a hazard ratio of 1.42). Not a column name.|
|ci_lower|number|선택|None|Lower confidence limit of that estimate.|
|ci_upper|number|선택|None|Upper confidence limit of that estimate.|
|scale|string|선택|'rr'|"rr" (default) / "hr" are used as-is; "or" is converted as √OR unless `rare_outcome`; "rd" is a risk difference and REQUIRES `baseline_risk`.|
|baseline_risk|number|선택|None|Control-arm risk, required for scale="rd" so the difference can be put on the ratio scale.|
|rare_outcome|bool|선택|False|For scale="or": true uses the OR directly (rare-outcome approximation). Default false.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 효과 추정치/CI 등의 스칼라 수치가 주 입력이며 환자 테이블은 계산에 필요하지 않다. 행 데이터가 아닌 양의 효과 추정치와 CI 입력. scale·희귀결과 여부 등 RR 척도 변환 가정을 확인한다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|scale|string|rr \| hr \| or \| rd|
|estimate|number|metric/estimate_type 척도의 점추정|
|ci_lower|number|CI 하한|
|ci_upper|number|CI 상한|
|risk_ratio_scale|number|RR 척도로 변환한 효과|
|evalue_point|number|점추정 E-value|
|evalue_ci|number|귀무값에 가까운 CI의 E-value|

**Output 검토 / 가정 위반 시 주의:** 점 추정치와 귀무값에 가까운 CI의 E-value를 분리해 주는 것은 적절하다. OR/HR의 RR 근사는 상황에 의존한다. 큰 값이 교란 부재나 인과성을 증명하지 않는다.

**Processing Type:** 적합 없음 / 수치 1세트 계산 / 배치 불필요. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-bias_sensitivity"></a>

## 22. `bias_sensitivity`

**Description / 목적:** 가정한 미측정 교란 강도별 bounding factor와 편향 조정 효과를 계산한다.

**구현 근거:** [tool_sample.py:13116](../tool_sample/tool_sample.py#L13116) · `bias_sensitivity`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|estimate|number|필수|— (인수 필수)|The observed ratio estimate (RR/OR/HR), as a number.|
|ci_lower|number|선택|None|Lower confidence limit.|
|ci_upper|number|선택|None|Upper confidence limit.|
|scenarios|list[object]|선택|None|The loop axis: {"label", "rr_confounder_outcome", "rr_confounder_exposure"} per scenario — the confounder's association with the outcome and with the exposure.|
|grid|list[number]|선택|None|Used when `scenarios` is omitted: strengths applied to BOTH associations, e.g. [1.25,1.5,2.0,2.5,3.0]. Defaults to 1.1…3.0.|
|scale|str|선택|'rr'|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 효과 추정치/CI 등의 스칼라 수치가 주 입력이며 환자 테이블은 계산에 필요하지 않다. RR 척도와 교란-노출/결과 연관의 방향·크기 가정. 입력값 자체는 데이터에서 식별한 교란 효과가 아니다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_scenario`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|scenario|string|비교 시나리오|
|rr_confounder_outcome|number|가정한 교란-결과 RR|
|rr_confounder_exposure|number|가정한 교란-노출 RR|
|bounding_factor|number|최대 편향계수|
|adjusted_estimate|number|편향 조정 점추정|
|adjusted_ci_lower|number|편향 조정 CI 하한|
|adjusted_ci_upper|number|편향 조정 CI 상한|
|still_significant|bool|조정 후 귀무값 제외 여부|

**Output 검토 / 가정 위반 시 주의:** 시나리오별 조정 CI는 민감도 분석용이며 새로 관측한 효과가 아니다. still_significant는 가정한 범위 안의 결과이고 grid 밖에서 강건함을 보장하지 않는다.

**Processing Type:** 적합 없음 / grid·시나리오 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-impute_missing"></a>

## 23. `impute_missing`

**Description / 목적:** 수치형 MICE/중앙값, 범주형 최빈값으로 결측을 채우고 다중대치 draw를 쌓는다.

**구현 근거:** [tool_sample.py:13418](../tool_sample/tool_sample.py#L13418) · `impute_missing`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|columns|list[column]|필수|None|The variables to impute. Give MICE at least two numeric columns — with one there is nothing to condition on and every draw is the same mean fill.|
|method|string|선택|'mice'|"mice" (default, sklearn IterativeImputer) \| "median" \| "mode". The simple fills are deterministic, so n_imputations is forced to 1 for them.|
|n_imputations|integer|선택|1|Number of completed copies (default 1). Above 1 the output is m stacked copies of the SAME patients with an `_imputation` column — m× the rows, NOT m× the patients. The estimator downstream handles that index; a hand-written SQL node reading this table must group by it or filter to one draw.|
|max_iter|integer|선택|10|MICE iterations. Default 10.|
|add_indicator|bool|선택|True|Keep a `<column>_missing` 0/1 flag per imputed column. Default true.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. MICE는 관측 변수 조건부 MAR 및 적절한 대치모형 가정. MNAR이면 별도 민감도 분석. 예측 연구에서 대치는 train 안에서 학습해야 한다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|_imputation|integer|draw index 1…m; absent when n_imputations=1 / 조건: n_imputations>1|
|<column>_missing|integer|1 if the original cell was missing / 조건: add_indicator=true|

**Output 검토 / 가정 위반 시 주의:** _imputation은 환자 ID가 아니다. draw를 독립 환자로 취급하면 n/SE가 왜곡된다. method=mode도 수치형은 median으로 처리되고 MICE 실패 시 median 대체를 로그에만 남길 수 있다. 범주형은 확률적 다중대치가 아니다. 구현과 method 표기를 일치시켜야 한다.

**Processing Type:** MICE는 대치모형 적합 / 변수·draw 반복 / 한 번 호출, m배 메모리. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-predict_breast_os"></a>

## 24. `predict_breast_os`

**Description / 목적:** 고정 계수 PREDICT Breast v2.1로 수술 단독 생존확률과 순차 치료 추가 이득을 산출한다.

**구현 근거:** [tool_sample.py:13569](../tool_sample/tool_sample.py#L13569) · `predict_breast_os`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|age_start|column\|number|필수|None|Age at diagnosis in YEARS. The model domain is 25-85; a patient outside it is reported as ineligible, not clipped.|
|size|column\|number|필수|None|Invasive tumour size in MILLIMETRES (not cm — 2.0 would be read as a 2 mm tumour). Must be > 0.|
|grade|column\|number|필수|None|Tumour grade coded 1 / 2 / 3, or 9 for unknown. WARNING: for an ER-NEGATIVE patient v2.1 scores unknown grade as grade 1 (the most favourable), which is optimistic by tens of percentage points — those rows are refused unless `allow_unknown_grade_er_neg` is set.|
|nodes|column\|number|필수|None|Number of POSITIVE nodes as a whole number (0 allowed). Not a N-stage label and not a yes/no flag.|
|er|column\|number|필수|None|ER status coded 1 = positive, 0 = negative. Selects the model's whole ER branch (different baseline hazard and different coefficients), and hormone benefit is zero when 0 — so a wrong coding is not a small error.|
|her2|column\|number|선택|9|HER2 coded 1 = positive, 0 = negative, 9 = unknown. Defaults to 9, which sets its coefficient to zero — between + and −. Trastuzumab benefit is zero unless HER2 = 1.|
|ki67|column\|number|선택|9|KI67 coded 1 = positive, 0 = negative, 9 = unknown. Default 9. Only affects ER-positive patients in v2.1.|
|screen|column\|number|선택|2|Detection: 0 = clinically detected, 1 = screen detected, 2 = unknown (default; imputed to the cohort proportion 0.204 as in the model).|
|generation|column\|number|선택|0|Chemotherapy generation: 0 = none (default), 2 = 2nd generation, 3 = 3rd generation. This therapy's reported benefit is ZERO unless this flag says it was given. Bind the OBSERVED column to describe the gain the cohort actually had; pin it to 1 to ask what the therapy WOULD add for everyone.|
|horm|column\|number|선택|0|Hormone therapy: 1 / 0. Default 0. This therapy's reported benefit is ZERO unless this flag says it was given. Bind the OBSERVED column to describe the gain the cohort actually had; pin it to 1 to ask what the therapy WOULD add for everyone.|
|traz|column\|number|선택|0|Trastuzumab: 1 / 0. Default 0. Also needs HER2 = 1. This therapy's reported benefit is ZERO unless this flag says it was given. Bind the OBSERVED column to describe the gain the cohort actually had; pin it to 1 to ask what the therapy WOULD add for everyone.|
|bis|column\|number|선택|0|Bisphosphonate: 1 / 0. Default 0. This therapy's reported benefit is ZERO unless this flag says it was given. Bind the OBSERVED column to describe the gain the cohort actually had; pin it to 1 to ask what the therapy WOULD add for everyone.|
|year|integer|선택|10|Horizon in years, 1-15. Default 10. It names the output columns (`predict_os_10y`), so two nodes at different horizons can be joined.|
|on_invalid|string|선택|'skip'|"skip" (default) scores whoever it can and records the reason for the rest in `predict_ineligible`; "fail" refuses the whole node if ANY patient is out of domain. Use "fail" when the protocol requires the full cohort to be scored.|
|allow_unknown_grade_er_neg|bool|선택|False|Score ER-negative patients whose grade is unknown, reproducing the v2.1 behaviour of treating them as grade 1. Default false. Only set it deliberately, and say so in the write-up.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 모델 개발 대상과 입력 코딩/단위에 부합하는 환자. year 범위와 임상변수 코딩은 제공 param 표 및 원 모델 구현 확인. 신규 코호트 보정·검증은 별도.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predict_os_<year>y|number|% surviving at <year> years with SURGERY ALONE — the untreated baseline, NOT the survival of a patient on therapy. It does not change when the therapy flags change. NULL when out of domain|
|predict_horm_benefit_<year>y|number|percentage points added by hormone therapy; 0 unless horm=1 and ER+|
|predict_chemo_benefit_<year>y|number|percentage points added by chemotherapy ON TOP of hormone; 0 unless generation=2/3|
|predict_traz_benefit_<year>y|number|percentage points added by trastuzumab ON TOP of hormone+chemo; 0 unless traz=1 and HER2+|
|predict_bis_benefit_<year>y|number|percentage points added by bisphosphonate ON TOP of the other three; 0 unless bis=1|
|predict_ineligible|string|why the patient could not be scored; empty when scored|

**Side output:** 주 output edge와 별도이며 후속 노드에서 환자 코호트처럼 연결할 수 없다. Distribution of each predicted column (mean / sd / median / IQR / range) with the cohort flow (n_rows → n_scored → n_ineligible), the per-reason exclusion counts, and every variable that was pinned to a FIXED value rather than read from a column.

|Side Column|의미|
|---|---|

**기존 Output 계약 메모:** TWO things a reader gets wrong unless the write-up says them. (1) The survival column is the SURGERY-ALONE baseline; predicted survival UNDER treatment is that column PLUS the benefits, so never present it as 'predicted survival' for a treated cohort. (2) The four benefits are INCREMENTAL, in the order hormone → chemo → trastuzumab → bisphosphonate: each is the gain from ADDING that therapy to the ones before it, so they sum to the total gain over surgery alone and none is a standalone effect. A benefit is ZERO whenever its therapy flag is 0 — bind a flag to a constant 1 to ask 'what would this therapy add', and to the observed column to describe what the cohort actually gained. Rows with a non-empty `predict_ineligible` have NULL predictions — filter on it (or on the survival column being NOT NULL) before summarising, and report how many were dropped.

**Output 검토 / 가정 위반 시 주의:** 원본 환자+생존/치료 이득/부적격 사유 구조는 좋다. 이득은 정해진 순서의 증분이며 각각 독립 치료 효과가 아니다. v3와 혼동 금지. 참조하는 predict_breast 모듈이 이 저장소에 없어 실제 수식과 동작은 검증 불가.

**Processing Type:** 학습 없음(기학습 고정계수) / 환자별 일괄 추론 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-logisticregression"></a>

## 25. `LogisticRegression`

**Description / 목적:** 벌점 로지스틱 회귀의 예측확률를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9234](../tool_sample/tool_sample.py#L9234) · `LogisticRegression`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column and pure identifiers. Never empty.|
|penalty|string|선택|'l2'|"l2" (default) \| "l1" \| "elasticnet" \| "none".|
|C|number|선택|1.0|Inverse regularization strength. Default 1.0.|
|solver|string|선택|''|Default lbfgs (l2/none) or saga (elasticnet/l1).|
|l1_ratio|number|선택|None|Elastic-net mix; only when penalty=elasticnet.|
|max_iter|integer|선택|2000|Solver iterations. Default 2000.|
|class_weight|string|선택|None|"balanced" to reweight classes; omit for none.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, the model is fit on train and EVERY row is scored. Do not also restrict `where` to one arm.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical predictors.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 수치 척도와 선형/커널 구조를 점검한다. 결정점수는 확률이 아니며 보정 없이 calibration/DCA에 넣지 않는다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 단일 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-logisticregressioncv"></a>

## 26. `LogisticRegressionCV`

**Description / 목적:** 내부 CV로 벌점 강도를 고르는 로지스틱 예측확률를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9262](../tool_sample/tool_sample.py#L9262) · `LogisticRegressionCV`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column and pure identifiers. Never empty.|
|penalty|string|선택|'l2'|"l2" (default) \| "l1" \| "elasticnet".|
|solver|string|선택|''|Default lbfgs (l2) or saga (elasticnet).|
|l1_ratio|number|선택|None|Elastic-net mix; only when penalty=elasticnet.|
|cv|integer|선택|5|Folds for C / λ selection. Default 5.|
|max_iter|integer|선택|2000|Solver iterations. Default 2000.|
|class_weight|string|선택|None|"balanced" to reweight classes; omit for none.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, the model is fit on train and EVERY row is scored. Do not also restrict `where` to one arm.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical predictors.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 수치 척도와 선형/커널 구조를 점검한다. 결정점수는 확률이 아니며 보정 없이 calibration/DCA에 넣지 않는다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 내부 CV 후 최종 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-passiveaggressiveclassifier"></a>

## 27. `PassiveAggressiveClassifier`

**Description / 목적:** 수동-공격적 갱신 선형 분류의 결정점수를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9290](../tool_sample/tool_sample.py#L9290) · `PassiveAggressiveClassifier`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns. Never empty.|
|C|number|선택|1.0|Maximum step size (regularization). Default 1.0.|
|max_iter|integer|선택|2000|Epochs. Default 2000.|
|split_column|column|선택|''|Fit on train, score every row.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category}.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 수치 척도와 선형/커널 구조를 점검한다. 결정점수는 확률이 아니며 보정 없이 calibration/DCA에 넣지 않는다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 단일 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-perceptron"></a>

## 28. `Perceptron`

**Description / 목적:** 퍼셉트론 선형 분류의 결정점수를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9313](../tool_sample/tool_sample.py#L9313) · `Perceptron`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column and pure identifiers. Never empty.|
|penalty|string|선택|''|Optional L2/L1/elasticnet penalty on the weights.|
|alpha|number|선택|0.0001|Penalty multiplier. Default 0.0001.|
|max_iter|integer|선택|2000|Epochs. Default 2000.|
|class_weight|string|선택|None|"balanced" to reweight classes; omit for none.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, the model is fit on train and EVERY row is scored. Do not also restrict `where` to one arm.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical predictors.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 수치 척도와 선형/커널 구조를 점검한다. 결정점수는 확률이 아니며 보정 없이 calibration/DCA에 넣지 않는다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 단일 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-ridgeclassifier"></a>

## 29. `RidgeClassifier`

**Description / 목적:** L2 최소제곱 분류의 결정점수를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9339](../tool_sample/tool_sample.py#L9339) · `RidgeClassifier`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column and pure identifiers. Never empty.|
|alpha|number|선택|1.0|L2 strength. Default 1.0.|
|class_weight|string|선택|None|"balanced" to reweight classes; omit for none.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, the model is fit on train and EVERY row is scored. Do not also restrict `where` to one arm.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical predictors.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 수치 척도와 선형/커널 구조를 점검한다. 결정점수는 확률이 아니며 보정 없이 calibration/DCA에 넣지 않는다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 단일 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-ridgeclassifiercv"></a>

## 30. `RidgeClassifierCV`

**Description / 목적:** 내부 CV로 L2 강도를 고르는 분류 결정점수를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9362](../tool_sample/tool_sample.py#L9362) · `RidgeClassifierCV`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column and pure identifiers. Never empty.|
|alphas|list[number]|선택|None|α grid. Default [0.1, 1, 10].|
|cv|integer|선택|None|CV folds for α; omit for GCV-style default.|
|class_weight|string|선택|None|"balanced" to reweight classes; omit for none.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, the model is fit on train and EVERY row is scored. Do not also restrict `where` to one arm.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical predictors.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 수치 척도와 선형/커널 구조를 점검한다. 결정점수는 확률이 아니며 보정 없이 calibration/DCA에 넣지 않는다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 내부 CV 후 최종 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-sgdclassifier"></a>

## 31. `SGDClassifier`

**Description / 목적:** 확률적 경사하강 선형 분류의 점수(loss에 따라 확률)를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9387](../tool_sample/tool_sample.py#L9387) · `SGDClassifier`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column and pure identifiers. Never empty.|
|loss|string|선택|'hinge'|"hinge" (default, linear SVM) \| "log_loss" (logistic, has predict_proba) \| "modified_huber" \| "squared_hinge" \| "perceptron".|
|penalty|string|선택|'l2'|"l2" (default) \| "l1" \| "elasticnet".|
|alpha|number|선택|0.0001|Regularization multiplier. Default 0.0001.|
|l1_ratio|number|선택|0.15|Elastic-net mix. Default 0.15.|
|max_iter|integer|선택|2000|Epochs. Default 2000.|
|learning_rate|string|선택|'optimal'|"optimal" (default) \| "constant" \| "invscaling" \| "adaptive".|
|eta0|number|선택|0.0|Initial learning rate when not optimal. Default 0.|
|class_weight|string|선택|None|"balanced" to reweight classes; omit for none.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, the model is fit on train and EVERY row is scored. Do not also restrict `where` to one arm.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical predictors.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 수치 척도와 선형/커널 구조를 점검한다. 결정점수는 확률이 아니며 보정 없이 calibration/DCA에 넣지 않는다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 단일 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-sgdoneclasssvm"></a>

## 32. `SGDOneClassSVM`

**Description / 목적:** 정상 영역을 학습하는 비지도 이상탐지 점수를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9422](../tool_sample/tool_sample.py#L9422) · `SGDOneClassSVM`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|predictors|list[column]|필수|— (인수 필수)|Feature columns. Never empty. No outcome.|
|nu|number|선택|0.5|Approximate outlier fraction in (0, 1]. Default 0.5.|
|max_iter|integer|선택|2000|Epochs. Default 2000.|
|split_column|column|선택|''|When set, fit on train rows only, score everyone.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category}.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 정상 학습 표본의 대표성과 독립성. 종속변수는 불필요하다. 수치 척도와 선형/커널 구조를 점검한다. 결정점수는 확률이 아니며 보정 없이 calibration/DCA에 넣지 않는다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. predicted_class의 +1/-1은 정상/이상이며 질병 양성/음성이 아니다.

**Processing Type:** 모델 학습 필요 / 단일 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-svc"></a>

## 33. `SVC`

**Description / 목적:** 커널 최대마진 분류 및 확률 추정를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9446](../tool_sample/tool_sample.py#L9446) · `SVC`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column and pure identifiers. Never empty.|
|C|number|선택|1.0|Inverse regularization. Default 1.0.|
|kernel|string|선택|'rbf'|"rbf" (default) \| "linear" \| "poly" \| "sigmoid".|
|gamma|string|선택|'scale'|Kernel coefficient: "scale" (default) \| "auto" \| a float.|
|class_weight|string|선택|None|"balanced" to reweight classes; omit for none.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, the model is fit on train and EVERY row is scored. Do not also restrict `where` to one arm.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical predictors.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 수치 척도와 선형/커널 구조를 점검한다. 결정점수는 확률이 아니며 보정 없이 calibration/DCA에 넣지 않는다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 단일 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-linearsvc"></a>

## 34. `LinearSVC`

**Description / 목적:** 선형 최대마진 분류 결정점수를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9475](../tool_sample/tool_sample.py#L9475) · `LinearSVC`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column and pure identifiers. Never empty.|
|C|number|선택|1.0|Inverse regularization. Default 1.0.|
|max_iter|integer|선택|2000|Solver iterations. Default 2000.|
|class_weight|string|선택|None|"balanced" to reweight classes; omit for none.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, the model is fit on train and EVERY row is scored. Do not also restrict `where` to one arm.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical predictors.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 수치 척도와 선형/커널 구조를 점검한다. 결정점수는 확률이 아니며 보정 없이 calibration/DCA에 넣지 않는다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 단일 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-nusvc"></a>

## 35. `NuSVC`

**Description / 목적:** nu 제약 커널 분류 및 확률 추정를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9500](../tool_sample/tool_sample.py#L9500) · `NuSVC`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column and pure identifiers. Never empty.|
|nu|number|선택|0.5|ν in (0, 1] — upper bound on training error. Default 0.5.|
|kernel|string|선택|'rbf'|"rbf" (default) \| "linear" \| "poly" \| "sigmoid".|
|gamma|string|선택|'scale'|Kernel coefficient: "scale" (default) \| "auto" \| a float.|
|class_weight|string|선택|None|"balanced" to reweight classes; omit for none.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, the model is fit on train and EVERY row is scored. Do not also restrict `where` to one arm.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical predictors.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 수치 척도와 선형/커널 구조를 점검한다. 결정점수는 확률이 아니며 보정 없이 calibration/DCA에 넣지 않는다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 단일 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-decisiontreeclassifier"></a>

## 36. `DecisionTreeClassifier`

**Description / 목적:** 단일 결정트리의 분류 확률를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9526](../tool_sample/tool_sample.py#L9526) · `DecisionTreeClassifier`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column and pure identifiers. Never empty.|
|max_depth|integer|선택|None|Max tree depth. Omit to grow until pure leaves.|
|min_samples_split|integer|선택|2|Min samples to split. Default 2.|
|min_samples_leaf|integer|선택|1|Min samples in a leaf. Default 1.|
|class_weight|string|선택|None|"balanced" to reweight classes; omit for none.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, the model is fit on train and EVERY row is scored. Do not also restrict `where` to one arm.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical predictors.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 트리는 비선형·상호작용을 허용하지만 과적합과 변수 중요도의 고유값 수 편향을 점검한다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 단일 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-extratreeclassifier"></a>

## 37. `ExtraTreeClassifier`

**Description / 목적:** 무작위 분할 단일 트리의 분류 확률를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9553](../tool_sample/tool_sample.py#L9553) · `ExtraTreeClassifier`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column and pure identifiers. Never empty.|
|max_depth|integer|선택|None|Max tree depth. Omit to grow until pure leaves.|
|min_samples_split|integer|선택|2|Min samples to split. Default 2.|
|min_samples_leaf|integer|선택|1|Min samples in a leaf. Default 1.|
|class_weight|string|선택|None|"balanced" to reweight classes; omit for none.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, the model is fit on train and EVERY row is scored. Do not also restrict `where` to one arm.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical predictors.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 트리는 비선형·상호작용을 허용하지만 과적합과 변수 중요도의 고유값 수 편향을 점검한다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 단일 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-randomforestclassifier"></a>

## 38. `RandomForestClassifier`

**Description / 목적:** bootstrap 랜덤 포레스트 분류 확률를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9580](../tool_sample/tool_sample.py#L9580) · `RandomForestClassifier`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column and pure identifiers. Never empty.|
|n_estimators|integer|선택|200|Number of trees. Default 200.|
|max_depth|integer|선택|None|Max tree depth. Omit for fully grown trees.|
|min_samples_split|integer|선택|2|Min samples to split. Default 2.|
|min_samples_leaf|integer|선택|1|Min samples in a leaf. Default 1.|
|class_weight|string|선택|None|"balanced" to reweight classes; omit for none.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, the model is fit on train and EVERY row is scored. Do not also restrict `where` to one arm.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical predictors.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 트리는 비선형·상호작용을 허용하지만 과적합과 변수 중요도의 고유값 수 편향을 점검한다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 단일 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-extratreesclassifier"></a>

## 39. `ExtraTreesClassifier`

**Description / 목적:** 다수의 무작위 분할 트리 분류 확률를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9608](../tool_sample/tool_sample.py#L9608) · `ExtraTreesClassifier`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column and pure identifiers. Never empty.|
|n_estimators|integer|선택|200|Number of trees. Default 200.|
|max_depth|integer|선택|None|Max tree depth. Omit for fully grown trees.|
|min_samples_split|integer|선택|2|Min samples to split. Default 2.|
|min_samples_leaf|integer|선택|1|Min samples in a leaf. Default 1.|
|class_weight|string|선택|None|"balanced" to reweight classes; omit for none.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, the model is fit on train and EVERY row is scored. Do not also restrict `where` to one arm.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical predictors.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 트리는 비선형·상호작용을 허용하지만 과적합과 변수 중요도의 고유값 수 편향을 점검한다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 단일 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-adaboostclassifier"></a>

## 40. `AdaBoostClassifier`

**Description / 목적:** 오분류 관측을 강조하는 부스팅 분류 확률를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9636](../tool_sample/tool_sample.py#L9636) · `AdaBoostClassifier`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns. Never empty.|
|n_estimators|integer|선택|50|Boosting rounds. Default 50.|
|learning_rate|number|선택|1.0|Shrinkage. Default 1.0.|
|split_column|column|선택|''|Fit on train, score every row.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category}.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 깊이·학습률·반복 수에 따른 과적합과 이상치 민감도를 점검한다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 단일 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-gradientboostingclassifier"></a>

## 41. `GradientBoostingClassifier`

**Description / 목적:** 순차 손실 개선 트리 부스팅 분류 확률를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9660](../tool_sample/tool_sample.py#L9660) · `GradientBoostingClassifier`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns. Never empty.|
|n_estimators|integer|선택|200|Boosting rounds. Default 200.|
|learning_rate|number|선택|0.1|Shrinkage. Default 0.1.|
|max_depth|integer|선택|3|Max tree depth. Default 3.|
|min_samples_split|integer|선택|2|Min samples to split. Default 2.|
|min_samples_leaf|integer|선택|1|Min samples in a leaf. Default 1.|
|split_column|column|선택|''|Fit on train, score every row.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category}.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 깊이·학습률·반복 수에 따른 과적합과 이상치 민감도를 점검한다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 단일 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-histgradientboostingclassifier"></a>

## 42. `HistGradientBoostingClassifier`

**Description / 목적:** 히스토그램 기반 트리 부스팅 분류 확률를 산출하여 입력 환자 코호트에 붙인다.

**구현 근거:** [tool_sample.py:9689](../tool_sample/tool_sample.py#L9689) · `HistGradientBoostingClassifier`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome to predict.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass just the positive label, verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column and pure identifiers. Never empty.|
|max_iter|integer|선택|200|Boosting rounds. Default 200.|
|learning_rate|number|선택|0.1|Shrinkage. Default 0.1.|
|max_depth|integer|선택|None|Max tree depth. Omit for no limit.|
|class_weight|string|선택|None|"balanced" to reweight classes; omit for none.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, the model is fit on train and EVERY row is scored. Do not also restrict `where` to one arm.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical predictors.|
|random_state|integer|선택|42|Seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다. 깊이·학습률·반복 수에 따른 과적합과 이상치 민감도를 점검한다.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|predicted_probability|number|P(y=1) when the estimator has predict_proba|
|predicted_score|number|decision_function when there is no predict_proba|
|predicted_class|integer|0/1 predicted label|

**기존 Output 계약 메모:** FIT once. OUTPUT is the input cohort plus score columns — `predicted_probability` when the estimator has predict_proba, otherwise `predicted_score` (decision_function), plus `predicted_class`. Incomplete rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) must read these columns; they must NOT refit. Distinct from statistics.logistic_regression (statsmodels odds-ratio table).

**Output 검토 / 가정 위반 시 주의:** 주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다. split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다.

**Processing Type:** 모델 학습 필요 / 단일 적합 / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-ml_train_test_split"></a>

## 43. `ml_train_test_split`

**Description / 목적:** 코호트에 train/test 표식을 추가하여 학습과 평가를 분리한다.

**구현 근거:** [tool_sample.py:8747](../tool_sample/tool_sample.py#L8747) · `ml_train_test_split`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|test_size|number|선택|0.3|Fraction of rows in the TEST set, in (0, 1). Default 0.3.|
|stratify_column|column|선택|''|Column to stratify the split on — usually the outcome, so train and test keep the same class mix. Optional; omit for a simple random split.|
|split_column|string|선택|'split'|Name of the added label column. Default "split" with values "train" and "test".|
|random_state|integer|선택|42|Split seed. Default 42.|
|where|string|선택|''|SQL boolean cohort filter before splitting. Optional.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 환자 행 전제. 반복측정·다기관·시간 예측에서는 환자/기관/시간 기준 분할 필요. 층화 클래스 최소 표본 수 확인.

**Output:** `dataset` · 계약 형식 `parquet` · 행 단위 `row_subset`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|split|string|train \| test (or params.split_column)|

**Output 검토 / 가정 위반 시 주의:** split 표식 보존은 적절하다. 모델에 split_column을 전달하지 않으면 전체 자료를 학습할 수 있다. 분할만으로 전처리 누수가 해결되지 않는다.

**Processing Type:** 학습 없음 / 1회 분할 / 배치 불필요. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-ml_classifier_performance"></a>

## 44. `ml_classifier_performance`

**Description / 목적:** 이미 저장한 예측확률 또는 점수로 분류 성능 및 bootstrap CI를 계산한다.

**구현 근거:** [tool_sample.py:9715](../tool_sample/tool_sample.py#L9715) · `ml_classifier_performance`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1), verbatim. For a 0/1 flag pass [1]; for a labeled column pass just the positive label.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|n_bootstrap|integer|선택|500|Bootstrap reps of the existing (y, p) pairs. Default 500. Does not refit.|
|threshold|number|선택|None|Probability cut for sens/spec/PPV/NPV. Omit to use the Youden-optimal cut.|
|probability_column|column|선택|'predicted_probability'|Predicted-probability column written by the upstream model node. Default "predicted_probability". Does not fit.|
|score_column|str|선택|'predicted_score'|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, only split_value rows are read (default test). Do not also restrict `where` to one arm.|
|split_value|string|선택|'test'|Which split arm to read. Default "test".|
|random_state|int|선택|42|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 검증 데이터와 두 결과군. 확률은 0~1이며 점수는 확률과 구별. train/test 지정과 양성 라벨 일치 필요.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_metric`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|metric|string|auc / auc_test, brier, pr_auc, sensitivity, specificity, ppv, npv, calibration_slope, calibration_intercept, threshold, n, n_events, bootstrap_reps|
|value|number|지표 값|
|ci_lower|number|CI 하한|
|ci_upper|number|CI 상한|

**Output 검토 / 가정 위반 시 주의:** metric/value/CI long table은 재사용에 적합하다. 평가셋에서 Youden 임계값을 선택하면 임계값 성능은 낙관적이다. bootstrap은 기존 예측쌍 재표집으로 학습 불확실성/낙관편향을 교정하지 않는다.

**Processing Type:** 재학습 없음 / bootstrap 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-ml_roc_curve"></a>

## 45. `ml_roc_curve`

**Description / 목적:** 기존 예측 점수의 임계값별 TPR/FPR과 ROC를 생성한다.

**구현 근거:** [tool_sample.py:9855](../tool_sample/tool_sample.py#L9855) · `ml_roc_curve`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1), verbatim. For a 0/1 flag pass [1]; for a labeled column pass just the positive label.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|probability_column|column|선택|'predicted_probability'|Predicted-probability column written by the upstream model node. Default "predicted_probability". Does not fit.|
|score_column|str|선택|'predicted_score'|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, only split_value rows are read (default test). Do not also restrict `where` to one arm.|
|split_value|string|선택|'test'|Which split arm to read. Default "test".|
|title|string|선택|''|Figure title. Optional.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 평가자료의 두 결과군. 확률뿐 아니라 연속 결정점수도 가능. 양성 방향을 확인한다.

**Output:** `figure` · 계약 형식 `png+parquet` · 행 단위 `figure`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 Figure 계약의 빈 columns를 실제 생성 코드 기준으로 보완했다. 그림의 데이터 테이블은 다음과 같다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|fpr|number\|string|위양성률|
|tpr|number\|string|민감도|
|threshold|number\|string|임계값; 무한값은 null|

**기존 Output 계약 메모:** Returns a PNG plus the tidy frame the chart was drawn from. Does not invent columns — it plots what its inputs already hold.

**Output 검토 / 가정 위반 시 주의:** FPR/TPR/threshold 표와 그림이 적절하다. AUC는 calibration이나 임상 효용이 아니다. 무한 초기 임계값은 null 처리되며 Youden 선택은 탐색적이다. 카탈로그 공통 Figure schema에 실제 열이 누락되어 있다.

**Processing Type:** 재학습 없음 / 임계값 순회 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-ml_calibration_curve"></a>

## 46. `ml_calibration_curve`

**Description / 목적:** 예측확률 분위수 구간별 평균 예측확률과 실제 발생률을 비교한다.

**구현 근거:** [tool_sample.py:9928](../tool_sample/tool_sample.py#L9928) · `ml_calibration_curve`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1), verbatim. For a 0/1 flag pass [1]; for a labeled column pass just the positive label.|
|n_bins|integer|선택|10|Quantile bins for the calibration groups. Default 10.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|probability_column|column|선택|'predicted_probability'|Predicted-probability column written by the upstream model node. Default "predicted_probability". Does not fit.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, only split_value rows are read (default test). Do not also restrict `where` to one arm.|
|split_value|string|선택|'test'|Which split arm to read. Default "test".|
|title|string|선택|''|Figure title. Optional.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 0~1 확률, 독립 평가자료, 각 bin 충분한 표본. 결정점수를 확률처럼 넣지 않는다.

**Output:** `figure` · 계약 형식 `png+parquet` · 행 단위 `figure`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 Figure 계약의 빈 columns를 실제 생성 코드 기준으로 보완했다. 그림의 데이터 테이블은 다음과 같다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|prob_pred|number\|string|bin 평균 예측확률|
|prob_true|number\|string|bin 실제 사건 비율|
|bin_count|number\|string|bin 표본 수; 동점 경계 불일치 가능|

**기존 Output 계약 메모:** Returns a PNG plus the tidy frame the chart was drawn from. Does not invent columns — it plots what its inputs already hold.

**Output 검토 / 가정 위반 시 주의:** prob_pred/prob_true/bin_count와 그림을 출력한다. 소개문의 slope/intercept/Brier는 이 함수가 계산하지 않는다. sklearn bin 할당과 별도 np.digitize의 경계처리가 달라 동점 확률에서 bin_count가 일치하지 않을 수 있다. bin별 CI도 없다.

**Processing Type:** 재학습 없음 / bin 집계 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-ml_decision_curve"></a>

## 47. `ml_decision_curve`

**Description / 목적:** 임계확률별 모델·전원처치·무처치의 순편익을 비교한다.

**구현 근거:** [tool_sample.py:10009](../tool_sample/tool_sample.py#L10009) · `ml_decision_curve`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Column holding the binary outcome.|
|outcome_values|list[value]|필수|— (인수 필수)|ONLY the value(s) counted as the POSITIVE class (=1), verbatim. For a 0/1 flag pass [1]; for a labeled column pass just the positive label.|
|thresholds|list[number]|선택|None|Threshold probabilities to evaluate (each in 0..1). Default 0.01…0.99 step 0.01.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|probability_column|column|선택|'predicted_probability'|Predicted-probability column written by the upstream model node. Default "predicted_probability". Does not fit.|
|split_column|column|선택|''|Train/test label from ml_train_test_split (usually "split"). When set, only split_value rows are read (default test). Do not also restrict `where` to one arm.|
|split_value|string|선택|'test'|Which split arm to read. Default "test".|
|title|string|선택|''|Figure title. Optional.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 0<임계확률<1, 적절히 보정된 확률, 목표 모집단 유병률, 처치 손익을 임계값으로 표현할 수 있다는 전제.

**Output:** `figure` · 계약 형식 `png+parquet` · 행 단위 `figure`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 Figure 계약의 빈 columns를 실제 생성 코드 기준으로 보완했다. 그림의 데이터 테이블은 다음과 같다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|threshold|number\|string|임계확률|
|net_benefit_model|number\|string|모델 순편익|
|net_benefit_all|number\|string|모두 처치 순편익|
|net_benefit_none|number\|string|무처치 순편익=0|

**기존 Output 계약 메모:** Returns a PNG plus the tidy frame the chart was drawn from. Does not invent columns — it plots what its inputs already hold.

**Output 검토 / 가정 위반 시 주의:** 세 순편익을 함께 보여 비교 가능하다. 순편익은 정확도가 아니며 희귀사건·작은 평가집단에서 불안정하다. CI와 임상적으로 타당한 임계 범위를 추가 권장.

**Processing Type:** 재학습 없음 / 임계값 grid 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-ml_reclassification"></a>

## 48. `ml_reclassification`

**Description / 목적:** 동일 환자 두 모델의 예측확률로 IDI 및 연속/임계값 NRI를 비교한다.

**구현 근거:** [tool_sample.py:10101](../tool_sample/tool_sample.py#L10101) · `ml_reclassification`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Binary outcome column.|
|outcome_values|list[value]|필수|— (인수 필수)|Positive-class value(s), verbatim.|
|probability_column|column|선택|'predicted_probability'|FULL model's predicted-probability column. Default "predicted_probability".|
|baseline_probability_column|column|선택|''|REDUCED model's probability column on the SAME table. Required unless baseline_source is set.|
|baseline_source|string|선택|''|Second scored dataset (another model node). Joined to `source` on id_column. Both columns may be named predicted_probability.|
|id_column|column|선택|''|Join key when baseline_source is set. Required in that case.|
|nri_thresholds|list[number]|선택|None|Probability cuts for category-based NRI (each in 0..1). Optional; continuous NRI is always reported.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|split_column|column|선택|''|If set, read only split_value rows (default test).|
|split_value|string|선택|'test'|Which split arm to read. Default "test".|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 같은 환자·결과·예측 시점. 별도 source를 결합할 때 id_column의 유일성 및 1:1 조인 확인.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_metric`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|metric|string|auc_full, auc_reduced, idi, nri_continuous, nri_events, nri_nonevents, plus categorical NRI when nri_thresholds set|
|value|number|지표 값|

**Output 검토 / 가정 위반 시 주의:** metric/value는 간단하나 CI가 없어 불확실성을 판단하기 어렵다. NRI는 calibration이나 임상효용을 대체하지 않는다. 여러 임계값은 각 cut의 결과이며 자동 다범주 NRI로 읽으면 안 된다.

**Processing Type:** 재학습 없음 / 모델 예측쌍 비교 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-ml_cv_performance"></a>

## 49. `ml_cv_performance`

**Description / 목적:** 한 알고리즘을 층화 교차검증에서 재학습하고 OOF 성능을 산출한다.

**구현 근거:** [tool_sample.py:14192](../tool_sample/tool_sample.py#L14192) · `ml_cv_performance`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Binary outcome column.|
|outcome_values|list[value]|필수|— (인수 필수)|Positive-class value(s), verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns. Never empty.|
|model|string|선택|'elasticnet_logistic'|EXACT catalog key for a learning-procedure node that REFITS each fold. Prefer a sklearn class-name tool: "LogisticRegression", "LogisticRegressionCV", "RandomForestClassifier", "GradientBoostingClassifier", "SVC", … Legacy aliases also work: "elasticnet_logistic" \| "logistic" \| "random_forest" \| "gradient_boosting". NEVER write "xgboost" / "rf". Do NOT pass this to ROC / calibration / DCA / performance — those read predicted_probability and never fit.|
|n_splits|integer|선택|5|Stratified CV folds. Default 5.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{categorical predictor: baseline level}. Optional.|
|l1_ratio|float|선택|0.5|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|cv_folds|int|선택|10|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|n_estimators|int|선택|500|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|max_depth|int|선택|3|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|learning_rate|float|선택|0.1|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|class_weight|Any|선택|None|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|random_state|int|선택|42|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 각 fold 두 결과군과 충분한 표본, 환자 단위 독립성. 전처리·튜닝은 각 training fold 안에서 해야 한다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|model|string|모델 키|
|model_name|string|모델 표시명|
|n|integer|분석/검사 분모; 도구별 관측 단위 확인|
|n_events|integer|사건/양성 수|
|folds|integer|CV fold 수|
|auc|number|ROC AUC|
|brier|number|확률 제곱오차 평균|
|calibration_slope|number|보정 기울기(이상적 1)|
|calibration_intercept|number|보정 절편(이상적 0)|
|citl|number|calibration-in-the-large|

**Output 검토 / 가정 위반 시 주의:** OOF AUC/Brier/calibration을 제공한다. 최종 배포 모델 파일은 아니다. 전체 데이터의 설계행렬을 미리 만들고, OOF에서 임계값을 선택하는 부분을 점검해야 한다. CI·fold별 분산과 외부 검증이 필요하다.

**Processing Type:** fold별 모델 학습 / CV 반복 필수 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-ml_compare"></a>

## 50. `ml_compare`

**Description / 목적:** 동일 fold로 여러 알고리즘을 교차검증하고 OOF AUC 순위를 비교한다.

**구현 근거:** [tool_sample.py:14264](../tool_sample/tool_sample.py#L14264) · `ml_compare`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|Binary outcome column.|
|outcome_values|list[value]|필수|— (인수 필수)|Positive-class value(s), verbatim.|
|predictors|list[column]|필수|— (인수 필수)|Predictor columns, shared by every model. Never empty.|
|models|list[value]|필수|None|Two or more catalog keys — sklearn class names (LogisticRegression, RandomForestClassifier, …) or legacy aliases (elasticnet_logistic, logistic, random_forest, gradient_boosting). Defaults to LogisticRegressionCV + RandomForestClassifier + GradientBoostingClassifier.|
|n_splits|integer|선택|5|Stratified CV folds, shared by every model. Default 5.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|reference_levels|object|선택|None|{categorical predictor: baseline level}. Optional.|
|l1_ratio|float|선택|0.5|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|cv_folds|int|선택|10|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|n_estimators|int|선택|500|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|max_depth|int|선택|3|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|learning_rate|float|선택|0.1|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|class_weight|Any|선택|None|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|random_state|int|선택|42|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 같은 표본·fold·평가 정의. 모델 선택에 사용한 CV 점수를 최종 일반화 성능으로 보지 않는다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_model`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|rank|integer|1 = best AUC|
|model|string|모델 키|
|model_name|string|모델 표시명|
|n|integer|분석/검사 분모; 도구별 관측 단위 확인|
|n_events|integer|사건/양성 수|
|folds|integer|CV fold 수|
|auc|number|ROC AUC|
|brier|number|확률 제곱오차 평균|
|calibration_slope|number|보정 기울기(이상적 1)|
|calibration_intercept|number|보정 절편(이상적 0)|
|citl|number|calibration-in-the-large|

**Output 검토 / 가정 위반 시 주의:** rank는 해당 표본의 추정 순위로 유의한 성능 차이를 뜻하지 않는다. 차이의 CI와 nested CV/독립 test가 필요하다. 모델별 적합 실패도 명시적으로 보고해야 한다.

**Processing Type:** 모델×fold별 학습 / 중첩 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-kaplan_meier"></a>

## 51. `kaplan_meier`

**Description / 목적:** 우측 검열 생존자료의 군별 Kaplan–Meier 생존곡선과 life table을 계산한다.

**구현 근거:** [tool_sample.py:5508](../tool_sample/tool_sample.py#L5508) · `kaplan_meier`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|time_column|column|필수|— (인수 필수)|Follow-up time (numeric, e.g. survival months).|
|event_column|column|필수|— (인수 필수)|Column recording the outcome status.|
|event_values|list[value]|필수|— (인수 필수)|Value(s) of event_column that count as an EVENT/death (=1), copied verbatim, e.g. ["Dead"]; everything else is censored. Do NOT list censoring values here.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|group_by|list[column]|선택|None|Fit one curve per combination of these columns. Optional.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 관측·비정보적 검열·일관된 time origin과 단위, 음수 시간 없음. 사건 코드 이외의 값이 검열로 처리되므로 누락/미상 코드 사전 정리.

**Output:** `figure` · 계약 형식 `png+parquet` · 행 단위 `figure`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 Figure 계약의 빈 columns를 실제 생성 코드 기준으로 보완했다. 그림의 데이터 테이블은 다음과 같다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|group|number\|string|군(그룹 지정 시)|
|time_months|number\|string|입력 단위의 시간; 월로 변환하지 않음|
|n_at_risk|number\|string|직전 위험집단 수|
|n_events|number\|string|해당 시점 사건 수|
|survival_probability|number\|string|생존확률|
|ci_lower|number\|string|95% CI 하한|
|ci_upper|number\|string|95% CI 상한|

**기존 Output 계약 메모:** Returns a PNG plus the tidy frame the chart was drawn from. Does not invent columns — it plots what its inputs already hold.

**Output 검토 / 가정 위반 시 주의:** 생존확률/CI/위험집단/사건수는 적절하다. time_months라는 이름을 쓰지만 단위 변환은 하지 않는다. censor 수·median 및 추적기간 요약 추가 권장. 경쟁사건의 누적발생률을 1-KM으로 구하면 과대평가 가능.

**Processing Type:** 생존분포 추정(예측모델 학습 없음) / 군별 적합 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-competing_risk_cif"></a>

## 52. `competing_risk_cif`

**Description / 목적:** Aalen–Johansen으로 관심 사건 및 경쟁사건의 누적발생률을 추정한다.

**구현 근거:** [tool_sample.py:5639](../tool_sample/tool_sample.py#L5639) · `competing_risk_cif`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|duration_column|column|필수|— (인수 필수)|Follow-up time (numeric, e.g. survival months).|
|event_column|column|필수|— (인수 필수)|Column recording the CAUSE/outcome status, e.g. a cause-specific death classification.|
|event_values|list[value]|필수|— (인수 필수)|Value(s) marking the EVENT OF INTEREST (cause 1), verbatim — e.g. death from the cancer under study.|
|competing_values|list[value]|필수|— (인수 필수)|Value(s) marking the COMPETING event (cause 2), verbatim — e.g. death from another cause. Required: with no competing event this reduces to 1-KM, so use kaplan_meier.|
|group_column|column|선택|''|Estimate one CIF per level of this column (e.g. treatment arm).|
|group_values|list[value]|선택|None|Restrict to these group_column levels (verbatim).|
|cif_time_points|list[number]|선택|None|Horizons at which to report the CIF, in the duration column's OWN unit — e.g. [60] for 5-year cumulative incidence. With exactly two groups the absolute risk difference between them is reported as well.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|weights_column|column|선택|''|Weight column for an ADJUSTED CIF — the 'iptw' column from iptw_weight, with that weighted cohort as this node's input.|
|both_causes|bool|선택|True|Also estimate/plot the competing event's CIF (default true), as competing-risk figures normally show both.|
|title|string|선택|''|Figure title. Optional.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 상호 배타적인 사건/경쟁사건 코드, 독립 검열, 정확한 시간과 원인 분류. 사건 집합이 겹치면 안 된다.

**Output:** `figure` · 계약 형식 `png+parquet` · 행 단위 `figure`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 Figure 계약의 빈 columns를 실제 생성 코드 기준으로 보완했다. 그림의 데이터 테이블은 다음과 같다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|group|number\|string|군|
|cause|number\|string|사건 종류|
|time|number\|string|입력 단위 시간|
|cif|number\|string|누적발생률|
|cif_lower95|number\|string|CI 하한|
|cif_upper95|number\|string|CI 상한|

**기존 Output 계약 메모:** Returns a PNG plus the tidy frame the chart was drawn from. Does not invent columns — it plots what its inputs already hold.

**Output 검토 / 가정 위반 시 주의:** group/cause/time/CIF/CI 구조는 적절하다. 관심 사건이 0인 군을 skip하여 실제 0위험 곡선이 표에서 사라질 수 있다. 관찰 최대시간 밖의 ffill은 근거 없는 외삽처럼 보일 수 있다. 추적 지지구간을 표시해야 한다.

**Processing Type:** 생존분포 추정 / 군×원인 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-logrank_test"></a>

## 53. `logrank_test`

**Description / 목적:** 두 군의 생존함수 차이를 log-rank 통계량으로 검정한다.

**구현 근거:** [tool_sample.py:10618](../tool_sample/tool_sample.py#L10618) · `logrank_test`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|time_column|column|필수|— (인수 필수)|Follow-up time (numeric).|
|event_column|column|필수|— (인수 필수)|Column recording the outcome status.|
|event_values|list[value]|필수|— (인수 필수)|Value(s) of event_column that count as an EVENT (=1), verbatim; the rest are censored.|
|group_column|column|필수|— (인수 필수)|Column defining the two arms whose survival is compared.|
|group_values|list[value]|선택|None|The TWO arm labels to compare (verbatim), required when group_column has >2 labels.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|t_0|float|선택|-1|카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인.|
|weightings|string|선택|''|"wilcoxon" \| "tarone-ware" \| "peto" (default: unweighted log-rank).|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 표본·비정보적 검열·동일 시간원점. PH일 때 검정력이 좋으며 곡선 교차 시 검정력이 떨어질 수 있다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|time_column|string|추적시간 열|
|event_column|string|사건코드 열|
|group_column|string|군 구분 열|
|group_a|string|첫 비교군|
|n_a|integer|첫 군 표본 수|
|events_a|integer|첫 군 사건 수|
|group_b|string|둘째 비교군|
|n_b|integer|둘째 군 표본 수|
|events_b|integer|둘째 군 사건 수|
|test_statistic|number|검정통계량|
|dof|integer|검정 자유도|
|p_value|number|귀무가설하 p값|
|t_0|number|검정 추적 제한시간|
|weightings|string|log-rank 가중 방식|

**Output 검토 / 가정 위반 시 주의:** 군별 n/사건수/통계량/p가 있어 검정에는 적절하다. 효과크기나 생존율 차이 CI가 없으므로 KM/RMST와 함께 보고한다. 비유의는 동등성을 증명하지 않는다.

**Processing Type:** 예측모델 학습 없음 / 단일 검정 / 배치 불필요. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-cox_ph"></a>

## 54. `cox_ph`

**Description / 목적:** 전체 공변량을 동시에 포함한 Cox 비례위험 모형의 HR 및 상호작용을 추정한다.

**구현 근거:** [tool_sample.py:7139](../tool_sample/tool_sample.py#L7139) · `cox_ph`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|duration_column|column|필수|— (인수 필수)|Follow-up time (numeric).|
|event_column|column|필수|— (인수 필수)|Column recording the outcome status.|
|event_values|list[value]|필수|— (인수 필수)|Value(s) of event_column that count as an EVENT (=1), verbatim; the rest are censored.|
|covariates|list[column]|필수|— (인수 필수)|Adjustment columns (categoricals auto one-hot). EXCLUDE duration/event columns and identifiers. Never empty.|
|where|string|선택|''|SQL boolean cohort filter. Do NOT add 'IS NOT NULL' guards for the covariates: the tool applies the complete-case restriction itself (rows missing ANY covariate are dropped BEFORE encoding, so a category that survives only in dropped rows never becomes a phantom level), and it drops covariate columns that end up constant or redundant in the resulting cohort, reporting both in its summary. Use `where` for the CLINICAL cohort definition only. If a covariate is too incompletely recorded to lose, impute it first with impute_missing instead of filtering on it.|
|strata|list[column]|선택|None|Columns to stratify the baseline hazard by. Optional.|
|weights_column|column|선택|''|Per-patient weight column for an IPTW-WEIGHTED Cox — set it to the 'iptw' column produced by iptw_weight and make that weighted cohort this node's input. Robust variance is enabled automatically, as non-integer weights otherwise understate the SEs.|
|robust|bool|선택|None|Robust (sandwich) standard errors. Defaults to true when weights_column is set.|
|cluster_column|column|선택|''|Column identifying correlated clusters (registry, hospital…) for clustered robust SEs.|
|interactions|list[string]|선택|None|Effect-modification terms, each naming TWO columns that are also in `covariates`, e.g. ["Radiation recode * Age recode"]. Write the EXPOSURE first and the effect MODIFIER second. Each term yields both `contrast` rows (the exposure's HR within every modifier level, computed from the full covariance matrix) and one `interaction_wald` row (the joint test over the whole block — the only valid p-value when a categorical interaction spans several dummy columns).|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical covariates, e.g. {"Race recode": "Black"}. Every hazard ratio is measured against this level, so whenever the request names a reference/baseline category you MUST set it here — otherwise the baseline is whichever level sorts first and the HRs answer a different question. Copy the level verbatim from the column's values; a level that does not occur is an error.|
|penalizer|number|선택|0.0|Ridge penalty (e.g. 0.1) that stabilizes a collinear/wide one-hot design which otherwise fails to converge. Default 0.|
|imputation_column|column|선택|''|Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default) — the tool detects `_imputation` on its own, runs the estimate INSIDE each draw and pools the m results by Rubin's rules, so every reported n counts PATIENTS. Name a column only when the index is spelled differently; pass "none" to analyse the stacked draws as one cohort, which counts every patient m times and is almost never what the protocol means.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 비례위험·조건부 비정보적 검열·연속변수의 log-hazard 선형성·충분한 사건·독립성(또는 적절한 cluster/robust 분산).

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_term`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|term_type|string|coefficient \| reference \| interaction_contrast \| global_wald|
|term|string|설계행렬 항/대비명|
|group|string|군 또는 상호작용 수준; 도구별 확인|
|coef|number|링크/log-hazard 척도 계수|
|se|number|계수 표준오차|
|hazard_ratio|number|exp(Cox 계수), 순간위험비|
|hr_lower95|number|HR CI 하한|
|hr_upper95|number|HR CI 상한|
|statistic|number|Wald 등 통계량|
|df|number|검정 자유도|
|p|number|양측 검정 p값|

**Output 검토 / 가정 위반 시 주의:** HR은 위험비/확률비가 아니다. coefficient/reference/contrast/interaction_wald 행을 구별한다. 계약의 interaction_contrast/global_wald 표기와 실제 행 문자열이 다를 수 있다. 상수·종속 열 제거 및 완전사례 탈락을 확인한다. PH 진단 도구는 weights/strata/cluster/interactions를 모두 재현하지 못한다.

**Processing Type:** Cox 적합 / 대치 draw별 반복 가능 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-cox_ph_univariate"></a>

## 55. `cox_ph_univariate`

**Description / 목적:** 공변량별 별도 Cox 모형을 적합하여 비조정 HR을 나열한다.

**구현 근거:** [tool_sample.py:7522](../tool_sample/tool_sample.py#L7522) · `cox_ph_univariate`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|duration_column|column|필수|— (인수 필수)|Follow-up time (numeric).|
|event_column|column|필수|— (인수 필수)|Column recording the outcome status.|
|event_values|list[value]|필수|— (인수 필수)|Value(s) of event_column that count as an EVENT (=1), verbatim; the rest are censored.|
|covariates|list[column]|필수|— (인수 필수)|The characteristics to model ONE AT A TIME — each gets its own model, so list every characteristic the univariate column reports. EXCLUDE duration/event columns and identifiers. Never empty.|
|where|string|선택|''|SQL boolean cohort filter. Do NOT add 'IS NOT NULL' guards for the covariates: the tool applies the complete-case restriction itself (rows missing ANY covariate are dropped BEFORE encoding, so a category that survives only in dropped rows never becomes a phantom level), and it drops covariate columns that end up constant or redundant in the resulting cohort, reporting both in its summary. Use `where` for the CLINICAL cohort definition only. If a covariate is too incompletely recorded to lose, impute it first with impute_missing instead of filtering on it. Each univariate model gets its OWN complete-case population, which is why the table reports n per row.|
|strata|list[column]|선택|None|Columns to stratify every model's baseline hazard by. A column that is also the model's own covariate is skipped for that model (it cannot be both). Optional.|
|weights_column|column|선택|''|Per-patient weight column for IPTW-weighted models (the 'iptw' column from iptw_weight). Robust variance is enabled automatically.|
|robust|bool|선택|None|Robust (sandwich) standard errors. Defaults to true when weights_column is set.|
|cluster_column|column|선택|''|Column identifying correlated clusters (registry, hospital…) for clustered robust SEs.|
|reference_levels|object|선택|None|{covariate: baseline category} for categorical covariates, e.g. {"Race recode": "Black"}. Every hazard ratio is measured against this level, so whenever the request names a reference/baseline category you MUST set it here. Copy the level verbatim from the column's values; a level that does not occur is an error.|
|penalizer|number|선택|0.0|Ridge penalty (e.g. 0.1) for a covariate whose levels are collinear/sparse. Default 0.|
|imputation_column|column|선택|''|Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default) — the tool detects `_imputation` on its own, runs the estimate INSIDE each draw and pools the m results by Rubin's rules, so every reported n counts PATIENTS. Name a column only when the index is spelled differently; pass "none" to analyse the stacked draws as one cohort, which counts every patient m times and is almost never what the protocol means.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 각 모형에서 PH·검열·선형성 전제. 변수별 결측 때문에 분석 표본이 달라질 수 있다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_covariate_term`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|covariate|string|which univariate model the row came from|
|term_type|string|coefficient \| reference \| global_wald|
|term|string|설계행렬 항/대비명|
|coef|number|링크/log-hazard 척도 계수|
|se|number|계수 표준오차|
|hazard_ratio|number|exp(Cox 계수), 순간위험비|
|hr_lower95|number|HR CI 하한|
|hr_upper95|number|HR CI 상한|
|statistic|number|Wald 등 통계량|
|df|number|검정 자유도|
|p|number|양측 검정 p값|
|n|integer|분석/검사 분모; 도구별 관측 단위 확인|
|events|integer|사건 수|

**Output 검토 / 가정 위반 시 주의:** covariate/n/events로 모형을 구별하는 구조가 적절하다. 여러 수준의 전역 검정과 수준별 검정을 구분한다. 단변수 p값에 따른 자동 변수선택과 다중검정에 주의한다.

**Processing Type:** 변수별 Cox 적합 / 변수×대치 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-cox_ph_subgroup"></a>

## 56. `cox_ph_subgroup`

**Description / 목적:** 각 하위집단 안에서 노출 효과의 Cox 모형을 별도로 적합한다.

**구현 근거:** [tool_sample.py:7794](../tool_sample/tool_sample.py#L7794) · `cox_ph_subgroup`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|duration_column|column|필수|— (인수 필수)|Follow-up time (numeric).|
|event_column|column|필수|— (인수 필수)|Column recording the outcome status.|
|event_values|list[value]|필수|— (인수 필수)|Value(s) of event_column that count as an EVENT (=1), verbatim; the rest are censored.|
|exposure_column|column|필수|— (인수 필수)|The exposure / treatment column whose HR is reported inside every subgroup (e.g. surgery type). Categoricals are one-hot encoded against reference_level.|
|subgroup_columns|list[column]|필수|— (인수 필수)|Columns that DEFINE the subgroups — each distinct level of each column gets its own exposure-only Cox. List every characteristic the subgroup table/forest covers. Never empty. Must not include duration/event/exposure.|
|reference_level|value|선택|''|Baseline category of exposure_column (shorthand for reference_levels={exposure_column: level}). Whenever the request names the reference arm (e.g. mastectomy alone), set this — otherwise the baseline is whichever level sorts first.|
|reference_levels|object|선택|None|{covariate: baseline category} for exposure and any extra covariates. reference_level (if set) fills in exposure_column when absent here.|
|covariates|list[column]|선택|None|Optional ADDITIONAL adjustment columns included in EVERY subgroup fit alongside exposure_column. Leave empty for the usual unadjusted-within-subgroup analysis.|
|include_overall|bool|선택|True|If true (default), also fit one Overall model on the full filtered cohort and emit subgroup_variable='Overall', subgroup_category='All'.|
|where|string|선택|''|SQL boolean cohort filter. Do NOT add 'IS NOT NULL' guards for the covariates: the tool applies the complete-case restriction itself (rows missing ANY covariate are dropped BEFORE encoding, so a category that survives only in dropped rows never becomes a phantom level), and it drops covariate columns that end up constant or redundant in the resulting cohort, reporting both in its summary. Use `where` for the CLINICAL cohort definition only. If a covariate is too incompletely recorded to lose, impute it first with impute_missing instead of filtering on it. Inside one subgroup a covariate often collapses to a single level; that slot's column is dropped and named in the summary rather than sinking the fit.|
|strata|list[column]|선택|None|Columns to stratify every model's baseline hazard by. Optional; this is NOT a substitute for subgroup_columns.|
|weights_column|column|선택|''|Per-patient weight column for IPTW-weighted models (the 'iptw' column from iptw_weight). Robust variance is enabled automatically.|
|robust|bool|선택|None|Robust (sandwich) standard errors. Defaults to true when weights_column is set.|
|cluster_column|column|선택|''|Column identifying correlated clusters (registry, hospital…) for clustered robust SEs.|
|penalizer|number|선택|0.0|Ridge penalty (e.g. 0.1) when a slot's design is collinear/sparse. Default 0.|
|imputation_column|column|선택|''|Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default) — the tool detects `_imputation` on its own, runs the estimate INSIDE each draw and pools the m results by Rubin's rules, so every reported n counts PATIENTS. Name a column only when the index is spelled differently; pass "none" to analyse the stacked draws as one cohort, which counts every patient m times and is almost never what the protocol means.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 하위집단별 충분한 사건·노출 두 수준, PH 및 검열 전제. subgroup_columns와 adjustment/strata는 역할이 다르다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_subgroup_term`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|subgroup_variable|string|하위집단 변수|
|subgroup_category|string|하위집단 수준|
|exposure|string|노출 변수/수준|
|term_type|string|결과 행 유형|
|term|string|설계행렬 항/대비명|
|coef|number|링크/log-hazard 척도 계수|
|se|number|계수 표준오차|
|hazard_ratio|number|exp(Cox 계수), 순간위험비|
|hr_lower95|number|HR CI 하한|
|hr_upper95|number|HR CI 상한|
|statistic|number|Wald 등 통계량|
|p|number|양측 검정 p값|
|n|integer|분석/검사 분모; 도구별 관측 단위 확인|
|n_ref|integer|기준군 수|
|n_exposed|integer|노출군 수|
|events|integer|사건 수|

**Output 검토 / 가정 위반 시 주의:** 하위집단·노출·n/사건수·HR로 구분 가능하다. 한 군 유의/다른 군 비유의가 상호작용의 증거는 아니다. 정식 interaction 검정 및 실패한 하위집단 표시가 필요하다.

**Processing Type:** 하위집단별 Cox 적합 / 집단×대치 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-cox_ph_assumptions"></a>

## 57. `cox_ph_assumptions`

**Description / 목적:** Cox를 재적합하고 rank 시간 변환의 Schoenfeld 잔차 기반 PH 검정을 수행한다.

**구현 근거:** [tool_sample.py:10258](../tool_sample/tool_sample.py#L10258) · `cox_ph_assumptions`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|duration_column|column|필수|— (인수 필수)|Follow-up time (numeric); same as the cox_ph being checked.|
|event_column|column|필수|— (인수 필수)|Column recording the outcome status.|
|event_values|list[value]|필수|— (인수 필수)|Value(s) counted as an EVENT (=1), verbatim; rest censored.|
|covariates|list[column]|필수|— (인수 필수)|The same covariates used in the cox_ph model. Never empty.|
|where|string|선택|''|SQL boolean cohort filter — copy the cox_ph node's verbatim. You do NOT need to add 'IS NOT NULL' for the covariates: the tool applies the complete-case restriction itself (rows missing ANY covariate are dropped BEFORE encoding, so a category that survives only in dropped rows never becomes a phantom level), and it drops covariate columns that end up constant or redundant in the resulting cohort, reporting both in its summary. Use `where` for the CLINICAL cohort definition only. If a covariate is too incompletely recorded to lose, impute it first with impute_missing instead of filtering on it.|
|reference_levels|object|선택|None|{covariate: baseline category}, copied from the cox_ph node being checked. The baseline decides which dummy columns the design has, so a different one tests a different model.|
|penalizer|number|선택|0.0|Ridge penalty, copied from the cox_ph node being checked. Default 0.|
|imputation_column|column|선택|''|Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default) — the tool detects `_imputation` on its own, runs the estimate INSIDE each draw and pools the m results by Rubin's rules, so every reported n counts PATIENTS. Name a column only when the index is spelled differently; pass "none" to analyse the stacked draws as one cohort, which counts every patient m times and is almost never what the protocol means.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 검정 대상과 같은 표본·공변량·기준범주·penalizer여야 한다. p>0.05는 PH 충족의 증명이 아니다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_covariate`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|covariate|string|모형의 공변량 또는 수준|
|test_statistic|number|검정통계량|
|p|number|양측 검정 p값|
|violates_ph|bool|p < 0.05|

**Output 검토 / 가정 위반 시 주의:** 변수별 test_statistic/p/violates_ph만 생성한다. 소개문의 global 검정·잔차 그림은 없다. 대치별 p 평균·다수결은 정식 결합검정이 아니다. 가중/층화/상호작용 Cox와 동일한 모형으로 재현할 인수가 없다.

**Processing Type:** Cox 재적합 / 변수 검정·대치 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-cox_time_varying"></a>

## 58. `cox_time_varying`

**Description / 목적:** 환자별 start–stop 긴 형태 자료로 시간변화 공변량 Cox를 적합한다.

**구현 근거:** [tool_sample.py:10438](../tool_sample/tool_sample.py#L10438) · `cox_time_varying`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|id_column|column|필수|— (인수 필수)|Subject id (one subject spans multiple interval rows).|
|start_column|column|필수|— (인수 필수)|Interval start time.|
|stop_column|column|필수|— (인수 필수)|Interval stop time.|
|event_column|column|필수|— (인수 필수)|Event status at the interval's stop.|
|covariates|list[column]|필수|— (인수 필수)|Adjustment columns (may vary across intervals). Never empty.|
|input|str|선택|'seer'|입력 관계명(source의 예외 명칭)|
|event_values|list[value]|선택|None|Value(s) counted as an EVENT (=1), verbatim. Optional.|
|where|string|선택|''|SQL boolean cohort filter. Do NOT add 'IS NOT NULL' guards for the covariates: the tool applies the complete-case restriction itself (rows missing ANY covariate are dropped BEFORE encoding, so a category that survives only in dropped rows never becomes a phantom level), and it drops covariate columns that end up constant or redundant in the resulting cohort, reporting both in its summary. Use `where` for the CLINICAL cohort definition only. If a covariate is too incompletely recorded to lose, impute it first with impute_missing instead of filtering on it. The unit dropped here is an INTERVAL, so a subject can lose part of their follow-up rather than all of it.|
|imputation_column|column|선택|''|Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default) — the tool detects `_imputation` on its own, runs the estimate INSIDE each draw and pools the m results by Rubin's rules, so every reported n counts PATIENTS. Name a column only when the index is spelled differently; pass "none" to analyse the stacked draws as one cohort, which counts every patient m times and is almost never what the protocol means.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. id별 start<stop, 구간 중복 없음, 사건은 해당 구간 끝, 미래 정보 누수 없음. 적절한 검열 및 PH 구조.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_term`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|term_type|string|coefficient \| reference \| interaction_contrast \| global_wald|
|term|string|설계행렬 항/대비명|
|group|string|군 또는 상호작용 수준; 도구별 확인|
|coef|number|링크/log-hazard 척도 계수|
|se|number|계수 표준오차|
|hazard_ratio|number|exp(Cox 계수), 순간위험비|
|hr_lower95|number|HR CI 하한|
|hr_upper95|number|HR CI 상한|
|statistic|number|Wald 등 통계량|
|df|number|검정 자유도|
|p|number|양측 검정 p값|

**Output 검토 / 가정 위반 시 주의:** 시간변화 계수 모형과 시간변화 공변량 모형은 다르다. 결측 삭제는 환자가 아니라 일부 추적 구간을 제거한다. n_intervals/n_subjects 및 구간 유효성 진단이 필요하다. source 대신 input 인수를 쓰는 예외가 있다.

**Processing Type:** Cox 적합 / 대치별 반복 가능 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-iptw_kaplan_meier"></a>

## 59. `iptw_kaplan_meier`

**Description / 목적:** 성향점수 가중 생존곡선과 재적합 bootstrap CI를 계산한다.

**구현 근거:** [tool_sample.py:6910](../tool_sample/tool_sample.py#L6910) · `iptw_kaplan_meier`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|treatment_column|column|필수|— (인수 필수)|Column separating the treated and control arms.|
|treatment_values|list[value]|필수|— (인수 필수)|ONLY the value(s) marking the TREATED arm, verbatim; control is everyone else.|
|duration_column|column|필수|— (인수 필수)|Follow-up time (numeric, e.g. survival months).|
|event_column|column|필수|— (인수 필수)|Column recording the outcome status.|
|event_values|list[value]|필수|— (인수 필수)|Value(s) of event_column that count as an EVENT (=1), verbatim; the rest are censored.|
|covariates|list[column]|필수|None|Confounders the weights adjust for (auto-typed: numeric → continuous, else categorical). EXCLUDE the treatment, duration and event columns. Never empty.|
|cont_var|list[column]|선택|None|Force these covariates to be CONTINUOUS.|
|cat_var|list[column]|선택|None|Force these covariates to be CATEGORICAL.|
|binary_var|list[column]|선택|None|Force these covariates to be BINARY.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|weight_type|string|선택|'iptw'|"iptw" (default, ATE) or "overlap" (ATO).|
|stabilized|bool|선택|True|Stabilized IPTW. Default true.|
|clip_bounds|list[number]|선택|None|Trim propensity scores to [lower, upper], e.g. [0.01, 0.99].|
|normalize|str|선택|''|가중치 정규화 옵션; 본문 구현 확인|
|n_bootstrap|integer|선택|200|Bootstrap resamples behind the CI (default 200). Every resample refits the propensity model, so raise it only on small cohorts.|
|random_state|integer|선택|42|Bootstrap/model seed. Default 42.|
|title|string|선택|''|Figure title. Optional.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 인과 가중치 전제+비정보적 검열. 치료 IPTW는 정보적 검열을 자동 교정하지 않는다. 두 군 overlap과 ESS 확인.

**Output:** `figure` · 계약 형식 `png+parquet` · 행 단위 `figure`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

원본 Figure 계약의 빈 columns를 실제 생성 코드 기준으로 보완했다. 그림의 데이터 테이블은 다음과 같다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|time|number\|string|추적 시간|
|treatment_estimate|number\|string|처치 생존확률|
|control_estimate|number\|string|대조 생존확률|
|treatment_lower_ci / treatment_upper_ci|number\|string|처치 bootstrap CI|
|control_lower_ci / control_upper_ci|number\|string|대조 bootstrap CI|

**기존 Output 계약 메모:** Returns a PNG plus the tidy frame the chart was drawn from. Does not invent columns — it plots what its inputs already hold.

**Output 검토 / 가정 위반 시 주의:** time 및 군별 추정치/CI가 있어 좋다. 일반 Figure 스키마에 열이 누락되어 있다. bootstrap 성공 횟수, 가중 ESS, follow-up 지지구간과 weight_type을 결과에 남겨야 한다.

**Processing Type:** 성향점수 적합+생존 추정 / bootstrap 재적합 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-iptw_survival_metrics"></a>

## 60. `iptw_survival_metrics`

**Description / 목적:** 가중 고정시점 생존확률·RMST·중앙생존 및 처치-대조 절대차를 계산한다.

**구현 근거:** [tool_sample.py:7005](../tool_sample/tool_sample.py#L7005) · `iptw_survival_metrics`. 정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음.

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|treatment_column|column|필수|— (인수 필수)|Column separating the treated and control arms.|
|treatment_values|list[value]|필수|— (인수 필수)|ONLY the value(s) marking the TREATED arm, verbatim; control is everyone else.|
|duration_column|column|필수|— (인수 필수)|Follow-up time (numeric).|
|event_column|column|필수|— (인수 필수)|Column recording the outcome status.|
|event_values|list[value]|필수|— (인수 필수)|Value(s) counted as an EVENT (=1), verbatim; the rest are censored.|
|covariates|list[column]|필수|None|Confounders the weights adjust for (auto-typed). Never empty.|
|cont_var|list[column]|선택|None|Force these covariates to be CONTINUOUS.|
|cat_var|list[column]|선택|None|Force these covariates to be CATEGORICAL.|
|binary_var|list[column]|선택|None|Force these covariates to be BINARY.|
|where|string|선택|''|SQL boolean cohort filter. Optional.|
|psurv_time_points|list[number]|선택|None|Timepoints for adjusted survival probability, in the duration column's OWN unit — e.g. [60, 120] for 5- and 10-year survival when duration is in months.|
|rmst_time_points|list[number]|선택|None|Horizons for restricted mean survival time, same unit as duration, e.g. [60].|
|median_time|bool|선택|True|Also report median survival per arm. Default true.|
|weight_type|string|선택|'iptw'|"iptw" (default, ATE) or "overlap" (ATO).|
|stabilized|bool|선택|True|Stabilized IPTW. Default true.|
|clip_bounds|list[number]|선택|None|Trim propensity scores to [lower, upper].|
|normalize|str|선택|''|가중치 정규화 옵션; 본문 구현 확인|
|n_bootstrap|integer|선택|200|Bootstrap resamples behind the CIs (default 200).|
|random_state|integer|선택|42|Bootstrap/model seed. Default 42.|
|label|str|선택|''|출력 이름; 빈 값이면 자동 생성|
|source|str|선택|'seer'|입력 DuckDB 관계명; 기본 seer|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 가중 생존분석 전제. 시간점/적분 상한은 데이터의 시간 단위이며 충분한 추적 지지구간 안이어야 한다.

**Output:** `table` · 계약 형식 `parquet` · 행 단위 `one_row_per_group_metric_timepoint`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|group|string|treatment \| control \| difference|
|metric|string|survival_probability \| rmst \| median_survival|
|timepoint|number|horizon; null for median_survival|
|estimate|number|metric/estimate_type 척도의 점추정|
|lower_ci|number|CI 하한|
|upper_ci|number|CI 상한|

**Output 검토 / 가정 위반 시 주의:** group/metric/timepoint/estimate/CI의 long table은 유용하다. median 미도달은 0이 아닌 결측/미도달로 표시해야 한다. RMST와 생존확률은 단위가 달라 metric별 표시 단위가 필요하다.

**Processing Type:** 성향점수 적합+생존 추정 / 시간점·bootstrap 반복 / 한 번 호출. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.


<a id="tool-basic_glm"></a>

## 61. `basic_glm`

**Description / 목적:** 제출용 기본 GLM: Gaussian 평균 차이, Bernoulli OR, Poisson count ratio를 추정한다.

**구현 근거:** [tool_sample.py:5413](../tool_sample/tool_sample.py#L5413) · `basic_glm`. 신규 구현은 [glm.py](../tool_sample/glm.py).

**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. `None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.

|Parameter|형식|필수|실제 기본값|의미/조건|
|---|---|---|---|---|
|outcome_column|column|필수|— (인수 필수)|종속변수. binomial은 0/1, poisson은 비음수 정수.|
|covariates|list[column]|필수|— (인수 필수)|중복 없는 설명변수 목록. 종속변수 제외.|
|family|string|선택|'gaussian'|gaussian(기본), binomial, poisson. 링크는 각각 identity/logit/log 고정.|
|categorical|list[column]|선택|None|범주형으로 처리할 설명변수. 기본 없음; 숫자 코드도 명시.|
|reference_levels|object|선택|None|범주형 변수별 기준값. 기본은 완전 사례에서 문자열 정렬 첫 값.|
|missing|string|선택|'raise'|raise(기본) 또는 drop. 후자는 인코딩 전에 행 제거.|
|max_iter|integer|선택|100|양의 정수. 기본 100.|
|tolerance|number|선택|1e-08|양의 유한 수렴 허용오차. 기본 1e-8.|
|where|string|선택|''|DuckDB 필터. 기본 빈 문자열. 신뢰하는 로컬 SQL만 사용.|
|label|string|선택|''|결과 관계 이름. 기본 basic_glm_순번. source와 달라야 함.|
|source|string|선택|'seer'|입력 DuckDB 관계 이름. 기본 seer.|

**입력 형식·조건 / Assumptions:** 기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다. 독립 행, 올바른 분포/고정 링크, full-rank 설계, 충분한 표본. Gaussian 조건부 등분산·정규성(모형 기반 추론), Bernoulli logit 선형성/분리 없음, Poisson 조건부 평균=분산. 숫자 범주는 categorical로 명시한다.

**Output:** `table` · 계약 형식 `DuckDB table + JSON metadata` · 행 단위 `one_row_per_design_term`. 반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.

|주요 Column|형식|의미/생성 조건|
|---|---|---|
|term|string|절편 또는 설명변수/수준|
|variable|string\|null|원본 설명변수 이름; 절편은 null|
|level|string\|null|범주 수준|
|reference|string\|null|해당 변수의 기준 수준|
|term_type|string|intercept 또는 coefficient|
|coef|number|링크 척도 계수|
|se|number|계수 표준오차|
|z|number|Wald z 통계량|
|p|number|양측 Wald p값|
|coef_lower95|number|계수 CI 하한|
|coef_upper95|number|계수 CI 상한|
|estimate|number|Gaussian은 계수, 나머지는 exp(coef)|
|lower95|number|estimate CI 하한|
|upper95|number|estimate CI 상한|
|estimate_type|string|mean_difference/odds_ratio/count_ratio; 절편은 baseline_mean/odds/count|

**기존 Output 계약 메모:** deliverable.diagnostics에 표본수, 제외수, family/link, 기준수준, AIC, deviance, 분산, 수렴 및 경고 저장. 모델 파일/예측/Figure는 생성하지 않음.

**Output 검토 / 가정 위반 시 주의:** 명시적 결측 정책, 분석 n/제외수, 수렴/분산/AIC/deviance, 기준범주와 절편 척도를 보존한다. 모델 기반 Wald CI이며 소표본·준완전분리·군집 상관·과산포에서는 신뢰하기 어렵다. offset/exposure/가중치/대치 pooling/새자료 예측은 범위 밖이다. 기존 GLM과 별도 이름으로 추가했다.

**Processing Type:** IRLS 통계모델 적합 / 반복 최적화, 외부 batch 불필요 / 단일 실행. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.

## 부록 A. 등록 분석 외 보조 코드

상단 officialdocs 기반 ToolHub 로더는 `_OFFICIALDOCS_LOADER_DISABLED` raw 문자열 내부에 있어 실행되지 않는다. 주석의 scipy/sklearn 전체 라이브러리 자동 등록을 현재 기능으로 간주하면 안 된다.

|구분|입력/출력 및 역할|주의사항|
|---|---|---|
|seer_schema|keyword → 열 이름/형식 문자열|최대 표시 열 수가 있으며 분석 산출물 아님|
|seer_value_counts|column, top_n=25 → 상위 값/빈도 문자열|전체 분포가 아닌 상위 100개 이내|
|seer_sql|query, output_name → 문자열 및 선택 관계/preview|읽기 전용 검사와 실제 접근통제는 다름|
|duckdb_query|query, limit → 제한된 미리보기 문자열|산출물 등록 없음|
|_op_filter/_op_aggregate/_op_value_counts/_op_describe/_op_sql|SQL 변환 생성기|일부 정의는 현재 registry 연결과 다를 수 있으므로 public 분석 60개에 포함하지 않음|
|ml_classifier / ml_predict|범용 모델 적합/예측 내부 경로|개별 estimator 또는 CV 도구와 중복되며 현재 description 60개에는 없음. 숨은 구현을 새 public 계약으로 보지 않음|
|_design_matrix 등|인코딩·매칭·가중·분산·대치 pooling 보조 함수|독립 사용자 도구가 아니나 여러 도구의 결과에 영향을 줌|
|run_analysis_step / execute_step|노드 spec → 실행 payload|출력 이름, 입력 edge, 오류·미리보기와 전체 결과 구분|
|persist_* / build_kedro_yaml / build_catalog_metadata|저장 및 실행 메타데이터/YAML|외부 S3 및 전체 애플리케이션 경로가 제공 샘플에 없음|

## 부록 B. 참고 근거

도구의 실제 동작에 대한 1차 근거는 제공 코드이다. 아래 공식 문서는 통계 정의·라이브러리 계약 확인에 사용했다. 문서의 최신 버전과 실행 환경 버전을 동일하다고 가정하지 않는다. 실제 실행 버전은 requirements-lock.txt에 기록했다.

- [statsmodels GLM](https://www.statsmodels.org/stable/glm.html): family/link와 GLM 구조.
- [statsmodels 0.14.4 GLM API](https://www.statsmodels.org/v0.14.4/generated/statsmodels.genmod.generalized_linear_model.GLM.html): exposure/offset/weights 정의, 0.14부터 완전분리의 기본 처리가 경고라는 버전 주의사항.
- [lifelines PH 가정 확인](https://lifelines.readthedocs.io/en/latest/jupyter_notebooks/Proportional%20hazard%20assumption.html): Schoenfeld 기반 검정과 시각적 진단.
- [lifelines statistics](https://lifelines.readthedocs.io/en/latest/lifelines.statistics.html): log-rank와 PH 검정 API.

개별 도구의 원본 공식 참고 링크는 동반 JSON의 `toolhub_intro`에 보존했다. 모든 외부 링크/라이브러리를 실행 검증한 것은 아니다.

