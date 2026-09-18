"""Executable evidence of current source defects, not desired behavior.

These tests document the original behavior and should be revised when it is fixed.
"""
import inspect

import numpy as np
import pandas as pd

from tool_sample.tool_desc import get_tool
from tool_sample.tool_sample import SeerToolbox, _design_matrix, _df_to_deliverable


def test_categorical_missing_is_encoded_like_reference():
    data = pd.DataFrame({"x0": ["A", "B", None]})
    matrix, _ = _design_matrix(data, ["x0"], {"x0": "group"})
    np.testing.assert_array_equal(matrix.iloc[0], matrix.iloc[2])
    assert not matrix.iloc[2].isna().any()


def test_preview_truncation_flag_is_incorrect():
    payload = _df_to_deliverable("result", pd.DataFrame({"x": range(300)}), 300)
    assert len(payload["preview"]) == 200
    assert payload["row_count"] == 300
    assert payload["truncated"] is False  # confirmed original defect


def test_table1_defaults_disagree_with_catalog():
    signature = inspect.signature(SeerToolbox.table1)
    for name in ("pval", "smd", "overall"):
        assert signature.parameters[name].default is True
        spec = next(p for p in get_tool("table1")["param_specs"] if p["name"] == name)
        assert "Default false" in spec["description"]


def test_mode_imputation_actually_uses_numeric_median(tmp_path, monkeypatch):
    path = tmp_path / "missing.parquet"
    pd.DataFrame({"x": [1., 1., 2., 3., 100., np.nan]}).to_parquet(path)
    tb = SeerToolbox(str(path))
    # Storage is outside this test: the original sample lacks its S3 utility.
    monkeypatch.setattr(tb, "_export_parquet", lambda name: None)
    tb.impute_missing(columns=["x"], method="mode", label="imputed")
    values = tb.con.execute("select x from imputed").fetchnumpy()["x"]
    assert np.count_nonzero(values == 2.) == 2  # filled median=2, not mode=1
    assert tb.deliverables[-1]["preview"][0]["method"] == "mode"
