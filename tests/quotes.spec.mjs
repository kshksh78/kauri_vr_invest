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
page.on("pageerror", (error) => errors.push(error.message));
let price = 120.001, fail = false, release, started;
function quote(symbol) {
  return { symbol, price: symbol === "SOXL" ? price : 95.4321, currency: "USD",
    as_of: "2026-10-15T20:05:00+00:00", fetched_at: "2026-10-15T20:06:00+00:00",
    session: "post", provider: "Yahoo Finance" };
}
try {
  const create = async (symbol) => {
    const response = await page.request.post(`${base}/api/portfolios`, {
      headers: { "x-vr-request": "1" },
      data: { name: `최신 시세 ${symbol}`, symbol, start: "2026-01-02", price: 100 },
    });
    assert.equal(response.status(), 201);
    return response.json();
  };
  const soxl = await create("SOXL"), qld = await create("QLD");
  await page.addInitScript((id) => localStorage.setItem("vr.account", JSON.stringify(id)), soxl.id);
  await page.route("**/api/quotes/*", async (route) => {
    const symbol = new URL(route.request().url()).pathname.split("/").at(-1);
    const data = quote(symbol);
    if (release && symbol === "SOXL") {
      const gate = release;
      started();
      await gate;
    }
    await route.fulfill({ status: fail ? 422 : 200, contentType: "application/json",
      body: JSON.stringify(fail ? { detail: "공급자 연결 실패" } : data) });
  });
  await page.goto(base);
  await page.locator("#account-select").selectOption(soxl.id);
  await page.locator("#quote-status").filter({ hasText: "가격 조회 완료" }).waitFor();
  assert.equal(await page.locator("#quote-symbol").innerText(), "SOXL");
  assert.equal(await page.locator("#quote-price").innerText(), "120.0010");
  assert.match(await page.locator("#quote-time").innerText(), /2026.*10.*16.*한국시간/);
  assert.equal(await page.locator("#quote-session").innerText(), "장후 시세");
  price = 121.1234;
  await page.getByRole("button", { name: "가격 새로고침" }).click();
  await page.locator("#quote-price").filter({ hasText: "121.1234" }).waitFor();
  assert.deepEqual(await (await page.request.get(`${base}/api/portfolios/${soxl.id}`)).json(), soxl);

  fail = true;
  await page.getByRole("button", { name: "가격 새로고침" }).click();
  await page.locator("#quote-error").filter({ hasText: "공급자 연결 실패" }).waitFor();
  assert.equal(await page.locator("#quote-price").innerText(), "121.1234");
  assert.match(await page.locator("#quote-status").innerText(), /이전에 조회한 가격/);
  assert.equal(await page.locator("#refresh-quote").isEnabled(), true);
  await page.locator("#account-select").selectOption(qld.id);
  await page.locator("#quote-error").filter({ hasText: "공급자 연결 실패" }).waitFor();
  assert.equal(await page.locator("#quote-symbol").innerText(), "QLD");
  assert.equal(await page.locator("#quote-price").innerText(), "—");

  fail = false;
  await page.getByRole("button", { name: "가격 새로고침" }).click();
  await page.locator("#quote-price").filter({ hasText: "95.4321" }).waitFor();
  let finish;
  release = new Promise((resolve) => { finish = resolve; });
  const requestStarted = new Promise((resolve) => { started = resolve; });
  await page.locator("#account-select").selectOption(soxl.id);
  await requestStarted;
  assert.equal(await page.locator("#refresh-quote").isDisabled(), true);
  await page.locator("#account-select").selectOption(qld.id);
  await page.locator("#quote-status").filter({ hasText: "가격 조회 완료" }).waitFor();
  const oldResponse = page.waitForResponse((response) => response.url().endsWith("/api/quotes/SOXL"));
  finish();
  await (await oldResponse).finished();
  await page.waitForLoadState("networkidle");
  assert.equal(await page.locator("#quote-symbol").innerText(), "QLD");
  assert.equal(await page.locator("#quote-price").innerText(), "95.4321");
  release = null;
  await page.locator("#account-select").selectOption(soxl.id);
  await page.locator("#quote-status").filter({ hasText: "가격 조회 완료" }).waitFor();
  await page.screenshot({ path: "test-results/quotes-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "test-results/quotes-mobile.png", fullPage: true });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "mobile overflow");
  assert.deepEqual(errors, []);
  console.log("PASS: latest quote, refresh, four decimals, timestamps, stale/empty errors, account switch race, ledger unchanged, desktop/mobile");
} finally {
  await browser.close();
}
