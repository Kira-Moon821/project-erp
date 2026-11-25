/* ERP Analytics Lab · 前端（零构建，原生 JS + 手写 SVG 图表）
   安全约定：访问令牌与刷新令牌只保存在内存中，不写 localStorage / sessionStorage / URL；
   刷新页面需要重新登录（演示系统，权衡安全性与便利性）。 */
'use strict';

const state = {
  accessToken: null,   // 仅内存
  refreshToken: null,  // 仅内存
  user: null,
  period: '12',
  view: 'overview',
  pages: { products: 1, customers: 1, orders: 1 },
};

const API = '/api';
const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, html) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (html !== undefined) node.innerHTML = html;
  return node;
};
const fmt = (n, digits = 0) => (n === null || n === undefined || isNaN(n)) ? '-' :
  Number(n).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
const fmtWan = (n) => (Number(n) / 10000).toFixed(1) + ' 万';

/* ---------------- API 封装 ---------------- */
async function api(path, options = {}) {
  const headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
  if (state.accessToken) headers['Authorization'] = `Bearer ${state.accessToken}`;
  const res = await fetch(API + path, Object.assign({}, options, { headers }));
  if (res.status === 401 && state.refreshToken && !options._retried) {
    const refreshed = await refreshTokens();
    if (refreshed) return api(path, Object.assign({}, options, { _retried: true }));
  }
  if (!res.ok) {
    let payload = null;
    try { payload = await res.json(); } catch (e) { /* 非 JSON 响应 */ }
    const msg = payload && payload.error ? `${payload.error.message}` : `请求失败（${res.status}）`;
    const err = new Error(msg);
    err.payload = payload;
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

async function refreshTokens() {
  const res = await fetch(`${API}/auth/refresh`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: state.refreshToken }),
  });
  if (!res.ok) { logoutLocal(); return false; }
  const data = await res.json();
  state.accessToken = data.access_token;
  state.refreshToken = data.refresh_token;
  return true;
}

function periodRange() {
  const end = '2025-12-31';
  if (state.period === '24') return { start: '2024-01-01', end };
  return { start: '2025-01-01', end };
}
const withPeriod = (path) => {
  const { start, end } = periodRange();
  const sep = path.includes('?') ? '&' : '?';
  return `${path}${sep}start=${start}&end=${end}`;
};

/* ---------------- 登录 ---------------- */
$('#login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = $('#login-error');
  err.textContent = '';
  try {
    const data = await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username: $('#username').value, password: $('#password').value }),
    });
    state.accessToken = data.access_token;
    state.refreshToken = data.refresh_token;
    state.user = data.user;
    showApp();
  } catch (ex) {
    err.textContent = ex.message;
  }
});

$('#logout').addEventListener('click', async () => {
  try { await api('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token: state.refreshToken }) }); }
  catch (e) { /* 忽略 */ }
  logoutLocal();
});

function logoutLocal() {
  state.accessToken = null; state.refreshToken = null; state.user = null;
  $('#app').classList.add('hidden');
  $('#login').classList.remove('hidden');
}

function showApp() {
  $('#login').classList.add('hidden');
  $('#app').classList.remove('hidden');
  const name = state.user.full_name || state.user.username;
  $('#who-name').textContent = name;
  $('#who-role').textContent = state.user.role;
  $('#who-avatar').textContent = name.slice(0, 1).toUpperCase();
  switchView(state.view);
}

document.querySelectorAll('.nav-item').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    switchView(btn.dataset.view);
  });
});

$('#period').addEventListener('change', (e) => { state.period = e.target.value; switchView(state.view); });
$('#refresh').addEventListener('click', (e) => {
  e.currentTarget.classList.add('spinning');
  switchView(state.view).finally(() => e.currentTarget.classList.remove('spinning'));
});

function toast(msg, kind = 'ok') {
  const t = $('#toast');
  t.textContent = msg;
  t.className = `toast ${kind}`;
  setTimeout(() => t.classList.add('hidden'), 4200);
}

