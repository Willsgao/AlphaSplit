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
  backtestComparison: null,
  agentEvidence: [],
  agentTrust: null,
  factorConfigMeta: null,
  factorConfig: null,
  factorConfigProposal: null,
  factorDefaultConfig: null,
  factorConversation: [],
  factorPreferences: {
    risk_level: "稳健",
    objectives: ["控制回撤"],
    focus_roles: ["风控分析师"],
  },
  factorConfigAudit: null,
  agentPlan: null,
  dualPoolAmount: 10_000_000,
  dualPoolBaseline: null,
  dualPoolConfirmed: false,
  backtestTimer: null,
  backtestFocusTimer: null,
  backtestStreamPopulated: false,
  roadshowMode: false,
  guidedStage: "preferences",
  guidedMaxStep: 1,
};

if ("scrollRestoration" in history) history.scrollRestoration = "manual";

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

/** 原生 Canvas 图表，避免在竞赛提交包中附带公共类库代码。 */
function destroyChart(key) {
  const chart = state.charts[key];
  if (chart) {
    chart.dispose();
    delete state.charts[key];
  }
  if (state.chartOptions) delete state.chartOptions[key];
}

function chartValue(item) {
  const value = item && typeof item === "object" ? item.value : item;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function chartColor(series, item, fallbackIndex = 0) {
  return item?.itemStyle?.color || series?.itemStyle?.color || series?.lineStyle?.color ||
    SENS_COLORS?.[fallbackIndex % SENS_COLORS.length] || "#5b8def";
}

function drawChartText(ctx, text, x, y, options = {}) {
  ctx.save();
  ctx.fillStyle = options.color || CHART.muted;
  ctx.font = `${options.weight || 400} ${options.size || 11}px "Noto Sans SC", "Segoe UI", sans-serif`;
  ctx.textAlign = options.align || "center";
  ctx.textBaseline = options.baseline || "middle";
  if (options.rotate) {
    ctx.translate(x, y);
    ctx.rotate(options.rotate);
    ctx.fillText(String(text), 0, 0, options.maxWidth);
  } else {
    ctx.fillText(String(text), x, y, options.maxWidth);
  }
  ctx.restore();
}

class NativeCanvasChart {
  constructor(element) {
    this.element = element;
    this.canvas = document.createElement("canvas");
    this.canvas.className = "native-chart-canvas";
    this.canvas.setAttribute("aria-hidden", "true");
    this.tooltip = document.createElement("div");
    this.tooltip.className = "native-chart-tooltip hidden";
    this.element.replaceChildren(this.canvas, this.tooltip);
    this.context = this.canvas.getContext("2d");
    this.disposed = false;
    this.hitColumns = [];
    this.onMove = (event) => this.showTooltip(event);
    this.onLeave = () => this.tooltip.classList.add("hidden");
    this.canvas.addEventListener("mousemove", this.onMove);
    this.canvas.addEventListener("mouseleave", this.onLeave);
  }

  getDom() { return this.element; }
  isDisposed() { return this.disposed; }

  setOption(option) {
    this.option = option || {};
    this.resize();
  }

  resize() {
    if (this.disposed || !this.option) return;
    const width = Math.max(280, this.element.clientWidth || 640);
    const height = Math.max(180, this.element.clientHeight || 280);
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    this.canvas.style.width = `${width}px`;
    this.canvas.style.height = `${height}px`;
    this.canvas.width = Math.round(width * ratio);
    this.canvas.height = Math.round(height * ratio);
    this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.draw(width, height);
  }

  dispose() {
    this.disposed = true;
    this.canvas.removeEventListener("mousemove", this.onMove);
    this.canvas.removeEventListener("mouseleave", this.onLeave);
    this.element.replaceChildren();
  }

  draw(width, height) {
    const ctx = this.context;
    ctx.clearRect(0, 0, width, height);
    this.hitColumns = [];
    if (this.option.title?.text) {
      drawChartText(ctx, this.option.title.text, width / 2, 17, {
        color: this.option.title.textStyle?.color || CHART.ink,
        size: this.option.title.textStyle?.fontSize || 13,
        weight: 600,
        maxWidth: width - 24,
      });
    }
    if (this.option.series?.[0]?.type === "pie") {
      this.drawPie(width, height);
    } else {
      this.drawCartesian(width, height);
    }
  }

  legendItems() {
    const configured = this.option.legend?.data;
    const series = this.option.series || [];
    if (configured?.length) {
      return configured.map((name, index) => {
        const item = series.find((entry) => entry.name === name) || series[index];
        return { name, color: chartColor(item, null, index) };
      });
    }
    if (series.length === 1 && series[0].type === "pie") {
      return (series[0].data || []).map((item, index) => ({
        name: item.name,
        color: chartColor(series[0], item, index),
      }));
    }
    return series.filter((item) => item.name).map((item, index) => ({
      name: item.name,
      color: chartColor(item, null, index),
    }));
  }

  drawLegend(width, height) {
    const items = this.legendItems();
    if (!items.length || !this.option.legend) return;
    const top = this.option.legend.top !== undefined;
    const y = top ? 17 : height - 14;
    const itemWidth = Math.min(150, Math.max(70, width / items.length));
    const start = Math.max(12, (width - itemWidth * items.length) / 2);
    items.forEach((item, index) => {
      const x = start + itemWidth * index;
      this.context.fillStyle = item.color;
      this.context.fillRect(x, y - 4, 12, 8);
      drawChartText(this.context, item.name, x + 17, y, {
        align: "left", size: 10, color: CHART.muted, maxWidth: itemWidth - 20,
      });
    });
  }

  drawPie(width, height) {
    const series = this.option.series[0];
    const data = series.data || [];
    const total = data.reduce((sum, item) => sum + Math.max(0, chartValue(item) || 0), 0) || 1;
    const cx = width / 2;
    const cy = height / 2 - 4;
    const outer = Math.min(width, height) * 0.27;
    const inner = outer * 0.58;
    let angle = -Math.PI / 2;
    data.forEach((item, index) => {
      const next = angle + (Math.max(0, chartValue(item) || 0) / total) * Math.PI * 2;
      this.context.beginPath();
      this.context.arc(cx, cy, outer, angle, next);
      this.context.arc(cx, cy, inner, next, angle, true);
      this.context.closePath();
      this.context.fillStyle = chartColor(series, item, index);
      this.context.fill();
      angle = next;
    });
    drawChartText(this.context, "100%", cx, cy, { color: CHART.ink, size: 15, weight: 600 });
    this.drawLegend(width, height);
  }

  drawCartesian(width, height) {
    const option = this.option;
    let labels = [...(option.xAxis?.data || [])];
    let series = (option.series || []).map((entry) => ({ ...entry, data: [...(entry.data || [])] }));
    const zoom = Array.isArray(option.dataZoom) ? option.dataZoom[0] : null;
    if (zoom && labels.length > 8) {
      const start = Math.max(0, Math.floor(labels.length * Number(zoom.start || 0) / 100));
      labels = labels.slice(start);
      series = series.map((entry) => ({ ...entry, data: entry.data.slice(start) }));
    }
    const grid = option.grid || {};
    const left = Number(grid.left) || 48;
    const right = Number(grid.right) || 16;
    const top = Number(grid.top) || (option.title ? 40 : 16);
    const bottom = Number(grid.bottom) || (option.legend ? 48 : 32);
    const plotWidth = Math.max(10, width - left - right);
    const plotHeight = Math.max(10, height - top - bottom);
    const values = series.flatMap((entry) => entry.data.map(chartValue)).filter((value) => value !== null);
    let min = Number.isFinite(Number(option.yAxis?.min)) ? Number(option.yAxis.min) : Math.min(0, ...values);
    let max = Number.isFinite(Number(option.yAxis?.max)) ? Number(option.yAxis.max) : Math.max(0, ...values);
    if (min === max) { min -= 1; max += 1; }
    if (!Number.isFinite(min) || !Number.isFinite(max)) { min = 0; max = 1; }
    if (option.yAxis?.min === undefined && min < 0) min *= 1.12;
    if (option.yAxis?.max === undefined && max > 0) max *= 1.12;
    const yFor = (value) => top + ((max - value) / (max - min)) * plotHeight;
    const percentAxis = String(option.yAxis?.axisLabel?.formatter || "").includes("%");
    for (let tick = 0; tick <= 4; tick += 1) {
      const value = min + ((max - min) * tick) / 4;
      const y = yFor(value);
      this.context.strokeStyle = CHART.grid;
      this.context.lineWidth = 1;
      this.context.beginPath();
      this.context.moveTo(left, y);
      this.context.lineTo(width - right, y);
      this.context.stroke();
      drawChartText(this.context, `${value.toFixed(Math.abs(max - min) < 5 ? 1 : 0)}${percentAxis ? "%" : ""}`, left - 7, y, {
        align: "right", color: CHART.muted, size: 9,
      });
    }
    const step = plotWidth / Math.max(1, labels.length);
    const barSeries = series.filter((entry) => entry.type === "bar");
    const lineSeries = series.filter((entry) => entry.type === "line");
    const zeroY = yFor(Math.max(min, Math.min(max, 0)));
    labels.forEach((label, index) => {
      const x = left + step * (index + 0.5);
      const every = Math.max(1, Math.ceil(labels.length / Math.max(5, Math.floor(plotWidth / 70))));
      if (index % every === 0 || index === labels.length - 1) {
        drawChartText(this.context, label, x, height - bottom + 13, {
          color: CHART.muted,
          size: option.xAxis?.axisLabel?.fontSize || 9,
          rotate: option.xAxis?.axisLabel?.rotate ? -Math.PI / 5 : 0,
          maxWidth: Math.max(42, step * every - 4),
        });
      }
      if (barSeries.length) {
        const groupWidth = Math.min(step * 0.72, barSeries.length * 40);
        const barWidth = Math.max(2, groupWidth / barSeries.length - 2);
        barSeries.forEach((entry, seriesIndex) => {
          const value = chartValue(entry.data[index]);
          if (value === null) return;
          const y = yFor(value);
          const x0 = x - groupWidth / 2 + seriesIndex * (groupWidth / barSeries.length) + 1;
          this.context.fillStyle = chartColor(entry, entry.data[index], seriesIndex);
          this.context.fillRect(x0, Math.min(y, zeroY), barWidth, Math.max(1, Math.abs(zeroY - y)));
        });
      }
      this.hitColumns.push({ x0: left + step * index, x1: left + step * (index + 1), index, label, series });
    });
    lineSeries.forEach((entry, seriesIndex) => {
      const color = chartColor(entry, null, seriesIndex);
      this.context.strokeStyle = color;
      this.context.lineWidth = entry.lineStyle?.width || 2;
      this.context.setLineDash(entry.lineStyle?.type === "dashed" ? [6, 5] : []);
      this.context.beginPath();
      let started = false;
      entry.data.forEach((item, index) => {
        const value = chartValue(item);
        if (value === null) return;
        const x = left + step * (index + 0.5);
        const y = yFor(value);
        if (!started) { this.context.moveTo(x, y); started = true; }
        else this.context.lineTo(x, y);
      });
      this.context.stroke();
      this.context.setLineDash([]);
      if (entry.showSymbol) {
        entry.data.forEach((item, index) => {
          const value = chartValue(item);
          if (value === null) return;
          this.context.beginPath();
          this.context.arc(left + step * (index + 0.5), yFor(value), (entry.symbolSize || 5) / 2, 0, Math.PI * 2);
          this.context.fillStyle = color;
          this.context.fill();
        });
      }
    });
    this.drawLegend(width, height);
  }

  showTooltip(event) {
    if (!this.hitColumns.length) return;
    const rect = this.canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const hit = this.hitColumns.find((column) => x >= column.x0 && x <= column.x1);
    if (!hit) { this.tooltip.classList.add("hidden"); return; }
    const lines = hit.series.map((entry) => {
      const value = chartValue(entry.data[hit.index]);
      return value === null ? "" : `${entry.name || "数值"}: ${value.toFixed(2)}`;
    }).filter(Boolean);
    this.tooltip.textContent = [hit.label, ...lines].join("\n");
    this.tooltip.style.left = `${Math.min(rect.width - 170, Math.max(8, x + 12))}px`;
    this.tooltip.style.top = `${Math.max(8, event.clientY - rect.top - 20)}px`;
    this.tooltip.classList.remove("hidden");
  }
}

function setEChart(key, selector, option) {
  const el = typeof selector === "string" ? $(selector) : selector;
  if (!el) return null;
  let chart = state.charts[key];
  if (!chart || chart.isDisposed() || chart.getDom() !== el) {
    if (chart && !chart.isDisposed()) chart.dispose();
    chart = new NativeCanvasChart(el);
    state.charts[key] = chart;
  }
  if (!state.chartOptions) state.chartOptions = {};
  state.chartOptions[key] = option;
  chart.setOption(option);
  return chart;
}

function ecAxis(extra = {}) {
  return {
    axisLabel: { color: CHART.muted, fontSize: 11 },
    axisLine: { lineStyle: { color: CHART.grid } },
    splitLine: { show: true, lineStyle: { color: CHART.grid } },
    ...extra,
  };
}

function applyThemeToCharts() {
  refreshChartTheme();
  try {
    if (state.backtestLive) {
      updateRoleLiveChart();
      updateNavLiveChart();
      if (state.backtestLive.shapleyPoints?.length) updateShapleyLiveChart();
    }
    if (state.backtestResult) renderBacktestTechDetails(state.backtestResult);
    if (state.backtestComparison) renderPlanComparisonChart(state.backtestComparison);
    if (state.evolution) {
      renderCompare(state.evolution);
      renderEvolutionCharts(state.evolution);
    }
    if (state.attribution) renderAttribution(state.attribution);
  } catch (_) {
    /* 初始化阶段部分 renderer 尚未就绪 */
  }
  Object.values(state.charts || {}).forEach((c) => c?.resize?.());
}

const THEMES = ["dark", "roadshow", "warm"];
const THEME_LABELS = { dark: "科技深色", roadshow: "路演白", warm: "暖沙色" };

function currentTheme() {
  return document.documentElement.getAttribute("data-theme") || "dark";
}

function setTheme(theme) {
  const next = THEMES.includes(theme) ? theme : "dark";
  document.documentElement.setAttribute("data-theme", next);
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
  document.documentElement.setAttribute("data-theme", "dark");
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

function animateNumber(el, toValue, opts = {}) {
  if (!el) return;
  const duration = opts.duration ?? 900;
  const decimals = opts.decimals ?? 2;
  const prefix = opts.prefix ?? "";
  const suffix = opts.suffix ?? "";
  const from = Number(opts.from ?? 0);
  const fmt = (v) => `${prefix}${v.toFixed(decimals)}${suffix}`;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    el.textContent = fmt(toValue);
    return;
  }
  const start = performance.now();
  const tick = (now) => {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = fmt(from + (toValue - from) * eased);
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
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
    excessEl.classList.toggle("positive", excess > 0);
    excessEl.classList.toggle("negative", excess < 0);
    animateNumber(excessEl, excess, {
      decimals: 2,
      prefix: excess >= 0 ? "+" : "",
      suffix: "%",
      from: 0,
    });
  }
  const excessSub = $("#kpiExcessSub");
  if (excessSub) excessSub.textContent = ov.excess_return_desc || "相对沪深300";
  const sharpeEl = $("#kpiSharpe");
  if (sharpeEl) animateNumber(sharpeEl, ov.sharpe_ratio ?? 0, { decimals: 2 });
  const sharpeSub = $("#kpiSharpeSub");
  if (sharpeSub) sharpeSub.textContent = ov.sharpe_ratio_desc || "年化夏普";
  const dd = Math.abs(ov.max_drawdown || 0) * 100;
  const ddEl = $("#kpiDrawdown");
  if (ddEl) animateNumber(ddEl, dd, { decimals: 2, prefix: "-", suffix: "%" });
  const ddSub = $("#kpiDrawdownSub");
  if (ddSub) ddSub.textContent = ov.max_drawdown_desc || "最大回撤";
  const top = breakdown[0];
  const policy = data.results.allocation_policy || {};
  const roleEl = $("#kpiTopRole");
  const roleSub = $("#kpiTopRoleSub");
  if (top && roleEl) {
    roleEl.textContent = (top.role || "").replace("分析师", "");
    if (roleSub) {
      const relaxed = policy.cap_relaxed ? " · 上限已透明放宽" : "";
      roleSub.textContent = `证据轨建议权重 ${((top.weight || 0) * 100).toFixed(1)}%${relaxed}`;
    }
  }
}

function updateShapleyRing(done = 0, total = 31) {
  const n = Math.max(0, Math.min(total, Number(done) || 0));
  const pct = total ? (n / total) * 100 : 0;
  const arc = $("#shapleyRingArc");
  if (arc) arc.setAttribute("stroke-dasharray", `${pct.toFixed(2)}, 100`);
  const count = $("#shapleyRingCount");
  if (count) count.textContent = String(n);
  const mini = $("#shapleyMiniCount");
  if (mini) mini.textContent = `联盟 ${n}/${total}`;
}

const SPEAKER_CLASS = {
  周总监: "arbiter",
};

function money(n) {
  return Number(n).toLocaleString("zh-CN", { maximumFractionDigits: 0 }) + " 单位";
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

function cloneJson(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** 页面数值统一解释层：指标旁仅保留信息按钮，完整依据在抽屉展示。 */
const metricExplanations = new Map();
let metricExplanationSerial = 0;
let metricExplanationTrigger = null;

function finiteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function percentText(value, decimals = 2, signed = false) {
  const number = finiteNumber(value);
  const sign = signed && number > 0 ? "+" : "";
  return `${sign}${(number * 100).toFixed(decimals)}%`;
}

function explainButton(explanation, options = {}) {
  const id = `metric-explain-${++metricExplanationSerial}`;
  metricExplanations.set(id, explanation);
  const compact = options.compact === false ? "" : " compact";
  const extraClass = options.className ? ` ${escapeHtml(options.className)}` : "";
  const label = options.label || `查看${explanation.title || "该数据"}依据`;
  return `<button type="button" class="metric-info-button${compact}${extraClass}" data-explain-id="${id}" aria-label="${escapeHtml(label)}" title="查看数据依据">i</button>`;
}

function setChartExplanation(container, explanation) {
  if (!container) return;
  container.querySelector(".chart-explain-button")?.remove();
  container.insertAdjacentHTML("afterbegin", explainButton(explanation, {
    className: "chart-explain-button",
    label: `查看${explanation.title}口径`,
  }));
}

function evidenceForPath(sourcePath) {
  return (state.agentEvidence || []).find((item) => item.source_path === sourcePath) || null;
}

function backtestTrace(data = state.backtestResult) {
  const config = data?.results?.factor_config || state.factorConfig || {};
  return {
    scope: data?.query_summary || "等待回测后生成区间与筛选口径",
    benchmark: data?.results?.filter_detail?.benchmark === "hs300" ? "沪深300" : "沪深300",
    requestId: data?.request_id || "—",
    configId: config.config_id || "默认/未记录",
  };
}

function explanationSection(title, value, className = "") {
  if (value == null || value === "") return "";
  return `<section class="metric-explain-section${className ? ` ${className}` : ""}"><h3>${escapeHtml(title)}</h3><p>${escapeHtml(value)}</p></section>`;
}

function openMetricExplanation(explanation, trigger = null) {
  if (!explanation) return;
  const overlay = $("#metricExplainOverlay");
  const title = $("#metricExplainTitle");
  const body = $("#metricExplainBody");
  if (!overlay || !title || !body) return;
  metricExplanationTrigger = trigger || document.activeElement;
  title.textContent = explanation.title || "指标解释";
  const traceRows = [
    ["时间/范围", explanation.scope],
    ["对照基准", explanation.benchmark],
    ["数据字段", explanation.sourcePath],
    ["证据编号", explanation.evidenceId],
    ["请求编号", explanation.requestId],
    ["配置编号", explanation.configId],
  ].filter(([, value]) => value != null && value !== "");
  body.innerHTML = `
    <div class="metric-explain-current"><span>当前显示值</span><strong>${escapeHtml(explanation.current ?? "—")}</strong></div>
    ${explanationSection("定义", explanation.definition)}
    ${explanationSection("计算公式", explanation.formula, "metric-explain-formula")}
    ${explanationSection("本次代入", explanation.calculation)}
    ${traceRows.length ? `<section class="metric-explain-section"><h3>追溯信息</h3><dl class="metric-explain-trace">${traceRows.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl></section>` : ""}
    ${explanationSection("使用边界", explanation.limitation || "历史回测与归因结果仅用于决策支持，不构成收益承诺；最终方案须经评审委员会（或机构治理责任人）确认。", "metric-explain-warning")}
  `;
  overlay.classList.remove("hidden");
  overlay.setAttribute("aria-hidden", "false");
  document.body.classList.add("metric-explain-open");
  $("#btnMetricExplainClose")?.focus();
}

function closeMetricExplanation() {
  const overlay = $("#metricExplainOverlay");
  if (!overlay || overlay.classList.contains("hidden")) return;
  overlay.classList.add("hidden");
  overlay.setAttribute("aria-hidden", "true");
  document.body.classList.remove("metric-explain-open");
  metricExplanationTrigger?.focus?.();
  metricExplanationTrigger = null;
}

function buildOverviewExplanation(metric, data = state.backtestResult) {
  const ov = data?.results?.overview || {};
  if (!data?.results?.overview || !(metric in ov)) {
    const labels = {
      total_return: "组合累计收益",
      benchmark_return: "沪深300累计收益",
      excess_return: "区间超额收益",
      sharpe_ratio: "年化夏普比率",
      max_drawdown: "最大回撤",
    };
    return {
      title: labels[metric] || metric,
      current: "等待回测",
      definition: "完成回测后显示当前值、实际代入过程和可追溯证据。",
      scope: "尚未生成回测结果",
      benchmark: "沪深300",
      sourcePath: `results.overview.${metric}`,
      evidenceId: "回测完成并经Agent校验后生成",
      configId: state.factorConfig?.config_id || "默认/未记录",
    };
  }
  const series = data?.results?.time_series || [];
  const trace = backtestTrace(data);
  const path = `results.overview.${metric}`;
  const evidence = evidenceForPath(path);
  const total = finiteNumber(ov.total_return);
  const benchmarkReturn = finiteNumber(ov.benchmark_return);
  const n = series.length;
  const annReturn = n ? (1 + total) ** (12 / n) - 1 : 0;
  const returns = series.map((row) => Number(row.return)).filter(Number.isFinite);
  const mean = returns.length ? returns.reduce((sum, value) => sum + value, 0) / returns.length : 0;
  const variance = returns.length > 1
    ? returns.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (returns.length - 1)
    : 0;
  const annVol = Math.sqrt(variance) * Math.sqrt(12);
  const common = { ...trace, sourcePath: path, evidenceId: evidence?.id || "回测完成并经 Agent 校验后生成" };
  const definitions = {
    total_return: {
      title: "组合累计收益",
      current: percentText(total),
      definition: "各回测期组合收益连续复利后的区间收益。月末信号用于下一期持仓。",
      formula: "R组合 = ∏(1 + rₜ) - 1",
      calculation: `${n}期月度收益连续复利 = ${percentText(total)}`,
    },
    benchmark_return: {
      title: "沪深300累计收益",
      current: percentText(benchmarkReturn),
      definition: "与客户组合完全相同区间内，沪深300各期收益连续复利的结果。",
      formula: "R基准 = ∏(1 + r沪深300,ₜ) - 1",
      calculation: `${n}期沪深300收益连续复利 = ${percentText(benchmarkReturn)}`,
    },
    excess_return: {
      title: "区间超额收益",
      current: percentText(ov.excess_return, 2, true),
      definition: "组合累计收益相对同期沪深300累计收益的算术差。",
      formula: "超额收益 = 组合累计收益 - 沪深300累计收益",
      calculation: `${percentText(total)} - ${percentText(benchmarkReturn)} = ${percentText(ov.excess_return, 2, true)}`,
    },
    sharpe_ratio: {
      title: "年化夏普比率",
      current: finiteNumber(ov.sharpe_ratio).toFixed(2),
      definition: "组合年化收益超过2%年化无风险利率的部分，相对于年化波动率的比例。",
      formula: "夏普 = (年化收益 - 2%) / 年化波动率；年化波动率 = 月收益标准差 × √12",
      calculation: `年化收益 ${percentText(annReturn)}，年化波动率 ${percentText(annVol)}；(${percentText(annReturn)} - 2.00%) / ${percentText(annVol)} = ${finiteNumber(ov.sharpe_ratio).toFixed(2)}`,
    },
    max_drawdown: {
      title: "最大回撤",
      current: percentText(ov.max_drawdown),
      definition: "回测净值从任一历史峰值到其后低点的最大跌幅。",
      formula: "最大回撤 = minₜ[净值ₜ / 截至t的历史最高净值 - 1]",
      calculation: `逐期复利净值并与此前峰值比较，本区间最深回撤为 ${percentText(ov.max_drawdown)}`,
    },
  };
  return { ...(definitions[metric] || { title: metric, current: "—" }), ...common };
}

function buildRoleExplanation(row, metric, data = state.backtestResult) {
  const breakdown = data?.results?.role_breakdown || [];
  const index = breakdown.findIndex((item) => item.role === row.role);
  const trace = backtestTrace(data);
  const shapley = finiteNumber(row.shapley_raw ?? row.contribution_raw);
  const excess = finiteNumber(data?.results?.overview?.excess_return);
  const sourcePath = `results.role_breakdown[${Math.max(index, 0)}].${metric}`;
  const evidence = evidenceForPath(sourcePath);
  const common = { ...trace, sourcePath, evidenceId: evidence?.id || "待本次证据校验返回" };
  if (metric === "shapley_raw") return {
    title: `${row.role}夏普利超额贡献`, current: percentText(shapley, 2, true), ...common,
    definition: "该角色跨全部联盟顺序的平均边际超额贡献，保留正负号。",
    formula: "φᵢ = Σ[|S|!(n-|S|-1)!/n!] × [v(S∪{i})-v(S)]；v(S)=R(S)-R(沪深300)",
    calculation: `五角色共32个理论联盟（31个非空联盟回测）；本角色加权边际贡献 = ${percentText(shapley, 2, true)}。校验：五个φ之和 = ${percentText(excess, 2, true)}。`,
  };
  if (metric === "contribution_relative") return {
    title: `${row.role}相对贡献`, current: percentText(row.contribution_relative, 1, true), ...common,
    definition: "该角色夏普利贡献占全组合超额收益的比例，保留符号，因此可能为负数，也不等同于最终分配份额。",
    formula: "相对贡献ᵢ = φᵢ / Σφ",
    calculation: `${percentText(shapley, 2, true)} / ${percentText(excess, 2, true)} = ${percentText(row.contribution_relative, 1, true)}`,
  };
  const policy = data?.results?.allocation_policy || {};
  const configuredCap = policy.configured_max_role_weight ?? policy.max_role_weight ?? 0.5;
  const effectiveCap = policy.effective_max_role_weight ?? configuredCap;
  const capRule = policy.cap_relaxed
    ? `配置上限为 ${percentText(configuredCap, 0)}；因正贡献角色不足以承接100%权重，本次实际可用上限透明放宽至 ${percentText(effectiveCap, 0)}。`
    : `本次单角色上限为 ${percentText(effectiveCap, 0)}。`;
  return {
    title: `${row.role}证据轨建议权重`, current: percentText(row.weight, 1), ...common,
    definition: "将正向夏普利贡献转换为证据轨内部建议权重；负贡献仍展示，但不进入正向权重评分。",
    formula: "scoreᵢ = max(φᵢ, 0) × 角色调节系数；正贡献角色内归一化，配置上限不可行时按最小幅度放宽",
    calculation: `φ=${percentText(shapley, 2, true)} → 建议权重 ${percentText(row.weight, 1)}；${capRule} 五角色权重合计100%。`,
  };
}

function buildTopRoleExplanation(data = state.backtestResult) {
  const top = [...(data?.results?.role_breakdown || [])].sort((a, b) => finiteNumber(b.weight) - finiteNumber(a.weight))[0];
  if (!top) return { title: "贡献最高角色", current: "等待回测", definition: "完成回测后按证据轨建议权重排序。" };
  return buildRoleExplanation(top, "weight", data);
}

function buildDualPoolExplanation(row, metric, data = state.backtestResult) {
  const trace = backtestTrace(data);
  if (metric === "amount") return {
    title: `${row.role}合成资源量`, current: money(row.amount), ...trace,
    definition: "资源池按该角色6:4合成份额换算出的资源单位数量。",
    formula: "合成资源量 = 可分配资源池 × 合成份额",
    calculation: `${money(state.dualPoolAmount)} × ${percentText(row.finalW, 1)} = ${money(row.amount)}`,
    sourcePath: "frontend.computeDualPoolRows[].amount",
    limitation: "资源池可代表预算、研究资源、项目机会、数据/算力额度或激励权益；评审委员会确认前不生效。",
  };
  if (metric === "finalW") return {
    title: `${row.role}6:4合成份额`, current: percentText(row.finalW, 1), ...trace,
    definition: "机构现行制度份额与回测证据轨建议份额按6:4加权后的建议锚点。",
    formula: "合成份额 = 60% × 制度轨现行份额 + 40% × 证据轨建议份额",
    calculation: `60% × ${percentText(row.oldW, 1)} + 40% × ${percentText(row.newW, 1)} = ${percentText(row.finalW, 1)}`,
    sourcePath: "frontend.computeDualPoolRows[].finalW",
    limitation: "合成结果是评审决策的量化输入，不会自动应用，必须由评审委员会或机构治理责任人确认。",
  };
  return metric === "oldW" ? {
    title: `${row.role}制度轨现行份额`, current: percentText(row.oldW, 1), ...trace,
    definition: "由机构提供的现行分配比例；演示环境默认五角色均等20%，可替换为真实制度比例。",
    formula: "制度轨输入由机构录入，五角色合计应为100%",
    calculation: `当前输入 ${percentText(row.oldW, 1)}；在合成结果中的系数为60%。`,
    sourcePath: `frontend.dualPoolBaseline.${row.role}`,
  } : buildRoleExplanation({ role: row.role, weight: row.newW, shapley_raw: row.shapleyRaw }, "weight", data);
}

function buildComparisonExplanation(label, kind, customer, baseline, benchmark, comparison) {
  const keyMap = { "累计收益": "total_return", "相对沪深300超额": "excess_return", "夏普比率": "sharpe_ratio", "最大回撤": "max_drawdown" };
  const key = keyMap[label];
  const display = (value) => comparisonValue(value, kind);
  const trace = backtestTrace();
  return {
    title: `${label}三方对照`,
    current: `客户 ${display(customer)} / 默认 ${display(baseline)} / 沪深300 ${display(benchmark)}`,
    definition: "三列使用同一日期、股票范围、调仓频率和交易口径，仅因子配置不同。",
    formula: key === "excess_return" ? "各方案超额 = 各方案累计收益 - 同期沪深300累计收益" : `三列均按“${label}”统一公式计算`,
    calculation: `客户方案 ${display(customer)}；默认等权方案 ${display(baseline)}；沪深300 ${display(benchmark)}。`,
    ...trace,
    sourcePath: `comparison.customer/default/benchmark.${key}`,
    configId: `${state.factorConfig?.config_id || "客户配置"} / ${state.factorDefaultConfig?.config_id || "默认配置"}`,
    limitation: "该对照用于解释个性化配置差异，不用于根据历史结果反复寻优，也不构成收益承诺。",
  };
}

function buildFactorExplanation(role, factor, cfg) {
  const value = finiteNumber(cfg?.factor_weights?.[factor.key]);
  const configId = state.factorConfig?.config_id || "默认方案";
  return {
    title: `${role} · ${factor.label || factor.key}`,
    current: percentText(value, 1),
    definition: `${factor.description || "该因子参与本角色候选排序。"}；${factor.preference || (finiteNumber(factor.direction, 1) < 0 ? "低值优先" : "高值优先")}。`,
    formula: "角色因子权重 = 该因子原始权重 / 本角色8个因子原始权重之和",
    calculation: `当前确认配置中该因子归一化权重为 ${percentText(value, 1)}；本角色8个因子合计100%，单因子上限35%。`,
    scope: "下一次实时回测的角色内部选股评分",
    sourcePath: `query.factor_config.roles.${role}.factor_weights.${factor.key}`,
    configId,
    limitation: "因子权重表达客户偏好，不是该因子的收益贡献；只有人工确认后的配置才进入回测。",
  };
}

function buildModuleParamExplanation(role, key, value) {
  const meta = factorRoleMeta(role);
  const bounds = meta.param_bounds?.[key];
  return {
    title: `${role} · ${key}`,
    current: String(value),
    definition: "该值是角色模型运行参数，不是角色权重或收益率。",
    formula: bounds ? `参数白名单约束：${bounds[0]} ≤ ${key} ≤ ${bounds[1]}` : "按后端参数白名单校验后传入回测模块",
    calculation: `当前确认值 ${value}${bounds ? `，允许范围 ${bounds[0]}–${bounds[1]}` : ""}。`,
    scope: "下一次实时回测",
    sourcePath: `query.factor_config.roles.${role}.module_params.${key}`,
    configId: state.factorConfig?.config_id || "默认方案",
    limitation: "参数建议必须经过人工确认；超出白名单范围的值会被后端拒绝。",
  };
}

function buildFactorChangeExplanation(change, proposal) {
  const isFactor = Boolean(change.factor);
  const oldValue = isFactor ? percentText(change.old_weight, 1) : String(change.old_value);
  const newValue = isFactor ? percentText(change.new_weight, 1) : String(change.new_value);
  return {
    title: `${change.role} · ${change.label || change.factor || change.parameter}调整`,
    current: `${oldValue} → ${newValue}`,
    definition: isFactor
      ? "Agent把用户定性偏好转换为白名单内的因子权重补丁，随后由后端重新归一化角色内8个因子。"
      : "Agent把用户偏好转换为白名单内的模型参数建议。",
    formula: isFactor ? "建议权重 = 调整原始权重后，除以本角色全部因子权重之和" : "建议参数必须落在后端登记的允许区间内",
    calculation: `${oldValue} → ${newValue}；原因：${change.reason || proposal.summary || "用户偏好映射"}`,
    scope: "尚未确认的Agent建议",
    sourcePath: isFactor
      ? `proposal.config.roles.${change.role}.factor_weights.${change.factor}`
      : `proposal.config.roles.${change.role}.module_params.${change.parameter}`,
    configId: proposal.config?.config_id || "待确认配置",
    requestId: proposal.audit?.audit_id || "—",
    limitation: "Agent只能生成配置建议，不能直接执行回测；用户确认后才替换相应字段，其他因子保持在同一归一化配置中。",
  };
}

function explanationForStaticKey(key) {
  if (key === "top_role") return buildTopRoleExplanation();
  return buildOverviewExplanation(key);
}

document.addEventListener("click", (event) => {
  const button = event.target.closest?.("[data-explain-id], [data-explain-key]");
  if (button) {
    const explanation = button.dataset.explainId
      ? metricExplanations.get(button.dataset.explainId)
      : explanationForStaticKey(button.dataset.explainKey);
    openMetricExplanation(explanation, button);
    return;
  }
  if (event.target === $("#metricExplainOverlay")) closeMetricExplanation();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeMetricExplanation();
});
$("#btnMetricExplainClose")?.addEventListener("click", closeMetricExplanation);

const APPENDIX_TABS = new Set([
  "technical",
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

$$(".journey-step[data-goto-tab]").forEach((btn) => {
  btn.addEventListener("click", () => {
    switchToTab(btn.dataset.gotoTab, {
      openAppendix: btn.dataset.openAppendix === "1",
    });
  });
});

function highlightDemoFlow(tabId) {
  const flowMap = { backtest: "1", negotiate: "2", technical: "3" };
  const step = flowMap[tabId];
  const cur = step ? parseInt(step, 10) : 0;
  $$(".demo-flow-step").forEach((el) => {
    el.classList.toggle("current", step ? el.dataset.flow === step : false);
  });
  $$(".journey-step[data-flow]").forEach((el) => {
    el.classList.toggle("active", step ? el.dataset.flow === step : false);
  });
  $$(".demo-flow .journey-connector").forEach((el) => {
    const after = parseInt(el.dataset.after, 10);
    el.classList.toggle("done", cur > after);
  });
}

const GUIDED_STEPS = ["preferences", "confirm", "backtest", "apply"];
const GUIDED_COPY = {
  preferences: {
    title: "先告诉Agent你的投资偏好",
    body: "页面已预选“稳健、控制回撤、关注风控”。你可以直接使用，也可以修改选择或补充文字。",
    button: "开始制定我的方案",
  },
  confirm: {
    title: "检查Agent建议，确认后才会生效",
    body: "重点看调整前后数值和原因。只有点击确认，新的因子配置才会进入下一次实时回测。",
    button: "查看并确认建议",
  },
  backtest: {
    title: "方案已就绪，现在验证它的历史表现",
    body: "首次体验建议使用预置数据；需要验证刚确认的客户因子配置时，选择实时回测。",
    button: "前往回测",
  },
  apply: {
    title: "回测已完成，查看贡献如何进入应用建议",
    body: "先阅读客户方案、默认方案和沪深300的对照，再进入6:4建议与评审委员会决策。",
    button: "进入应用建议",
  },
  complete: {
    title: "本次方案已由评审委员会确认",
    body: "你可以查看最终份额和资源量，或返回第一步重新描述客户需求。",
    button: "查看确认结果",
  },
};

function scrollToGuideTarget(id, block = "start") {
  const target = $(`#${id}`);
  if (!target || target.classList.contains("hidden")) return false;
  target.scrollIntoView({ behavior: "smooth", block, inline: "nearest" });
  return true;
}

function setNextActionCue(target, label = "下一步") {
  $$(".is-next-action").forEach((button) => {
    button.classList.remove("is-next-action");
    delete button.dataset.nextCue;
  });
  const button = typeof target === "string" ? $(target) : target;
  if (!button) return;
  button.classList.add("is-next-action");
  button.dataset.nextCue = label;
}

function revealCurrentNextAction() {
  const button = $(".is-next-action:not(:disabled)");
  if (!button) return false;
  const rect = button.getBoundingClientRect();
  const topGuard = 72;
  const bottomGuard = 24;
  const visible = rect.top >= topGuard && rect.bottom <= window.innerHeight - bottomGuard;
  if (!visible) button.scrollIntoView({ behavior: "auto", block: "center", inline: "nearest" });
  return true;
}

function syncGuidedNextAction(stage) {
  if (stage === "preferences") {
    setNextActionCue("#btnGuidePrimary");
  } else if (stage === "confirm") {
    setNextActionCue("#btnFactorApply", "请确认");
  } else if (stage === "backtest") {
    setNextActionCue("#btnGuidedDemo");
  } else if (stage === "apply") {
    setNextActionCue("#btnGuidePrimary");
  } else {
    setNextActionCue(null);
  }
}

function setGuidedStage(stage, options = {}) {
  const stageIndex = stage === "complete" ? GUIDED_STEPS.length : GUIDED_STEPS.indexOf(stage);
  if (stageIndex < 0) return;
  state.guidedStage = stage;
  state.guidedMaxStep = Math.max(state.guidedMaxStep, Math.min(stageIndex + 1, GUIDED_STEPS.length));
  $$("[data-guide-step]").forEach((button) => {
    const index = GUIDED_STEPS.indexOf(button.dataset.guideStep);
    button.classList.toggle("active", stage !== "complete" && index === stageIndex);
    button.classList.toggle("done", stage === "complete" || index < stageIndex);
    button.disabled = index + 1 > state.guidedMaxStep;
  });
  $$(".guided-stepper .journey-connector").forEach((connector) => {
    connector.classList.toggle("done", Number(connector.dataset.after) <= stageIndex);
  });
  const copy = GUIDED_COPY[stage];
  if ($("#guideNowTitle")) $("#guideNowTitle").textContent = copy.title;
  if ($("#guideNowBody")) $("#guideNowBody").textContent = options.body || copy.body;
  const primary = $("#btnGuidePrimary");
  if (primary) {
    primary.textContent = copy.button;
    primary.dataset.guideAction = stage;
  }
  const canBacktest = state.guidedMaxStep >= 3;
  $("#btnGuidedDemo")?.toggleAttribute("disabled", !canBacktest);
  $("#btnGuidedBacktest")?.toggleAttribute("disabled", !canBacktest);
  syncGuidedNextAction(stage);
}

function runGuidedAction(stage = state.guidedStage) {
  if (stage === "preferences") {
    switchToTab("backtest");
    scrollToGuideTarget("factorConfigPanel");
    setNextActionCue("#btnFactorPropose");
  } else if (stage === "confirm") {
    switchToTab("backtest");
    if (!scrollToGuideTarget("factorProposalPreview", "center")) scrollToGuideTarget("factorConfigPanel");
    setNextActionCue("#btnFactorApply", "请确认");
  } else if (stage === "backtest") {
    switchToTab("backtest");
    scrollToGuideTarget("guidedBacktestActions", "center");
    setNextActionCue("#btnGuidedDemo");
  } else {
    renderDualPoolPanel();
    switchToTab("negotiate");
    window.setTimeout(() => {
      scrollToGuideTarget(stage === "complete" ? "confirmResult" : "dualPoolPanel");
      setNextActionCue(stage === "complete" ? null : "#btnStartGuidedNegotiate");
    }, 120);
  }
}

$("#btnGuidePrimary")?.addEventListener("click", (event) => {
  runGuidedAction(event.currentTarget.dataset.guideAction);
});
$$('[data-guide-step]').forEach((button) => {
  button.addEventListener("click", () => runGuidedAction(button.dataset.guideStep));
});

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
        请先在「HS300 岗位贡献」完成回测或路演演示，系统将自动带入证据轨建议，
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
      const oldInfo = explainButton(buildDualPoolExplanation(r, "oldW", data));
      const newInfo = explainButton(buildDualPoolExplanation(r, "newW", data));
      const finalInfo = explainButton(buildDualPoolExplanation(r, "finalW", data));
      const amountInfo = explainButton(buildDualPoolExplanation(r, "amount", data));
      return `<tr>
        <td data-label="角色"><span class="rank-dot" style="background:${roleColor(r.role)}"></span>${r.role}</td>
        <td data-label="原有方案 · 制度轨内部"><span class="metric-value-with-info">${(r.oldW * 100).toFixed(1)}%${oldInfo}</span></td>
        <td data-label="纯新方案 · 证据轨内部"><span class="metric-value-with-info">${(r.newW * 100).toFixed(1)}%${newInfo}</span></td>
        <td data-label="最终合成 · 占总资源池"><span class="metric-value-with-info"><strong>${(r.finalW * 100).toFixed(1)}%</strong>${finalInfo}</span></td>
        <td data-label="最终资源量"><span class="metric-value-with-info">${money(r.amount)}${amountInfo}</span></td>
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
    ? `<p class="note dual-pool-ok">已采用当前制度轨输入生成评审建议；最终方案仍需评审委员会（或机构治理责任人）独立确认。</p>`
    : "";

  box.innerHTML = `
    <h3>6:4 双轨分配方案</h3>
    <p class="dual-pool-lead">
      <strong>制度轨 60%</strong> 沿用机构现行分配 ·
      <strong>证据轨 40%</strong> 按 HS300 夏普利证据建议 ·
      合成后由<strong>评审委员会（或机构治理责任人）确认</strong>方可应用。
    </p>
    <div class="allocation-scope-guide" aria-label="分配比例口径说明">
      <div class="allocation-scope-item legacy">
        <span>原有方案比例</span>
        <strong>仅制度轨内部</strong>
        <p>五角色合计100%，在最终方案中的计算权重为60%。</p>
      </div>
      <div class="allocation-scope-item evidence">
        <span>纯新方案比例</span>
        <strong>仅40%证据轨内部</strong>
        <p>按夏普利贡献形成，五角色合计100%；它不是最终总池比例。</p>
      </div>
      <div class="allocation-scope-item final">
        <span>最终合成比例</span>
        <strong>占总可分配资源池</strong>
        <p>60%原有方案与40%纯新方案合成，作为评审委员会决策的量化建议。</p>
      </div>
    </div>
    <div class="dual-pool-controls">
      <label class="pool-amount">
        <span>可分配资源池</span>
        <input type="number" id="dualPoolAmountInput" min="100000" step="100000" value="${amount}" />
        <span class="unit">资源单位</span>
      </label>
    </div>
    ${baselineWarning}
    <div class="table-wrap dual-pool-table-wrap">
      <table class="dual-pool-table">
        <thead>
          <tr>
            <th>角色</th>
            <th>原有方案比例<br><small>仅制度轨内部 · 权重60%</small></th>
            <th>纯新方案比例<br><small>仅证据轨内部 · 权重40%</small></th>
            <th>最终合成比例<br><small>占总资源池</small></th>
            <th>最终资源量<br><small>按总资源池计算</small></th>
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
      <summary>编辑现行分配（制度轨 60% 输入）</summary>
      <p class="note">演示默认五角色均等 20%；机构落地时替换为真实制度比例。</p>
      <div class="baseline-form">${baselineInputs}</div>
      <button type="button" class="btn btn-ghost" id="btnBaselineReset">恢复默认均等</button>
    </details>
    <div class="dual-pool-actions">
      <button type="button" class="btn btn-ghost" id="btnDualPoolConfirm">采用当前制度轨输入，进入评审决策</button>
      <button type="button" class="btn btn-ghost" id="btnDualPoolRecalc">重新计算</button>
    </div>
    ${confirmNote}
    <p class="note dual-pool-formula">
      公式：合成份额 = ${(OLD_POOL_RATIO * 100).toFixed(0)}% × 制度轨现行份额 + ${(NEW_POOL_RATIO * 100).toFixed(0)}% × 证据轨建议份额
      · 回测区间：${data.query_summary || "—"}
    </p>
    <div class="guided-next-action">
      <div>
        <span>下一步</span>
        <strong>提交贡献证据，由评审委员会决策</strong>
        <p>系统将生成6:4合成建议，并汇总五类角色的贡献陈述作为参考；角色意见不改变建议份额，最终由评审委员会独立调整和确认。</p>
      </div>
      <button type="button" class="btn primary" id="btnStartGuidedNegotiate">进入评审委员会决策</button>
    </div>
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

  $("#btnStartGuidedNegotiate")?.addEventListener("click", () => {
    box.querySelectorAll("[data-baseline-role]").forEach((input) => {
      const role = input.dataset.baselineRole;
      getDualPoolBaseline()[role] = Number(input.value) / 100;
    });
    state.dualPoolConfirmed = true;
    runNegotiate();
  });
}

function renderUtterance(u) {
  const cls = SPEAKER_CLASS[u.speaker] || "";
  const div = document.createElement("div");
  div.className = `bubble ${cls}`;
  div.innerHTML = `
    <div class="meta">
      <span>${u.speaker} · ${u.role || ""}</span>
      ${u.claim != null ? `<span class="claim">参考意见 ${pct(u.claim)}</span>` : ""}
    </div>
    <div class="text">${u.text}</div>
  `;
  return div;
}

function buildSettlementExplanation(name, row, data) {
  const proposed = finiteNumber(row.proposed_share ?? row.final_share);
  const anchor = finiteNumber(row.formula_share);
  const negotiated = finiteNumber(row.negotiated_share, anchor);
  const amount = finiteNumber(row.amount);
  return {
    title: `${name}评审建议`,
    current: `${percentText(proposed, 1)} / ${money(amount)}`,
    definition: "系统建议由制度轨60%与夏普利证据轨40%合成；角色陈述只供评审参考，不参与建议份额计算。",
    formula: "系统建议 = 60% × 制度轨现行份额 + 40% × 证据轨建议份额；资源量 = 系统建议份额 × 可分配资源",
    calculation: `6:4合成建议 ${percentText(anchor, 1)}；角色参考意见 ${percentText(negotiated, 1)} 不参与计算。评审调整区间 ${percentText(row.band_low, 1)}–${percentText(row.band_high, 1)}；当前建议 ${percentText(proposed, 1)} × ${money(data.distributable)} = ${money(amount)}。`,
    scope: data.backtest_summary || state.backtestResult?.query_summary || "当前评审",
    benchmark: "沪深300夏普利证据",
    sourcePath: `negotiation.settlement.${name}`,
    requestId: state.backtestResult?.request_id || "—",
    configId: state.backtestResult?.results?.factor_config?.config_id || state.factorConfig?.config_id || "—",
    limitation: "系统建议不是自动裁决；最终比例由评审委员会（或机构治理责任人）独立调整并确认，越界须明确承担合规定责。",
  };
}

function renderSettlement(data) {
  const settle = $("#settlement");
  const band = data.band ?? 0.05;
  const isFive = data.role_model === "five_roles";
  const items = Object.entries(data.settlement)
    .map(([name, s]) => {
      const status = s.in_band === false ? "越界" : "带宽内";
      const anchorLabel = isFive ? "6:4合成" : "锚点";
      const evidenceShare = data.dual_track?.new_pool_weights?.[name];
      const evidenceLabel = isFive && Number.isFinite(Number(evidenceShare))
        ? `纯新方案 ${pct(Number(evidenceShare))} · `
        : "";
      const info = explainButton(buildSettlementExplanation(name, s, data));
      return `
      <div class="settle-item">
        <div class="name">${name}</div>
        <div class="amt metric-value-with-info">${money(s.amount)}${info}</div>
        <div class="sub">
          最终建议 ${pct(s.proposed_share ?? s.final_share)} · ${evidenceLabel}${anchorLabel} ${pct(s.formula_share)}
          · 带宽 ${pct(s.band_low)}–${pct(s.band_high)} · ${status}
        </div>
      </div>`;
    })
    .join("");

  const dual = data.dual_track;
  const dualNote = dual
    ? `<p class="note" style="margin:0 0 0.75rem">双轨：制度轨60%现行 + 证据轨40%夏普利 · ${data.backtest_summary || ""}</p>`
    : "";

  settle.innerHTML = `
    <h3>评审建议 · 最终合成比例（占总资源池）</h3>
    ${dualNote}
    <p class="allocation-final-note">下列“最终建议”已包含60%原有方案；“纯新方案”仅表示40%证据轨内部比例。可分配资源 ${Number(data.distributable || 0).toLocaleString("zh-CN")} 单位 · 带宽 ±${(band * 100).toFixed(0)}%</p>
    <div class="settle-grid">${items}</div>
    <p class="note" style="margin-top:0.75rem">
      状态：${data.status || "pending_human_confirm"} · 模式 ${data.mode || "-"} · 需评审委员会确认后生效
    </p>
  `;
  settle.classList.remove("hidden");
}

function renderHumanConfirm(data) {
  const box = $("#humanConfirm");
  const rows = Object.entries(data.settlement)
    .map(([name, s]) => {
      const val = ((s.proposed_share ?? s.final_share) * 100).toFixed(1);
      const evidenceShare = data.dual_track?.new_pool_weights?.[name];
      const evidenceLabel = Number.isFinite(Number(evidenceShare))
        ? `纯新方案 ${pct(Number(evidenceShare))} · `
        : "";
      const info = explainButton(buildSettlementExplanation(name, s, data));
      return `
      <label class="share-row">
        <span>${name}
          <small>${evidenceLabel}最终合成锚点 ${pct(s.formula_share)} · 建议带宽 ${pct(s.band_low)}–${pct(s.band_high)} ${info}</small>
        </span>
        <input type="number" min="5" max="80" step="0.5" data-name="${name}" value="${val}" />
        <span class="unit">%</span>
      </label>`;
    })
    .join("");

  box.innerHTML = `
    <h3>评审委员会分配决策（占总资源池）</h3>
    <p class="allocation-final-note"><strong>请注意：</strong>下列输入比例已经包含60%原有方案和40%纯新方案，五角色合计应为100%；并非只分配40%证据轨。</p>
    <p class="note">角色陈述仅供参考。评审委员会可在建议带宽内独立调整；勾选「允许越界」表示在合规定责下作出人工覆盖。</p>
    <div class="share-form">${rows}</div>
    <label class="override">
      <input type="checkbox" id="allowOutside" /> 允许越出带宽（需明示合规定责）
    </label>
    <div class="confirm-actions">
      <button id="btnAcceptProposed" class="btn">采用系统建议</button>
      <button id="btnConfirm" class="btn primary">确认评审决定</button>
    </div>
    <div id="confirmResult" class="confirm-result"></div>
  `;
  box.classList.remove("hidden");
  setNextActionCue("#btnConfirm", "请确认");

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
  setGuidedStage("complete");
  scrollToGuideTarget("confirmResult", "center");
}

function focusNegotiateProgress(target, block = "center") {
  if (!target) return;
  window.requestAnimationFrame(() => {
    window.setTimeout(() => {
      target.scrollIntoView({ behavior: "smooth", block, inline: "nearest" });
    }, 80);
  });
}

async function runNegotiate(options = {}) {
  const roadshow = options.roadshow || state.roadshowMode;
  const utteranceDelay = roadshow ? ROADSHOW_PACE.utterance : 220;
  const roundGap = roadshow ? ROADSHOW_PACE.roundGap : 0;
  const btn = $("#btnNegotiate");
  const guidedBtn = $("#btnStartGuidedNegotiate");
  setBusy(btn, true);
  setBusy(guidedBtn, true);
  const chat = $("#chatStream");
  $("#settlement").classList.add("hidden");
  $("#humanConfirm").classList.add("hidden");
  chat.innerHTML = `<div class="bubble arbiter negotiate-progress-bubble"><div class="text">正在读取回测证据并生成角色贡献陈述与评审建议…</div></div>`;
  chat.setAttribute("aria-busy", "true");
  focusNegotiateProgress(chat);

  if (!state.backtestResult?.results?.role_breakdown?.length) {
    chat.innerHTML = `<div class="bubble arbiter"><div class="text">请先在「HS300 岗位贡献」完成回测，再进入评审委员会决策。</div></div>`;
    chat.removeAttribute("aria-busy");
    focusNegotiateProgress(chat);
    setBusy(btn, false);
    setBusy(guidedBtn, false);
    return;
  }

  if (roadshow) {
    showRoadshowLine(
      "第2步 · 贡献评审",
      "五类角色基于夏普利证据陈述意见，仅供参考；系统提供 6:4 建议，最终由评审委员会决策。",
      3
    );
    await sleep(ROADSHOW_PACE.negotiateIntro);
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
    chat.innerHTML = "";
    const heroDesc = $("#heroDesc");
    if (heroDesc) {
      heroDesc.textContent = `${data.framework || ""} · ${data.scenario}`;
    }

    for (const round of data.rounds) {
      const label = document.createElement("div");
      label.className = "round-label";
      label.textContent = `Round ${round.round} · ${round.phase} · consensus ${((round.consensus || 0) * 100).toFixed(0)}%`;
      chat.appendChild(label);
      if (roadshow) {
        const phaseLabel = round.phase === "opening" ? "首次陈述" : "补充陈述";
        showRoadshowLine(
          `第2步 · ${phaseLabel}`,
          `五类角色 ${phaseLabel}：各自引用贡献证据表达意见，内容仅供评审参考…`,
          3
        );
        await sleep(600);
      }
      for (const u of round.utterances) {
        chat.appendChild(renderUtterance(u));
        chat.scrollTop = chat.scrollHeight;
        await sleep(utteranceDelay);
      }
      if (roundGap) await sleep(roundGap);
    }

    chat.appendChild(
      renderUtterance({
        speaker: data.arbiter.name,
        role: data.arbiter.role,
        text: data.arbiter_statement,
      })
    );
    chat.scrollTop = chat.scrollHeight;
    if (roadshow) {
      showRoadshowLine(
        "第2步 · 评审决策说明",
        data.arbiter_statement || "评审委员会：证据链已齐备，请独立判断、调整并确认分配方案。",
        3
      );
      await sleep(1200);
    }

    renderSettlement(data);
    renderHumanConfirm(data);
    focusNegotiateProgress($("#humanConfirm"), "center");
  } catch (e) {
    chat.innerHTML = `<div class="bubble arbiter"><div class="text">评审材料生成失败：${e.message}</div></div>`;
    focusNegotiateProgress(chat);
  } finally {
    chat.removeAttribute("aria-busy");
    setBusy(btn, false);
    setBusy(guidedBtn, false);
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

  setEChart("compare", "#compareChart", {
    title: { text: `${data.rounds} 轮均值对照`, left: "center", textStyle: { color: CHART.ink, fontSize: 13 } },
    legend: { bottom: 0, textStyle: { color: CHART.muted } },
    tooltip: { trigger: "axis" },
    grid: { left: 48, right: 16, top: 40, bottom: 48 },
    xAxis: { type: "category", data: labels, ...ecAxis({ splitLine: { show: false } }) },
    yAxis: { type: "value", min: 0, max: 1, ...ecAxis() },
    series: datasets.map((d) => ({
      name: d.label,
      type: "bar",
      data: d.data,
      itemStyle: { color: d.backgroundColor, borderRadius: [4, 4, 0, 0] },
    })),
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
  setEChart(key, canvasId, {
    title: { text: title, left: "center", textStyle: { color: CHART.ink, fontSize: 13 } },
    legend: { bottom: 0, textStyle: { color: CHART.muted } },
    tooltip: { trigger: "axis" },
    grid: { left: 48, right: 16, top: 40, bottom: 48 },
    xAxis: { type: "category", data: labels, ...ecAxis({ splitLine: { show: false } }) },
    yAxis: { type: "value", ...ecAxis() },
    series: ["kpi", "formula", "agent"].map((g) => ({
      name: GROUP_LABELS[g],
      type: "line",
      data: data.series[g][seriesKey],
      smooth: true,
      showSymbol: false,
      lineStyle: { width: 2, color: GROUP_COLORS[g] },
      itemStyle: { color: GROUP_COLORS[g] },
    })),
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
            <th>稀缺</th><th>复用</th><th>贡献值</th><th>锚点份额</th><th>资源量</th>
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
  setEChart("attrWeight", "#attrWeightChart", {
    title: { text: "三因素贡献比重", left: "center", textStyle: { color: CHART.ink, fontSize: 13 } },
    tooltip: { trigger: "item", formatter: "{b}: {c}%" },
    legend: { bottom: 0, textStyle: { color: CHART.muted } },
    series: [{
      type: "pie",
      radius: ["42%", "68%"],
      label: { color: CHART.muted },
      data: [
        { name: "策略 Alpha", value: +(w.strategy_alpha * 100).toFixed(2), itemStyle: { color: "#3d9a7a" } },
        { name: "行业·政策", value: +(w.industry_policy * 100).toFixed(2), itemStyle: { color: "#5b8def" } },
        { name: "偶然·宏观", value: +(w.luck_macro * 100).toFixed(2), itemStyle: { color: "#c4a35a" } },
      ],
    }],
  });

  const names = Object.keys(data.attributed_allocation);
  setEChart("attrAlloc", "#attrAllocChart", {
    title: { text: "写入 Impact 锚点后的分配变化", left: "center", textStyle: { color: CHART.ink, fontSize: 13 } },
    legend: { bottom: 0, textStyle: { color: CHART.muted } },
    tooltip: { trigger: "axis" },
    grid: { left: 48, right: 16, top: 40, bottom: 48 },
    xAxis: { type: "category", data: names, ...ecAxis({ splitLine: { show: false } }) },
    yAxis: { type: "value", axisLabel: { color: CHART.muted, formatter: "{value}%" }, splitLine: { lineStyle: { color: CHART.grid } } },
    series: [
      {
        name: "归因前份额%",
        type: "bar",
        data: names.map((n) => data.baseline_allocation[n].share_pct),
        itemStyle: { color: "rgba(139,155,176,0.45)" },
      },
      {
        name: "归因后份额%",
        type: "bar",
        data: names.map((n) => data.attributed_allocation[n].share_pct),
        itemStyle: { color: "#3d9a7a", borderRadius: [4, 4, 0, 0] },
      },
    ],
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
      <thead><tr><th>角色</th><th>新 Impact</th><th>原份额</th><th>新份额</th><th>资源量</th></tr></thead>
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
  setEChart("shareBar", "#shareBarChart", {
    title: { text: title, left: "center", textStyle: { color: CHART.ink, fontSize: 13 } },
    tooltip: { trigger: "axis", valueFormatter: (v) => `${v}%` },
    grid: { left: 48, right: 16, top: 40, bottom: 32 },
    xAxis: { type: "category", data: names, ...ecAxis({ splitLine: { show: false } }) },
    yAxis: { type: "value", min: 0, max: 70, axisLabel: { color: CHART.muted, formatter: "{value}%" }, splitLine: { lineStyle: { color: CHART.grid } } },
    series: [{
      type: "bar",
      data: valuesPct.map((v, i) => ({ value: v, itemStyle: { color: colors[i], borderRadius: [4, 4, 0, 0] } })),
      animationDuration: 180,
    }],
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
    const xs = data.sweep.factor_weight.map((w) => Number(w).toFixed(2));
    setEChart("sweep", "#sweepChart", {
      title: {
        text: "参考：份额随因子权重 w 的可行域",
        left: "center",
        textStyle: { color: CHART.ink, fontSize: 13 },
      },
      legend: { bottom: 0, textStyle: { color: CHART.muted } },
      tooltip: { trigger: "axis" },
      grid: { left: 52, right: 16, top: 40, bottom: 52 },
      xAxis: {
        type: "category",
        name: "因子权重 w",
        nameTextStyle: { color: CHART.muted },
        data: xs,
        ...ecAxis({ splitLine: { show: false } }),
      },
      yAxis: {
        type: "value",
        name: "份额 %",
        nameTextStyle: { color: CHART.muted },
        ...ecAxis(),
      },
      series: names.map((name, i) => ({
        name,
        type: "line",
        data: data.sweep.share_pct[name],
        smooth: true,
        symbolSize: 4,
        lineStyle: { width: 2, color: SENS_COLORS[i % SENS_COLORS.length] },
        itemStyle: { color: SENS_COLORS[i % SENS_COLORS.length] },
      })),
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
          <th>角色</th><th>你的目标</th><th>公式锚点</th><th>合理目标</th><th>当前动画</th><th>资源量</th>
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
    output: "可解释的贡献系数 + 可审计的价值分配证据链。",
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
    output: "各角色夏普利贡献值 → 可解释的证据轨建议权重。",
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
    body: "已得到各岗位贡献排序与权重，可进入「贡献评审与分配决策」讨论如何应用这些证据。",
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
  if (state.roadshowMode && ROADSHOW_STAGE_LINES[key]) {
    showRoadshowLine(`回测 · ${n.tag}`, ROADSHOW_STAGE_LINES[key], key === "shapley" ? 2 : 1);
  }
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
    lead += ` 按夏普利归因，<strong>${top.role}</strong>证据轨建议权重最高（${((top.weight || 0) * 100).toFixed(1)}%）。`;
  }
  if (bottom && bottom.role !== top?.role && (bottom.shapley_raw || 0) < 0) {
    lead += ` <strong>${bottom.role}</strong>呈负向拖累，需在考核中重点关注。`;
  }

  const rankHtml = breakdown
    .map((r, i) => {
      const w = ((r.weight || 0) * 100).toFixed(1);
      const sh = ((r.shapley_raw || 0) * 100).toFixed(2);
      const weightInfo = explainButton(buildRoleExplanation(r, "weight", data));
      const shapleyInfo = explainButton(buildRoleExplanation(r, "shapley_raw", data));
      return `<li>
        <span class="rank-dot" style="background:${roleColor(r.role)}"></span>
        <span>${i + 1}. ${r.role}</span>
        <span style="margin-left:auto;color:var(--muted)">证据轨 <span class="metric-value-with-info">${w}%${weightInfo}</span> · 夏普利 <span class="metric-value-with-info">${sh}%${shapleyInfo}</span></span>
      </li>`;
    })
    .join("");

  const rec = results.recommendation?.summary || data.query_summary || "";
  const policy = results.allocation_policy || {};
  const capNote = policy.cap_relaxed
    ? `<p class="note" style="margin:0 0 0.75rem"><strong>权重上限说明：</strong>本次正贡献角色数量不足，配置上限 ${(finiteNumber(policy.configured_max_role_weight) * 100).toFixed(0)}% 无法同时满足“负贡献不获建议权重”和“证据轨合计100%”；系统已将实际上限透明放宽至 ${(finiteNumber(policy.effective_max_role_weight) * 100).toFixed(0)}%。</p>`
    : "";

  box.innerHTML = `
    <h3>结论摘要（给业务看）</h3>
    <p class="conclusion-lead">${lead}</p>
    <p class="note dual-track-hint" style="margin:0 0 0.75rem">
      <strong>6:4 双轨：</strong>本回测产出的是<strong>证据轨 40%</strong> 夏普利建议权重；
      制度轨 60% 沿用机构现行方案。完整合成表见下一步「评审决策」。
    </p>
    ${capNote}
    ${rec ? `<p class="note" style="margin:0 0 0.75rem">${rec}</p>` : ""}
    <p class="note" style="margin:0 0 0.5rem"><strong>用途：</strong>以下为贡献计量证据，可支持预算、研究资源、项目机会、数据/算力额度和激励权益等<strong>广义价值分配</strong>；方案须经评审委员会（或机构治理责任人）确认。</p>
    <ul class="rank-list">${rankHtml}</ul>
    <div class="conclusion-actions">
      <button type="button" class="btn primary" id="btnGotoNegotiate">下一步：评审委员会决策 →</button>
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
  updateShapleyRing(0, 31);
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
    const info = explainButton({ title: "股票池数量", current: `${live.stocks}只`, definition: "完成日期、行业和沪深300成分筛选后可用于本次回测的股票数量。", formula: "股票池 = 基础行情 ∩ 日期范围 ∩ 行业筛选 ∩ 指数成分约束", calculation: `本次筛选后保留 ${live.stocks} 只股票。`, sourcePath: "demo_replay.stocks / backtest init event", ...backtestTrace() });
    parts.push(`<div class="metric-card"><div class="label metric-label-with-info">股票池${info}</div><div class="value">${live.stocks}</div><div class="sub">只</div></div>`);
  }
  if (live.tradingDays != null) {
    const info = explainButton({ title: "有效交易日", current: `${live.tradingDays}天`, definition: "回测区间内行情数据实际覆盖的有效交易日数量。", formula: "有效交易日 = 去重后的交易日期计数", calculation: `本次数据覆盖 ${live.tradingDays} 个有效交易日。`, sourcePath: "demo_replay.trading_days / backtest init event", ...backtestTrace() });
    parts.push(`<div class="metric-card"><div class="label metric-label-with-info">交易日${info}</div><div class="value">${live.tradingDays}</div><div class="sub">天</div></div>`);
  }
  if (live.pipelineReturn != null) {
    const info = state.backtestResult ? buildOverviewExplanation("total_return") : { title: "组合累计收益（运行中）", current: percentText(live.pipelineReturn), definition: "当前已计算月份收益连续复利后的阶段性结果。", formula: "R组合 = ∏(1+rₜ)-1", calculation: `当前阶段累计 ${percentText(live.pipelineReturn)}。`, sourcePath: "SSE pipeline_return" };
    parts.push(`<div class="metric-card"><div class="label metric-label-with-info">组合累计${explainButton(info)}</div><div class="value">${(live.pipelineReturn * 100).toFixed(2)}%</div><div class="sub">五角色协作</div></div>`);
  }
  if (live.shapleyPoints.length) {
    const info = explainButton({ title: "夏普利联盟进度", current: `${live.shapleyPoints.length}/31`, definition: "五角色共有2⁵=32个联盟，空联盟无需实际回测，因此执行31个非空联盟。", formula: "非空联盟数 = 2⁵ - 1 = 31", calculation: `当前已完成 ${live.shapleyPoints.length} 个，共31个。`, sourcePath: "SSE shapley subset progress", ...backtestTrace() });
    parts.push(`<div class="metric-card"><div class="label metric-label-with-info">夏普利子集${info}</div><div class="value">${live.shapleyPoints.length}/31</div><div class="sub">反事实回测进度</div></div>`);
  }
  $("#backtestLiveMetrics").innerHTML = parts.join("");
  updateShapleyRing(live.shapleyPoints.length, 31);
}

function updateRoleLiveChart() {
  const live = state.backtestLive;
  if (!live) return;
  const labels = live.roleOrder;
  const data = labels.map((r) => live.roles[r]?.months || 0);
  const colors = labels.map((r) =>
    roleColor(r, live.roles[r]?.done ? 1 : 0.35)
  );
  setEChart("btRoleLive", "#backtestRoleLiveChart", {
    tooltip: { trigger: "axis" },
    grid: { left: 44, right: 12, top: 12, bottom: 36 },
    xAxis: {
      type: "category",
      data: labels.map((r) => ROLE_SHORT[r] || r),
      axisLabel: { color: CHART.muted, fontSize: 11 },
      axisLine: { lineStyle: { color: CHART.grid } },
      splitLine: { show: false },
    },
    yAxis: { type: "value", minInterval: 1, ...ecAxis() },
    series: [{
      type: "bar",
      data: data.map((v, i) => ({
        value: v,
        itemStyle: { color: colors[i], borderRadius: [4, 4, 0, 0] },
      })),
      barMaxWidth: 36,
    }],
  });
}

function updateNavLiveChart() {
  const live = state.backtestLive;
  if (!live?.pipelineMonthly?.length) return;
  const comparisonCurves = buildComparisonCurveData(state.backtestComparison);
  if (comparisonCurves) {
    const newColor = currentTheme() === "dark" ? "#22d3ee" : "#087f6b";
    const defaultColor = currentTheme() === "dark" ? "#fbbf24" : "#b7791f";
    const benchmarkColor = currentTheme() === "dark" ? "#a78bfa" : "#5b5bd6";
    setEChart("btNavLive", "#backtestNavLiveChart", {
      tooltip: { trigger: "axis", valueFormatter: (v) => `${Number(v).toFixed(2)}%` },
      legend: {
        top: 0,
        right: 4,
        textStyle: { color: CHART.muted, fontSize: 10 },
        data: ["新策略", "原始默认策略", "HS300"],
      },
      grid: { left: 48, right: 16, top: 38, bottom: 28 },
      xAxis: {
        type: "category",
        data: comparisonCurves.labels,
        boundaryGap: false,
        ...ecAxis({ splitLine: { show: false } }),
      },
      yAxis: {
        type: "value",
        axisLabel: { color: CHART.muted, formatter: "{value}%" },
        splitLine: { lineStyle: { color: CHART.grid } },
      },
      series: [
        {
          name: "新策略",
          type: "line",
          data: comparisonCurves.customer,
          smooth: false,
          showSymbol: false,
          lineStyle: { width: 2.5, color: newColor },
          itemStyle: { color: newColor },
        },
        {
          name: "原始默认策略",
          type: "line",
          data: comparisonCurves.baseline,
          smooth: false,
          showSymbol: true,
          symbolSize: 5,
          lineStyle: { width: 2.5, type: "dashed", color: defaultColor },
          itemStyle: { color: defaultColor },
        },
        {
          name: "HS300",
          type: "line",
          data: comparisonCurves.benchmark,
          smooth: false,
          showSymbol: false,
          lineStyle: { width: 2.5, type: "dashed", color: benchmarkColor },
          itemStyle: { color: benchmarkColor },
        },
      ],
    });
    return;
  }
  const labels = live.pipelineMonthly.map((m) => m.month);
  const data = live.pipelineMonthly.map((m) => m.cumulative * 100);
  const lineColor = currentTheme() === "dark" ? "#22d3ee" : "#0d6e5c";
  setEChart("btNavLive", "#backtestNavLiveChart", {
    tooltip: { trigger: "axis", valueFormatter: (v) => `${Number(v).toFixed(2)}%` },
    grid: { left: 48, right: 16, top: 12, bottom: 28 },
    xAxis: {
      type: "category",
      data: labels,
      boundaryGap: false,
      ...ecAxis({ splitLine: { show: false } }),
    },
    yAxis: {
      type: "value",
      axisLabel: { color: CHART.muted, formatter: "{value}%" },
      splitLine: { lineStyle: { color: CHART.grid } },
    },
    series: [{
      type: "line",
      data,
      smooth: true,
      showSymbol: false,
      lineStyle: { width: 2.5, color: lineColor },
      areaStyle: {
        color: {
          type: "linear",
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: "rgba(34, 211, 238, 0.35)" },
            { offset: 1, color: "rgba(34, 211, 238, 0.02)" },
          ],
        },
      },
      itemStyle: { color: lineColor },
    }],
  });
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
  const n = live.shapleyPoints.length;
  const showZoom = n > 8;
  setEChart("btShapleyLive", "#backtestShapleyLiveChart", {
    tooltip: {
      trigger: "axis",
      formatter(params) {
        const p = live.shapleyPoints[params[0]?.dataIndex];
        if (!p) return "";
        const names = (p.subset || []).join("、") || "无";
        return `第 ${p.index} 组 · ${p.fullLabel || coalitionLabel(p.subset)}<br/>${p.metric || "联盟超额收益"} ${Number(params[0].value).toFixed(2)}%<br/>角色：${names}`;
      },
    },
    grid: { left: 48, right: 12, top: 12, bottom: showZoom ? 52 : 40 },
    dataZoom: showZoom
      ? [{ type: "inside", xAxisIndex: 0, start: Math.max(0, 100 - (8 / n) * 100), end: 100 }]
      : undefined,
    xAxis: {
      type: "category",
      data: labels,
      axisLabel: {
        color: CHART.muted,
        rotate: n > 6 ? 40 : 0,
        fontSize: 9,
        interval: n > 12 ? "auto" : 0,
        hideOverlap: true,
      },
      axisLine: { lineStyle: { color: CHART.grid } },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: CHART.muted, formatter: "{value}%" },
      splitLine: { lineStyle: { color: CHART.grid } },
    },
    series: [{
      type: "bar",
      data: data.map((v, i) => ({
        value: v,
        itemStyle: { color: colors[i], borderRadius: [3, 3, 0, 0] },
      })),
      barMaxWidth: 18,
    }],
  });
  updateShapleyRing(live.shapleyPoints.length, 31);
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
  setEChart("btShapley", "#backtestShapleyChart", {
    title: {
      text: "各角色夏普利边际贡献",
      left: "center",
      textStyle: { color: CHART.ink, fontSize: 13 },
    },
    tooltip: { trigger: "axis", valueFormatter: (v) => `${Number(v).toFixed(2)}%` },
    grid: { left: 48, right: 16, top: 40, bottom: 40 },
    xAxis: {
      type: "category",
      data: roles.map((r) => ROLE_SHORT[r] || r),
      ...ecAxis({ splitLine: { show: false } }),
    },
    yAxis: {
      type: "value",
      axisLabel: { color: CHART.muted, formatter: "{value}%" },
      splitLine: { lineStyle: { color: CHART.grid } },
    },
    series: [{
      type: "bar",
      data: data.map((v, i) => ({
        value: v,
        itemStyle: {
          color: v >= 0 ? roleColor(roles[i], 0.9) : "rgba(212,120,106,0.75)",
          borderRadius: [4, 4, 0, 0],
        },
      })),
    }],
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
      `[夏普利 ${current}/${total}] ${fullLabel} → 联盟超额收益 ${(ret * 100).toFixed(2)}%`,
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
        metric: ev.metric || "联盟超额收益",
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

/** 一键路演 75 秒完整节奏 */
const ROADSHOW_PACE = {
  intro: 5000,
  stage: 2300,
  snapshot: 2000,
  role: 1700,
  pipeline: 2600,
  shapley: 1100,
  conclusion: 11000,
  phaseTransition: 2400,
  negotiateIntro: 2800,
  utterance: 900,
  roundGap: 1100,
  dualPool: 4500,
  finalizeReveal: 600,
  finalizeTech: 900,
};

const ROADSHOW_STAGE_LINES = {
  parse: "解析 2024 上半年 HS300 回测区间与调仓频率…",
  init: "加载沪深300成分股行情、行业映射与因子底座…",
  factors: "五类岗位各自用因子打分选股——把「决策」变成可回测信号…",
  pipeline: "按投研链整合五角色决策，模拟协作后的组合净值…",
  shapley: "遍历角色联盟做反事实对照——估计各岗位边际贡献 φ…",
  save: "汇总选股、收益与证据轨建议权重，生成可审计报告…",
  complete: "贡献计量完成：证据已就绪，可进入评审委员会决策环节。",
};

function setRoadshowMode(on) {
  state.roadshowMode = !!on;
  document.body.classList.toggle("roadshow-mode", !!on);
  $("#roadshowNarrator")?.classList.toggle("hidden", !on);
  if (on) highlightRoadshowQuestion(1);
}

function highlightRoadshowQuestion(n) {
  $$(".roadshow-q").forEach((el) => {
    el.classList.toggle("active", Number(el.dataset.q) === n);
  });
}

function showRoadshowLine(phase, line, questionNum) {
  const phaseEl = $("#roadshowPhase");
  const lineEl = $("#roadshowLine");
  if (phaseEl) phaseEl.textContent = phase;
  if (lineEl) lineEl.textContent = line;
  if (questionNum) highlightRoadshowQuestion(questionNum);
}

function buildConclusionNarration(data) {
  const results = data?.results || {};
  const ov = results.overview || {};
  const breakdown = [...(results.role_breakdown || [])].sort(
    (a, b) => (b.weight || 0) - (a.weight || 0)
  );
  const excess = ((ov.excess_return || 0) * 100).toFixed(2);
  const top = breakdown[0];
  const bottom = breakdown[breakdown.length - 1];
  let line = `本区间组合相对沪深300超额约 ${excess}%。`;
  if (top) {
    line += ` 夏普利归因显示，${top.role.replace("分析师", "")}岗边际贡献最高（证据轨建议权重 ${((top.weight || 0) * 100).toFixed(1)}%）。`;
  }
  if (bottom && bottom.role !== top?.role && (bottom.shapley_raw || 0) < 0) {
    line += ` ${bottom.role.replace("分析师", "")}岗呈负向拖累，需在考核中重点关注。`;
  }
  line += " 以上为计量证据，下一步进入贡献评审与评审委员会分配决策。";
  return line;
}

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
  const query = { ...baseQuery, ...(queryOverride || {}) };
  if (state.factorConfig) query.factor_config = cloneJson(state.factorConfig);
  return {
    request_id: `web_${Date.now()}`,
    use_cache: $("#btUseCache")?.checked !== false,
    force_refresh: false,
    demo_mode: false,
    ...rest,
    query,
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
  const trust = report.trust || {};
  const evidenceCount = (report.evidence || []).length;
  const trustLabel = trust.status === "trusted"
    ? `证据校验通过 · ${evidenceCount}项可追溯证据`
    : trust.status === "warning"
      ? `证据校验有警告 · ${(trust.warnings || []).length}项字段已隔离`
      : "证据校验信息将在本次回测后生成";
  box.innerHTML = `
    <h4>Agent 解读 · ${report.headline || ""}</h4>
    <p style="margin:0.35rem 0;white-space:pre-line">${report.body || ""}</p>
    ${bullets ? `<ul class="agent-bullets">${bullets}</ul>` : ""}
    ${report.dual_pool_note ? `<p class="note" style="margin:0.5rem 0 0">${report.dual_pool_note}</p>` : ""}
    <p class="note" style="margin:0.5rem 0 0">${trustLabel}</p>
  `;
  box.classList.remove("hidden");
}

function renderFactorAgentMode() {
  const badge = $("#factorAgentModeBadge");
  if (!badge) return;
  const agent = state.factorConfigMeta?.agent || {};
  if (agent.available) {
    badge.textContent = `${agent.provider === "deepseek" ? "DeepSeek" : "LLM"} 在线 · ${agent.model || "deepseek-chat"}`;
    badge.classList.add("online");
    badge.classList.remove("fallback");
  } else {
    const offlineCache = agent.offline_cache || {};
    badge.textContent = offlineCache.available
      ? `离线Agent缓存 · ${offlineCache.response_count || 0}组预置响应`
      : "规则兜底模式";
    badge.classList.remove("online");
    badge.classList.add("fallback");
  }
  renderAgentCredentialStatus();
}

function setAgentCredentialChoice(showInput) {
  const form = $("#agentCredentialForm");
  const offlineButton = $("#btnKeepOffline");
  const onlineButton = $("#btnShowAgentKey");
  form?.classList.toggle("hidden", !showInput);
  offlineButton?.classList.toggle("active", !showInput);
  onlineButton?.classList.toggle("active", showInput);
  offlineButton?.setAttribute("aria-pressed", String(!showInput));
  onlineButton?.setAttribute("aria-pressed", String(showInput));
  onlineButton?.setAttribute("aria-expanded", String(showInput));
  if (showInput) window.requestAnimationFrame(() => $("#agentApiKey")?.focus());
}

function renderAgentCredentialStatus(message = "", type = "") {
  const box = $("#agentCredentialStatus");
  const summary = $("#agentModeSummary");
  const clearButton = $("#btnClearAgentKey");
  if (!box) return;
  const agent = state.factorConfigMeta?.agent || {};
  const runtimeConfigured = agent.credential_source === "runtime";
  if (message) {
    box.textContent = message;
  } else if (runtimeConfigured) {
    box.textContent = "在线 Agent 已启用。当前密钥仅保存在本次服务进程内存中。";
  } else if (agent.available) {
    box.textContent = "在线 Agent 已通过服务端环境变量启用；页面不会显示或读取该密钥。";
  } else if (agent.offline_cache?.available) {
    box.textContent = "当前使用内置离线 Agent 缓存；不输入密钥也可完整体验。";
  } else {
    box.textContent = "当前使用规则模式；可输入 DeepSeek API Key 启用在线 Agent。";
  }
  if (summary) {
    summary.textContent = runtimeConfigured
      ? "在线 Agent 已启用；密钥仅保存在本次服务进程内存中。"
      : agent.available
        ? "在线 Agent 已通过服务端环境变量启用，页面不会读取或显示密钥。"
        : agent.offline_cache?.available
          ? "默认使用内置离线 Agent 缓存，无需 API Key 也能完整体验。"
          : "当前使用规则模式；也可以输入 DeepSeek API Key 启用在线 Agent。";
  }
  box.className = `agent-credential-status${type ? ` ${type}` : ""}`;
  if (clearButton) clearButton.disabled = !runtimeConfigured;
}

async function keepOfflineAgentMode() {
  const agent = state.factorConfigMeta?.agent || {};
  if (agent.credential_source === "runtime") {
    await clearAgentApiKey();
  } else if (agent.available) {
    setAgentCredentialChoice(false);
    renderAgentCredentialStatus("当前在线 Agent 由服务端环境变量启用；移除该环境变量并重启服务后可恢复离线模式。");
  } else {
    setAgentCredentialChoice(false);
    renderAgentCredentialStatus("已保持离线完整演示模式；需要时可随时选择输入 API Key。", "ok");
  }
}

async function saveAgentApiKey() {
  const input = $("#agentApiKey");
  const button = $("#btnSaveAgentKey");
  const apiKey = input?.value?.trim() || "";
  if (!apiKey) {
    renderAgentCredentialStatus("请输入 DeepSeek API Key，或保持当前离线缓存模式。", "error");
    return;
  }
  setBusy(button, true);
  try {
    const result = await api("/api/agent/credentials", {
      method: "PUT",
      body: JSON.stringify({ api_key: apiKey }),
    });
    state.factorConfigMeta = {
      ...(state.factorConfigMeta || {}),
      agent: {
        ...(state.factorConfigMeta?.agent || {}),
        ...(result.agent || {}),
      },
    };
    renderFactorAgentMode();
    renderAgentCredentialStatus("在线 Agent 已启用；密钥将在服务重启时自动清除。", "ok");
    setAgentCredentialChoice(true);
  } catch (error) {
    renderAgentCredentialStatus(`启用失败：${error.message}`, "error");
  } finally {
    if (input) input.value = "";
    setBusy(button, false);
  }
}

async function clearAgentApiKey() {
  const input = $("#agentApiKey");
  const button = $("#btnClearAgentKey");
  setBusy(button, true);
  try {
    const result = await api("/api/agent/credentials", { method: "DELETE" });
    state.factorConfigMeta = {
      ...(state.factorConfigMeta || {}),
      agent: {
        ...(state.factorConfigMeta?.agent || {}),
        ...(result.agent || {}),
      },
    };
    renderFactorAgentMode();
    const message = result.agent?.available
      ? "页面输入的密钥已清除；当前仍使用服务端环境变量配置。"
      : "页面输入的密钥已清除，已恢复内置离线 Agent 缓存。";
    renderAgentCredentialStatus(message, "ok");
    setAgentCredentialChoice(!!result.agent?.available);
  } catch (error) {
    renderAgentCredentialStatus(`清除失败：${error.message}`, "error");
  } finally {
    if (input) input.value = "";
    setBusy(button, false);
  }
}

function renderFactorConversation() {
  const box = $("#factorChatMessages");
  if (!box) return;
  const messages = state.factorConversation.length
    ? state.factorConversation
    : [{
        role: "assistant",
        content: "请选择风险偏好和关注目标，或直接描述你的投资需求。我会先给出配置建议，不会自动执行回测。",
      }];
  box.innerHTML = messages
    .map((message) => `
      <div class="factor-chat-bubble ${message.role === "user" ? "user" : "assistant"}">
        <span>${message.role === "user" ? "你" : "Agent"}</span>
        <p>${escapeHtml(message.content)}</p>
      </div>`)
    .join("");
  box.scrollTop = box.scrollHeight;
}

function renderFactorPreferences() {
  $$(".factor-chip").forEach((button) => {
    const key = button.dataset.prefKey;
    const value = button.dataset.prefValue;
    const selected = state.factorPreferences[key];
    const active = Array.isArray(selected) ? selected.includes(value) : selected === value;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function toggleFactorPreference(button) {
  const key = button.dataset.prefKey;
  const value = button.dataset.prefValue;
  if (!key || !value) return;
  if (button.dataset.exclusive === "true") {
    state.factorPreferences[key] = state.factorPreferences[key] === value ? null : value;
  } else {
    const selected = new Set(state.factorPreferences[key] || []);
    if (selected.has(value)) selected.delete(value);
    else selected.add(value);
    state.factorPreferences[key] = [...selected];
  }
  renderFactorPreferences();
}

function factorRoleMeta(role) {
  return (state.factorConfigMeta?.roles || []).find((item) => item.role === role) || {
    role,
    factors: [],
    module_params: {},
  };
}

function setFactorConfigStatus(message, type = "") {
  const box = $("#factorConfigStatus");
  if (!box) return;
  box.textContent = message;
  box.className = `factor-config-status${type ? ` ${type}` : ""}`;
}

function renderFactorConfigCards() {
  const box = $("#factorRoleCards");
  if (!box || !state.factorConfig) return;
  const roles = state.factorConfigMeta?.roles || Object.keys(state.factorConfig.roles || {}).map((role) => ({ role, factors: [] }));
  box.innerHTML = roles
    .map((meta) => {
      const cfg = state.factorConfig.roles?.[meta.role] || {};
      const weights = cfg.factor_weights || {};
      const knownFactors = meta.factors?.length ? meta.factors : Object.keys(weights).map((key) => ({ key, label: key }));
      const factors = knownFactors
        .map((factor) => {
          const value = Number(weights[factor.key] || 0) * 100;
          const preference = factor.preference || (Number(factor.direction || 1) < 0 ? "低值优先" : "高值优先");
          const directionClass = Number(factor.direction || 1) < 0 ? "negative" : "positive";
          const info = explainButton(buildFactorExplanation(meta.role, factor, cfg));
          return `<li title="${escapeHtml(factor.description || "")}">
            <span>${escapeHtml(factor.label || factor.key)} <small class="factor-direction ${directionClass}">${escapeHtml(preference)}</small></span>
            <span class="metric-value-with-info"><strong>${value.toFixed(1)}%</strong>${info}</span>
          </li>`;
        })
        .join("");
      const params = Object.entries(cfg.module_params || {})
        .map(([key, value]) => {
          const display = typeof value === "number" ? value.toFixed(3) : value;
          return `<span class="metric-value-with-info">${escapeHtml(key)}=${escapeHtml(display)}${explainButton(buildModuleParamExplanation(meta.role, key, value))}</span>`;
        })
        .join("");
      return `
        <article class="factor-role-card">
          <div class="factor-role-head">
            <strong>${escapeHtml(meta.role)}</strong>
            <span class="factor-role-state">${cfg.enabled === false ? "已停用" : "已启用"}</span>
          </div>
          <ul class="factor-weight-list">${factors}</ul>
          ${params ? `<div class="factor-module-params">${params}</div>` : ""}
        </article>`;
    })
    .join("");
}

function renderFactorProposal(proposal) {
  const box = $("#factorProposalPreview");
  const apply = $("#btnFactorApply");
  if (!box) return;
  if (!proposal) {
    box.classList.add("hidden");
    if (apply) apply.disabled = true;
    return;
  }
  const changes = proposal.changes || [];
  const rows = changes
    .map((change) => {
      const label = change.factor ? `${change.role} · ${change.label || change.factor}` : `${change.role} · ${change.parameter}`;
      const oldValue = change.factor ? `${(Number(change.old_weight || 0) * 100).toFixed(1)}%` : Number(change.old_value).toFixed(3);
      const newValue = change.factor ? `${(Number(change.new_weight || 0) * 100).toFixed(1)}%` : Number(change.new_value).toFixed(3);
      const metaFactor = factorRoleMeta(change.role).factors?.find((factor) => factor.key === change.factor);
      const factorDirection = Number(change.direction ?? metaFactor?.direction ?? 1);
      const direction = change.factor
        ? `<small class="factor-direction ${factorDirection < 0 ? "negative" : "positive"}">${factorDirection < 0 ? "低值优先" : "高值优先"}</small>`
        : "";
      const info = explainButton(buildFactorChangeExplanation(change, proposal));
      return `<tr><td>${escapeHtml(label)} ${direction}</td><td>${oldValue}</td><td><span class="metric-value-with-info">${newValue}${info}</span></td><td>${escapeHtml(change.reason || "")}</td></tr>`;
    })
    .join("");
  const changeTable = rows
    ? `<div class="factor-proposal-table"><table><thead><tr><th>项目</th><th>当前</th><th>建议</th><th>原因</th></tr></thead><tbody>${rows}</tbody></table></div>`
    : '<p class="note">没有可执行的变更，当前配置保持不变。</p>';
  const audit = proposal.audit || {};
  const llmCall = audit.llm_call || {};
  const auditDetails = audit.audit_id
    ? `审计号 ${escapeHtml(audit.audit_id)} · 配置 ${escapeHtml(audit.config_before || "—")} → ${escapeHtml(audit.config_after || "—")}${llmCall.attempts ? ` · 模型请求${llmCall.attempts}次 / ${Number(llmCall.duration_ms || 0).toFixed(0)}ms` : ""}`
    : "";
  box.innerHTML = `
    <div class="factor-proposal-head">
      <h4>配置调整建议</h4>
      <span class="agent-badge ${proposal.source === "deepseek" ? "online" : "fallback"}">${proposal.source === "deepseek" ? `DeepSeek · ${escapeHtml(proposal.model || "deepseek-chat")}` : proposal.source === "agent_cache" ? "预置Agent响应 · 离线" : proposal.source === "rule_fallback" ? "规则回退" : "规则模式"}</span>
    </div>
    <p>${escapeHtml(proposal.summary || "")}</p>
    ${proposal.clarification_needed && proposal.clarification_question ? `<div class="factor-clarification"><strong>需要补充：</strong>${escapeHtml(proposal.clarification_question)}</div>` : ""}
    ${changeTable}
    ${proposal.fallback_reason ? `<p class="note factor-fallback-note">DeepSeek未生效：${escapeHtml(proposal.fallback_reason)}。当前建议来自规则兜底。</p>` : ""}
    ${auditDetails ? `<p class="note" style="margin:0.55rem 0 0">${auditDetails}</p>` : ""}
    <p class="note" style="margin:0.55rem 0 0">配置仍未应用到回测；只有人工确认后，下一次实时回测才会使用该方案。</p>
  `;
  box.classList.remove("hidden");
  if (apply) apply.disabled = !proposal.config || !changes.length || proposal.clarification_needed;
}

async function loadFactorConfigMeta() {
  try {
    const data = await api("/api/agent/factor-config");
    state.factorConfigMeta = data;
    state.factorConfig = cloneJson(data.default_config);
    state.factorDefaultConfig = cloneJson(data.default_config);
    state.factorConfigProposal = null;
    renderFactorConfigCards();
    renderFactorProposal(null);
    renderFactorAgentMode();
    renderFactorConversation();
    renderFactorPreferences();
    setFactorConfigStatus("示例偏好已预选；点击“生成我的方案建议”，检查并确认后即可进入实时回测。", "ok");
  } catch (e) {
    setFactorConfigStatus(`因子配置加载失败：${e.message}`, "error");
  }
}

async function proposeFactorConfig() {
  const btn = $("#btnFactorPropose");
  const text = $("#factorAgentText")?.value?.trim() || "";
  const activePreferences = Object.fromEntries(
    Object.entries(state.factorPreferences).filter(([, value]) =>
      Array.isArray(value) ? value.length : Boolean(value)
    )
  );
  if (!text && !Object.keys(activePreferences).length) {
    setFactorConfigStatus("请先选择偏好，或描述希望调整的投资方案。", "error");
    return;
  }
  const userMessage = text || `请根据我的快捷选择生成投资方案：${JSON.stringify(activePreferences)}`;
  const history = state.factorConversation.slice(-8);
  state.factorConversation.push({ role: "user", content: userMessage });
  renderFactorConversation();
  setBusy(btn, true);
  try {
    const useLlm = state.factorConfigMeta?.agent?.available === true
      || state.factorConfigMeta?.agent?.offline_cache?.available === true;
    const proposal = await api("/api/agent/factor-config", {
      method: "POST",
      body: JSON.stringify({
        text: userMessage,
        current_config: state.factorConfig,
        messages: history,
        quick_preferences: activePreferences,
        mode: useLlm ? "llm" : "mock",
      }),
    });
    state.factorConfigProposal = proposal;
    const replyParts = [proposal.assistant_message || proposal.summary || "已生成建议。"];
    if (proposal.clarification_needed && proposal.clarification_question) {
      replyParts.push(proposal.clarification_question);
    }
    state.factorConversation.push({ role: "assistant", content: replyParts.join("\n") });
    if ($("#factorAgentText")) $("#factorAgentText").value = "";
    renderFactorConversation();
    renderFactorProposal(proposal);
    if (proposal.clarification_needed) {
      setFactorConfigStatus("Agent需要补充信息，当前配置尚未改变。", "pending");
      setGuidedStage("preferences", { body: "Agent还需要更明确的信息。请回答对话中的问题，再次生成方案建议。" });
    } else if (proposal.source === "deepseek") {
      setFactorConfigStatus("DeepSeek已生成结构化建议，等待人工确认。", "pending");
    } else if (proposal.source === "agent_cache") {
      setFactorConfigStatus("已加载并重新校验预置Agent响应，等待人工确认。", "pending");
    } else if (proposal.source === "rule_fallback") {
      setFactorConfigStatus("DeepSeek不可用，已明确切换到规则建议；等待人工确认。", "pending");
    } else {
      setFactorConfigStatus("规则Agent已生成建议，等待人工确认。", "pending");
    }
    if (!proposal.clarification_needed) {
      setGuidedStage("confirm");
      window.setTimeout(() => scrollToGuideTarget("factorProposalPreview", "center"), 120);
    }
  } catch (e) {
    state.factorConversation.push({ role: "assistant", content: `本次建议生成失败：${e.message}` });
    renderFactorConversation();
    setFactorConfigStatus(`生成建议失败：${e.message}`, "error");
  } finally {
    setBusy(btn, false);
  }
}

function applyFactorConfigProposal() {
  const proposal = state.factorConfigProposal;
  if (!proposal?.config) return;
  state.factorConfig = cloneJson(proposal.config);
  state.factorConfig.provenance = {
    source: proposal.source || "unknown",
    model: proposal.model || null,
    confirmed_at: new Date().toISOString(),
    summary: proposal.summary || null,
  };
  state.factorConfigAudit = {
    confirmed_at: state.factorConfig.provenance.confirmed_at,
    source: proposal.source,
    model: proposal.model,
    summary: proposal.summary,
    changes: cloneJson(proposal.changes || []),
    conversation: cloneJson(state.factorConversation.slice(-10)),
    agent_audit: cloneJson(proposal.audit || {}),
  };
  state.factorConfigProposal = null;
  renderFactorConfigCards();
  renderFactorProposal(null);
  state.factorConversation.push({
    role: "assistant",
    content: `配置 ${state.factorConfig.config_id || "custom"} 已经你确认。下一次实时回测将使用该客户方案。`,
  });
  renderFactorConversation();
  setFactorConfigStatus(`客户方案已确认：${state.factorConfig.config_id || "custom"}。下一次实时回测将使用该配置。`, "ok");
  if ($("#guidedConfigNote")) {
    $("#guidedConfigNote").textContent = `已确认客户方案 ${state.factorConfig.config_id || "custom"}；“运行我的方案回测”将使用这套因子配置。`;
  }
  setGuidedStage("backtest");
  window.setTimeout(() => scrollToGuideTarget("guidedBacktestActions", "center"), 120);
}

function resetFactorConfig() {
  const defaults = state.factorDefaultConfig || state.factorConfigMeta?.default_config;
  if (!defaults) return;
  state.factorConfig = cloneJson(defaults);
  state.factorConfigProposal = null;
  state.factorConfigAudit = null;
  renderFactorConfigCards();
  renderFactorProposal(null);
  state.factorConversation.push({ role: "assistant", content: "已恢复默认等权方案。" });
  renderFactorConversation();
  setFactorConfigStatus("已恢复默认等权方案。", "ok");
  if ($("#guidedConfigNote")) {
    $("#guidedConfigNote").textContent = "完成“生成建议 → 人工确认”后解锁；专业模式也可直接使用默认等权方案。";
  }
  setGuidedStage("preferences");
}

function clearFactorConversation() {
  state.factorConversation = [];
  state.factorPreferences = {};
  state.factorConfigProposal = null;
  renderFactorConversation();
  renderFactorPreferences();
  renderFactorProposal(null);
  setFactorConfigStatus(
    state.factorConfigAudit
      ? `当前仍应用已确认方案：${state.factorConfig?.config_id || "custom"}。`
      : "对话已清空，当前配置未改变。",
    "ok"
  );
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
    sel.value = presets.some((preset) => preset.id === "demo_roadshow_2024h2_2025h1")
      ? "demo_roadshow_2024h2_2025h1"
      : "";
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
    state.agentEvidence = cloneJson(res.report?.evidence || []);
    state.agentTrust = cloneJson(res.report?.trust || null);
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
  const res = await fetch(`/static/demo/backtest_demo.json?v=${Date.now()}`, {
    cache: "no-store",
  });
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
  state.backtestComparison = null;
  $("#backtestPlanComparison")?.classList.add("hidden");
  if ($("#backtestPlanComparison")) $("#backtestPlanComparison").innerHTML = "";
  $("#backtestSummary").classList.add("hidden");
  $("#backtestConclusion")?.classList.add("hidden");
  $("#backtestTechDivider")?.classList.add("hidden");
  $("#backtestEvidenceCharts")?.classList.add("hidden");
  $("#dualTrackResultWrap")?.classList.add("hidden");
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
      metric: pt.metric || "角色Shapley超额贡献",
      current: pt.index,
      total,
      percent: 72 + Math.floor(((pt.index || 0) / total) * 18),
    });
    await sleep(pace.shapley);
  }

  setBacktestProgress(100, "计算完成，正在生成业务结论…", "complete");
  await sleep(900);
}

async function finalizeBacktestResults(data, { staged = false, roadshow = false } = {}) {
  state.backtestResult = data;
  state.dualPoolConfirmed = false;
  state.agentEvidence = [];
  state.agentTrust = null;
  // 每次成功回测都生成可信证据编号；mock解读不调用外部LLM。
  await interpretBacktestWithAgent(data);

  const useStaged =
    staged || data._source === "demo" || data._source === "cache";

  if (!state.backtestStreamPopulated && data.demo_replay) {
    await playClientDemoReplay(
      data.demo_replay,
      roadshow ? ROADSHOW_PACE : DEMO_REPLAY_PACE
    );
  }

  const revealDelay = roadshow ? ROADSHOW_PACE.finalizeReveal : 900;
  const techDelay = roadshow ? ROADSHOW_PACE.finalizeTech : 1400;

  if (useStaged) {
    await sleep(revealDelay);
    renderBacktestConclusion(data, { showTechDivider: false });
    focusBacktestStage("complete");
    const conclusion = $("#backtestConclusion");
    conclusion?.classList.remove("reveal-in");
    void conclusion?.offsetWidth;
    conclusion?.classList.add("reveal-in");
    updateBacktestNarrative("complete");
    if (roadshow) {
      showRoadshowLine("第1步 · 结论摘要", buildConclusionNarration(data), 1);
    }
    if (!roadshow) {
      await sleep(techDelay);
      renderBacktestTechDetails(data);
      const techBlocks = document.querySelectorAll(".backtest-tech-block");
      techBlocks.forEach((el, i) => {
        setTimeout(() => el.classList.add("reveal-in"), i * 120);
      });
    }
    renderDualPoolPanel();
  } else {
    renderHs300Backtest(data);
    renderDualPoolPanel();
  }
  if (data.comparison) {
    state.backtestComparison = cloneJson(data.comparison);
    renderPlanComparison(state.backtestComparison);
  }
  setGuidedStage("apply");
}

async function attachLatestDemoComparison(data) {
  if (data?.comparison) return data;
  try {
    const latest = await fetchDemoPayloadStatic();
    if (latest?.comparison) data.comparison = cloneJson(latest.comparison);
  } catch (error) {
    appendBacktestLog(`三方预制对照加载失败：${error.message}`);
  }
  return data;
}

async function runBacktestDemo(options = {}) {
  const roadshow = options.roadshow || false;
  const btnDemo = $("#btnBacktestDemo");
  const btnLive = $("#btnBacktest");
  const guidedBtn = $("#btnGuidedDemo");
  setGuidedStage("backtest", { body: "正在加载预置数据并执行五角色归因，请跟随下方进度查看每一步在做什么。" });
  setBusy(btnDemo, true);
  setBusy(btnLive, true);
  setBusy(guidedBtn, true);
  prepareBacktestUI();
  updateBacktestNarrative("parse");
  setBacktestStatus(
    roadshow ? "一键路演：加载 HS300 五角色贡献证据…" : "路演演示：加载官方预置结果…",
    "running"
  );
  updateBacktestModeHint(roadshow ? "75秒路演模式" : "路演模式");

  const started = Date.now();
  try {
    let data;
    if (roadshow) {
      // 75秒路演：纯客户端节奏重播，避免 SSE 秒开跳过动画
      data = await fetchDemoPayload();
      state.backtestStreamPopulated = false;
    } else {
      try {
        data = await runBacktestStream({ demo_mode: true, query: {} });
      } catch (apiErr) {
        appendBacktestLog(`API 不可用，切换离线演示包：${apiErr.message}`);
        data = await fetchDemoPayloadStatic();
        await playClientDemoReplay(data.demo_replay, DEMO_REPLAY_PACE);
      }
    }
    const elapsed = ((Date.now() - started) / 1000).toFixed(1);
    setBacktestStatus(
      `${backtestSourceLabel(data)} · ${data.demo_label || data.query_summary || ""} · ${elapsed}s`,
      "ok"
    );
    data = await attachLatestDemoComparison(data);
    await finalizeBacktestResults(data, { staged: true, roadshow });
  } catch (e) {
    setBacktestProgress(0, "演示加载失败", "complete");
    setBacktestStatus(`演示失败：${e.message}`, "error");
    appendBacktestLog(`ERROR: ${e.message}`);
  } finally {
    setBusy(btnDemo, false);
    setBusy(btnLive, false);
    setBusy(guidedBtn, false);
    setBacktestRunning(false);
  }
}

async function runHs300Backtest() {
  const btn = $("#btnBacktest");
  const btnDemo = $("#btnBacktestDemo");
  const guidedBtn = $("#btnGuidedBacktest");
  setGuidedStage("backtest", { body: "正在使用当前确认的因子配置执行实时回测。运行期间可以查看下方步骤说明。" });
  setBusy(btn, true);
  setBusy(btnDemo, true);
  setBusy(guidedBtn, true);
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
    if (state.factorDefaultConfig) {
      await loadDefaultPlanComparison(data, payload);
    } else {
      state.backtestComparison = {
        loading: false,
        error: "默认方案配置尚未加载，无法生成同口径对照",
      };
      renderPlanComparison(state.backtestComparison);
    }
  } catch (e) {
    clearBacktestTimer();
    setBacktestProgress(0, "回测失败", "complete");
    setBacktestStatus(`回测失败：${e.message}`, "error");
    appendBacktestLog(`ERROR: ${e.message}`);
  } finally {
    setBusy(btn, false);
    setBusy(btnDemo, false);
    setBusy(guidedBtn, false);
    setBacktestRunning(false);
  }
}

function renderBacktestTechDetails(data) {
  const results = data.results || {};
  const ov = results.overview || {};
  const breakdown = results.role_breakdown || [];
  const rec = results.recommendation || {};
  const highlights = results.highlights || [];
  const appliedFactorConfig = results.factor_config;
  if (breakdown.length) {
    $("#backtestEvidenceCharts")?.classList.remove("hidden");
  } else {
    $("#backtestEvidenceCharts")?.classList.add("hidden");
  }

  const totalInfo = explainButton(buildOverviewExplanation("total_return", data), { compact: false });
  const benchmarkInfo = explainButton(buildOverviewExplanation("benchmark_return", data), { compact: false });
  const excessInfo = explainButton(buildOverviewExplanation("excess_return", data), { compact: false });
  const sharpeInfo = explainButton(buildOverviewExplanation("sharpe_ratio", data), { compact: false });
  const drawdownInfo = explainButton(buildOverviewExplanation("max_drawdown", data));
  $("#backtestOverview").innerHTML = `
    <div class="metric-card">
      <div class="label metric-label-with-info">组合收益${totalInfo}</div>
      <div class="value">${((ov.total_return || 0) * 100).toFixed(2)}%</div>
      <div class="sub">${ov.total_return_desc || ""}</div>
    </div>
    <div class="metric-card">
      <div class="label metric-label-with-info">基准收益${benchmarkInfo}</div>
      <div class="value">${((ov.benchmark_return || 0) * 100).toFixed(2)}%</div>
      <div class="sub">${ov.benchmark_return_desc || ""}</div>
    </div>
    <div class="metric-card">
      <div class="label metric-label-with-info">超额收益${excessInfo}</div>
      <div class="value">${((ov.excess_return || 0) * 100).toFixed(2)}%</div>
      <div class="sub">${ov.excess_return_desc || ""}</div>
    </div>
    <div class="metric-card">
      <div class="label metric-label-with-info">夏普比率${sharpeInfo}</div>
      <div class="value">${(ov.sharpe_ratio || 0).toFixed(2)}</div>
      <div class="sub">${ov.sharpe_ratio_desc || ""} · <span class="metric-value-with-info">${ov.max_drawdown_desc || ""}${drawdownInfo}</span></div>
    </div>
  `;
  $("#backtestOverview").classList.remove("hidden");
  $("#backtestOverview").classList.add("backtest-tech-block");

  const roles = breakdown.map((r) => r.role);
  const weights = breakdown.map((r) => (r.weight || 0) * 100);
  const shapleys = breakdown.map((r) => (r.shapley_raw || r.contribution_raw || 0) * 100);
  const shortRoles = roles.map((r) => ROLE_SHORT[r] || r);

  const weightWrap = $("#backtestWeightChart")?.closest(".chart-wrap");
  weightWrap?.classList.add("backtest-tech-block");
  setChartExplanation(weightWrap, {
    title: "角色证据轨建议权重图",
    current: roles.map((role, i) => `${role} ${weights[i].toFixed(1)}%`).join("；"),
    definition: "将各角色正向夏普利贡献归一化并应用单角色50%上限后的权重对比。",
    formula: "scoreᵢ=max(φᵢ,0)×角色调节系数；水位法归一化，单角色≤50%，合计100%",
    calculation: roles.map((role, i) => `${role} ${weights[i].toFixed(1)}%`).join("；"),
    ...backtestTrace(data), sourcePath: "results.role_breakdown[].weight",
  });
  setEChart("btWeight", "#backtestWeightChart", {
    title: {
      text: "各角色证据轨建议权重",
      left: "center",
      textStyle: { color: CHART.ink, fontSize: 13 },
    },
    tooltip: { trigger: "axis", valueFormatter: (v) => `${Number(v).toFixed(1)}%` },
    grid: { left: 48, right: 16, top: 40, bottom: 40 },
    xAxis: { type: "category", data: shortRoles, ...ecAxis({ splitLine: { show: false } }) },
    yAxis: {
      type: "value",
      axisLabel: { color: CHART.muted, formatter: "{value}%" },
      splitLine: { lineStyle: { color: CHART.grid } },
    },
    series: [{
      type: "bar",
      data: weights.map((v, i) => ({
        value: v,
        itemStyle: { color: roleColor(roles[i], 1), borderRadius: [4, 4, 0, 0] },
      })),
      barMaxWidth: 40,
    }],
  });

  const shapleyWrap = $("#backtestShapleyChart")?.closest(".chart-wrap");
  shapleyWrap?.classList.add("backtest-tech-block");
  setChartExplanation(shapleyWrap, {
    title: "角色夏普利边际贡献图",
    current: roles.map((role, i) => `${role} ${shapleys[i] >= 0 ? "+" : ""}${shapleys[i].toFixed(2)}%`).join("；"),
    definition: "每个柱表示该角色跨全部联盟的平均边际超额贡献，负值表示在本区间形成拖累。",
    formula: "φᵢ=Σ权重(S)×[v(S∪{i})-v(S)]；v(S)=R(S)-R(沪深300)",
    calculation: `31个非空联盟完成回测；五角色贡献合计 ${percentText(ov.excess_return, 2, true)}。`,
    ...backtestTrace(data), sourcePath: "results.role_breakdown[].shapley_raw",
  });
  setEChart("btShapley", "#backtestShapleyChart", {
    title: {
      text: "各角色夏普利边际贡献（瀑布）",
      left: "center",
      textStyle: { color: CHART.ink, fontSize: 13 },
    },
    tooltip: { trigger: "axis", valueFormatter: (v) => `${Number(v).toFixed(2)}%` },
    grid: { left: 48, right: 16, top: 40, bottom: 40 },
    xAxis: { type: "category", data: shortRoles, ...ecAxis({ splitLine: { show: false } }) },
    yAxis: {
      type: "value",
      axisLabel: { color: CHART.muted, formatter: "{value}%" },
      splitLine: { lineStyle: { color: CHART.grid } },
    },
    series: [{
      type: "bar",
      data: shapleys.map((v, i) => ({
        value: v,
        itemStyle: {
          color: v >= 0 ? roleColor(roles[i], 0.9) : "rgba(251,113,133,0.75)",
          borderRadius: [4, 4, 0, 0],
        },
      })),
      barMaxWidth: 40,
    }],
  });

  // 6:4 双轨对比（证据舱）
  const dualWrap = $("#dualTrackResultWrap");
  const baseline = getDualPoolBaseline();
  if (dualWrap && roles.length) {
    dualWrap.classList.remove("hidden");
    const oldW = roles.map((r) => (baseline[r] || 0) * 100);
    const newW = weights;
    const finalW = roles.map((_, i) => OLD_POOL_RATIO * oldW[i] + NEW_POOL_RATIO * newW[i]);
    setChartExplanation(dualWrap, {
      title: "6:4双轨合成对照图",
      current: roles.map((role, i) => `${role} ${finalW[i].toFixed(1)}%`).join("；"),
      definition: "逐角色比较制度轨输入、证据轨建议和两者按6:4形成的合成锚点。",
      formula: "合成份额 = 60% × 制度轨现行份额 + 40% × 证据轨建议份额",
      calculation: roles.map((role, i) => `${role}: 60%×${oldW[i].toFixed(1)}% + 40%×${newW[i].toFixed(1)}% = ${finalW[i].toFixed(1)}%`).join("；"),
      ...backtestTrace(data), sourcePath: "frontend.dualTrackResult",
    });
    setEChart("btDualTrack", "#backtestDualTrackChart", {
      title: {
        text: "6:4 双轨合成对照（制度轨 vs 证据轨 vs 合成）",
        left: "center",
        textStyle: { color: CHART.ink, fontSize: 13 },
      },
      legend: { bottom: 0, textStyle: { color: CHART.muted } },
      tooltip: { trigger: "axis", valueFormatter: (v) => `${Number(v).toFixed(1)}%` },
      grid: { left: 48, right: 16, top: 44, bottom: 52 },
      xAxis: { type: "category", data: shortRoles, ...ecAxis({ splitLine: { show: false } }) },
      yAxis: {
        type: "value",
        axisLabel: { color: CHART.muted, formatter: "{value}%" },
        splitLine: { lineStyle: { color: CHART.grid } },
      },
      series: [
        { name: "制度轨现行", type: "bar", data: oldW, itemStyle: { color: "rgba(139,155,176,0.55)" } },
        { name: "证据轨建议", type: "bar", data: newW, itemStyle: { color: "#5b8def" } },
        {
          name: "6:4 合成",
          type: "bar",
          data: finalW,
          itemStyle: { color: "#22d3ee", borderRadius: [4, 4, 0, 0] },
        },
      ],
    });
  }

  updateShapleyRing(31, 31);
  const hl = highlights.map((h) => `<li>${h.text || h}</li>`).join("");
  $("#backtestSummary").innerHTML = `
    <h3>结论摘要</h3>
    <p><strong>${rec.summary || data.query_summary || ""}</strong></p>
    ${hl ? `<ul class="attr-experiments">${hl}</ul>` : ""}
    ${appliedFactorConfig ? `<p class="note">本次实时回测生效配置：<strong>${escapeHtml(appliedFactorConfig.config_id || "custom")}</strong> · 配置版本 ${escapeHtml(appliedFactorConfig.version || 1)}</p>` : ""}
    ${results.allocation_policy?.cap_relaxed ? `<p class="note"><strong>权重上限已透明放宽：</strong>配置上限 ${(finiteNumber(results.allocation_policy.configured_max_role_weight) * 100).toFixed(0)}%，本次实际上限 ${(finiteNumber(results.allocation_policy.effective_max_role_weight) * 100).toFixed(0)}%；原因是正贡献角色不足，且负贡献角色不进入证据轨建议权重。</p>` : ""}
    <p class="note">${ov.attribution_description || ""} · ${data.query_summary || ""}</p>
  `;
  $("#backtestSummary").classList.remove("hidden");
  $("#backtestSummary").classList.add("backtest-tech-block");

  const rows = breakdown
    .map((r) => {
      const weightInfo = explainButton(buildRoleExplanation(r, "weight", data));
      const shapleyInfo = explainButton(buildRoleExplanation(r, "shapley_raw", data));
      const relativeInfo = explainButton(buildRoleExplanation(r, "contribution_relative", data));
      return `<tr>
        <td>${r.role}${r.is_target ? " ★" : ""}</td>
        <td><span class="metric-value-with-info">${((r.weight || 0) * 100).toFixed(1)}%${weightInfo}</span></td>
        <td><span class="metric-value-with-info">${((r.shapley_raw || 0) * 100).toFixed(2)}%${shapleyInfo}</span></td>
        <td><span class="metric-value-with-info">${((r.contribution_relative || 0) * 100).toFixed(1)}%${relativeInfo}</span></td>
        <td>${r.highlight || ""}</td>
      </tr>`;
    })
    .join("");
  $("#backtestTable").innerHTML = `
    <table>
      <thead>
        <tr>
          <th>角色</th><th>证据轨建议权重</th><th>夏普利超额贡献</th><th>相对贡献</th><th>说明</th>
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
  document.querySelectorAll(".backtest-tech-block").forEach((el) => {
    el.classList.add("reveal-in");
  });
}

function compoundedReturn(rows, key) {
  return (rows || []).reduce((nav, row) => nav * (1 + Number(row?.[key] || 0)), 1) - 1;
}

function monthlySeriesStats(rows, key) {
  const values = (rows || [])
    .map((row) => Number(row?.[key]))
    .filter((value) => Number.isFinite(value));
  if (!values.length) return { total_return: null, sharpe_ratio: null, max_drawdown: null };
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance = values.length > 1
    ? values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (values.length - 1)
    : 0;
  const deviation = Math.sqrt(variance);
  const totalReturn = compoundedReturn(rows, key);
  const annualReturn = (1 + totalReturn) ** (12 / values.length) - 1;
  const annualVolatility = deviation * Math.sqrt(12);
  let nav = 1;
  let peak = 1;
  let maxDrawdown = 0;
  for (const value of values) {
    nav *= 1 + value;
    peak = Math.max(peak, nav);
    maxDrawdown = Math.min(maxDrawdown, nav / peak - 1);
  }
  return {
    total_return: totalReturn,
    sharpe_ratio: annualVolatility > 0 ? (annualReturn - 0.02) / annualVolatility : null,
    max_drawdown: maxDrawdown,
  };
}

function comparisonValue(value, kind) {
  if (!Number.isFinite(value)) return "—";
  return kind === "ratio" ? value.toFixed(2) : `${(value * 100).toFixed(2)}%`;
}

function cumulativeComparisonSeries(rows, periods, key = "return") {
  const values = new Map((rows || []).map((row) => [String(row.period), Number(row?.[key] || 0)]));
  let nav = 1;
  return periods.map((period) => {
    nav *= 1 + (values.get(period) || 0);
    return Number(((nav - 1) * 100).toFixed(4));
  });
}

function buildComparisonCurveData(comparison) {
  if (!comparison || comparison.loading || comparison.error) return null;
  const customerRows = comparison.customer_time_series || [];
  const defaultRows = comparison.default_time_series || [];
  const periods = [...new Set(
    [...customerRows, ...defaultRows]
      .map((row) => String(row?.period || ""))
      .filter(Boolean)
  )].sort();
  if (!periods.length) return null;
  return {
    labels: ["起点", ...periods],
    customer: [0, ...cumulativeComparisonSeries(customerRows, periods, "return")],
    baseline: [0, ...cumulativeComparisonSeries(defaultRows, periods, "return")],
    benchmark: [0, ...cumulativeComparisonSeries(customerRows, periods, "benchmark")],
  };
}

function renderPlanComparisonChart(comparison) {
  const chart = $("#planComparisonChart");
  if (!chart || !comparison || comparison.loading || comparison.error) return;
  const curves = buildComparisonCurveData(comparison);
  if (!curves) {
    chart.innerHTML = '<p class="plan-comparison-chart-empty">暂无可绘制的月度收益序列</p>';
    return;
  }

  const newColor = currentTheme() === "dark" ? "#22d3ee" : "#087f6b";
  const defaultColor = currentTheme() === "dark" ? "#fbbf24" : "#b7791f";
  const benchmarkColor = currentTheme() === "dark" ? "#a78bfa" : "#5b5bd6";

  setEChart("planComparison", chart, {
    animationDuration: 700,
    tooltip: {
      trigger: "axis",
      valueFormatter: (value) => `${Number(value).toFixed(2)}%`,
    },
    legend: {
      top: 2,
      right: 8,
      textStyle: { color: CHART.muted },
      data: ["新策略", "原始默认策略", "HS300"],
    },
    grid: { left: 54, right: 22, top: 44, bottom: 38 },
    xAxis: {
      type: "category",
      data: curves.labels,
      boundaryGap: false,
      ...ecAxis({ splitLine: { show: false } }),
    },
    yAxis: {
      type: "value",
      axisLabel: { color: CHART.muted, formatter: "{value}%" },
      splitLine: { lineStyle: { color: CHART.grid } },
    },
    series: [
      {
        name: "新策略",
        type: "line",
        data: curves.customer,
        smooth: false,
        showSymbol: true,
        symbolSize: 7,
        lineStyle: { width: 3, color: newColor },
        itemStyle: { color: newColor },
      },
      {
        name: "原始默认策略",
        type: "line",
        data: curves.baseline,
        smooth: false,
        showSymbol: true,
        symbolSize: 6,
        lineStyle: { width: 2.5, color: defaultColor },
        itemStyle: { color: defaultColor },
      },
      {
        name: "HS300",
        type: "line",
        data: curves.benchmark,
        smooth: false,
        showSymbol: true,
        symbolSize: 6,
        lineStyle: { width: 2.5, type: "dashed", color: benchmarkColor },
        itemStyle: { color: benchmarkColor },
      },
    ],
  });
}

function renderPlanComparison(comparison) {
  const panel = $("#backtestPlanComparison");
  if (!panel || !comparison) return;
  if (comparison.loading) {
    panel.innerHTML = '<p class="plan-comparison-loading">正在按同一回测口径生成默认方案对照…</p>';
    panel.classList.remove("hidden");
    return;
  }
  if (comparison.error) {
    panel.innerHTML = `<p class="plan-comparison-error">默认方案对照暂不可用：${escapeHtml(comparison.error)}</p>`;
    panel.classList.remove("hidden");
    return;
  }

  const customer = comparison.customer || {};
  const baseline = comparison.default || {};
  const benchmark = comparison.benchmark || {};
  const deltaReturn = Number(customer.total_return || 0) - Number(baseline.total_return || 0);
  const deltaExcess = Number(customer.excess_return || 0) - Number(baseline.excess_return || 0);
  const rows = [
    ["累计收益", "percent", customer.total_return, baseline.total_return, benchmark.total_return],
    ["相对沪深300超额", "percent", customer.excess_return, baseline.excess_return, 0],
    ["夏普比率", "ratio", customer.sharpe_ratio, baseline.sharpe_ratio, benchmark.sharpe_ratio],
    ["最大回撤", "percent", customer.max_drawdown, baseline.max_drawdown, benchmark.max_drawdown],
  ];
  const returnDeltaInfo = explainButton({
    title: "较默认方案收益变化", current: percentText(deltaReturn, 2, true),
    definition: "客户因子方案与原始默认等权因子方案的累计收益差。",
    formula: "收益变化 = 客户方案累计收益 - 默认方案累计收益",
    calculation: `${percentText(customer.total_return)} - ${percentText(baseline.total_return)} = ${percentText(deltaReturn, 2, true)}`,
    ...backtestTrace(), sourcePath: "comparison.customer.total_return - comparison.default.total_return",
    limitation: "仅说明本回测区间的配置差异，不代表未来收益改善。",
  });
  const excessDeltaInfo = explainButton({
    title: "较默认方案超额变化", current: percentText(deltaExcess, 2, true),
    definition: "客户方案与默认等权方案相对同一沪深300基准的超额收益差。",
    formula: "超额变化 = 客户方案超额收益 - 默认方案超额收益",
    calculation: `${percentText(customer.excess_return)} - ${percentText(baseline.excess_return)} = ${percentText(deltaExcess, 2, true)}`,
    ...backtestTrace(), sourcePath: "comparison.customer.excess_return - comparison.default.excess_return",
    limitation: "仅说明本回测区间的配置差异，不代表未来收益改善。",
  });
  const sourceLabel = comparison.source === "precomputed_verified_pair"
    ? "官方预制新策略 · 已验证"
    : comparison.current_is_default
      ? "当前即默认方案"
      : "同口径回测结果";
  panel.innerHTML = `
    <div class="plan-comparison-head">
      <div>
        <h3>新策略 / 默认策略 / HS300 平行对比</h3>
        <p>同一日期、股票范围、调仓频率与交易口径</p>
      </div>
      <span class="agent-badge online">${sourceLabel}</span>
    </div>
    <div class="plan-comparison-chart-head">
      <h4>累计收益路径</h4>
      <span>每月收益连续复利 · 起点归一为0%</span>
    </div>
    <div id="planComparisonChart" class="plan-comparison-chart" role="img" aria-label="新策略、原始默认策略和沪深300累计收益对比折线图"></div>
    <div class="plan-comparison-deltas">
      <div><span>较默认方案收益变化</span><span class="metric-value-with-info"><strong class="${deltaReturn >= 0 ? "positive" : "negative"}">${deltaReturn >= 0 ? "+" : ""}${(deltaReturn * 100).toFixed(2)}%</strong>${returnDeltaInfo}</span></div>
      <div><span>较默认方案超额变化</span><span class="metric-value-with-info"><strong class="${deltaExcess >= 0 ? "positive" : "negative"}">${deltaExcess >= 0 ? "+" : ""}${(deltaExcess * 100).toFixed(2)}%</strong>${excessDeltaInfo}</span></div>
    </div>
    <div class="table-wrap plan-comparison-table">
      <table>
        <thead><tr><th>指标</th><th>新策略（客户方案）</th><th>原始默认策略</th><th>沪深300</th></tr></thead>
        <tbody>${rows.map(([label, kind, a, b, c]) => `
          <tr><td><span class="metric-label-with-info">${label}${explainButton(buildComparisonExplanation(label, kind, a, b, c, comparison))}</span></td><td>${comparisonValue(a, kind)}</td><td>${comparisonValue(b, kind)}</td><td>${comparisonValue(c, kind)}</td></tr>
        `).join("")}</tbody>
      </table>
    </div>
    <p class="note">${comparison.source === "precomputed_verified_pair" ? "预制模式回放官方新策略与原始默认策略的成对真实回测；任意自定义参数请使用实时回测。" : "该对照用于验证个性化因子配置的实际差异。"} 不代表收益承诺，也不用于根据历史结果反复寻优。</p>
  `;
  panel.classList.remove("hidden");
  window.requestAnimationFrame(() => {
    renderPlanComparisonChart(comparison);
    updateNavLiveChart();
  });
}

async function loadDefaultPlanComparison(customerData, customerPayload) {
  const customerOverview = customerData?.results?.overview;
  if (!customerOverview) return;
  if (!state.factorDefaultConfig) {
    state.backtestComparison = { loading: false, error: "默认方案配置尚未加载" };
    renderPlanComparison(state.backtestComparison);
    return;
  }

  const currentConfig = customerData?.results?.factor_config || customerPayload?.query?.factor_config;
  const comparableConfig = (config) => {
    const roles = config?.roles || {};
    return Object.fromEntries(
      Object.keys(roles).sort().map((role) => [role, {
        enabled: roles[role]?.enabled !== false,
        factor_weights: roles[role]?.factor_weights || {},
        module_params: roles[role]?.module_params || {},
      }])
    );
  };
  if (JSON.stringify(comparableConfig(currentConfig)) === JSON.stringify(comparableConfig(state.factorDefaultConfig))) {
    const benchmark = monthlySeriesStats(customerData?.results?.time_series || [], "benchmark");
    state.backtestComparison = {
      loading: false,
      current_is_default: true,
      customer: customerOverview,
      default: customerOverview,
      benchmark,
      customer_time_series: customerData?.results?.time_series || [],
      default_time_series: customerData?.results?.time_series || [],
    };
    renderPlanComparison(state.backtestComparison);
    return;
  }
  state.backtestComparison = { loading: true };
  renderPlanComparison(state.backtestComparison);
  try {
    const defaultPayload = cloneJson(customerPayload);
    defaultPayload.request_id = `web_default_${Date.now()}`;
    defaultPayload.use_cache = true;
    defaultPayload.force_refresh = false;
    defaultPayload.query = defaultPayload.query || {};
    defaultPayload.query.factor_config = cloneJson(state.factorDefaultConfig);
    const defaultData = await api("/api/backtest/run", {
      method: "POST",
      body: JSON.stringify(defaultPayload),
    });
    const defaultOverview = defaultData?.results?.overview;
    if (!defaultOverview) throw new Error("默认方案结果缺少绩效指标");
    const benchmark = monthlySeriesStats(customerData?.results?.time_series || [], "benchmark");
    state.backtestComparison = {
      loading: false,
      customer: customerOverview,
      default: defaultOverview,
      benchmark,
      customer_time_series: customerData?.results?.time_series || [],
      default_time_series: defaultData?.results?.time_series || [],
      default_source: defaultData._source || "computed",
    };
    renderPlanComparison(state.backtestComparison);
  } catch (error) {
    state.backtestComparison = { loading: false, error: error.message || String(error) };
    renderPlanComparison(state.backtestComparison);
  }
}

async function refreshSensitivity() {
  await loadTargetControls();
}

async function runAll() {
  const btn = $("#btnRunAll");
  setBusy(btn, true);
  setRoadshowMode(true);
  const t0 = Date.now();

  try {
    showRoadshowLine(
      "路演开始",
      "本次演示回答三个问题：各岗位贡献多少？夏普利依据是什么？评审委员会如何基于6:4建议作出决策？",
      1
    );
    highlightDemoFlow("backtest");
    switchToTab("backtest");
    await sleep(ROADSHOW_PACE.intro);

    showRoadshowLine(
      "第1步 · 贡献计量",
      "加载 HS300 真实数据，启动五角色 Pipeline + 夏普利反事实回测…",
      1
    );
    await runBacktestDemo({ roadshow: true });

    $("#backtestConclusion")?.scrollIntoView({ behavior: "smooth", block: "center" });
    showRoadshowLine("第1步 · 结论摘要", buildConclusionNarration(state.backtestResult), 1);
    await sleep(ROADSHOW_PACE.conclusion);

    showRoadshowLine(
      "第2步 · 贡献评审",
      "证据已产出。接下来五类角色陈述贡献意见供参考，系统提供 6:4 建议，由评审委员会独立决策…",
      3
    );
    highlightDemoFlow("negotiate");
    await sleep(ROADSHOW_PACE.phaseTransition);
    switchToTab("negotiate");
    await runNegotiate({ roadshow: true });

    renderDualPoolPanel();
    showRoadshowLine(
      "第3步 · 评审委员会决策",
      "合成公式：建议 = 60%×机构现行方案 + 40%×夏普利证据池。角色意见不参与计算，由评审委员会确认后再应用。",
      3
    );
    $("#dualPoolPanel")?.classList.add("roadshow-highlight");
    $("#dualPoolPanel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    await sleep(ROADSHOW_PACE.dualPool);

    const elapsed = Math.round((Date.now() - t0) / 1000);
    showRoadshowLine("路演完成", `全流程约 ${elapsed} 秒。证据链：回测 → 贡献评审 → 分配决策。`, 3);
  } finally {
    $("#dualPoolPanel")?.classList.remove("roadshow-highlight");
    setRoadshowMode(false);
    setBusy(btn, false);
  }
}

$("#btnNegotiate").addEventListener("click", runNegotiate);
$("#btnRunAll").addEventListener("click", runAll);
$("#btnBacktest")?.addEventListener("click", () => {
  state.agentPlan = null;
  $("#agentPlanPreview")?.classList.add("hidden");
  runHs300Backtest();
});
$("#btnBacktestDemo")?.addEventListener("click", runBacktestDemo);
$("#btnGuidedDemo")?.addEventListener("click", runBacktestDemo);
$("#btnGuidedBacktest")?.addEventListener("click", () => {
  state.agentPlan = null;
  $("#agentPlanPreview")?.classList.add("hidden");
  runHs300Backtest();
});
$("#btnAgentPlan")?.addEventListener("click", runAgentPlanOnly);
$("#btnAgentRun")?.addEventListener("click", runAgentPlanAndBacktest);
$("#btnFactorPropose")?.addEventListener("click", proposeFactorConfig);
$("#btnFactorApply")?.addEventListener("click", applyFactorConfigProposal);
$("#btnFactorReset")?.addEventListener("click", resetFactorConfig);
$("#btnFactorClearChat")?.addEventListener("click", clearFactorConversation);
$("#btnSaveAgentKey")?.addEventListener("click", saveAgentApiKey);
$("#btnClearAgentKey")?.addEventListener("click", clearAgentApiKey);
$("#btnKeepOffline")?.addEventListener("click", keepOfflineAgentMode);
$("#btnShowAgentKey")?.addEventListener("click", () => setAgentCredentialChoice(true));
$("#agentApiKey")?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    saveAgentApiKey();
  }
});
$("#factorAgentText")?.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.key === "Enter") {
    event.preventDefault();
    proposeFactorConfig();
  }
});
$$(".factor-chip").forEach((button) => {
  button.addEventListener("click", () => toggleFactorPreference(button));
});
$("#btnThemeToggle")?.addEventListener("click", toggleTheme);
$("#btnDevMode")?.addEventListener("click", () => {
  document.documentElement.classList.toggle("dev-mode");
  const active = document.documentElement.classList.contains("dev-mode");
  $("#btnDevMode").textContent = active ? "退出专业模式" : "专业模式";
});

initTheme();
initStage3D();
window.addEventListener("resize", () => {
  Object.values(state.charts || {}).forEach((c) => c?.resize?.());
});
checkHealth();
highlightDemoFlow("backtest");
switchToTab("backtest");
setGuidedStage("preferences");
loadBacktestMeta();
loadAgentPresets();
loadFactorConfigMeta();
window.addEventListener("pageshow", () => {
  window.requestAnimationFrame(() => window.setTimeout(revealCurrentNextAction, 80));
}, { once: true });
