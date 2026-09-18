"""수치형 입력을 위한 기본 GLM: Gaussian / Binomial / Poisson."""
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tools.sm_exceptions import (
    PerfectSeparationError,
    PerfectSeparationWarning,
)


def glm_regression(data, outcome_column, covariates, family="gaussian"):
    """절편을 포함한 GLM을 적합하고 coefficients(DataFrame), summary(dict) 반환.

    분석 열은 수치 변환 가능하며 결측/무한값이 없어야 한다.
    Binomial은 개별 0/1 관측, Poisson은 비음수 정수 count만 지원한다.
    링크는 각각 identity/logit/log로 고정한다. CI는 계수 척도의
    95% model-based Wald 구간이다. 입력 오류·불안정 적합은 ValueError.
    """
    # 1. 입력 구조와 필요한 열 검사
    if not isinstance(data, pd.DataFrame):
        raise ValueError("data는 pandas DataFrame이어야 합니다.")
    if not data.columns.is_unique:
        raise ValueError("데이터의 열 이름이 중복되어 있습니다.")
    if not isinstance(outcome_column, str) or not outcome_column:
        raise ValueError("outcome_column에 종속변수 열 이름을 지정하세요.")
    if (not isinstance(covariates, list) or not covariates
            or any(not isinstance(c, str) or not c for c in covariates)):
        raise ValueError("covariates는 비어 있지 않은 열 이름 목록이어야 합니다.")
    if len(covariates) != len(set(covariates)):
        raise ValueError("covariates에 중복된 열이 있습니다.")
    if outcome_column in covariates:
        raise ValueError("종속변수를 독립변수에 포함할 수 없습니다.")
    if not isinstance(family, str) or family not in ("gaussian", "binomial", "poisson"):
        raise ValueError("family는 gaussian, binomial, poisson 중 하나여야 합니다.")
    columns = [outcome_column] + covariates
    absent = [c for c in columns if c not in data.columns]
    if absent:
        raise ValueError(f"데이터에 없는 열: {absent}")

    # 2. 분석 열만 선택. 자동 행 삭제나 범주형 추측은 하지 않는다.
    frame = data[columns].copy()
    if frame.empty:
        raise ValueError("분석할 행이 없습니다.")
    try:
        frame = frame.apply(pd.to_numeric, errors="raise").astype(float)
    except (ValueError, TypeError) as exc:
        raise ValueError("분석 열은 모두 수치형이어야 합니다. 범주형은 미리 인코딩하세요.") from exc
    if frame.isna().any().any():
        raise ValueError("분석 열에 결측값이 있습니다. 결측 처리 후 다시 실행하세요.")
    if not np.isfinite(frame.to_numpy()).all():
        raise ValueError("분석 열에 무한값 또는 유효하지 않은 수치가 있습니다.")
    y = frame[outcome_column].to_numpy()
    if family == "binomial" and (not np.isin(y, [0, 1]).all() or len(np.unique(y)) != 2):
        raise ValueError("Binomial 종속변수는 0과 1만 사용하고 두 값 모두 있어야 합니다.")
    if family == "poisson":
        if (y < 0).any() or (y != np.floor(y)).any():
            raise ValueError("Poisson 종속변수는 0 이상의 정수여야 합니다.")
        if not (y > 0).any():
            raise ValueError("Poisson 종속변수가 모두 0이면 유한한 절편을 추정할 수 없습니다.")

    # 이름 충돌 없이 절편을 추가하고 계수 식별 가능성을 확인한다.
    X = np.column_stack([np.ones(len(frame)), frame[covariates].to_numpy()])
    if len(frame) <= X.shape[1]:
        raise ValueError("관측 수가 절편 포함 추정 계수 수보다 커야 합니다.")
    if np.linalg.matrix_rank(X) < X.shape[1]:
        raise ValueError("상수 또는 선형 종속 독립변수가 있습니다. 중복 정보를 제거하세요.")

    # 3. 기본 링크로 적합. 분리·미수렴을 정상 결과로 내보내지 않는다.
    families = {
        "gaussian": sm.families.Gaussian,
        "binomial": sm.families.Binomial,
        "poisson": sm.families.Poisson,
    }
    try:
        with warnings.catch_warnings():
            if family == "binomial":
                warnings.simplefilter("error", PerfectSeparationWarning)
            result = sm.GLM(y, X, family=families[family]()).fit(maxiter=100)
    except (PerfectSeparationError, PerfectSeparationWarning) as exc:
        raise ValueError("완전분리로 Binomial 계수를 안정적으로 추정할 수 없습니다.") from exc
    except (ValueError, RuntimeError, np.linalg.LinAlgError, FloatingPointError) as exc:
        raise ValueError(f"GLM 적합에 실패했습니다: {exc}") from exc
    if not result.converged:
        raise ValueError("GLM이 수렴하지 않았습니다. 데이터와 독립변수를 확인하세요.")
    ci = np.asarray(result.conf_int(alpha=0.05))
    inference = np.column_stack([result.params, result.bse, result.tvalues, result.pvalues, ci])
    if not np.isfinite(inference).all() or (result.bse <= 0).any():
        raise ValueError("계수 또는 추론 결과가 유효하지 않습니다. 완전적합·분리·표본을 확인하세요.")

    # 4. coef와 CI 모두 링크 척도. exp(coef) 등 확장 출력은 제외한다.
    coefficients = pd.DataFrame(inference, columns=["coef", "se", "z", "p", "ci_lower", "ci_upper"])
    coefficients.insert(0, "covariate", ["(Intercept)"] + covariates)
    summary = {"family": family, "n_obs": int(result.nobs),
               "aic": float(result.aic), "deviance": float(result.deviance)}
    if not np.isfinite([summary["aic"], summary["deviance"]]).all():
        raise ValueError("AIC 또는 deviance가 유효하지 않습니다. 퇴화한 적합인지 확인하세요.")
    return {"coefficients": coefficients, "summary": summary}
