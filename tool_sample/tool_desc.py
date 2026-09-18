"""Hand-authored tool catalog for the hub in ``tool_hub.py``.

Biomni-style: a single ``description = [...]`` list, one entry per hub tool, with
its category, param signature, output type, a one-line summary, and an
``output_schema`` contract (columns the hub actually writes onto the node's
``outputs`` edge). This is the CATALOG the pipeline decomposer reads — the
planner binds each matrix node's ``tool`` to one ``name`` below and grounds
``inputs``/``outputs`` in the tool's declared IO. Keep it in sync with the ops
the hub actually runs.

Rendered for prompts via :func:`render_tool_catalog`.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

# Category → one-line description (mirrors tool_hub.TOOL_CATEGORIES).
TOOL_CATEGORY_DESC: Dict[str, str] = {
    "descriptive": "Baseline-characteristics \"Table 1\" with per-group p-values / SMD (tableone), "
    "CONSORT attrition flow and data-quality (missingness / temporal order) reports.",
    "statistics": "Confounding adjustment (binary / multi-arm propensity-score matching, "
    "IPTW / overlap weighting, ATT weighting) + causal effect estimation by IPW / "
    "g-computation / matching / doubly-robust AIPW, with method and specification sweeps, for "
    "the effect in the TREATED (att_*) or in the whole cohort / overlap population (ate_*), "
    "plus covariate balance, "
    "unmeasured-confounding bias analysis, imputation + hypothesis tests / regressions.",
    "survival": "Time-to-event analysis (Kaplan-Meier, log-rank, Cox PH, time-varying Cox, "
    "IPTW-adjusted KM / RMST, competing-risk CIF).",
    "modeling": "Three layers. (A) Model tools FIT once and write a scored dataset "
    "(`predicted_probability`). (B) Evaluation tools READ that column only — they "
    "never fit. (C) ml_cv_performance / ml_compare refit each fold from a model key.",
}

_CATEGORY_ORDER = ["descriptive", "statistics", "survival", "modeling"]


# User-facing Tool Hub copy. Kept separate from each op's terse ``summary``:
# ``summary`` is also sent to the planner as an execution contract, whereas this
# Markdown is returned only by ``GET /tools/{name}`` and rendered in the UI.
# Source copy: ``io_toolhub_catalog_en.md``.
TOOL_HUB_INTRO: Dict[str, str] = {
    'attrition_table': '## Attrition Table\n\nApplies the eligibility criteria in sequence and reports the number of patients remaining and excluded at each step. Produces the participant-flow evidence that observational study reporting guidelines expect, and makes it obvious when a single criterion is responsible for most of the sample loss.\n*Reference:* [STROBE Statement — reporting of observational studies](https://www.strobe-statement.org/)',
    'data_quality': '## Data Quality Check\n\nProfiles the dataset for the quality problems that most often invalidate an analysis: missingness by variable, implausible or out-of-range values, unexpected category counts, and temporal inconsistencies such as events dated before diagnosis. Results are organized along the conformance / completeness / plausibility axes of the Kahn framework so that findings can be reported in standard terms.\n*Reference:* Kahn MG, et al. A Harmonized Data Quality Assessment Terminology and Framework for the Secondary Use of Electronic Health Record Data. *eGEMs* 2016;4(1):1244. [doi:10.13063/2327-9214.1244](https://doi.org/10.13063/2327-9214.1244) · [OHDSI Data Quality Dashboard](https://ohdsi.github.io/DataQualityDashboard/)',
    'table1': '## Table 1\n\nSummarizes baseline characteristics of the cohort, overall and by group, using means with standard deviations, medians with interquartile ranges, or counts with percentages as appropriate to each variable type. Optionally reports standardized mean differences and group-comparison p-values. Standardized differences are preferred over p-values when the purpose is to assess balance rather than to test a hypothesis.\n*Reference:* [tableone documentation](https://tableone.readthedocs.io/en/latest/) · Pollard TJ, et al. *JAMIA Open* 2018;1(1):26–31. [doi:10.1093/jamiaopen/ooy012](https://doi.org/10.1093/jamiaopen/ooy012)',
    'ate_estimate': '## ATE Estimate\n\nEstimates the average treatment effect across the entire study population, with a confidence interval, after adjusting for measured confounders. Supports weighting, outcome-regression, and doubly robust estimation depending on configuration. Validity rests on no unmeasured confounding, positivity, and correct specification of at least one of the treatment or outcome models.\n*Reference:* [zEpid — Time-Fixed Exposure](https://zepid.readthedocs.io/en/stable/Time-Fixed%20Exposure.html) · [zEpid — `AIPTW`](https://zepid.readthedocs.io/en/latest/Reference/generated/zepid.causal.doublyrobust.AIPW.AIPTW.html)',
    'ate_estimate_multi': '## ATE Multi-Method\n\nEstimates the ATE in the same cohort using several estimators — for example IPTW, g-computation, AIPW, and TMLE — and presents the results side by side. Convergence across estimators is evidence that the finding is not an artifact of one modeling choice; divergence localizes which model is doing the work.\n*Reference:* [zEpid — Causal inference methods](https://github.com/CamDavidsonPilon/zepid/blob/master/docs/Causal.rst) · [zEpid — `TMLE`](https://zepid.readthedocs.io/en/stable/Reference/generated/zepid.causal.doublyrobust.TMLE.TMLE.html)',
    'ate_sensitivity': '## ATE Sensitivity\n\nRe-estimates the ATE while varying one analytic decision at a time — covariate set, weight truncation, cohort definition, estimator — and reports how much the estimate moves. Distinguishes findings that are stable across defensible specifications from those that depend on a single choice.\n*Reference:* [zEpid — Time-Fixed Exposure](https://zepid.readthedocs.io/en/stable/Time-Fixed%20Exposure.html)',
    'ate_weight': '## ATE Weights\n\nGenerates propensity-based weights targeting the full-population estimand, including stabilized inverse-probability weights and overlap weights. Overlap weights bound the influence of patients with extreme propensity scores and are the safer default when the two groups are poorly matched at the tails. Returns the weight column plus the propensity-score distribution for inspection.\n*Reference:* [zEpid — `IPTW`](https://zepid.readthedocs.io/en/latest/Reference/generated/zepid.causal.ipw.IPTW.IPTW.html)',
    'att_estimate': '## ATT Estimate\n\nEstimates the average treatment effect among the treated — the effect of treatment in the patients who actually received it — with a confidence interval. This is usually the clinically relevant estimand when the question is whether the treatment helped the people it was given to, rather than whether it should be given to everyone.\n*Reference:* [zEpid — Time-Fixed Exposure](https://zepid.readthedocs.io/en/stable/Time-Fixed%20Exposure.html)',
    'att_estimate_multi': '## ATT Multi-Method\n\nEstimates the ATT with multiple methods — matching, ATT weighting, and doubly robust estimation — on the same cohort and compares the results. Differences between matched and weighted ATT estimates typically reflect who was dropped by matching, which the output reports alongside the estimates.\n*Reference:* [zEpid — Causal inference methods](https://github.com/CamDavidsonPilon/zepid/blob/master/docs/Causal.rst)',
    'att_sensitivity': '## ATT Sensitivity\n\nVaries cohort definition, covariate set, propensity-score trimming, caliper, and estimator, and reports the resulting range of ATT estimates. Designed to be reported as a specification curve rather than a single robustness claim.\n*Reference:* [zEpid — Time-Fixed Exposure](https://zepid.readthedocs.io/en/stable/Time-Fixed%20Exposure.html)',
    'att_weight': '## ATT Weights\n\nGenerates propensity-score weights that reweight control patients to resemble the treated population, so that the treated group is preserved intact and the comparison targets the ATT. Returns weights, effective sample size, and the propensity-score overlap needed to judge whether the reweighting is credible.\n*Reference:* [zEpid — `IPTW`](https://zepid.readthedocs.io/en/latest/Reference/generated/zepid.causal.ipw.IPTW.IPTW.html)',
    'bias_sensitivity': '## Unmeasured Confounding Sensitivity\n\nQuantifies how strong an unmeasured confounder would have to be, in its association with both treatment and outcome, to move the observed effect to the null or to any specified threshold. Reports the result as a bias-factor contour rather than a single pass/fail verdict, so the plausibility judgment stays with the investigator.\n*Reference:* VanderWeele TJ, Ding P. *Ann Intern Med* 2017;167:268–274 · [Linden A, Mathur MB, VanderWeele TJ. *Stata J* 2020](https://doi.org/10.1177/1536867X20909696) · [CRAN — `EValue`](https://cran.r-project.org/package=EValue)',
    'covariate_balance': '## Covariate Balance\n\nCompares the distribution of each covariate between treatment groups using standardized mean differences, variance ratios, and empirical CDF distances. Standardized differences below 0.1 are the conventional balance threshold; unlike p-values, they do not depend on sample size. Reports balance before and after adjustment.\n*Reference:* [CRAN — `cobalt`](https://cran.r-project.org/package=cobalt) · [zEpid — `IPTW` diagnostics](https://zepid.readthedocs.io/en/latest/Reference/generated/zepid.causal.ipw.IPTW.IPTW.html)',
    'covariate_balance_multi': '## Covariate Balance Comparison\n\nEvaluates covariate balance across several adjustment strategies at once — unadjusted, matched, IPTW, overlap-weighted — in a single Love plot and table. Used to choose an adjustment approach on balance evidence rather than on which one produced the preferred effect estimate.\n*Reference:* [CRAN — `cobalt`](https://cran.r-project.org/package=cobalt)',
    'evalue': '## E-value\n\nComputes the E-value for a point estimate and for the confidence limit closest to the null: the minimum strength of association, on the risk-ratio scale, that an unmeasured confounder would need with both exposure and outcome to explain away the observed result. Supports risk ratios, rate ratios, odds ratios, hazard ratios, and standardized mean differences. An E-value is a summary of how much confounding would be required, not evidence that such confounding is absent.\n*Reference:* VanderWeele TJ, Ding P. *Ann Intern Med* 2017;167:268–274 · [Linden A, Mathur MB, VanderWeele TJ. *Stata J* 2020](https://doi.org/10.1177/1536867X20909696) · [CRAN — `EValue`](https://cran.r-project.org/package=EValue)',
    'iptw_weight': '## IPTW Weights\n\nFits a propensity-score model and constructs stabilized inverse-probability-of-treatment weights, creating a pseudo-population in which measured confounders are independent of treatment assignment. Because no patient is discarded, the full cohort is retained, but extreme weights can dominate the estimate — the tool reports the weight distribution and supports truncation.\n*Reference:* [zEpid — `IPTW`](https://zepid.readthedocs.io/en/latest/Reference/generated/zepid.causal.ipw.IPTW.IPTW.html)',
    'propensity_score_match': '## Propensity Score Matching\n\nMatches treated and control patients with similar propensity scores, with configurable ratio, caliper, and replacement, to build a comparable cohort for direct comparison. Returns the matched cohort, the number and characteristics of unmatched patients, and post-match balance diagnostics. Patients outside the region of common support are excluded, which changes the population the estimate applies to.\n*Reference:* [CRAN — `MatchIt`](https://cran.r-project.org/package=MatchIt) · [scikit-learn — `NearestNeighbors`](https://scikit-learn.org/stable/modules/generated/sklearn.neighbors.NearestNeighbors.html)',
    'propensity_score_match_multi': '## Multi-Group Propensity Matching\n\nExtends propensity-score matching to three or more treatment groups using generalized propensity scores, producing matched sets that are comparable across all arms simultaneously. Useful for comparing several regimens, at the cost of substantially smaller matched samples than pairwise matching.\n*Reference:* [CRAN — `MatchIt`](https://cran.r-project.org/package=MatchIt)',
    'chi2_contingency': "## Chi-Square Test of Independence\n\nTests whether two categorical variables are associated, reporting the chi-square statistic, degrees of freedom, p-value, expected counts, and Cramér's V as a measure of association strength. Falls back to an exact test when expected cell counts are small, since the chi-square approximation is unreliable there.\n*Reference:* [SciPy — `scipy.stats.chi2_contingency`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.chi2_contingency.html)",
    'glm_regression': '## Generalized Linear Model\n\nFits a generalized linear model with a family and link chosen to match the outcome type: Poisson or negative binomial for counts and rates, gamma for skewed positive outcomes such as cost, Gaussian for continuous outcomes, and log-binomial or Poisson with robust variance for risk ratios. Supports offsets for person-time and returns coefficients, exponentiated effect measures, and confidence intervals.\n*Reference:* [statsmodels — Generalized Linear Models](https://www.statsmodels.org/stable/glm.html)',
    'impute_missing': "## Missing Data Imputation\n\nHandles missing values by single or multiple imputation, including chained-equations (MICE) imputation with pooling of estimates across imputed datasets by Rubin's rules. Reports the missingness pattern first, since the choice between complete-case analysis and imputation depends on whether data are plausibly missing at random.\n*Reference:* [statsmodels — Multiple Imputation (`MICE`)](https://www.statsmodels.org/stable/imputation.html)",
    'logistic_regression': '## Logistic Regression\n\nModels a binary outcome as a function of multiple clinical variables and reports adjusted odds ratios with 95% confidence intervals and p-values. Intended for association and inference rather than prediction; use the Prediction Models section when the goal is a model that will be scored on new patients. Odds ratios approximate risk ratios only when the outcome is rare.\n*Reference:* [statsmodels — `Logit`](https://www.statsmodels.org/stable/generated/statsmodels.discrete.discrete_model.Logit.html)',
    'mann_whitney_u': '## Mann-Whitney U Test\n\nCompares the distribution of a continuous or ordinal variable between two independent groups without assuming normality, reporting the U statistic, p-value, and an effect-size measure. Appropriate for skewed variables and small samples; it tests stochastic dominance rather than a difference in means.\n*Reference:* [SciPy — `scipy.stats.mannwhitneyu`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.mannwhitneyu.html)',
    'competing_risk_cif': '## Competing Risks Cumulative Incidence\n\nEstimates the cumulative incidence of the event of interest using the Aalen–Johansen estimator when competing events (for example, death from other causes) prevent the event from occurring. Treating competing events as censoring and reporting 1 − Kaplan–Meier overestimates incidence; this tool avoids that error and returns cause-specific curves with confidence intervals.\n*Reference:* [lifelines — `AalenJohansenFitter`](https://lifelines.readthedocs.io/en/latest/fitters/univariate/AalenJohansenFitter.html)',
    'cox_ph': '## Cox Proportional Hazards Model\n\nFits a multivariable Cox model to time-to-event data and reports adjusted hazard ratios with 95% confidence intervals, supporting stratification, robust standard errors, and penalization. The hazard ratio is an average over follow-up; the proportional-hazards assumption should be checked separately before the estimate is interpreted.\n*Reference:* [lifelines — `CoxPHFitter`](https://lifelines.readthedocs.io/en/latest/fitters/regression/CoxPHFitter.html)',
    'cox_ph_assumptions': '## Proportional Hazards Assumption Test\n\nTests the proportional-hazards assumption for each covariate and globally using scaled Schoenfeld residuals, and returns residual-versus-time plots for visual inspection. A violation does not invalidate the analysis outright — it indicates that the effect changes over follow-up and should be modeled with stratification, a time-varying coefficient, or a time-restricted estimate.\n*Reference:* [lifelines — `statistics.proportional_hazard_test`](https://lifelines.readthedocs.io/en/latest/lifelines.statistics.html)',
    'cox_ph_subgroup': '## Subgroup Cox Analysis\n\nEstimates the treatment or exposure hazard ratio separately within each level of a specified clinical subgroup and tests for interaction. Produces the forest plot expected in oncology reporting. Subgroup estimates are underpowered by construction and the interaction test, not the individual p-values, is the appropriate basis for claiming effect modification.\n*Reference:* [lifelines — `CoxPHFitter`](https://lifelines.readthedocs.io/en/latest/fitters/regression/CoxPHFitter.html)',
    'cox_ph_univariate': '## Univariate Cox Analysis\n\nFits a separate Cox model for each candidate variable and reports unadjusted hazard ratios, confidence intervals, and p-values in one table. Conventionally reported alongside the multivariable model. Selecting multivariable covariates purely on univariate p-values is a known source of bias and is not recommended.\n*Reference:* [lifelines — `CoxPHFitter`](https://lifelines.readthedocs.io/en/latest/fitters/regression/CoxPHFitter.html)',
    'cox_time_varying': '## Time-Varying Cox Model\n\nFits a Cox model on start–stop interval data in which covariate values change during follow-up, such as treatment initiation, dose changes, or evolving lab values. This is the standard correction for immortal time bias, which arises when a post-baseline exposure is treated as if it were present from baseline.\n*Reference:* [lifelines — `CoxTimeVaryingFitter`](https://lifelines.readthedocs.io/en/latest/fitters/regression/CoxTimeVaryingFitter.html) · [lifelines — `utils.to_episodic_format`](https://lifelines.readthedocs.io/en/latest/lifelines.utils.html)',
    'iptw_kaplan_meier': '## IPTW-Adjusted Kaplan-Meier\n\nProduces weighted Kaplan–Meier survival curves in which measured baseline confounders have been balanced by inverse-probability-of-treatment weighting, with robust confidence intervals. Gives an adjusted survival curve that can be presented directly, rather than only an adjusted hazard ratio.\n*Reference:* [lifelines — `KaplanMeierFitter`](https://lifelines.readthedocs.io/en/latest/fitters/univariate/KaplanMeierFitter.html) · [zEpid — `IPTW`](https://zepid.readthedocs.io/en/latest/Reference/generated/zepid.causal.ipw.IPTW.IPTW.html)',
    'iptw_survival_metrics': '## IPTW Survival Metrics\n\nAfter IPTW adjustment, reports landmark survival probabilities at specified time points, restricted mean survival time, and median survival, together with absolute differences between groups and their confidence intervals. Absolute measures such as RMST difference remain interpretable when proportional hazards does not hold, unlike the hazard ratio.\n*Reference:* [lifelines — `utils.restricted_mean_survival_time`](https://lifelines.readthedocs.io/en/latest/lifelines.utils.html)',
    'kaplan_meier': '## Kaplan-Meier Estimator\n\nEstimates and plots the survival function over time by group, with confidence bands, at-risk tables, and median survival with confidence intervals. Assumes non-informative censoring, and should not be used for the event of interest when competing events are present.\n*Reference:* [lifelines — `KaplanMeierFitter`](https://lifelines.readthedocs.io/en/latest/fitters/univariate/KaplanMeierFitter.html)',
    'logrank_test': '## Log-Rank Test\n\nTests whether survival distributions differ between two or more groups, with support for stratified and weighted (Gehan–Breslow, Tarone–Ware) variants. Most powerful when hazards are proportional; when curves cross, a non-significant result does not mean the groups are equivalent.\n*Reference:* [lifelines — `statistics.logrank_test`](https://lifelines.readthedocs.io/en/latest/lifelines.statistics.html)',
    'AdaBoostClassifier': '## AdaBoost Classifier\n\nFits an ensemble in which each successive weak learner is trained with greater weight on the observations misclassified by its predecessors, and returns predicted class probabilities. Effective on moderate-sized tabular data but sensitive to label noise and outliers, which it will progressively up-weight.\n*Reference:* [scikit-learn — `AdaBoostClassifier`](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.AdaBoostClassifier.html)',
    'DecisionTreeClassifier': '## Decision Tree Classifier\n\nLearns a hierarchy of threshold rules on clinical variables to classify the outcome, producing a model that can be read and audited directly. Valuable when interpretability matters more than accuracy; single trees are unstable, and small changes in the data can produce a substantially different tree.\n*Reference:* [scikit-learn — `DecisionTreeClassifier`](https://scikit-learn.org/stable/modules/generated/sklearn.tree.DecisionTreeClassifier.html)',
    'ExtraTreeClassifier': '## Extra Tree Classifier\n\nA single decision tree that selects split thresholds at random rather than optimizing them, trading fit for reduced variance and faster training. Primarily used as a component of an Extra Trees ensemble rather than as a standalone clinical model.\n*Reference:* [scikit-learn — `ExtraTreeClassifier`](https://scikit-learn.org/stable/modules/generated/sklearn.tree.ExtraTreeClassifier.html)',
    'ExtraTreesClassifier': '## Extra Trees Classifier\n\nAggregates many extremely randomized trees to produce predicted probabilities and impurity-based variable importances. Often comparable to random forests with lower training cost; impurity-based importances are biased toward high-cardinality variables and should be cross-checked with permutation importance.\n*Reference:* [scikit-learn — `ExtraTreesClassifier`](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.ExtraTreesClassifier.html)',
    'GradientBoostingClassifier': '## Gradient Boosting Classifier\n\nBuilds an additive ensemble in which each tree is fitted to the residual errors of the current model, typically giving strong performance on structured clinical data. Requires tuning of learning rate, tree depth, and number of iterations; without early stopping it overfits readily.\n*Reference:* [scikit-learn — `GradientBoostingClassifier`](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.GradientBoostingClassifier.html)',
    'HistGradientBoostingClassifier': '## Histogram Gradient Boosting Classifier\n\nA histogram-based gradient boosting implementation that bins continuous features before splitting, making it markedly faster on large datasets and able to handle missing values natively. The recommended boosting default for registry-scale cohorts.\n*Reference:* [scikit-learn — `HistGradientBoostingClassifier`](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html)',
    'LinearSVC': '## Linear SVC\n\nFits a linear support vector classifier that separates classes by a maximum-margin hyperplane, scaling well to high-dimensional data such as omics features. Produces decision-function scores rather than calibrated probabilities, so probability calibration is required before risk-based evaluation.\n*Reference:* [scikit-learn — `LinearSVC`](https://scikit-learn.org/stable/modules/generated/sklearn.svm.LinearSVC.html)',
    'LogisticRegression': '## Logistic Regression (Prediction)\n\nFits a regularized logistic regression to produce patient-level predicted probabilities, with L1, L2, or elastic-net penalties. The standard baseline for clinical prediction: well calibrated by default and interpretable through its coefficients. Regularized coefficients are shrunk and should not be read as unbiased association estimates.\n*Reference:* [scikit-learn — `LogisticRegression`](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html)',
    'LogisticRegressionCV': '## Logistic Regression with CV\n\nFits a logistic regression whose regularization strength is selected by internal cross-validation, avoiding a manually chosen penalty. Because tuning happens inside the fit, external evaluation must use data held out from this procedure to avoid optimistic performance.\n*Reference:* [scikit-learn — `LogisticRegressionCV`](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegressionCV.html)',
    'NuSVC': '## Nu-Support Vector Classifier\n\nA support vector classifier parameterized by ν, which directly bounds the fraction of margin errors and support vectors, giving more intuitive control over model complexity than the C parameter. Supports non-linear kernels; training cost grows steeply with sample size.\n*Reference:* [scikit-learn — `NuSVC`](https://scikit-learn.org/stable/modules/generated/sklearn.svm.NuSVC.html)',
    'PassiveAggressiveClassifier': '## Passive Aggressive Classifier\n\nAn online linear classifier that leaves its parameters unchanged on correctly classified examples and updates aggressively on errors. Suited to streaming or incrementally arriving data; it does not produce probability estimates.\n*Reference:* [scikit-learn — `PassiveAggressiveClassifier`](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.PassiveAggressiveClassifier.html)',
    'Perceptron': '## Perceptron\n\nLearns a simple linear decision boundary by incremental updates on misclassified examples. Included mainly as a minimal linear baseline; it has no probabilistic output and converges only when the classes are linearly separable.\n*Reference:* [scikit-learn — `Perceptron`](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Perceptron.html)',
    'RandomForestClassifier': '## Random Forest Classifier\n\nAverages many decision trees grown on bootstrap samples with randomized feature subsets, returning predicted probabilities and variable importances. Robust to non-linearity and interactions with little tuning, which makes it a common first non-linear comparator against logistic regression.\n*Reference:* [scikit-learn — `RandomForestClassifier`](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html)',
    'RidgeClassifier': '## Ridge Classifier\n\nApplies L2-penalized least squares to class labels to learn a stable linear boundary, performing well when predictors are correlated — a common situation with clinical and omics covariates. Fast, but outputs decision scores rather than probabilities.\n*Reference:* [scikit-learn — `RidgeClassifier`](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.RidgeClassifier.html)',
    'RidgeClassifierCV': '## Ridge Classifier with CV\n\nSelects the L2 penalty by efficient built-in cross-validation over a specified grid, then fits the final classifier. Suitable when the penalty strength materially affects performance and a manual search is not warranted.\n*Reference:* [scikit-learn — `RidgeClassifierCV`](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.RidgeClassifierCV.html)',
    'SGDClassifier': '## SGD Classifier\n\nFits linear classifiers — logistic, hinge, or other losses — by stochastic gradient descent, allowing training on datasets too large to hold in memory. Performance depends heavily on feature scaling and learning-rate schedule.\n*Reference:* [scikit-learn — `SGDClassifier`](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.SGDClassifier.html)',
    'SGDOneClassSVM': '## SGD One-Class SVM\n\nLearns the boundary of the normal-data region without outcome labels and flags observations that fall outside it. Used for anomaly and outlier detection — atypical patient profiles, data-entry errors, or distribution shift — not for outcome prediction.\n*Reference:* [scikit-learn — `SGDOneClassSVM`](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.SGDOneClassSVM.html)',
    'SVC': '## Support Vector Classifier\n\nFits a kernel support vector machine, allowing non-linear decision boundaries through RBF, polynomial, or custom kernels, with optional Platt-scaled probability output. Powerful on small to moderate cohorts with complex structure; training scales poorly beyond roughly tens of thousands of patients, and probability estimates require the additional calibration step.\n*Reference:* [scikit-learn — `SVC`](https://scikit-learn.org/stable/modules/generated/sklearn.svm.SVC.html)',
    'ml_calibration_curve': '## Calibration Curve\n\nPlots observed event rates against predicted probabilities across risk strata and reports calibration slope, intercept, and Brier score. A model can discriminate well and still be badly calibrated; calibration is what determines whether a predicted probability can be quoted to a patient. Reads stored predictions and does not refit.\n*Reference:* [scikit-learn — `calibration_curve`](https://scikit-learn.org/stable/modules/generated/sklearn.calibration.calibration_curve.html) · [scikit-learn — Probability calibration](https://scikit-learn.org/stable/modules/calibration.html)',
    'ml_classifier_performance': '## Classifier Performance\n\nComputes discrimination and accuracy metrics from stored predictions: AUC, Brier score, sensitivity, specificity, PPV, NPV, F1, and the confusion matrix at a specified threshold. PPV and NPV depend on outcome prevalence and are not transportable across cohorts with different event rates. Reads stored predictions and does not refit.\n*Reference:* [scikit-learn — Metrics and scoring](https://scikit-learn.org/stable/modules/model_evaluation.html)',
    'ml_compare': '## Model Comparison\n\nEvaluates several candidate models on the same data under identical cross-validation folds and preprocessing, and reports performance metrics side by side with fold-level variability. Because it refits each model within the CV loop, results are independent of any predictions already stored on the dataset.\n*Reference:* [scikit-learn — Cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html)',
    'ml_cv_performance': '## Cross-Validated Performance\n\nRuns k-fold or repeated stratified cross-validation and reports out-of-fold discrimination and calibration, giving an internally validated estimate of performance that corrects for the optimism of resubstitution. Any feature selection or hyperparameter tuning must occur inside the folds, which this tool enforces.\n*Reference:* [scikit-learn — `cross_val_predict`](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.cross_val_predict.html) · [scikit-learn — Cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html)',
    'ml_decision_curve': '## Decision Curve Analysis\n\nComputes net benefit across a range of threshold probabilities and compares the model against treat-all and treat-none strategies. Answers whether using the model to guide a decision would do more good than harm at clinically plausible thresholds — a question that AUC does not address. Reads stored predictions and does not refit.\n*Reference:* [dcurves (Python)](https://github.com/MSKCC-Epi-Bio/dcurves) · Vickers AJ, Elkin EB. *Med Decis Making* 2006;26(6):565–574. [doi:10.1177/0272989X06295361](https://doi.org/10.1177/0272989X06295361)',
    'ml_reclassification': '## Reclassification Analysis\n\nQuantifies how much a new model improves risk classification relative to a reference model using the integrated discrimination improvement (IDI) and the net reclassification improvement (NRI), with category-based NRI computed against clinically defined risk strata. Category-free NRI is known to be sensitive to model miscalibration and is reported with that caveat. Reads stored predictions and does not refit.\n*Reference:* Pencina MJ, et al. *Stat Med* 2008;27(2):157–172. [doi:10.1002/sim.2929](https://doi.org/10.1002/sim.2929) · [CRAN — `nricens`](https://cran.r-project.org/package=nricens)',
    'ml_roc_curve': '## ROC Curve\n\nPlots the receiver operating characteristic curve, reports AUC with a confidence interval, and lists candidate cutoffs including the Youden index and threshold values meeting a specified sensitivity or specificity target. AUC is prevalence-independent, which is a strength for comparing discrimination and a limitation for judging clinical usefulness. Reads stored predictions and does not refit.\n*Reference:* [scikit-learn — `roc_curve`](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.roc_curve.html) · [scikit-learn — `roc_auc_score`](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.roc_auc_score.html)',
    'ml_train_test_split': '## Train/Test Split\n\nPartitions the cohort into development and evaluation sets, with stratification on the outcome and optional grouping to keep records from the same patient or institution in a single partition. Establishes the independence required for honest performance estimation; a random split gives internal validation only, not external validity.\n*Reference:* [scikit-learn — `train_test_split`](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.train_test_split.html)',
    'predict_breast_os': '## PREDICT Breast\n\nApplies the published PREDICT Breast prognostic model to compute overall survival probabilities at 5, 10, and 15 years and the incremental survival benefit attributable to each adjuvant therapy option. This tool applies fixed published coefficients — it does not fit a model to the current cohort — so the model version is recorded with every result for provenance.\n*Reference:* [PREDICT Breast tool](https://breast.predict.nhs.uk/tool) · Candido dos Reis FJ, et al. (v2) *Breast Cancer Res* 2017;19:58. [doi:10.1186/s13058-017-0852-3](https://doi.org/10.1186/s13058-017-0852-3) · [v3.0](https://doi.org/10.1038/s41523-024-00612-y)\n*Version note:* the currently pinned version is **v2.1**. PREDICT Breast v3.0/v3.1 (2023–2024) and v4.0 (2025) have since been published and are better calibrated for contemporary cohorts. See the review note at the end of this document.',

}


def _p(name: str, ptype: str, required: bool, description: str) -> Dict[str, Any]:
    """One PARAMETER spec (name · type · required · description) for a tool entry."""
    return {"name": name, "type": ptype, "required": required, "description": description}


def _t(
    name: str,
    category: str,
    output_type: str,
    params: str,
    summary: str,
    params_detail: Optional[List[Dict[str, Any]]] = None,
    output_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    spec = {
        "name": name,
        "category": category,
        "output_type": output_type,  # dataset | table | figure
        "params": params,
        "summary": summary,
        # Screen-only long-form Markdown. It is intentionally absent from
        # ``render_tool_catalog`` so user-facing prose cannot alter planner binding.
        "toolhub_intro": TOOL_HUB_INTRO.get(name, ""),
        # Per-parameter specs (biomni-style, like tool_desc/sklearn.py) so the
        # plan / tool-params author sees each param's meaning — especially the
        # value-list semantics (which values mark the treated/positive/event arm).
        "param_specs": params_detail or [],
    }
    if output_schema:
        spec["output_schema"] = output_schema
    return spec


def _c(name: str, typ: str, desc: str = "", *, when: str = "") -> Dict[str, Any]:
    """One OUTPUT column in the parquet / DuckDB view the node produces."""
    col: Dict[str, Any] = {"name": name, "type": typ}
    if desc:
        col["description"] = desc
    if when:
        col["when"] = when
    return col


def _os(
    *,
    format: str = "parquet",
    cardinality: str = "rows",
    inherits: bool = False,
    derived: bool = False,
    columns: Optional[List[Dict[str, Any]]] = None,
    note: str = "",
    wire: str = "",
    side_deliverable: Optional[Dict[str, Any]] = None,
    consumes: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Output-schema contract: what lands on this node's ``outputs`` edge."""
    out: Dict[str, Any] = {
        "format": format,
        "cardinality": cardinality,
        "inherits_input_columns": inherits,
        "derived_columns": derived,
        "columns": list(columns or []),
    }
    if note:
        out["note"] = note
    if wire:
        out["wire"] = wire
    if side_deliverable:
        out["side_deliverable"] = side_deliverable
    if consumes:
        out["consumes"] = consumes
    return out


