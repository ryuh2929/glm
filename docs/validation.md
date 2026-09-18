# 실행 검증 기록

- 검증일: 2026-09-18
- 환경: Windows / CPython 3.14.5. 의존성은 requirements-lock.txt 참조.
- `python -m pytest -q`: **27 passed**. 신규 GLM 23개(파라미터화 사례 포함), 기존 결함 근거 4개.
- `python -m examples.run_glm`: 세 분포 각각 n=300, 계수 항=3, converged=True.
- 직접 계산의 계수·SE·95% CI를 독립 구성한 statsmodels 모델과 비교했고, Gaussian 계수는 NumPy 최소제곱과도 일치했다.
- `SeerToolbox.run`, `run_analysis_step`, DuckDB 전체 결과 조회, output schema 일치를 검증했다.
- 결측 범주 사전 제거, 잘못된 종속변수, 빈 자료, 무한값, 공선성/상수열, 없는 기준범주, 잘못된 인수, 표본 부족, 완전분리, 미수렴, 100,000행 초과를 검증했다.
- 카탈로그: 원본 60개와 신규 1개 모두 검토 메모 및 실제 시그니처가 존재한다. 생성 스크립트가 누락을 assertion으로 검사한다.
- 샘플 JSON 6개를 다시 파싱했다. CSV 3개와 원본 합성 CSV/Parquet를 함께 제공한다.

전체 원본 도구의 실행 검증이나 통계적 타당성 인증이 아니다. 기존 결함 재현 테스트는 현재 동작의 증거이며 원하는 수정 후 동작을 정의한 테스트가 아니다. 실제 연구자료, S3, 누락된 PREDICT 모듈 및 전체 서버 환경은 검증하지 않았다.
