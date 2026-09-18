"""Small, explicit GLM implementation and SeerToolbox adapter.

No remote storage is required. Three fixed family/link pairs are supported.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tools.sm_exceptions import PerfectSeparationWarning


@dataclass
class GLMResult:
    coefficients: pd.DataFrame
    diagnostics: dict


def fit_glm(data: pd.DataFrame, outcome_column: str, covariates: list[str],
            family: str = "gaussian", categorical: list[str] | None = None,
            reference_levels: dict | None = None, missing: str = "raise",
            max_iter: int = 100, tolerance: float = 1e-8) -> GLMResult:
    """Fit Gaussian/identity, Bernoulli/logit or Poisson/log with intercept.

    Rows must be independent. Numeric categorical codes must be explicitly
    listed in categorical. Missing values are rejected unless missing='drop'.
    Raises ValueError for invalid data or unreliable fits. No fitted estimator
    is persisted and all confidence intervals are model-based Wald intervals.
    """
    if not isinstance(data, pd.DataFrame) or not data.columns.is_unique:
        raise ValueError("data must be a DataFrame with unique columns")
    if not isinstance(outcome_column, str) or not outcome_column:
        raise ValueError("outcome_column must be a non-empty string")
    if (not isinstance(covariates, list) or not covariates
            or any(not isinstance(c, str) or not c for c in covariates)
            or len(set(covariates)) != len(covariates)
            or outcome_column in covariates):
        raise ValueError("covariates must be unique column names excluding outcome")
    if family not in ("gaussian", "binomial", "poisson"):
        raise ValueError("family must be gaussian, binomial or poisson")
    if missing not in ("raise", "drop"):
        raise ValueError("missing must be raise or drop")
    if isinstance(max_iter, bool) or not isinstance(max_iter, int) or max_iter < 1:
        raise ValueError("max_iter must be a positive integer")
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not np.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be positive and finite")
    categorical = [] if categorical is None else categorical
    refs = {} if reference_levels is None else reference_levels
    if (not isinstance(categorical, list) or any(not isinstance(c, str) for c in categorical)
            or len(set(categorical)) != len(categorical) or not set(categorical) <= set(covariates)):
        raise ValueError("categorical must be a unique subset of covariates")
    if not isinstance(refs, dict) or not set(refs) <= set(categorical):
        raise ValueError("reference_levels keys must be explicitly categorical")
    selected = [outcome_column] + covariates
    absent = set(selected) - set(data.columns)
    if absent:
        raise ValueError(f"Missing columns: {sorted(absent)}")
    df = data[selected].copy().replace(r"^\s*$", np.nan, regex=True)
    incomplete = df.isna().any(axis=1)
    if incomplete.any() and missing == "raise":
        raise ValueError(f"Missing values in {int(incomplete.sum())} rows; use missing='drop' explicitly")
    df = df.loc[~incomplete].reset_index(drop=True)
    if df.empty:
        raise ValueError("No complete observations")
    numeric = [outcome_column] + [c for c in covariates if c not in categorical]
    for c in numeric:
        try:
            df[c] = pd.to_numeric(df[c], errors="raise").astype(float)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Column {c!r} must be numeric; declare categorical predictors explicitly") from exc
        if not np.isfinite(df[c]).all():
            raise ValueError(f"Column {c!r} contains non-finite values")
    y = df[outcome_column]
    if family == "binomial" and (not y.isin([0, 1]).all() or y.nunique() != 2):
        raise ValueError("Binomial outcome must contain both 0 and 1 (individual Bernoulli observations)")
    if family == "poisson" and ((y < 0).any() or (y != np.floor(y)).any() or y.sum() == 0):
        raise ValueError("Poisson outcome must be non-negative integers with at least one positive count")
    X = pd.DataFrame({"Intercept": np.ones(len(df))})
    terms = [{"term": "Intercept", "variable": None, "level": None,
              "reference": None, "term_type": "intercept"}]
    actual_refs = {}
    for c in covariates:
        if c in categorical:
            values = df[c].astype(str)
            levels = sorted(values.unique())
            if len(levels) < 2:
                raise ValueError(f"Categorical predictor {c!r} has only one level")
            ref = str(refs[c]) if c in refs else levels[0]
            if ref not in levels:
                raise ValueError(f"Reference {ref!r} absent in complete cases for {c!r}")
            actual_refs[c] = ref
            for level in levels:
                if level == ref:
                    continue
                key = f"x{len(terms)}"
                X[key] = (values == level).astype(float)
                terms.append({"term": f"{c}={level}", "variable": c, "level": level,
                              "reference": ref, "term_type": "coefficient"})
        else:
            X[f"x{len(terms)}"] = df[c]
            terms.append({"term": c, "variable": c, "level": None,
                          "reference": None, "term_type": "coefficient"})
    if len(X) <= X.shape[1]:
        raise ValueError("Observations must exceed the number of design columns")
    if np.linalg.matrix_rank(X.to_numpy()) != X.shape[1]:
        raise ValueError("Rank-deficient design: constant or collinear predictors")
    families = {"gaussian": sm.families.Gaussian, "binomial": sm.families.Binomial,
                "poisson": sm.families.Poisson}
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = sm.GLM(y, X, family=families[family]()).fit(maxiter=max_iter, tol=tolerance)
        if family == "binomial" and any(issubclass(w.category, PerfectSeparationWarning) for w in caught):
            raise ValueError("Perfect separation: finite binomial estimates cannot be reported")
        if not result.converged:
            raise ValueError("GLM did not converge; estimates are not reportable")
        ci = np.asarray(result.conf_int(alpha=0.05))
        values = np.column_stack([result.params, result.bse, result.tvalues, result.pvalues, ci])
        if not np.isfinite(values).all() or (result.bse <= 0).any():
            raise ValueError("Non-finite or degenerate coefficient inference")
    except (ValueError, np.linalg.LinAlgError, FloatingPointError) as exc:
        raise ValueError(f"GLM fit failed: {exc}") from exc
    rows = []
    for i, term in enumerate(terms):
        coef, se, z, p, low, high = values[i]
        effect = np.array([coef, low, high])
        if family != "gaussian":
            with np.errstate(over="ignore"):
                effect = np.exp(effect)
        if not np.isfinite(effect).all():
            raise ValueError("Effect or confidence interval overflow; unstable fit")
        effect_type = {"gaussian": "mean_difference", "binomial": "odds_ratio",
                       "poisson": "count_ratio"}[family]
        if i == 0:
            effect_type = {"gaussian": "baseline_mean", "binomial": "baseline_odds",
                           "poisson": "baseline_count"}[family]
        rows.append(dict(term, coef=float(coef), se=float(se), z=float(z), p=float(p),
                         coef_lower95=float(low), coef_upper95=float(high),
                         estimate=float(effect[0]), lower95=float(effect[1]),
                         upper95=float(effect[2]), estimate_type=effect_type))
    dispersion = float(result.pearson_chi2 / result.df_resid)
    notes = list(dict.fromkeys(str(w.message) for w in caught))
    if family == "poisson" and dispersion > 1.5:
        notes.append("Possible overdispersion: model-based Poisson intervals may be too narrow; 1.5 is a heuristic, not a test.")
    if np.linalg.cond(X) > 1e8:
        notes.append("Ill-conditioned design: rescale predictors and inspect collinearity.")
    diagnostics = dict(family=family, link={"gaussian": "identity", "binomial": "logit", "poisson": "log"}[family],
                       n_input=len(data), n_used=len(df), n_dropped=int(incomplete.sum()),
                       n_parameters=X.shape[1], df_resid=float(result.df_resid),
                       converged=bool(result.converged), deviance=float(result.deviance),
                       pearson_dispersion=dispersion, aic=float(result.aic),
                       reference_levels=actual_refs, missing=missing, warnings=notes,
                       covariance="nonrobust", confidence_level=0.95)
    for key in ("deviance", "pearson_dispersion", "aic"):
        if not np.isfinite(diagnostics[key]):
            diagnostics[key] = None
            notes.append(f"{key} is non-finite and was stored as null")
    return GLMResult(pd.DataFrame(rows), diagnostics)

def run_basic_glm(toolbox, outcome_column: str, covariates: list[str],
                  family: str = "gaussian", categorical=None, reference_levels=None,
                  missing: str = "raise", max_iter: int = 100, tolerance: float = 1e-8,
                  where: str = "", label: str = "", source: str = "seer") -> str:
    """Adapter: DuckDB source → complete coefficient relation + deliverable.

    where is trusted local SQL, as in the existing tools; not a security sandbox.
    The explicit 100,000 row cap fails instead of silently truncating the cohort.
    """
    from .tool_sample import _q
    import json

    name = label.strip() or f"basic_glm_{toolbox._n + 1}"
    if name == source:
        return "Error: label must differ from source"
    try:
        if not isinstance(covariates, list):
            raise ValueError("covariates must be a list")
        cols = list(dict.fromkeys([outcome_column] + covariates))
        query = f"SELECT {', '.join(_q(c) for c in cols)} FROM {_q(source)}"
        if where:
            query += f" WHERE ({where})"
        df = toolbox.con.execute(query + " LIMIT 100001").fetchdf()
        if len(df) > 100000:
            raise ValueError("Cohort exceeds 100000 rows; narrow where explicitly")
        result = fit_glm(df, outcome_column, covariates, family, categorical,
                         reference_levels, missing, max_iter, tolerance)
        toolbox._materialize_output(name, result.coefficients)
        toolbox._register_deliverable(name, result.coefficients, len(result.coefficients),
                                      title=f"Basic GLM ({family})", diagnostics=result.diagnostics)
        return "GLM completed: " + json.dumps(result.diagnostics, ensure_ascii=False, allow_nan=False)
    except Exception as exc:
        return f"Error: basic_glm: {exc}" 
