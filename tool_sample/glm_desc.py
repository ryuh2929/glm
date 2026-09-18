"""Catalog contract for the new submission tool; no numerical imports."""
description = {
    "name": "basic_glm", "category": "statistics", "output_type": "table",
    "params": '{"outcome_column": "y", "covariates": ["x"], "family": "gaussian"}',
    "summary": "Gaussian/identity, Bernoulli/logit, Poisson/log 기본 GLM. 절편 포함 계수와 95% Wald CI 및 진단값을 생성한다.",
    "param_specs": [
        {"name": n, "type": t, "required": r, "description": d}
        for n, t, r, d in [
            ("outcome_column", "column", True, "종속변수. binomial은 0/1, poisson은 비음수 정수."),
            ("covariates", "list[column]", True, "중복 없는 설명변수 목록. 종속변수 제외."),
            ("family", "string", False, "gaussian(기본), binomial, poisson. 링크는 각각 identity/logit/log 고정."),
            ("categorical", "list[column]", False, "범주형으로 처리할 설명변수. 기본 없음; 숫자 코드도 명시."),
            ("reference_levels", "object", False, "범주형 변수별 기준값. 기본은 완전 사례에서 문자열 정렬 첫 값."),
            ("missing", "string", False, "raise(기본) 또는 drop. 후자는 인코딩 전에 행 제거."),
            ("max_iter", "integer", False, "양의 정수. 기본 100."),
            ("tolerance", "number", False, "양의 유한 수렴 허용오차. 기본 1e-8."),
            ("where", "string", False, "DuckDB 필터. 기본 빈 문자열. 신뢰하는 로컬 SQL만 사용."),
            ("source", "string", False, "입력 DuckDB 관계 이름. 기본 seer."),
            ("label", "string", False, "결과 관계 이름. 기본 basic_glm_순번. source와 달라야 함."),
        ]
    ],
    "output_schema": {
        "format": "DuckDB table + JSON metadata", "cardinality": "one_row_per_design_term",
        "columns": [{"name": n, "type": t, "description": d} for n, t, d in [
            ("term", "string", "절편 또는 설명변수/수준"),
            ("variable", "string|null", "원본 설명변수 이름; 절편은 null"),
            ("level", "string|null", "범주 수준"), ("reference", "string|null", "해당 변수의 기준 수준"),
            ("term_type", "string", "intercept 또는 coefficient"),
            ("coef", "number", "링크 척도 계수"), ("se", "number", "계수 표준오차"),
            ("z", "number", "Wald z 통계량"), ("p", "number", "양측 Wald p값"),
            ("coef_lower95", "number", "계수 CI 하한"), ("coef_upper95", "number", "계수 CI 상한"),
            ("estimate", "number", "Gaussian은 계수, 나머지는 exp(coef)"),
            ("lower95", "number", "estimate CI 하한"), ("upper95", "number", "estimate CI 상한"),
            ("estimate_type", "string", "mean_difference/odds_ratio/count_ratio; 절편은 baseline_mean/odds/count"),
        ]],
        "note": "deliverable.diagnostics에 표본수, 제외수, family/link, 기준수준, AIC, deviance, 분산, 수렴 및 경고 저장. 모델 파일/예측/Figure는 생성하지 않음. ",
    },
}