# Shared inputs for first-class sklearn FIT tools (not SGDOneClassSVM).
_LINEAR_CLF_OUTCOME = [
    _p("outcome_column", "column", True, "Column holding the binary outcome to predict."),
    _p("outcome_values", "list[value]", True,
       "ONLY the value(s) counted as the POSITIVE class (=1) — the rest are 0. "
       "NEVER list every value: for a 0/1 flag pass [1]; for a labeled column pass "
       "just the positive label, verbatim."),
]
_LINEAR_CLF_COMMON = [
    _p("predictors", "list[column]", True,
       "Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the "
       "outcome_column and pure identifiers. Never empty."),
    _p("split_column", "column", False,
       "Train/test label from ml_train_test_split (usually \"split\"). When set, "
       "the model is fit on train and EVERY row is scored. Do not also restrict "
       "`where` to one arm."),
    _p("reference_levels", "object", False,
       "{covariate: baseline category} for categorical predictors."),
    _p("where", "string", False, "SQL boolean cohort filter. Optional."),
    _p("class_weight", "string", False, "\"balanced\" to reweight classes; omit for none."),
    _p("random_state", "integer", False, "Seed. Default 42."),
]
_LINEAR_CLF_OUT = (
    "FIT once. OUTPUT is the input cohort plus score columns — "
    "`predicted_probability` when the estimator has predict_proba, otherwise "
    "`predicted_score` (decision_function), plus `predicted_class`. Incomplete "
    "rows stay and get a NULL score. Evaluation tools (ROC / AUC / calibration) "
    "must read these columns; they must NOT refit. Distinct from "
    "statistics.logistic_regression (statsmodels odds-ratio table)."
)

# ONLY for ml_cv_performance / ml_compare. Evaluation tools must NOT take model=.
_ML_MODEL_PARAM = (
    "EXACT catalog key for a learning-procedure node that REFITS each fold. "
    "Prefer a sklearn class-name tool: \"LogisticRegression\", \"LogisticRegressionCV\", "
    "\"RandomForestClassifier\", \"GradientBoostingClassifier\", \"SVC\", … "
    "Legacy aliases also work: \"elasticnet_logistic\" | \"logistic\" | "
    "\"random_forest\" | \"gradient_boosting\". NEVER write \"xgboost\" / \"rf\". "
    "Do NOT pass this to ROC / calibration / DCA / performance — those read "
    "predicted_probability and never fit."
)

_EVAL_COMMON = [
    _p("outcome_column", "column", True, "Column holding the binary outcome."),
    _p("outcome_values", "list[value]", True,
       "ONLY the value(s) counted as the POSITIVE class (=1), verbatim. "
       "For a 0/1 flag pass [1]; for a labeled column pass just the positive label."),
    _p("probability_column", "column", False,
       "Predicted-probability column written by the upstream model node. "
       "Default \"predicted_probability\". Does not fit."),
    _p("where", "string", False, "SQL boolean cohort filter. Optional."),
    _p("split_column", "column", False,
       "Train/test label from ml_train_test_split (usually \"split\"). When set, "
       "only split_value rows are read (default test). Do not also restrict `where` "
       "to one arm."),
    _p("split_value", "string", False, "Which split arm to read. Default \"test\"."),
]

# Multiple imputation is NOT something the plan has to wire up. A tool reading an
# `impute_missing(n_imputations=m)` table finds the `_imputation` index itself,
# estimates inside each draw and pools by Rubin's rules — mice's with() + pool()
# on the inside. This parameter only renames the index, or opts out.
_MI_PARAM = (
    "Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default) — the tool "
    "detects `_imputation` on its own, runs the estimate INSIDE each draw and pools "
    "the m results by Rubin's rules, so every reported n counts PATIENTS. Name a "
    "column only when the index is spelled differently; pass \"none\" to analyse the "
    "stacked draws as one cohort, which counts every patient m times and is almost "
    "never what the protocol means."
)

# What every Cox tool now does on its own, so a plan stops trying to arrange it by
# hand. Hand-written 'IS NOT NULL' filters were the usual cause of the failure this
# replaces: they covered some covariates and not others, and the uncovered ones
# still emptied a category, leaving an all-zero dummy that killed the fit with
# "delta contains nan value(s)".
_COMPLETE_CASE = (
    "the tool applies the complete-case restriction itself (rows missing ANY "
    "covariate are dropped BEFORE encoding, so a category that survives only in "
    "dropped rows never becomes a phantom level), and it drops covariate columns "
    "that end up constant or redundant in the resulting cohort, reporting both in "
    "its summary. Use `where` for the CLINICAL cohort definition only. If a "
    "covariate is too incompletely recorded to lose, impute it first with "
    "impute_missing instead of filtering on it."
)

# The therapy flags in PREDICT are NOT counterfactual. The reported benefit of a
# therapy is exactly zero unless its flag is 1, so binding the observed column
# describes what the cohort actually gained, while pinning the flag to 1 asks what
# the therapy WOULD add. Getting this backwards yields a table of zeros that looks
# like "no benefit" rather than "never asked".
_PREDICT_RX_NOTE = (
    "This therapy's reported benefit is ZERO unless this flag says it was given. "
    "Bind the OBSERVED column to describe the gain the cohort actually had; pin it "
    "to 1 to ask what the therapy WOULD add for everyone."
)

# Positivity handling, shared by the ATT family. Spelled out at length because these
# two params are where sibling exhibits silently diverge: the DEFAULT is a real
# analytic choice (the whole cohort, untrimmed), so omitting them does not mean
# "unspecified", it means a different estimand than a sibling that sets them.
_OVERLAP_PARAM = (
    "true restricts the estimate to COMMON SUPPORT before estimating; false (the "
    "default) estimates on everyone. NOT a formatting flag — it changes which patients "
    "the effect is defined over, so a node that omits it is not comparable with one that "
    "sets it. State it explicitly whenever the run's primary spec does."
)
_TRIM_PARAM = (
    "Drop rows whose PS falls outside [trim, 1-trim] (0.01 / 0.05 are the usual "
    "choices). Default 0 = no trimming, which is itself a choice: trimming and "
    "`restrict_to_overlap` are DIFFERENT populations, so do not substitute one for the "
    "other when matching a locked primary spec."
)
# Every ATT result row carries the cohort flow, so the attrition figure is readable
# off the table and a covariate that was never recorded cannot pass unnoticed.

# The ESTIMAND is the target population, and it is the choice that decides which
# tool family to bind at all. Spelled out because "average treatment effect" in a
# protocol is ambiguous on its own: the same cohort, adjustment set and estimator
# give three different numbers depending on whom the effect is averaged over.
_ESTIMAND_PARAM = (
    "\"ate\" (default) averages the effect over the WHOLE cohort — what treatment "
    "would do if everyone got it. \"ato\" averages it over the OVERLAP population "
    "(bounded 1-PS / PS weights) — the effect among patients who could plausibly "
    "have received either arm. Prefer \"ato\" when propensity scores approach 0 or "
    "1, because the ATE's 1/PS weights then hand a handful of patients most of the "
    "estimate; say in the report that it answers the narrower question. For the "
    "effect in the TREATED use the att_* tools instead — this parameter cannot "
    "request the ATT."
)
_ATE_METHOD_PARAM = (
    "\"ipw\" (default, 1/PS and 1/(1-PS) weights) | \"gcomp\" (outcome regression "
    "standardized to every patient) | \"aipw\" (doubly robust — consistent if "
    "EITHER the propensity or the outcome model is right). \"psm\" is NOT available: "
    "matching without replacement builds a control group FOR THE TREATED, so it "
    "only identifies the ATT."
)
_ATT_OUTPUT_NOTE = (
    "Every row also reports the cohort flow — `n_loaded` -> `n_complete` (after "
    "listwise deletion) -> `n_analyzed` (after common support) — plus "
    "`n_covariate_missing` / `covariates_unrecorded` for patients KEPT with an "
    "unrecorded covariate (one-hot encoding models them at its reference level rather "
    "than adjusting for them), and `feasible`, which is false when an arm was left "
    "with fewer than 10 patients and no estimate was produced."
)


# ---------------------------------------------------------------------------
# Output-schema contracts (what tool_hub actually writes onto the node edge)
# ---------------------------------------------------------------------------
# Decompose wires `inputs`/`outputs` by name. Without these columns it cannot
# know that table1(smd=true) is the SMD table a viz must read, or that a
# matching/IPTW node outputs a COHORT (no SMD column on the edge).