/* ---------------- 图表 ---------------- */
// SVG 用 viewBox + width:100% 时会等比缩放，字号跟着一起缩。
// 所以先量出内容区实际宽度，按 1:1 的坐标系画图，字号才不会被压小。
function contentWidth() {
  const c = $('#content');
  const cs = getComputedStyle(c);
  return Math.max(280, c.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight));
}
// 总览页三栏（1.45 : 1 : 1）里第一栏的面板内宽
function colWidth(ratio, sum, gap = 28) {
  return Math.round((contentWidth() - gap) * ratio / sum) - 40;
}

// KPI 卡片上 42,318,900 元 太长，统一压成 亿 / 万
function fmtCompact(v) {
  const n = Math.abs(Number(v) || 0);
  if (n >= 1e8) return (v / 1e8).toFixed(2) + ' 亿';
  if (n >= 1e4) return fmt(v / 1e4, 1) + ' 万';
  return fmt(v, 0);
}

/** 迷你趋势线：纯装饰，无文字，用 preserveAspectRatio="none" 拉伸填满卡片宽度 */
function sparkline(values, color = '#4c8dff') {
  const nums = (values || []).map((v) => Number(v) || 0);
  if (nums.length < 2) return '';
  const w = 120, h = 34, pad = 3;
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = max - min || 1;
  const stepX = w / (nums.length - 1);
  const y = (v) => h - pad - ((v - min) / span) * (h - pad * 2);
  const line = nums.map((v, i) => `${i ? 'L' : 'M'}${(i * stepX).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const area = `${line} L${w},${h} L0,${h} Z`;
  const gid = 'sp' + Math.random().toString(36).slice(2, 8);
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${color}" stop-opacity=".3"/>
      <stop offset="100%" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
    <path d="${area}" fill="url(#${gid})"/>
    <path d="${line}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${w}" cy="${y(nums[nums.length - 1]).toFixed(1)}" r="2" fill="${color}"/>
  </svg>`;
}

function lineChart(data, { w = 720, h = 252, padL = 54, padR = 18, padT = 16, padB = 30, key = 'revenue', label = '营收' } = {}) {
  if (!data.length) return '<p class="panel-sub">暂无数据</p>';
  const values = data.map((d) => Number(d[key]) || 0);
  const max = (Math.max(...values) || 1) * 1.14;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;
  const stepX = innerW / Math.max(1, data.length - 1);
  const x = (i) => padL + i * stepX;
  const y = (v) => padT + innerH - (v / max) * innerH;
  const line = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const area = `${line} L${x(data.length - 1).toFixed(1)},${padT + innerH} L${padL},${padT + innerH} Z`;

  const grid = [0, .25, .5, .75, 1].map((r) => {
    const yy = y(max * r);
    return `<line x1="${padL}" y1="${yy.toFixed(1)}" x2="${w - padR}" y2="${yy.toFixed(1)}" stroke="#1a2432" stroke-width="1" ${r === 0 ? '' : 'stroke-dasharray="3 5"'}/>
      <text x="${padL - 10}" y="${(yy + 4).toFixed(1)}" fill="#5c6e83" font-size="10.5" text-anchor="end">${fmtCompact(max * r)}</text>`;
  }).join('');

  // 按可用宽度决定标签密度，避免窄栏里最后两个月份标签叠在一起；
  // 末月单独补一个标签，前提是它和上一个标签至少隔了 64px。
  const every = Math.max(1, Math.ceil(data.length / Math.max(2, Math.floor((w - padL - padR) / 72))));
  const lastIdx = data.length - 1;
  const showLast = lastIdx % every !== 0 && (lastIdx % every) * stepX >= 64;
  const labels = data.map((d, i) => (i % every === 0 || (i === lastIdx && showLast))
    ? `<text x="${x(i).toFixed(1)}" y="${h - padB + 18}" fill="#5c6e83" font-size="10.5" text-anchor="middle">${d.period.slice(2)}</text>` : '').join('');

  const dots = values.map((v, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="2.8" fill="#0b0f16" stroke="#4c8dff" stroke-width="1.8"/>`).join('');
  // 每个点一个透明热区，鼠标悬停即出原生 tooltip（不依赖第三方库）
  const hits = data.map((d, i) => `<g><rect x="${(x(i) - stepX / 2).toFixed(1)}" y="${padT}" width="${stepX.toFixed(1)}" height="${innerH}" fill="transparent"/>
    <title>${d.period}　${label} ${fmt(d[key], 2)}${d.orders !== undefined ? `　订单 ${fmt(d.orders)}` : ''}</title></g>`).join('');

  const lx = x(data.length - 1), ly = y(values[values.length - 1]);
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" style="display:block;width:100%;height:auto">
    <defs><linearGradient id="lc-fill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#4c8dff" stop-opacity=".28"/>
      <stop offset="100%" stop-color="#4c8dff" stop-opacity="0"/></linearGradient></defs>
    ${grid}
    <path d="${area}" fill="url(#lc-fill)"/>
    <path d="${line}" fill="none" stroke="#4c8dff" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    ${dots}
    <circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="7" fill="#4c8dff" opacity=".16"/>
    <circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="3.4" fill="#4c8dff"/>
    ${labels}${hits}
  </svg>`;
}

function barChart(rows, { label = 'name', value = 'value', fmtV = (v) => fmt(v), color = '#4c8dff' } = {}) {
  if (!rows.length) return '<p class="panel-sub">暂无数据</p>';
  const max = Math.max(...rows.map((r) => Number(r[value]) || 0)) || 1;
  // 用 HTML/CSS 画条形而不是 SVG：SVG 固定宽高会被等比缩放，字号随之失控；
  // CSS 版本文字始终是 12px，条形宽度随容器自适应。
  return `<div class="hbars">${rows.map((r) => `
    <div class="hbar">
      <span class="hbar-label" title="${r[label]}">${r[label]}</span>
      <span class="hbar-track"><span class="hbar-fill" style="width:${((Number(r[value]) / max) * 100).toFixed(2)}%;background:${color}"></span></span>
      <span class="hbar-value">${fmtV(r[value])}</span>
    </div>`).join('')}</div>`;
}

/**
 * 对照组 / AI 组的对比条。
 * 不用同一张柱状图：首响（0~60 分钟）、满意度（0~5）、转化率（0~20%）量级差太多，
 * 挤在一根 y 轴上小数会变成看不见的细线。改为「每组独立刻度」的横向对比条。
 */
function compareBars(groups, series) {
  return `<div class="cmp-bars">${groups.map((g) => {
    const max = Math.max(...series.map((s) => Number(g[s.key]) || 0)) || 1;
    const lines = series.map((s) => {
      const v = Number(g[s.key]) || 0;
      const w = Math.max(2, (v / max) * 100);
      return `<div class="cmp-line">
        <span class="cmp-tag">${s.label}</span>
        <span class="cmp-track"><span class="cmp-fill" style="width:${w.toFixed(1)}%;background:${s.color}"></span></span>
        <span class="cmp-val">${fmt(v, 1)}</span>
      </div>`;
    }).join('');
    return `<div class="cmp-group"><div class="cmp-name">${g.name}</div>${lines}</div>`;
  }).join('')}</div>`;
}

function funnelChart(stages) {
  const max = Math.max(...stages.map((s) => s.count)) || 1;
  return stages.map((s, i) => {
    const width = Math.max(4, (s.count / max) * 100);
    const conv = s.conversion_from_prev === null || s.conversion_from_prev === undefined
      ? '起点' : `转化 ${s.conversion_from_prev.toFixed(1)}%`;
    return `<div class="funnel-row">
      <div class="funnel-head">
        <span class="funnel-stage"><span class="funnel-idx">${i + 1}</span>${s.stage}</span>
        <span class="funnel-meta"><b>${fmt(s.count)}</b> 条 · ${conv}</span>
      </div>
      <div class="funnel-track"><div class="funnel-fill" style="width:${width.toFixed(1)}%"></div></div>
    </div>`;
  }).join('');
}

/* ---------------- 视图 ---------------- */
const VIEWS = {
  async overview() {
    const [summary, trend, funnel, ai, insights, inv] = await Promise.all([
      api(withPeriod('/dashboard/summary')),
      api(withPeriod('/dashboard/sales-trend')),
      api(withPeriod('/dashboard/funnel')),
      api(withPeriod('/analytics/ai-value')),
      api(withPeriod('/ai/insights')),
      api('/dashboard/inventory-health'),
    ]);
    const monthly = summary.monthly || [];
    const kpis = summary.kpis.map((k) => {
      const cmp = k.comparison;
      const hasCmp = cmp !== null && cmp !== undefined;
      // 变动小于 0.05 视为持平，避免「▲ 0.0%」这种噪声
      const flat = hasCmp && Math.abs(cmp) < 0.05;
      const cls = !hasCmp || flat ? 'flat' : (cmp > 0 ? 'up' : 'down');
      const arrow = !hasCmp || flat ? '' : (cmp > 0 ? '▲ ' : '▼ ');
      const shown = k.unit === '元' ? fmtCompact(k.value)
        : k.unit === '%' ? fmt(k.value, 2) : fmt(k.value, 0);
      // 只有月度序列里真实存在的指标才画迷你趋势线（库存类 KPI 是时点快照，没有序列）
      const series = monthly.length ? monthly.map((m) => Number(m[k.key])) : [];
      const spark = series.length > 1 && series.every((v) => Number.isFinite(v))
        ? sparkline(series, cls === 'down' ? '#f2555a' : '#4c8dff') : '';
      const cmpHtml = hasCmp
        ? `<span class="cmp ${cls}">${arrow}${fmt(Math.abs(cmp), 1)}${k.comparison_unit || '%'}<i>${k.comparison_label || ''}</i></span>`
        : '<span class="cmp flat">当期快照</span>';
      return `<div class="kpi">
        <div class="label"><span>${k.label}</span>${k.hint ? `<i>${k.hint}</i>` : ''}</div>
        <div class="value">${shown}<small>${k.unit}</small></div>
        ${cmpHtml}${spark}
      </div>`;
    }).join('');

    const u = ai.usage;
    return `
      <div class="grid kpis">${kpis}</div>
      <div class="dash-row">
        <div class="panel"><h3>营收趋势（按月）</h3>
          <p class="panel-sub">区域为当月营收，悬停查看当月订单数；同比 / 环比见「销售分析」</p>
          ${lineChart(trend, { w: colWidth(1.45, 3.45), h: 200 })}</div>
        <div class="panel"><h3>销售漏斗</h3>
          <p class="panel-sub">线索 → 需求确认 → 方案演示 → 商务谈判 → 成单</p>
          ${funnelChart(funnel)}</div>
        <div class="panel"><h3>AI 助手使用</h3>
          <p class="panel-sub">内部采纳率与节省工时，是 AI 产品价值的内部基线</p>
          <div class="mini-cards">
            <div class="kpi"><div class="label"><span>采纳率</span></div>
              <div class="value">${fmt(u.acceptance_rate * 100, 1)}<small>%</small></div>
              <span class="cmp flat">${fmt(u.accepted)} / ${fmt(u.queries)} 次被采纳</span></div>
            <div class="kpi"><div class="label"><span>累计节省工时</span></div>
              <div class="value">${fmt(u.hours_saved, 0)}<small>小时</small></div>
              <span class="cmp flat">覆盖 ${u.active_users} 名员工</span></div>
          </div></div>
      </div>
      <div class="panel"><h3>经营洞察</h3>
        <p class="panel-sub">规则引擎按指标阈值自动判定，每条结论都附带可复现的证据 SQL</p>
        <div class="insight-grid">
          ${insights.slice(0, 4).map((i) => `
            <div class="insight ${i.severity}">
              <div class="t"><span class="dot"></span>${i.title}</div>
              <p class="d">${i.detail}</p>
              ${i.suggestion ? `<p class="s">建议：${i.suggestion}</p>` : ''}
              ${i.evidence_sql ? `<details><summary>证据 SQL</summary><pre>${i.evidence_sql.trim()}</pre></details>` : ''}
            </div>`).join('')}
        </div>
      </div>`;
  },

  async sales() {
    const [trend, industry, region, channel, tier, topC, topP] = await Promise.all([
      api(withPeriod('/dashboard/sales-trend')),
      api(withPeriod('/dashboard/breakdown/industry')),
      api(withPeriod('/dashboard/breakdown/region')),
      api(withPeriod('/dashboard/breakdown/channel')),
      api(withPeriod('/dashboard/breakdown/tier')),
      api(withPeriod('/dashboard/top-customers?limit=8')),
      api(withPeriod('/dashboard/top-products?limit=8')),
    ]);
    const trendRows = trend.map((t) => `<tr>
        <td>${t.period}</td><td class="num">${fmt(t.revenue, 0)}</td><td class="num">${fmt(t.orders)}</td>
        <td class="num">${fmt(t.gross_profit, 0)}</td>
        <td class="num">${t.yoy_pct === null ? '-' : fmt(t.yoy_pct, 1) + '%'}</td>
        <td class="num">${t.mom_pct === null ? '-' : fmt(t.mom_pct, 1) + '%'}</td></tr>`).join('');
    const custRows = topC.map((c) => `<tr>
        <td>${c.customer_name}</td><td><span class="tag ${c.tier.toLowerCase()}">${c.tier}</span></td>
        <td>${c.industry}</td><td class="num">${fmt(c.revenue, 0)}</td><td class="num">${c.orders}</td>
        <td class="num">${fmt(c.aov, 0)}</td></tr>`).join('');
    const prodRows = topP.map((p) => `<tr>
        <td>${p.product_name}</td><td>${p.category}</td><td class="num">${fmt(p.qty)}</td>
        <td class="num">${fmt(p.revenue, 0)}</td><td class="num">${fmt(p.gross_margin * 100, 1)}%</td></tr>`).join('');
    return `
      <div class="panel"><h3>月度趋势明细</h3><p class="panel-sub">同比（与去年同期）与环比（与上月）</p>
        ${lineChart(trend, { w: contentWidth() - 40, h: 220 })}
        <table style="margin-top:10px"><thead><tr><th>月份</th><th class="num">营收</th><th class="num">订单</th>
          <th class="num">毛利</th><th class="num">同比</th><th class="num">环比</th></tr></thead><tbody>${trendRows}</tbody></table></div>
      <div class="cols-2">
        <div class="panel"><h3>Top 客户</h3><p class="panel-sub">按营收排序</p>
          <table><thead><tr><th>客户</th><th>层级</th><th>行业</th><th class="num">营收</th><th class="num">订单</th><th class="num">客单价</th></tr></thead>
          <tbody>${custRows}</tbody></table></div>
        <div class="panel"><h3>Top 商品</h3><p class="panel-sub">按收入排序</p>
          <table><thead><tr><th>商品</th><th>品类</th><th class="num">销量</th><th class="num">收入</th><th class="num">毛利率</th></tr></thead>
          <tbody>${prodRows}</tbody></table></div>
      </div>
      <div class="cols-2">
        ${[['行业', industry], ['区域', region], ['渠道', channel], ['客户层级', tier]].map(([name, rows]) => `
        <div class="panel"><h3>按${name}拆解</h3>${barChart(rows.map((r) => ({ name: r.name, value: r.revenue })), { fmtV: fmtWan })}</div>`).join('')}
      </div>`;
  },

  async inventory() {
    const [inv, list] = await Promise.all([
      api('/dashboard/inventory-health'),
      api('/inventory'),
    ]);
    const short = list.filter((r) => r.stock_gap < 0).sort((a, b) => a.stock_gap - b.stock_gap).slice(0, 12);
    const rows = short.map((r) => `<tr>
        <td>${r.sku}</td><td>${r.product_name}</td><td>${r.warehouse}</td>
        <td class="num">${fmt(r.on_hand_qty)}</td><td class="num">${fmt(r.safety_stock)}</td>
        <td class="num"><span class="tag ${r.stock_gap < 0 ? 'bad' : 'warn'}">${fmt(r.stock_gap)}</span></td>
        <td class="num">${fmt(r.inventory_value, 0)}</td></tr>`).join('');
    return `
      <div class="grid kpis">
        <div class="kpi"><div class="label">期末库存金额</div><div class="value">${fmtWan(inv.inventory_value)}<small>元</small></div>
          <div class="cmp flat">快照日 ${inv.snapshot_date}</div></div>
        <div class="kpi"><div class="label">库存周转天数</div><div class="value">${fmt(inv.turnover_days, 1)}<small>天</small></div>
          <div class="cmp flat">成本口径</div></div>
        <div class="kpi"><div class="label">低于安全库存</div><div class="value">${inv.shortage_skus}<small>个 SKU</small></div>
          <div class="cmp ${inv.shortage_skus ? 'down' : 'up'}">共 ${inv.sku_count} 个 SKU</div></div>
        <div class="kpi"><div class="label">近 90 天动销 SKU</div><div class="value">${inv.moving_skus_90d}<small>个</small></div>
          <div class="cmp flat">滞销 ${inv.slow_moving_skus} 个</div></div>
      </div>
      <div class="panel"><h3>缺口清单</h3><p class="panel-sub">在手量低于安全库存的 SKU，缺口 = 在手 − 安全库存（负数即需补货）</p>
        <table><thead><tr><th>SKU</th><th>商品</th><th>仓库</th><th class="num">在手</th>
          <th class="num">安全库存</th><th class="num">缺口</th><th class="num">库存金额</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="7">无缺口</td></tr>'}</tbody></table></div>`;
  },

  async funnel() {
    const [funnel, ai, marketing] = await Promise.all([
      api(withPeriod('/dashboard/funnel')),
      api(withPeriod('/analytics/ai-value')),
      api(withPeriod('/analytics/marketing')),
    ]);
    const L = ai.leads[1] || { count: 0, avg_win_prob: 0, avg_cycle_days: 0, won: 0 };
    const C = ai.leads[0] || { count: 0, avg_win_prob: 0, avg_cycle_days: 0, won: 0 };
    const T = ai.tickets[1] || { count: 0, avg_first_response_min: 0, avg_satisfaction: 0, converted: 0 };
    const TC = ai.tickets[0] || { count: 0, avg_first_response_min: 0, avg_satisfaction: 0, converted: 0 };
    const leadGroups = [
      { name: '成单率 %', ai: (L.won / L.count) * 100, ctl: (C.won / C.count) * 100 },
      { name: '平均赢率 %', ai: L.avg_win_prob * 100, ctl: C.avg_win_prob * 100 },
      { name: '销售周期 天', ai: L.avg_cycle_days, ctl: C.avg_cycle_days },
    ];
    const ticketGroups = [
      { name: '首响 分钟', ai: T.avg_first_response_min, ctl: TC.avg_first_response_min },
      { name: '满意度', ai: T.avg_satisfaction, ctl: TC.avg_satisfaction },
      { name: '转商机 %', ai: (T.converted / T.count) * 100, ctl: (TC.converted / TC.count) * 100 },
    ];
    const mktRows = marketing.map((m) => `<tr><td>${m.channel}</td><td class="num">${fmt(m.cost, 0)}</td>
        <td class="num">${fmt(m.leads)}</td><td class="num">${fmt(m.cac, 0)}</td>
        <td class="num">${fmt(m.roas, 2)}</td>
        <td><span class="tag ${m.roas >= 3 ? 'ok' : m.roas >= 2 ? 'warn' : 'bad'}">${m.roas >= 3 ? '可加投' : m.roas >= 2 ? '维持' : '建议减投'}</span></td></tr>`).join('');
    return `
      <div class="cols-2">
        <div class="panel"><h3>线索 → 成单漏斗</h3><p class="panel-sub">逐级转化率与平均销售周期</p>${funnelChart(funnel)}
          <table style="margin-top:12px"><thead><tr><th>阶段</th><th class="num">数量</th><th class="num">上一级转化</th><th class="num">平均周期</th></tr></thead>
          <tbody>${funnel.map((f) => `<tr><td>${f.stage}</td><td class="num">${fmt(f.count)}</td>
            <td class="num">${f.conversion_from_prev === null ? '-' : fmt(f.conversion_from_prev, 1) + '%'}</td>
            <td class="num">${f.avg_cycle_days} 天</td></tr>`).join('')}</tbody></table></div>
        <div class="panel"><h3>营销渠道效率</h3><p class="panel-sub">CAC = 成本 ÷ 线索数；ROAS = 归因收入 ÷ 成本</p>
          <table><thead><tr><th>渠道</th><th class="num">成本</th><th class="num">线索</th><th class="num">CAC</th><th class="num">ROAS</th><th>建议</th></tr></thead>
          <tbody>${mktRows}</tbody></table></div>
      </div>
      <div class="cols-2">
        <div class="panel"><h3>AI 辅助商机 vs 对照组</h3><p class="panel-sub">AI 组赢率更高、周期更短</p>
          ${compareBars(leadGroups, [{ key: 'ai', label: 'AI 辅助', color: '#4c8dff' }, { key: 'ctl', label: '对照组', color: '#5d7186' }])}</div>
        <div class="panel"><h3>AI 处理工单 vs 人工</h3><p class="panel-sub">首响更快、满意度更高、转商机更多</p>
          ${compareBars(ticketGroups, [{ key: 'ai', label: 'AI 处理', color: '#8b6cf0' }, { key: 'ctl', label: '人工', color: '#5d7186' }])}</div>
      </div>`;
  },

  async products() {
    const page = state.pages.products;
    const data = await api(`/products?page=${page}&size=10`);
    const rows = data.items.map((p) => `<tr><td>${p.sku}</td><td>${p.product_name}</td><td>${p.category}</td>
        <td>${p.brand}</td><td class="num">${fmt(p.unit_cost, 2)}</td><td class="num">${fmt(p.list_price, 2)}</td>
        <td><span class="tag ${p.status === '在售' ? 'ok' : 'bad'}">${p.status}</span></td></tr>`).join('');
    return `<div class="panel"><h3>产品主数据</h3><p class="panel-sub">共 ${data.total} 个 SKU，本页 ${data.items.length} 条</p>
      <table><thead><tr><th>SKU</th><th>名称</th><th>品类</th><th>品牌</th><th class="num">成本</th><th class="num">标价</th><th>状态</th></tr></thead>
      <tbody>${rows}</tbody></table>
      ${pager('products', data)}</div>`;
  },

  async customers() {
    const page = state.pages.customers;
    const data = await api(`/customers?page=${page}&size=10`);
    const rows = data.items.map((c) => `<tr><td>${c.customer_name}</td>
        <td><span class="tag ${c.tier.toLowerCase()}">${c.tier}</span></td><td>${c.industry}</td>
        <td>${c.region} · ${c.city}</td><td>${c.channel}</td><td>${c.customer_manager}</td>
        <td><span class="tag ${c.status === '合作中' ? 'ok' : 'bad'}">${c.status}</span></td></tr>`).join('');
    return `<div class="panel"><h3>客户主数据</h3><p class="panel-sub">共 ${data.total} 家客户</p>
      <table><thead><tr><th>客户</th><th>层级</th><th>行业</th><th>区域</th><th>渠道</th><th>客户经理</th><th>状态</th></tr></thead>
      <tbody>${rows}</tbody></table>${pager('customers', data)}</div>`;
  },

  async orders() {
    const page = state.pages.orders;
    const [data, customers, products] = await Promise.all([
      api(`/sales-orders?page=${page}&size=10`),
      api('/customers?page=1&size=200'),
      api('/products?page=1&size=200'),
    ]);
    const rows = data.items.map((o) => `<tr><td>${o.order_no}</td><td>${o.customer_name}</td>
        <td>${o.channel}</td><td class="num">${fmt(o.net_amount, 0)}</td>
        <td><span class="tag ${o.status === '已完成' ? 'ok' : o.status === '已退款' ? 'bad' : 'warn'}">${o.status}</span></td>
        <td>${o.payment_status}</td></tr>`).join('');
    const custOpts = customers.items.map((c) => `<option value="${c.customer_id}">${c.customer_name}（${c.tier}）</option>`).join('');
    const prodOpts = products.items.map((p) => `<option value="${p.product_id}">${p.sku} ${p.product_name}</option>`).join('');
    return `
      <div class="panel"><h3>新建销售订单</h3>
        <p class="panel-sub">服务端会校验客户状态、商品在售状态与仓库可用库存，不足则整单回滚（事务边界）</p>
        <div class="form-row">
          <label>客户<select id="new-customer">${custOpts}</select></label>
          <label>商品<select id="new-product">${prodOpts}</select></label>
          <label>数量<input id="new-qty" type="number" value="1" min="1" style="width:90px"></label>
          <label>折扣率<input id="new-disc" type="number" value="0" min="0" max="0.35" step="0.01" style="width:90px"></label>
          <button class="btn primary" id="submit-order">提交订单</button>
        </div>
        <div id="order-result"></div>
      </div>
      <div class="panel"><h3>订单列表</h3><p class="panel-sub">共 ${data.total} 单</p>
        <table><thead><tr><th>订单号</th><th>客户</th><th>渠道</th><th class="num">金额</th><th>状态</th><th>付款</th></tr></thead>
        <tbody>${rows}</tbody></table>${pager('orders', data)}</div>`;
  },
};

function pager(key, data) {
  const pages = Math.max(1, Math.ceil(data.total / data.size));
  return `<div class="pager">
    <button class="btn" data-page="${key}" data-dir="-1" ${data.page <= 1 ? 'disabled' : ''}>上一页</button>
    <span>第 ${data.page} / ${pages} 页</span>
    <button class="btn" data-page="${key}" data-dir="1" ${data.page >= pages ? 'disabled' : ''}>下一页</button>
  </div>`;
}

async function switchView(view) {
  state.view = view;
  const content = $('#content');
  content.innerHTML = '<div class="loading">正在加载数据…</div>';
  const titles = {
    overview: ['经营总览', '核心 KPI、趋势、漏斗与自动洞察'],
    sales: ['销售分析', '趋势 / 结构 / Top 榜单'],
    inventory: ['库存健康', '库存金额、周转、缺口与滞销'],
    funnel: ['漏斗与 AI 价值', '销售漏斗、渠道效率与 AI 辅助对照'],
    products: ['产品主数据', 'SKU、价格与状态'],
    customers: ['客户主数据', '客户分层、行业与归属'],
    orders: ['销售订单', '订单查询与下单（事务 + 库存校验）'],
  };
  $('#view-title').textContent = titles[view][0];
  $('#view-sub').textContent = titles[view][1];
  try {
    content.innerHTML = await VIEWS[view]();
    bindViewEvents();
  } catch (ex) {
    content.innerHTML = `<div class="insight critical"><div class="t">加载失败</div><p class="d">${ex.message}</p></div>`;
  }
}

function bindViewEvents() {
  document.querySelectorAll('[data-page]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.page;
      state.pages[key] += Number(btn.dataset.dir);
      switchView(state.view);
    });
  });
  const submit = document.getElementById('submit-order');
  if (submit) submit.addEventListener('click', async () => {
    const payload = {
      customer_id: Number($('#new-customer').value),
      items: [{
        product_id: Number($('#new-product').value),
        qty: Number($('#new-qty').value),
        discount_rate: Number($('#new-disc').value),
      }],
    };
    try {
      const res = await api('/sales-orders', { method: 'POST', body: JSON.stringify(payload) });
      $('#order-result').innerHTML = `<div class="insight"><div class="t">✅ 订单已创建：${res.order_no}</div>
        <p class="d">金额 ${fmt(res.net_amount, 2)} 元，毛利 ${fmt(res.gross_profit, 2)} 元，状态 ${res.status}</p></div>`;
      toast(`订单 ${res.order_no} 创建成功`);
      switchView('orders');
    } catch (ex) {
      const detail = ex.payload && ex.payload.error && ex.payload.error.details
        ? JSON.stringify(ex.payload.error.details) : '';
      $('#order-result').innerHTML = `<div class="insight critical"><div class="t">❌ ${ex.message}</div>
        ${detail ? `<pre>${detail}</pre>` : ''}</div>`;
      toast(ex.message, 'err');
    }
  });
}

/* 时钟 */
setInterval(() => {
  const d = new Date();
  $('#clock').textContent = d.toLocaleString('zh-CN', { hour12: false });
}, 1000);
