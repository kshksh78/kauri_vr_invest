---
title: 계좌 삭제 후 늦은 조회 응답으로 계좌가 다시 표시되는 문제 방지
date: 2026-10-08
module: 계좌 장부와 화면 상태
problem_type: convention
tags: [account-deletion, sqlite, revision, async-ui]
---

# 계좌 삭제의 저장 범위와 늦은 응답

계좌의 초기 상태, 거래·입출금 사건, 확정 회차는 `portfolios.document` 한 행에 함께 저장된다. 삭제는 계좌 ID로 이 행만 제거한다. 가격 snapshot과 원본 import 기록은 계좌마다 따로 소유하지 않는 공용 데이터이므로 삭제하지 않는다.

확인 화면에서 가져온 계좌 ID·revision·계좌명을 요청에 고정한다. DB에서 `BEGIN IMMEDIATE` 후 최신 revision과 계좌명을 확인하고 같은 트랜잭션 안에서 삭제한다. 다른 창에서 장부가 변경되었다면 409를 반환하고 삭제하지 않는다.

삭제 전에 실행한 GET이 삭제 후 도착할 수 있다. 기존 `applyAccount`는 선택 상태 검사보다 먼저 계좌 캐시에 응답을 넣으므로, 선택 세대만 증가시키면 삭제한 계좌가 선택 목록에 다시 나타날 수 있다. 삭제 성공 ID를 현재 페이지의 Set에 기록하고 `applyAccount`의 첫 단계에서 그 ID의 응답을 거부한다. 목록 조회도 같은 Set으로 걸러내며 성공 시 선택 세대를 증가시켜 진행 중인 이전 목록 조회를 무효화한다. 새 계좌 ID는 UUID이고 페이지 재시작 시에는 DB 목록을 다시 읽으므로 Set을 영구 저장할 필요가 없다.

`tests/test_api.py`는 삭제 확인·revision·로컬 요청 보호와 다른 계좌·가격 보존 및 재시작 후 삭제 상태를 검증한다. `tests/delete.spec.mjs`는 삭제 전 GET의 응답을 지연시킨 뒤 삭제를 완료하고, 지연 응답 도착 후에도 삭제 ID가 목록에 복귀하지 않는지 검증한다. 브라우저 테스트는 새 격리 DB에서만 실행한다.
