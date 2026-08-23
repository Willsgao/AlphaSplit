/* AlphaSplit frontend — 场景切换 + 人工确认 */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

const state = {
  scenario: "quant_fund",
  evolution: null,
  formula: null,
  negotiate: null,
  charts: {},
  backtestMeta: null,
  backtestResult: null,
  agentPlan: null,
  dualPoolAmount: 10_000_000,
  dualPoolBaseline: null,
  dualPoolConfirmed: false,
  backtestTimer: null,
  backtestFocusTimer: null,
  backtestStreamPopulated: false,
};

/** 6:4 双轨分配 */
const OLD_POOL_RATIO = 0.6;
const NEW_POOL_RATIO = 0.4;
const DUAL_POOL_ROLES = [
  "行业分析师",
  "个股分析师",
  "策略分析师",
  "量化分析师",
  "风控分析师",
];
const DEFAULT_BASELINE_WEIGHTS = Object.fromEntries(
  DUAL_POOL_ROLES.map((r) => [r, 0.2])
);

/** 图表配色（随 CSS 主题变量同步） */
const CHART = {
  ink: "#1a2332",
  muted: "#5c6b7f",
  grid: "rgba(26, 35, 50, 0.08)",
  fill: "rgba(37, 99, 235, 0.1)",
};

function refreshChartTheme() {
  const s = getComputedStyle(document.documentElement);
  const g = (v) => s.getPropertyValue(v).trim();
  CHART.ink = g("--chart-ink") || CHART.ink;
  CHART.muted = g("--chart-muted") || CHART.muted;
  CHART.grid = g("--chart-grid") || CHART.grid;
  CHART.fill = g("--chart-fill") || CHART.fill;
}

function applyThemeToCharts() {
  refreshChartTheme();
  Object.values(state.charts).forEach((chart) => {
    if (!chart?.options) return;
    const c = CHART;
    if (chart.options.plugins?.legend?.labels) chart.options.plugins.legend.labels.color = c.muted;
    const title = chart.options.plugins?.title;
    if (title) title.color = c.ink;
    ["x", "y"].forEach((ax) => {
      const scale = chart.options.scales?.[ax];
      if (!scale) return;
      if (scale.ticks) scale.ticks.color = c.muted;
      if (scale.title) scale.title.color = c.muted;
      if (scale.grid) scale.grid.color = c.grid;
    });
    chart.update("none");
  });
}

const THEMES = ["warm", "roadshow", "dark"];
const THEME_LABELS = { roadshow: "路演白", warm: "暖沙色", dark: "深色" };

function currentTheme() {
  return document.documentElement.getAttribute("data-theme") || "warm";
}

function setTheme(theme) {
  const next = THEMES.includes(theme) ? theme : "warm";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("alphasplit-theme", next);
  applyThemeToCharts();
  updateThemeToggleLabel();
}

function toggleTheme() {
  const idx = THEMES.indexOf(currentTheme());
  setTheme(THEMES[(idx + 1) % THEMES.length]);
}

function updateThemeToggleLabel() {
  const btn = $("#btnThemeToggle");
  if (!btn) return;
  const cur = currentTheme();
  const next = THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length];
  btn.textContent = `→ ${THEME_LABELS[next]}`;
  btn.title = `当前：${THEME_LABELS[cur]}，点击切换为${THEME_LABELS[next]}`;
}

function initTheme() {
  const saved = localStorage.getItem("alphasplit-theme");
  if (saved && THEMES.includes(saved)) {
    document.documentElement.setAttribute("data-theme", saved);
  }
  refreshChartTheme();
  updateThemeToggleLabel();
}

/** 演示强调：边框/阴影脉冲，不做 Z 轴叠压 */
function pulseZone3D(zone) {
  if (!zone || !document.body.classList.contains("fx-3d")) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  zone.classList.remove("zone-3d-pop");
  void zone.offsetWidth;
  zone.classList.add("zone-3d-pop");
  setTimeout(() => zone.classList.remove("zone-3d-pop"), 800);
}

function pulseNarrative3D() {
  const el = $("#backtestNarrative");
  if (!el || !document.body.classList.contains("fx-3d")) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  el.classList.remove("stage-3d-pulse");
  void el.offsetWidth;
  el.classList.add("stage-3d-pulse");
  setTimeout(() => el.classList.remove("stage-3d-pulse"), 650);
}

function initStage3D() {
  /* 平面高亮模式 */
}

function updateHeroKpis(data) {
  const strip = $("#heroKpiStrip");
  if (!strip || !data?.results) return;
  strip.classList.remove("kpi-strip--empty");
  const ov = data.results.overview || {};
  const breakdown = [...(data.results.role_breakdown || [])].sort(
    (a, b) => (b.weight || 0) - (a.weight || 0)
  );
  const excess = (ov.excess_return || 0) * 100;
  const excessEl = $("#kpiExcess");
  if (excessEl) {
    excessEl.textContent = `${excess >= 0 ? "+" : ""}${excess.toFixed(2)}%`;
    excessEl.classList.toggle("positive", excess > 0);
    excessEl.classList.toggle("negative", excess < 0);
  }
  const excessSub = $("#kpiExcessSub");
  if (excessSub) excessSub.textContent = ov.excess_return_desc || "相对沪深300";
  const sharpeEl = $("#kpiSharpe");
  if (sharpeEl) sharpeEl.textContent = (ov.sharpe_ratio ?? 0).toFixed(2);
  const sharpeSub = $("#kpiSharpeSub");
  if (sharpeSub) sharpeSub.textContent = ov.sharpe_ratio_desc || "年化夏普";
  const dd = Math.abs(ov.max_drawdown || 0) * 100;
  const ddEl = $("#kpiDrawdown");
  if (ddEl) ddEl.textContent = `-${dd.toFixed(2)}%`;
  const ddSub = $("#kpiDrawdownSub");
  if (ddSub) ddSub.textContent = ov.max_drawdown_desc || "最大回撤";
  const top = breakdown[0];
  const roleEl = $("#kpiTopRole");
  const roleSub = $("#kpiTopRoleSub");
  if (top && roleEl) {
    roleEl.textContent = (top.role || "").replace("分析师", "");
    if (roleSub) roleSub.textContent = `夏普利权重 ${((top.weight || 0) * 100).toFixed(1)}%`;
  }
}

function chartPremiumOptions(titleText, yCallback) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      title: {
        display: !!titleText,
        text: titleText || "",
        color: CHART.ink,
        font: { size: 13, weight: "600", family: "'Noto Sans SC', sans-serif" },
        padding: { bottom: 12 },
      },
    },
    scales: {
      x: {
        ticks: { color: CHART.muted, font: { size: 11 } },
        grid: { display: false },
        border: { display: false },
      },
      y: {
        ticks: {
          color: CHART.muted,
          font: { size: 11 },
          callback: yCallback,
        },
        grid: { color: CHART.grid, drawBorder: false },
        border: { display: false },
      },
    },
  };
}

const SPEAKER_CLASS = {
  李量化: "li",
  张经理: "zhang",
  陈经理: "chen",
  王模型: "li",
  赵经理: "zhang",
  孙经理: "chen",
  周总监: "arbiter",
};

function money(n) {
  return "¥" + Number(n).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

function pct(n) {
  return (Number(n) * 100).toFixed(1) + "%";
}

function currentScenario() {
  return $("#scenarioSelect")?.value || state.scenario;
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || res.statusText);
  }
  return res.json();
}

const APPENDIX_TABS = new Set([
  "attribution",
  "sensitivity",
  "compare",
  "evolution",
  "formula",
]);

$$(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    switchToTab(btn.dataset.tab);
  });
});

function switchToTab(tabId, opts = {}) {
  if (APPENDIX_TABS.has(tabId) || opts.openAppendix) {
    const appendix = $("#appendixTabs");
    if (appendix) appendix.open = true;
  }
  $$(".tab").forEach((b) => b.classList.remove("active"));
  $$(".panel").forEach((p) => p.classList.remove("active"));
  const tabBtn = $(`.tab[data-tab="${tabId}"]`);
  if (tabBtn) tabBtn.classList.add("active");
  const panel = $(`#panel-${tabId}`);
  if (panel) panel.classList.add("active");
  highlightDemoFlow(tabId);
  if (tabId === "backtest") updateBacktestNarrative("idle");
  if (tabId === "negotiate") renderDualPoolPanel();
}

$$(".demo-flow-step").forEach((btn) => {
  btn.addEventListener("click", () => {
    switchToTab(btn.dataset.gotoTab, {
      openAppendix: btn.dataset.openAppendix === "1",
    });
  });
});

$$(".journey-step").forEach((btn) => {
  btn.addEventListener("click", () => {
    switchToTab(btn.dataset.gotoTab, {
      openAppendix: btn.dataset.openAppendix === "1",
    });
  });
});

function highlightDemoFlow(tabId) {
  const flowMap = { backtest: "1", negotiate: "2", attribution: "3" };
  const step = flowMap[tabId];
  const cur = step ? parseInt(step, 10) : 0;
  $$(".demo-flow-step").forEach((el) => {
    el.classList.toggle("current", step ? el.dataset.flow === step : false);
  });
  $$(".journey-step").forEach((el) => {
    el.classList.toggle("active", step ? el.dataset.flow === step : false);
  });
  $$(".journey-connector").forEach((el) => {
    const after = parseInt(el.dataset.after, 10);
    el.classList.toggle("done", cur > after);
  });
}

function setBusy(btn, busy) {
  if (!btn) return;
  btn.disabled = !!busy;
}

async function checkHealth() {
  const dot = $("#healthDot");
  try {
    const h = await api("/api/health");
    const badge = $("#healthBadge");
    const bt = h.backtest_engine?.available ? " · 回测引擎✓" : " · 回测引擎✗";
    if (badge) badge.textContent = `v${h.version} · ${h.mode}${bt}`;
    if (dot) {
      dot.classList.add("ok");
      dot.classList.remove("err");
      dot.title = `服务正常 · v${h.version}`;
    }
  } catch {
    const badge = $("#healthBadge");
    if (badge) {
      badge.textContent = "offline";
      badge.classList.remove("ok");
    }
    if (dot) {
      dot.classList.add("err");
      dot.classList.remove("ok");
      dot.title = "服务离线";
    }
  }
}

async function loadScenarioList() {
  const data = await api("/api/scenarios");
  const sel = $("#scenarioSelect");
  sel.innerHTML = data.scenarios
    .map(
      (s) =>
        `<option value="${s.id}">${s.name}${s.domain ? " · " + s.domain : ""}</option>`
    )
    .join("");
  sel.value = state.scenario;
  sel.addEventListener("change", () => {
    state.scenario = sel.value;
    $("#chatStream").innerHTML = "";
    $("#settlement").classList.add("hidden");
    $("#humanConfirm").classList.add("hidden");
    runCalculate();
    loadTargetControls();
  });
}

function getDualPoolBaseline() {
  if (!state.dualPoolBaseline) {
    state.dualPoolBaseline = { ...DEFAULT_BASELINE_WEIGHTS };
  }
  return state.dualPoolBaseline;
}

