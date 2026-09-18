"""표준 unittest로 수치 일치·입력 실패·분리·미수렴을 확인한다."""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import statsmodels.api as sm

from glm import glm_regression
from run_example import make_sample_data


class GLMTests(unittest.TestCase):
    def test_three_families_against_reference(self):
        data = make_sample_data()
        for family, outcome, covs, ctor in [
            ("gaussian", "score", ["age", "income"], sm.families.Gaussian),
            ("binomial", "disease", ["age", "smoker"], sm.families.Binomial),
            ("poisson", "visit_count", ["age", "smoker"], sm.families.Poisson),
        ]:
            with self.subTest(family=family):
                result = glm_regression(data, outcome, covs, family)
                X = sm.add_constant(data[covs].astype(float))
                expected = sm.GLM(data[outcome], X, family=ctor()).fit()
                table = result["coefficients"]
                np.testing.assert_allclose(table.coef, expected.params)
                np.testing.assert_allclose(table.se, expected.bse)
                np.testing.assert_allclose(table[["ci_lower", "ci_upper"]], expected.conf_int())
                self.assertEqual(result["summary"]["n_obs"], 300)
                self.assertEqual(list(table.columns), ["covariate", "coef", "se", "z", "p", "ci_lower", "ci_upper"])
                if family == "gaussian":
                    np.testing.assert_allclose(table.coef, np.linalg.lstsq(X, data[outcome], rcond=None)[0])

    def test_invalid_parameters(self):
        data = make_sample_data()
        for kwargs in [
            {"outcome_column": "absent", "covariates": ["age"]},
            {"outcome_column": "score", "covariates": ["absent"]},
            {"outcome_column": "score", "covariates": ["score"]},
            {"outcome_column": "score", "covariates": ["age", "age"]},
            {"outcome_column": "score", "covariates": []},
            {"outcome_column": "score", "covariates": "age"},
            {"outcome_column": "score", "covariates": ["age"], "family": "gamma"},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                glm_regression(data, **kwargs)

    def test_invalid_data(self):
        base = make_sample_data()
        missing = base.astype({"age": float})
        missing.loc[0, "age"] = np.nan
        infinite = base.astype({"age": float})
        infinite.loc[0, "age"] = np.inf
        text = base.copy()
        text["age"] = "category"
        constant = base.copy()
        constant["age"] = 1
        duplicate = base.copy()
        duplicate["income"] = duplicate.age * 2
        for data in [base.iloc[:0], base.iloc[:2], missing, infinite, text, constant, duplicate]:
            with self.subTest(shape=data.shape), self.assertRaises(ValueError):
                glm_regression(data, "score", ["age", "income"])

    def test_outcome_domains(self):
        for family, values in [
            ("binomial", [0, 2] * 10), ("binomial", [1] * 20),
            ("poisson", [-1, 1] * 10), ("poisson", [0.5, 2] * 10),
            ("poisson", [0] * 20),
        ]:
            with self.subTest(family=family, values=values), self.assertRaises(ValueError):
                glm_regression(pd.DataFrame({"x": range(20), "y": values}), "y", ["x"], family)

    def test_separation(self):
        data = pd.DataFrame({"x": range(-20, 20), "y": [0] * 20 + [1] * 20})
        with self.assertRaisesRegex(ValueError, "분리|수렴"):
            glm_regression(data, "y", ["x"], "binomial")

    def test_fit_failure_and_nonconvergence(self):
        # 통계 라이브러리의 실패가 사용자 오류 메시지로 전달되는지 검사.
        data = make_sample_data()
        with patch("glm.sm.GLM") as model:
            model.return_value.fit.side_effect = ValueError("test fit failure")
            with self.assertRaisesRegex(ValueError, "적합에 실패"):
                glm_regression(data, "score", ["age"])
        with patch("glm.sm.GLM") as model:
            model.return_value.fit.return_value.converged = False
            with self.assertRaisesRegex(ValueError, "수렴하지"):
                glm_regression(data, "score", ["age"])

    def test_numeric_strings_unused_missing_and_no_mutation(self):
        data = make_sample_data()
        data["unused"] = np.nan
        data["age"] = data.age.astype(str)
        original = data.copy(deep=True)
        result = glm_regression(data, "score", ["age", "income"])
        self.assertEqual(result["summary"]["n_obs"], 300)
        pd.testing.assert_frame_equal(data, original)


if __name__ == "__main__":
    unittest.main()
