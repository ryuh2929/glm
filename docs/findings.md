# 발견한 오류 및 개선사항

검토일 2026-09-18. **확인된 동작**, **정적 코드 근거**, **통계적 주의/개선 제안**을 구분한다. 아래 기존 문제는 원본 분석 동작을 광범위하게 바꾸지 않기 위해 유지했으며, 신규 basic_glm에 관련 검증을 적용했다. 원본 결함 재현 테스트는 현재 잘못된 동작을 확인하는 증거이므로, 해당 결함을 수정할 때 기대값도 변경해야 한다.

P1은 잘못된 연구 해석 또는 실행 차단, P2는 재현성/계약/진단 개선 우선순위다.

|ID / 우선순위|근거와 확인 상태|영향|개선안 / 이번 처리|
|---|---|---|---|
|F01 / P1|`_design_matrix`(tool_sample.py:2927)의 dummy_na=False 및 결측 행 사전 제거 부재. **재현 테스트 확인**: A와 NULL의 더미 벡터 동일.|기존 GLM/logistic 등에서 미기록 범주가 기준 수준으로 흡수되어 complete-case라고 오해하거나 교란 조정이 잘못될 수 있음. 모든 호출부가 동일하게 영향받는 것은 아니며 Cox 일부는 사전 삭제함.|공통 결측 정책과 인코딩 전 처리. 신규 GLM은 기본 오류, 명시적 drop 및 제외수 보고.|
|F02 / P1|여러 모델 쿼리에 `LIMIT _MODEL_MAX_ROWS`(1,000,000), ORDER BY나 초과 여부 검사 없음. **정적 확인**.|앞부분의 비무작위 부분집단 분석이 전체 코호트 결과로 보고될 위험.|COUNT 또는 cap+1 검사 후 명시적 실패/동의된 표본추출. 신규 adapter는 100,001행 검사 후 실패.|
|F03 / P1|기존 `glm_regression`(8289)은 binomial의 두 고유값만 확인하고 0/1 범위를 확인하지 않음. count는 음수만 검사. **정적 확인**.|잘못된 Bernoulli 코드나 소수 count가 유효 입력처럼 들어갈 수 있음. 일부 라이브러리 경고/실패에 의존.|개별 Bernoulli와 집계 비율을 계약에서 분리, 유한값·정수 범위 검사. 신규는 Bernoulli 0/1 및 비음수 정수 count로 제한.|
|F04 / P1|기존 GLM은 예외·converged 검사만 있고 PerfectSeparationWarning을 실패로 승격하지 않음. **정적 확인**.|라이브러리 버전에 따라 분리된 이진자료가 큰 계수와 부적절 CI로 반환될 가능성. 경고는 수렴과 별개.|분리 경고·비유한 추론 검사. 신규에 적용 및 완전분리 테스트. 준완전분리까지 완전히 해결한 것은 아님.|
|F05 / P2|`_glm_effect_label`(3556)은 Poisson/log를 exposure 여부와 무관하게 rate_ratio로 표시. 절편도 동일 estimate_type. **정적 확인**.|노출시간 없는 count ratio를 incidence-rate ratio로, exp(intercept)를 비교 효과로 오해.|노출 정의에 따라 척도 명시. 신규는 count_ratio와 baseline_count/odds/mean을 구별.|
|F06 / P1|기존 GLM은 weights_column을 freq_weights로 전달하고 기본 nonrobust 허용. **정적 확인 및 통계적 검토**.|빈도 가중치와 추정 IPTW는 의미가 다르다. model-based SE 또는 단순 HC0만으로 성향점수 추정까지 포함한 분산을 보장할 수 없음.|weight 의미를 계약에 분리하고 목표 추정량에 맞는 sandwich/bootstrap 검증. 신규는 가중분석 미지원.|
|F07 / P2|`table1`(11134)의 pval/smd/overall=True와 param 설명의 Default false 불일치. **재현 테스트 확인**.|요청하지 않은 검정이 추가되거나 재현 실행의 기본값이 달라짐.|시그니처에서 기본값을 생성. 본 카탈로그는 실제 True를 명시, 원본 설명도 대조 가능하게 보존.|
|F08 / P2|`_df_to_deliverable`(2817)은 preview=head(200)이지만 truncated를 n>len(df)로 계산. **300행 재현 확인**.|300행 전체 df를 전달하면 preview는 200행인데 truncated=false여서 미리보기를 전체로 오인.|`total > len(preview)`로 판정하도록 수정 권장. 신규 GLM 결과는 테스트의 3행이므로 이 결함에 노출되지 않았지만 공통 helper는 그대로임.|
|F09 / P1|`_export_parquet`(14395)의 `utils.storage.bucket` import가 try 밖. predict_breast_os(13569)는 누락된 predict_breast 모듈에 의존. **파일·정적 확인**.|best-effort export 설명과 달리 원본 도구가 로컬에서 import 오류로 중단될 수 있음. PREDICT의 실제 수식은 검증 불가.|스토리지 의존성 분리 및 로컬 writer 제공. 신규는 S3 없이 실행. PREDICT 파일을 임의로 재구현하지 않음.|
|F10 / P1|`impute_missing`(13418)의 수치형 non-MICE 분기가 median; method=mode여도 결과 method는 mode. **재현 확인**: 1,1,2,3,100,NULL → 2로 채움.|요청/보고된 최빈값 대치와 실제 중앙값 대치가 다름.|mode 분기를 구현하거나 지원 이름 수정. 실패 fallback에서도 실제 사용 알고리즘을 기록. 이번에는 개선사항으로 제출.|
|F11 / P1|MICE 오류를 catch 후 median 대체하며 요약은 요청 method 유지. 범주형은 모든 draw에서 최빈값. **정적 확인**.|실제로 대치 불확실성이 반영되지 않은 결과를 다중대치라고 보고할 수 있음.|actual_method/fallback_reason/draw variability 기록, 범주형 대치 모형 검증. 다중대치 stacking 미지원 도구에 전달 금지.|
|F12 / P2|`cox_ph_assumptions`(10258): 변수별 rank Schoenfeld 검정만 있고 소개문의 global/그림 없음. weights/strata/cluster/interactions 인수 없음. **정적 확인**.|원 Cox와 다른 모형의 검정을 동일 모형 진단으로 오해. 대치 p 평균/다수결도 정식 pooled p가 아님.|모형 사양 공유, 잔차 그림/전역검정 별도 제공, 대치 진단은 탐색적 결과로 표시.|
|F13 / P2|`ml_calibration_curve`(9928): prob_pred/prob_true/bin_count만 계산. slope/intercept/Brier 소개문과 불일치. sklearn과 별도 digitize로 bin_count 계산. **정적 확인**.|없는 산출물을 기대하거나 동점 경계에서 count와 평균이 어긋날 수 있음(해당 수치 불일치는 아직 실행 재현 안 함).|하나의 bin assignment로 모든 통계 집계, bin CI 추가, 소개 수정.|
|F14 / P2|`ml_classifier_performance`는 평가 데이터로 Youden threshold를 선택 가능. `_ml_oof_metrics`(14102)도 OOF에서 임계값 선택. **정적 확인·방법론 검토**.|그 임계값의 민감도/특이도가 독립적으로 검증된 것처럼 보이는 낙관 편향. 학습하지 않는 bootstrap도 이를 교정하지 않음.|train/내부 CV에서 임계값 고정 후 test 평가. 불확실성 범위 및 평가 프로토콜 저장.|
|F15 / P2|`_ml_fit_frame`(8658)과 CV 경로에서 전체 자료로 설계행렬을 만든 뒤 분할/학습. **정적 확인**.|범주 수준·80% 수치 판정이 test의 분포를 미리 볼 수 있음. 결과값 누수와는 구별하되 완전한 전처리 분리가 아님.|train fit / test transform Pipeline, group/time split 및 nested CV 검토.|
|F16 / P2|KM은 `time_months`라는 이름으로 입력 시간을 그대로 저장. CIF(5639)는 관심 사건 0인 군 skip, grid ffill. **정적 확인**.|시간단위 오표시, 0사건 군 누락, 추적 이후 값이 근거 있는 추정처럼 보일 위험.|time+unit 메타데이터, 0사건 군 유지, at-risk/support 범위/외삽 경고.|
|F17 / P2|Figure 공통 schema가 columns=[]이고 '이미 있는 값만 그림' 설명을 계산형 KM/CIF/IPTW에도 사용. **정적 확인**.|후속 노드가 실제 생성 수치 열과 처리 의미를 알 수 없음.|도구별 스키마 정의. 본 카탈로그는 실제 plot 데이터 열을 보완.|
|F18 / P2|load_seer_tool_specs(1373)의 production 경로가 이 샘플에 없음. get_output_schema도 원래 tool.tool_desc를 먼저 참조. **정적 확인**.|샘플 패키지에서 output schema 조회가 비어 있을 수 있음.|이번에 get_output_schema의 로컬 패키지 fallback 추가. production loader 전체를 재설계하지 않음.|

## 권장 후속 검증

전체 분석 환경을 복원하면 도구별 합성 ground truth/독립 라이브러리 비교, 입력·출력 계약 테스트, 작은/희소/0사건 코호트, weights/MI/cluster의 불확실성, 실제 사용 데이터 단위·인코딩을 점검한다. 자동 검정이 가정의 충족을 보증하지 않으므로 잔차·overlap·가중치·추적 지지구간 등의 시각적 검토도 필요하다.

## 이번 검증 결과

- `python -m pytest -q`: 27개 통과(신규 GLM 23개, 기존 결함 근거 4개). 현재 환경: Python 3.14.5 / Windows.
- `python -m examples.run_glm`: Gaussian/Binomial/Poisson 모두 300행, 절편 포함 3항, 정상 수렴. 직접 함수와 기존 파이프라인 모두 실행.
- 신규 수치 검증: 3개 family의 계수·SE·95% CI를 별도 구성한 statsmodels 설계행렬 결과와 비교. Gaussian은 NumPy 최소제곱 계수와도 비교.
- 검증 한계: 원본 60개 도구 전체 실행, S3 내보내기, PREDICT 모듈, 실제 환자 데이터·외부 검증은 수행하지 않았다.
