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
  await page.locator("#create-fee").fill("0.05");
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
  const otherAccountId = await page.locator("#account-select").inputValue();
  await page.reload();
  await page
    .locator("#account-name")
    .filter({ hasText: "추가 종목 AAPL 검증" })
    .waitFor();
  await page.getByRole("button", { name: "새 계좌", exact: true }).click();
  await page.locator("#create-name").fill("기존 보유 반복 증액 검증");
  await page.locator("#create-symbol").fill("QLD");
  await page
    .locator("#create-initialization-mode")
    .selectOption("existing_holdings");
  await page.locator("#create-price").fill("100");
  await page.locator("#create-start").fill("2026-01-02");
  await page.locator("#create-qty").fill("100");
  await page.locator("#create-fee").fill("0.05");
  await page.locator("#create-pool").fill("5000");
  await page.locator("#create-periodic_flow").fill("100");
  await page.getByRole("button", { name: "계좌 만들기", exact: true }).click();
  await page
    .locator("#account-name")
    .filter({ hasText: "기존 보유 반복 증액 검증" })
    .waitFor();
  assert.equal(await page.locator("#metric-qty").innerText(), "100");
  assert.equal(await page.locator("#metric-pool").innerText(), "5,000.00");
  assert.match(
    await page.locator("#seed-values").textContent(),
    /초기 매수 비용0\.00 USD/,
  );
  await page.locator("#event-kind").selectOption("buy");
  await page.locator("#event-date").fill("2026-01-05");
  await page.locator("#event-qty").fill("1");
  await page.locator("#event-price").fill("100");
  await page.locator("#event-fee").fill("1");
  await page.getByRole("button", { name: "장부에 기록", exact: true }).click();
  await page.waitForFunction(
    () => document.querySelector("#metric-pool").textContent === "4,899.00",
  );
  await page.getByRole("button", { name: "수정", exact: true }).first().click();
  await page.locator("#event-fee").fill("");
  await page.getByRole("button", { name: "변경 저장", exact: true }).click();
  await page.waitForFunction(
    () => document.querySelector("#metric-pool").textContent === "4,899.95",
    null,
    { timeout: 3000 },
  );
  await page.getByRole("button", { name: "삭제", exact: true }).first().click();
  await page.waitForFunction(
    () => document.querySelector("#metric-pool").textContent === "5,000.00",
  );
  for (const [date, amount] of [
    ["2026-01-05", "2000"],
    ["2026-01-12", "3000"],
  ]) {
    await page.locator("#event-kind").selectOption("flow");
    await page.locator("#event-date").fill(date);
    await page.locator("#event-amount").fill(amount);
    const saved = page.waitForResponse(
      (r) => r.url().includes("/events") && r.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "장부에 기록", exact: true })
      .click();
    assert.equal((await saved).status(), 201);
    await page
      .locator("#ledger-body")
      .filter({ hasText: Number(amount).toLocaleString("ko-KR") })
      .waitFor();
  }
  assert.equal(await page.locator("#metric-pool").innerText(), "5,000.00");
  assert.match(
    await page.locator("#funding-summary").innerText(),
    /미반영 순입출금: 5,000\.00 USD/,
  );
  await page.locator("#next-start").fill("2026-01-16");
  await page.locator("#next-close").fill("100");
  await page
    .getByRole("button", { name: "다음 회차 시작", exact: true })
    .click();
  await page.waitForFunction(
    () => document.querySelector("#metric-pool").textContent === "10,000.00",
  );
  assert.equal(await page.locator("#metric-v").innerText(), "15,500.00");
  assert.match(
    await page.locator("#funding-summary").innerText(),
    /누적 순투입금: 20,000\.00 USD/,
  );
  await page.reload();
  await page
    .locator("#account-name")
    .filter({ hasText: "기존 보유 반복 증액 검증" })
    .waitFor();
  assert.equal(await page.locator("#metric-pool").innerText(), "10,000.00");
  const activeAccountId = await page.locator("#account-select").inputValue();
  let releaseAccount, accountRequestStarted;
  const accountGate = new Promise((resolve) => {
    releaseAccount = resolve;
  });
  const accountStarted = new Promise((resolve) => {
    accountRequestStarted = resolve;
  });
  const accountRoute = `**/api/portfolios/${activeAccountId}`;
  await page.route(accountRoute, async (route) => {
    const response = await route.fetch();
    accountRequestStarted();
    await accountGate;
    await route.fulfill({ response });
  });
  const delayedAccount = page.waitForResponse((response) =>
    response.url().endsWith(`/api/portfolios/${activeAccountId}`),
  );
  await page.locator("#reload-account").click();
  await accountStarted;
  await page.locator("#account-select").selectOption(otherAccountId);
  await page.locator("#event-kind").selectOption("flow");
  await page.locator("#event-amount").fill("777");
  releaseAccount();
  await (await delayedAccount).finished();
  await page.waitForLoadState("networkidle");
  assert.equal(
    await page.locator("#account-select").inputValue(),
    otherAccountId,
  );
  assert.equal(await page.locator("#event-amount").inputValue(), "777");
  await page.unroute(accountRoute);
  await page.locator("#account-select").selectOption(activeAccountId);
  await page
    .locator("#latest-valuation")
    .filter({ hasText: "19,000.00 USD" })
    .waitFor();
  let releaseQuote, quoteRequestStarted;
  const quoteGate = new Promise((resolve) => {
    releaseQuote = resolve;
  });
  const quoteStarted = new Promise((resolve) => {
    quoteRequestStarted = resolve;
  });
  let quoteRequests = 0;
  const quoteRoute = "**/api/prices/QLD?*";
  await page.route(quoteRoute, async (route) => {
    if (++quoteRequests !== 1) return route.continue();
    const response = await route.fetch();
    quoteRequestStarted();
    await quoteGate;
    await route.fulfill({ response });
  });
  await page.locator("#reload-account").click();
  await quoteStarted;
  await page.locator("#event-kind").selectOption("cost");
  await page.locator("#event-date").fill("2026-01-16");
  await page.locator("#event-amount").fill("100");
  await page.getByRole("button", { name: "장부에 기록", exact: true }).click();
  await page
    .locator("#latest-valuation")
    .filter({ hasText: "18,900.00 USD" })
    .waitFor();
  const delayedQuote = page.waitForResponse((response) =>
    response.url().includes("/api/prices/QLD?"),
  );
  releaseQuote();
  await (await delayedQuote).finished();
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
  assert.match(
    await page.locator("#latest-valuation").innerText(),
    /18,900\.00 USD/,
  );
  await page.unroute(quoteRoute);
  await page.getByRole("button", { name: "삭제", exact: true }).last().click();
  await page.waitForFunction(
    () => document.querySelector("#metric-pool").textContent === "10,000.00",
  );
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
  await page
    .locator("#bt-initialization-mode")
    .selectOption("existing_holdings");
  await page.locator("#bt-qty").fill("100");
  await page.locator("#bt-pool").fill("5000");
  await page.locator("#bt-flows").fill("2026-01-05, 2000\n2026-01-12, 3000");
  const existingResult = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/backtests") && r.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "백테스트 실행", exact: true })
    .click();
  const existingData = await (await existingResult).json();
  assert.equal(existingData.results[0].daily[0].trade, null);
  assert.equal(existingData.results[0].daily[0].equity, 15000);
  await page.locator("#chart-metric").selectOption("equity");
  await page
    .locator('#performance-chart svg[aria-label="날짜별 총자산 USD"]')
    .waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(
    () =>
      document.querySelector("#performance-chart svg").viewBox.baseVal.width <
      400,
    null,
    { timeout: 3000 },
  );
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "test-results/mobile.png", fullPage: true });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
    "mobile overflow",
  );
  assert.deepEqual(errors, []);
  console.log(
    "PASS: account, persistence, flow edit/delete, invalid rollback, waiting/resolution, existing holdings without fees, repeated funding and planned override, sync error, comparative/existing backtest, equity chart, option effects, desktop/mobile, no console errors",
  );
} finally {
  await browser.close();
}