function computeDualPoolRows(backtestData) {
  const breakdown = [...(backtestData?.results?.role_breakdown || [])].sort(
    (a, b) => (b.weight || 0) - (a.weight || 0)
  );
  const baseline = getDualPoolBaseline();
  const amount = Number(state.dualPoolAmount) || 10_000_000;
  const rows = breakdown.map((r) => {
    const oldW = baseline[r.role] ?? 0;
    const newW = r.weight ?? 0;
    const finalW = OLD_POOL_RATIO * oldW + NEW_POOL_RATIO * newW;
    return {
      role: r.role,
      oldW,
      newW,
      shapleyRaw: r.shapley_raw ?? 0,
      finalW,
      amount: finalW * amount,
    };
  });
  const baselineSum = DUAL_POOL_ROLES.reduce((s, role) => s + (baseline[role] || 0), 0);
  const finalSum = rows.reduce((s, r) => s + r.finalW, 0);
  return { rows, amount, baselineSum, finalSum };
}

function renderDualPoolPanel() {
  const box = $("#dualPoolPanel");
  if (!box) return;

  const data = state.backtestResult;
  if (!data?.results?.role_breakdown?.length) {
    box.innerHTML = `
      <h3>6:4 双轨分配方案</h3>
      <p class="note dual-pool-empty">
        请先在「HS300 岗位贡献」完成回测或路演演示，系统将自动带入夏普利新池建议，
        并在此合成 <strong>60% 现行 + 40% 证据</strong> 的最终分配表。
      </p>`;
    box.classList.remove("hidden");
    return;
  }

  const { rows, amount, baselineSum, finalSum } = computeDualPoolRows(data);
  const baselineWarning =
    Math.abs(baselineSum - 1) > 0.01
      ? `<p class="note dual-pool-warn">现行份额合计 ${(baselineSum * 100).toFixed(1)}%，建议调整为 100%。</p>`
      : "";

  const tableRows = rows
    .map((r) => {
      return `<tr>
        <td><span class="rank-dot" style="background:${roleColor(r.role)}"></span>${r.role}</td>
        <td>${(r.oldW * 100).toFixed(1)}%</td>
        <td>${(r.newW * 100).toFixed(1)}%</td>
        <td><strong>${(r.finalW * 100).toFixed(1)}%</strong></td>
        <td>${money(r.amount)}</td>
      </tr>`;
    })
    .join("");

  const baselineInputs = DUAL_POOL_ROLES.map((role) => {
    const val = ((getDualPoolBaseline()[role] || 0) * 100).toFixed(1);
    return `<label class="baseline-row">
      <span>${role}</span>
      <input type="number" min="0" max="100" step="0.5" data-baseline-role="${role}" value="${val}" />
      <span class="unit">%</span>
    </label>`;
  }).join("");

  const confirmNote = state.dualPoolConfirmed
    ? `<p class="note dual-pool-ok">已人工确认：本方案仅供考核讨论参考，非自动发薪。</p>`
    : "";

  box.innerHTML = `
    <h3>6:4 双轨分配方案</h3>
    <p class="dual-pool-lead">
      <strong>旧池 60%</strong> 沿用机构现行分配 ·
      <strong>新池 40%</strong> 按 HS300 夏普利证据建议 ·
      合成后<strong>人工确认</strong>方可应用。
    </p>
    <div class="dual-pool-controls">
      <label class="pool-amount">
        <span>可分配池</span>
        <input type="number" id="dualPoolAmountInput" min="100000" step="100000" value="${amount}" />
        <span class="unit">元</span>
      </label>
    </div>
    ${baselineWarning}
    <div class="table-wrap dual-pool-table-wrap">
      <table class="dual-pool-table">
        <thead>
          <tr>
            <th>角色</th>
            <th>旧池 60%<br><small>现行份额</small></th>
            <th>新池 40%<br><small>夏普利建议</small></th>
            <th>合成份额</th>
            <th>合成金额</th>
          </tr>
        </thead>
        <tbody>${tableRows}</tbody>
        <tfoot>
          <tr>
            <td colspan="3"><strong>合计</strong></td>
            <td><strong>${(finalSum * 100).toFixed(1)}%</strong></td>
            <td><strong>${money(amount)}</strong></td>
          </tr>
        </tfoot>
      </table>
    </div>
    <details class="dual-pool-baseline-edit">
      <summary>编辑现行分配（旧池 60% 输入）</summary>
      <p class="note">演示默认五角色均等 20%；机构落地时替换为真实制度比例。</p>
      <div class="baseline-form">${baselineInputs}</div>
      <button type="button" class="btn btn-ghost" id="btnBaselineReset">恢复默认均等</button>
    </details>
    <div class="dual-pool-actions">
      <button type="button" class="btn primary" id="btnDualPoolConfirm">确认落账（人工）</button>
      <button type="button" class="btn btn-ghost" id="btnDualPoolRecalc">重新计算</button>
    </div>
    ${confirmNote}
    <p class="note dual-pool-formula">
      公式：合成份额 = ${(OLD_POOL_RATIO * 100).toFixed(0)}% × 现行份额 + ${(NEW_POOL_RATIO * 100).toFixed(0)}% × 夏普利新池份额
      · 回测区间：${data.query_summary || "—"}
    </p>
  `;
  box.classList.remove("hidden");

  $("#dualPoolAmountInput")?.addEventListener("change", (e) => {
    state.dualPoolAmount = Number(e.target.value) || 10_000_000;
    state.dualPoolConfirmed = false;
    renderDualPoolPanel();
  });

  $("#btnBaselineReset")?.addEventListener("click", () => {
    state.dualPoolBaseline = { ...DEFAULT_BASELINE_WEIGHTS };
    state.dualPoolConfirmed = false;
    renderDualPoolPanel();
  });

  $("#btnDualPoolRecalc")?.addEventListener("click", () => {
    box.querySelectorAll("[data-baseline-role]").forEach((input) => {
      const role = input.dataset.baselineRole;
      getDualPoolBaseline()[role] = Number(input.value) / 100;
    });
    state.dualPoolConfirmed = false;
    renderDualPoolPanel();
  });

  $("#btnDualPoolConfirm")?.addEventListener("click", () => {
    box.querySelectorAll("[data-baseline-role]").forEach((input) => {
      const role = input.dataset.baselineRole;
      getDualPoolBaseline()[role] = Number(input.value) / 100;
    });
    state.dualPoolConfirmed = true;
    renderDualPoolPanel();
  });
}

function renderUtterance(u) {
  const cls = SPEAKER_CLASS[u.speaker] || "";
  const div = document.createElement("div");
  div.className = `bubble ${cls}`;
  div.innerHTML = `
    <div class="meta">
      <span>${u.speaker} · ${u.role || ""}</span>
      ${u.claim != null ? `<span class="claim">主张 ${pct(u.claim)}</span>` : ""}
    </div>
    <div class="text">${u.text}</div>
  `;
  return div;
}

function renderSettlement(data) {
  const settle = $("#settlement");
  const band = data.band ?? 0.05;
  const isFive = data.role_model === "five_roles";
  const items = Object.entries(data.settlement)
    .map(([name, s]) => {
      const status = s.in_band === false ? "越界" : "带宽内";
      const anchorLabel = isFive ? "6:4合成" : "锚点";
      return `
      <div class="settle-item">
        <div class="name">${name}</div>
        <div class="amt">${money(s.amount)}</div>
        <div class="sub">
          建议 ${pct(s.proposed_share ?? s.final_share)} · ${anchorLabel} ${pct(s.formula_share)}
          · 带宽 ${pct(s.band_low)}–${pct(s.band_high)} · ${status}
        </div>
      </div>`;
    })
    .join("");

  const dual = data.dual_track;
  const dualNote = dual
    ? `<p class="note" style="margin:0 0 0.75rem">双轨：旧池60%现行 + 新池40%夏普利 · ${data.backtest_summary || ""}</p>`
    : "";

  settle.innerHTML = `
    <h3>${isFive ? "五角色" : ""}系统建议案 · 可分配池 ${money(data.distributable)} · 带宽 ±${(band * 100).toFixed(0)}%</h3>
    ${dualNote}
    <div class="settle-grid">${items}</div>
    <p class="note" style="margin-top:0.75rem">
      状态：${data.status || "pending_human_confirm"} · 模式 ${data.mode || "-"} · 需人工确认后生效
    </p>
  `;
  settle.classList.remove("hidden");
}

function renderHumanConfirm(data) {
  const box = $("#humanConfirm");
  const rows = Object.entries(data.settlement)
    .map(([name, s]) => {
      const val = ((s.proposed_share ?? s.final_share) * 100).toFixed(1);
      return `
      <label class="share-row">
        <span>${name}
          <small>锚点 ${pct(s.formula_share)} · 建议带宽 ${pct(s.band_low)}–${pct(s.band_high)}</small>
        </span>
        <input type="number" min="5" max="80" step="0.5" data-name="${name}" value="${val}" />
        <span class="unit">%</span>
      </label>`;
    })
    .join("");

  box.innerHTML = `
    <h3>人工确认落账</h3>
    <p class="note">默认夹入带宽；勾选「允许越界」表示合规定责下的人工覆盖。</p>
    <div class="share-form">${rows}</div>
    <label class="override">
      <input type="checkbox" id="allowOutside" /> 允许越出带宽（需明示合规定责）
    </label>
    <div class="confirm-actions">
      <button id="btnAcceptProposed" class="btn">采纳建议案</button>
      <button id="btnConfirm" class="btn primary">确认落账</button>
    </div>
    <div id="confirmResult" class="confirm-result"></div>
  `;
  box.classList.remove("hidden");

  $("#btnAcceptProposed").onclick = () => {
    Object.entries(data.settlement).forEach(([name, s]) => {
      const input = box.querySelector(`input[data-name="${name}"]`);
      if (input) input.value = ((s.proposed_share ?? s.final_share) * 100).toFixed(1);
    });
  };

  $("#btnConfirm").onclick = () => submitConfirm(data);
}

async function submitConfirm(negoData) {
  const box = $("#humanConfirm");
  const shares = {};
  box.querySelectorAll("input[data-name]").forEach((input) => {
    shares[input.dataset.name] = Number(input.value) / 100;
  });
  const negotiated = {};
  const proposed = {};
  Object.entries(negoData.settlement).forEach(([name, s]) => {
    negotiated[name] = s.negotiated_share;
    proposed[name] = s.proposed_share ?? s.final_share;
  });

  const isFive = negoData.role_model === "five_roles";
  const payload = {
    scenario: isFive ? "hs300_five_roles" : currentScenario(),
    shares,
    negotiated,
    proposed,
    allow_outside_band: $("#allowOutside")?.checked || false,
  };
  if (isFive) {
    payload.role_model = "five_roles";
    payload.settlement_context = negoData;
  }

  const result = await api("/api/confirm", {
    method: "POST",
    body: JSON.stringify(payload),
  });

  const lines = Object.entries(result.settlement || result.rows || {})
    .map(
      ([name, s]) =>
        `<div class="settle-item">
          <div class="name">${name}</div>
          <div class="amt">${money(s.amount)}</div>
          <div class="sub">确认份额 ${pct(s.final_share)} ${s.in_band ? "· 带宽内" : "· 已覆盖越界"}</div>
        </div>`
    )
    .join("");

  $("#confirmResult").innerHTML = `
    <p class="ok-line">已确认：${result.status}${result.overridden ? "（越界覆盖）" : ""}</p>
    <div class="settle-grid">${lines}</div>
  `;
  state.negotiate = { ...negoData, ...result, awaiting_human_confirm: false };
}

