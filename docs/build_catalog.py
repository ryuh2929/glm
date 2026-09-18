"""Rebuild Markdown/JSON from source signatures and human-reviewed notes.

Run from repository root: python -m docs.build_catalog
"""
import ast
import hashlib
import json
from pathlib import Path

from tool_sample.tool_desc import description
from docs.catalog_notes import NOTES

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tool_sample" / "tool_sample.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SeerToolbox")
methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}

MEANING = {
    "Variable": "변수 표시명", "Level": "범주 수준", "Overall": "전체 요약",
    "step": "조건 적용 순서(0은 시작 코호트)", "criterion": "조건 이름", "expression": "적용 SQL",
    "n_before": "단계 직전 행 수", "n_after": "단계 직후 행 수", "n_excluded": "해당 단계 제외 행 수",
    "pct_excluded": "직전 행 수 대비 제외 백분율", "n_subjects": "고유 대상자 수",
    "check": "검사 유형", "variable": "대상 변수", "n": "분석/검사 분모; 도구별 관측 단위 확인",
    "n_flagged": "위반 또는 결측 건수", "pct_flagged": "분모 대비 위반 백분율", "n_distinct": "고유값 수",
    "detail": "검사 설명 또는 오류", "value_column": "수치 결과 열", "group_column": "군 구분 열",
    "group_a": "첫 비교군", "group_b": "둘째 비교군", "n_a": "첫 군 표본 수", "n_b": "둘째 군 표본 수",
    "median_a": "첫 군 중앙값", "median_b": "둘째 군 중앙값", "u_statistic": "U 검정통계량",
    "p_value": "귀무가설하 p값", "alternative": "대립가설 방향", "method": "사용 추정/검정 방법",
    "row_column": "교차표 행 변수", "col_column": "교차표 열 변수", "n_rows": "교차표 행 범주 수",
    "n_cols": "교차표 열 범주 수", "chi2_statistic": "카이제곱/선택 power-divergence 통계량",
    "dof": "검정 자유도", "cramers_v": "범주 연관 강도", "lambda_": "power-divergence 파라미터",
    "correction": "연속성 보정 설정", "covariate": "모형의 공변량 또는 수준",
    "level_type": "계수/절편/기준범주 구분", "coef": "링크/log-hazard 척도 계수",
    "se": "계수 표준오차", "odds_ratio": "exp(logit 계수), 오즈비", "or_lower95": "OR CI 하한",
    "or_upper95": "OR CI 상한", "z": "Wald z", "p": "양측 검정 p값",
    "estimate": "metric/estimate_type 척도의 점추정", "ci_lower": "CI 하한", "ci_upper": "CI 상한",
    "estimate_type": "효과 척도", "estimand": "목표 효과 집단 ATT/ATE/ATO", "feasible": "효과 계산 가능 여부",
    "n_loaded": "불러온 행 수", "n_complete": "완전사례 처리 후 수", "n_analyzed": "지지영역 제한 후 분석 수",
    "n_covariate_missing": "공변량 미기록이 남은 행 수", "covariates_unrecorded": "미기록 공변량 목록",
    "n_imputations": "대치 draw 수", "n_treated": "처치군 수", "n_control": "대조군 수",
    "mu_treated": "처치 잠재결과 평균", "mu_control": "대조 잠재결과 평균",
    "effect": "처치-대조 평균차", "effect_lower95": "평균차 CI 하한", "effect_upper95": "평균차 CI 상한",
    "effect_se": "평균차 표준오차", "ratio": "처치/대조 평균비", "n_bootstrap": "bootstrap 횟수(성공 수 별도 확인)",
    "significant": "효과 CI가 귀무값을 제외하는지", "specification": "분석 설정 식별자",
    "effect_minus_primary": "주 분석 대비 효과 차이", "type": "변수/결과 유형", "level": "범주 수준",
    "treated": "처치군 평균 또는 비율", "control": "대조군 평균 또는 비율", "asd": "절대 표준화 차이",
    "balanced": "ASD<0.1 플래그", "scenario": "비교 시나리오", "asd_reference": "첫 시나리오 ASD",
    "scale": "입력 효과 척도", "risk_ratio_scale": "RR 척도로 변환한 효과",
    "evalue_point": "점추정 E-value", "evalue_ci": "귀무값에 가까운 CI의 E-value",
    "rr_confounder_outcome": "가정한 교란-결과 RR", "rr_confounder_exposure": "가정한 교란-노출 RR",
    "bounding_factor": "최대 편향계수", "adjusted_estimate": "편향 조정 점추정",
    "adjusted_ci_lower": "편향 조정 CI 하한", "adjusted_ci_upper": "편향 조정 CI 상한",
    "still_significant": "조정 후 귀무값 제외 여부", "metric": "평가지표/생존지표 종류", "value": "지표 값",
    "model": "모델 키", "model_name": "모델 표시명", "n_events": "사건/양성 수", "folds": "CV fold 수",
    "auc": "ROC AUC", "brier": "확률 제곱오차 평균", "calibration_slope": "보정 기울기(이상적 1)",
    "calibration_intercept": "보정 절편(이상적 0)", "citl": "calibration-in-the-large",
    "rank": "OOF AUC 순위", "time_column": "추적시간 열", "event_column": "사건코드 열",
    "events_a": "첫 군 사건 수", "events_b": "둘째 군 사건 수", "test_statistic": "검정통계량",
    "t_0": "검정 추적 제한시간", "weightings": "log-rank 가중 방식", "term_type": "결과 행 유형",
    "term": "설계행렬 항/대비명", "group": "군 또는 상호작용 수준; 도구별 확인",
    "hazard_ratio": "exp(Cox 계수), 순간위험비", "hr_lower95": "HR CI 하한", "hr_upper95": "HR CI 상한",
    "statistic": "Wald 등 통계량", "df": "검정 자유도", "events": "사건 수", "exposure": "노출 변수/수준",
    "subgroup_variable": "하위집단 변수", "subgroup_category": "하위집단 수준", "n_ref": "기준군 수",
    "n_exposed": "노출군 수", "violates_ph": "p<0.05 플래그; PH 위반 확정이 아님",
    "timepoint": "생존확률/RMST 평가 시간", "lower_ci": "CI 하한", "upper_ci": "CI 상한",
}
FIGURES = {
    "kaplan_meier": [("group", "군(그룹 지정 시)"), ("time_months", "입력 단위의 시간; 월로 변환하지 않음"), ("n_at_risk", "직전 위험집단 수"), ("n_events", "해당 시점 사건 수"), ("survival_probability", "생존확률"), ("ci_lower", "95% CI 하한"), ("ci_upper", "95% CI 상한")],
    "competing_risk_cif": [("group", "군"), ("cause", "사건 종류"), ("time", "입력 단위 시간"), ("cif", "누적발생률"), ("cif_lower95", "CI 하한"), ("cif_upper95", "CI 상한")],
    "ml_roc_curve": [("fpr", "위양성률"), ("tpr", "민감도"), ("threshold", "임계값; 무한값은 null")],
    "ml_calibration_curve": [("prob_pred", "bin 평균 예측확률"), ("prob_true", "bin 실제 사건 비율"), ("bin_count", "bin 표본 수; 동점 경계 불일치 가능")],
    "ml_decision_curve": [("threshold", "임계확률"), ("net_benefit_model", "모델 순편익"), ("net_benefit_all", "모두 처치 순편익"), ("net_benefit_none", "무처치 순편익=0")],
    "iptw_kaplan_meier": [("time", "추적 시간"), ("treatment_estimate", "처치 생존확률"), ("control_estimate", "대조 생존확률"), ("treatment_lower_ci / treatment_upper_ci", "처치 bootstrap CI"), ("control_lower_ci / control_upper_ci", "대조 bootstrap CI")],
}


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def main():
    assert {d["name"] for d in description} == set(NOTES), "Review coverage mismatch"
    lines = [(ROOT / "docs" / "catalog_intro.md").read_text(encoding="utf-8"),
             "\n## 도구 목록\n", "|번호|도구|분류|주 출력|", "|---|---|---|---|"]
    for i, spec in enumerate(description, 1):
        lines.append(f"|{i}|[{spec['name']}](#tool-{spec['name'].lower()})|{spec['category']}|{spec['output_type']}|")
    exported = []
    for i, spec in enumerate(description, 1):
        name = spec["name"]
        node = methods[name]
        purpose, assumptions, review, processing = NOTES[name]
        lines += [f'\n<a id="tool-{name.lower()}"></a>\n', f"## {i}. `{name}`\n",
                  f"**Description / 목적:** {purpose}\n",
                  f"**구현 근거:** [tool_sample.py:{node.lineno}](../tool_sample/tool_sample.py#L{node.lineno}) · `{node.name}`. "
                  + ("신규 구현은 [glm.py](../tool_sample/glm.py)." if name == "basic_glm" else "정적 검토; 기존 도구의 전체 수치 검증은 수행하지 않음."),
                  "\n**Input / Parameter:** 아래 필수 여부는 카탈로그의 사용 계약, 기본값은 실제 함수 시그니처 기준이다. "
                  "`None` 기본값이 있어도 본문에서 값 입력을 요구할 수 있다. `source`/`label`은 실행 계층이 주입할 수 있다.\n",
                  "|Parameter|형식|필수|실제 기본값|의미/조건|", "|---|---|---|---|---|"]
        params = {p["name"]: p for p in spec.get("param_specs", [])}
        args = node.args.args[1:]
        defaults = [None]*(len(args)-len(node.args.defaults)) + node.args.defaults
        extracted = []
        for arg, default in zip(args, defaults):
            p = params.get(arg.arg, {})
            required = p.get("required", default is None)
            default_text = "— (인수 필수)" if default is None else ast.unparse(default)
            desc = p.get("description", {
                "source": "입력 DuckDB 관계명; 기본 seer", "input": "입력 관계명(source의 예외 명칭)",
                "label": "출력 이름; 빈 값이면 자동 생성", "normalize": "가중치 정규화 옵션; 본문 구현 확인",
                "order": "범주 표시 순서", "limit": "표시 수준 수 제한", "decimals": "표시 소수 자릿수",
                "missing": "결측 요약 표시 여부", "label_suffix": "요약 통계 접미사 표시", "include_null": "NULL 수준 포함 여부",
            }.get(arg.arg, "카탈로그 param_specs에는 없음. 실제 함수 인수이며 사용 전 구현의 처리 조건 확인."))
            typ = p.get("type", ast.unparse(arg.annotation) if arg.annotation else "Any")
            lines.append("|"+"|".join(cell(v) for v in [arg.arg, typ, "필수" if required else "선택", default_text, desc])+"|")
            extracted.append(dict(name=arg.arg, type=typ, required=required, default_source=default_text, description=desc))
        input_text = ("효과 추정치/CI 등의 스칼라 수치가 주 입력이며 환자 테이블은 계산에 필요하지 않다." if name in ("evalue", "bias_sensitivity") else
                      "기본 입력은 로컬/S3 Parquet가 등록된 DuckDB `seer` 또는 선행 노드의 관계다. 1행=1관측이 기본이며, 시간변화 Cox는 1행=1추적구간, 다중대치는 환자×draw 구조다. 열 이름과 값 코딩은 위 파라미터를 따른다.")
        lines += [f"\n**입력 형식·조건 / Assumptions:** {input_text} {assumptions}\n"]
        schema = spec.get("output_schema", {})
        lines += [f"**Output:** `{spec['output_type']}` · 계약 형식 `{schema.get('format', '미정의')}` · 행 단위 `{schema.get('cardinality', '미정의')}`. "
                  "반환값 자체는 문자열 요약이며, 분석 테이블은 DuckDB 관계 및 deliverables로 전달한다. Parquet/PNG 저장은 환경 의존이다.\n"]
        if schema.get("inherits_input_columns"):
            lines += ["원본 입력 열을 이어받는 환자 데이터셋이다. 아래에는 파생 열만 열거한다.\n"]
        cols = schema.get("columns", [])
        if name in FIGURES:
            cols = [dict(name=n, type="number|string", description=d) for n, d in FIGURES[name]]
            lines += ["원본 Figure 계약의 빈 columns를 실제 생성 코드 기준으로 보완했다. 그림의 데이터 테이블은 다음과 같다.\n"]
        lines += ["|주요 Column|형식|의미/생성 조건|", "|---|---|---|"]
        reviewed_cols = []
        for col in cols:
            meaning = col.get("description") or MEANING.get(col["name"], "원본 스키마의 파생 열; 이름에 표시된 지표/시점 기준")
            if col.get("when"): meaning += " / 조건: "+col["when"]
            reviewed_cols.append(dict(col, description=meaning))
            lines.append("|"+"|".join(cell(x) for x in [col["name"], col.get("type", ""), meaning])+"|")
        side = schema.get("side_deliverable")
        if side:
            lines += ["\n**Side output:** 주 output edge와 별도이며 후속 노드에서 환자 코호트처럼 연결할 수 없다. " + str(side.get("note", "")),
                      "\n|Side Column|의미|", "|---|---|"]
            for col in side.get("columns", []):
                lines.append(f"|{cell(col['name'])}|{cell(col.get('description') or MEANING.get(col['name'], 'side 진단값'))}|")
        if schema.get("note"): lines.append("\n**기존 Output 계약 메모:** "+schema["note"])
        lines += [f"\n**Output 검토 / 가정 위반 시 주의:** {review}\n",
                  f"**Processing Type:** {processing}. 여기서 반복은 내부 계산이며 분산/스트리밍 배치 지원을 뜻하지 않는다.\n"]
        exported.append(dict(spec, source=dict(file="tool_sample/tool_sample.py", line=node.lineno, end_line=node.end_lineno),
                             implementation_parameters=extracted, purpose_ko=purpose, assumptions_ko=assumptions,
                             output_review_ko=review, processing_ko=processing,
                             reviewed_output_columns=reviewed_cols))
    lines += [(ROOT / "docs" / "catalog_appendix.md").read_text(encoding="utf-8")]
    (ROOT / "docs" / "analysis_catalog.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    (ROOT / "docs" / "analysis_catalog.json").write_text(json.dumps({
        "catalog_version": "1.0.0", "review_date": "2026-09-18", "original_tools": 60,
        "new_tools": 1, "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(), "tools": exported,
    }, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Generated catalog: {len(exported)} tools")


if __name__ == "__main__": main()
