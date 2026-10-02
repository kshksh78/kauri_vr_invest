# VR 투자 로컬 서비스

김승혁의 기본 VR·실력 VR 운용과 가격 데이터·백테스트를 관리하는 로컬 웹 서비스입니다.

설계: [구현 계획](docs/plans/2026-10-02-local-vr-service.md).

FastAPI, SQLite, 별도 빌드가 없는 한국어 웹 UI를 사용합니다. 원본 가격과 개인 계좌 DB는 저장소에 올리지 않습니다.

## 실행과 배포

WSL Ubuntu에서 저장소를 받아 실행합니다. Python 3.14와 systemd 사용자 서비스 환경에서 검증했습니다.

```bash
git clone https://github.com/kshksh78/kauri_vr_invest.git
cd kauri_vr_invest
git switch feat/local-vr-service # PR 병합 전 구현 브랜치
bash scripts/deploy_wsl.sh
```

접속: **http://localhost:8787**. 배포 위치는 `/home/kauri/hobby/kauri_vr_invest_service`입니다.
SQLite는 그 폴더의 `runtime/vr.sqlite3`, 재배포 전 백업은 `backups/`에 저장합니다. 배포는 원본 저장소에서 실행하며 DB·백업·가상환경을 보존합니다.

```bash
systemctl --user status kauri-vr.service
systemctl --user restart kauri-vr.service
journalctl --user -u kauri-vr.service -n 50 --no-pager
```

사용자 서비스 자동 시작에는 linger가 필요합니다(`loginctl show-user kauri -p Linger`). 이번 환경은 이미 `Linger=yes`입니다. WSL을 종료하면 서비스도 종료되며, Windows 부팅 시 WSL 자동 시작은 별도 설정입니다.