async function runNegotiate() {
  const btn = $("#btnNegotiate");
  setBusy(btn, true);
  const chat = $("#chatStream");
  $("#settlement").classList.add("hidden");
  $("#humanConfirm").classList.add("hidden");
  chat.innerHTML = "";

  if (!state.backtestResult?.results?.role_breakdown?.length) {
    chat.innerHTML = `<div class="bubble arbiter"><div class="text">请先在「HS300 岗位贡献」完成回测，再开始五角色协商。</div></div>`;
    setBusy(btn, false);
    return;
  }

  try {
    const data = await api("/api/negotiate", {
      method: "POST",
      body: JSON.stringify({
        scenario: "hs300_five_roles",
        mode: "mock",
        backtest: state.backtestResult,
        bonus_pool: Number(state.dualPoolAmount) || 10_000_000,
        baseline_weights: getDualPoolBaseline(),
      }),
    });
    state.negotiate = data;
    $("#heroDesc").textContent = `${data.framework || ""} · ${data.scenario}`;

    for (const round of data.rounds) {
      const label = document.createElement("div");
      label.className = "round-label";
      label.textContent = `Round ${round.round} · ${round.phase} · consensus ${((round.consensus || 0) * 100).toFixed(0)}%`;
      chat.appendChild(label);
      for (const u of round.utterances) {
        chat.appendChild(renderUtterance(u));
        chat.scrollTop = chat.scrollHeight;
        await new Promise((r) => setTimeout(r, 220));
      }
    }

    chat.appendChild(
      renderUtterance({
        speaker: data.arbiter.name,
        role: data.arbiter.role,
        text: data.arbiter_statement,
      })
    );
    chat.scrollTop = chat.scrollHeight;

    renderSettlement(data);
    renderHumanConfirm(data);
  } catch (e) {
    chat.innerHTML = `<div class="bubble arbiter"><div class="text">协商失败：${e.message}</div></div>`;
  } finally {
    setBusy(btn, false);
  }
}

function destroyChart(key) {
  if (state.charts[key]) {
    state.charts[key].destroy();
    delete state.charts[key];
  }
}

const GROUP_COLORS = { kpi: "#d4786a", formula: "#5b8def", agent: "#3d9a7a" };
const GROUP_LABELS = { kpi: "KPI 基线", formula: "纯公式", agent: "Agent+锚点" };

async function runEvolution(rounds = 100) {
  const btn = $("#btnEvolution");
  setBusy(btn, true);
  try {
    const data = await api("/api/evolution", {
      method: "POST",
      body: JSON.stringify({ scenario: currentScenario(), rounds, seed: 42 }),
    });
    state.evolution = data;
    renderCompare(data);
    renderEvolutionCharts(data);
    return data;
  } finally {
    setBusy(btn, false);
  }
}

function renderCompare(data) {
  $("#compareNote").textContent = data.disclaimer || "";
  const labels = ["Gini↓", "满意度↑", "复用激励↑", "协作效率↑"];
  const keys = ["gini", "satisfaction", "reuse_incentive", "collaboration"];
  const datasets = ["kpi", "formula", "agent"].map((g) => ({
    label: GROUP_LABELS[g],
    data: keys.map((k) => data.summary[g][k]),
    backgroundColor: GROUP_COLORS[g],
  }));

  destroyChart("compare");
  state.charts.compare = new Chart($("#compareChart"), {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: CHART.muted } },
        title: { display: true, text: `${data.rounds} 轮均值对照`, color: CHART.ink },
      },
      scales: {
        x: { ticks: { color: CHART.muted }, grid: { color: CHART.grid } },
        y: { min: 0, max: 1, ticks: { color: CHART.muted }, grid: { color: CHART.grid } },
      },
    },
  });

  const rows = ["kpi", "formula", "agent"]
    .map((g) => {
      const s = data.summary[g];
      return `<tr>
        <td>${GROUP_LABELS[g]}</td>
        <td>${s.gini.toFixed(3)}</td>
        <td>${(s.satisfaction * 100).toFixed(1)}%</td>
        <td>${(s.reuse_incentive * 100).toFixed(1)}%</td>
        <td>${(s.collaboration * 100).toFixed(1)}%</td>
      </tr>`;
    })
    .join("");
  $("#compareTable").innerHTML = `
    <table>
      <thead><tr><th>组别</th><th>Gini</th><th>满意度</th><th>复用激励</th><th>协作</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function lineChart(canvasId, key, title, seriesKey) {
  const data = state.evolution;
  if (!data) return;
  const labels = data.series.kpi[seriesKey].map((_, i) => i + 1);
  destroyChart(key);
  state.charts[key] = new Chart($(canvasId), {
    type: "line",
    data: {
      labels,
      datasets: ["kpi", "formula", "agent"].map((g) => ({
        label: GROUP_LABELS[g],
        data: data.series[g][seriesKey],
        borderColor: GROUP_COLORS[g],
        backgroundColor: "transparent",
        tension: 0.25,
        pointRadius: 0,
        borderWidth: 2,
      })),
    },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: CHART.muted } },
        title: { display: true, text: title, color: CHART.ink },
      },
      scales: {
        x: { ticks: { color: CHART.muted, maxTicksLimit: 10 }, grid: { color: CHART.grid } },
        y: { ticks: { color: CHART.muted }, grid: { color: CHART.grid } },
      },
    },
  });
}

function renderEvolutionCharts(data) {
  state.evolution = data;
  lineChart("#giniChart", "gini", "Gini 系数（越低越均）", "gini");
  lineChart("#satChart", "sat", "公平满意度", "satisfaction");
  lineChart("#reuseChart", "reuse", "知识复用激励", "reuse");
}

async function runCalculate() {
  const btn = $("#btnCalculate");
  setBusy(btn, true);
  try {
    const data = await api("/api/calculate", {
      method: "POST",
      body: JSON.stringify({ scenario: currentScenario() }),
    });
    state.formula = data;
    const rows = data.contributors
      .map(
        (c) => `<tr>
        <td>${c.name}</td>
        <td>${c.hours}</td>
        <td>${c.impact}</td>
        <td>${c.complexity}</td>
        <td>${c.scarcity}</td>
        <td>${c.reuse_factor}</td>
        <td>${c.contribution}</td>
        <td>${c.share_pct}%</td>
        <td>${money(c.profit)}</td>
      </tr>`
      )
      .join("");
    $("#formulaTable").innerHTML = `
      <p class="note">${data.formula} · 可分配 ${money(data.distributable)} · 平台 ${money(data.platform_profit)} · 带宽 ±${((data.band || 0.05) * 100).toFixed(0)}%</p>
      <table>
        <thead>
          <tr>
            <th>姓名</th><th>工时</th><th>Impact</th><th>复杂度</th>
            <th>稀缺</th><th>复用</th><th>贡献值</th><th>锚点份额</th><th>金额</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>`;
  } finally {
    setBusy(btn, false);
  }
}

/* ---- Agent 规划回测归因 ---- */
async function runAttribution() {
  const btn = $("#btnAttribution");
  setBusy(btn, true);
  try {
    const data = await api("/api/attribution", {
      method: "POST",
      body: JSON.stringify({ scenario: currentScenario(), mode: "mock", seed: 42 }),
    });
    state.attribution = data;
    renderAttribution(data);
  } catch (e) {
    $("#attrPlan").textContent = "归因失败：" + e.message;
  } finally {
    setBusy(btn, false);
  }
}

function renderAttribution(data) {
  const plan = data.plan || {};
  const exps = (plan.experiments || [])
    .map((e) => `<li><strong>${e.name}</strong> — ${e.desc}</li>`)
    .join("");
  $("#attrPlan").innerHTML = `
    <h3>Agent 实验规划</h3>
    <div>${plan.goal || ""}</div>
    <ul class="attr-experiments">${exps}</ul>
    <div style="margin-top:0.6rem">决策规则：${plan.decision_rule || ""}</div>
  `;
  $("#attrInterp").innerHTML = `<h3>归因解读</h3><div>${(data.interpretation || "").replace(/\n/g, "<br/>")}</div>`;

  const w = data.backtest.weights;
  destroyChart("attrWeight");
  state.charts.attrWeight = new Chart($("#attrWeightChart"), {
    type: "doughnut",
    data: {
      labels: ["策略 Alpha", "行业·政策", "偶然·宏观"],
      datasets: [{
        data: [w.strategy_alpha * 100, w.industry_policy * 100, w.luck_macro * 100],
        backgroundColor: ["#3d9a7a", "#5b8def", "#c4a35a"],
      }],
    },
    options: {
      plugins: {
        legend: { labels: { color: CHART.muted } },
        title: { display: true, text: "三因素贡献比重", color: CHART.ink },
      },
    },
  });

  const names = Object.keys(data.attributed_allocation);
  destroyChart("attrAlloc");
  state.charts.attrAlloc = new Chart($("#attrAllocChart"), {
    type: "bar",
    data: {
      labels: names,
      datasets: [
        {
          label: "归因前份额%",
          data: names.map((n) => data.baseline_allocation[n].share_pct),
          backgroundColor: "rgba(139,155,176,0.45)",
        },
        {
          label: "归因后份额%",
          data: names.map((n) => data.attributed_allocation[n].share_pct),
          backgroundColor: "#3d9a7a",
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: CHART.muted } },
        title: { display: true, text: "写入 Impact 锚点后的分配变化", color: CHART.ink },
      },
      scales: {
        x: { ticks: { color: CHART.muted }, grid: { color: CHART.grid } },
        y: { ticks: { color: CHART.muted, callback: (v) => v + "%" }, grid: { color: CHART.grid } },
      },
    },
  });

  const cells = data.backtest.cells || [];
  const rows = cells
    .map(
      (c) => `<tr>
      <td>${c.period_label}</td>
      <td>${c.category_label}</td>
      <td>${(c.ann_strategy * 100).toFixed(1)}%</td>
      <td>${(c.alpha_hat * 100).toFixed(2)}%</td>
      <td>${(c.industry_contrib_ann * 100).toFixed(2)}%</td>
      <td>${(c.noise_share * 100).toFixed(0)}%</td>
    </tr>`
    )
    .join("");
  const ov = data.impact_overrides || {};
  const ovRows = Object.entries(ov)
    .map(([n, v]) => `<tr><td>${n}</td><td>${v}</td>
      <td>${data.baseline_allocation[n]?.share_pct ?? "-"}%</td>
      <td>${data.attributed_allocation[n]?.share_pct ?? "-"}%</td>
      <td>${money(data.attributed_allocation[n]?.profit ?? 0)}</td></tr>`)
    .join("");

  $("#attrTable").innerHTML = `
    <p class="note">${data.backtest.disclaimer || ""}</p>
    <h3 style="font-family:var(--display);font-weight:400">回测切片（合成数据）</h3>
    <table>
      <thead><tr><th>时段</th><th>品类</th><th>策略年化</th><th>Alpha</th><th>行业贡献</th><th>噪声</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <h3 style="font-family:var(--display);font-weight:400;margin-top:1rem">Impact 覆盖 → 分配</h3>
    <table>
      <thead><tr><th>角色</th><th>新 Impact</th><th>原份额</th><th>新份额</th><th>金额</th></tr></thead>
      <tbody>${ovRows}</tbody>
    </table>`;
}


/* ---- 目标设定 · 自动回平衡 ---- */
const SENS_COLORS = ["#3d9a7a", "#5b8def", "#9b7bdb", "#c4a35a", "#d4786a"];
let rebalanceTimer = null;
state.targetDefaults = null;

async function loadTargetControls() {
  const data = await api("/api/calculate", {
    method: "POST",
    body: JSON.stringify({ scenario: currentScenario() }),
  });
  const defaults = {};
  data.contributors.forEach((c) => {
    defaults[c.name] = c.share_pct;
  });
  state.targetDefaults = defaults;
  state.formula = data;

  const box = $("#targetControls");
  if (!box) return;
  box.innerHTML =
    data.contributors
      .map((c) => {
        const v = c.share_pct.toFixed(1);
        return `<label class="slider-row">
          <span>${c.name} 目标份额 <strong data-val-for="${c.name}">${v}</strong>%</span>
          <input type="range" class="target-slider" data-name="${c.name}" min="5" max="70" step="0.5" value="${v}" />
        </label>`;
      })
      .join("") + `<div class="target-sum" id="targetSum"></div>`;

  box.querySelectorAll(".target-slider").forEach((el) => {
    el.addEventListener("input", () => {
      const name = el.dataset.name;
      const label = box.querySelector(`[data-val-for="${name}"]`);
      if (label) label.textContent = Number(el.value).toFixed(1);
      updateTargetSum();
      previewTargetsOnChart();
    });
  });
  updateTargetSum();
  previewTargetsOnChart();
  refreshSweepOnly();
}

function readTargetShares() {
  const shares = {};
  $$(".target-slider").forEach((el) => {
    shares[el.dataset.name] = Number(el.value) / 100;
  });
  return shares;
}

function updateTargetSum() {
  const shares = readTargetShares();
  const sum = Object.values(shares).reduce((a, b) => a + b, 0) * 100;
  const el = $("#targetSum");
  if (!el) return;
  el.textContent = `目标合计 ${sum.toFixed(1)}%（播放前会自动归一；偏激目标会被投影到锚点±带宽内）`;
  el.classList.toggle("warn", Math.abs(sum - 100) > 8);
}

function previewTargetsOnChart() {
  const shares = readTargetShares();
  const names = Object.keys(shares);
  const values = names.map((n) => shares[n] * 100);
  renderShareBar(names, values, "你设定的目标份额（尚未回平衡）");
}

function renderShareBar(names, valuesPct, title) {
  const colors = names.map((_, i) => SENS_COLORS[i % SENS_COLORS.length]);
  destroyChart("shareBar");
  state.charts.shareBar = new Chart($("#shareBarChart"), {
    type: "bar",
    data: {
      labels: names,
      datasets: [{ label: "份额 %", data: valuesPct, backgroundColor: colors }],
    },
    options: {
      responsive: true,
      animation: { duration: 180 },
      plugins: {
        legend: { display: false },
        title: { display: true, text: title, color: CHART.ink },
      },
      scales: {
        x: { ticks: { color: CHART.muted }, grid: { color: CHART.grid } },
        y: {
          min: 0,
          max: 70,
          ticks: { color: CHART.muted, callback: (v) => v + "%" },
          grid: { color: CHART.grid },
        },
      },
    },
  });
}

async function refreshSweepOnly() {
  try {
    const data = await api("/api/sensitivity", {
      method: "POST",
      body: JSON.stringify({
        scenario: currentScenario(),
        factor_weight: 0.45,
        sweep: true,
        sweep_points: 13,
      }),
    });
    const names = Object.keys(data.sweep.share_pct);
    destroyChart("sweep");
    state.charts.sweep = new Chart($("#sweepChart"), {
      type: "line",
      data: {
        labels: data.sweep.factor_weight.map((w) => Number(w).toFixed(2)),
        datasets: names.map((name, i) => ({
          label: name,
          data: data.sweep.share_pct[name],
          borderColor: SENS_COLORS[i % SENS_COLORS.length],
          backgroundColor: "transparent",
          tension: 0.3,
          pointRadius: 2,
          borderWidth: 2,
        })),
      },
      options: {
        responsive: true,
        plugins: {
          legend: { labels: { color: CHART.muted } },
          title: {
            display: true,
            text: "参考：份额随因子权重 w 的可行域",
            color: CHART.ink,
          },
        },
        scales: {
          x: {
            title: { display: true, text: "因子权重 w", color: CHART.muted },
            ticks: { color: CHART.muted },
            grid: { color: CHART.grid },
          },
          y: {
            title: { display: true, text: "份额 %", color: CHART.muted },
            ticks: { color: CHART.muted },
            grid: { color: CHART.grid },
          },
        },
      },
    });
  } catch (_) {}
}

function renderRebalanceTable(data, frame) {
  const names = Object.keys(data.reasonable_target);
  const rows = names
    .map((n) => {
      const cur = frame.shares[n];
      return `<tr>
        <td>${n}</td>
        <td>${(data.user_target[n] * 100).toFixed(1)}%</td>
        <td>${(data.formula_anchor[n] * 100).toFixed(1)}%</td>
        <td>${(data.reasonable_target[n] * 100).toFixed(1)}%</td>
        <td>${(cur * 100).toFixed(1)}%</td>
        <td>${money(frame.amounts[n])}</td>
      </tr>`;
    })
    .join("");
  $("#sensTable").innerHTML = `
    <p class="note">${data.explanation}</p>
    <table>
      <thead>
        <tr>
          <th>角色</th><th>你的目标</th><th>公式锚点</th><th>合理目标</th><th>当前动画</th><th>金额</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

