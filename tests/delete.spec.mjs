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
const headers = { "x-vr-request": "1" };
const name = "계좌 & <삭제 검증>";
async function openDelete(accountName) {
  await page.locator("#delete-account").click();
  await page.getByRole("dialog", { name: "계좌 삭제 확인" }).waitFor();
  await page.locator("#delete-account-name").fill(accountName);
}
try {
  const original = await (await page.request.get(`${base}/api/portfolios`)).json();
  assert.equal(original.length, 0, "Start this suite with a new isolated test DB");
  const data = { name, symbol: "QLD", price: 100, start: "2026-01-02" };
  const account = await (await page.request.post(`${base}/api/portfolios`, { headers, data })).json();
  const other = await (await page.request.post(`${base}/api/portfolios`, {
    headers, data: { ...data, name: "보존 검증 계좌" },
  })).json();
  await page.goto(base);
  await page.locator("#account-name").filter({ hasText: name }).waitFor();
  await openDelete("틀린 이름");
  assert.equal(await page.locator("#confirm-delete-account").isDisabled(), true);
  assert.match(await page.locator("#delete-account-target").innerText(), /계좌 & <삭제 검증>/);
  await page.locator("#delete-account-name").fill(name);
  assert.equal(await page.locator("#confirm-delete-account").isEnabled(), true);
  await page.screenshot({ path: "test-results/delete-desktop.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "test-results/delete-mobile.png" });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  assert.ok(await page.locator("#delete-account-dialog").evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return rect.left >= 0 && rect.right <= innerWidth && rect.height <= innerHeight;
  }));
  await page.locator("#cancel-delete-account").click();
  assert.equal((await page.request.get(`${base}/api/portfolios/${account.id}`)).status(), 200);
  await openDelete(name);
  await page.keyboard.press("Escape");
  assert.equal(await page.locator("#delete-account-dialog").isVisible(), false);
  // A different tab changes the ledger after this page captured revision 1.
  await page.request.patch(`${base}/api/portfolios/${account.id}/settings`, {
    headers, data: { revision: 1, settings: { g: 12 } },
  });
  await openDelete(name);
  await page.locator("#confirm-delete-account").click();
  await page.locator("#delete-account-error").filter({ hasText: "revision 충돌" }).waitFor();
  assert.equal((await page.request.get(`${base}/api/portfolios/${account.id}`)).status(), 200);
  await page.locator("#cancel-delete-account").click();
  await page.locator("#reload-account").click();
  await page.locator("#revision-label").filter({ hasText: "저장 버전 2" }).waitFor();
  // A server failure leaves the account and selection intact.
  const url = `**/api/portfolios/${account.id}`;
  await page.route(url, (route) => route.request().method() === "DELETE"
    ? route.fulfill({ status: 500, contentType: "application/json", body: '{"detail":"테스트 연결 실패"}' })
    : route.continue());
  await openDelete(name);
  await page.locator("#confirm-delete-account").click();
  await page.locator("#delete-account-error").filter({ hasText: "테스트 연결 실패" }).waitFor();
  assert.equal(await page.locator("#account-select").inputValue(), account.id);
  await page.locator("#cancel-delete-account").click();
  await page.unroute(url);
  // An earlier GET arrives after deletion: it must not resurrect the account.
  const old = await (await page.request.get(`${base}/api/portfolios/${account.id}`)).json();
  let releaseGet;
  const getGate = new Promise((resolve) => { releaseGet = resolve; });
  let announceGet;
  const getStarted = new Promise((resolve) => { announceGet = resolve; });
  await page.route(url, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    announceGet();
    await getGate;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(old) });
  });
  await page.locator("#reload-account").click();
  await getStarted;
  await openDelete(name);
  await page.locator("#confirm-delete-account").click();
  await page.locator("#account-name").filter({ hasText: other.name }).waitFor();
  const returnedGet = page.waitForResponse((response) => response.url().endsWith(account.id)
    && response.request().method() === "GET");
  releaseGet();
  await (await returnedGet).finished();
  await page.waitForLoadState("networkidle");
  assert.equal(await page.locator(`#account-select option[value="${account.id}"]`).count(), 0);
  assert.equal(await page.locator("#account-name").innerText(), other.name);
  assert.equal(await page.locator("#toast").innerText(), `‘${name}’ 계좌와 기록을 삭제했습니다.`);
  assert.equal((await page.request.get(`${base}/api/portfolios/${account.id}`)).status(), 404);
  assert.equal(await page.locator("#account-select").inputValue(), other.id);
  const surviving = await (await page.request.get(`${base}/api/portfolios/${other.id}`)).json();
  assert.deepEqual(surviving, other);
  assert.ok((await (await page.request.get(`${base}/api/prices/QLD?start=2026-01-02&end=2026-01-30`)).json()).length);
  await page.unroute(url);
  await page.reload();
  await page.locator("#account-name").filter({ hasText: other.name }).waitFor();
  await openDelete(other.name);
  await page.locator("#confirm-delete-account").click();
  await page.locator("#account-empty").waitFor();
  assert.equal(await page.locator("#delete-account").isDisabled(), true);
  assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem("vr.account"))), null);
  await page.reload();
  await page.locator("#account-empty").waitFor();
  assert.deepEqual(await (await page.request.get(`${base}/api/portfolios`)).json(), []);
  assert.deepEqual(errors, []);
  console.log("PASS: account deletion confirmation/cancel, revision conflict, failure preservation, stale GET, other account/prices, last-account empty state, reload, desktop/mobile");
} finally {
  await browser.close();
}