개발 서버는 격리 DB를 지정합니다.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
VR_DB_PATH=/tmp/vr-dev.sqlite3 .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8790
```

## 가격 원본과 인터넷 조회

배포 폴더에서 아래 명령을 실행합니다. 파일은 읽기만 하며 개인 DB와 raw 자료는 Git에서 제외합니다.

```bash
cd /home/kauri/hobby/kauri_vr_invest_service
.venv/bin/python -m app.cli import --directory '/mnt/h/downloads/VR투자'
.venv/bin/python -m app.cli sync --symbol QLD --symbol TQQQ --symbol SOXL --symbol UPRO --years 10
.venv/bin/python -m app.cli prices
```

웹의 가격 화면에서는 추가 종목 코드와 1~10년 조회 범위를 입력할 수 있습니다. 화면 기본 범위는 5년입니다. 공급자 수정종가 기준을 통일하려고 온라인 갱신은 최대 지원 기간 10년을 한 snapshot으로 받습니다. 실패하면 이전 가격을 보존하고 오류를 표시합니다. 시장 시간대의 확정 종가만 사용합니다.

원본 XLSX는 파일명으로 식별한 ticker와 같은 실제 시트만 가져옵니다. `QLD_2×NDX`, `TQQQ_3×NDX`, 환율·KRW 시트는 제외합니다. CSV는 `date,close,adj_close`가 필요하며 OHLC·volume·source_url·retrieved_utc가 있으면 함께 기록합니다. 같은 파일의 재주입은 SHA256으로 중복을 방지합니다. 원본 주입 이력은 최신 온라인 snapshot 이후에도 남습니다.

Yahoo chart 경로는 변경되거나 차단될 수 있습니다. 출처 URL·조회 시각·가격 날짜·통화·snapshot ID로 사용 데이터를 확인하세요. 통화 환산은 하지 않으며 추가 종목의 계좌 통화는 가격 DB 통화와 일치해야 합니다.

## 운용 기준

- 기본식: `V_prev + Pool_prev/G + 이번 순입출금`.
- 실력식: `ROUND(V_prev + Pool_prev/G + (직전 주식평가액 - V_prev)/(2√G), 2) + 이번 순입출금`.
- 기본값: 15,000달러, 초기 매수 50%, G=10, 밴드 ±15%, 비용 0.05%, 회차 14달력일, Pool 사용률 50%.
- 초기 주수는 비용 포함 매수 가능 수량의 정수 내림입니다. 기존 계좌 이관에는 실제 주수·Pool·V를 직접 지정할 수 있습니다. 초기 상태는 생성 후 고정합니다.
- 미래 기본 설정과 확정 회차 설정을 구분합니다. 과거 회차를 바꾸려면 해당 회차 재계산을 명시적으로 실행합니다.
- 회차 시작 매수한도는 `시작 Pool × 사용률`입니다. 매도·배당으로 현금이 늘어도 한도를 다시 늘리지 않습니다.
- 거래·배당·비용·분할을 실제 기록으로 입력합니다. 과거 사건 수정·삭제는 이후 상태 전체를 재생하며, 잔고·한도 위반이면 저장하지 않습니다.
- 5,000달러 추가 입금은 flow 사건 하나로 기록합니다. Pool과 V에 각각 한 번 반영합니다. 회차 중 입금은 다음 회차 시작에 적용하며, 해당 회차 실제 입출금이 정기 예정액을 대체합니다. 대기 목록에서 반영일을 확인하세요.
- 실력 VR의 새 회차에는 직전 확정 종가가 필요합니다. 미입력 시 계산 대기이며 종가를 입력해 확정할 수 있습니다.
- 분할은 실제 주수만 바꿉니다. 단주가 생기는 분할은 브로커 현금 정산 후 정수 주수로 기록해야 합니다.
- 주문표는 최대 40개의 1주 단위 참고 예약 가격입니다. 매수는 호가 내림, 매도는 올림하며 비용 포함 누적 한도를 지킵니다. 주문을 증권사에 전송하는 기능은 없습니다.

## 백테스트 해석

수정종가를 사용하는 **종가 모형**입니다. 모형 주수는 실제 브로커 주수가 아니며, 수정종가에 반영된 배당을 현금에 다시 더하지 않습니다. 장중 예약주문 체결·세금·환전·현금 이자는 모형에 포함하지 않습니다.

첫 실제 거래일에 초기 매수를 하고 다음 거래일부터 밴드 매매를 판단합니다. 회차는 그 날짜를 기준으로 달력일을 계산하고, 새 회차 V에는 직전 실제 종가를 사용합니다. 가격을 보간하지 않습니다. 요청 범위와 사용된 실제 범위·가격 간격·상장 전 또는 미확보 날짜 경고를 함께 표시합니다.

총자산·순투입금·손익은 금액으로 표시합니다. TWR는 입출금 시 거래 전 평가액으로 성과 단위를 발행/상환하여 외부 자금 흐름을 제거하며, MDD는 이 단위가치 곡선의 최대 하락률입니다. 따라서 입금 자체를 수익으로 계산하지 않습니다. ROI(손익/순투입금)와 TWR의 의미는 다릅니다. 과다 인출과 전액 인출은 계산 오류로 중단합니다.

## 검증

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

브라우저 검증은 개발용 격리 DB의 8790 서버와 Playwright를 사용합니다. 2026-01-02~01-30의 QLD 가격이 있는 테스트 DB를 준비하고 실행하세요.

```bash
.venv/bin/python tests/prepare_browser.py --db /tmp/vr-browser-new.sqlite3
VR_DB_PATH=/tmp/vr-browser-new.sqlite3 .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8790
# 별도 터미널
npm install
npx playwright install chromium
VR_TEST_URL=http://localhost:8790 npm run test:browser
```

번들 Playwright를 사용할 경우 `PLAYWRIGHT_MODULE`에 모듈 경로를 지정할 수 있습니다. 브라우저 테스트는 테스트 계좌를 생성하므로 실계좌 DB에서 실행하지 않습니다. HTTP 쓰기에는 `x-vr-request: 1` 헤더가 필요합니다.

계산·가격 기준의 프로젝트 지식: [VR 가격과 장부](docs/solutions/vr-price-basis-and-ledger.md).