async function playRebalance() {
  const btn = $("#btnRebalance");
  setBusy(btn, true);
  clearTimeout(rebalanceTimer);
  $("#liveMsg").textContent = "计算回平衡轨迹…";

  try {
    const data = await api("/api/rebalance", {
      method: "POST",
      body: JSON.stringify({
        scenario: currentScenario(),
        target_shares: readTargetShares(),
        steps: 28,
        start_weight: 0.25,
      }),
    });
    state.rebalance = data;
    const traj = data.trajectory || [];
    let i = 0;

    const tick = () => {
      if (i >= traj.length) {
        $("#liveMsg").textContent = `完成：最佳 w=${data.best_factor_weight}，已收敛到合理配比`;
        setBusy(btn, false);
        return;
      }
      const frame = traj[i];
      const names = Object.keys(frame.shares);
      renderShareBar(
        names,
        names.map((n) => frame.shares[n] * 100),
        `自动回平衡中 · step ${frame.step}/${traj.length - 1}`
      );
      $("#liveW").textContent = Number(frame.factor_weight).toFixed(3);
      $("#liveProgress").textContent = `${Math.round(frame.progress * 100)}%`;
      $("#liveMsg").textContent =
        i === 0
          ? "从偏激目标出发…"
          : i === traj.length - 1
            ? "到达合理配比"
            : "权重自动调整中…";
      renderRebalanceTable(data, frame);
      i += 1;
      rebalanceTimer = setTimeout(tick, 110);
    };
    tick();
  } catch (e) {
    $("#liveMsg").textContent = `失败：${e.message}`;
    setBusy(btn, false);
  }
}

async function resetSensitivity() {
  await loadTargetControls();
  $("#liveW").textContent = "—";
  $("#liveProgress").textContent = "0%";
  $("#liveMsg").textContent = "已重置为目标=公式锚点，可再故意拖偏后演示";
}

/* ---- HS300 真实回测（QuantSkills 引擎） ---- */
const BT_INDUSTRIES = [
  "半导体", "证券Ⅱ", "银行", "消费电子", "计算机", "医药生物", "有色金属",
  "电子", "光伏设备", "食品饮料", "汽车", "通信", "国防军工", "软件开发",
  "煤炭", "房地产", "钢铁", "电力设备", "传媒", "白酒Ⅱ",
];

function setBacktestStatus(msg, kind = "running") {
  const el = $("#backtestStatus");
  el.classList.remove("hidden", "error", "ok");
  if (kind === "error") el.classList.add("error");
  if (kind === "ok") el.classList.add("ok");
  el.textContent = msg;
}

function clearBacktestTimer() {
  if (state.backtestTimer) {
    clearInterval(state.backtestTimer);
    state.backtestTimer = null;
  }
}

const ROLE_DUTIES = {
  行业分析师: "行业配置与赛道选择",
  个股分析师: "个股精选与打分",
  策略分析师: "择时与仓位调整",
  量化分析师: "多策略信号优化",
  风控分析师: "集中度与止损约束",
};

const STAGE_NARRATIVE = {
  idle: {
    tag: "准备就绪",
    title: "点击「路演演示」秒开，或「实时回测」完整计算",
    body: "经典归因只能到资产/风格；本演示把计量对象延伸到投研组织角色，并用真实行情验证。",
    meaning: "等待启动。系统将用因子代理各岗位决策，再通过对照实验估计贡献。",
    output: "可解释的贡献系数 + 回测证据链（非自动发薪）。",
  },
  parse: {
    tag: "步骤 1/5",
    title: "解析回测参数",
    body: "确认时间区间、行业范围、基准指数与调仓频率。",
    meaning: "把业务问题翻译成可执行的回测任务。",
    output: "标准化查询条件，保证结果可复现。",
  },
  init: {
    tag: "步骤 2/5",
    title: "加载行情与映射数据",
    body: "读取沪深300成分股日线、行业映射与因子计算所需数据。",
    meaning: "构建「信号层」——各角色决策的可计算输入底座。",
    output: "股票池规模、交易日数量等基础信息。",
  },
  factors: {
    tag: "步骤 3/5",
    title: "五类角色因子选股",
    body: "行业/个股/策略/量化/风控各自用因子打分，按月选出候选股票。",
    meaning: "把「岗位决策」量化为可回测的选股方案（因子套壳代理）。",
    output: "各角色每月选股清单与样本股。",
  },
  pipeline: {
    tag: "步骤 4/5",
    title: "多角色 Pipeline 组合回测",
    body: "按投研链顺序整合五类决策：行业→个股→量化→策略→风控，模拟真实协作。",
    meaning: "观察「全员参与」时组合相对基准的表现。",
    output: "组合累计收益曲线，作为后续归因的基准绩效。",
  },
  shapley: {
    tag: "步骤 5/5",
    title: "夏普利反事实对照实验",
    body: "遍历不同角色联盟组合，回答「如果只有这几类岗位参与，收益会变成多少」。",
    meaning: "从相关到边际贡献：估计各岗位独立带来的增量。",
    output: "各角色夏普利贡献值 → 可解释分配权重。",
  },
  save: {
    tag: "收尾",
    title: "保存中间结果",
    body: "写入选股、收益、归因等中间文件，便于审计与复现。",
    meaning: "保证计量过程可追溯，而非黑箱一次输出。",
    output: "完整 JSON 报告与中间数据目录。",
  },
  complete: {
    tag: "已完成",
    title: "贡献计量完成",
    body: "已得到各岗位贡献排序与权重，可进入「协商与确认」讨论如何应用这些证据。",
    meaning: "技术链路闭环：证据 → 决策支持（人工终裁）。",
    output: "见下方「结论摘要」；明细见技术图表。",
  },
};

