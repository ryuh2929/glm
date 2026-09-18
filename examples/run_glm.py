"""Run from repository root: python -m examples.run_glm."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from tool_sample.glm import fit_glm
from tool_sample.tool_sample import run_analysis_step


def sample_data():
    rng = np.random.default_rng(20260918)
    n = 300
    x = rng.normal(size=n)
    group = rng.choice(["control", "treated"], n)
    t = (group == "treated").astype(float)
    return pd.DataFrame({
        "subject_id": np.arange(1, n + 1), "x": x, "group": group,
        "continuous": 2 + 0.8*x + 0.5*t + rng.normal(size=n),
        "binary": rng.binomial(1, 1/(1+np.exp(-(-0.4+0.8*x+0.5*t)))),
        "count": rng.poisson(np.exp(0.2+0.3*x+0.4*t)),
    })


def main():
    root = Path(__file__).resolve().parent
    output = root / "output"
    output.mkdir(exist_ok=True)
    data = sample_data()
    data.to_csv(root / "sample_data.csv", index=False)
    path = root / "sample_data.parquet"
    data.to_parquet(path, index=False)
    for family, outcome in [("gaussian", "continuous"), ("binomial", "binary"), ("poisson", "count")]:
        params = dict(outcome_column=outcome, covariates=["x", "group"], family=family,
                      categorical=["group"], reference_levels={"group": "control"})
        fitted = fit_glm(data, **params)
        fitted.coefficients.to_csv(output / f"{family}_coefficients.csv", index=False)
        (output / f"{family}_diagnostics.json").write_text(
            json.dumps(fitted.diagnostics, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        payload = run_analysis_step(str(path), {
            "op": "basic_glm", "name": f"demo_{family}", "output": f"demo_{family}",
            "inputs": ["seer"], "params": params,
        })
        if payload["error"]:
            raise RuntimeError(payload["error"])
        (output / f"{family}_pipeline.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        print(f"{family}: n={fitted.diagnostics['n_used']}, terms={len(fitted.coefficients)}, converged=True")


if __name__ == "__main__":
    main()