_COL_ATT = [
    _c("estimand", "string",
       "ATT | ATE | ATO — the target population this row's effect is defined over"),
    _c("method", "string", "ipw | gcomp | psm | aipw"),
    _c("feasible", "bool",
       "false when an arm has <10 patients — no estimate was produced"),
    _c("n_loaded", "integer", "rows before listwise deletion"),
    _c("n_complete", "integer", "after listwise deletion"),
    _c("n_analyzed", "integer", "after common-support restriction"),
    _c("n_covariate_missing", "integer",
       "kept patients with an unrecorded covariate"),
    _c("covariates_unrecorded", "string",
       "which covariates were unrecorded among kept patients"),
    _c("n_imputations", "integer",
       "m when the input is multiply imputed", when="MI input"),
    _c("n_treated", "integer"),
    _c("n_control", "integer"),
    _c("mu_treated", "number", "observed outcome mean in the treated"),
    _c("mu_control", "number", "counterfactual control mean"),
    _c("effect", "number", "ATT (risk difference or mean difference)"),
    _c("effect_lower95", "number"),
    _c("effect_upper95", "number"),
    _c("effect_se", "number"),
    _c("ratio", "number", "risk ratio when the outcome is binary"),
    _c("n_bootstrap", "integer"),
    _c("significant", "bool", "CI excludes 0"),
]
_COL_SMD_PAIR = [
    _c("covariate", "string"),
    _c("smd_before", "number", "SMD on the unmatched / unweighted cohort"),
    _c("smd_after", "number", "SMD on the matched / weighted sample"),
]
_COL_BALANCE = [
    _c("variable", "string"),
    _c("level", "string",
       "category level; empty/null for a continuous covariate"),
    _c("type", "string", "continuous | categorical"),
    _c("treated", "number", "mean or proportion in treated"),
    _c("control", "number", "mean or proportion in control"),
    _c("asd", "number", "absolute standardized difference"),
    _c("balanced", "bool", "asd < 0.1"),
]
_OS_TABLE1 = _os(
    cardinality="one_row_per_variable_level",
    columns=[
        _c("Variable", "string",
           "Baseline variable name after TableOne MultiIndex flatten"),
        _c("Level", "string",
           "Category level; empty for a continuous row"),
        _c("<groupby headers>", "string",
           "One display column per group value (n (%) / mean (SD) / median [IQR])",
           when="groupby set"),
        _c("Overall", "string", "All-groups column", when="overall=true"),
        _c("p-value", "number|string",
           "Per-variable p. Flattened name is `p-value` or `p`",
           when="pval=true"),
        _c("SMD", "number",
           "Standardized mean difference. Flattened name is `SMD` "
           "(sometimes prefixed by the groupby header). "
           "This is the column a love / SMD figure must plot.",
           when="smd=true"),
    ],
    note="A tidy characteristics table — NOT a cohort. No patient rows.",
    wire="To plot SMD, viz.inputs MUST be this node's outputs. "
         "Do not point viz at the input cohort — that table has no SMD column.",
)
_OS_ATTRITION = _os(
    cardinality="one_row_per_step",
    columns=[
        _c("step", "integer", "0 = source cohort, then 1…n criteria"),
        _c("criterion", "string"),
        _c("expression", "string", "SQL WHERE applied at this step"),
        _c("n_before", "integer"),
        _c("n_after", "integer"),
        _c("n_excluded", "integer"),
        _c("pct_excluded", "number"),
        _c("n_subjects", "integer",
           "distinct patients when distinct_column is set"),
    ],
)
_OS_DATA_QUALITY = _os(
    cardinality="one_row_per_check",
    columns=[
        _c("check", "string", "missingness | temporal_order"),
        _c("variable", "string"),
        _c("n", "integer"),
        _c("n_flagged", "integer"),
        _c("pct_flagged", "number"),
        _c("n_distinct", "integer", when="check=missingness"),
        _c("detail", "string"),
    ],
)
_OS_PSM = _os(
    cardinality="row_subset",
    inherits=True,
    derived=True,
    columns=[_c("_treat", "integer", "1 = treated, 0 = control")],
    note="NODE OUTPUT is the matched PATIENT cohort (source columns + `_treat`). "
         "The SMD before/after table is a SIDE deliverable under the same node "
         "name and is NOT on the dataset edge.",
    side_deliverable=_os(
        cardinality="one_row_per_covariate",
        columns=_COL_SMD_PAIR,
        note="Registered as a workspace deliverable only. Downstream nodes "
             "cannot read it via inputs unless a dedicated table1(smd=true) "
             "or covariate_balance node produces it.",
    ),
    wire="KM / Cox / table1 read this cohort. A viz of SMD must NOT take this "
         "cohort as its only input — it has no SMD column. Add table1(smd=true) "
         "or covariate_balance and point viz.inputs at THAT table.",
)
_OS_PSM_MULTI = _os(
    cardinality="row_subset",
    inherits=True,
    derived=True,
    columns=[_c("_arm", "integer", "0..K-1 arm index, equal n per arm")],
    note="Matched patient cohort. Pairwise SMD before/after is a side deliverable, "
         "not the node output.",
    side_deliverable=_os(
        cardinality="one_row_per_covariate_pair",
        columns=_COL_SMD_PAIR + [
            _c("arm_i", "string", "first arm label"),
            _c("arm_j", "string", "second arm label"),
        ],
    ),
    wire="Same as propensity_score_match: viz of SMD binds to table1 / "
         "covariate_balance, not this cohort.",
)
_OS_IPTW = _os(
    cardinality="row_subset",
    inherits=True,
    derived=True,
    columns=[
        _c("propensity_score", "number"),
        _c("iptw", "number",
           "ATE weight (column name is `overlap_weight` when weight_type=overlap)"),
    ],
    note="NODE OUTPUT is the FULL weighted cohort. SMD before vs after weighting "
         "is a side deliverable (package column `smd_weighted`) — not on the edge.",
    side_deliverable=_os(
        cardinality="one_row_per_covariate",
        columns=[
            _c("smd_weighted", "number",
               "SMD after weighting; |SMD|>0.1 flags residual imbalance"),
        ],
    ),
    wire="Weighted KM / Cox read this cohort (`iptw` / `overlap_weight`). "
         "A viz of SMD binds to table1(smd=true) or covariate_balance "
         "(pass weight_column), not this cohort.",
)
_OS_ATT_WEIGHT = _os(
    cardinality="row_subset",
    inherits=True,
    derived=True,
    columns=[
        _c("propensity_score", "number"),
        _c("att_weight", "number",
           "1 for treated, PS/(1-PS) for controls (or params.weight_column)"),
        _c("overlap_flag", "integer", "1 = on common support"),
    ],
    note="Weighted patient cohort. ESS / weight-range diagnostics are a side "
         "deliverable, not the node output.",
)
_OS_ATT = _os(
    cardinality="one_row",
    columns=_COL_ATT,
    note=_ATT_OUTPUT_NOTE,
    wire="A comparison / forest figure must take this table as viz.inputs "
         "(columns `effect`, `effect_lower95`, `effect_upper95`, `feasible`).",
)
_OS_ATT_MULTI = _os(
    cardinality="one_row_per_method",
    columns=_COL_ATT + [
        _c("specification", "string", "method label"),
        _c("effect_minus_primary", "number",
           "difference from the primary_method row"),
    ],
    wire="Point viz.inputs at this table to compare estimators — not the cohort.",
)
_OS_ATT_SENS = _os(
    cardinality="one_row_per_spec",
    columns=[
        _c("specification", "string"),
        *_COL_ATT,
        _c("effect_minus_primary", "number",
           "difference from the first specification"),
    ],
    wire="Point viz.inputs at this table for a robustness / forest figure.",
)
# Same columns as _COL_ATT, but the ones whose MEANING depends on the estimand are
# re-described: for a population effect both mu_* are counterfactual means over the
# same cohort, and `psm` is not a legal method.
_ATE_COL_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "estimand": _c("estimand", "string",
                   "ATE | ATO — the target population this row's effect is defined over"),
    "method": _c("method", "string", "ipw | gcomp | aipw"),
    "mu_treated": _c("mu_treated", "number",
                     "counterfactual mean if EVERYONE were treated (over the target population)"),
    "mu_control": _c("mu_control", "number",
                     "counterfactual mean if NOBODY were treated (same population)"),
    "effect": _c("effect", "number",
                 "ATE / ATO (risk difference or mean difference), = mu_treated - mu_control"),
}
_COL_ATE = [_ATE_COL_OVERRIDES.get(c["name"], c) for c in _COL_ATT]

_OS_ATE_WEIGHT = _os(
    cardinality="row_subset",
    inherits=True,
    derived=True,
    columns=[
        _c("propensity_score", "number"),
        _c("ate_weight", "number",
           "1/PS for treated, 1/(1-PS) for controls — named `overlap_weight` when "
           "estimand=ato (1-PS treated, PS control), or params.weight_column"),
        _c("overlap_flag", "integer", "1 = on common support"),
    ],
    note="Weighted patient cohort on the SAME propensity fit the ate_* estimators "
         "use. ESS / weight-range diagnostics are a side deliverable, not the "
         "node output.",
)
_OS_ATE = _os(
    cardinality="one_row",
    columns=_COL_ATE,
    note=_ATT_OUTPUT_NOTE,
    wire="A comparison / forest figure must take this table as viz.inputs "
         "(columns `effect`, `effect_lower95`, `effect_upper95`, `feasible`). "
         "NEVER union it with an att_* table without keeping `estimand`: the ATT "
         "and the ATE are different quantities.",
)
_OS_ATE_MULTI = _os(
    cardinality="one_row_per_method",
    columns=_COL_ATE + [
        _c("specification", "string", "method label"),
        _c("effect_minus_primary", "number",
           "difference from the first method row"),
    ],
    wire="Point viz.inputs at this table to compare estimators — not the cohort.",
)
_OS_ATE_SENS = _os(
    cardinality="one_row_per_spec",
    columns=[
        _c("specification", "string"),
        *_COL_ATE,
        _c("effect_minus_primary", "number",
           "difference from the first specification"),
    ],
    wire="Point viz.inputs at this table for a robustness / forest figure.",
)
_OS_BALANCE = _os(
    cardinality="one_row_per_variable_level",
    columns=_COL_BALANCE + [
        _c("n_imputations", "integer", when="MI input"),
    ],
    note="Tidy ASD table. Categorical covariates emit one row per level.",
    wire="Love / ASD plot: viz.inputs = this node's outputs "
         "(`variable`, `level`, `asd`).",
)
_OS_BALANCE_MULTI = _os(
    cardinality="one_row_per_scenario_level",
    columns=[
        _c("scenario", "string"),
        *_COL_BALANCE,
        _c("asd_reference", "number",
           "ASD of the same variable/level in the first scenario"),
    ],
    wire="viz.inputs = this table to plot ASD before vs after / across scenarios.",
)
_OS_MW = _os(
    cardinality="one_row",
    columns=[
        _c("value_column", "string"),
        _c("group_column", "string"),
        _c("group_a", "string"),
        _c("n_a", "integer"),
        _c("median_a", "number"),
        _c("group_b", "string"),
        _c("n_b", "integer"),
        _c("median_b", "number"),
        _c("u_statistic", "number"),
        _c("p_value", "number"),
        _c("alternative", "string"),
        _c("method", "string"),
    ],
)
_OS_CHI2 = _os(
    cardinality="one_row",
    columns=[
        _c("row_column", "string"),
        _c("col_column", "string"),
        _c("n", "integer"),
        _c("n_rows", "integer"),
        _c("n_cols", "integer"),
        _c("chi2_statistic", "number"),
        _c("dof", "integer"),
        _c("p_value", "number"),
        _c("cramers_v", "number"),
        _c("lambda_", "string"),
        _c("correction", "bool"),
    ],
)
_OS_LOGIT = _os(
    cardinality="one_row_per_term",
    columns=[
        _c("covariate", "string"),
        _c("level_type", "string", "coefficient | reference | intercept"),
        _c("coef", "number"),
        _c("odds_ratio", "number"),
        _c("or_lower95", "number"),
        _c("or_upper95", "number"),
        _c("z", "number"),
        _c("p", "number"),
    ],
    wire="Forest of ORs: viz.inputs = this table "
         "(`covariate`, `odds_ratio`, `or_lower95`, `or_upper95`). "
         "Filter level_type='coefficient' if you drop reference rows.",
)
_OS_GLM = _os(
    cardinality="one_row_per_term",
    columns=[
        _c("covariate", "string"),
        _c("level_type", "string", "coefficient | reference | intercept"),
        _c("coef", "number", "linear-predictor scale (log for a log link)"),
        _c("se", "number"),
        _c("estimate", "number",
           "exp(coef) on a log/logit link, else the coefficient itself"),
        _c("ci_lower", "number"),
        _c("ci_upper", "number"),
        _c("estimate_type", "string",
           "rate_ratio | risk_ratio | odds_ratio | ratio | mean_difference — "
           "what `estimate` MEANS for the family/link that was fitted"),
        _c("z", "number"),
        _c("p", "number"),
    ],
    wire="Forest of effects: viz.inputs = this table "
         "(`covariate`, `estimate`, `ci_lower`, `ci_upper`). "
         "Filter level_type='coefficient' if you drop reference rows. "
         "Label the axis from `estimate_type` — a log-link count model gives "
         "RATE ratios, not odds ratios.",
)
_OS_EVALUE = _os(
    cardinality="one_row",
    columns=[
        _c("scale", "string", "rr | hr | or | rd"),
        _c("estimate", "number"),
        _c("ci_lower", "number"),
        _c("ci_upper", "number"),
        _c("risk_ratio_scale", "number"),
        _c("evalue_point", "number"),
        _c("evalue_ci", "number"),
    ],
)
_OS_BIAS = _os(
    cardinality="one_row_per_scenario",
    columns=[
        _c("scenario", "string"),
        _c("rr_confounder_outcome", "number"),
        _c("rr_confounder_exposure", "number"),
        _c("bounding_factor", "number"),
        _c("adjusted_estimate", "number"),
        _c("adjusted_ci_lower", "number"),
        _c("adjusted_ci_upper", "number"),
        _c("still_significant", "bool"),
    ],
)
_OS_IMPUTE = _os(
    cardinality="row_subset",
    inherits=True,
    derived=True,
    columns=[
        _c("_imputation", "integer",
           "draw index 1…m; absent when n_imputations=1",
           when="n_imputations>1"),
        _c("<column>_missing", "integer",
           "1 if the original cell was missing",
           when="add_indicator=true"),
    ],
)
_OS_PREDICT_BREAST = _os(
    cardinality="row_subset",
    inherits=True,
    derived=True,
    columns=[
        _c("predict_os_<year>y", "number",
           "% surviving at <year> years with SURGERY ALONE — the untreated "
           "baseline, NOT the survival of a patient on therapy. It does not "
           "change when the therapy flags change. NULL when out of domain"),
        _c("predict_horm_benefit_<year>y", "number",
           "percentage points added by hormone therapy; 0 unless horm=1 and ER+"),
        _c("predict_chemo_benefit_<year>y", "number",
           "percentage points added by chemotherapy ON TOP of hormone; "
           "0 unless generation=2/3"),
        _c("predict_traz_benefit_<year>y", "number",
           "percentage points added by trastuzumab ON TOP of hormone+chemo; "
           "0 unless traz=1 and HER2+"),
        _c("predict_bis_benefit_<year>y", "number",
           "percentage points added by bisphosphonate ON TOP of the other three; "
           "0 unless bis=1"),
        _c("predict_ineligible", "string",
           "why the patient could not be scored; empty when scored"),
    ],
    note="TWO things a reader gets wrong unless the write-up says them. "
         "(1) The survival column is the SURGERY-ALONE baseline; predicted survival "
         "UNDER treatment is that column PLUS the benefits, so never present it as "
         "'predicted survival' for a treated cohort. "
         "(2) The four benefits are INCREMENTAL, in the order hormone → chemo → "
         "trastuzumab → bisphosphonate: each is the gain from ADDING that therapy to "
         "the ones before it, so they sum to the total gain over surgery alone and "
         "none is a standalone effect. "
         "A benefit is ZERO whenever its therapy flag is 0 — bind a flag to a "
         "constant 1 to ask 'what would this therapy add', and to the observed "
         "column to describe what the cohort actually gained. "
         "Rows with a non-empty `predict_ineligible` have NULL predictions — filter "
         "on it (or on the survival column being NOT NULL) before summarising, and "
         "report how many were dropped.",
    wire="A downstream node summarising or plotting these must filter "
         "`predict_ineligible = ''`. For EXTERNAL VALIDATION against observed "
         "outcomes, a `sql` node derives the risk the eval tools expect — "
         "predicted_probability = 1 - predict_os_<year>y/100 — and then "
         "ml_calibration_curve / ml_roc_curve read it without refitting. That "
         "validation only makes sense against an UNTREATED (or "
         "treatment-adjusted) comparison, since the column is the "
         "surgery-alone baseline.",
    side_deliverable={
        "kind": "table",
        "note": "Distribution of each predicted column (mean / sd / median / IQR / "
                "range) with the cohort flow (n_rows → n_scored → n_ineligible), "
                "the per-reason exclusion counts, and every variable that was "
                "pinned to a FIXED value rather than read from a column.",
    },
)
_OS_ML_SCORED = _os(
    cardinality="row_subset",
    inherits=True,
    derived=True,
    columns=[
        _c("predicted_probability", "number",
           "P(y=1) when the estimator has predict_proba"),
        _c("predicted_score", "number",
           "decision_function when there is no predict_proba"),
        _c("predicted_class", "integer", "0/1 predicted label"),
    ],
    note=_LINEAR_CLF_OUT,
    wire="ROC / calibration / DCA / performance read `predicted_probability` "
         "(or `predicted_score`) from this dataset. They do not refit.",
)
_OS_ML_SPLIT = _os(
    cardinality="row_subset",
    inherits=True,
    derived=True,
    columns=[
        _c("split", "string",
           "train | test (or params.split_column)"),
    ],
)
_OS_ML_PERF = _os(
    cardinality="one_row_per_metric",
    columns=[
        _c("metric", "string",
           "auc / auc_test, brier, pr_auc, sensitivity, specificity, "
           "ppv, npv, calibration_slope, calibration_intercept, "
           "threshold, n, n_events, bootstrap_reps"),
        _c("value", "number"),
        _c("ci_lower", "number"),
        _c("ci_upper", "number"),
    ],
)
_OS_ML_RECLASS = _os(
    cardinality="one_row_per_metric",
    columns=[
        _c("metric", "string",
           "auc_full, auc_reduced, idi, nri_continuous, nri_events, "
           "nri_nonevents, plus categorical NRI when nri_thresholds set"),
        _c("value", "number"),
    ],
)
_OS_ML_CV = _os(
    cardinality="one_row",
    columns=[
        _c("model", "string"),
        _c("model_name", "string"),
        _c("n", "integer"),
        _c("n_events", "integer"),
        _c("folds", "integer"),
        _c("auc", "number"),
        _c("brier", "number"),
        _c("calibration_slope", "number"),
        _c("calibration_intercept", "number"),
        _c("citl", "number"),
    ],
)
_OS_ML_COMPARE = _os(
    cardinality="one_row_per_model",
    columns=[
        _c("rank", "integer", "1 = best AUC"),
        _c("model", "string"),
        _c("model_name", "string"),
        _c("n", "integer"),
        _c("n_events", "integer"),
        _c("folds", "integer"),
        _c("auc", "number"),
        _c("brier", "number"),
        _c("calibration_slope", "number"),
        _c("calibration_intercept", "number"),
        _c("citl", "number"),
    ],
)
_OS_LOGRANK = _os(
    cardinality="one_row",
    columns=[
        _c("time_column", "string"),
        _c("event_column", "string"),
        _c("group_column", "string"),
        _c("group_a", "string"),
        _c("n_a", "integer"),
        _c("events_a", "integer"),
        _c("group_b", "string"),
        _c("n_b", "integer"),
        _c("events_b", "integer"),
        _c("test_statistic", "number"),
        _c("dof", "integer"),
        _c("p_value", "number"),
        _c("t_0", "number"),
        _c("weightings", "string"),
    ],
)
_OS_COX = _os(
    cardinality="one_row_per_term",
    columns=[
        _c("term_type", "string",
           "coefficient | reference | interaction_contrast | global_wald"),
        _c("term", "string"),
        _c("group", "string"),
        _c("coef", "number"),
        _c("se", "number"),
        _c("hazard_ratio", "number"),
        _c("hr_lower95", "number"),
        _c("hr_upper95", "number"),
        _c("statistic", "number"),
        _c("df", "number"),
        _c("p", "number"),
    ],
    wire="Forest of HRs: viz.inputs = this table "
         "(`term`/`covariate`, `hazard_ratio`, `hr_lower95`, `hr_upper95`).",
)
_OS_COX_UNI = _os(
    cardinality="one_row_per_covariate_term",
    columns=[
        _c("covariate", "string", "which univariate model the row came from"),
        _c("term_type", "string",
           "coefficient | reference | global_wald"),
        _c("term", "string"),
        _c("coef", "number"),
        _c("se", "number"),
        _c("hazard_ratio", "number"),
        _c("hr_lower95", "number"),
        _c("hr_upper95", "number"),
        _c("statistic", "number"),
        _c("df", "number"),
        _c("p", "number"),
        _c("n", "integer"),
        _c("events", "integer"),
    ],
    wire="Same as cox_ph — viz.inputs = this table for a univariate HR forest.",
)
_OS_COX_SUB = _os(
    cardinality="one_row_per_subgroup_term",
    columns=[
        _c("subgroup_variable", "string"),
        _c("subgroup_category", "string"),
        _c("exposure", "string"),
        _c("term_type", "string"),
        _c("term", "string"),
        _c("coef", "number"),
        _c("se", "number"),
        _c("hazard_ratio", "number"),
        _c("hr_lower95", "number"),
        _c("hr_upper95", "number"),
        _c("statistic", "number"),
        _c("p", "number"),
        _c("n", "integer"),
        _c("n_ref", "integer"),
        _c("n_exposed", "integer"),
        _c("events", "integer"),
    ],
    wire="Subgroup forest: viz.inputs = this table "
         "(`subgroup_variable`, `subgroup_category`, `hazard_ratio`, "
         "`hr_lower95`, `hr_upper95`).",
)
_OS_COX_PH_ASSUMPTIONS = _os(
    cardinality="one_row_per_covariate",
    columns=[
        _c("covariate", "string"),
        _c("test_statistic", "number"),
        _c("p", "number"),
        _c("violates_ph", "bool", "p < 0.05"),
    ],
)
_OS_SURVIVAL_METRICS = _os(
    cardinality="one_row_per_group_metric_timepoint",
    columns=[
        _c("group", "string", "treatment | control | difference"),
        _c("metric", "string",
           "survival_probability | rmst | median_survival"),
        _c("timepoint", "number", "horizon; null for median_survival"),
        _c("estimate", "number"),
        _c("lower_ci", "number"),
        _c("upper_ci", "number"),
    ],
    wire="Plot RMST / survival-at-t from this table, not the weighted cohort.",
)
_OS_FIGURE = _os(
    format="png+parquet",
    cardinality="figure",
    note="Returns a PNG plus the tidy frame the chart was drawn from. "
         "Does not invent columns — it plots what its inputs already hold.",
)
# name → schema. Applied onto ``description`` after the catalog is built so
# each _t(...) call stays a compact signature + param_specs block.
OUTPUT_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "table1": _OS_TABLE1,
    "attrition_table": _OS_ATTRITION,
    "data_quality": _OS_DATA_QUALITY,
    "propensity_score_match": _OS_PSM,
    "propensity_score_match_multi": _OS_PSM_MULTI,
    "iptw_weight": _OS_IPTW,
    "mann_whitney_u": _OS_MW,
    "chi2_contingency": _OS_CHI2,
    "logistic_regression": _OS_LOGIT,
    "glm_regression": _OS_GLM,
    "att_weight": _OS_ATT_WEIGHT,
    "att_estimate": _OS_ATT,
    "att_estimate_multi": _OS_ATT_MULTI,
    "att_sensitivity": _OS_ATT_SENS,
    "ate_weight": _OS_ATE_WEIGHT,
    "ate_estimate": _OS_ATE,
    "ate_estimate_multi": _OS_ATE_MULTI,
    "ate_sensitivity": _OS_ATE_SENS,
    "covariate_balance": _OS_BALANCE,
    "covariate_balance_multi": _OS_BALANCE_MULTI,
    "evalue": _OS_EVALUE,
    "bias_sensitivity": _OS_BIAS,
    "impute_missing": _OS_IMPUTE,
    "predict_breast_os": _OS_PREDICT_BREAST,
    "LogisticRegression": _OS_ML_SCORED,
    "LogisticRegressionCV": _OS_ML_SCORED,
    "PassiveAggressiveClassifier": _OS_ML_SCORED,
    "Perceptron": _OS_ML_SCORED,
    "RidgeClassifier": _OS_ML_SCORED,
    "RidgeClassifierCV": _OS_ML_SCORED,
    "SGDClassifier": _OS_ML_SCORED,
    "SGDOneClassSVM": _OS_ML_SCORED,
    "SVC": _OS_ML_SCORED,
    "LinearSVC": _OS_ML_SCORED,
    "NuSVC": _OS_ML_SCORED,
    "DecisionTreeClassifier": _OS_ML_SCORED,
    "ExtraTreeClassifier": _OS_ML_SCORED,
    "RandomForestClassifier": _OS_ML_SCORED,
    "ExtraTreesClassifier": _OS_ML_SCORED,
    "AdaBoostClassifier": _OS_ML_SCORED,
    "GradientBoostingClassifier": _OS_ML_SCORED,
    "HistGradientBoostingClassifier": _OS_ML_SCORED,
    "ml_train_test_split": _OS_ML_SPLIT,
    "ml_classifier_performance": _OS_ML_PERF,
    "ml_roc_curve": _OS_FIGURE,
    "ml_calibration_curve": _OS_FIGURE,
    "ml_decision_curve": _OS_FIGURE,
    "ml_reclassification": _OS_ML_RECLASS,
    "ml_cv_performance": _OS_ML_CV,
    "ml_compare": _OS_ML_COMPARE,
    "kaplan_meier": _OS_FIGURE,
    "competing_risk_cif": _OS_FIGURE,
    "logrank_test": _OS_LOGRANK,
    "cox_ph": _OS_COX,
    "cox_ph_univariate": _OS_COX_UNI,
    "cox_ph_subgroup": _OS_COX_SUB,
    "cox_ph_assumptions": _OS_COX_PH_ASSUMPTIONS,
    "cox_time_varying": _OS_COX,
    "iptw_kaplan_meier": _OS_FIGURE,
    "iptw_survival_metrics": _OS_SURVIVAL_METRICS,
}