function updateBacktestNarrative(stageId, contextText) {
  const stageMap = { filter: "init", assemble: "save" };
  const key = stageMap[stageId] || stageId || "idle";
  const n = STAGE_NARRATIVE[key] || STAGE_NARRATIVE.idle;
  const tagEl = $("#narrativeTag");
  const titleEl = $("#narrativeTitle");
  const bodyEl = $("#narrativeBody");
  const meaningEl = $("#narrativeMeaning");
  const outputEl = $("#narrativeOutput");
  if (!tagEl) return;
  tagEl.textContent = n.tag;
  titleEl.textContent = contextText || n.title;
  bodyEl.textContent = n.body;
  meaningEl.textContent = n.meaning;
  outputEl.textContent = n.output;
  if ($("#panel-backtest")?.classList.contains("is-running") && key !== "idle") {
    pulseNarrative3D();
  }
}

function renderBacktestConclusion(data, { showTechDivider = true } = {}) {
  const box = $("#backtestConclusion");
  const divider = $("#backtestTechDivider");
  if (!box) return;
  const results = data.results || {};
  const ov = results.overview || {};
  const breakdown = [...(results.role_breakdown || [])].sort(
    (a, b) => (b.weight || 0) - (a.weight || 0)
  );
  const excess = ov.excess_return || 0;
  const excessPct = (excess * 100).toFixed(2);
  const beat = excess > 0;
  const top = breakdown[0];
  const bottom = breakdown[breakdown.length - 1];

  let lead = beat
    ? `本区间组合<strong>跑赢</strong>沪深300基准，超额收益约 <strong>${excessPct}%</strong>。`
  : `本区间组合<strong>未跑赢</strong>基准，超额收益约 <strong>${excessPct}%</strong>。`;
  if (top) {
    lead += ` 按夏普利归因，<strong>${top.role}</strong>贡献权重最高（${((top.weight || 0) * 100).toFixed(1)}%）。`;
  }
  if (bottom && bottom.role !== top?.role && (bottom.shapley_raw || 0) < 0) {
    lead += ` <strong>${bottom.role}</strong>呈负向拖累，需在考核中重点关注。`;
  }

  const rankHtml = breakdown
    .map((r, i) => {
      const w = ((r.weight || 0) * 100).toFixed(1);
      const sh = ((r.shapley_raw || 0) * 100).toFixed(2);
      return `<li>
        <span class="rank-dot" style="background:${roleColor(r.role)}"></span>
        <span>${i + 1}. ${r.role}</span>
        <span style="margin-left:auto;color:var(--muted)">权重 ${w}% · 夏普利 ${sh}%</span>
      </li>`;
    })
    .join("");

  const rec = results.recommendation?.summary || data.query_summary || "";

  box.innerHTML = `
    <h3>结论摘要（给业务看）</h3>
    <p class="conclusion-lead">${lead}</p>
    <p class="note dual-track-hint" style="margin:0 0 0.75rem">
      <strong>6:4 双轨：</strong>本回测产出的是<strong>新池 40%</strong> 夏普利建议权重；
      旧池 60% 沿用机构现行方案。完整合成表见下一步「人工确认」。
    </p>
    ${rec ? `<p class="note" style="margin:0 0 0.75rem">${rec}</p>` : ""}
    <p class="note" style="margin:0 0 0.5rem"><strong>用途：</strong>以下为贡献计量证据，供考核与分配<strong>讨论参考</strong>；最终需人工确认，<strong>非自动发薪</strong>。</p>
    <ul class="rank-list">${rankHtml}</ul>
    <div class="conclusion-actions">
      <button type="button" class="btn primary" id="btnGotoNegotiate">下一步：人工确认 →</button>
    </div>
  `;
  box.classList.remove("hidden");
  if (divider) {
    divider.classList.toggle("hidden", !showTechDivider);
  }
  updateHeroKpis(data);
  $("#btnGotoNegotiate")?.addEventListener("click", () => {
    renderDualPoolPanel();
    switchToTab("negotiate");
  });
  updateBacktestNarrative("complete");
}

const BT_STAGE_ORDER = ["parse", "init", "factors", "pipeline", "shapley", "save", "complete"];

/** 五类分析师固定配色（全流程一致） */
const ROLE_COLORS = {
  行业分析师: "#5b8def",
  个股分析师: "#0d9488",
  策略分析师: "#9b7bdb",
  量化分析师: "#c4a35a",
  风控分析师: "#d4786a",
};

const ROLE_SHORT = {
  行业分析师: "行业",
  个股分析师: "个股",
  策略分析师: "策略",
  量化分析师: "量化",
  风控分析师: "风控",
};

function coalitionLabel(subset) {
  if (!subset?.length) return "空联盟";
  return subset.map((r) => ROLE_SHORT[r] || r).join("+");
}

function roleColor(role, alpha = 1) {
  const hex = ROLE_COLORS[role] || CHART.muted;
  if (alpha >= 1) return hex;
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function initBacktestLiveState() {
  const roles = state.backtestMeta?.roles || [
    "行业分析师", "个股分析师", "策略分析师", "量化分析师", "风控分析师",
  ];
  state.backtestLive = {
    roleOrder: roles,
    roles: Object.fromEntries(roles.map((r) => [r, { months: 0, sample: [], done: false }])),
    shapleyPoints: [],
    pipelineMonthly: [],
    pipelineReturn: null,
    stocks: null,
    tradingDays: null,
  };
  renderRoleFactorCards();
  $("#backtestLiveMetrics").innerHTML = "";
  destroyChart("btRoleLive");
  destroyChart("btNavLive");
  destroyChart("btShapleyLive");
}

function setBacktestRunning(running) {
  $("#panel-backtest")?.classList.toggle("is-running", !!running);
  document.body.classList.toggle("backtest-progress-active", !!running);
  if (!running) {
    $("#backtestProgressWrap")?.classList.add("hidden");
    if (state.backtestFocusTimer) {
      clearTimeout(state.backtestFocusTimer);
      state.backtestFocusTimer = null;
    }
    resetLiveZoneStates();
    $$(".role-factor-card").forEach((c) => c.classList.remove("active"));
    $$(".live-zone").forEach((z) => z.classList.remove("zone-3d-pop"));
    const labelEl = $("#liveZoneLabel");
    if (labelEl) labelEl.textContent = "等待开始";
  }
}

function resetLiveZoneStates() {
  LIVE_ZONE_ORDER.forEach((id) => {
    const z = $(`#${id}`);
    if (!z) return;
    z.classList.remove("live-zone-active", "live-zone-done");
    z.classList.add("live-zone-pending");
  });
}

function updateLiveZoneStates(activeId) {
  const activeIdx = LIVE_ZONE_ORDER.indexOf(activeId);
  LIVE_ZONE_ORDER.forEach((id, idx) => {
    const z = $(`#${id}`);
    if (!z) return;
    z.classList.remove("live-zone-active", "live-zone-done", "live-zone-pending");
    if (idx < activeIdx) z.classList.add("live-zone-done");
    else if (idx === activeIdx) z.classList.add("live-zone-active");
    else z.classList.add("live-zone-pending");
  });
}

const BACKTEST_STAGE_ZONE = {
  parse: "liveZoneMetrics",
  init: "liveZoneMetrics",
  filter: "liveZoneMetrics",
  factors: "liveZoneRoles",
  pipeline: "liveZonePipeline",
  shapley: "liveZoneShapley",
  save: "liveZoneShapley",
  complete: "conclusion",
};

function scrollBacktestTo(el, block = "nearest") {
  if (!el) return;
  if (state.backtestFocusTimer) clearTimeout(state.backtestFocusTimer);
  state.backtestFocusTimer = setTimeout(() => {
    el.scrollIntoView({ behavior: "smooth", block, inline: "nearest" });
  }, 160);
}

function focusBacktestStage(stageId, opts = {}) {
  const stageMap = { filter: "init", assemble: "save" };
  const mapped = stageMap[stageId] || stageId;
  const zoneKey = BACKTEST_STAGE_ZONE[mapped];

  if (zoneKey === "narrative") {
    pulseNarrative3D();
    scrollBacktestTo($("#backtestNarrative"), "start");
    return;
  }
  if (zoneKey === "conclusion") {
    scrollBacktestTo($("#backtestConclusion"), "center");
    return;
  }
  if (!zoneKey) return;

  const zone = $(`#${zoneKey}`);
  if (!zone) return;

  updateLiveZoneStates(zoneKey);
  pulseZone3D(zone);

  const label = zone.dataset.zoneLabel || mapped;
  const labelEl = $("#liveZoneLabel");
  if (labelEl) labelEl.textContent = label;

  if (opts.scroll !== false) {
    scrollBacktestTo(zone, "nearest");
  }
}

function highlightRoleCard(role) {
  $$(".role-factor-card").forEach((c) => c.classList.remove("active"));
  const card = $(`.role-factor-card[data-role="${role}"]`);
  if (card) {
    card.classList.add("active");
    if ($("#panel-backtest")?.classList.contains("is-running")) {
      scrollBacktestTo(card, "nearest");
    }
  }
}

function resetBacktestProgressUI() {
  $("#backtestProgressWrap").classList.remove("hidden");
  $("#backtestLivePanel").classList.remove("hidden");
  $("#backtestProgressFill").style.width = "0%";
  $("#backtestPercentLabel").textContent = "0%";
  $("#backtestStageLabel").textContent = "准备启动…";
  $("#backtestLog").innerHTML = "";
  $$("#backtestSteps li").forEach((li) => li.classList.remove("active", "done"));
  initBacktestLiveState();
  resetLiveZoneStates();
  updateBacktestNarrative("idle");
  $("#backtestConclusion")?.classList.add("hidden");
  $("#backtestTechDivider")?.classList.add("hidden");
}

function renderRoleFactorCards() {
  const box = $("#backtestRoleCards");
  if (!box || !state.backtestLive) return;
  box.innerHTML = state.backtestLive.roleOrder
    .map((role) => {
      const info = state.backtestLive.roles[role] || {};
      const cls = info.done ? "done" : "pending";
      const border = roleColor(role, info.done ? 1 : 0.45);
      const sample = (info.sampleLabels || info.sample || []).slice(0, 3).join("、") || "—";
      return `<div class="role-factor-card ${cls}" data-role="${role}" style="border-left:3px solid ${border}">
        <div class="name">${role}</div>
        <div class="duty">${ROLE_DUTIES[role] || ""}</div>
        <div class="sub">${info.done ? `已完成 · ${info.months} 个月选股` : "等待计算…"}</div>
        <div class="sub">样本：${sample}</div>
      </div>`;
    })
    .join("");
}

function updateLiveMetrics() {
  const live = state.backtestLive;
  if (!live) return;
  const parts = [];
  if (live.stocks != null) {
    parts.push(`<div class="metric-card"><div class="label">股票池</div><div class="value">${live.stocks}</div><div class="sub">只</div></div>`);
  }
  if (live.tradingDays != null) {
    parts.push(`<div class="metric-card"><div class="label">交易日</div><div class="value">${live.tradingDays}</div><div class="sub">天</div></div>`);
  }
  if (live.pipelineReturn != null) {
    parts.push(`<div class="metric-card"><div class="label">组合累计</div><div class="value">${(live.pipelineReturn * 100).toFixed(2)}%</div><div class="sub">五角色协作</div></div>`);
  }
  if (live.shapleyPoints.length) {
    parts.push(`<div class="metric-card"><div class="label">夏普利子集</div><div class="value">${live.shapleyPoints.length}/31</div><div class="sub">反事实回测进度</div></div>`);
  }
  $("#backtestLiveMetrics").innerHTML = parts.join("");
}

function updateRoleLiveChart() {
  const live = state.backtestLive;
  if (!live) return;
  const labels = live.roleOrder;
  const data = labels.map((r) => live.roles[r]?.months || 0);
  const colors = labels.map((r) =>
    roleColor(r, live.roles[r]?.done ? 1 : 0.35)
  );
  destroyChart("btRoleLive");
  state.charts.btRoleLive = new Chart($("#backtestRoleLiveChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [{ label: "选股月数", data, backgroundColor: colors }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        title: { display: true, text: "各角色因子选股进度（同色标识）", color: CHART.ink },
      },
      scales: {
        x: { ticks: { color: CHART.muted, maxRotation: 45 }, grid: { color: CHART.grid } },
        y: { beginAtZero: true, ticks: { color: CHART.muted, stepSize: 1 }, grid: { color: CHART.grid } },
      },
    },
  });
  state.charts.btRoleLive?.resize();
}

