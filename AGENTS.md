# 프로젝트 작업 기준

- 한국어 UI와 문서를 유지한다.
- `python -m pytest -q`, `ruff check .`로 검증한다. 브라우저 테스트는 별도 격리 DB 서버에서 실행한다.
- 금융 계산은 `app/engine.py`의 공통 순수 함수를 사용한다. 실력 ROUND 순서·입금 전 Pool·고정 회차 한도를 바꾸기 전에 독립 기대값 테스트를 확인한다.
- 계좌 seed와 확정 회차 설정을 미래 기본 설정과 구분한다. 장부 변경은 revision 검사·시간순 재생·원자 저장을 유지한다.
- 가격은 coherent snapshot 기준으로 읽는다. 합성 데이터나 다른 조정 시점의 가격을 실제 백테스트에 조용히 섞지 않는다.
- raw 파일·DB·백업·계좌 입력·인증정보는 Git에 넣지 않는다.
- WSL 서비스는 `/home/kauri/hobby/kauri_vr_invest_service`, localhost8787이다. 배포는 `bash scripts/deploy_wsl.sh`로 수행하며 runtime과 venv를 보존한다.
- 비직관적 판단과 실제 검증 근거는 `docs/solutions/`에 남긴다. 문서 YAML의 module·tags·problem_type으로 관련 지식을 찾는다. 관련 지식은 `docs/solutions/vr-price-basis-and-ledger.md`를 먼저 참고한다.