def _apply_output_schemas(tools: List[Dict[str, Any]]) -> None:
    """Attach OUTPUT_SCHEMAS onto each catalog entry (in place)."""
    for spec in tools:
        schema = OUTPUT_SCHEMAS.get(str(spec.get("name") or ""))
        if schema:
            spec["output_schema"] = schema


# ---------------------------------------------------------------------------
# The catalog — one entry per hub op.
# ---------------------------------------------------------------------------
description: List[Dict[str, Any]] = [
    # --- descriptive ---
    _t("table1", "descriptive", "table",
       '{"columns":[...],"groupby"?,"categorical"?:[...],"nonnormal"?:[...],'
       '"rename"?:{"col":"Label"},"pval"?:true,"smd"?:true,"overall"?:true,"where"?}',
       "Baseline-characteristics \"Table 1\" (tableone), optionally per group with p-values/SMD.",
       [
           _p("columns", "list[column]", True,
              "The baseline variables to SUMMARIZE (one row-block each). Never empty. "
              "Do NOT include the groupby column here."),
           _p("groupby", "column", False,
              "Column to stratify by (produces per-group columns + p-value/SMD). Its own "
              "value is the group header, not a summarized row."),
           _p("categorical", "list[column]", False,
              "Which of `columns` are categorical (counts/%); the rest are treated as continuous."),
           _p("nonnormal", "list[column]", False,
              "Skewed continuous columns to report as median [IQR] instead of mean (SD)."),
           _p("rename", "object{column:string}", False,
              "Display-label map for Table 1 row names: {source_column: \"Label\"}. "
              "The source column stays the same; only the printed Variable label changes "
              "(e.g. {\"BMI_23_LSY\": \"BMI_23\"} strips a suffix). Keys must be columns "
              "already in `columns`. Omit to keep the raw column names."),
           _p("pval", "bool", False, "Add a per-variable p-value column (needs groupby). Default false."),
           _p("smd", "bool", False, "Add a standardized-mean-difference column (needs groupby). Default false."),
           _p("overall", "bool", False, "Include an overall (all-groups) column. Default false."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("imputation_column", "column", False,
              "Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default): a baseline "
              "table counts PATIENTS, so the tool narrows an `_imputation` stack to ONE draw "
              "instead of reporting m copies of the cohort as N."),
       ]),
    _t("attrition_table", "descriptive", "table",
       '{"steps":[{"label","where"},...],"distinct_column"?,"where"?}',
       "CONSORT-style inclusion/exclusion flow: applies EVERY criterion in `steps` "
       "CUMULATIVELY and reports n before/after/excluded at each one. This is the LOOP "
       "tool for attrition — one node for the whole flow, never one node per criterion.",
       [
           _p("steps", "list[object]", True,
              "The loop axis: an ORDERED list of {\"label\": \"...\", \"where\": \"<SQL boolean>\"} "
              "criteria, each applied ON TOP OF the previous ones. Write them in the order the "
              "protocol states them — the table reads as the flow diagram does. Never empty."),
           _p("distinct_column", "column", False,
              "Patient/subject id, to count SUBJECTS alongside rows at each step. Optional."),
           _p("where", "string", False,
              "Filter defining the SOURCE population (step 0), before any criterion. Optional."),
       ]),
    _t("data_quality", "descriptive", "table",
       '{"columns":[...],"date_order"?:[{"earlier","later","label"}],"where"?}',
       "Missingness / cardinality per column PLUS temporal-consistency violations per rule — "
       "two loop axes in one node. Use it for the protocol's data-quality section instead of "
       "one node per variable.",
       [
           _p("columns", "list[column]", False,
              "Loop axis 1: the columns to profile. Each gets n, n_flagged (null or blank), "
              "pct_flagged and n_distinct."),
           _p("date_order", "list[object]", False,
              "Loop axis 2: order rules, each {\"earlier\": \"<column>\", \"later\": \"<column>\", "
              "\"label\": \"...\"}, counting the rows where `later` PRECEDES `earlier` (e.g. a "
              "treatment date before the diagnosis date). Values compare as dates when both "
              "cast, otherwise as numbers, so year-only fields work unparsed."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
       ]),

    # --- statistics ---
    _t("propensity_score_match", "statistics", "dataset",
       '{"treatment_column","treatment_values":[...],"covariates":[...],"where"?,"caliper"?:0.2,"ratio"?:1}',
       "Binary PSM: greedy nearest-neighbour matching of treated to control on the PS logit, "
       "without replacement, within a caliper; OUTPUT is the matched cohort (+`_treat`). "
       "TWO arms only — for 3+ arms use propensity_score_match_multi.",
       [
           _p("treatment_column", "column", True,
              "Column that separates treated vs control (e.g. a 0/1 flag or a 2-label category)."),
           _p("treatment_values", "list[value]", True,
              "ONLY the value(s) of treatment_column that mark the TREATED arm — the control is "
              "everyone else, inferred automatically. NEVER list every value: for a 0/1 flag pass "
              "[1] (not [1,0]); for a labeled column pass just the treated label, copied verbatim "
              "from its real values."),
           _p("covariates", "list[column]", True,
              "Baseline columns to balance on (categoricals auto one-hot encoded). EXCLUDE the "
              "treatment_column and any pure identifier. Never empty."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("caliper", "number", False,
              "Match tolerance as a multiple of SD(PS logit); applies at every ratio. Default 0.2 "
              "(Austin's recommendation) — keep it unless the source explicitly used another value."),
           _p("ratio", "integer", False, "Controls matched per treated (1 = 1:1). Default 1."),
       ]),
    _t("propensity_score_match_multi", "statistics", "dataset",
       '{"treatment_column","arms":[A,B,C,…],"covariates":[...],"exact_columns"?:[...],'
       '"tolerance_columns"?:{col:tol}|[{column,tolerance}],"where"?,"caliper"?:0.6}',
       "Multi-arm (K≥3) 1:1:…:1 PSM (multinomial GPS vector, Rassen-style K-tuples); "
       "OUTPUT is the matched cohort (equal n per arm + `_arm`).",
       [
           _p("treatment_column", "column", True,
              "Column whose values identify the K treatment arms (e.g. surgery type)."),
           _p("arms", "list[value]", True,
              "Ordered list of ≥3 distinct treatment_column values to match 1:1:…:1. Copy each "
              "label VERBATIM from the data. Do NOT use this tool for binary (2-arm) matching."),
           _p("covariates", "list[column]", True,
              "Baseline columns for the multinomial propensity model (categoricals auto one-hot "
              "encoded). EXCLUDE treatment_column and pure identifiers. Never empty."),
           _p("exact_columns", "list[column]", False,
              "Columns that must match exactly within each K-tuple (hard strata), e.g. histology, "
              "stage, ER status. Optional."),
           _p("tolerance_columns", "object|list", False,
              "Numeric within-tolerance constraints: {column: tol} or "
              "[{column, tolerance}, …] — e.g. {\"Age\": 2, \"Year of diagnosis\": 2}. Every pair "
              "in a tuple must satisfy |Δ| ≤ tol. Optional."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("caliper", "number", False,
              "Per GPS-dimension caliper as a multiple of SD(logit P(arm=a) among patients in "
              "arm a). Default 0.6 (common three-group PSM / Rassen-style recipes)."),
       ]),
    _t("iptw_weight", "statistics", "dataset",
       '{"treatment_column","treatment_values":[...],"covariates":[...],"cont_var"?:[...],'
       '"where"?,"weight_type"?:"iptw"|"overlap","stabilized"?:true,"clip_bounds"?:[0.01,0.99]}',
       "IPTW (iptw-survival): weights every patient by 1/PS instead of discarding unmatched ones; "
       "OUTPUT is the full cohort + `propensity_score` + `iptw`.",
       [
           _p("treatment_column", "column", True,
              "Column that separates treated vs control (a 0/1 flag or a 2-label category)."),
           _p("treatment_values", "list[value]", True,
              "ONLY the value(s) marking the TREATED arm — control is everyone else, inferred "
              "automatically. NEVER list every value: for a 0/1 flag pass [1] (not [1,0]); for a "
              "labeled column pass just the treated label, copied verbatim from its real values."),
           _p("covariates", "list[column]", True,
              "Confounders the propensity model adjusts for. Typed AUTOMATICALLY: numeric columns "
              "become continuous, everything else categorical (blanks become an 'Unknown' level). "
              "EXCLUDE the treatment column, the outcome and any identifier. Never empty."),
           _p("cont_var", "list[column]", False,
              "Force these covariates to be CONTINUOUS. Needed for numeric fields stored as text "
              "that the auto-typing would otherwise treat as categories."),
           _p("cat_var", "list[column]", False, "Force these covariates to be CATEGORICAL."),
           _p("binary_var", "list[column]", False, "Force these covariates to be BINARY (exactly 2 levels)."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("weight_type", "string", False,
              "\"iptw\" (default) targets the ATE; \"overlap\" targets the ATO and is far more "
              "stable when some patients have extreme propensity scores."),
           _p("stabilized", "bool", False,
              "Stabilize IPTW by the marginal treatment probability (default true). Ignored for "
              "overlap weights."),
           _p("clip_bounds", "list[number]", False,
              "Trim propensity scores to [lower, upper], e.g. [0.01, 0.99], to cap extreme weights."),
           _p("normalize", "string", False,
              "Overlap weights only: \"by_group\" or \"overall\" rescaling of the weights."),
           _p("random_state", "integer", False, "Seed for the propensity model. Default 42."),
       ]),
    _t("mann_whitney_u", "statistics", "table",
       '{"value_column","group_column","group_values"?:[A,B],"where"?,"alternative"?,"method"?}',
       "Mann-Whitney U rank test comparing a numeric column between two groups (one-row result table).",
       [
           _p("value_column", "column", True, "The NUMERIC column to compare between the two arms."),
           _p("group_column", "column", True, "Categorical column defining the two arms."),
           _p("group_values", "list[value]", False,
              "The TWO group labels to compare (verbatim), required when group_column has >2 labels, e.g. [\"A\",\"B\"]."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("alternative", "string", False, "\"two-sided\" (default) | \"less\" | \"greater\"."),
           _p("method", "string", False, "\"auto\" (default) | \"asymptotic\" | \"exact\"."),
       ]),
    _t("chi2_contingency", "statistics", "table",
       '{"row_column","col_column","row_values"?:[...],"col_values"?:[...],"where"?,"correction"?:true}',
       "Chi-square test of independence between two categorical columns (+Cramér's V).",
       [
           _p("row_column", "column", True, "First CATEGORICAL column (table rows)."),
           _p("col_column", "column", True, "Second CATEGORICAL column (table columns)."),
           _p("row_values", "list[value]", False, "Restrict row_column to these labels (verbatim). Optional."),
           _p("col_values", "list[value]", False, "Restrict col_column to these labels (verbatim). Optional."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("correction", "bool", False, "Yates' continuity correction for 2×2. Default true."),
       ]),
    _t("logistic_regression", "statistics", "table",
       '{"outcome_column","outcome_values":[...],"covariates":[...],"where"?,'
       '"reference_levels"?:{"column":"baseline level"}}',
       "Multivariable logistic regression (statsmodels); returns an odds-ratio table with 95% CI "
       "(covariate/level_type/coef/odds_ratio/or_lower95/or_upper95/z/p). Each categorical "
       "covariate also gets a level_type='reference' row (odds_ratio=1.0) naming its baseline, so "
       "the table already states what every OR is measured against.",
       [
           _p("outcome_column", "column", True, "Column holding the binary outcome to model."),
           _p("outcome_values", "list[value]", True,
              "ONLY the value(s) of outcome_column counted as the POSITIVE class (=1) — the rest "
              "are 0, inferred automatically. NEVER list every value: for a 0/1 flag pass [1] (not "
              "[1,0]); for a labeled column pass just the positive label, copied verbatim, e.g. [\"Yes\"]."),
           _p("covariates", "list[column]", True,
              "Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the outcome_column "
              "and pure identifiers. Never empty."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("reference_levels", "object", False,
              "{covariate: baseline category} for categorical predictors, e.g. {\"Race recode\": "
              "\"Black\"}. Every odds ratio is measured against this level, so whenever the request "
              "names a reference/baseline category you MUST set it here — otherwise the baseline is "
              "whichever level sorts first and the ORs answer a different question. Copy the level "
              "verbatim from the column's values; a level that does not occur is an error."),
       ]),
    _t("glm_regression", "statistics", "table",
       '{"outcome_column","covariates":[...],"family":"poisson","link"?:"log",'
       '"exposure_column"?,"offset_column"?,"weights_column"?,"cov_type"?:"HC0",'
       '"cluster_column"?,"alpha"?:1.0,"outcome_values"?:[...],"where"?,'
       '"reference_levels"?:{"column":"baseline level"}}',
       "Generalized linear model (statsmodels GLM) for outcomes that are NOT a binary event: "
       "count / incidence-RATE models (poisson, negativebinomial + exposure_column for "
       "person-time), skewed positive cost or length-of-stay (gamma, log link), and continuous "
       "means (gaussian). Returns one row per term with coef/se and `estimate` + ci_lower/ci_upper, "
       "where estimate is exp(coef) on a log/logit link; `estimate_type` names the scale "
       "(rate_ratio / risk_ratio / odds_ratio / ratio / mean_difference). Also fits WEIGHTED "
       "outcome models over an iptw / overlap_weight column. Use logistic_regression for a binary "
       "outcome reported as odds ratios; come here for risk ratios (family=binomial, link=log). "
       "The design matrix rank is checked before fitting, so a redundant or constant covariate is "
       "a named error rather than a fit whose coefficients are not uniquely determined.",
       [
           _p("outcome_column", "column", True,
              "Column holding the outcome. Read as a NUMBER (counts, cost, duration, mean) for "
              "every family except binomial."),
           _p("covariates", "list[column]", True,
              "Predictor columns (categoricals auto one-hot, drop-first). EXCLUDE the "
              "outcome_column, the exposure/offset column and pure identifiers. Never empty. "
              "Do NOT pass a duplicate or rescaling of another covariate (age and age_in_months), "
              "or two columns encoding the SAME partition under different labels — that is "
              "rank-deficient and is rejected. A binned version of a continuous covariate "
              "(age and age_band) is fine."),
           _p("family", "string", False,
              "gaussian (default) | binomial | poisson | negativebinomial | gamma | "
              "inverse_gaussian. Pick from the OUTCOME type: counts/rates → poisson, "
              "overdispersed counts → negativebinomial, skewed positive money/time → gamma."),
           _p("link", "string", False,
              "identity | log | logit | probit | cloglog | inverse | sqrt. Defaults to the link "
              "that family is published with (gaussian→identity, binomial→logit, "
              "poisson/negativebinomial/gamma→log)."),
           _p("exposure_column", "column", False,
              "Person-time denominator for a RATE model, in the unit the rate is reported in. "
              "Enters as log(exposure) with its coefficient fixed at 1, which is what makes the "
              "ratios incidence-RATE ratios instead of count ratios. Log link only. Must be "
              "strictly positive."),
           _p("offset_column", "column", False,
              "Raw linear-predictor offset when you already logged the denominator yourself. "
              "Pass exposure_column OR offset_column, never both."),
           _p("weights_column", "column", False,
              "Per-row weights for a WEIGHTED outcome model — the `iptw` / `overlap_weight` "
              "column produced by iptw_weight / ate_weight. Set cov_type=\"HC0\" with it, "
              "because the model-based standard errors are too small for a weighted fit."),
           _p("cov_type", "string", False,
              "\"nonrobust\" (default) | \"HC0\" | \"HC1\" | \"cluster\". Use HC0 for weighted "
              "or overdispersed fits; \"cluster\" needs cluster_column."),
           _p("cluster_column", "column", False,
              "Grouping column for cluster-robust standard errors (hospital, registry, patient "
              "with repeated rows). Required when cov_type=\"cluster\"."),
           _p("alpha", "number", False,
              "Negative-binomial dispersion. Default 1.0 — GLM does not estimate it, so set it "
              "when the paper reports one."),
           _p("outcome_values", "list[value]", False,
              "ONLY for family=binomial: the value(s) counted as the POSITIVE class (=1), the "
              "rest are 0. For a 0/1 flag pass [1], never [1,0]. Ignored by other families, "
              "which read outcome_column as a number."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("reference_levels", "object", False,
              "{covariate: baseline category} for categorical predictors. Every ratio is measured "
              "against this level, so set it whenever the request names a reference category; "
              "otherwise the baseline is whichever level sorts first. Copy the level verbatim."),
       ]),

    # --- statistics: causal inference (ATT family) ---
    # Single version + loop version of each operation. When the protocol repeats
    # an operation along an axis (four estimators, six specifications, two
    # populations), bind the LOOP tool ONCE — never N sibling nodes.
    _t("att_weight", "statistics", "dataset",
       '{"treatment_column","treatment_values":[...],"covariates":[...],"where"?,'
       '"clip_bounds"?:[0.01,0.99],"trim"?:0.0,"restrict_to_overlap"?:false,'
       '"weight_column"?:"att_weight"}',
       "ATT propensity weights: OUTPUT is the full cohort + `propensity_score`, `att_weight` "
       "(1 for treated, PS/(1-PS) for controls) and `overlap_flag`. Targets the effect in the "
       "TREATED — use iptw_weight instead when the estimand is the ATE over everyone.",
       [
           _p("treatment_column", "column", True, "Column separating treated from control."),
           _p("treatment_values", "list[value]", True,
              "ONLY the TREATED arm's value(s) — control is everyone else, inferred. For a 0/1 "
              "flag pass [1], not [1,0]; for a labelled column pass just the treated label, verbatim."),
           _p("covariates", "list[column]", True,
              "Confounders the propensity model adjusts for (categoricals auto one-hot). "
              "EXCLUDE the treatment, the outcome and any identifier. Never empty."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("clip_bounds", "list[number]", False,
              "Clip the propensity score to [lower, upper], e.g. [0.01, 0.99], so a near-0/1 "
              "score cannot produce an enormous weight."),
           _p("trim", "number", False, _TRIM_PARAM),
           _p("restrict_to_overlap", "bool", False,
              "true drops the non-overlap rows from the OUTPUT; false (default) keeps every row "
              "and only flags them in `overlap_flag`. Either way this must match the propensity "
              "specification the run's ATT estimators use — a weighted cohort built on a "
              "different adjustment set than the effect it feeds is the same inconsistency one "
              "step earlier."),
           _p("weight_column", "string", False, "Name of the added weight column. Default \"att_weight\"."),
           _p("reference_levels", "object", False, "{categorical covariate: baseline level}. Optional."),
           _p("random_state", "integer", False, "Propensity-model seed. Default 42."),
           _p("imputation_column", "column", False,
              "Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default): the propensity "
              "model is fitted SEPARATELY inside each `_imputation` draw, every row keeps its own "
              "draw's score/weight, and the index survives in the OUTPUT so the estimator "
              "downstream can pool. Diagnostics are then per draw (patient scale)."),
       ]),
    _t("att_estimate", "statistics", "table",
       '{"treatment_column","treatment_values":[...],"covariates":[...],"outcome_column",'
       '"outcome_values"?:[...],"method"?:"ipw"|"gcomp"|"psm"|"aipw","where"?,'
       '"clip_bounds"?,"trim"?,"restrict_to_overlap"?,"n_bootstrap"?:200}',
       "ONE average treatment effect on the treated by ONE method: mu_treated (observed), "
       "mu_control (counterfactual), their difference and a bootstrap 95% CI. For SEVERAL "
       "methods use att_estimate_multi; for the same method under several analytic choices "
       "use att_sensitivity. " + _ATT_OUTPUT_NOTE,
       [
           _p("treatment_column", "column", True, "Column separating treated from control."),
           _p("treatment_values", "list[value]", True,
              "ONLY the TREATED arm's value(s), verbatim — never list every value."),
           _p("covariates", "list[column]", True, "Confounders to adjust for. Never empty."),
           _p("outcome_column", "column", True, "The outcome whose ATT is estimated."),
           _p("outcome_values", "list[value]", False,
              "Positive-class value(s) for a BINARY outcome, e.g. [\"Dead\"] — the effect is then a "
              "risk difference and `ratio` a risk ratio. OMIT for a numeric outcome, which is read "
              "as a number and gives a mean difference."),
           _p("method", "string", False,
              "\"ipw\" (default, ATT weights) | \"gcomp\" (outcome regression standardized to the "
              "treated) | \"psm\" (nearest-neighbour matching on the PS logit) | \"aipw\" (doubly "
              "robust — consistent if EITHER the propensity or the outcome model is right)."),
           _p("where", "string", False,
              "SQL boolean cohort filter. Optional. A COMPLETE-CASE filter here (e.g. "
              "\"menopause IS NOT NULL\") does not adjust for that covariate, it deletes "
              "whichever arm rarely records it — impute instead, or expect an infeasible row."),
           _p("clip_bounds", "list[number]", False, "Clip the propensity score, e.g. [0.01, 0.99]."),
           _p("trim", "number", False, _TRIM_PARAM),
           _p("restrict_to_overlap", "bool", False, _OVERLAP_PARAM),
           _p("match_ratio", "integer", False, "Controls per treated unit (method=\"psm\"). Default 1."),
           _p("caliper", "number", False,
              "Matching caliper in SDs of the PS logit (method=\"psm\"). Default 0.2 (Austin)."),
           _p("n_bootstrap", "integer", False,
              "Bootstrap replicates for the CI; the whole estimator (including the propensity fit) "
              "is resampled. Default 200. Set 0 to skip — do that for \"psm\" on a large cohort, "
              "where every replicate re-matches and the resampling dominates the runtime."),
           _p("reference_levels", "object", False, "{categorical covariate: baseline level}. Optional."),
           _p("random_state", "integer", False, "Seed. Default 42."),
           _p("imputation_column", "column", False, _MI_PARAM),
       ]),
    _t("att_estimate_multi", "statistics", "table",
       '{"treatment_column","treatment_values":[...],"covariates":[...],"outcome_column",'
       '"methods":["ipw","gcomp","psm","aipw"],"outcome_values"?:[...],"where"?,"n_bootstrap"?:200}',
       "LOOP over ESTIMATION METHODS: the same ATT computed by every method in `methods` against "
       "ONE identically-encoded cohort, stacked one row per method with each row's difference "
       "from the primary. Bind this ONCE instead of one att_estimate node per method.",
       [
           _p("methods", "list[value]", True,
              "The loop axis: any of \"ipw\", \"gcomp\", \"psm\", \"aipw\" — e.g. all four when the "
              "protocol asks whether the approaches agree. Defaults to all four if omitted."),
           _p("treatment_column", "column", True, "Column separating treated from control."),
           _p("treatment_values", "list[value]", True, "ONLY the TREATED arm's value(s), verbatim."),
           _p("covariates", "list[column]", True, "Confounders to adjust for. Never empty."),
           _p("outcome_column", "column", True, "The outcome whose ATT is estimated."),
           _p("outcome_values", "list[value]", False,
              "Positive-class value(s) for a binary outcome; omit for a numeric one."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("clip_bounds", "list[number]", False, "Clip the propensity score, e.g. [0.01, 0.99]."),
           _p("trim", "number", False, _TRIM_PARAM),
           _p("restrict_to_overlap", "bool", False, _OVERLAP_PARAM),
           _p("match_ratio", "integer", False, "Controls per treated unit for \"psm\". Default 1."),
           _p("caliper", "number", False, "Matching caliper in SDs of the PS logit. Default 0.2."),
           _p("n_bootstrap", "integer", False,
              "Replicates per method (default 200). Every method pays it, so lower it — or set 0 — "
              "when \"psm\" is in the list. On a MULTIPLY IMPUTED input the replicates are split "
              "across the draws, so the result reports `n_bootstrap_per_draw` alongside "
              "`n_bootstrap_total` and `n_bootstrap_requested` — a per-draw count smaller than "
              "what you asked for is expected, not a failure."),
           _p("reference_levels", "object", False, "{categorical covariate: baseline level}. Optional."),
           _p("random_state", "integer", False, "Seed. Default 42."),
           _p("imputation_column", "column", False, _MI_PARAM),
       ]),
    _t("att_sensitivity", "statistics", "table",
       '{"treatment_column","treatment_values":[...],"covariates":[...],"outcome_column",'
       '"specifications":[{"label","where"?,"covariates"?,"method"?,"trim"?,"clip_bounds"?},...],'
       '"outcome_values"?:[...],"n_bootstrap"?:200}',
       "LOOP over ANALYTIC SPECIFICATIONS: re-estimates the ATT under each override in "
       "`specifications` (different filter, covariate set, trimming, or estimator) and reports "
       "every result against the FIRST one. This is the \"is the conclusion robust to how we "
       "analysed it\" table — one node, not one node per specification. The node's OWN arguments "
       "are the primary analysis and must match the run's locked primary spec; each entry then "
       "changes ONE thing. A specification that leaves fewer than 10 patients in either arm is "
       "reported as an INFEASIBLE diagnostic row (`feasible` false, no effect) instead of an "
       "estimate, and every row carries the cohort flow (`n_loaded` / `n_complete` / "
       "`n_analyzed`) plus `covariates_unrecorded`.",
       [
           _p("specifications", "list[object]", True,
              "The loop axis: an ORDERED list of override objects; the FIRST is the PRIMARY "
              "analysis and should therefore override NOTHING. Each other entry may override "
              "this node's own arguments — {\"label\":\"Primary\"}, "
              "{\"label\":\"Trim 1%\",\"trim\":0.01}, {\"label\":\"Doubly robust\",\"method\":\"aipw\"}, "
              "{\"label\":\"Drop stage\",\"covariates\":[...]}, {\"label\":\"Complete cases\","
              "\"where\":\"...\"}. A `method` override must be one of \"ipw\", \"gcomp\", \"psm\", "
              "\"aipw\" VERBATIM — an unknown name (e.g. \"g_computation\") now fails the whole "
              "node up front rather than dropping that one row. Never empty."),
           _p("treatment_column", "column", True, "Column separating treated from control."),
           _p("treatment_values", "list[value]", True, "ONLY the TREATED arm's value(s), verbatim."),
           _p("covariates", "list[column]", True, "DEFAULT confounder set, overridable per specification."),
           _p("outcome_column", "column", True, "The outcome whose ATT is estimated."),
           _p("outcome_values", "list[value]", False, "Positive-class value(s) for a binary outcome."),
           _p("method", "string", False,
              "DEFAULT estimator for specifications that do not name one — \"ipw\" (default) | "
              "\"gcomp\" | \"psm\" | \"aipw\", verbatim."),
           _p("where", "string", False, "DEFAULT cohort filter, overridable per specification."),
           # These four ARE accepted and define the PRIMARY row, so they belong in the
           # catalog: a planner that cannot see them omits them, and the first
           # specification then silently estimates on a different population than the
           # sibling node the protocol says it matches.
           _p("clip_bounds", "list[number]", False,
              "DEFAULT propensity clip, e.g. [0.01, 0.99], overridable per specification."),
           _p("trim", "number", False, "DEFAULT trimming. " + _TRIM_PARAM),
           _p("restrict_to_overlap", "bool", False, "DEFAULT positivity handling. " + _OVERLAP_PARAM),
           _p("match_ratio", "integer", False, "Controls per treated unit for \"psm\". Default 1."),
           _p("caliper", "number", False, "Matching caliper in SDs of the PS logit. Default 0.2."),
           _p("n_bootstrap", "integer", False,
              "Replicates per specification (default 200) — this is paid once per row, so lower it "
              "for a long specification list."),
           _p("reference_levels", "object", False, "{categorical covariate: baseline level}. Optional."),
           _p("random_state", "integer", False, "Seed. Default 42."),
           _p("imputation_column", "column", False, _MI_PARAM),
       ]),
    # --- statistics: causal inference (ATE / ATO family) ---
    # Same shape as the ATT family, different ESTIMAND. Pick by the question, not
    # by convenience: "what did the treatment do to the patients who received it"
    # is att_*, "what would it do if everyone were treated" is ate_*. They are
    # different numbers whenever the effect varies across patients, and every row
    # carries `estimand` so a downstream table cannot conflate them.
    _t("ate_weight", "statistics", "dataset",
       '{"treatment_column","treatment_values":[...],"covariates":[...],'
       '"estimand"?:"ate"|"ato","where"?,"clip_bounds"?:[0.01,0.99],"trim"?:0.0,'
       '"restrict_to_overlap"?:false,"weight_column"?}',
       "ATE / ATO propensity weights: OUTPUT is the full cohort + `propensity_score`, "
       "`ate_weight` (1/PS treated, 1/(1-PS) control) or `overlap_weight` when "
       "estimand=ato, and `overlap_flag`. The population sibling of att_weight, on the "
       "SAME propensity fit the ate_* estimators use — prefer it over iptw_weight when "
       "the weighted cohort feeds an ate_estimate node.",
       [
           _p("treatment_column", "column", True, "Column separating treated from control."),
           _p("treatment_values", "list[value]", True,
              "ONLY the TREATED arm's value(s) — control is everyone else, inferred. For a 0/1 "
              "flag pass [1], not [1,0]; for a labelled column pass just the treated label, verbatim."),
           _p("covariates", "list[column]", True,
              "Confounders the propensity model adjusts for (categoricals auto one-hot). "
              "EXCLUDE the treatment, the outcome and any identifier. Never empty."),
           _p("estimand", "string", False, _ESTIMAND_PARAM),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("clip_bounds", "list[number]", False,
              "Clip the propensity score to [lower, upper], e.g. [0.01, 0.99]. MORE important "
              "here than for the ATT: 1/PS is unbounded, so one patient with PS=0.001 carries "
              "the weight of a thousand. Set it, or use estimand=\"ato\"."),
           _p("trim", "number", False, _TRIM_PARAM),
           _p("restrict_to_overlap", "bool", False,
              "true drops the non-overlap rows from the OUTPUT; false (default) keeps every row "
              "and only flags them in `overlap_flag`. Must match the propensity specification "
              "the run's ate_* estimators use."),
           _p("weight_column", "string", False,
              "Name of the added weight column. Defaults to \"ate_weight\", or "
              "\"overlap_weight\" when estimand=ato."),
           _p("reference_levels", "object", False, "{categorical covariate: baseline level}. Optional."),
           _p("random_state", "integer", False, "Propensity-model seed. Default 42."),
           _p("imputation_column", "column", False,
              "Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default): the propensity "
              "model is fitted SEPARATELY inside each draw and the index survives in the OUTPUT "
              "so the downstream estimator can pool."),
       ]),
    _t("ate_estimate", "statistics", "table",
       '{"treatment_column","treatment_values":[...],"covariates":[...],"outcome_column",'
       '"outcome_values"?:[...],"method"?:"ipw"|"gcomp"|"aipw","estimand"?:"ate"|"ato",'
       '"where"?,"clip_bounds"?,"trim"?,"restrict_to_overlap"?,"n_bootstrap"?:200}',
       "ONE average treatment effect in the WHOLE cohort (ATE) by ONE method: mu_treated "
       "and mu_control are BOTH counterfactual means over the same population, and their "
       "difference is the ATE. Use when the question is what treatment would do to "
       "everyone rather than to the patients who received it (that is att_estimate). "
       "`psm` is NOT available. For SEVERAL methods use ate_estimate_multi; for the same "
       "method under several analytic choices use ate_sensitivity. " + _ATT_OUTPUT_NOTE,
       [
           _p("treatment_column", "column", True, "Column separating treated from control."),
           _p("treatment_values", "list[value]", True,
              "ONLY the TREATED arm's value(s), verbatim — never list every value."),
           _p("covariates", "list[column]", True, "Confounders to adjust for. Never empty."),
           _p("outcome_column", "column", True, "The outcome whose ATE is estimated."),
           _p("outcome_values", "list[value]", False,
              "Positive-class value(s) for a BINARY outcome, e.g. [\"Dead\"] — the effect is then a "
              "risk difference and `ratio` a risk ratio. OMIT for a numeric outcome, which is read "
              "as a number and gives a mean difference."),
           _p("method", "string", False, _ATE_METHOD_PARAM),
           _p("estimand", "string", False, _ESTIMAND_PARAM),
           _p("where", "string", False,
              "SQL boolean cohort filter. Optional. A COMPLETE-CASE filter here does not adjust "
              "for that covariate, it deletes whichever arm rarely records it — impute instead."),
           _p("clip_bounds", "list[number]", False,
              "Clip the propensity score, e.g. [0.01, 0.99]. Set it: the ATE's 1/PS weights are "
              "unbounded, so a near-deterministic patient can dominate the estimate."),
           _p("trim", "number", False, _TRIM_PARAM),
           _p("restrict_to_overlap", "bool", False, _OVERLAP_PARAM),
           _p("n_bootstrap", "integer", False,
              "Bootstrap replicates for the CI; the whole estimator (including the propensity "
              "fit) is resampled. Default 200. Set 0 to skip."),
           _p("reference_levels", "object", False, "{categorical covariate: baseline level}. Optional."),
           _p("random_state", "integer", False, "Seed. Default 42."),
           _p("imputation_column", "column", False, _MI_PARAM),
       ]),
    _t("ate_estimate_multi", "statistics", "table",
       '{"treatment_column","treatment_values":[...],"covariates":[...],"outcome_column",'
       '"methods":["ipw","gcomp","aipw"],"estimand"?:"ate"|"ato","outcome_values"?:[...],'
       '"where"?,"n_bootstrap"?:200}',
       "LOOP over ESTIMATION METHODS: the same ATE computed by every method in `methods` "
       "against ONE identically-encoded cohort, stacked one row per method with each row's "
       "difference from the first. Bind this ONCE instead of one ate_estimate node per method.",
       [
           _p("methods", "list[value]", True,
              "The loop axis: any of \"ipw\", \"gcomp\", \"aipw\". Defaults to all three if "
              "omitted. \"psm\" is REJECTED — it only identifies the ATT."),
           _p("treatment_column", "column", True, "Column separating treated from control."),
           _p("treatment_values", "list[value]", True, "ONLY the TREATED arm's value(s), verbatim."),
           _p("covariates", "list[column]", True, "Confounders to adjust for. Never empty."),
           _p("outcome_column", "column", True, "The outcome whose ATE is estimated."),
           _p("outcome_values", "list[value]", False,
              "Positive-class value(s) for a binary outcome; omit for a numeric one."),
           _p("estimand", "string", False, _ESTIMAND_PARAM),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("clip_bounds", "list[number]", False, "Clip the propensity score, e.g. [0.01, 0.99]."),
           _p("trim", "number", False, _TRIM_PARAM),
           _p("restrict_to_overlap", "bool", False, _OVERLAP_PARAM),
           _p("n_bootstrap", "integer", False,
              "Replicates per method (default 200). On a MULTIPLY IMPUTED input the replicates "
              "are split across the draws, so a per-draw count smaller than what you asked for "
              "is expected, not a failure."),
           _p("reference_levels", "object", False, "{categorical covariate: baseline level}. Optional."),
           _p("random_state", "integer", False, "Seed. Default 42."),
           _p("imputation_column", "column", False, _MI_PARAM),
       ]),
    _t("ate_sensitivity", "statistics", "table",
       '{"treatment_column","treatment_values":[...],"covariates":[...],"outcome_column",'
       '"specifications":[{"label","where"?,"covariates"?,"method"?,"estimand"?,"trim"?,'
       '"clip_bounds"?},...],"outcome_values"?:[...],"n_bootstrap"?:200}',
       "LOOP over ANALYTIC SPECIFICATIONS: re-estimates the ATE under each override in "
       "`specifications` and reports every result against the FIRST one. The node's OWN "
       "arguments are the primary analysis and must match the run's locked primary spec; "
       "each entry then changes ONE thing. A specification that leaves fewer than 10 "
       "patients in either arm is reported as an INFEASIBLE diagnostic row.",
       [
           _p("specifications", "list[object]", True,
              "The loop axis: an ORDERED list of override objects; the FIRST is the PRIMARY "
              "analysis and should therefore override NOTHING. Each other entry may override "
              "this node's own arguments — {\"label\":\"Primary\"}, "
              "{\"label\":\"Trim 1%\",\"trim\":0.01}, {\"label\":\"Doubly robust\",\"method\":\"aipw\"}, "
              "{\"label\":\"Overlap population\",\"estimand\":\"ato\"}. A `method` override must be "
              "\"ipw\", \"gcomp\" or \"aipw\" VERBATIM and an `estimand` override \"ate\" or "
              "\"ato\" — anything else fails the whole node up front rather than dropping one row."),
           _p("treatment_column", "column", True, "Column separating treated from control."),
           _p("treatment_values", "list[value]", True, "ONLY the TREATED arm's value(s), verbatim."),
           _p("covariates", "list[column]", True, "DEFAULT confounder set, overridable per specification."),
           _p("outcome_column", "column", True, "The outcome whose ATE is estimated."),
           _p("outcome_values", "list[value]", False, "Positive-class value(s) for a binary outcome."),
           _p("method", "string", False, "DEFAULT estimator. " + _ATE_METHOD_PARAM),
           _p("estimand", "string", False, "DEFAULT estimand. " + _ESTIMAND_PARAM),
           _p("where", "string", False, "DEFAULT cohort filter, overridable per specification."),
           _p("clip_bounds", "list[number]", False,
              "DEFAULT propensity clip, e.g. [0.01, 0.99], overridable per specification."),
           _p("trim", "number", False, "DEFAULT trimming. " + _TRIM_PARAM),
           _p("restrict_to_overlap", "bool", False, "DEFAULT positivity handling. " + _OVERLAP_PARAM),
           _p("n_bootstrap", "integer", False,
              "Replicates per specification (default 200) — paid once per row, so lower it for a "
              "long specification list."),
           _p("reference_levels", "object", False, "{categorical covariate: baseline level}. Optional."),
           _p("random_state", "integer", False, "Seed. Default 42."),
           _p("imputation_column", "column", False, _MI_PARAM),
       ]),
    _t("covariate_balance", "statistics", "table",
       '{"treatment_column","treatment_values":[...],"covariates":[...],"weight_column"?,"where"?,'
       '"cat_var"?,"cont_var"?}',
       "Absolute standardized differences for ONE population: per covariate (and per LEVEL for "
       "categoricals) the treated/control means and their ASD, flagged at |ASD| < 0.1. Pass "
       "`weight_column` to score the weighted pseudo-population.",
       [
           _p("treatment_column", "column", True, "Column separating treated from control."),
           _p("treatment_values", "list[value]", True, "ONLY the TREATED arm's value(s), verbatim."),
           _p("covariates", "list[column]", True, "The covariates to check. Never empty."),
           _p("cat_var", "list[column]", False,
              "Force these covariates to be CATEGORICAL (one ASD row per level). Use for "
              "numeric codebook codes (T/N/grade/histology, 0/1 flags)."),
           _p("cont_var", "list[column]", False,
              "Force these covariates to be CONTINUOUS (one ASD row, no levels)."),
           _p("weight_column", "column", False,
              "Weight column from att_weight / iptw_weight. Omit for the CRUDE (unweighted) cohort."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("imputation_column", "column", False,
              "Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default): balance is a "
              "property of each COMPLETED dataset, so ASDs are computed inside every "
              "`_imputation` draw and averaged."),
       ]),
    _t("covariate_balance_multi", "statistics", "table",
       '{"treatment_column","treatment_values":[...],"covariates":[...],'
       '"scenarios":[{"label","weight_column"?,"where"?},...],"cat_var"?,"cont_var"?}',
       "LOOP over POPULATIONS: balance for every scenario, stacked, each row also carrying the "
       "FIRST scenario's ASD as `asd_reference`. The canonical before/after table is one node: "
       "[{\"label\":\"Crude\"},{\"label\":\"ATT-weighted\",\"weight_column\":\"att_weight\"}].",
       [
           _p("scenarios", "list[object]", True,
              "The loop axis: an ORDERED list of {\"label\", \"weight_column\"?, \"where\"?} "
              "populations; the FIRST is the reference the others are compared against. A scenario "
              "with no weight_column is the crude cohort. Never empty."),
           _p("treatment_column", "column", True, "Column separating treated from control."),
           _p("treatment_values", "list[value]", True, "ONLY the TREATED arm's value(s), verbatim."),
           _p("covariates", "list[column]", True, "The covariates to check. Never empty."),
           _p("cat_var", "list[column]", False,
              "Force these covariates to be CATEGORICAL (one ASD row per level)."),
           _p("cont_var", "list[column]", False,
              "Force these covariates to be CONTINUOUS (one ASD row, no levels)."),
           _p("where", "string", False, "DEFAULT cohort filter, overridable per scenario. Optional."),
           _p("imputation_column", "column", False,
              "Draw index of a MULTIPLY IMPUTED input. Leave EMPTY (the default): every "
              "scenario's ASDs are computed inside each `_imputation` draw and averaged."),
       ]),
    _t("evalue", "statistics", "table",
       '{"estimate":<number>,"ci_lower"?,"ci_upper"?,"scale"?:"rr"|"hr"|"or"|"rd","baseline_risk"?}',
       "E-value for ONE estimate: the minimum association an unmeasured confounder would need "
       "with BOTH exposure and outcome to explain it away, for the point estimate and for the "
       "confidence limit nearest the null. Takes NUMBERS from an earlier result, not columns.",
       [
           _p("estimate", "number", True,
              "The observed effect estimate, copied from the upstream result (e.g. a hazard ratio "
              "of 1.42). Not a column name."),
           _p("ci_lower", "number", False, "Lower confidence limit of that estimate."),
           _p("ci_upper", "number", False, "Upper confidence limit of that estimate."),
           _p("scale", "string", False,
              "\"rr\" (default) / \"hr\" are used as-is; \"or\" is converted as √OR unless "
              "`rare_outcome`; \"rd\" is a risk difference and REQUIRES `baseline_risk`."),
           _p("baseline_risk", "number", False,
              "Control-arm risk, required for scale=\"rd\" so the difference can be put on the "
              "ratio scale."),
           _p("rare_outcome", "bool", False,
              "For scale=\"or\": true uses the OR directly (rare-outcome approximation). Default false."),
       ]),
    _t("bias_sensitivity", "statistics", "table",
       '{"estimate":<number>,"ci_lower"?,"ci_upper"?,'
       '"scenarios"?:[{"label","rr_confounder_outcome","rr_confounder_exposure"},...],"grid"?:[...]}',
       "LOOP over UNMEASURED-CONFOUNDER STRENGTHS: bias-adjusts the estimate by the Ding & "
       "VanderWeele bounding factor in each scenario and reports whether the finding survives, "
       "locating the TIPPING POINT. Omit `scenarios` to sweep a symmetric `grid` instead.",
       [
           _p("estimate", "number", True, "The observed ratio estimate (RR/OR/HR), as a number."),
           _p("ci_lower", "number", False, "Lower confidence limit."),
           _p("ci_upper", "number", False, "Upper confidence limit."),
           _p("scenarios", "list[object]", False,
              "The loop axis: {\"label\", \"rr_confounder_outcome\", \"rr_confounder_exposure\"} per "
              "scenario — the confounder's association with the outcome and with the exposure."),
           _p("grid", "list[number]", False,
              "Used when `scenarios` is omitted: strengths applied to BOTH associations, e.g. "
              "[1.25,1.5,2.0,2.5,3.0]. Defaults to 1.1…3.0."),
       ]),
    _t("impute_missing", "statistics", "dataset",
       '{"columns":[...],"method"?:"mice"|"median"|"mode","n_imputations"?:1,"add_indicator"?:true,"where"?}',
       "Fill missing values and return the COMPLETED cohort. `method=\"mice\"` runs chained "
       "equations on the numeric columns (categoricals take the modal level). "
       "`n_imputations` > 1 is the loop axis: m draws stacked with an `_imputation` index (1…m). "
       "The estimators (att_*, covariate_balance*, table1) DETECT that index and run per draw "
       "with Rubin pooling on their own — do not add a node to split or average the stack.",
       [
           _p("columns", "list[column]", True,
              "The variables to impute. Give MICE at least two numeric columns — with one there "
              "is nothing to condition on and every draw is the same mean fill."),
           _p("method", "string", False,
              "\"mice\" (default, sklearn IterativeImputer) | \"median\" | \"mode\". The simple "
              "fills are deterministic, so n_imputations is forced to 1 for them."),
           _p("n_imputations", "integer", False,
              "Number of completed copies (default 1). Above 1 the output is m stacked copies of "
              "the SAME patients with an `_imputation` column — m× the rows, NOT m× the patients. "
              "The estimator downstream handles that index; a hand-written SQL node reading this "
              "table must group by it or filter to one draw."),
           _p("add_indicator", "bool", False,
              "Keep a `<column>_missing` 0/1 flag per imputed column. Default true."),
           _p("max_iter", "integer", False, "MICE iterations. Default 10."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("random_state", "integer", False, "Seed. Default 42."),
       ]),

    # --- modeling (published calculator — fixed coefficients, nothing fitted) ---
    _t("predict_breast_os", "modeling", "dataset",
       '{"age_start","size","grade","nodes","er","her2"?,"ki67"?,"screen"?,'
       '"generation"?,"horm"?,"traz"?,"bis"?,"year"?:10,"on_invalid"?:"skip",'
       '"allow_unknown_grade_er_neg"?:false,"where"?}',
       "PREDICT Breast v2.1 (Wishart et al.) scored for EVERY patient in the cohort: "
       "`year`-year survival WITH SURGERY ALONE, plus the incremental benefit of "
       "hormone therapy, chemotherapy, trastuzumab and bisphosphonate, appended to the "
       "cohort it read. The survival column is the untreated baseline — survival under "
       "treatment is that column plus the benefits. "
       "A PUBLISHED calculator with fixed coefficients — it fits NOTHING on this "
       "cohort, so it needs no outcome column, no train/test split and no CV, and it "
       "must never be described as a model trained here. "
       "Each of the twelve clinical variables is bound to a COLUMN NAME or pinned to a "
       "CONSTANT (a cohort with no bisphosphonate column passes bis=0), and every "
       "binding is reported. Inputs must already be CODED as stated below — recode "
       "'Positive'/'Negative' in an upstream `sql` node (CASE WHEN … THEN 1 …); a "
       "text column is refused with its observed values. "
       "This is v2.1, NOT the v3.0 model on breast.predict.nhs.uk: label it in the write-up.",
       [
           _p("age_start", "column|number", True,
              "Age at diagnosis in YEARS. The model domain is 25-85; a patient outside "
              "it is reported as ineligible, not clipped."),
           _p("size", "column|number", True,
              "Invasive tumour size in MILLIMETRES (not cm — 2.0 would be read as a "
              "2 mm tumour). Must be > 0."),
           _p("grade", "column|number", True,
              "Tumour grade coded 1 / 2 / 3, or 9 for unknown. WARNING: for an "
              "ER-NEGATIVE patient v2.1 scores unknown grade as grade 1 (the most "
              "favourable), which is optimistic by tens of percentage points — those "
              "rows are refused unless `allow_unknown_grade_er_neg` is set."),
           _p("nodes", "column|number", True,
              "Number of POSITIVE nodes as a whole number (0 allowed). Not a "
              "N-stage label and not a yes/no flag."),
           _p("er", "column|number", True,
              "ER status coded 1 = positive, 0 = negative. Selects the model's whole "
              "ER branch (different baseline hazard and different coefficients), and "
              "hormone benefit is zero when 0 — so a wrong coding is not a small error."),
           _p("her2", "column|number", False,
              "HER2 coded 1 = positive, 0 = negative, 9 = unknown. Defaults to 9, "
              "which sets its coefficient to zero — between + and −. Trastuzumab "
              "benefit is zero unless HER2 = 1."),
           _p("ki67", "column|number", False,
              "KI67 coded 1 = positive, 0 = negative, 9 = unknown. Default 9. Only "
              "affects ER-positive patients in v2.1."),
           _p("screen", "column|number", False,
              "Detection: 0 = clinically detected, 1 = screen detected, 2 = unknown "
              "(default; imputed to the cohort proportion 0.204 as in the model)."),
           _p("generation", "column|number", False,
              "Chemotherapy generation: 0 = none (default), 2 = 2nd generation, "
              "3 = 3rd generation. " + _PREDICT_RX_NOTE),
           _p("horm", "column|number", False,
              "Hormone therapy: 1 / 0. Default 0. " + _PREDICT_RX_NOTE),
           _p("traz", "column|number", False,
              "Trastuzumab: 1 / 0. Default 0. Also needs HER2 = 1. "
              + _PREDICT_RX_NOTE),
           _p("bis", "column|number", False,
              "Bisphosphonate: 1 / 0. Default 0. " + _PREDICT_RX_NOTE),
           _p("year", "integer", False,
              "Horizon in years, 1-15. Default 10. It names the output columns "
              "(`predict_os_10y`), so two nodes at different horizons can be joined."),
           _p("on_invalid", "string", False,
              "\"skip\" (default) scores whoever it can and records the reason for the "
              "rest in `predict_ineligible`; \"fail\" refuses the whole node if ANY "
              "patient is out of domain. Use \"fail\" when the protocol requires the "
              "full cohort to be scored."),
           _p("allow_unknown_grade_er_neg", "bool", False,
              "Score ER-negative patients whose grade is unknown, reproducing the v2.1 "
              "behaviour of treating them as grade 1. Default false. Only set it "
              "deliberately, and say so in the write-up."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
       ]),

    # --- modeling (scikit-learn linear classifiers — FIT once, write scores) ---
    _t("LogisticRegression", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"penalty"?:"l2","C"?:1.0,"solver"?,"l1_ratio"?,"max_iter"?:2000,'
       '"class_weight"?,"split_column"?,"reference_levels"?:{...},"where"?}',
       "sklearn LogisticRegression (logit / MaxEnt). " + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("penalty", "string", False, "\"l2\" (default) | \"l1\" | \"elasticnet\" | \"none\"."),
           _p("C", "number", False, "Inverse regularization strength. Default 1.0."),
           _p("solver", "string", False,
              "Default lbfgs (l2/none) or saga (elasticnet/l1)."),
           _p("l1_ratio", "number", False, "Elastic-net mix; only when penalty=elasticnet."),
           _p("max_iter", "integer", False, "Solver iterations. Default 2000."),
       ] + _LINEAR_CLF_COMMON),
    _t("LogisticRegressionCV", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"penalty"?:"l2","cv"?:5,"solver"?,"l1_ratio"?,"max_iter"?:2000,'
       '"class_weight"?,"split_column"?,"reference_levels"?:{...},"where"?}',
       "sklearn LogisticRegressionCV — C / λ chosen by CV, then the same scored "
       "dataset contract as LogisticRegression. " + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("penalty", "string", False, "\"l2\" (default) | \"l1\" | \"elasticnet\"."),
           _p("cv", "integer", False, "Folds for C / λ selection. Default 5."),
           _p("solver", "string", False, "Default lbfgs (l2) or saga (elasticnet)."),
           _p("l1_ratio", "number", False, "Elastic-net mix; only when penalty=elasticnet."),
           _p("max_iter", "integer", False, "Solver iterations. Default 2000."),
       ] + _LINEAR_CLF_COMMON),
    _t("PassiveAggressiveClassifier", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"C"?:1.0,"max_iter"?:2000,"split_column"?,"reference_levels"?:{...},"where"?}',
       "sklearn PassiveAggressiveClassifier. No predict_proba — writes "
       "`predicted_score` (decision) + `predicted_class`. " + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("C", "number", False, "Maximum step size (regularization). Default 1.0."),
           _p("max_iter", "integer", False, "Epochs. Default 2000."),
           _p("predictors", "list[column]", True, "Predictor columns. Never empty."),
           _p("split_column", "column", False, "Fit on train, score every row."),
           _p("reference_levels", "object", False, "{covariate: baseline category}."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("random_state", "integer", False, "Seed. Default 42."),
       ]),
    _t("Perceptron", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"penalty"?,"alpha"?:0.0001,"max_iter"?:2000,"class_weight"?,'
       '"split_column"?,"reference_levels"?:{...},"where"?}',
       "sklearn linear Perceptron. No predict_proba — writes `predicted_score` + "
       "`predicted_class`. " + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("penalty", "string", False, "Optional L2/L1/elasticnet penalty on the weights."),
           _p("alpha", "number", False, "Penalty multiplier. Default 0.0001."),
           _p("max_iter", "integer", False, "Epochs. Default 2000."),
       ] + _LINEAR_CLF_COMMON),
    _t("RidgeClassifier", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"alpha"?:1.0,"class_weight"?,"split_column"?,"reference_levels"?:{...},"where"?}',
       "sklearn RidgeClassifier (ridge regression as a classifier). Writes "
       "`predicted_score` + `predicted_class`. " + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("alpha", "number", False, "L2 strength. Default 1.0."),
       ] + _LINEAR_CLF_COMMON),
    _t("RidgeClassifierCV", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"alphas"?:[0.1,1,10],"cv"?,"class_weight"?,"split_column"?,'
       '"reference_levels"?:{...},"where"?}',
       "sklearn RidgeClassifierCV — α chosen by CV, then the scored-dataset "
       "contract. " + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("alphas", "list[number]", False, "α grid. Default [0.1, 1, 10]."),
           _p("cv", "integer", False, "CV folds for α; omit for GCV-style default."),
       ] + _LINEAR_CLF_COMMON),
    _t("SGDClassifier", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"loss"?:"hinge","penalty"?:"l2","alpha"?:0.0001,"l1_ratio"?:0.15,'
       '"max_iter"?:2000,"learning_rate"?:"optimal","eta0"?:0,"class_weight"?,'
       '"split_column"?,"reference_levels"?:{...},"where"?}',
       "sklearn SGDClassifier (linear SVM / logistic / … via `loss`). "
       "`loss=\"log_loss\"` (or modified_huber) is required for "
       "`predicted_probability`; hinge writes `predicted_score` only. "
       + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("loss", "string", False,
              "\"hinge\" (default, linear SVM) | \"log_loss\" (logistic, has "
              "predict_proba) | \"modified_huber\" | \"squared_hinge\" | \"perceptron\"."),
           _p("penalty", "string", False, "\"l2\" (default) | \"l1\" | \"elasticnet\"."),
           _p("alpha", "number", False, "Regularization multiplier. Default 0.0001."),
           _p("l1_ratio", "number", False, "Elastic-net mix. Default 0.15."),
           _p("max_iter", "integer", False, "Epochs. Default 2000."),
           _p("learning_rate", "string", False, "\"optimal\" (default) | \"constant\" | \"invscaling\" | \"adaptive\"."),
           _p("eta0", "number", False, "Initial learning rate when not optimal. Default 0."),
       ] + _LINEAR_CLF_COMMON),
    _t("SGDOneClassSVM", "modeling", "dataset",
       '{"predictors":[...],"nu"?:0.5,"max_iter"?:2000,"split_column"?,'
       '"reference_levels"?:{...},"where"?}',
       "sklearn SGDOneClassSVM — linear one-class SVM (unsupervised novelty). "
       "NO outcome. OUTPUT is the input cohort plus `predicted_score` "
       "(decision_function) and `predicted_class` (+1 inlier / −1 outlier). "
       "Fit once; evaluation reads the score column.",
       [
           _p("predictors", "list[column]", True, "Feature columns. Never empty. No outcome."),
           _p("nu", "number", False, "Approximate outlier fraction in (0, 1]. Default 0.5."),
           _p("max_iter", "integer", False, "Epochs. Default 2000."),
           _p("split_column", "column", False, "When set, fit on train rows only, score everyone."),
           _p("reference_levels", "object", False, "{covariate: baseline category}."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("random_state", "integer", False, "Seed. Default 42."),
       ]),

    # --- modeling (sklearn SVM / trees / boosting — FIT once, write scores) ---
    _t("SVC", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"C"?:1.0,"kernel"?:"rbf","gamma"?:"scale","class_weight"?,'
       '"split_column"?,"reference_levels"?:{...},"where"?}',
       "sklearn SVC (C-Support Vector Classification). probability=True so the "
       "output includes predicted_probability. " + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("C", "number", False, "Inverse regularization. Default 1.0."),
           _p("kernel", "string", False, "\"rbf\" (default) | \"linear\" | \"poly\" | \"sigmoid\"."),
           _p("gamma", "string", False, "Kernel coefficient: \"scale\" (default) | \"auto\" | a float."),
       ] + _LINEAR_CLF_COMMON),
    _t("LinearSVC", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"C"?:1.0,"max_iter"?:2000,"class_weight"?,"split_column"?,'
       '"reference_levels"?:{...},"where"?}',
       "sklearn LinearSVC — linear SVM. No predict_proba; writes predicted_score "
       "+ predicted_class. " + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("C", "number", False, "Inverse regularization. Default 1.0."),
           _p("max_iter", "integer", False, "Solver iterations. Default 2000."),
       ] + _LINEAR_CLF_COMMON),
    _t("NuSVC", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"nu"?:0.5,"kernel"?:"rbf","gamma"?:"scale","class_weight"?,'
       '"split_column"?,"reference_levels"?:{...},"where"?}',
       "sklearn NuSVC (ν-SVM). Writes predicted_probability. " + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("nu", "number", False, "ν in (0, 1] — upper bound on training error. Default 0.5."),
           _p("kernel", "string", False, "\"rbf\" (default) | \"linear\" | \"poly\" | \"sigmoid\"."),
           _p("gamma", "string", False, "Kernel coefficient: \"scale\" (default) | \"auto\" | a float."),
       ] + _LINEAR_CLF_COMMON),
    _t("DecisionTreeClassifier", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"max_depth"?,"min_samples_split"?:2,"min_samples_leaf"?:1,"class_weight"?,'
       '"split_column"?,"reference_levels"?:{...},"where"?}',
       "sklearn DecisionTreeClassifier. Writes predicted_probability + feature "
       "importances. " + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("max_depth", "integer", False, "Max tree depth. Omit to grow until pure leaves."),
           _p("min_samples_split", "integer", False, "Min samples to split. Default 2."),
           _p("min_samples_leaf", "integer", False, "Min samples in a leaf. Default 1."),
       ] + _LINEAR_CLF_COMMON),
    _t("ExtraTreeClassifier", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"max_depth"?,"min_samples_split"?:2,"min_samples_leaf"?:1,"class_weight"?,'
       '"split_column"?,"reference_levels"?:{...},"where"?}',
       "sklearn ExtraTreeClassifier (single extremely randomized tree). "
       + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("max_depth", "integer", False, "Max tree depth. Omit to grow until pure leaves."),
           _p("min_samples_split", "integer", False, "Min samples to split. Default 2."),
           _p("min_samples_leaf", "integer", False, "Min samples in a leaf. Default 1."),
       ] + _LINEAR_CLF_COMMON),
    _t("RandomForestClassifier", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"n_estimators"?:200,"max_depth"?,"min_samples_split"?:2,"min_samples_leaf"?:1,'
       '"class_weight"?,"split_column"?,"reference_levels"?:{...},"where"?}',
       "sklearn RandomForestClassifier. Writes predicted_probability + importances. "
       + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("n_estimators", "integer", False, "Number of trees. Default 200."),
           _p("max_depth", "integer", False, "Max tree depth. Omit for fully grown trees."),
           _p("min_samples_split", "integer", False, "Min samples to split. Default 2."),
           _p("min_samples_leaf", "integer", False, "Min samples in a leaf. Default 1."),
       ] + _LINEAR_CLF_COMMON),
    _t("ExtraTreesClassifier", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"n_estimators"?:200,"max_depth"?,"min_samples_split"?:2,"min_samples_leaf"?:1,'
       '"class_weight"?,"split_column"?,"reference_levels"?:{...},"where"?}',
       "sklearn ExtraTreesClassifier (extremely randomized forest). "
       + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("n_estimators", "integer", False, "Number of trees. Default 200."),
           _p("max_depth", "integer", False, "Max tree depth. Omit for fully grown trees."),
           _p("min_samples_split", "integer", False, "Min samples to split. Default 2."),
           _p("min_samples_leaf", "integer", False, "Min samples in a leaf. Default 1."),
       ] + _LINEAR_CLF_COMMON),
    _t("AdaBoostClassifier", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"n_estimators"?:50,"learning_rate"?:1.0,"split_column"?,'
       '"reference_levels"?:{...},"where"?}',
       "sklearn AdaBoostClassifier. Writes predicted_probability. " + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("n_estimators", "integer", False, "Boosting rounds. Default 50."),
           _p("learning_rate", "number", False, "Shrinkage. Default 1.0."),
           _p("predictors", "list[column]", True, "Predictor columns. Never empty."),
           _p("split_column", "column", False, "Fit on train, score every row."),
           _p("reference_levels", "object", False, "{covariate: baseline category}."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("random_state", "integer", False, "Seed. Default 42."),
       ]),
    _t("GradientBoostingClassifier", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"n_estimators"?:200,"learning_rate"?:0.1,"max_depth"?:3,'
       '"min_samples_split"?:2,"min_samples_leaf"?:1,"split_column"?,'
       '"reference_levels"?:{...},"where"?}',
       "sklearn GradientBoostingClassifier. Writes predicted_probability. "
       + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("n_estimators", "integer", False, "Boosting rounds. Default 200."),
           _p("learning_rate", "number", False, "Shrinkage. Default 0.1."),
           _p("max_depth", "integer", False, "Max tree depth. Default 3."),
           _p("min_samples_split", "integer", False, "Min samples to split. Default 2."),
           _p("min_samples_leaf", "integer", False, "Min samples in a leaf. Default 1."),
           _p("predictors", "list[column]", True, "Predictor columns. Never empty."),
           _p("split_column", "column", False, "Fit on train, score every row."),
           _p("reference_levels", "object", False, "{covariate: baseline category}."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("random_state", "integer", False, "Seed. Default 42."),
       ]),
    _t("HistGradientBoostingClassifier", "modeling", "dataset",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"max_iter"?:200,"learning_rate"?:0.1,"max_depth"?,"class_weight"?,'
       '"split_column"?,"reference_levels"?:{...},"where"?}',
       "sklearn HistGradientBoostingClassifier (histogram GB — the fast sklearn "
       "booster). Writes predicted_probability. " + _LINEAR_CLF_OUT,
       _LINEAR_CLF_OUTCOME + [
           _p("max_iter", "integer", False, "Boosting rounds. Default 200."),
           _p("learning_rate", "number", False, "Shrinkage. Default 0.1."),
           _p("max_depth", "integer", False, "Max tree depth. Omit for no limit."),
       ] + _LINEAR_CLF_COMMON),

    _t("ml_train_test_split", "modeling", "dataset",
       '{"test_size"?:0.3,"stratify_column"?,"split_column"?:"split","random_state"?:42,"where"?}',
       "Adds a `split` column (`train` / `test`) only — no fitting. Chain a model "
       "tool next (LogisticRegression, RandomForestClassifier, …) with "
       "split_column=\"split\" so it fits on train and scores every row. Then "
       "point eval tools at that scored dataset.",
       [
           _p("test_size", "number", False,
              "Fraction of rows in the TEST set, in (0, 1). Default 0.3."),
           _p("stratify_column", "column", False,
              "Column to stratify the split on — usually the outcome, so train and "
              "test keep the same class mix. Optional; omit for a simple random split."),
           _p("split_column", "string", False,
              "Name of the added label column. Default \"split\" with values "
              "\"train\" and \"test\"."),
           _p("random_state", "integer", False, "Split seed. Default 42."),
           _p("where", "string", False, "SQL boolean cohort filter before splitting. Optional."),
       ]),
    _t("ml_classifier_performance", "modeling", "table",
       '{"outcome_column","outcome_values":[...],"probability_column"?:"predicted_probability",'
       '"split_column"?,"split_value"?:"test","n_bootstrap"?:500,"threshold"?,"where"?}',
       "Does not fit. Reads predicted_probability from the upstream model node. "
       "AUC / Brier / sens / spec / PPV / NPV + bootstrap CI on the existing (y, p) "
       "pairs. When split_column is set, test rows only. Not optimism correction — "
       "use ml_cv_performance for out-of-fold estimates.",
       _EVAL_COMMON + [
           _p("n_bootstrap", "integer", False,
              "Bootstrap reps of the existing (y, p) pairs. Default 500. Does not refit."),
           _p("threshold", "number", False,
              "Probability cut for sens/spec/PPV/NPV. Omit to use the Youden-optimal cut."),
       ]),
    _t("ml_roc_curve", "modeling", "figure",
       '{"outcome_column","outcome_values":[...],"probability_column"?:"predicted_probability",'
       '"split_column"?,"where"?,"title"?}',
       "Does not fit. Reads predicted_probability from the upstream model node. "
       "ROC curve (sklearn roc_curve(y, p)) with AUC, chance diagonal, Youden point.",
       _EVAL_COMMON + [
           _p("title", "string", False, "Figure title. Optional."),
       ]),
    _t("ml_calibration_curve", "modeling", "figure",
       '{"outcome_column","outcome_values":[...],"probability_column"?:"predicted_probability",'
       '"n_bins"?:10,"split_column"?,"where"?,"title"?}',
       "Does not fit. Reads predicted_probability from the upstream model node. "
       "Calibration curve: observed vs mean-predicted event rate in n_bins quantile groups.",
       _EVAL_COMMON + [
           _p("n_bins", "integer", False, "Quantile bins for the calibration groups. Default 10."),
           _p("title", "string", False, "Figure title. Optional."),
       ]),
    _t("ml_decision_curve", "modeling", "figure",
       '{"outcome_column","outcome_values":[...],"probability_column"?:"predicted_probability",'
       '"thresholds"?:[...],"split_column"?,"where"?,"title"?}',
       "Does not fit. Reads predicted_probability from the upstream model node. "
       "Decision-curve analysis: net benefit vs treat-all / treat-none.",
       _EVAL_COMMON + [
           _p("thresholds", "list[number]", False,
              "Threshold probabilities to evaluate (each in 0..1). Default 0.01…0.99 step 0.01."),
           _p("title", "string", False, "Figure title. Optional."),
       ]),
    _t("ml_reclassification", "modeling", "table",
       '{"outcome_column","outcome_values":[...],"probability_column"?:"predicted_probability",'
       '"baseline_probability_column"?,"baseline_source"?,"id_column"?,'
       '"nri_thresholds"?:[...],"where"?}',
       "Does not fit. IDI / NRI from two already-scored probability columns on the "
       "same table, or two scored datasets joined on id_column (baseline_source). "
       "Join two model outputs with sql first if you prefer one table.",
       [
           _p("outcome_column", "column", True, "Binary outcome column."),
           _p("outcome_values", "list[value]", True, "Positive-class value(s), verbatim."),
           _p("probability_column", "column", False,
              "FULL model's predicted-probability column. Default \"predicted_probability\"."),
           _p("baseline_probability_column", "column", False,
              "REDUCED model's probability column on the SAME table. Required unless "
              "baseline_source is set."),
           _p("baseline_source", "string", False,
              "Second scored dataset (another model node). Joined to `source` on id_column. "
              "Both columns may be named predicted_probability."),
           _p("id_column", "column", False,
              "Join key when baseline_source is set. Required in that case."),
           _p("nri_thresholds", "list[number]", False,
              "Probability cuts for category-based NRI (each in 0..1). Optional; "
              "continuous NRI is always reported."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("split_column", "column", False, "If set, read only split_value rows (default test)."),
           _p("split_value", "string", False, "Which split arm to read. Default \"test\"."),
       ]),
    _t("ml_cv_performance", "modeling", "table",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"model":"LogisticRegressionCV|RandomForestClassifier|…","n_splits"?:5,"where"?}',
       "Learning procedure, not evaluation of a fitted model: refits ONE model key "
       "on each stratified fold and reports OOF AUC / Brier / calibration / "
       "threshold metrics. Use when the protocol says cross-validation.",
       [
           _p("outcome_column", "column", True, "Binary outcome column."),
           _p("outcome_values", "list[value]", True, "Positive-class value(s), verbatim."),
           _p("predictors", "list[column]", True, "Predictor columns. Never empty."),
           _p("model", "string", False, _ML_MODEL_PARAM),
           _p("n_splits", "integer", False, "Stratified CV folds. Default 5."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("reference_levels", "object", False, "{categorical predictor: baseline level}. Optional."),
       ]),
    _t("ml_compare", "modeling", "table",
       '{"outcome_column","outcome_values":[...],"predictors":[...],'
       '"models":["LogisticRegressionCV","RandomForestClassifier","GradientBoostingClassifier"],'
       '"n_splits"?:5,"where"?}',
       "Learning procedure: every key in `models` is refit on the SAME folds and "
       "the same design matrix, ranked by OOF AUC. Bind this ONCE instead of one "
       "ml_cv_performance node per algorithm.",
       [
           _p("models", "list[value]", True,
              "Two or more catalog keys — sklearn class names "
              "(LogisticRegression, RandomForestClassifier, …) or legacy aliases "
              "(elasticnet_logistic, logistic, random_forest, gradient_boosting). "
              "Defaults to LogisticRegressionCV + RandomForestClassifier + "
              "GradientBoostingClassifier."),
           _p("outcome_column", "column", True, "Binary outcome column."),
           _p("outcome_values", "list[value]", True, "Positive-class value(s), verbatim."),
           _p("predictors", "list[column]", True, "Predictor columns, shared by every model. Never empty."),
           _p("n_splits", "integer", False, "Stratified CV folds, shared by every model. Default 5."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("reference_levels", "object", False, "{categorical predictor: baseline level}. Optional."),
       ]),

    # --- survival ---
    _t("kaplan_meier", "survival", "figure",
       '{"time_column","event_column","event_values":[...],"group_by"?:[...],"where"?}',
       "Kaplan-Meier curve (lifelines) per group; OUTPUT is the life-table + a step survival-curve figure.",
       [
           _p("time_column", "column", True, "Follow-up time (numeric, e.g. survival months)."),
           _p("event_column", "column", True, "Column recording the outcome status."),
           _p("event_values", "list[value]", True,
              "Value(s) of event_column that count as an EVENT/death (=1), copied verbatim, e.g. "
              "[\"Dead\"]; everything else is censored. Do NOT list censoring values here."),
           _p("group_by", "list[column]", False, "Fit one curve per combination of these columns. Optional."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
       ]),
    _t("competing_risk_cif", "survival", "figure",
       '{"duration_column","event_column","event_values":[...],"competing_values":[...],'
       '"group_column"?,"group_values"?:[...],"cif_time_points"?:[60],"weights_column"?,'
       '"both_causes"?:true,"where"?}',
       "Competing-risk cumulative incidence (Aalen-Johansen). Use INSTEAD of kaplan_meier when "
       "patients can die of an unrelated cause — 1-KM censors those deaths and overstates the risk.",
       [
           _p("duration_column", "column", True, "Follow-up time (numeric, e.g. survival months)."),
           _p("event_column", "column", True,
              "Column recording the CAUSE/outcome status, e.g. a cause-specific death classification."),
           _p("event_values", "list[value]", True,
              "Value(s) marking the EVENT OF INTEREST (cause 1), verbatim — e.g. death from the "
              "cancer under study."),
           _p("competing_values", "list[value]", True,
              "Value(s) marking the COMPETING event (cause 2), verbatim — e.g. death from another "
              "cause. Required: with no competing event this reduces to 1-KM, so use kaplan_meier."),
           _p("group_column", "column", False, "Estimate one CIF per level of this column (e.g. treatment arm)."),
           _p("group_values", "list[value]", False, "Restrict to these group_column levels (verbatim)."),
           _p("cif_time_points", "list[number]", False,
              "Horizons at which to report the CIF, in the duration column's OWN unit — e.g. [60] "
              "for 5-year cumulative incidence. With exactly two groups the absolute risk "
              "difference between them is reported as well."),
           _p("weights_column", "column", False,
              "Weight column for an ADJUSTED CIF — the 'iptw' column from iptw_weight, with that "
              "weighted cohort as this node's input."),
           _p("both_causes", "bool", False,
              "Also estimate/plot the competing event's CIF (default true), as competing-risk "
              "figures normally show both."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("title", "string", False, "Figure title. Optional."),
       ]),
    _t("logrank_test", "survival", "table",
       '{"time_column","event_column","event_values":[...],"group_column","group_values"?:[A,B],"where"?,"weightings"?}',
       "Log-rank test for whether survival differs between two arms (one-row result table).",
       [
           _p("time_column", "column", True, "Follow-up time (numeric)."),
           _p("event_column", "column", True, "Column recording the outcome status."),
           _p("event_values", "list[value]", True,
              "Value(s) of event_column that count as an EVENT (=1), verbatim; the rest are censored."),
           _p("group_column", "column", True, "Column defining the two arms whose survival is compared."),
           _p("group_values", "list[value]", False,
              "The TWO arm labels to compare (verbatim), required when group_column has >2 labels."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("weightings", "string", False, "\"wilcoxon\" | \"tarone-ware\" | \"peto\" (default: unweighted log-rank)."),
       ]),
    _t("cox_ph", "survival", "table",
       '{"duration_column","event_column","event_values":[...],"covariates":[...],"strata"?:[...],'
       '"where"?,"weights_column"?,"robust"?,"cluster_column"?,"interactions"?:["A * B"],'
       '"reference_levels"?:{"column":"baseline level"},"penalizer"?}',
       "MULTIVARIABLE Cox proportional-hazards regression (lifelines) — ONE model over ALL the "
       "covariates at once. For separate one-covariate-at-a-time models use cox_ph_univariate "
       "instead. For SEPARATE exposure fits WITHIN each subgroup category (Table 5 / forest of "
       "subgroup HRs) use cox_ph_subgroup — do NOT misuse strata (baseline only) or interactions "
       "for that. Supports IPTW-weighted fits, robust/clustered variance and interaction terms. "
       "Returns ONE long table "
       "(term_type/term/group/coef/se/hazard_ratio/hr_lower95/hr_upper95/statistic/df/p) whose "
       "term_type is 'coefficient' (per design term), 'reference' (each categorical covariate's "
       "baseline level, hazard_ratio=1.0), 'contrast' (with interactions: the focal "
       "exposure's HR INSIDE each modifier level, one row per level, `group` = the level) or "
       "'interaction_wald' (the joint test over an interaction block). Stratum-specific HRs and "
       "the global interaction p-value are therefore ALREADY computed — a downstream node only "
       "filters/renames these rows and must never try to recompute them. A multiply imputed "
       "input is fitted draw by draw and pooled by Rubin's rules without being asked.",
       [
           _p("duration_column", "column", True, "Follow-up time (numeric)."),
           _p("event_column", "column", True, "Column recording the outcome status."),
           _p("event_values", "list[value]", True,
              "Value(s) of event_column that count as an EVENT (=1), verbatim; the rest are censored."),
           _p("covariates", "list[column]", True,
              "Adjustment columns (categoricals auto one-hot). EXCLUDE duration/event columns and "
              "identifiers. Never empty."),
           _p("strata", "list[column]", False, "Columns to stratify the baseline hazard by. Optional."),
           _p("where", "string", False,
              "SQL boolean cohort filter. Do NOT add 'IS NOT NULL' guards for the covariates: "
              + _COMPLETE_CASE),
           _p("weights_column", "column", False,
              "Per-patient weight column for an IPTW-WEIGHTED Cox — set it to the 'iptw' column "
              "produced by iptw_weight and make that weighted cohort this node's input. Robust "
              "variance is enabled automatically, as non-integer weights otherwise understate the SEs."),
           _p("robust", "bool", False,
              "Robust (sandwich) standard errors. Defaults to true when weights_column is set."),
           _p("cluster_column", "column", False,
              "Column identifying correlated clusters (registry, hospital…) for clustered robust SEs."),
           _p("interactions", "list[string]", False,
              "Effect-modification terms, each naming TWO columns that are also in `covariates`, "
              "e.g. [\"Radiation recode * Age recode\"]. Write the EXPOSURE first and the effect "
              "MODIFIER second. Each term yields both `contrast` rows (the exposure's HR within "
              "every modifier level, computed from the full covariance matrix) and one "
              "`interaction_wald` row (the joint test over the whole block — the only valid "
              "p-value when a categorical interaction spans several dummy columns)."),
           _p("reference_levels", "object", False,
              "{covariate: baseline category} for categorical covariates, e.g. {\"Race recode\": "
              "\"Black\"}. Every hazard ratio is measured against this level, so whenever the "
              "request names a reference/baseline category you MUST set it here — otherwise the "
              "baseline is whichever level sorts first and the HRs answer a different question. "
              "Copy the level verbatim from the column's values; a level that does not occur is an "
              "error."),
           _p("penalizer", "number", False,
              "Ridge penalty (e.g. 0.1) that stabilizes a collinear/wide one-hot design which "
              "otherwise fails to converge. Default 0."),
           _p("imputation_column", "column", False, _MI_PARAM),
       ]),
    _t("cox_ph_univariate", "survival", "table",
       '{"duration_column","event_column","event_values":[...],"covariates":[...],"strata"?:[...],'
       '"where"?,"weights_column"?,"robust"?,"cluster_column"?,'
       '"reference_levels"?:{"column":"baseline level"},"penalizer"?}',
       "UNIVARIATE Cox regression (lifelines): fits ONE SEPARATE single-covariate model per entry "
       "in `covariates` and stacks them into one table — the \"univariate / one characteristic at "
       "a time\" column survival papers print next to the multivariable one. Use THIS (not cox_ph) "
       "whenever the request asks for unadjusted or one-variable-at-a-time hazard ratios; cox_ph "
       "fits a single mutually-adjusted model and cannot produce them. Returns "
       "covariate/term_type/term/coef/se/hazard_ratio/hr_lower95/hr_upper95/statistic/df/p/n/events, "
       "where `covariate` names the model a row came from and term_type is 'coefficient' (one per "
       "non-baseline level), 'reference' (that covariate's baseline, hazard_ratio=1.0) or "
       "'global_wald' (the single p-value for the whole characteristic — the only valid one when a "
       "categorical spans several levels). All of these are ALREADY computed; a downstream node "
       "only filters/renames rows.",
       [
           _p("duration_column", "column", True, "Follow-up time (numeric)."),
           _p("event_column", "column", True, "Column recording the outcome status."),
           _p("event_values", "list[value]", True,
              "Value(s) of event_column that count as an EVENT (=1), verbatim; the rest are censored."),
           _p("covariates", "list[column]", True,
              "The characteristics to model ONE AT A TIME — each gets its own model, so list every "
              "characteristic the univariate column reports. EXCLUDE duration/event columns and "
              "identifiers. Never empty."),
           _p("strata", "list[column]", False,
              "Columns to stratify every model's baseline hazard by. A column that is also the "
              "model's own covariate is skipped for that model (it cannot be both). Optional."),
           _p("where", "string", False,
              "SQL boolean cohort filter. Do NOT add 'IS NOT NULL' guards for the covariates: "
              + _COMPLETE_CASE + " Each univariate model gets its OWN complete-case population, "
              "which is why the table reports n per row."),
           _p("weights_column", "column", False,
              "Per-patient weight column for IPTW-weighted models (the 'iptw' column from "
              "iptw_weight). Robust variance is enabled automatically."),
           _p("robust", "bool", False,
              "Robust (sandwich) standard errors. Defaults to true when weights_column is set."),
           _p("cluster_column", "column", False,
              "Column identifying correlated clusters (registry, hospital…) for clustered robust SEs."),
           _p("reference_levels", "object", False,
              "{covariate: baseline category} for categorical covariates, e.g. {\"Race recode\": "
              "\"Black\"}. Every hazard ratio is measured against this level, so whenever the "
              "request names a reference/baseline category you MUST set it here. Copy the level "
              "verbatim from the column's values; a level that does not occur is an error."),
           _p("penalizer", "number", False,
              "Ridge penalty (e.g. 0.1) for a covariate whose levels are collinear/sparse. Default 0."),
           _p("imputation_column", "column", False, _MI_PARAM),
       ]),
    _t("cox_ph_subgroup", "survival", "table",
       '{"duration_column","event_column","event_values":[...],"exposure_column","reference_level"?,'
       '"subgroup_columns":[...],"include_overall"?:true,"covariates"?:[...],"where"?,'
       '"weights_column"?,"robust"?,"cluster_column"?,"strata"?:[...],'
       '"reference_levels"?:{"column":"baseline level"},"penalizer"?}',
       "SUBGROUP Cox (lifelines): SEPARATE exposure models within each level of each "
       "`subgroup_columns` entry (plus an optional Overall row) — the \"HR for the exposure in "
       "every subgroup\" / Table-5 / forest-plot pattern. Wraps the same CoxPHFitter path as "
       "cox_ph. Use THIS whenever the request asks for subgroup-specific HRs from SEPARATE fits; "
       "do NOT use cox_ph with strata (only changes the baseline hazard) or interactions (one "
       "shared model), and do NOT emit one cox_ph node per subgroup level. ONE node covers ALL "
       "subgroup variables. Returns one stacked table with "
       "subgroup_variable/subgroup_category/n/n_ref/n_exposed/events plus the exposure HR "
       "(term/coef/se/hazard_ratio/hr_lower95/hr_upper95/p). All of these are ALREADY computed; "
       "a downstream node only filters/renames/joins rows. A multiply imputed input is fitted "
       "draw by draw and pooled, so the counts stay on the patient scale.",
       [
           _p("duration_column", "column", True, "Follow-up time (numeric)."),
           _p("event_column", "column", True, "Column recording the outcome status."),
           _p("event_values", "list[value]", True,
              "Value(s) of event_column that count as an EVENT (=1), verbatim; the rest are censored."),
           _p("exposure_column", "column", True,
              "The exposure / treatment column whose HR is reported inside every subgroup "
              "(e.g. surgery type). Categoricals are one-hot encoded against reference_level."),
           _p("reference_level", "value", False,
              "Baseline category of exposure_column (shorthand for "
              "reference_levels={exposure_column: level}). Whenever the request names the "
              "reference arm (e.g. mastectomy alone), set this — otherwise the baseline is "
              "whichever level sorts first."),
           _p("subgroup_columns", "list[column]", True,
              "Columns that DEFINE the subgroups — each distinct level of each column gets its "
              "own exposure-only Cox. List every characteristic the subgroup table/forest covers. "
              "Never empty. Must not include duration/event/exposure."),
           _p("include_overall", "bool", False,
              "If true (default), also fit one Overall model on the full filtered cohort and "
              "emit subgroup_variable='Overall', subgroup_category='All'."),
           _p("covariates", "list[column]", False,
              "Optional ADDITIONAL adjustment columns included in EVERY subgroup fit alongside "
              "exposure_column. Leave empty for the usual unadjusted-within-subgroup analysis."),
           _p("strata", "list[column]", False,
              "Columns to stratify every model's baseline hazard by. Optional; this is NOT a "
              "substitute for subgroup_columns."),
           _p("where", "string", False,
              "SQL boolean cohort filter. Do NOT add 'IS NOT NULL' guards for the covariates: "
              + _COMPLETE_CASE + " Inside one subgroup a covariate often collapses to a single "
              "level; that slot's column is dropped and named in the summary rather than "
              "sinking the fit."),
           _p("weights_column", "column", False,
              "Per-patient weight column for IPTW-weighted models (the 'iptw' column from "
              "iptw_weight). Robust variance is enabled automatically."),
           _p("robust", "bool", False,
              "Robust (sandwich) standard errors. Defaults to true when weights_column is set."),
           _p("cluster_column", "column", False,
              "Column identifying correlated clusters (registry, hospital…) for clustered robust SEs."),
           _p("reference_levels", "object", False,
              "{covariate: baseline category} for exposure and any extra covariates. "
              "reference_level (if set) fills in exposure_column when absent here."),
           _p("penalizer", "number", False,
              "Ridge penalty (e.g. 0.1) when a slot's design is collinear/sparse. Default 0."),
           _p("imputation_column", "column", False, _MI_PARAM),
       ]),
    _t("cox_ph_assumptions", "survival", "table",
       '{"duration_column","event_column","event_values":[...],"covariates":[...],"where"?,'
       '"reference_levels"?:{"column":"baseline level"},"penalizer"?}',
       "Proportional-hazards assumption check (Schoenfeld residuals) for a Cox model. MIRROR the "
       "cox_ph node being checked: same covariates, same where, same reference_levels, same "
       "penalizer — the test describes a MODEL, so a different specification tests a model nobody "
       "reported. On a multiply imputed input the test runs inside each draw and is averaged, "
       "with violates_ph the majority verdict.",
       [
           _p("duration_column", "column", True, "Follow-up time (numeric); same as the cox_ph being checked."),
           _p("event_column", "column", True, "Column recording the outcome status."),
           _p("event_values", "list[value]", True, "Value(s) counted as an EVENT (=1), verbatim; rest censored."),
           _p("covariates", "list[column]", True, "The same covariates used in the cox_ph model. Never empty."),
           _p("where", "string", False,
              "SQL boolean cohort filter — copy the cox_ph node's verbatim. You do NOT need to add "
              "'IS NOT NULL' for the covariates: " + _COMPLETE_CASE),
           _p("reference_levels", "object", False,
              "{covariate: baseline category}, copied from the cox_ph node being checked. The "
              "baseline decides which dummy columns the design has, so a different one tests a "
              "different model."),
           _p("penalizer", "number", False,
              "Ridge penalty, copied from the cox_ph node being checked. Default 0."),
           _p("imputation_column", "column", False, _MI_PARAM),
       ]),
    _t("cox_time_varying", "survival", "table",
       '{"id_column","start_column","stop_column","event_column","covariates":[...],"event_values"?:[...],"where"?}',
       "Time-varying Cox (lifelines) over a long/counting-process table; use when a covariate changes over time.",
       [
           _p("id_column", "column", True, "Subject id (one subject spans multiple interval rows)."),
           _p("start_column", "column", True, "Interval start time."),
           _p("stop_column", "column", True, "Interval stop time."),
           _p("event_column", "column", True, "Event status at the interval's stop."),
           _p("covariates", "list[column]", True, "Adjustment columns (may vary across intervals). Never empty."),
           _p("event_values", "list[value]", False, "Value(s) counted as an EVENT (=1), verbatim. Optional."),
           _p("where", "string", False,
              "SQL boolean cohort filter. Do NOT add 'IS NOT NULL' guards for the covariates: "
              + _COMPLETE_CASE + " The unit dropped here is an INTERVAL, so a subject can lose "
              "part of their follow-up rather than all of it."),
           _p("imputation_column", "column", False, _MI_PARAM),
       ]),
    _t("iptw_kaplan_meier", "survival", "figure",
       '{"treatment_column","treatment_values":[...],"duration_column","event_column",'
       '"event_values":[...],"covariates":[...],"cont_var"?:[...],"where"?,"n_bootstrap"?:200}',
       "IPTW-ADJUSTED Kaplan-Meier (iptw-survival) with bootstrap 95% CIs; use instead of "
       "kaplan_meier when the two arms must be confounder-adjusted.",
       [
           _p("treatment_column", "column", True, "Column separating the treated and control arms."),
           _p("treatment_values", "list[value]", True,
              "ONLY the value(s) marking the TREATED arm, verbatim; control is everyone else."),
           _p("duration_column", "column", True, "Follow-up time (numeric, e.g. survival months)."),
           _p("event_column", "column", True, "Column recording the outcome status."),
           _p("event_values", "list[value]", True,
              "Value(s) of event_column that count as an EVENT (=1), verbatim; the rest are censored."),
           _p("covariates", "list[column]", True,
              "Confounders the weights adjust for (auto-typed: numeric → continuous, else "
              "categorical). EXCLUDE the treatment, duration and event columns. Never empty."),
           _p("cont_var", "list[column]", False, "Force these covariates to be CONTINUOUS."),
           _p("cat_var", "list[column]", False, "Force these covariates to be CATEGORICAL."),
           _p("binary_var", "list[column]", False, "Force these covariates to be BINARY."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("weight_type", "string", False, "\"iptw\" (default, ATE) or \"overlap\" (ATO)."),
           _p("stabilized", "bool", False, "Stabilized IPTW. Default true."),
           _p("clip_bounds", "list[number]", False, "Trim propensity scores to [lower, upper], e.g. [0.01, 0.99]."),
           _p("n_bootstrap", "integer", False,
              "Bootstrap resamples behind the CI (default 200). Every resample refits the "
              "propensity model, so raise it only on small cohorts."),
           _p("random_state", "integer", False, "Bootstrap/model seed. Default 42."),
           _p("title", "string", False, "Figure title. Optional."),
       ]),
    _t("iptw_survival_metrics", "survival", "table",
       '{"treatment_column","treatment_values":[...],"duration_column","event_column",'
       '"event_values":[...],"covariates":[...],"psurv_time_points"?:[60],'
       '"rmst_time_points"?:[60],"median_time"?:true,"where"?,"n_bootstrap"?:200}',
       "IPTW-adjusted survival probability at fixed timepoints + RMST + median with bootstrap CIs, "
       "AND the treated-minus-control ABSOLUTE difference a hazard ratio cannot express.",
       [
           _p("treatment_column", "column", True, "Column separating the treated and control arms."),
           _p("treatment_values", "list[value]", True,
              "ONLY the value(s) marking the TREATED arm, verbatim; control is everyone else."),
           _p("duration_column", "column", True, "Follow-up time (numeric)."),
           _p("event_column", "column", True, "Column recording the outcome status."),
           _p("event_values", "list[value]", True,
              "Value(s) counted as an EVENT (=1), verbatim; the rest are censored."),
           _p("covariates", "list[column]", True,
              "Confounders the weights adjust for (auto-typed). Never empty."),
           _p("psurv_time_points", "list[number]", False,
              "Timepoints for adjusted survival probability, in the duration column's OWN unit — "
              "e.g. [60, 120] for 5- and 10-year survival when duration is in months."),
           _p("rmst_time_points", "list[number]", False,
              "Horizons for restricted mean survival time, same unit as duration, e.g. [60]."),
           _p("median_time", "bool", False, "Also report median survival per arm. Default true."),
           _p("cont_var", "list[column]", False, "Force these covariates to be CONTINUOUS."),
           _p("cat_var", "list[column]", False, "Force these covariates to be CATEGORICAL."),
           _p("binary_var", "list[column]", False, "Force these covariates to be BINARY."),
           _p("where", "string", False, "SQL boolean cohort filter. Optional."),
           _p("weight_type", "string", False, "\"iptw\" (default, ATE) or \"overlap\" (ATO)."),
           _p("stabilized", "bool", False, "Stabilized IPTW. Default true."),
           _p("clip_bounds", "list[number]", False, "Trim propensity scores to [lower, upper]."),
           _p("n_bootstrap", "integer", False, "Bootstrap resamples behind the CIs (default 200)."),
           _p("random_state", "integer", False, "Bootstrap/model seed. Default 42."),
       ]),

]
_apply_output_schemas(description)

# ---------------------------------------------------------------------------
# Lookup + rendering helpers
# ---------------------------------------------------------------------------

# name → spec
TOOLS_BY_NAME: Dict[str, Dict[str, Any]] = {t["name"]: t for t in description}

# category → [name, ...]
TOOL_CATEGORIES: Dict[str, List[str]] = {}
for _t_spec in description:
    TOOL_CATEGORIES.setdefault(_t_spec["category"], []).append(_t_spec["name"])


def list_tool_names(categories: Optional[Iterable[str]] = None) -> List[str]:
    """All tool names, optionally restricted to the given categories."""
    if not categories:
        return [t["name"] for t in description]
    wanted = set(categories)
    return [t["name"] for t in description if t["category"] in wanted]


def get_tool(name: str) -> Optional[Dict[str, Any]]:
    """Return one tool spec by name (or None)."""
    return TOOLS_BY_NAME.get(str(name or "").strip())


def param_names(name: str) -> List[str]:
    """Legal parameter keys this tool accepts, in catalog order.

    This is the allow-list a parameter delta must consult: a knob that was never
    authored in the last run (``table1.rename``) is still legal if it is here.
    Empty when the name is not a hub tool or has no curated ``param_specs``.
    """
    spec = get_tool(name)
    if not spec:
        return []
    out: List[str] = []
    for p in spec.get("param_specs") or []:
        key = str((p or {}).get("name") or "").strip()
        if key and key not in out:
            out.append(key)
    return out


def get_param(name: str, key: str) -> Optional[Dict[str, Any]]:
    """One parameter spec ``{name, type, required, description}``, or None."""
    spec = get_tool(name)
    want = str(key or "").strip()
    if not spec or not want:
        return None
    for p in spec.get("param_specs") or []:
        if isinstance(p, dict) and str(p.get("name") or "").strip() == want:
            return p
    lowered = want.casefold()
    for p in spec.get("param_specs") or []:
        if isinstance(p, dict) and str(p.get("name") or "").strip().casefold() == lowered:
            return p
    return None


def get_output_schema(name: str) -> Optional[Dict[str, Any]]:
    """Return the ``output_schema`` contract for a catalog op, or None."""
    spec = TOOLS_BY_NAME.get(str(name or "").strip())
    if not spec:
        return None
    schema = spec.get("output_schema")
    return schema if isinstance(schema, dict) else None


def render_output_schema(name: Any, *, indent: str = "      ") -> str:
    """Compact output-column block for a catalog / spec line.

    Returns ``""`` when the tool has no contract so callers can append it
    unconditionally.
    """
    out = get_output_schema(str(name or ""))
    if not out:
        return ""
    lines: List[str] = []
    card = out.get("cardinality") or "rows"
    fmt = out.get("format") or "parquet"
    lines.append(f"{indent}output [{fmt}, {card}]")
    if out.get("inherits_input_columns"):
        extra = " + derived columns below" if out.get("derived_columns") else ""
        lines.append(f"{indent}  columns: all input columns (row subset){extra}")
    for col in out.get("columns") or []:
        if not isinstance(col, dict):
            continue
        when = f"  [when {col['when']}]" if col.get("when") else ""
        desc = " ".join(str(col.get("description") or "").split())
        tail = f": {desc}" if desc else ""
        lines.append(
            f"{indent}  - {col.get('name', '?')} ({col.get('type', '?')}){tail}{when}"
        )
    side = out.get("side_deliverable") or {}
    if isinstance(side, dict) and (side.get("columns") or side.get("note")):
        lines.append(
            f"{indent}  SIDE deliverable (NOT the node outputs edge — "
            f"downstream inputs cannot read it):"
        )
        for col in side.get("columns") or []:
            if not isinstance(col, dict):
                continue
            desc = " ".join(str(col.get("description") or "").split())
            tail = f": {desc}" if desc else ""
            lines.append(
                f"{indent}    - {col.get('name', '?')} ({col.get('type', '?')}){tail}"
            )
        if side.get("note"):
            lines.append(f"{indent}    note: {side['note']}")
    for cons in out.get("consumes") or []:
        if not isinstance(cons, dict):
            continue
        when = cons.get("when") or "plot"
        src = cons.get("from") or ""
        req = cons.get("requires_any") or cons.get("requires") or []
        lines.append(
            f"{indent}  consumes ({when}): {', '.join(str(x) for x in req)}"
            + (f"  ← {src}" if src else "")
        )
    if out.get("note"):
        lines.append(f"{indent}  note: {out['note']}")
    if out.get("wire"):
        lines.append(f"{indent}  wire: {out['wire']}")
    return "\n".join(lines)


# Tools whose params are COMPILED at execute time from the plan's per-column
# ``column_plan`` instead of being authored whole in the plan.
#
# Only the free-form cohort builder qualifies: it projects and recodes EVERY input
# column, so a per-column spec is the right artifact and writing the query twice
# would be absurd. Every other tool — including the small transform ops
# (filter / aggregate / value_counts / describe) — has a closed param object the
# plan can author completely on its own. Routing those through the compiler made
# the params be authored TWICE from different prompts, and the two authors
# disagreed (a clean `group_by: ["col13"]` was replaced by raw upstream column
# names that no longer existed in the input).
QUERY_COMPILED_TOOLS: frozenset = frozenset()

# Catalog tools with NO fixed implementation: the DAG selects them by name like any
# other tool, but their work is written by the codegen step. ``viz`` is the figure
# op — a figure's shape is exactly what a fixed signature cannot pin down, so it is
# generated per figure instead (see ``tool_hub.CODEGEN_OPS``).
#
# They are named tools rather than plain `tool=null` codegen so the architect can
# CHOOSE "a figure" explicitly, and so the catalog can state what a figure node may
# and may not do (plot upstream results; never compute a statistic).
CODEGEN_TOOLS: frozenset = frozenset()


def is_codegen_backed(name: Any) -> bool:
    """True for a catalog tool whose implementation is generated code (``viz``)."""
    return str(name or "").strip() in CODEGEN_TOOLS


def is_frozen(name: Any) -> bool:
    """True for a tool with a FIXED implementation + fixed output schema.

    The distinction every stage needs: a frozen tool is authored as params and
    dispatched to the hub, while a codegen-backed tool is planned as prose and run
    as generated code. ``bool(node["tool"])`` used to be the test for "frozen", so
    every site that asked it must ask this instead or a ``viz`` node would be
    dispatched to a hub function that does not exist.
    """
    return bool(str(name or "").strip()) and not is_codegen_backed(name)


def is_query_compiled(name: str) -> bool:
    """True when this tool's params are compiled from a ``column_plan`` at run time."""
    return str(name or "").strip() in QUERY_COMPILED_TOOLS


# Params that name a column without saying so through a ``*_column`` suffix. Used
# for the tools that carry no curated ``param_specs`` (the plotly_* / mpl_* charts).
_COLUMN_PARAMS_BY_CONVENTION: frozenset = frozenset(
    {"columns", "covariates", "strata", "group_by", "group", "by"}
)


def column_params(name: Any, keys: Iterable[str]) -> List[str]:
    """Which of ``keys`` must name a COLUMN of the input for tool ``name``.

    Taken from the catalog's declared param types where curated, and otherwise from
    the naming convention every hub tool follows (a ``*_column`` suffix, plus the
    handful of plural list params). Callers use this to check a param against the
    real input schema BEFORE dispatch, so a stale column name fails where it can be
    read rather than as a DuckDB bind error deep inside the tool.
    """
    declared: Dict[str, str] = {}
    spec = get_tool(str(name or "").strip())
    for p in (spec or {}).get("param_specs") or []:
        if isinstance(p, dict) and p.get("name"):
            declared[str(p["name"])] = str(p.get("type") or "")
    out: List[str] = []
    for key in keys or []:
        k = str(key)
        ptype = declared.get(k)
        if ptype is not None:
            if "column" in ptype:
                out.append(k)
            continue
        if k.endswith("_column") or k in _COLUMN_PARAMS_BY_CONVENTION:
            out.append(k)
    return out


def render_tool_param_details(name: str) -> str:
    """Render a tool's PER-PARAMETER specs (name · type · required · description).

    Sourced from this catalog's own ``param_specs`` (biomni-style, like
    ``tool_desc/sklearn.py``) so the plan / tool-params author sees each param's
    meaning — critically the value-list semantics (which value(s) mark the
    treated / positive / event arm). Returns ``""`` for tools without detailed
    specs so callers can append it unconditionally and fall back to another
    source (e.g. the live tool-hub JSON schema).
    """
    spec = TOOLS_BY_NAME.get(str(name or "").strip())
    if not spec:
        return ""
    param_specs = spec.get("param_specs") or []
    if not param_specs:
        return ""
    lines: List[str] = []
    for p in param_specs:
        if not isinstance(p, dict):
            continue
        req = "required" if p.get("required") else "optional"
        desc = " ".join(str(p.get("description") or "").split())
        lines.append(
            f"    - {p.get('name')} ({p.get('type', 'any')}, {req}): {desc}".rstrip()
        )
    if not lines:
        return ""
    return "  param details:\n" + "\n".join(lines)


def render_tool_spec(name: Any, *, missing: str = "") -> str:
    """Render ONE tool's full spec: signature, summary, output type, param details.

    The single renderer shared by plan / execute / verify. They must agree on what
    a tool can do — a plan authored against one description and judged against
    another is how a verifier ends up demanding a parameter that does not exist.
    Falls back to the live tool-hub JSON schema for tools with no curated
    ``param_specs``; ``missing`` is returned when the name is not a hub tool.
    """
    spec = get_tool(str(name or ""))
    if not spec:
        return missing or f"(tool '{name}' not found in catalog)"
    text = (
        f"{spec['name']} {spec['params']}\n"
        f"  → {spec['summary']} [output_type: {spec['output_type']}]"
    )
    schema = render_output_schema(spec["name"], indent="  ")
    if schema:
        text += "\n" + schema
    detail = render_tool_param_details(spec["name"])
    if not detail:
        try:
            from tool import tool_hub

            detail = tool_hub.render_tool_param_details(spec["name"])
        except Exception:
            detail = ""
    if detail:
        text += "\n" + detail
    return text


def render_tool_catalog(categories: Optional[Iterable[str]] = None) -> str:
    """Render the tool catalog for the pipeline decomposer prompt.

    One section per category (short description + its tools), each tool line
    showing ``name  params  → summary [output_type]``. Pass ``categories`` to
    focus the catalog on a Stage-1 shortlist.
    """
    picked = set(categories) if categories else None

    lines: List[str] = [
        "TOOL HUB CATALOG — bind each pipeline node's `tool` to one exact op name below.",
        "Each op reads its input dataset(s) and produces the stated output_type "
        "(dataset | table | figure). Use tool=null / codegen only when no op fits.",
        "",
        "OUTPUT SCHEMA CONTRACT — wire `inputs`/`outputs` by the PRODUCER table, "
        "not the raw cohort:",
        "  • A figure that plots a computed column (SMD, asd, effect, hazard_ratio, "
        "odds_ratio) MUST set viz.inputs to that producer node's outputs name.",
        "  • table1(smd=true) emits `SMD`; covariate_balance emits `asd`. Those "
        "are the SMD/love-plot sources.",
        "  • propensity_score_match / iptw_weight / att_weight output a COHORT "
        "(`_treat` / `propensity_score` / `iptw`). Their SMD table is a SIDE "
        "deliverable and is NOT on the dataset edge — do not point viz at them "
        "for an SMD plot.",
        "  • viz never computes a statistic; it only plots columns already on "
        "its inputs.",
        "",
    ]
    for cat in _CATEGORY_ORDER:
        names = TOOL_CATEGORIES.get(cat) or []
        if not names or (picked is not None and cat not in picked):
            continue
        lines.append(f"## {cat} — {TOOL_CATEGORY_DESC.get(cat, '')}")
        for name in names:
            spec = TOOLS_BY_NAME[name]
            lines.append(
                f"  • {name} {spec['params']}"
                f"\n      → {spec['summary']} [{spec['output_type']}]"
            )
            schema = render_output_schema(name)
            if schema:
                lines.append(schema)
        lines.append("")
    return "\n".join(lines).rstrip()