"use strict";
const $ = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const num = (value, digits = 2) =>
  value == null
    ? "—"
    : Number(value).toLocaleString("ko-KR", {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits,
      });
const pct = (value) => (value == null ? "—" : `${num(value * 100)}%`);
const modeName = (mode) => (mode === "skilled" ? "실력 VR" : "기본 VR");
const kindName = (kind) =>
  ({
    buy: "매수",
    sell: "매도",
    flow: "외부 입출금",
    dividend: "배당",
    cost: "비용",
    split: "분할",
  })[kind] || kind;
const defaults = {
  mode: "skilled",
  g: 10,
  band: 0.15,
  fee: 0.0025,
  tick: 0.01,
  cycle_days: 14,
  pool_usage: 0.5,
  periodic_flow: 0,
};
let account = null,
  portfolios = [],
  prices = [],
  eventId = null,
  results = [],
  toastTimer;
let accountSelection = 0,
  valuationGeneration = 0;
const deletedAccountIds = new Set();
let deleteTarget = null,
  deletingAccount = false;
function remember(key, value) {
  try {
    localStorage.setItem(`vr.${key}`, JSON.stringify(value));
  } catch {}
}
function recall(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(`vr.${key}`)) ?? fallback;
  } catch {
    return fallback;
  }
}
const savedFee = recall("defaultFee", null);
if (typeof savedFee === "number" && savedFee >= 0 && savedFee < 1)
  defaults.fee = savedFee;
function showMessage(id, text) {
  $(id).textContent = text || "";
  $(id).hidden = !text;
}
function toast(text) {
  clearTimeout(toastTimer);
  showMessage("toast", text);
  toastTimer = setTimeout(() => ($("toast").hidden = true), 3500);
}
function errorText(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((x) => `${(x.loc || []).join(" · ")}: ${x.msg}`)
      .join("\n");
  return JSON.stringify(detail || "요청을 처리하지 못했습니다.");
}
async function api(path, method = "GET", data) {
  const response = await fetch(path, {
    method,
    headers: { "content-type": "application/json", "x-vr-request": "1" },
    ...(data === undefined ? {} : { body: JSON.stringify(data) }),
  });
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error("서버 응답을 읽을 수 없습니다. 서버 연결을 확인하세요.");
  }
  if (!response.ok) {
    const error = new Error(errorText(body.detail));
    error.status = response.status;
    throw error;
  }
  return body;
}
async function action(form, errorId, task) {
  const buttons = [...form.querySelectorAll("button")];
  buttons.forEach((b) => (b.disabled = true));
  showMessage(errorId, "");
  try {
    await task();
  } catch (e) {
    showMessage(
      errorId,
      e.message +
        (e.status === 409
          ? " 현재 화면은 갱신되지 않았습니다. “새로 불러오기” 후 내용을 확인하고 다시 저장하세요."
          : ""),
    );
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}
function settingsMarkup(prefix, values = defaults, includeMode = true) {
  const fields = [
    ["g", "G · 성장 계수", values.g, "0.000001", "any", null],
    ["band", "밴드 폭 (%)", values.band * 100, "0.000001", "any", "99.999999"],
    ["fee", "거래 비용률 (%)", values.fee * 100, "0", "any", "99.999999"],
    ["tick", "지정가 호가 단위", values.tick, "0.000001", "any", null],
    ["cycle_days", "회차 길이 · 달력일", values.cycle_days, "1", "1", "365"],
    [
      "pool_usage",
      "회차 Pool 사용 한도 (%)",
      values.pool_usage * 100,
      "0",
      "any",
      "100",
    ],
    [
      "periodic_flow",
      "회차별 예정 입출금",
      values.periodic_flow,
      null,
      "any",
      null,
    ],
  ];
  return (
    (includeMode
      ? `<label>운용 방식<select id="${prefix}-mode" data-setting="mode"><option value="skilled" ${values.mode === "skilled" ? "selected" : ""}>실력 VR · REV2</option><option value="basic" ${values.mode === "basic" ? "selected" : ""}>기본 VR</option></select></label>`
      : "") +
    fields
      .map(
        ([key, label, value, min, step, max]) =>
          `<label>${label}<input id="${prefix}-${key}" data-setting="${key}" type="number" value="${esc(value)}" ${min === null ? "" : `min="${min}"`} ${max === null ? "" : `max="${max}"`} step="${step}" required></label>`,
      )
      .join("")
  );
}
function readSettings(container, fallback = defaults) {
  const value = { ...fallback };
  $(container)
    .querySelectorAll("[data-setting]")
    .forEach((input) => {
      const key = input.dataset.setting;
      value[key] =
        key === "mode"
          ? input.value
          : Number(input.value) /
            (["band", "fee", "pool_usage"].includes(key) ? 100 : 1);
    });
  return value;
}
function setSettings(container, prefix, values, includeMode = true) {
  $(container).innerHTML = settingsMarkup(prefix, values, includeMode);
}
function money(value, currency = account?.currency || "USD") {
  return value == null ? "—" : `${num(value)} ${currency}`;
}
function switchTab(name) {
  const titles = {
    operations: [
      "오늘의 VR 운용",
      "기준 가치와 현금 Pool을 확인하고, 다음 거래를 준비하세요.",
    ],
    backtest: [
      "규칙을 검증하는 백테스트",
      "같은 가격과 투자금으로 기본 VR과 실력 VR의 성과를 비교하세요.",
    ],
    prices: [
      "나의 가격 데이터",
      "실제 가격의 기간과 출처를 확인하고 필요한 데이터를 확보하세요.",
    ],
    help: [
      "VR 사용 설명",
      "계좌 만들기부터 예약 주문과 다음 회차까지, 순서대로 알아보세요.",
    ],
  };
  if (!Object.hasOwn(titles, name)) name = "operations";
  document
    .querySelectorAll(".page-section")
    .forEach((panel) => (panel.hidden = panel.id !== name));
  document
    .querySelectorAll(".nav-button")
    .forEach((button) =>
      button.classList.toggle("active", button.dataset.tab === name),
    );
  $("page-title").textContent = titles[name][0];
  $("page-description").textContent = titles[name][1];
  remember("tab", name);
  if (
    location.hash.slice(1) !== name &&
    !(name === "help" && location.hash.startsWith("#guide-"))
  )
    history.replaceState(null, "", `#${name}`);
  if (name === "prices")
    loadPrices().catch((error) => showMessage("sync-error", error.message));
}
function openCreate() {
  $("create-panel").hidden = false;
  $("create-name").focus();
}
function renderAccounts() {
  const selected = account?.id || recall("account", null);
  $("account-select").innerHTML =
    '<option value="">계좌를 선택하세요</option>' +
    portfolios
      .map(
        (p) =>
          `<option value="${esc(p.id)}" ${p.id === selected ? "selected" : ""}>${esc(p.name)} · ${esc(p.symbol)} (${esc(p.currency)})</option>`,
      )
      .join("");
}
async function loadAccounts() {
  const selection = accountSelection;
  const loaded = await api("/api/portfolios");
  if (selection !== accountSelection) return;
  portfolios = loaded.filter((p) => !deletedAccountIds.has(p.id));
  const selected = recall("account", null);
  account = portfolios.find((p) => p.id === selected) || portfolios[0] || null;
  renderAccounts();
  renderAccount();
}
function applyAccount(value, select = false, selection = accountSelection) {
  if (deletedAccountIds.has(value.id)) return false;
  const index = portfolios.findIndex((p) => p.id === value.id);
  if (index >= 0 && portfolios[index].revision > value.revision) return false;
  if (index < 0) portfolios.push(value);
  else portfolios[index] = value;
  if (!select && (selection !== accountSelection || account?.id !== value.id)) {
    renderAccounts();
    return false;
  }
  if (select) accountSelection++;
  account = value;
  remember("account", value.id);
  renderAccounts();
  renderAccount();
  return true;
}
async function requestAccount(path, method = "GET", data) {
  const selection = accountSelection;
  return applyAccount(await api(path, method, data), false, selection);
}
function addDays(day, amount) {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + amount);
  while (date.getUTCDay() === 0 || date.getUTCDay() === 6)
    date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}
