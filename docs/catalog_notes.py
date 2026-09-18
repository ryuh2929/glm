"""Human-reviewed Korean annotations used by build_catalog.py.

Tuple: purpose, assumptions/input constraints, output review, processing.
This file complements extracted signatures; it is not an automated review.
"""
NOTES = {
"table1": ("코호트의 기저 특성을 전체/군별 기술통계와 SMD, p값으로 요약한다.", "관측 단위와 분모를 통일한다. categorical/nonnormal을 데이터 의미에 맞게 지정하고, 군간 검정은 독립 관측을 전제한다.", "문자열로 포맷된 평균(SD)/중앙값[IQR]/n(%)는 표시용으로 적절하나 후속 계산용 수치 테이블이 별도로 필요하다. 문서의 pval/smd/overall 기본 false와 함수의 True가 다르다. SMD 열 이름도 동적으로 변한다. 다중대치 데이터는 한 draw만 기술한다.", "적합 없음 / 한 번 호출, 변수·군별 집계 / 배치 필수 아님"),
"attrition_table": ("조건을 순서대로 누적 적용하여 포함·제외 흐름을 계산한다.", "steps 순서가 연구 프로토콜 순서여야 한다. 행 수와 distinct 환자 수를 구별한다. SQL NULL의 3값 논리에 유의한다.", "n_before/n_after/n_excluded가 있어 흐름 재현에 적합하다. pct_excluded는 해당 단계 직전 행 수 기준이다. n_subjects는 distinct_column이 있을 때만 의미가 있다. 중복 환자 기준 제외 수를 별도 제공하면 좋다.", "적합 없음 / 조건별 반복 집계 / 한 번 호출"),
"data_quality": ("열별 결측·고유값 수와 날짜/숫자 선후관계 위반을 확인한다.", "columns 또는 date_order 중 하나 이상 필요. 날짜 형식·단위를 통일한다. 비교 불가능 값은 시간 규칙 분모에서 제외된다.", "check별 분모 n의 의미가 다르다. 시간 검사는 비교 가능한 행 수이고 결측 검사는 전체 행 수이다. 소개문과 달리 일반 범위/이상치 검사는 없다. 비교 불가 수와 실패 status 추가가 필요하다.", "적합 없음 / 변수·규칙 반복 / 한 번 호출"),
"propensity_score_match": ("이진 처치 성향점수 logit의 최근접 탐욕 매칭으로 비교 코호트를 만든다.", "기저 공변량만 사용. 일관성·간섭 없음·조건부 교환가능성·양의 처치확률이 인과 해석에 필요하다. 처치값 이외는 대조군이므로 사전 코딩 확인.", "출력 edge는 환자 코호트이며 SMD는 side deliverable이다. 매칭 세트 ID, 미매칭 이유/탈락 수, PS 분포를 추가하면 추적성이 좋아진다. 소개문은 replacement 설정을 암시하지만 함수는 비복원 매칭이다. 매칭 후 독립표본 SE를 그대로 쓰지 않는다.", "성향점수 모델 적합 / 매칭 반복 / 한 번 호출"),
"propensity_score_match_multi": ("3개 이상 처치군의 다항 성향점수로 1:1:…:1 매칭 세트를 구성한다.", "서로 다른 arms 3개 이상, exact/tolerance 조건의 현실적 중첩, 모든 군 간 positivity 필요. 이진 도구와 구별한다.", "_arm은 arms 순서 인덱스이다. 군별 수가 같아도 균형 달성을 보장하지 않는다. 쌍별 SMD는 side output이며 세트 식별자와 매칭 탈락 상세가 필요하다.", "다항 성향점수 적합 / K-tuple 탐색 반복 / 한 번 호출"),
"iptw_weight": ("ATE용 IPTW 또는 ATO용 overlap 가중치를 생성한다.", "공변량과 처치의 정확한 코딩, 교환가능성·positivity·일관성. clip_bounds와 stabilized 설정이 추정 대상을 바꿀 수 있다.", "가중 코호트와 균형표를 분리해야 한다. iptw 이름만 보고 ATE라고 해석하지 말고 weight_type을 보존한다. 극단 가중치·ESS·제외수와 추정량 메타데이터를 함께 확인한다.", "성향점수 적합 / 전체 코호트 일괄 계산 / 한 번 호출"),
"mann_whitney_u": ("두 독립 군의 수치 결과 분포를 순위 기반 U 검정으로 비교한다.", "독립 표본, 순서화 가능 결과. 중앙값 차이 검정으로 해석하려면 분포 형태가 유사해야 한다. 동점·소표본에서 method 선택 확인.", "군별 n/중앙값/U/p/alternative가 있어 기본 검정에는 적합하다. 효과크기(rank-biserial 등)와 CI가 없다. p값만으로 임상적 차이를 판단하지 않는다.", "적합 없음 / 단일 검정 / 배치 불필요"),
"chi2_contingency": ("두 범주형 변수의 독립성을 카이제곱 검정하고 Cramér’s V를 계산한다.", "독립 관측, 상호 배타적 범주, 충분한 기대도수. 희소 2×2 표에서는 Fisher 검정을 고려한다.", "통계량/자유도/p/V는 유용하나 실제 교차표와 기대도수·희소 셀 경고가 빠져 있다. lambda_가 Pearson 이외이면 검정 통계량과 Cramér’s V 정의가 일치하는지 확인해야 한다.", "적합 없음 / 단일 검정 / 배치 불필요"),
"logistic_regression": ("이진 결과의 다변수 로지스틱 회귀와 조정 OR을 계산한다.", "두 결과군, 독립 관측, logit에서 연속변수 선형성, 충분한 사건 수, 완전분리·공선성 없음. outcome_values는 양성값만 지정한다.", "OR/CI/기준범주가 있어 해석 가능하다. OR은 RR이 아니다. _design_matrix의 범주형 결측 기준수준 오인, 행 LIMIT, 분리/수렴 경고 처리 확인이 필요하다. 표에 분석 n·제외수·모델 진단을 추가해야 한다.", "통계모델 적합 / 한 번 호출 / 배치 불필요"),
"glm_regression": ("기존 확장 GLM: Gaussian/Binomial/Poisson/음이항/Gamma/역가우시안과 링크·노출·가중치 설정으로 평균을 모델링한다.", "분포의 지지집합, 링크의 유효 범위, 독립성 및 설계행렬 full rank. 음이항 alpha는 추정하지 않고 고정한다. exposure는 양수이며 log 링크에서만 사용한다.", "계수와 효과 척도를 함께 주는 구조는 좋다. 범주형 결측 처리·Binomial 범위·정수 count·완전분리 검증이 불충분하다. Poisson에서 exposure 없이도 rate_ratio 표기가 가능하고 절편을 같은 효과 라벨로 표시한다. IPTW를 freq_weights로 전달하는 것만으로 올바른 인과분산이 보장되지 않는다. 상세 개선표 참조.", "통계모델 적합 / 한 번 호출 / 배치 불필요"),
"covariate_balance": ("처치/대조군의 변수별·범주수준별 절대 표준화 차이(ASD)를 계산한다.", "같은 모집단·같은 변수코딩으로 비교하며 weight_column은 적절한 비음수 가중치여야 한다. 수치형/범주형 강제 지정 검토.", "treated/control/ASD/균형 여부는 균형 점검에 적절하다. 0.1은 관례적 기준이고 인과 식별의 증거가 아니다. 분산 0일 때 ASD, 가중 ESS, 결측 처리의 영향도 확인한다.", "모델 적합 없음 / 변수·수준 반복 / 한 번 호출"),
"covariate_balance_multi": ("원 코호트·매칭·가중 코호트 등 시나리오별 균형을 비교한다.", "시나리오 간 동일한 변수·분모·코딩 및 적절한 가중치. 각 source가 실제 존재해야 한다.", "scenario와 asd_reference가 있어 비교에 적합하다. 서로 다른 환자집단의 균형 개선을 같은 모집단 효과로 해석하면 안 된다. n/ESS를 시나리오별 추가 권장.", "모델 적합 없음 / 시나리오·변수 반복 / 한 번 호출"),
"evalue": ("보고된 효과를 설명해 없애기 위한 미측정 교란의 최소 연관 강도를 E-value로 계산한다.", "행 데이터가 아닌 양의 효과 추정치와 CI 입력. scale·희귀결과 여부 등 RR 척도 변환 가정을 확인한다.", "점 추정치와 귀무값에 가까운 CI의 E-value를 분리해 주는 것은 적절하다. OR/HR의 RR 근사는 상황에 의존한다. 큰 값이 교란 부재나 인과성을 증명하지 않는다.", "적합 없음 / 수치 1세트 계산 / 배치 불필요"),
"bias_sensitivity": ("가정한 미측정 교란 강도별 bounding factor와 편향 조정 효과를 계산한다.", "RR 척도와 교란-노출/결과 연관의 방향·크기 가정. 입력값 자체는 데이터에서 식별한 교란 효과가 아니다.", "시나리오별 조정 CI는 민감도 분석용이며 새로 관측한 효과가 아니다. still_significant는 가정한 범위 안의 결과이고 grid 밖에서 강건함을 보장하지 않는다.", "적합 없음 / grid·시나리오 반복 / 한 번 호출"),
"impute_missing": ("수치형 MICE/중앙값, 범주형 최빈값으로 결측을 채우고 다중대치 draw를 쌓는다.", "MICE는 관측 변수 조건부 MAR 및 적절한 대치모형 가정. MNAR이면 별도 민감도 분석. 예측 연구에서 대치는 train 안에서 학습해야 한다.", "_imputation은 환자 ID가 아니다. draw를 독립 환자로 취급하면 n/SE가 왜곡된다. method=mode도 수치형은 median으로 처리되고 MICE 실패 시 median 대체를 로그에만 남길 수 있다. 범주형은 확률적 다중대치가 아니다. 구현과 method 표기를 일치시켜야 한다.", "MICE는 대치모형 적합 / 변수·draw 반복 / 한 번 호출, m배 메모리"),
"predict_breast_os": ("고정 계수 PREDICT Breast v2.1로 수술 단독 생존확률과 순차 치료 추가 이득을 산출한다.", "모델 개발 대상과 입력 코딩/단위에 부합하는 환자. year 범위와 임상변수 코딩은 제공 param 표 및 원 모델 구현 확인. 신규 코호트 보정·검증은 별도.", "원본 환자+생존/치료 이득/부적격 사유 구조는 좋다. 이득은 정해진 순서의 증분이며 각각 독립 치료 효과가 아니다. v3와 혼동 금지. 참조하는 predict_breast 모듈이 이 저장소에 없어 실제 수식과 동작은 검증 불가.", "학습 없음(기학습 고정계수) / 환자별 일괄 추론 / 한 번 호출"),
"ml_train_test_split": ("코호트에 train/test 표식을 추가하여 학습과 평가를 분리한다.", "독립 환자 행 전제. 반복측정·다기관·시간 예측에서는 환자/기관/시간 기준 분할 필요. 층화 클래스 최소 표본 수 확인.", "split 표식 보존은 적절하다. 모델에 split_column을 전달하지 않으면 전체 자료를 학습할 수 있다. 분할만으로 전처리 누수가 해결되지 않는다.", "학습 없음 / 1회 분할 / 배치 불필요"),
"ml_classifier_performance": ("이미 저장한 예측확률 또는 점수로 분류 성능 및 bootstrap CI를 계산한다.", "독립 검증 데이터와 두 결과군. 확률은 0~1이며 점수는 확률과 구별. train/test 지정과 양성 라벨 일치 필요.", "metric/value/CI long table은 재사용에 적합하다. 평가셋에서 Youden 임계값을 선택하면 임계값 성능은 낙관적이다. bootstrap은 기존 예측쌍 재표집으로 학습 불확실성/낙관편향을 교정하지 않는다.", "재학습 없음 / bootstrap 반복 / 한 번 호출"),
"ml_roc_curve": ("기존 예측 점수의 임계값별 TPR/FPR과 ROC를 생성한다.", "독립 평가자료의 두 결과군. 확률뿐 아니라 연속 결정점수도 가능. 양성 방향을 확인한다.", "FPR/TPR/threshold 표와 그림이 적절하다. AUC는 calibration이나 임상 효용이 아니다. 무한 초기 임계값은 null 처리되며 Youden 선택은 탐색적이다. 카탈로그 공통 Figure schema에 실제 열이 누락되어 있다.", "재학습 없음 / 임계값 순회 / 한 번 호출"),
"ml_calibration_curve": ("예측확률 분위수 구간별 평균 예측확률과 실제 발생률을 비교한다.", "0~1 확률, 독립 평가자료, 각 bin 충분한 표본. 결정점수를 확률처럼 넣지 않는다.", "prob_pred/prob_true/bin_count와 그림을 출력한다. 소개문의 slope/intercept/Brier는 이 함수가 계산하지 않는다. sklearn bin 할당과 별도 np.digitize의 경계처리가 달라 동점 확률에서 bin_count가 일치하지 않을 수 있다. bin별 CI도 없다.", "재학습 없음 / bin 집계 / 한 번 호출"),
"ml_decision_curve": ("임계확률별 모델·전원처치·무처치의 순편익을 비교한다.", "0<임계확률<1, 적절히 보정된 확률, 목표 모집단 유병률, 처치 손익을 임계값으로 표현할 수 있다는 전제.", "세 순편익을 함께 보여 비교 가능하다. 순편익은 정확도가 아니며 희귀사건·작은 평가집단에서 불안정하다. CI와 임상적으로 타당한 임계 범위를 추가 권장.", "재학습 없음 / 임계값 grid 반복 / 한 번 호출"),
"ml_reclassification": ("동일 환자 두 모델의 예측확률로 IDI 및 연속/임계값 NRI를 비교한다.", "같은 환자·결과·예측 시점. 별도 source를 결합할 때 id_column의 유일성 및 1:1 조인 확인.", "metric/value는 간단하나 CI가 없어 불확실성을 판단하기 어렵다. NRI는 calibration이나 임상효용을 대체하지 않는다. 여러 임계값은 각 cut의 결과이며 자동 다범주 NRI로 읽으면 안 된다.", "재학습 없음 / 모델 예측쌍 비교 / 한 번 호출"),
"ml_cv_performance": ("한 알고리즘을 층화 교차검증에서 재학습하고 OOF 성능을 산출한다.", "각 fold 두 결과군과 충분한 표본, 환자 단위 독립성. 전처리·튜닝은 각 training fold 안에서 해야 한다.", "OOF AUC/Brier/calibration을 제공한다. 최종 배포 모델 파일은 아니다. 전체 데이터의 설계행렬을 미리 만들고, OOF에서 임계값을 선택하는 부분을 점검해야 한다. CI·fold별 분산과 외부 검증이 필요하다.", "fold별 모델 학습 / CV 반복 필수 / 한 번 호출"),
"ml_compare": ("동일 fold로 여러 알고리즘을 교차검증하고 OOF AUC 순위를 비교한다.", "같은 표본·fold·평가 정의. 모델 선택에 사용한 CV 점수를 최종 일반화 성능으로 보지 않는다.", "rank는 해당 표본의 추정 순위로 유의한 성능 차이를 뜻하지 않는다. 차이의 CI와 nested CV/독립 test가 필요하다. 모델별 적합 실패도 명시적으로 보고해야 한다.", "모델×fold별 학습 / 중첩 반복 / 한 번 호출"),
"kaplan_meier": ("우측 검열 생존자료의 군별 Kaplan–Meier 생존곡선과 life table을 계산한다.", "독립 관측·비정보적 검열·일관된 time origin과 단위, 음수 시간 없음. 사건 코드 이외의 값이 검열로 처리되므로 누락/미상 코드 사전 정리.", "생존확률/CI/위험집단/사건수는 적절하다. time_months라는 이름을 쓰지만 단위 변환은 하지 않는다. censor 수·median 및 추적기간 요약 추가 권장. 경쟁사건의 누적발생률을 1-KM으로 구하면 과대평가 가능.", "생존분포 추정(예측모델 학습 없음) / 군별 적합 / 한 번 호출"),
"competing_risk_cif": ("Aalen–Johansen으로 관심 사건 및 경쟁사건의 누적발생률을 추정한다.", "상호 배타적인 사건/경쟁사건 코드, 독립 검열, 정확한 시간과 원인 분류. 사건 집합이 겹치면 안 된다.", "group/cause/time/CIF/CI 구조는 적절하다. 관심 사건이 0인 군을 skip하여 실제 0위험 곡선이 표에서 사라질 수 있다. 관찰 최대시간 밖의 ffill은 근거 없는 외삽처럼 보일 수 있다. 추적 지지구간을 표시해야 한다.", "생존분포 추정 / 군×원인 반복 / 한 번 호출"),
"logrank_test": ("두 군의 생존함수 차이를 log-rank 통계량으로 검정한다.", "독립 표본·비정보적 검열·동일 시간원점. PH일 때 검정력이 좋으며 곡선 교차 시 검정력이 떨어질 수 있다.", "군별 n/사건수/통계량/p가 있어 검정에는 적절하다. 효과크기나 생존율 차이 CI가 없으므로 KM/RMST와 함께 보고한다. 비유의는 동등성을 증명하지 않는다.", "예측모델 학습 없음 / 단일 검정 / 배치 불필요"),
"cox_ph": ("전체 공변량을 동시에 포함한 Cox 비례위험 모형의 HR 및 상호작용을 추정한다.", "비례위험·조건부 비정보적 검열·연속변수의 log-hazard 선형성·충분한 사건·독립성(또는 적절한 cluster/robust 분산).",
"HR은 위험비/확률비가 아니다. coefficient/reference/contrast/interaction_wald 행을 구별한다. 계약의 interaction_contrast/global_wald 표기와 실제 행 문자열이 다를 수 있다. 상수·종속 열 제거 및 완전사례 탈락을 확인한다. PH 진단 도구는 weights/strata/cluster/interactions를 모두 재현하지 못한다.", "Cox 적합 / 대치 draw별 반복 가능 / 한 번 호출"),
"cox_ph_univariate": ("공변량별 별도 Cox 모형을 적합하여 비조정 HR을 나열한다.", "각 모형에서 PH·검열·선형성 전제. 변수별 결측 때문에 분석 표본이 달라질 수 있다.", "covariate/n/events로 모형을 구별하는 구조가 적절하다. 여러 수준의 전역 검정과 수준별 검정을 구분한다. 단변수 p값에 따른 자동 변수선택과 다중검정에 주의한다.", "변수별 Cox 적합 / 변수×대치 반복 / 한 번 호출"),
"cox_ph_subgroup": ("각 하위집단 안에서 노출 효과의 Cox 모형을 별도로 적합한다.", "하위집단별 충분한 사건·노출 두 수준, PH 및 검열 전제. subgroup_columns와 adjustment/strata는 역할이 다르다.", "하위집단·노출·n/사건수·HR로 구분 가능하다. 한 군 유의/다른 군 비유의가 상호작용의 증거는 아니다. 정식 interaction 검정 및 실패한 하위집단 표시가 필요하다.", "하위집단별 Cox 적합 / 집단×대치 반복 / 한 번 호출"),
"cox_ph_assumptions": ("Cox를 재적합하고 rank 시간 변환의 Schoenfeld 잔차 기반 PH 검정을 수행한다.", "검정 대상과 같은 표본·공변량·기준범주·penalizer여야 한다. p>0.05는 PH 충족의 증명이 아니다.", "변수별 test_statistic/p/violates_ph만 생성한다. 소개문의 global 검정·잔차 그림은 없다. 대치별 p 평균·다수결은 정식 결합검정이 아니다. 가중/층화/상호작용 Cox와 동일한 모형으로 재현할 인수가 없다.", "Cox 재적합 / 변수 검정·대치 반복 / 한 번 호출"),
"cox_time_varying": ("환자별 start–stop 긴 형태 자료로 시간변화 공변량 Cox를 적합한다.", "id별 start<stop, 구간 중복 없음, 사건은 해당 구간 끝, 미래 정보 누수 없음. 적절한 검열 및 PH 구조.", "시간변화 계수 모형과 시간변화 공변량 모형은 다르다. 결측 삭제는 환자가 아니라 일부 추적 구간을 제거한다. n_intervals/n_subjects 및 구간 유효성 진단이 필요하다. source 대신 input 인수를 쓰는 예외가 있다.", "Cox 적합 / 대치별 반복 가능 / 한 번 호출"),
"iptw_kaplan_meier": ("성향점수 가중 생존곡선과 재적합 bootstrap CI를 계산한다.", "인과 가중치 전제+비정보적 검열. 치료 IPTW는 정보적 검열을 자동 교정하지 않는다. 두 군 overlap과 ESS 확인.", "time 및 군별 추정치/CI가 있어 좋다. 일반 Figure 스키마에 열이 누락되어 있다. bootstrap 성공 횟수, 가중 ESS, follow-up 지지구간과 weight_type을 결과에 남겨야 한다.", "성향점수 적합+생존 추정 / bootstrap 재적합 / 한 번 호출"),
"iptw_survival_metrics": ("가중 고정시점 생존확률·RMST·중앙생존 및 처치-대조 절대차를 계산한다.", "가중 생존분석 전제. 시간점/적분 상한은 데이터의 시간 단위이며 충분한 추적 지지구간 안이어야 한다.", "group/metric/timepoint/estimate/CI의 long table은 유용하다. median 미도달은 0이 아닌 결측/미도달로 표시해야 한다. RMST와 생존확률은 단위가 달라 metric별 표시 단위가 필요하다.", "성향점수 적합+생존 추정 / 시간점·bootstrap 반복 / 한 번 호출"),
"basic_glm": ("제출용 기본 GLM: Gaussian 평균 차이, Bernoulli OR, Poisson count ratio를 추정한다.", "독립 행, 올바른 분포/고정 링크, full-rank 설계, 충분한 표본. Gaussian 조건부 등분산·정규성(모형 기반 추론), Bernoulli logit 선형성/분리 없음, Poisson 조건부 평균=분산. 숫자 범주는 categorical로 명시한다.", "명시적 결측 정책, 분석 n/제외수, 수렴/분산/AIC/deviance, 기준범주와 절편 척도를 보존한다. 모델 기반 Wald CI이며 소표본·준완전분리·군집 상관·과산포에서는 신뢰하기 어렵다. offset/exposure/가중치/대치 pooling/새자료 예측은 범위 밖이다. 기존 GLM과 별도 이름으로 추가했다.", "IRLS 통계모델 적합 / 반복 최적화, 외부 batch 불필요 / 단일 실행"),
}

