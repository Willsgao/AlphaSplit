/* AlphaSplit frontend */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

const state = {
  evolution: null,
  formula: null,
  charts: {},
};

const SPEAKER_CLASS = {
  李量化: "li",
  张经理: "zhang",
  陈经理: "chen",
  周总监: "arbiter",
};

function money(n) {
  return "¥" + Number(n).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

function pct(n) {
  return (Number(n) * 100).toFixed(1) + "%";
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

/* Tabs */
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
    badge.textContent = `mode: ${h.mode}`;
    badge.classList.add("ok");
  } catch {
    $("#healthBadge").textContent = "offline";
  }
}

/* Negotiate */
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

async function runNegotiate() {
  const btn = $("#btnNegotiate");
  setBusy(btn, true);
  const chat = $("#chatStream");
  const settle = $("#settlement");
  chat.innerHTML = "";
  settle.classList.add("hidden");

  try {
    const data = await api("/api/negotiate", {
      method: "POST",
      body: JSON.stringify({ scenario: "quant_fund", mode: "mock" }),
    });

    for (const round of data.rounds) {
      const label = document.createElement("div");
      label.className = "round-label";
      label.textContent = `Round ${round.round} · ${round.phase} · consensus ${(round.consensus * 100).toFixed(0)}%`;
      chat.appendChild(label);
      for (const u of round.utterances) {
        chat.appendChild(renderUtterance(u));
        chat.scrollTop = chat.scrollHeight;
        await new Promise((r) => setTimeout(r, 280));
      }
    }

    const arb = renderUtterance({
      speaker: data.arbiter.name,
      role: data.arbiter.role,
      text: data.arbiter_statement,
    });
    chat.appendChild(arb);
    chat.scrollTop = chat.scrollHeight;

    const items = Object.entries(data.settlement)
      .map(
        ([name, s]) => `
      <div class="settle-item">
        <div class="name">${name}</div>
        <div class="amt">${money(s.amount)}</div>
        <div class="sub">终裁份额 ${pct(s.final_share)} · 协商意向 ${pct(s.negotiated_share)}</div>
      </div>`
      )
      .join("");

    settle.innerHTML = `
      <h3>落账结果 · 可分配池 ${money(data.distributable)}</h3>
      <div class="settle-grid">${items}</div>
      <p class="note" style="margin-top:0.75rem">平台扣除 ${money(data.platform_profit)} · 模式 ${data.mode}</p>
    `;
    settle.classList.remove("hidden");
  } catch (e) {
    chat.innerHTML = `<div class="bubble arbiter"><div class="text">协商失败：${e.message}</div></div>`;
  } finally {
    setBusy(btn, false);
  }
}

/* Evolution + Compare */
function destroyChart(key) {
  if (state.charts[key]) {
    state.charts[key].destroy();
    delete state.charts[key];
  }
}

const GROUP_COLORS = {
  kpi: "#d4786a",
  formula: "#5b8def",
  agent: "#3d9a7a",
};
const GROUP_LABELS = {
  kpi: "KPI 基线",
  formula: "纯公式",
  agent: "Agent+公式",
};

async function runEvolution(rounds = 100) {
  const btn = $("#btnEvolution");
  setBusy(btn, true);
  try {
    const data = await api("/api/evolution", {
      method: "POST",
      body: JSON.stringify({ scenario: "quant_fund", rounds, seed: 42 }),
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
        x: {
          ticks: { color: "#8b9bb0", maxTicksLimit: 10 },
          grid: { color: "rgba(255,255,255,0.04)" },
        },
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

/* Formula */
async function runCalculate() {
  const btn = $("#btnCalculate");
  setBusy(btn, true);
  try {
    const data = await api("/api/calculate", {
      method: "POST",
      body: JSON.stringify({ scenario: "quant_fund" }),
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
      <p class="note">${data.formula} · 可分配 ${money(data.distributable)} · 平台 ${money(data.platform_profit)}</p>
      <table>
        <thead>
          <tr>
            <th>姓名</th><th>工时</th><th>Impact</th><th>复杂度</th>
            <th>稀缺</th><th>复用</th><th>贡献值</th><th>份额</th><th>金额</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>`;
  } finally {
    setBusy(btn, false);
  }
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
    await runEvolution(100);
  } finally {
    setBusy(btn, false);
  }
}

$("#btnNegotiate").addEventListener("click", runNegotiate);
$("#btnEvolution").addEventListener("click", () => runEvolution(100));
$("#btnCompare").addEventListener("click", () => runEvolution(100).then(() => {
  $$(".tab").forEach((b) => b.classList.remove("active"));
  $$(".panel").forEach((p) => p.classList.remove("active"));
  $$('.tab[data-tab="compare"]').classList.add("active");
  $("#panel-compare").classList.add("active");
}));
$("#btnCalculate").addEventListener("click", runCalculate);
$("#btnRunAll").addEventListener("click", runAll);

checkHealth();
runCalculate();