function updateNavLiveChart() {
  const live = state.backtestLive;
  if (!live?.pipelineMonthly?.length) return;
  const labels = live.pipelineMonthly.map((m) => m.month);
  const data = live.pipelineMonthly.map((m) => m.cumulative * 100);
  destroyChart("btNavLive");
  state.charts.btNavLive = new Chart($("#backtestNavLiveChart"), {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "累计收益 %",
        data,
        borderColor: "#0d6e5c",
        backgroundColor: "rgba(13, 110, 92, 0.08)",
        fill: true,
        tension: 0.35,
        pointRadius: 0,
        borderWidth: 2,
      }],
    },
    options: {
      ...chartPremiumOptions("组合累计收益", (v) => v + "%"),
    },
  });
  state.charts.btNavLive?.resize();
}

function shapleyBarColor(subset) {
  if (!subset?.length) return CHART.muted;
  if (subset.length === 1) return roleColor(subset[0], 1);
  // 多角色联盟：取首个角色色并略透明，与单角色区分
  return roleColor(subset[0], 0.72);
}

function updateShapleyLiveChart() {
  const live = state.backtestLive;
  if (!live?.shapleyPoints.length) return;
  const labels = live.shapleyPoints.map((p) => p.label || coalitionLabel(p.subset));
  const data = live.shapleyPoints.map((p) => p.y);
  const colors = live.shapleyPoints.map((p) => shapleyBarColor(p.subset));
  destroyChart("btShapleyLive");
  state.charts.btShapleyLive = new Chart($("#backtestShapleyLiveChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "子集累计收益 %",
        data,
        backgroundColor: colors,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        title: {
          display: true,
          text: "夏普利反事实子集收益（横轴为角色联盟简称）",
          color: CHART.ink,
        },
        tooltip: {
          callbacks: {
            title(ctx) {
              const p = live.shapleyPoints[ctx[0]?.dataIndex];
              return p ? `第 ${p.index} 组 · ${p.fullLabel || coalitionLabel(p.subset)}` : "";
            },
            afterLabel(ctx) {
              const p = live.shapleyPoints[ctx.dataIndex];
              if (!p) return "";
              const names = (p.subset || []).join("、") || "无";
              return `完整角色：${names}`;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: CHART.muted, maxRotation: 55, minRotation: 45, font: { size: 10 } },
          grid: { color: CHART.grid },
        },
        y: { ticks: { color: CHART.muted, callback: (v) => v + "%" }, grid: { color: CHART.grid } },
      },
    },
  });
  state.charts.btShapleyLive?.resize();
}

function setBacktestProgress(percent, message, stageId) {
  const pct = Math.max(0, Math.min(100, Number(percent) || 0));
  $("#backtestProgressFill").style.width = `${pct}%`;
  $("#backtestPercentLabel").textContent = `${pct.toFixed(0)}%`;
  if (message) $("#backtestStageLabel").textContent = message;
  if (stageId) {
    const stageMap = { filter: "init", assemble: "save" };
    const mapped = stageMap[stageId] || stageId;
    updateBacktestNarrative(
      mapped,
      STAGE_NARRATIVE[mapped]?.title === message ? undefined : message
    );
    const idx = BT_STAGE_ORDER.indexOf(mapped);
    $$("#backtestSteps li").forEach((li) => {
      const s = li.dataset.step;
      const si = BT_STAGE_ORDER.indexOf(s);
      li.classList.remove("active", "done");
      if (si >= 0 && idx >= 0) {
        if (si < idx) li.classList.add("done");
        if (si === idx) li.classList.add("active");
      }
    });
    if (mapped === "complete") {
      $$("#backtestSteps li").forEach((li) => li.classList.add("done"));
    }
    focusBacktestStage(mapped);
  }
}

function appendBacktestLog(message, cls = "log-line") {
  const box = $("#backtestLog");
  const line = document.createElement("div");
  line.className = cls;
  line.textContent = message;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

function renderPartialShapley(values) {
  const roles = Object.keys(values || {});
  if (!roles.length) return;
  const data = roles.map((r) => (values[r] || 0) * 100);
  destroyChart("btShapley");
  state.charts.btShapley = new Chart($("#backtestShapleyChart"), {
    type: "bar",
    data: {
      labels: roles,
      datasets: [{
        label: "夏普利边际贡献 %",
        data,
        backgroundColor: roles.map((r) => roleColor(r, 1)),
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        title: { display: true, text: "各角色夏普利边际贡献", color: CHART.ink },
      },
      scales: {
        x: { ticks: { color: CHART.muted }, grid: { color: CHART.grid } },
        y: { ticks: { color: CHART.muted, callback: (v) => v + "%" }, grid: { color: CHART.grid } },
      },
    },
  });
}

function handleBacktestStreamEvent(ev) {
  if (ev.type === "stage") {
    setBacktestProgress(ev.percent, ev.message, ev.stage);
    return;
  }
  if (ev.type === "log") {
    appendBacktestLog(ev.message);
    return;
  }
  if (ev.type === "data_snapshot") {
    state.backtestStreamPopulated = true;
    if (state.backtestLive) {
      state.backtestLive.stocks = ev.stocks;
      state.backtestLive.tradingDays = ev.trading_days;
      updateLiveMetrics();
    }
    focusBacktestStage("init");
    return;
  }
  if (ev.type === "role_factor") {
    state.backtestStreamPopulated = true;
    if (state.backtestLive) {
      state.backtestLive.roles[ev.role] = {
        months: ev.months,
        sample: ev.sample_stocks || [],
        sampleLabels: ev.sample_labels || ev.sample_stocks || [],
        done: true,
      };
      renderRoleFactorCards();
      highlightRoleCard(ev.role);
      updateRoleLiveChart();
      updateLiveMetrics();
      setBacktestProgress(ev.percent, `${ev.role} 因子选股完成`, "factors");
      focusBacktestStage("factors");
    }
    return;
  }
  if (ev.type === "pipeline") {
    if (state.backtestLive) {
      state.backtestLive.pipelineReturn = ev.total_return;
      state.backtestLive.pipelineMonthly = ev.monthly || [];
      updateNavLiveChart();
      updateLiveMetrics();
      setBacktestProgress(51, `Pipeline 收益 ${((ev.total_return || 0) * 100).toFixed(2)}%`, "pipeline");
      focusBacktestStage("pipeline");
    }
    return;
  }
  if (ev.type === "shapley") {
    const subset = ev.subset || [];
    const label = ev.subset_label || coalitionLabel(subset);
    const fullLabel = ev.subset_full || subset.join("、") || "空联盟";
    const ret = ev.subset_return ?? 0;
    const current = ev.current;
    const total = ev.total ?? 31;
    appendBacktestLog(
      `[夏普利 ${current}/${total}] ${fullLabel} → 收益 ${(ret * 100).toFixed(2)}%`,
      "log-line log-shapley"
    );
    if (state.backtestLive && current) {
      state.backtestLive.shapleyPoints.push({
        index: current,
        y: ret * 100,
        size: subset.length || 1,
        subset,
        label,
        fullLabel,
      });
      updateShapleyLiveChart();
      updateLiveMetrics();
    }
    setBacktestProgress(ev.percent, `夏普利子集 ${current}/${total}：${label}`, "shapley");
    focusBacktestStage("shapley");
    return;
  }
  if (ev.type === "partial_shapley") {
    appendBacktestLog("夏普利值计算完成，更新贡献图…");
    renderPartialShapley(ev.values);
  }
}

async function consumeBacktestStream(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      const jsonText = line.replace(/^data:\s*/, "");
      if (!jsonText) continue;
      const ev = JSON.parse(jsonText);
      if (ev.type === "complete") {
        finalResult = ev.result;
        continue;
      }
      if (ev.type === "error") {
        throw new Error(ev.error_message || "回测执行失败");
      }
      handleBacktestStreamEvent(ev);
    }
  }
  return finalResult;
}