for estimand in ("att", "ate"):
    population = "실제 처치군(ATT)" if estimand == "att" else "전체 모집단(ATE), 선택 시 중첩 모집단(ATO)"
    assumptions = "일관성·간섭 없음·조건부 교환가능성·positivity. 처치 이전 교란변수만 조정한다. trimming/overlap 제한은 대상 집단을 바꾼다."
    NOTES[estimand+"_weight"] = (
        f"{population}을 목표로 성향점수 가중 코호트를 생성한다.", assumptions,
        "성향점수·가중치·overlap_flag와 원 환자 정보를 보존한다. estimand 및 사용자 weight_column 설정에 따라 열 이름이 달라진다. 효과나 CI를 계산한 결과는 아니다. 가중 분포·ESS·ASD를 함께 보고해야 한다.",
        "성향점수 모델 적합 / 대치 draw 반복 가능 / 한 번 호출")
    for suffix, purpose, loop in [
        ("estimate", "한 추정법으로 잠재결과 평균과 절대 효과차 및 bootstrap CI를 추정한다.", "bootstrap"),
        ("estimate_multi", "여러 추정법의 효과를 같은 코호트에서 비교한다.", "추정법×bootstrap"),
        ("sensitivity", "코호트·공변량·절단 등 분석 설정을 바꾸어 효과 민감도를 비교한다.", "설정×bootstrap"),
    ]:
        NOTES[estimand+"_"+suffix] = (
            f"{population}: {purpose}", assumptions+" 결과모형/성향모형의 필요한 명세 가정은 선택한 estimator에 따라 다르다. doubly robust도 두 모형 모두 틀리면 보호되지 않는다.",
            "mu_treated/mu_control/effect/CI와 코호트 흐름·feasible은 유용하다. effect는 처치-대조 평균차(이진 결과는 위험차)이고 ratio와 구별한다. feasible=false의 결측 효과를 0으로 읽지 않는다. 범주형 미기록의 기준범주 흡수는 미조정 교란을 남긴다. 성공 bootstrap 수·ESS·사전 지정 primary를 보존해야 한다.",
            f"성향/결과모형 적합(방법별 상이) / {loop}·대치 반복 / 한 번 호출")

