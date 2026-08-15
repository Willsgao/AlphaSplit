/* AlphaSplit frontend — 场景切换 + 人工确认 */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

const state = {
  scenario: "quant_fund",
  evolution: null,
  formula: null,
  negotiate: null,
  charts: {},
};

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

$$(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab").forEach((b) => b.classList.remove("active"));
    $$(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#panel-${btn.dataset.tab}`).classList.add("active");
  });
});

function setBusy(btn, busy) {
  if (!btn) return;
  btn.disabled = !!busy;
}

async function checkHealth() {
  try {
    const h = await api("/api/health");
    const badge = $("#healthBadge");
    badge.textContent = `v${h.version} · ${h.mode}`;
    badge.classList.add("ok");
  } catch {
    $("#healthBadge").textContent = "offline";
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
  const items = Object.entries(data.settlement)
    .map(([name, s]) => {
      const status = s.in_band === false ? "越界" : "带宽内";
      return `
      <div class="settle-item">
        <div class="name">${name}</div>
        <div class="amt">${money(s.amount)}</div>
        <div class="sub">
          建议 ${pct(s.proposed_share ?? s.final_share)} · 锚点 ${pct(s.formula_share)}
          · 带宽 ${pct(s.band_low)}–${pct(s.band_high)} · ${status}
        </div>
      </div>`;
    })
    .join("");

  settle.innerHTML = `
    <h3>系统建议案 · 可分配池 ${money(data.distributable)} · 带宽 ±${(band * 100).toFixed(0)}%</h3>
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

  const result = await api("/api/confirm", {
    method: "POST",
    body: JSON.stringify({
      scenario: currentScenario(),
      shares,
      negotiated,
      proposed,
      allow_outside_band: $("#allowOutside")?.checked || false,
    }),
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

  try {
    const data = await api("/api/negotiate", {
      method: "POST",
      body: JSON.stringify({ scenario: currentScenario(), mode: "mock" }),
    });
    state.negotiate = data;
    $("#heroDesc").textContent = `${data.framework || ""} · 当前场景：${data.scenario}`;

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
        legend: { labels: { color: "#8b9bb0" } },
        title: { display: true, text: `${data.rounds} 轮均值对照`, color: "#e8eef6" },
      },
      scales: {
        x: { ticks: { color: "#8b9bb0" }, grid: { color: "rgba(255,255,255,0.05)" } },
        y: { min: 0, max: 1, ticks: { color: "#8b9bb0" }, grid: { color: "rgba(255,255,255,0.05)" } },
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
        legend: { labels: { color: "#8b9bb0" } },
        title: { display: true, text: title, color: "#e8eef6" },
      },
      scales: {
        x: { ticks: { color: "#8b9bb0", maxTicksLimit: 10 }, grid: { color: "rgba(255,255,255,0.04)" } },
        y: { ticks: { color: "#8b9bb0" }, grid: { color: "rgba(255,255,255,0.04)" } },
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
        legend: { labels: { color: "#8b9bb0" } },
        title: { display: true, text: "三因素贡献比重", color: "#e8eef6" },
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
        legend: { labels: { color: "#8b9bb0" } },
        title: { display: true, text: "写入 Impact 锚点后的分配变化", color: "#e8eef6" },
      },
      scales: {
        x: { ticks: { color: "#8b9bb0" }, grid: { color: "rgba(255,255,255,0.05)" } },
        y: { ticks: { color: "#8b9bb0", callback: (v) => v + "%" }, grid: { color: "rgba(255,255,255,0.05)" } },
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
        title: { display: true, text: title, color: "#e8eef6" },
      },
      scales: {
        x: { ticks: { color: "#8b9bb0" }, grid: { color: "rgba(255,255,255,0.05)" } },
        y: {
          min: 0,
          max: 70,
          ticks: { color: "#8b9bb0", callback: (v) => v + "%" },
          grid: { color: "rgba(255,255,255,0.05)" },
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
          legend: { labels: { color: "#8b9bb0" } },
          title: {
            display: true,
            text: "参考：份额随因子权重 w 的可行域",
            color: "#e8eef6",
          },
        },
        scales: {
          x: {
            title: { display: true, text: "因子权重 w", color: "#8b9bb0" },
            ticks: { color: "#8b9bb0" },
            grid: { color: "rgba(255,255,255,0.04)" },
          },
          y: {
            title: { display: true, text: "份额 %", color: "#8b9bb0" },
            ticks: { color: "#8b9bb0" },
            grid: { color: "rgba(255,255,255,0.04)" },
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

async function refreshSensitivity() {
  await loadTargetControls();
}

async function runAll() {
  const btn = $("#btnRunAll");
  setBusy(btn, true);
  try {
    $$(".tab").forEach((b) => b.classList.remove("active"));
    $$(".panel").forEach((p) => p.classList.remove("active"));
    $$('.tab[data-tab="negotiate"]').classList.add("active");
    $("#panel-negotiate").classList.add("active");
    await runNegotiate();
    await runCalculate();
    await loadTargetControls();
    await runEvolution(100);
  } finally {
    setBusy(btn, false);
  }
}

$("#btnNegotiate").addEventListener("click", runNegotiate);
$("#btnEvolution").addEventListener("click", () => runEvolution(100));
$("#btnCompare").addEventListener("click", () =>
  runEvolution(100).then(() => {
    $$(".tab").forEach((b) => b.classList.remove("active"));
    $$(".panel").forEach((p) => p.classList.remove("active"));
    $$('.tab[data-tab="compare"]').classList.add("active");
    $("#panel-compare").classList.add("active");
  })
);
$("#btnCalculate").addEventListener("click", runCalculate);
$("#btnRunAll").addEventListener("click", runAll);
$("#btnSensitivityReset")?.addEventListener("click", resetSensitivity);
$("#btnRebalance")?.addEventListener("click", playRebalance);
$("#btnAttribution")?.addEventListener("click", runAttribution);

checkHealth();
loadScenarioList()
  .then(() => Promise.all([runCalculate(), loadTargetControls()]))
  .catch(() => {
    runCalculate();
    loadTargetControls();
  });
