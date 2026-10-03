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
const mutations = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("request", (request) => {
  if (request.url().includes("/api/") && request.method() !== "GET")
    mutations.push(request.url());
});
try {
  await page.goto(`${base}/#constructor`);
  await page
    .getByRole("heading", { name: "오늘의 VR 운용", exact: true })
    .waitFor();
  await page.getByRole("button", { name: "백테스트", exact: true }).click();
  await page.locator("#bt-symbols").fill("QLD");
  await page.locator("#bt-start").fill("2026-01-02");
  await page.locator("#bt-end").fill("2026-01-30");
  await page.locator("#bt-capital").fill("20000");
  await page.locator("#bt-g").fill("12");
  await page.locator("#bt-fee").fill("0.15");
  await page.locator("#bt-flows").fill("2026-01-05, 100");
  await page
    .getByRole("button", { name: "백테스트 실행", exact: true })
    .click();
  await page.locator("#results-summary tbody tr").first().waitFor();
  mutations.length = 0;
  await page.goto(`${base}/#guide-fees`);
  await page
    .getByRole("heading", { name: "VR 사용 설명", exact: true })
    .waitFor();
  await page.waitForFunction(() => {
    const top = document
      .querySelector("#guide-fees")
      .getBoundingClientRect().top;
    return top >= 0 && top < innerHeight;
  });
  assert.equal(await page.locator("#default-fee").inputValue(), "0.25");
  await page.locator("#default-fee").fill("0.35");
  await page
    .getByRole("button", { name: "새 계좌·백테스트 기본값 저장" })
    .click();
  await page.locator("#default-fee-status").waitFor();
  await page.reload();
  assert.equal(await page.locator("#default-fee").inputValue(), "0.35");
  await page.getByRole("button", { name: "운용 장부", exact: true }).click();
  await page.getByRole("button", { name: "새 계좌", exact: true }).click();
  assert.equal(await page.locator("#create-fee").inputValue(), "0.35");
  assert.equal(new URL(page.url()).hash, "#operations");
  await page.reload();
  await page
    .getByRole("heading", { name: "오늘의 VR 운용", exact: true })
    .waitFor();
  await page.getByRole("button", { name: "백테스트", exact: true }).click();
  assert.equal(await page.locator("#bt-fee").inputValue(), "0.35");
  assert.equal(await page.locator("#bt-g").inputValue(), "12");
  assert.equal(await page.locator("#bt-capital").inputValue(), "20000");
  assert.equal(await page.locator("#bt-flows").inputValue(), "2026-01-05, 100");
  await page.locator("#bt-flows").fill("아직 입력 중인 내용");
  await page.getByRole("button", { name: "사용 설명", exact: true }).click();
  await page.locator("#default-fee").fill("0");
  await page
    .getByRole("button", { name: "새 계좌·백테스트 기본값 저장" })
    .click();
  assert.equal(await page.locator("#bt-fee").inputValue(), "0");
  assert.equal(
    await page.locator("#bt-flows").inputValue(),
    "아직 입력 중인 내용",
  );
  for (const href of await page
    .locator(".guide-toc a")
    .evaluateAll((links) => links.map((link) => link.getAttribute("href")))) {
    await page.locator(`.guide-toc a[href="${href}"]`).click();
    assert.equal(await page.locator(href).isVisible(), true);
    assert.equal(new URL(page.url()).hash, href);
    await page.waitForFunction((selector) => {
      const top = document.querySelector(selector).getBoundingClientRect().top;
      return top >= 0 && top < innerHeight;
    }, href);
  }
  await page.goto(`${base}/#help`);
  await page
    .getByRole("heading", { name: "VR 사용 설명", exact: true })
    .waitFor();
  await page.screenshot({
    path: "test-results/guide-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "test-results/guide-mobile.png",
    fullPage: true,
  });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
    "guide mobile overflow",
  );
  assert.deepEqual(
    mutations,
    [],
    "guide and personal fee preference must not mutate the account database",
  );
  assert.equal(await page.locator("#default-fee").inputValue(), "0");
  await page.locator("#default-fee").fill("0.25");
  await page
    .getByRole("button", { name: "새 계좌·백테스트 기본값 저장" })
    .click();
  await page.getByRole("button", { name: "운용 장부", exact: true }).click();
  await page.getByRole("button", { name: "새 계좌", exact: true }).click();
  await page.locator("#create-name").fill("기본 비용률 연결 검증");
  await page.locator("#create-start").fill("2026-01-02");
  await page.locator("#create-price").fill("100");
  await page.getByRole("button", { name: "계좌 만들기", exact: true }).click();
  await page
    .locator("#account-name")
    .filter({ hasText: "기본 비용률 연결 검증" })
    .waitFor();
  assert.equal(await page.locator("#metric-pool").innerText(), "7,581.50");
  assert.equal(await page.locator("#account-fee").inputValue(), "0.25");
  assert.deepEqual(errors, []);
  console.log(
    "PASS: guide deep links, all contents links, tab reload, personal fee persistence including zero, unfinished backtest preserved, desktop/mobile, no guide API writes, new account fee calculation, no console errors",
  );
} finally {
  await browser.close();
}