function keyValues(id, items) {
  $(id).innerHTML = items
    .map(([label, value]) => `<dt>${esc(label)}</dt><dd>${esc(value)}</dd>`)
    .join("");
}
function renderInitialization(prefix) {
  const existing =
    $(`${prefix}-initialization-mode`).value === "existing_holdings";
  document.querySelectorAll(`[data-${prefix}-purchase]`).forEach((label) => {
    label.hidden = existing;
    label.querySelector("input").disabled = existing;
  });
  const fields = $(`${prefix}-existing-fields`);
  fields.hidden = !existing;
  fields.querySelectorAll("input").forEach((input) => {
    input.disabled = !existing;
    input.required =
      existing && [`${prefix}-qty`, `${prefix}-pool`].includes(input.id);
  });
  if (prefix === "create") {
    $("create-price-label").textContent = existing
      ? "시작일 기준 평가가격"
      : "실제 초기 체결가";
    $("create-price").placeholder = existing
      ? "시작일 실제 가격 입력"
      : "증권사 체결가 입력";
    renderOpeningEquity();
  }
}
function renderOpeningEquity() {
  const inputs = ["create-qty", "create-price", "create-pool"].map(
    (id) => $(id).value,
  );
  $("create-opening-equity").textContent = inputs.every((value) => value !== "")
    ? `시작 자산: ${money(Number(inputs[0]) * Number(inputs[1]) + Number(inputs[2]), $("create-currency").value.toUpperCase())} · 초기 매수 비용 0`
    : "보유 수량, 시작일 평가가격, 현금 Pool을 입력하면 시작 자산을 계산합니다.";
}
function renderAccount() {
  const exists = !!account;
  $("account-empty").hidden = exists;
  $("account-content").hidden = !exists;
  $("reload-account").disabled = !exists;
  $("delete-account").disabled = !exists || deletingAccount;
  if (!exists) {
    valuationGeneration++;
    return;
  }
  const state = account.state,
    cycle = account.cycles.at(-1);
  $("account-name").textContent = account.name;
  $("account-caption").textContent =
    `${account.symbol} · ${account.currency} · ${modeName(cycle.settings.mode)} · G=${cycle.settings.g}`;
  $("cycle-badge").textContent = `${state.cycle_start} → ${state.cycle_end}`;
  $("metric-qty").textContent = num(state.qty, 0);
  $("metric-pool").textContent = num(state.pool);
  $("metric-pool-note").textContent = `${account.currency} · 실제 장부 현금`;
  $("metric-v").textContent = num(state.v);
  $("metric-band").textContent = state.waiting
    ? "직전 종가 확인 대기"
    : `하단 ${num(state.lower)} / 상단 ${num(state.upper)}`;
  $("metric-budget").textContent = num(state.remaining_budget);
  $("metric-budget-note").textContent =
    `최초 한도 ${num(state.budget)} ${account.currency}`;
  showMessage(
    "waiting-notice",
    state.waiting
      ? "직전 종가가 입력되지 않아 V·주문 계산을 기다리고 있습니다. 아래 “회차 진행 · 명시적 수정”에서 해당 회차의 직전 실제 확정 종가를 입력한 뒤 “선택 회차 재계산”을 눌러 주세요."
      : "",
  );
  showMessage(
    "pending-flows",
    account.pending_flows.length
      ? "다음 회차 적용 예정\n" +
          account.pending_flows
            .map(
              (e) =>
                `${e.date} 기록 → ${e.effective_date} 적용: ${money(e.amount)}`,
            )
            .join("\n")
      : "",
  );
  const pendingAmount = account.pending_flows.reduce(
    (sum, event) => sum + event.amount,
    0,
  );
  showMessage(
    "funding-summary",
    `시작 자산 기준: ${money(account.seed.capital)} · 반영된 순증액: ${money(state.net_contributions - account.seed.capital)}\n누적 순투입금: ${money(state.net_contributions)} · 미반영 순입출금: ${money(pendingAmount)}\n미반영 자금은 현재 Pool과 순투입금에 포함되지 않습니다. 다음 회차 확정 시 반영합니다.`,
  );
  renderOrders();
  const labels = {
    initial_v: "초기 V",
    previous_v: "직전 V",
    previous_pool: "직전 종료 Pool",
    previous_equity: "직전 주식 평가액",
    pool_growth: "Pool / G",
    skill_adjustment: "실력 보정값",
    rounded_v_before_flow: "입출금 전 V",
    flow: "이번 회차 입출금",
  };
  keyValues(
    "cycle-components",
    Object.entries(state.components)
      .filter(([key]) => labels[key])
      .map(([key, value]) => [labels[key], money(value)]),
  );
  const existing = account.seed.initialization_mode === "existing_holdings";
  keyValues("seed-values", [
    ["시작일", account.seed.start],
    [
      "시작 방식",
      existing ? "기존 주식과 현금으로 시작" : "새 투자금으로 초기 매수",
    ],
    [
      existing ? "시작일 평가 자산" : "초기 투자금",
      money(account.seed.capital),
    ],
    [
      existing ? "시작 주식 비중" : "초기 매수 비중",
      pct(account.seed.allocation),
    ],
    [existing ? "시작일 평가가격" : "초기 체결가", money(account.seed.price)],
    ["초기 수량", `${account.seed.qty}주`],
    ["초기 Pool", money(account.seed.pool)],
    ["초기 V", money(account.seed.v)],
    ["초기 매수 비용", money(account.seed.initial_fee)],
    ...(account.seed.holding_cost_basis == null
      ? []
      : [
          ["기존 주식 취득원가 · 참고", money(account.seed.holding_cost_basis)],
        ]),
  ]);
  $("revision-label").textContent = `저장 버전 ${account.revision}`;
  renderLedger();
  setSettings("account-settings", "account", account.settings);
  $("next-start").value = addDays(cycle.start, cycle.settings.cycle_days);
  $("event-date").value = state.cycle_start;
  $("cycle-select").innerHTML = account.cycles
    .map(
      (c, i) =>
        `<option value="${esc(c.id)}" ${i === account.cycles.length - 1 ? "selected" : ""}>${i + 1}회차 · ${esc(c.start)} · ${modeName(c.settings.mode)}</option>`,
    )
    .join("");
  renderCycleForm();
  updateValuation();
}
function renderOrders() {
  for (const side of ["buy", "sell"]) {
    const rows = account.orders[side] || [];
    $(side + "-orders").innerHTML = rows.length
      ? rows
          .map(
            (row) =>
              `<tr><td>${row.step}</td><td>${num(row.price)}</td><td>${num(side === "buy" ? row.cumulative_cost : row.cumulative_proceeds)}</td></tr>`,
          )
          .join("")
      : '<tr><td colspan="3">현재 주문 없음</td></tr>';
  }
  const clipped =
    Math.max(account.orders.buy.length, account.orders.sell.length) >= 40;
  $("order-note").textContent =
    `${account.currency} 기준 · 각 주문은 1주 · ${clipped ? "각 방향 최대 40단계 표시" : "회차 잔여 한도 내 주문만 표시"} · 한 주 미만의 밴드 차이는 정수 수량으로 남을 수 있습니다.`;
}
async function updateValuation() {
  const generation = ++valuationGeneration;
  const current = account;
  if (!current) return;
  const isCurrent = () =>
    generation === valuationGeneration &&
    account?.id === current.id &&
    account?.revision === current.revision;
  const coverage = prices.find((p) => p.symbol === current.symbol);
  $("latest-valuation").textContent = coverage
    ? `가격 DB 최근 종가일: ${coverage.last_date} (${coverage.currency || "통화 미확인"})`
    : "가격 DB에 이 종목의 가격이 없습니다. 가격 데이터에서 가져올 수 있습니다.";
  if (!coverage?.last_date) return;
  try {
    const rows = await api(
      `/api/prices/${encodeURIComponent(current.symbol)}?start=${coverage.last_date}&end=${coverage.last_date}`,
    );
    if (!isCurrent()) return;
    const row = rows.at(-1);
    if (!row) return;
    if (row.currency !== current.currency) {
      $("latest-valuation").textContent =
        "계좌 통화와 가격 DB 통화가 달라 평가액 표시를 생략했습니다.";
      return;
    }
    $("latest-valuation").textContent =
      `${row.date} 실제 종가 ${num(row.close)} ${row.currency} · 장부 수량 기준 총자산 ${money(current.state.qty * row.close + current.state.pool, current.currency)}. 과거 분할이 장부에 반영되었는지 확인하세요.`;
  } catch (e) {
    if (!isCurrent()) return;
    $("latest-valuation").textContent = `가격 평가액 조회: ${e.message}`;
  }
}
function renderLedger() {
  $("ledger-body").innerHTML = account.events.length
    ? account.events
        .map(
          (e) =>
            `<tr><td>${esc(e.date)}</td><td>${esc(kindName(e.kind))}</td><td>${["buy", "sell"].includes(e.kind) ? `${e.qty}주` : e.kind === "split" ? "—" : money(e.amount)}</td><td>${["buy", "sell"].includes(e.kind) ? num(e.price) : e.kind === "split" ? num(e.ratio) : "—"}</td><td>${esc(e.effective_date || e.date)}</td><td><div class="row-actions"><button type="button" data-edit="${esc(e.id)}">수정</button><button type="button" data-delete="${esc(e.id)}">삭제</button></div></td></tr>`,
        )
        .join("")
    : '<tr><td colspan="6">아직 기록이 없습니다.</td></tr>';
}
function renderEventFields() {
  const kind = $("event-kind").value;
  document.querySelectorAll("[data-event]").forEach((label) => {
    const show =
      label.dataset.event ===
      ("buy" === kind || "sell" === kind
        ? "trade"
        : kind === "split"
          ? "split"
          : "amount");
    label.hidden = !show;
    const input = label.querySelector("input");
    input.disabled = !show;
    input.required = show && input.name !== "fee";
  });
}
function cancelEvent() {
  eventId = null;
  $("event-submit").textContent = "장부에 기록";
  $("event-cancel").hidden = true;
  $("event-form").reset();
  if (account) $("event-date").value = account.state.cycle_start;
  showMessage("event-error", "");
  renderEventFields();
}
function renderCycleForm() {
  if (!account) return;
  const cycle = account.cycles.find((c) => c.id === $("cycle-select").value);
  $("cycle-close").value = cycle.previous_close ?? "";
  $("cycle-close").disabled = cycle.id === account.cycles[0].id;
  setSettings("cycle-settings", "cycle", cycle.settings);
}
function readNamed(form) {
  return Object.fromEntries(new FormData(form).entries());
}
async function loadPrices() {
  prices = await api("/api/prices");
  renderPrices();
  if (account) updateValuation();
}
function renderPrices() {
  $("coverage-body").innerHTML = prices.length
    ? prices
        .map(
          (p) =>
            `<tr><td><strong>${esc(p.symbol)}</strong><small>${esc(p.currency || "통화 미확인")}</small></td><td>${esc(p.first_date || "—")}<br>${esc(p.last_date || "—")}</td><td>${num(p.row_count || 0, 0)}</td><td>${esc(p.provider || "미확보")}<small>${esc(p.basis_warning || "같은 수정종가 snapshot")} · #${esc(p.snapshot_id || "—")}</small></td><td>${esc(p.fetched_at || "—")}</td><td class="${p.last_error ? "negative" : "positive"}">${p.last_error ? "실패 · 기존 가격 유지" : "정상"}<small>${esc(p.last_error || p.last_attempt_at || "원본 가져오기")}</small></td></tr>`,
        )
        .join("")
    : '<tr><td colspan="6">저장된 가격이 없습니다. 위에서 종목 가격을 가져오세요.</td></tr>';
}
async function syncOne(symbol, years) {
  showMessage(
    "sync-status",
    `${symbol} 전체 기간 가격을 가져오는 중입니다. 공급자 응답에 따라 잠시 걸릴 수 있습니다.`,
  );
  const result = await api("/api/prices/sync", "POST", { symbol, years });
  showMessage(
    "sync-status",
    `${result.symbol}: ${num(result.rows, 0)}행 확보 · ${result.first_date} ~ ${result.last_date} · ${result.currency}\n조회 ${years}년 / 수정종가 기준 일치를 위해 저장 ${result.snapshot_years}년`,
  );
  await loadPrices();
  return result;
}
function backtestPayload() {
  const form = $("backtest-form");
  const data = readNamed(form);
  const modes = [];
  if ($("bt-basic").checked) modes.push("basic");
  if ($("bt-skilled").checked) modes.push("skilled");
  if (!modes.length) throw new Error("비교할 VR 방식을 하나 이상 선택하세요.");
  const symbols = data.symbols
    .split(/[,\s]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
  const flows = data.flows.trim()
    ? data.flows
        .trim()
        .split(/\n/)
        .map((line, i) => {
          const parts = line.trim().split(/[,\s]+/);
          if (
            parts.length !== 2 ||
            !/^\d{4}-\d{2}-\d{2}$/.test(parts[0]) ||
            !Number.isFinite(Number(parts[1]))
          )
            throw new Error(
              `${i + 1}번째 입출금: YYYY-MM-DD, 금액 형식으로 입력하세요.`,
            );
          return { date: parts[0], amount: Number(parts[1]) };
        })
    : [];
  return {
    symbols,
    modes,
    years: Number(data.years),
    ...(data.start ? { start: data.start } : {}),
    ...(data.end ? { end: data.end } : {}),
    ...(data.initialization_mode === "existing_holdings"
      ? {
          initial_holdings: {
            qty: Number(data.initial_qty),
            pool: Number(data.initial_pool),
            ...(data.initial_v ? { v: Number(data.initial_v) } : {}),
          },
        }
      : {
          capital: Number(data.capital),
          allocation: Number(data.allocation) / 100,
        }),
    settings: readSettings("bt-settings"),
    flows,
  };
}
function restoreBacktest() {
  const data = recall("backtest", null);
  setSettings("bt-settings", "bt", data?.settings || defaults, false);
  if (!data) return;
  for (const [id, value] of Object.entries({
    "bt-symbols": data.symbols.join(","),
    "bt-years": data.years,
    "bt-start": data.start || "",
    "bt-end": data.end || "",
    "bt-capital": data.capital ?? 15000,
    "bt-allocation": (data.allocation ?? 0.5) * 100,
    "bt-initialization-mode": data.initial_holdings
      ? "existing_holdings"
      : "new_purchase",
    "bt-qty": data.initial_holdings?.qty ?? "",
    "bt-pool": data.initial_holdings?.pool ?? "",
    "bt-v": data.initial_holdings?.v ?? "",
    "bt-flows": data.flows.map((f) => `${f.date}, ${f.amount}`).join("\n"),
  }))
    $(id).value = value;
  $("bt-basic").checked = data.modes.includes("basic");
  $("bt-skilled").checked = data.modes.includes("skilled");
}
const colors = [
  "#267554",
  "#b18a36",
  "#4c73b3",
  "#9b597d",
  "#52a1a1",
  "#a76844",
  "#6b7c3c",
  "#805baa",
];
function renderChart() {
  const currencies = [...new Set(results.map((r) => r.metadata.currency))];
  const comparable = currencies.length === 1 && !!currencies[0];
  $("chart-metric").querySelector('option[value="equity"]').disabled =
    !comparable;
  if (!comparable) $("chart-metric").value = "twr";
  const metric = $("chart-metric").value;
  const equity = metric === "equity";
  const description = equity
    ? `날짜별 총자산 ${currencies[0]}`
    : "날짜별 입출금 제외 수익률 TWR";
  $("performance-chart").setAttribute("aria-label", description);
  $("chart-note").textContent = equity
    ? `금액 단위: ${currencies[0]}. 총자산에는 추가 입출금이 포함됩니다. 운용 수익률은 TWR로 비교하세요.`
    : "TWR는 입출금 효과를 제거한 성과입니다." +
      (!comparable
        ? " 통화가 다르거나 확인되지 않아 총자산 비교를 사용할 수 없습니다."
        : "");
  const w = Math.max(280, $("performance-chart").clientWidth),
    h = 310,
    left = equity ? 75 : 58,
    right = 20,
    top = 20,
    bottom = 40;
  const dates = results.flatMap((r) => r.daily.map((d) => Date.parse(d.date)));
  const lowDate = Math.min(...dates),
    highDate = Math.max(...dates);
  let low = Math.min(
      0,
      ...results.flatMap((r) => r.daily.map((d) => d[metric])),
    ),
    high = Math.max(
      0,
      ...results.flatMap((r) => r.daily.map((d) => d[metric])),
    );
  const margin = Math.max(equity ? 1 : 0.01, (high - low) * 0.12);
  low -= margin;
  high += margin;
  const x = (d) =>
    left +
    ((Date.parse(d) - lowDate) / (highDate - lowDate || 1)) *
      (w - left - right);
  const y = (value) =>
    top + ((high - value) / (high - low)) * (h - top - bottom);
  let svg = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(description)}"><title>${esc(description)}</title>`;
  for (let i = 0; i <= 4; i++) {
    const value = low + ((high - low) * i) / 4,
      yy = y(value);
    svg += `<line x1="${left}" y1="${yy}" x2="${w - right}" y2="${yy}" stroke="#e7ece3"/><text x="${left - 10}" y="${yy + 4}" text-anchor="end" font-size="11" fill="#849184">${esc(equity ? num(value, 0) : pct(value))}</text>`;
  }
  for (const [index, result] of results.entries()) {
    const samples = result.daily.filter(
      (_, i) =>
        i % Math.max(1, Math.floor(result.daily.length / 1000)) === 0 ||
        i === result.daily.length - 1,
    );
    svg += `<path d="${samples.map((d, i) => `${i ? "L" : "M"}${x(d.date).toFixed(2)},${y(d[metric]).toFixed(2)}`).join(" ")}" fill="none" stroke="${colors[index % colors.length]}" stroke-width="2.4"/>`;
  }
  svg += `<text x="${left}" y="${h - 10}" fill="#849184" font-size="11">${new Date(lowDate).toISOString().slice(0, 10)}</text><text x="${w - right}" y="${h - 10}" fill="#849184" font-size="11" text-anchor="end">${new Date(highDate).toISOString().slice(0, 10)}</text></svg>`;
  $("performance-chart").innerHTML = svg;
  $("chart-legend").innerHTML = results
    .map(
      (r, i) =>
        `<span><i class="legend-dot" style="background:${colors[i % colors.length]}"></i>${esc(r.symbol)} · ${modeName(r.mode)}</span>`,
    )
    .join("");
}
new ResizeObserver(() => {
  if (results.length && $("performance-chart").clientWidth > 0) renderChart();
}).observe($("performance-chart"));
function renderResults() {
  $("backtest-empty").hidden = true;
  $("backtest-results").hidden = false;
  $("results-summary").querySelector("tbody").innerHTML = results
    .map((r) => {
      const s = r.summary,
        c = r.metadata.currency || "통화 미확인";
      return `<tr><td><strong>${esc(r.symbol)}</strong><small>${modeName(r.mode)}</small></td><td class="${s.twr >= 0 ? "positive" : "negative"}">${pct(s.twr)}</td><td class="negative">${pct(s.mdd)}</td><td>${money(s.equity, c)}</td><td>${money(s.profit, c)}</td><td>${money(s.net_contributions, c)}</td><td>${num(s.trade_count, 0)}</td></tr>`;
    })
    .join("");
  $("result-select").innerHTML = results
    .map(
      (r, i) =>
        `<option value="${i}">${esc(r.symbol)} · ${modeName(r.mode)}</option>`,
    )
    .join("");
  renderChart();
  renderDaily();
}
function renderDaily() {
  const result = results[Number($("result-select").value)];
  if (!result) return;
  const meta = result.metadata;
  const currency = meta.currency || "통화 미확인";
  showMessage(
    "result-metadata",
    `요청 ${meta.requested_start} ~ ${meta.requested_end}\n실제 사용 ${meta.actual_start} ~ ${meta.actual_end} · ${currency} · snapshot ${meta.snapshots.join(", ") || "미지정"}\n` +
      (meta.warnings.length
        ? meta.warnings.join("\n")
        : "확보된 실제 가격 구간을 사용했습니다.") +
      `\n적용 G=${result.settings.g}, 밴드 ±${pct(result.settings.band)}, 비용 ${pct(result.settings.fee)}, 회차 ${result.settings.cycle_days}일, Pool 한도 ${pct(result.settings.pool_usage)}`,
  );
  const rows = result.daily.slice(-200);
  $("daily-body").innerHTML = rows
    .map(
      (d) =>
        `<tr><td>${esc(d.date)}</td><td>${num(d.price, 4)}</td><td>${num(d.qty, 0)}</td><td>${num(d.pool)}</td><td>${num(d.v)}</td><td>${num(d.equity)}</td><td>${pct(d.twr)}</td><td>${d.trade ? `${kindName(d.trade.side)} ${d.trade.qty}주` : "—"}</td><td>${d.flow ? num(d.flow) : "—"}</td></tr>`,
    )
    .join("");
  $("daily-note").textContent =
    `전체 ${num(result.daily.length, 0)}거래일 중 최근 ${rows.length}행 표시 · 전체 데이터는 CSV로 내려받을 수 있습니다. 금액 단위: ${currency}`;
  $("assumptions").innerHTML = result.assumptions
    .map((text) => `<li>${esc(text)}</li>`)
    .join("");
}
function downloadCsv() {
  const result = results[Number($("result-select").value)];
  if (!result) return;
  const keys = [
    "date",
    "price",
    "qty",
    "pool",
    "v",
    "equity",
    "net_contributions",
    "profit",
    "twr",
    "drawdown",
    "flow",
    "remaining_budget",
    "snapshot_id",
  ];
  const content =
    "\uFEFF" +
    keys.join(",") +
    "\r\n" +
    result.daily
      .map((d) =>
        keys
          .map((k) => `"${String(d[k] ?? "").replace(/"/g, '""')}"`)
          .join(","),
      )
      .join("\r\n");
  const url = URL.createObjectURL(
    new Blob([content], { type: "text/csv;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = `${result.symbol}_${result.mode}_${result.metadata.actual_start}_${result.metadata.actual_end}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
document.querySelectorAll(".nav-button").forEach((b) =>
  b.addEventListener("click", () => {
    switchTab(b.dataset.tab);
    window.scrollTo(0, 0);
  }),
);
function openHashTab() {
  const target = location.hash.slice(1);
  switchTab(
    target.startsWith("guide-")
      ? "help"
      : target || recall("tab", "operations"),
  );
  if (target.startsWith("guide-")) $(target)?.scrollIntoView();
}
window.addEventListener("hashchange", openHashTab);
$("default-fee-form").addEventListener("submit", (event) => {
  event.preventDefault();
  defaults.fee = Number($("default-fee").value) / 100;
  remember("defaultFee", defaults.fee);
  $("create-fee").value = defaults.fee * 100;
  $("bt-fee").value = defaults.fee * 100;
  const previous = recall("backtest", null);
  if (previous)
    remember("backtest", {
      ...previous,
      settings: { ...previous.settings, fee: defaults.fee },
    });
  showMessage(
    "default-fee-status",
    "이 브라우저의 새 계좌·백테스트 비용률을 저장했습니다. 기존 계좌와 확정 회차는 변경하지 않았습니다.",
  );
});
$("open-create").addEventListener("click", openCreate);
$("empty-create").addEventListener("click", openCreate);
$("close-create").addEventListener(
  "click",
  () => ($("create-panel").hidden = true),
);
$("account-select").addEventListener("change", () => {
  accountSelection++;
  account = portfolios.find((p) => p.id === $("account-select").value) || null;
  remember("account", account?.id || null);
  cancelEvent();
  renderAccount();
});
$("reload-account").addEventListener("click", async () => {
  if (!account) return;
  try {
    if (await requestAccount(`/api/portfolios/${account.id}`)) {
      cancelEvent();
      toast("최신 장부를 다시 불러왔습니다.");
    }
  } catch (e) {
    showMessage("global-error", e.message);
  }
});
function syncDeleteConfirmation() {
  $("confirm-delete-account").disabled =
    deletingAccount || !deleteTarget || $("delete-account-name").value !== deleteTarget.name;
}
$("delete-account").addEventListener("click", () => {
  if (!account || deletingAccount) return;
  deleteTarget = { id: account.id, revision: account.revision, name: account.name };
  $("delete-account-target").textContent =
    `${account.name} · ${account.symbol} (${account.currency}) · 기록 ${account.events.length}건 · 회차 ${account.cycles.length}개`;
  $("delete-account-name").value = "";
  showMessage("delete-account-error", "");
  syncDeleteConfirmation();
  $("delete-account-dialog").showModal();
  $("delete-account-name").focus();
});
$("delete-account-name").addEventListener("input", syncDeleteConfirmation);
$("cancel-delete-account").addEventListener("click", () => $("delete-account-dialog").close());
$("delete-account-dialog").addEventListener("cancel", (event) => {
  if (deletingAccount) event.preventDefault();
});
$("delete-account-dialog").addEventListener("close", () => {
  deleteTarget = null;
  syncDeleteConfirmation();
});
$("delete-account-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (deletingAccount || !deleteTarget || $("delete-account-name").value !== deleteTarget.name) return;
  const target = deleteTarget;
  deletingAccount = true;
  $("delete-account-name").disabled = true;
  $("cancel-delete-account").disabled = true;
  syncDeleteConfirmation();
  showMessage("delete-account-error", "");
  try {
    await api(`/api/portfolios/${target.id}`, "DELETE", {
      revision: target.revision,
      confirmation_name: target.name,
    });
    deletedAccountIds.add(target.id);
    accountSelection++;
    portfolios = portfolios.filter((p) => p.id !== target.id);
    if (account?.id === target.id) {
      account = portfolios[0] || null;
      remember("account", account?.id || null);
      cancelEvent();
    }
    renderAccounts();
    renderAccount();
    $("delete-account-dialog").close();
    toast(`‘${target.name}’ 계좌와 기록을 삭제했습니다.`);
  } catch (error) {
    showMessage("delete-account-error", error.message +
      (error.status === 409 ? " 삭제하지 않았습니다. 취소 후 ‘새로 불러오기’로 최신 내용을 확인하세요." : ""));
  } finally {
    deletingAccount = false;
    $("delete-account-name").disabled = false;
    $("cancel-delete-account").disabled = false;
    $("delete-account").disabled = !account;
    syncDeleteConfirmation();
  }
});
$("create-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(event.currentTarget, "create-error", async () => {
    const form = readNamed($("create-form"));
    const data = {
      name: form.name,
      symbol: form.symbol.trim().toUpperCase(),
      currency: form.currency.trim().toUpperCase(),
      start: form.start,
      initialization_mode: form.initialization_mode,
      ...(form.initialization_mode === "new_purchase"
        ? {
            capital: Number(form.capital),
            allocation: Number(form.allocation) / 100,
          }
        : {}),
      price: Number(form.price),
      settings: readSettings("create-settings"),
    };
    for (const key of [
      "qty_override",
      "pool_override",
      "v_override",
      "holding_cost_basis",
    ])
      if (form[key] != null && form[key] !== "") data[key] = Number(form[key]);
    const value = await api("/api/portfolios", "POST", data);
    applyAccount(value, true);
    $("create-panel").hidden = true;
    cancelEvent();
    toast("운용 계좌가 저장되었습니다.");
  });
});
$("event-kind").addEventListener("change", renderEventFields);
$("event-cancel").addEventListener("click", cancelEvent);
$("event-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(event.currentTarget, "event-error", async () => {
    if (!account) throw new Error("계좌를 먼저 선택하세요.");
    const form = readNamed($("event-form"));
    const data = {
      kind: form.kind,
      date: form.date,
      revision: account.revision,
    };
    for (const key of ["qty", "price", "fee", "amount", "ratio"])
      if (form[key] !== undefined && form[key] !== "")
        data[key] = Number(form[key]) / (key === "fee" ? 100 : 1);
    if (["buy", "sell"].includes(form.kind) && form.fee === "") data.fee = null;
    const suffix = eventId ? `/${eventId}` : "";
    const applied = await requestAccount(
      `/api/portfolios/${account.id}/events${suffix}`,
      eventId ? "PATCH" : "POST",
      data,
    );
    if (applied) cancelEvent();
    toast("장부가 저장되었습니다.");
  });
});
$("ledger-body").addEventListener("click", async (event) => {
  const edit = event.target.closest("[data-edit]");
  const remove = event.target.closest("[data-delete]");
  if (edit) {
    const row = account.events.find((item) => item.id === edit.dataset.edit);
    $("event-form").reset();
    eventId = row.id;
    for (const [key, value] of Object.entries(row)) {
      const input = $("event-form").elements.namedItem(key);
      if (input)
        input.value =
          key === "fee" && value != null ? value * 100 : (value ?? "");
    }
    renderEventFields();
    $("event-submit").textContent = "변경 저장";
    $("event-cancel").hidden = false;
    $("event-form").scrollIntoView({ behavior: "smooth", block: "center" });
  }
  if (remove) {
    remove.disabled = true;
    try {
      const applied = await requestAccount(
        `/api/portfolios/${account.id}/events/${remove.dataset.delete}`,
        "DELETE",
        { revision: account.revision },
      );
      if (applied && eventId === remove.dataset.delete) cancelEvent();
      toast("기록을 삭제하고 장부를 다시 계산했습니다.");
    } catch (error) {
      showMessage("event-error", error.message);
      remove.disabled = false;
    }
  }
});
$("settings-form").addEventListener("submit", (event) => {
  event.preventDefault();
  showMessage("settings-success", "");
  action(event.currentTarget, "settings-error", async () => {
    const applied = await requestAccount(
      `/api/portfolios/${account.id}/settings`,
      "PATCH",
      {
        settings: readSettings("account-settings"),
        revision: account.revision,
      },
    );
    if (applied)
      showMessage(
        "settings-success",
        "다음 회차 기본값을 저장했습니다. 현재 확정 회차는 유지됩니다.",
      );
  });
});
$("next-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(event.currentTarget, "next-error", async () => {
    const form = readNamed($("next-form"));
    const applied = await requestAccount(
      `/api/portfolios/${account.id}/cycles`,
      "POST",
      {
        start: form.start,
        previous_close: form.previous_close
          ? Number(form.previous_close)
          : null,
        revision: account.revision,
      },
    );
    if (applied) $("next-close").value = "";
    toast("다음 회차가 시작되었습니다.");
  });
});
$("cycle-select").addEventListener("change", renderCycleForm);
$("cycle-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(event.currentTarget, "cycle-error", async () => {
    const cycleId = $("cycle-select").value;
    const data = {
      settings: readSettings("cycle-settings"),
      revision: account.revision,
    };
    if (!$("cycle-close").disabled)
      data.previous_close = $("cycle-close").value
        ? Number($("cycle-close").value)
        : null;
    await requestAccount(
      `/api/portfolios/${account.id}/cycles/${cycleId}`,
      "PATCH",
      data,
    );
    toast("회차와 장부를 다시 계산하여 저장했습니다.");
  });
});
$("sync-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(event.currentTarget, "sync-error", async () => {
    try {
      await syncOne(
        $("sync-symbol").value.trim().toUpperCase(),
        Number($("sync-years").value),
      );
    } catch (e) {
      showMessage(
        "sync-status",
        "갱신에 실패했습니다. 기존 데이터는 유지됩니다.",
      );
      await loadPrices();
      throw e;
    }
  });
});
$("sync-all").addEventListener("click", () =>
  action($("sync-form"), "sync-error", async () => {
    const statuses = [];
    for (const symbol of ["TQQQ", "QLD", "SOXL", "UPRO"]) {
      try {
        const result = await syncOne(symbol, Number($("sync-years").value));
        statuses.push(`${symbol}: ${result.rows}행 확보 · ${result.last_date}`);
      } catch (e) {
        statuses.push(`${symbol}: ${e.message}`);
      }
    }
    showMessage("sync-status", statuses.join("\n"));
    await loadPrices();
  }),
);
$("refresh-prices").addEventListener("click", () =>
  loadPrices().catch((e) => showMessage("sync-error", e.message)),
);
$("backtest-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(event.currentTarget, "bt-error", async () => {
    const data = backtestPayload();
    remember("backtest", data);
    $("bt-submit").textContent = "계산 중…";
    try {
      const response = await api("/api/backtests", "POST", data);
      results = response.results;
      renderResults();
      toast(`${results.length}개 전략을 계산했습니다.`);
    } finally {
      $("bt-submit").textContent = "백테스트 실행";
    }
  });
});
$("result-select").addEventListener("change", renderDaily);
$("chart-metric").addEventListener("change", renderChart);
$("download-csv").addEventListener("click", downloadCsv);
for (const prefix of ["create", "bt"])
  $(`${prefix}-initialization-mode`).addEventListener("change", () =>
    renderInitialization(prefix),
  );
for (const id of [
  "create-qty",
  "create-price",
  "create-pool",
  "create-currency",
])
  $(id).addEventListener("input", renderOpeningEquity);
setSettings("create-settings", "create", defaults);
renderEventFields();
restoreBacktest();
renderInitialization("create");
renderInitialization("bt");
$("default-fee").value = defaults.fee * 100;
openHashTab();
(async () => {
  try {
    await api("/api/health");
    $("server-state").textContent = "로컬 서버 연결됨";
    await loadPrices();
    await loadAccounts();
  } catch (e) {
    $("server-state").textContent = "연결 확인 필요";
    showMessage("global-error", e.message);
  }
})();
