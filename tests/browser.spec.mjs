import { createRequire } from "node:module";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const base = process.env.VR_TEST_URL || "http://localhost:8790";
await mkdir("test-results", { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
try {
  await page.goto(base);
  await page.getByRole("heading", { name: "오늘의 VR 운용" }).waitFor();
  await page.getByRole("button", { name: "새 계좌" }).click();
  await page.locator("#create-name").fill("브라우저 검증 계좌");
  await page.locator("#create-price").fill("100");
  await page.locator("#create-start").fill("2026-01-02");
  await page.getByRole("button", { name: "계좌 만들기", exact: true }).click();
  await page
    .locator("#account-name")
    .filter({ hasText: "브라우저 검증 계좌" })
    .waitFor();
  assert.equal(await page.locator("#metric-qty").innerText(), "74");
  await page.reload();
  await page
    .locator("#account-name")
    .filter({ hasText: "브라우저 검증 계좌" })
    .waitFor();
  await page.locator("#event-kind").selectOption("flow");
  await page.locator("#event-date").fill("2026-01-05");
  await page.locator("#event-amount").fill("5000");
  await page.getByRole("button", { name: "장부에 기록", exact: true }).click();
  await page
    .locator("#pending-flows")
    .filter({ hasText: "2026-01-16" })
    .waitFor();
  await page.getByRole("button", { name: "수정", exact: true }).first().click();
  await page.locator("#event-amount").fill("5100");
  await page.getByRole("button", { name: "변경 저장", exact: true }).click();
  await page.locator("#ledger-body").filter({ hasText: "5,100" }).waitFor();
  await page.getByRole("button", { name: "삭제", exact: true }).first().click();
  await page
    .locator("#ledger-body")
    .filter({ hasText: "아직 기록이 없습니다" })
    .waitFor();
  await page.locator("#event-kind").selectOption("buy");
  await page.locator("#event-date").fill("2026-01-05");
  await page.locator("#event-qty").fill("9999");
  await page.locator("#event-price").fill("100");
  await page.getByRole("button", { name: "장부에 기록", exact: true }).click();
  await page.locator("#event-error").filter({ hasText: "부족" }).waitFor();
  assert.match(
    await page.locator("#ledger-body").innerText(),
    /아직 기록이 없습니다/,
  );
  await page.locator("#event-kind").selectOption("flow");
  await page.locator("#event-date").fill("2026-01-05");
  await page.locator("#event-amount").fill("5000");
  await page.getByRole("button", { name: "장부에 기록", exact: true }).click();
  await page
    .locator("#pending-flows")
    .filter({ hasText: "2026-01-16" })
    .waitFor();
  await page.locator("#next-start").fill("2026-01-16");
  await page
    .getByRole("button", { name: "다음 회차 시작", exact: true })
    .click();
  await page
    .locator("#waiting-notice")
    .filter({ hasText: "직전 종가" })
    .waitFor();
  await page.locator("#cycle-close").fill("100");
  await page
    .getByRole("button", { name: "선택 회차 재계산", exact: true })
    .click();
  await page.waitForFunction(
    () => document.querySelector("#waiting-notice").hidden,
  );
  assert.equal(await page.locator("#metric-pool").innerText(), "12,596.30");
  await page.getByRole("button", { name: "새 계좌", exact: true }).click();
  await page.locator("#create-name").fill("추가 종목 AAPL 검증");
  await page.locator("#create-symbol").fill("AAPL");
  await page.locator("#create-currency").fill("USD");
  await page.locator("#create-price").fill("100");
  await page.locator("#create-start").fill("2026-01-02");
  await page.getByRole("button", { name: "계좌 만들기", exact: true }).click();
  await page
    .locator("#account-name")
    .filter({ hasText: "추가 종목 AAPL 검증" })
    .waitFor();
  await page.reload();
  await page
    .locator("#account-name")
    .filter({ hasText: "추가 종목 AAPL 검증" })
    .waitFor();
  await page.getByRole("button", { name: "가격 데이터", exact: true }).click();
  await page.route("**/api/prices/sync", async (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        symbol: "AAPL",
        rows: 8,
        first_date: "2026-01-02",
        last_date: "2026-10-01",
        currency: "USD",
        snapshot_years: 10,
      }),
    }),
  );
  await page.locator("#sync-symbol").fill("AAPL");
  await page
    .getByRole("button", { name: "가격 가져오기", exact: true })
    .click();
  await page
    .locator("#sync-status")
    .filter({ hasText: "AAPL: 8행 확보" })
    .waitFor();
  await page.unroute("**/api/prices/sync");
  await page.route("**/api/prices/sync", async (route) =>
    route.fulfill({
      status: 422,
      contentType: "application/json",
      body: JSON.stringify({ detail: "검증용 공급자 오류: 기존 가격 보존" }),
    }),
  );
  await page.locator("#sync-symbol").fill("AAPL");
  await page
    .getByRole("button", { name: "가격 가져오기", exact: true })
    .click();
  await page
    .locator("#sync-error")
    .filter({ hasText: "기존 가격 보존" })
    .waitFor();
  await page.screenshot({ path: "test-results/desktop.png", fullPage: true });
  await page.getByRole("button", { name: "백테스트", exact: true }).click();
  await page.locator("#bt-symbols").fill("QLD");
  await page.locator("#bt-start").fill("2026-01-02");
  await page.locator("#bt-end").fill("2026-01-30");
  await page
    .getByRole("button", { name: "백테스트 실행", exact: true })
    .click();
  await page.locator("#results-summary tbody tr").first().waitFor();
  assert.equal(await page.locator("#results-summary tbody tr").count(), 2);
  await page.locator("#performance-chart svg").waitFor();
  await page.screenshot({
    path: "test-results/backtest-desktop.png",
    fullPage: true,
  });
  const before = await page.locator("#results-summary").innerText();
  await page.locator("#bt-g").fill("3");
  await page
    .getByRole("button", { name: "백테스트 실행", exact: true })
    .click();
  await page.waitForFunction(
    (old) => document.querySelector("#results-summary").innerText !== old,
    before,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(
    () => document.querySelector("#performance-chart svg").viewBox.baseVal.width < 400,
    null,
    { timeout: 3000 },
  );
  await page.screenshot({ path: "test-results/mobile.png", fullPage: true });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
    "mobile overflow",
  );
  assert.deepEqual(errors, []);
  console.log(
    "PASS: account, persistence, flow edit/delete, invalid rollback, waiting/resolution, sync error, comparative backtest, option effects, desktop/mobile, no console errors",
  );
} finally {
  await browser.close();
}