async function loadBacktestMeta() {
  try {
    const meta = await api("/api/backtest/meta");
    state.backtestMeta = meta;

    const roleSel = $("#btRole");
    roleSel.innerHTML =
      '<option value="">全部角色</option>' +
      (meta.roles || [])
        .map((r) => `<option value="${r}">${r}</option>`)
        .join("");

    const benchSel = $("#btBenchmark");
    benchSel.innerHTML = (meta.benchmarks || ["hs300"])
      .map((b) => {
        const label = b === "hs300" ? "沪深300" : b === "csi500" ? "中证500" : b;
        return `<option value="${b}">${label}</option>`;
      })
      .join("");

    const indSel = $("#btIndustry");
    indSel.innerHTML =
      '<option value="">全行业</option>' +
      BT_INDUSTRIES.map((i) => `<option value="${i}">${i}</option>`).join("");

    if (!meta.data_ready) {
      setBacktestStatus("回测数据未就绪，请确认 data/processed/ 已随仓库提供。", "error");
    } else if (meta.demo?.available) {
      updateBacktestModeHint(`可路演演示：${meta.demo.label || "官方预置包"}`);
    }
    initBacktestLiveState();
    updateBacktestNarrative("idle");
  } catch (e) {
    setBacktestStatus(`回测引擎不可用：${e.message}`, "error");
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const DEMO_REPLAY_PACE = {
  stage: 1200,
  snapshot: 1000,
  role: 1100,
  pipeline: 1600,
  shapley: 750,
};

const LIVE_ZONE_ORDER = [
  "liveZoneMetrics",
  "liveZoneRoles",
  "liveZonePipeline",
  "liveZoneShapley",
];

function backtestSourceLabel(data) {
  const src = data?._source;
  if (src === "demo") return "路演演示包（预置）";
  if (src === "cache") return "参数缓存（秒开）";
  if (src === "computed") return "实时计算";
  if (src === "history") return "历史记录";
  return "已加载";
}

function updateBacktestModeHint(text) {
  const el = $("#backtestModeHint");
  if (el) el.textContent = text ? ` · ${text}` : "";
}

function buildBacktestPayload(overrides = {}) {
  const { query: queryOverride, ...rest } = overrides;
  const baseQuery = state.agentPlan?.query || {
    time_range: {
      start_date: $("#btStart").value,
      end_date: $("#btEnd").value,
    },
    target_role: $("#btRole").value || null,
    industry: $("#btIndustry").value || null,
    benchmark: $("#btBenchmark").value || "hs300",
    rebalance_freq: $("#btFreq").value || "monthly",
    granularity: $("#btFreq").value || "monthly",
  };
  return {
    request_id: `web_${Date.now()}`,
    use_cache: $("#btUseCache")?.checked !== false,
    force_refresh: false,
    demo_mode: false,
    ...rest,
    query: { ...baseQuery, ...(queryOverride || {}) },
  };
}

function applyAgentPlanToForm(plan) {
  if (!plan?.query) return;
  const q = plan.query;
  const tr = q.time_range || {};
  if (tr.start_date) $("#btStart").value = tr.start_date;
  if (tr.end_date) $("#btEnd").value = tr.end_date;
  if ($("#btIndustry")) $("#btIndustry").value = q.industry || "";
  if ($("#btRole")) $("#btRole").value = q.target_role || "";
  if ($("#btBenchmark")) $("#btBenchmark").value = q.benchmark || "hs300";
  const freq = q.rebalance_freq || q.granularity || "monthly";
  if ($("#btFreq")) $("#btFreq").value = freq;
}

function renderAgentPlanPreview(plan) {
  const box = $("#agentPlanPreview");
  if (!box || !plan) return;
  const steps = (plan.steps || [])
    .map((s) => `<li><strong>${s.title}</strong> — ${s.detail}</li>`)
    .join("");
  box.innerHTML = `
    <h4>Agent 回测计划</h4>
    <p><strong>${plan.summary || ""}</strong></p>
    <p class="note" style="margin:0.35rem 0">${plan.reasoning || ""}</p>
    ${steps ? `<ul class="agent-bullets">${steps}</ul>` : ""}
    <p class="note" style="margin:0.5rem 0 0">来源：${plan.source || "rule"} · 已同步至下方参数表单</p>
  `;
  box.classList.remove("hidden");
}

function renderAgentReport(report) {
  const box = $("#agentReportPanel");
  if (!box || !report) return;
  const bullets = (report.bullets || []).map((b) => `<li>${b}</li>`).join("");
  box.innerHTML = `
    <h4>Agent 解读 · ${report.headline || ""}</h4>
    <p style="margin:0.35rem 0;white-space:pre-line">${report.body || ""}</p>
    ${bullets ? `<ul class="agent-bullets">${bullets}</ul>` : ""}
    ${report.dual_pool_note ? `<p class="note" style="margin:0.5rem 0 0">${report.dual_pool_note}</p>` : ""}
  `;
  box.classList.remove("hidden");
}

async function loadAgentPresets() {
  try {
    const data = await api("/api/agent/presets");
    const sel = $("#agentPreset");
    if (!sel) return;
    const presets = data.presets || [];
    sel.innerHTML =
      '<option value="">自定义 / 自然语言</option>' +
      presets.map((p) => `<option value="${p.id}">${p.label}</option>`).join("");
  } catch {
    /* Agent 层未启动时静默 */
  }
}

function agentRequestBody() {
  return {
    text: $("#agentText")?.value?.trim() || null,
    preset_id: $("#agentPreset")?.value || null,
    mode: "mock",
  };
}

async function fetchAgentPlan() {
  const data = await api("/api/agent/plan", {
    method: "POST",
    body: JSON.stringify(agentRequestBody()),
  });
  state.agentPlan = data.plan;
  applyAgentPlanToForm(data.plan);
  renderAgentPlanPreview(data.plan);
  updateBacktestNarrative("parse");
  return data.plan;
}

async function interpretBacktestWithAgent(backtestData) {
  if (!backtestData || backtestData.status !== "success") return;
  try {
    const res = await api("/api/agent/interpret", {
      method: "POST",
      body: JSON.stringify({
        backtest: backtestData,
        plan: state.agentPlan,
        mode: "mock",
      }),
    });
    renderAgentReport(res.report);
  } catch (e) {
    appendBacktestLog(`Agent 解读跳过: ${e.message}`);
  }
}

async function runAgentPlanOnly() {
  const btn = $("#btnAgentPlan");
  setBusy(btn, true);
  try {
    await fetchAgentPlan();
    setBacktestStatus("Agent 已生成回测计划（未执行）。可点「Agent 规划并回测」或「实时回测」。", "ok");
  } catch (e) {
    setBacktestStatus(`Agent 规划失败：${e.message}`, "error");
  } finally {
    setBusy(btn, false);
  }
}

async function runAgentPlanAndBacktest() {
  const btn = $("#btnAgentRun");
  setBusy(btn, true);
  $("#agentReportPanel")?.classList.add("hidden");
  try {
    await fetchAgentPlan();
    await runHs300Backtest();
  } catch (e) {
    setBacktestStatus(`Agent 流程失败：${e.message}`, "error");
  } finally {
    setBusy(btn, false);
  }
}

function applyDemoReplay(replay) {
  if (!replay) return;
  if (!state.backtestLive) initBacktestLiveState();
  const live = state.backtestLive;
  live.stocks = replay.stocks ?? live.stocks;
  live.tradingDays = replay.trading_days ?? live.tradingDays;
  live.pipelineReturn = replay.pipeline_return ?? live.pipelineReturn;
  live.pipelineMonthly = replay.pipeline_monthly || live.pipelineMonthly;
  live.roleOrder = replay.role_order || live.roleOrder;
  for (const role of live.roleOrder) {
    const info = replay.roles?.[role] || {};
    live.roles[role] = {
      months: info.months || 0,
      sample: info.sample || [],
      sampleLabels: info.sample_labels || info.sample || [],
      done: info.done !== false,
    };
  }
  live.shapleyPoints = (replay.shapley_points || []).map((p) => ({
    index: p.index,
    y: p.y,
    size: (p.subset || []).length || 1,
    subset: p.subset || [],
    label: p.label,
    fullLabel: p.fullLabel,
  }));
  $("#backtestLivePanel").classList.remove("hidden");
  renderRoleFactorCards();
  updateRoleLiveChart();
  updateNavLiveChart();
  updateShapleyLiveChart();
  updateLiveMetrics();
}

async function fetchDemoPayloadStatic() {
  const res = await fetch("/static/demo/backtest_demo.json");
  if (!res.ok) throw new Error("离线演示包未找到");
  const data = await res.json();
  data._source = data._source || "demo";
  return data;
}

async function fetchDemoPayload() {
  try {
    const data = await api("/api/backtest/demo");
    data._source = data._source || "demo";
    return data;
  } catch {
    return fetchDemoPayloadStatic();
  }
}

function prepareBacktestUI() {
  clearBacktestTimer();
  state.backtestStreamPopulated = false;
  setBacktestRunning(true);
  switchToTab("backtest");
  $("#backtestConclusion")?.classList.remove("reveal-in");
  document.querySelectorAll(".backtest-tech-block").forEach((el) => {
    el.classList.remove("reveal-in", "backtest-tech-block");
  });
  $("#backtestOverview").classList.add("hidden");
  $("#backtestSummary").classList.add("hidden");
  $("#backtestConclusion")?.classList.add("hidden");
  $("#backtestTechDivider")?.classList.add("hidden");
  $("#backtestTable").innerHTML = "";
  resetBacktestProgressUI();
  $("#backtestStatus").classList.remove("hidden");
}

async function consumeBacktestStreamOrThrow(response) {
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    const detail = err.detail;
    const msg =
      typeof detail === "string"
        ? detail
        : detail?.error_message || response.statusText;
    throw new Error(msg || "回测请求失败");
  }
  const data = await consumeBacktestStream(response);
  if (!data) throw new Error("未收到完整回测结果");
  return data;
}

async function runBacktestStream(payload) {
  const res = await fetch("/api/backtest/run/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return consumeBacktestStreamOrThrow(res);
}

async function playClientDemoReplay(replay, pace = DEMO_REPLAY_PACE) {
  if (!replay) return;
  initBacktestLiveState();
  $("#backtestLivePanel").classList.remove("hidden");

  const stages = [
    ["parse", 8, "解析回测参数…"],
    ["init", 14, "加载沪深300行情与行业映射…"],
    ["factors", 28, "五类角色因子选股计算中…"],
    ["pipeline", 48, "多角色 Pipeline 组合回测…"],
    ["shapley", 72, "夏普利反事实对照实验…"],
    ["save", 92, "汇总贡献与生成报告…"],
  ];
  for (const [stage, pct, msg] of stages) {
    setBacktestProgress(pct, msg, stage);
    updateBacktestNarrative(stage);
    await sleep(pace.stage);
  }

  if (replay.stocks != null) {
    handleBacktestStreamEvent({
      type: "data_snapshot",
      stocks: replay.stocks,
      trading_days: replay.trading_days,
    });
    await sleep(pace.snapshot);
  }

  const roleOrder = replay.role_order || state.backtestLive?.roleOrder || [];
  for (let i = 0; i < roleOrder.length; i++) {
    const role = roleOrder[i];
    const info = replay.roles?.[role] || {};
    handleBacktestStreamEvent({
      type: "role_factor",
      role,
      months: info.months || 0,
      sample_stocks: info.sample || [],
      sample_labels: info.sample_labels || info.sample || [],
      percent: 22 + (i + 1) * 5,
    });
    await sleep(pace.role);
  }

  if (replay.pipeline_return != null) {
    await sleep(pace.pipeline * 0.35);
    handleBacktestStreamEvent({
      type: "pipeline",
      total_return: replay.pipeline_return,
      monthly: replay.pipeline_monthly || [],
      percent: 55,
    });
    await sleep(pace.pipeline);
  }

  const shapleyPts = replay.shapley_points || [];
  const total = Math.max(shapleyPts.length, 1);
  for (const pt of shapleyPts) {
    handleBacktestStreamEvent({
      type: "shapley",
      subset: pt.subset || [],
      subset_label: pt.label,
      subset_full: pt.fullLabel,
      subset_return: (pt.y || 0) / 100,
      current: pt.index,
      total,
      percent: 72 + Math.floor(((pt.index || 0) / total) * 18),
    });
    await sleep(pace.shapley);
  }

  setBacktestProgress(100, "计算完成，正在生成业务结论…", "complete");
  await sleep(900);
}

async function finalizeBacktestResults(data, { staged = false } = {}) {
  state.backtestResult = data;
  state.dualPoolConfirmed = false;
  if (state.agentPlan) {
    await interpretBacktestWithAgent(data);
  }

  const useStaged =
    staged || data._source === "demo" || data._source === "cache";

  if (!state.backtestStreamPopulated && data.demo_replay) {
    await playClientDemoReplay(data.demo_replay);
  }

  if (useStaged) {
    await sleep(900);
    renderBacktestConclusion(data, { showTechDivider: false });
    focusBacktestStage("complete");
    const conclusion = $("#backtestConclusion");
    conclusion?.classList.remove("reveal-in");
    void conclusion?.offsetWidth;
    conclusion?.classList.add("reveal-in");
    updateBacktestNarrative("complete");
    await sleep(1400);
    renderBacktestTechDetails(data);
    const techBlocks = document.querySelectorAll(".backtest-tech-block");
    techBlocks.forEach((el, i) => {
      setTimeout(() => el.classList.add("reveal-in"), i * 120);
    });
    renderDualPoolPanel();
  } else {
    renderHs300Backtest(data);
    renderDualPoolPanel();
  }
}

async function runBacktestDemo() {
  const btnDemo = $("#btnBacktestDemo");
  const btnLive = $("#btnBacktest");
  setBusy(btnDemo, true);
  setBusy(btnLive, true);
  prepareBacktestUI();
  updateBacktestNarrative("parse");
  setBacktestStatus("路演演示：加载官方预置结果…", "running");
  updateBacktestModeHint("路演模式");

  const started = Date.now();
  try {
    let data;
    try {
      data = await runBacktestStream({ demo_mode: true, query: {} });
    } catch (apiErr) {
      appendBacktestLog(`API 不可用，切换离线演示包：${apiErr.message}`);
      data = await fetchDemoPayloadStatic();
      await playClientDemoReplay(data.demo_replay);
    }
    const elapsed = ((Date.now() - started) / 1000).toFixed(1);
    setBacktestStatus(
      `${backtestSourceLabel(data)} · ${data.demo_label || data.query_summary || ""} · ${elapsed}s`,
      "ok"
    );
    await finalizeBacktestResults(data, { staged: true });
  } catch (e) {
    setBacktestProgress(0, "演示加载失败", "complete");
    setBacktestStatus(`演示失败：${e.message}`, "error");
    appendBacktestLog(`ERROR: ${e.message}`);
  } finally {
    setBusy(btnDemo, false);
    setBusy(btnLive, false);
    setBacktestRunning(false);
  }
}

async function runHs300Backtest() {
  const btn = $("#btnBacktest");
  const btnDemo = $("#btnBacktestDemo");
  setBusy(btn, true);
  setBusy(btnDemo, true);
  prepareBacktestUI();
  updateBacktestNarrative("parse");
  const useCache = $("#btUseCache")?.checked !== false;
  setBacktestStatus(
    useCache
      ? "实时回测进行中（相同参数将自动缓存）…"
      : "实时回测进行中（已关闭缓存，强制重算）…",
    "running"
  );
  updateBacktestModeHint(useCache ? "在线 · 可缓存" : "在线 · 强制重算");

  const started = Date.now();
  state.backtestTimer = setInterval(() => {
    const sec = Math.floor((Date.now() - started) / 1000);
    const cur = $("#backtestStageLabel").textContent;
    if (!cur.includes("已耗时")) {
      $("#backtestStageLabel").textContent = `${cur.replace(/ · 已耗时.*/, "")} · 已耗时 ${sec}s`;
    }
  }, 1000);

  const payload = buildBacktestPayload({
    use_cache: useCache,
    force_refresh: !useCache,
  });

  try {
    const data = await runBacktestStream(payload);
    clearBacktestTimer();
    const elapsed = Math.floor((Date.now() - started) / 1000);
    setBacktestProgress(100, "回测完成", "complete");
    const cacheNote = data._source === "cache" ? "（命中缓存）" : "";
    setBacktestStatus(
      `${backtestSourceLabel(data)}${cacheNote} · request_id=${data.request_id} · 耗时 ${elapsed}s`,
      "ok"
    );
    await finalizeBacktestResults(data);
  } catch (e) {
    clearBacktestTimer();
    setBacktestProgress(0, "回测失败", "complete");
    setBacktestStatus(`回测失败：${e.message}`, "error");
    appendBacktestLog(`ERROR: ${e.message}`);
  } finally {
    setBusy(btn, false);
    setBusy(btnDemo, false);
    setBacktestRunning(false);
  }
}

function renderBacktestTechDetails(data) {
  const results = data.results || {};
  const ov = results.overview || {};
  const breakdown = results.role_breakdown || [];
  const rec = results.recommendation || {};
  const highlights = results.highlights || [];

  $("#backtestOverview").innerHTML = `
    <div class="metric-card">
      <div class="label">组合收益</div>
      <div class="value">${((ov.total_return || 0) * 100).toFixed(2)}%</div>
      <div class="sub">${ov.total_return_desc || ""}</div>
    </div>
    <div class="metric-card">
      <div class="label">基准收益</div>
      <div class="value">${((ov.benchmark_return || 0) * 100).toFixed(2)}%</div>
      <div class="sub">${ov.benchmark_return_desc || ""}</div>
    </div>
    <div class="metric-card">
      <div class="label">超额收益</div>
      <div class="value">${((ov.excess_return || 0) * 100).toFixed(2)}%</div>
      <div class="sub">${ov.excess_return_desc || ""}</div>
    </div>
    <div class="metric-card">
      <div class="label">夏普 / 回撤</div>
      <div class="value">${(ov.sharpe_ratio || 0).toFixed(2)}</div>
      <div class="sub">${ov.sharpe_ratio_desc || ""} · ${ov.max_drawdown_desc || ""}</div>
    </div>
  `;
  $("#backtestOverview").classList.remove("hidden");
  $("#backtestOverview").classList.add("backtest-tech-block");

  const roles = breakdown.map((r) => r.role);
  const weights = breakdown.map((r) => (r.weight || 0) * 100);
  const shapleys = breakdown.map((r) => (r.shapley_raw || r.contribution_raw || 0) * 100);

  destroyChart("btWeight");
  const weightWrap = $("#backtestWeightChart")?.closest(".chart-wrap");
  weightWrap?.classList.add("backtest-tech-block");
  state.charts.btWeight = new Chart($("#backtestWeightChart"), {
    type: "bar",
    data: {
      labels: roles,
      datasets: [{
        label: "新池分配权重 %",
        data: weights,
        backgroundColor: roles.map((r) => roleColor(r, 1)),
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        title: { display: true, text: "各角色新池 40% 分配权重", color: CHART.ink },
      },
      scales: {
        x: { ticks: { color: CHART.muted }, grid: { color: CHART.grid } },
        y: { ticks: { color: CHART.muted, callback: (v) => v + "%" }, grid: { color: CHART.grid } },
      },
    },
  });

  destroyChart("btShapley");
  const shapleyWrap = $("#backtestShapleyChart")?.closest(".chart-wrap");
  shapleyWrap?.classList.add("backtest-tech-block");
  state.charts.btShapley = new Chart($("#backtestShapleyChart"), {
    type: "bar",
    data: {
      labels: roles,
      datasets: [{
        label: "夏普利边际贡献 %",
        data: shapleys,
        backgroundColor: roles.map((r, i) =>
          shapleys[i] >= 0 ? roleColor(r, 0.85) : "rgba(212,120,106,0.75)"
        ),
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        title: { display: true, text: "各角色夏普利边际贡献", color: CHART.ink },
      },
      scales: {
        x: { ticks: { color: CHART.muted }, grid: { color: CHART.grid } },
        y: { ticks: { color: CHART.muted, callback: (v) => v + "%" }, grid: { color: CHART.grid } },
      },
    },
  });

  const hl = highlights.map((h) => `<li>${h.text || h}</li>`).join("");
  $("#backtestSummary").innerHTML = `
    <h3>结论摘要</h3>
    <p><strong>${rec.summary || data.query_summary || ""}</strong></p>
    ${hl ? `<ul class="attr-experiments">${hl}</ul>` : ""}
    <p class="note">${ov.attribution_description || ""} · ${data.query_summary || ""}</p>
  `;
  $("#backtestSummary").classList.remove("hidden");
  $("#backtestSummary").classList.add("backtest-tech-block");

  const rows = breakdown
    .map(
      (r) => `<tr>
        <td>${r.role}${r.is_target ? " ★" : ""}</td>
        <td>${((r.weight || 0) * 100).toFixed(1)}%</td>
        <td>${((r.shapley_raw || 0) * 100).toFixed(2)}%</td>
        <td>${((r.contribution_relative || 0) * 100).toFixed(1)}%</td>
        <td>${r.highlight || ""}</td>
      </tr>`
    )
    .join("");
  $("#backtestTable").innerHTML = `
    <table>
      <thead>
        <tr>
          <th>角色</th><th>分配权重</th><th>夏普利</th><th>相对贡献</th><th>说明</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
  $("#backtestTable").classList.add("backtest-tech-block");
  const divider = $("#backtestTechDivider");
  if (divider) {
    divider.classList.remove("hidden");
    divider.classList.add("backtest-tech-block");
  }
}

function renderHs300Backtest(data) {
  renderBacktestConclusion(data);
  if (data.demo_replay && !state.backtestStreamPopulated) {
    applyDemoReplay(data.demo_replay);
  }
  renderBacktestTechDetails(data);
}

async function refreshSensitivity() {
  await loadTargetControls();
}

async function runAll() {
  const btn = $("#btnRunAll");
  setBusy(btn, true);
  try {
    switchToTab("backtest");
    await runBacktestDemo();
    switchToTab("negotiate");
    await runNegotiate();
  } finally {
    setBusy(btn, false);
  }
}

$("#btnNegotiate").addEventListener("click", runNegotiate);
$("#btnEvolution").addEventListener("click", () => runEvolution(100));
$("#btnCompare").addEventListener("click", () =>
  runEvolution(100).then(() => switchToTab("compare"))
);
$("#btnCalculate").addEventListener("click", runCalculate);
$("#btnRunAll").addEventListener("click", runAll);
$("#btnSensitivityReset")?.addEventListener("click", resetSensitivity);
$("#btnRebalance")?.addEventListener("click", playRebalance);
$("#btnAttribution")?.addEventListener("click", runAttribution);
$("#btnBacktest")?.addEventListener("click", () => {
  state.agentPlan = null;
  $("#agentPlanPreview")?.classList.add("hidden");
  runHs300Backtest();
});
$("#btnBacktestDemo")?.addEventListener("click", runBacktestDemo);
$("#btnAgentPlan")?.addEventListener("click", runAgentPlanOnly);
$("#btnAgentRun")?.addEventListener("click", runAgentPlanAndBacktest);
$("#btnThemeToggle")?.addEventListener("click", toggleTheme);
$("#btnDevMode")?.addEventListener("click", () => {
  document.documentElement.classList.toggle("dev-mode");
});

initTheme();
initStage3D();
checkHealth();
highlightDemoFlow("backtest");
switchToTab("backtest");
loadBacktestMeta();
loadAgentPresets();
loadScenarioList()
  .then(() => Promise.all([runCalculate(), loadTargetControls()]))
  .catch(() => {
    runCalculate();
    loadTargetControls();
  });