MODELS = {
    "LogisticRegression": "벌점 로지스틱 회귀의 예측확률",
    "LogisticRegressionCV": "내부 CV로 벌점 강도를 고르는 로지스틱 예측확률",
    "PassiveAggressiveClassifier": "수동-공격적 갱신 선형 분류의 결정점수",
    "Perceptron": "퍼셉트론 선형 분류의 결정점수",
    "RidgeClassifier": "L2 최소제곱 분류의 결정점수",
    "RidgeClassifierCV": "내부 CV로 L2 강도를 고르는 분류 결정점수",
    "SGDClassifier": "확률적 경사하강 선형 분류의 점수(loss에 따라 확률)",
    "SGDOneClassSVM": "정상 영역을 학습하는 비지도 이상탐지 점수",
    "SVC": "커널 최대마진 분류 및 확률 추정",
    "LinearSVC": "선형 최대마진 분류 결정점수",
    "NuSVC": "nu 제약 커널 분류 및 확률 추정",
    "DecisionTreeClassifier": "단일 결정트리의 분류 확률",
    "ExtraTreeClassifier": "무작위 분할 단일 트리의 분류 확률",
    "RandomForestClassifier": "bootstrap 랜덤 포레스트 분류 확률",
    "ExtraTreesClassifier": "다수의 무작위 분할 트리 분류 확률",
    "AdaBoostClassifier": "오분류 관측을 강조하는 부스팅 분류 확률",
    "GradientBoostingClassifier": "순차 손실 개선 트리 부스팅 분류 확률",
    "HistGradientBoostingClassifier": "히스토그램 기반 트리 부스팅 분류 확률",
}
for name, purpose in MODELS.items():
    extra = ""
    if "Tree" in name or "Forest" in name:
        extra = " 트리는 비선형·상호작용을 허용하지만 과적합과 변수 중요도의 고유값 수 편향을 점검한다."
    elif "Boost" in name:
        extra = " 깊이·학습률·반복 수에 따른 과적합과 이상치 민감도를 점검한다."
    else:
        extra = " 수치 척도와 선형/커널 구조를 점검한다. 결정점수는 확률이 아니며 보정 없이 calibration/DCA에 넣지 않는다."
    NOTES[name] = (
        purpose+"를 산출하여 입력 환자 코호트에 붙인다.",
        ("정상 학습 표본의 대표성과 독립성. 종속변수는 불필요하다." if name == "SGDOneClassSVM" else "독립 환자, 두 결과군과 충분한 train 표본, 미래/결과 정보 누수 없음. test는 학습·튜닝에 사용하지 않는다.")+extra,
        "주 출력은 환자별 scored dataset이며 계수 추론표가 아니다. probability/score 열은 estimator 능력에 따라 조건부 생성된다. 원본 소개문의 모델 해석성/확률 보정을 실제 제공 산출물로 오인하지 않는다. 불완전 행의 null 예측률, 분할 여부, 학습 seed/버전, 모델 저장 여부를 보고해야 한다."
        + (" predicted_class의 +1/-1은 정상/이상이며 질병 양성/음성이 아니다." if name == "SGDOneClassSVM" else " split_column 미지정 시 학습 코호트 점수이므로 일반화 성능으로 해석하지 않는다."),
        "모델 학습 필요 / "+("내부 CV 후 최종 적합" if name.endswith("CV") else "단일 적합")+" / 한 번 호출, 스트리밍 partial_fit 인터페이스 없음")
