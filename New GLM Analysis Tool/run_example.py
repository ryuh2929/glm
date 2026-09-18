"""python run_example.py: 합성 CSV 생성 및 세 분포 실행. 외부 데이터 불필요."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from glm import glm_regression


def make_sample_data():
    """임상 근거가 없는 합성 자료 300행. income의 단위는 임의 단위."""
    rng = np.random.default_rng(20260918)
    n = 300
    age = rng.integers(20, 71, n)
    income = rng.integers(2000, 8001, n)
    smoker = rng.binomial(1, 0.3, n)
    probability = 1 / (1 + np.exp(-(-1 + 0.03 * (age - 45) + 0.7 * smoker)))
    return pd.DataFrame({
        "age": age, "income": income, "smoker": smoker,
        "disease": rng.binomial(1, probability),
        "visit_count": rng.poisson(np.exp(0.5 + 0.015 * (age - 45) + 0.3 * smoker)),
        "score": 70 + 0.1 * (age - 45) + 0.002 * (income - 5000) + rng.normal(0, 5, n),
    })


def main():
    folder = Path(__file__).resolve().parent
    make_sample_data().to_csv(folder / "sample_data.csv", index=False)
    data = pd.read_csv(folder / "sample_data.csv")
    output = folder / "sample_output"
    output.mkdir(exist_ok=True)
    cases = [
        ("gaussian", "score", ["age", "income"]),
        ("binomial", "disease", ["age", "smoker"]),
        ("poisson", "visit_count", ["age", "smoker"]),
    ]
    for family, outcome, covariates in cases:
        result = glm_regression(data, outcome, covariates, family)
        result["coefficients"].to_csv(output / f"{family}_coefficients.csv", index=False)
        (output / f"{family}_summary.json").write_text(
            json.dumps(result["summary"], indent=2, allow_nan=False), encoding="utf-8")
        print(f"\n{family}: {result['summary']}")
        print(result["coefficients"].to_string(index=False))


if __name__ == "__main__":
    main()
