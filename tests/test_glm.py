import json

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from examples.run_glm import sample_data
from tool_sample.glm import fit_glm
from tool_sample.tool_desc import get_tool
from tool_sample.tool_sample import SeerToolbox, run_analysis_step, get_output_schema


@pytest.mark.parametrize("family,outcome,constructor", [
    ("gaussian", "continuous", sm.families.Gaussian),
    ("binomial", "binary", sm.families.Binomial),
    ("poisson", "count", sm.families.Poisson),
])
def test_reference_fit(family, outcome, constructor):
    df = sample_data()
    result = fit_glm(df, outcome, ["x", "group"], family, ["group"], {"group": "control"})
    design = np.column_stack([np.ones(len(df)), df.x, (df.group == "treated").astype(float)])
    expected = sm.GLM(df[outcome], design, family=constructor()).fit()
    np.testing.assert_allclose(result.coefficients.coef, expected.params, atol=1e-8)
    np.testing.assert_allclose(result.coefficients.se, expected.bse, atol=1e-8)
    np.testing.assert_allclose(result.coefficients[["coef_lower95", "coef_upper95"]], expected.conf_int(), atol=1e-8)
    if family == "gaussian":
        np.testing.assert_allclose(result.coefficients.coef, np.linalg.lstsq(design, df[outcome], rcond=None)[0])
    assert result.diagnostics["n_used"] == 300
    assert result.coefficients.iloc[0].estimate_type.startswith("baseline_")
    json.dumps(result.diagnostics, allow_nan=False)


def test_missing_category_dropped_before_encoding():
    df = sample_data()
    df.loc[0, "group"] = None
    with pytest.raises(ValueError, match="Missing values"):
        fit_glm(df, "continuous", ["group"], categorical=["group"])
    result = fit_glm(df, "continuous", ["group"], categorical=["group"], missing="drop")
    assert result.diagnostics["n_used"] == 299
    assert result.diagnostics["n_dropped"] == 1


@pytest.mark.parametrize("family,y", [("binomial", [0, 2]*20), ("binomial", [1]*40),
    ("poisson", [-1, 2]*20), ("poisson", [0.5, 2]*20), ("poisson", [0]*40)])
def test_invalid_outcome(family, y):
    with pytest.raises(ValueError):
        fit_glm(pd.DataFrame({"y": y, "x": np.arange(len(y))}), "y", ["x"], family)


@pytest.mark.parametrize("case", ["empty", "infinity", "collinear", "constant", "reference", "string_covariates", "wrong_family", "small", "bad_numeric", "outcome_leak", "bad_iterations"])
def test_invalid_inputs(case):
    df = sample_data()
    kwargs = dict(outcome_column="continuous", covariates=["x"])
    if case == "empty": df = df.iloc[:0]
    if case == "infinity": df.loc[0, "x"] = np.inf
    if case == "collinear":
        df["twice"] = 2*df.x
        kwargs["covariates"] = ["x", "twice"]
    if case == "constant": df["x"] = 1
    if case == "reference": kwargs.update(covariates=["group"], categorical=["group"], reference_levels={"group": "absent"})
    if case == "string_covariates": kwargs["covariates"] = "x"
    if case == "wrong_family": kwargs["family"] = "gamma"
    if case == "small": df = df.iloc[:2]
    if case == "bad_numeric": kwargs["covariates"] = ["group"]
    if case == "outcome_leak": kwargs["covariates"] = ["continuous"]
    if case == "bad_iterations": kwargs["max_iter"] = 0
    with pytest.raises(ValueError): fit_glm(df, **kwargs)


def test_separation_and_nonconvergence():
    df = pd.DataFrame({"x": np.arange(-20, 20), "y": [0]*20+[1]*20})
    with pytest.raises(ValueError, match="separation|converge"):
        fit_glm(df, "y", ["x"], "binomial")
    with pytest.raises(ValueError, match="converge"):
        fit_glm(sample_data(), "binary", ["x"], "binomial", max_iter=1)


def test_pipeline_and_registry(tmp_path):
    path = tmp_path / "sample.parquet"
    sample_data().to_parquet(path, index=False)
    tb = SeerToolbox(str(path))
    assert get_tool("basic_glm")
    assert get_output_schema("basic_glm")["columns"] == get_tool("basic_glm")["output_schema"]["columns"]
    assert any(s["name"] == "basic_glm" for s in tb.specs())
    assert tb.run("basic_glm", {"outcome_column": "continuous", "covariates": ["x"]}).startswith("GLM completed")
    result = run_analysis_step(str(path), {"op": "basic_glm", "output": "glm_result", "inputs": ["seer"],
        "params": {"outcome_column": "count", "covariates": ["x"], "family": "poisson"}})
    assert result["error"] is None
    assert result["row_count"] == 2
    assert set(result["columns"]) == {c["name"] for c in get_output_schema("basic_glm")["columns"]}
    assert result["deliverable"]["diagnostics"]["n_used"] == 300
    assert tb.con.execute("select count(*) from glm_result").fetchone()[0] == 2
    assert tb.basic_glm("nonexistent", ["x"]).startswith("Error:")
    assert tb.basic_glm("continuous", ["x"], where="1=0").startswith("Error:")


def test_no_silent_truncation(tmp_path):
    path = tmp_path / "large.parquet"
    pd.DataFrame({"x": np.arange(100001), "y": np.arange(100001)}).to_parquet(path)
    tb = SeerToolbox(str(path))
    assert "exceeds 100000" in tb.basic_glm("y", ["x"])
    assert not tb.deliverables
