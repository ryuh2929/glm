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
