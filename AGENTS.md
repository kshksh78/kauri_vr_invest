# 프로젝트 작업 기준

- 한국어 UI와 문서를 유지한다.
- `python -m pytest -q`, `ruff check .`로 검증한다. 브라우저 테스트는 별도 격리 DB 서버에서 실행한다.
- 금융 계산은 `app/engine.py`의 공통 순수 함수를 사용한다. 실력 ROUND 순서·입금 전 Pool·고정 회차 한도를 바꾸기 전에 독립 기대값 테스트를 확인한다.
- 계좌 seed와 확정 회차 설정을 미래 기본 설정과 구분한다. 장부 변경은 revision 검사·시간순 재생·원자 저장을 유지한다.
- 기존 보유 시작은 시작 평가가격 × 실제 수량 + 현금이 기준자산이다. 취득원가는 참고값이고 새 매수 비용을 만들지 않는다. 저장된 이전 seed는 자동 재해석하지 않는다. 실제 입출금은 같은 회차에 합산하고 정기 예정액을 대체한다.
- 백테스트 입출금은 달력상 경계 대신 실제 회차 시작일에 적용한다. 휴장으로 미뤄진 시작일 당일의 입금도 포함하며, 실력 종가 미입력으로 대기 중인 운용 회차의 입금은 적용 대기 목록에 유지한다.
- 가격은 coherent snapshot 기준으로 읽는다. 합성 데이터나 다른 조정 시점의 가격을 실제 백테스트에 조용히 섞지 않는다.
- raw 파일·DB·백업·계좌 입력·인증정보는 Git에 넣지 않는다.
- GitHub workflow 파일의 푸시에는 OAuth workflow 권한이 필요하다. Windows gh 인증은 해당 권한이 없고 WSL gh 인증은 이미 보유한 환경일 수 있으므로, 실패 시 기존 인증 범위를 확인한다. CI 파일을 제거하거나 토큰을 출력해 우회하지 않는다.
- WSL 서비스는 `/home/kauri/hobby/kauri_vr_invest_service`, localhost39784이다. 배포는 `bash scripts/deploy_wsl.sh`로 수행하며 runtime과 venv를 보존한다.
- 비직관적 판단과 실제 검증 근거는 `docs/solutions/`에 남긴다. 문서 YAML의 module·tags·problem_type으로 관련 지식을 찾는다. 관련 지식은 `docs/solutions/vr-price-basis-and-ledger.md`를 먼저 참고한다.
