/* Zava Console — tri-agent web app: chat + real Voice Live + live orchestration + traces. */
const $ = (s) => document.querySelector(s);
const messagesEl = $('#messages');
const suggestionsEl = $('#suggestions');
const form = $('#chatForm');
const input = $('#chatMessage');
const viewTitle = $('#viewTitle');
const voiceStatus = $('#voiceStatus');
const tracesList = $('#tracesList');

const AGENTS = {
  inventory: {
    title: 'Inventory Dashboard', placeholder: 'Ask about inventory…', icon: 'box',
    greeting: "**Hi, I'm the Zava InventoryAgent.** 👋\n\nI check **live** stock across our 7 distribution centers — critical & low-stock alerts, on-hand by product line, per-SKU availability — and I answer inventory **policies** from the knowledge base. Pick a suggestion below or ask me anything.",
    suggestions: [
      'What are my most critical stock issues right now?',
      'How are stock levels for ZavaCore Field Elite?',
      'How many units of ZCPTM-SS-S-B0 do we have across facilities?',
      "What's our return policy for worn or opened apparel?",
    ],
  },
  delivery: {
    title: 'Order Tracking', placeholder: 'Ask about your delivery…', icon: 'truck',
    greeting: "**Hi, I'm Zava DeliverySupport.** 👋\n\nGive me an order number and I'll track it — **status, ETA, last location**, delays and what to do next. Try a suggestion below.",
    suggestions: [
      "What's the status of order 23518?",
      'Why is order 23544 delayed?',
      'Track order 23561',
      'My order 23575 says exception — what do I do?',
    ],
  },
  orchestration: {
    title: 'Incident Response', placeholder: 'Describe an incident (or run the sample)…', icon: 'workflow',
    greeting: "**Multi-framework incident response.** 🛠️\n\nThree agents built with **different frameworks** cooperate — **Triage** (LangGraph) → **Code Fix** (GitHub Copilot SDK) → **Compliance** (Foundry prompt agent) — orchestrated by the **Microsoft Agent Framework** and hosted on **Foundry**. Send the sample incident below and watch the pipeline run **live** on the right.",
    // A suggestion is either a plain string, or {label, text} when the chip should stay short
    // while the message sent to Triage is a full incident report.
    suggestions: [
      'Run the ZAVA-INC-4821 reorder incident',
      {
        label: '🔴 Negative quantities (buyer report)',
        text: "Purchasing escalation: the nightly reorder job wrote reorder quantities of -240 for SKUs that "
          + "are comfortably above their reorder point, and buyers cannot trust the purchase-order feed. "
          + "The unit tests in test_reorder.py are failing against reorder.py.",
      },
      {
        label: '🟠 Under-ordering at FC-MEM',
        text: "Operations reports that reorder.py is under-ordering: for about 40 SKUs at the Memphis "
          + "distribution center, on_hand + reorder is still below target_level after the nightly run. "
          + "Deficits look like they are being rounded DOWN to whole case packs instead of up.",
      },
      {
        label: '🟡 Data-quality alert on the PO feed',
        text: "Data-quality alert: last night's reorder export contains negative and below-target reorder "
          + "quantities, so the purchase-order feed for the ZavaCore Field lines is unusable. The defect "
          + "is in the reorder quantity calculation in reorder.py and test_reorder.py is red.",
      },
      {
        label: '🔵 Post-incident: verify the fix',
        text: "Follow-up on the reorder defect: a patch was applied to reorder.py but purchasing still sees "
          + "quantities below target level for several SKUs. Re-triage the incident, fix it properly and "
          + "run the change through the Zava engineering policy review before it ships.",
      },
    ],
  },
  evals: {
    title: 'Evaluations', placeholder: '', icon: 'shield',
    greeting: "**Foundry Evaluations.** 🛡️\n\nEvery run on the right was scored by the **Microsoft Foundry evaluation service** — the same results you see in *Foundry portal → Evaluations*. Three flavours of evaluator are used across the three demos:\n\n- **built-in** — Microsoft-curated (`relevance`, `intent_resolution`, `task_adherence`, `tool_call_success`, `violence`…)\n- **custom** — our own code-based `grade()` functions and prompt-based LLM judges\n- **rubric** — weighted, LLM-judged quality criteria per agent\n\nPick a run to see the per-row scores and the judge's reasoning.",
    suggestions: [],
  },
  finops: {
    title: 'FinOps', placeholder: '', icon: 'chart',
    greeting: "**FinOps over the AI Gateway.** 📊\n\nEvery figure on the right comes from **Azure API Management** sitting in front of the Foundry project. Calling Foundry directly gives you a `usage` object per response and nothing else — nothing aggregates it, attributes it, or keeps it.\n\nThree things had to be true for this tab to exist:\n\n- a diagnostic **on the API**, not just on the service\n- an **outbound policy** that reads `usage` out of the body, because APIM's built-in LLM parser does not understand the Responses API and reports 0 tokens\n- `metrics: true` **and** an Application Insights logger, or `emit-metric` is silently dropped\n\nCost is derived from `pricing.json`, so treat it as a model of your bill rather than the bill.",
    suggestions: [],
  },
};

const state = {
  view: 'inventory',
  history: { inventory: [], delivery: [], orchestration: [], evals: [], finops: [] },
  prevRespId: { inventory: null, delivery: null, orchestration: null, evals: null, finops: null },
  voice: null,
  traces: [],
  evals: { items: [], selectedRun: null },
};

const escapeHtml = (v) => String(v ?? '').replace(/[&<>'"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
const label = (k) => k.replaceAll('_', ' ').toUpperCase();
const statusClass = (s) => (s || 'in stock').replaceAll(' ', '-').toLowerCase();
const nowTime = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

/* ---------------- minimal Markdown renderer (safe: escapes first) ---------------- */
function mdInline(t) {
  return t
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
const splitRow = (l) => l.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map((c) => c.trim());
function renderMarkdown(src) {
  const lines = escapeHtml(src).split('\n');
  let html = '', i = 0;
  const blockAt = (l) => /^\s*[-*]\s+/.test(l) || /^\s*\d+\.\s+/.test(l) || /^#{1,4}\s+/.test(l);
  while (i < lines.length) {
    const line = lines[i];
    // table: a row with | followed by a separator row of dashes
    if (line.includes('|') && i + 1 < lines.length && /-/.test(lines[i + 1]) && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1])) {
      const header = splitRow(line); i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim() !== '') { rows.push(splitRow(lines[i])); i++; }
      html += '<table><thead><tr>' + header.map((h) => `<th>${mdInline(h)}</th>`).join('') +
        '</tr></thead><tbody>' + rows.map((r) => '<tr>' + r.map((c) => `<td>${mdInline(c)}</td>`).join('') + '</tr>').join('') +
        '</tbody></table>';
      continue;
    }
    const hm = line.match(/^(#{1,4})\s+(.*)$/);
    if (hm) { const lvl = Math.min(6, hm[1].length + 2); html += `<h${lvl}>${mdInline(hm[2])}</h${lvl}>`; i++; continue; }
    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) { items.push(mdInline(lines[i].replace(/^\s*[-*]\s+/, ''))); i++; }
      html += '<ul>' + items.map((it) => `<li>${it}</li>`).join('') + '</ul>'; continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) { items.push(mdInline(lines[i].replace(/^\s*\d+\.\s+/, ''))); i++; }
      html += '<ol>' + items.map((it) => `<li>${it}</li>`).join('') + '</ol>'; continue;
    }
    if (line.trim() === '') { i++; continue; }
    const para = [line]; i++;
    while (i < lines.length && lines[i].trim() !== '' && !blockAt(lines[i]) && !lines[i].includes('|')) { para.push(lines[i]); i++; }
    html += `<p>${para.map(mdInline).join('<br>')}</p>`;
  }
  return html;
}

/* ==================================================================
   Traces panel — what actually ran behind every answer.
   ================================================================== */
const TRACE_ICON = {
  model: 'cpu', toolbox: 'layers', tool: 'wrench', kb: 'book', fabric: 'database',
  citation: 'quote', usage: 'hash', voice: 'broadcast', agent: 'bot', step: 'loop',
  error: 'warn', handoff: 'route', harness: 'layers', memory: 'brain', todo: 'checklist',
};

function beginTrace(icon, title, subtitle) {
  const group = { id: `tg${Date.now()}${Math.random().toString(16).slice(2, 6)}`, icon, title, subtitle, ts: nowTime(), entries: [] };
  state.traces.push(group);
  if (state.traces.length > 40) state.traces.shift();
  renderTraces();
  return group;
}
function addTrace(group, entry) {
  if (!group || !entry) return;
  group.entries.push(entry);
  renderTraces();
}
function addTraces(group, entries) {
  if (!group || !Array.isArray(entries)) return;
  group.entries.push(...entries);
  renderTraces();
}

function traceEntryHtml(e) {
  const kind = e.kind || 'tool';
  const bad = e.status === 'error' || e.status === 'failed';
  const body = [];
  if (e.args && e.args !== '{}') body.push(`<div class="te-block"><span class="te-lbl">arguments</span><pre>${escapeHtml(e.args)}</pre></div>`);
  if (e.detail) body.push(`<div class="te-block"><span class="te-lbl">${kind === 'toolbox' || kind === 'citation' ? 'items' : 'result'}</span><pre>${escapeHtml(e.detail)}</pre></div>`);
  const head = `<span class="te-ic k-${kind}">${ico(TRACE_ICON[kind] || 'dot')}</span>
    <span class="te-txt"><b>${escapeHtml(e.title || kind)}</b>${e.subtitle ? `<i>${escapeHtml(e.subtitle)}</i>` : ''}</span>
    ${bad ? `<span class="te-st bad">${escapeHtml(e.status)}</span>` : ''}`;
  if (!body.length) return `<div class="te k-${kind}">${head}</div>`;
  return `<details class="te k-${kind}"><summary>${head}<span class="te-chev">${ico('chevron')}</span></summary>${body.join('')}</details>`;
}

function renderTraces() {
  const total = state.traces.reduce((n, g) => n + g.entries.length, 0);
  $('#traceCount').textContent = total;
  if (!state.traces.length) {
    tracesList.innerHTML = `<div class="traces-empty">${ico('activity')}<p>No traces yet. Ask an agent something &mdash; every model call, toolbox lookup, tool invocation and knowledge-base retrieval shows up here.</p></div>`;
    return;
  }
  const atBottom = tracesList.scrollTop + tracesList.clientHeight >= tracesList.scrollHeight - 60;
  tracesList.innerHTML = state.traces.map((g) => `
    <section class="trace-group">
      <header class="tg-head">
        <span class="tg-ic">${ico(g.icon || 'bot')}</span>
        <span class="tg-title">${escapeHtml(g.title)}</span>
        <span class="tg-ts">${escapeHtml(g.ts)}</span>
      </header>
      ${g.subtitle ? `<div class="tg-sub">${escapeHtml(g.subtitle)}</div>` : ''}
      <div class="tg-body">${g.entries.map(traceEntryHtml).join('') || '<div class="te pending"><span class="te-ic k-step">' + ico('loop') + '</span><span class="te-txt"><b>running…</b></span></div>'}</div>
    </section>`).join('');
  if (atBottom) tracesList.scrollTop = tracesList.scrollHeight;
}

$('#clearTraces').addEventListener('click', () => { state.traces = []; renderTraces(); });
$('#toggleTraces').addEventListener('click', () => {
  const collapsed = $('#shell').classList.toggle('no-traces');
  $('#toggleTraces').classList.toggle('off', collapsed);
});

/* ---------------- chat rendering ---------------- */
function renderHistory() {
  messagesEl.innerHTML = '';
  const hist = state.history[state.view];
  if (hist.length === 0) addBubble(AGENTS[state.view].greeting, 'assistant', '', false);
  for (const m of hist) addBubble(m.text, m.who, m.cls || '', false);
}
function addBubble(text, who = 'assistant', cls = '', persist = true) {
  const row = document.createElement('div');
  row.className = `bubble-row ${who === 'user' ? 'user-row' : 'assistant-row'}`;
  const avatar = `<div class="avatar ${who}">${ico(who === 'user' ? 'user' : AGENTS[state.view].icon)}</div>`;
  const bubble = document.createElement('div');
  bubble.className = `bubble ${who} ${cls}`;
  if (who === 'assistant') bubble.innerHTML = renderMarkdown(text); else bubble.textContent = text;
  row.innerHTML = who === 'user' ? `<div class="bubble ${who} ${cls}"></div>${avatar}` : `${avatar}<div class="bubble ${who} ${cls}"></div>`;
  row.querySelector('.bubble').replaceWith(bubble);
  messagesEl.appendChild(row);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  if (persist) state.history[state.view].push({ text, who, cls });
  return row;
}
function setBubbleText(row, text) { const b = row.querySelector('.bubble'); b.textContent = text; b.classList.remove('notice'); messagesEl.scrollTop = messagesEl.scrollHeight; }
function setBubbleHtml(row, text) { const b = row.querySelector('.bubble'); b.innerHTML = renderMarkdown(text); b.classList.remove('notice'); messagesEl.scrollTop = messagesEl.scrollHeight; }

/* ---------------- suggested prompts ---------------- */
function renderSuggestions() {
  suggestionsEl.innerHTML = AGENTS[state.view].suggestions
    .map((s) => {
      const label = typeof s === 'string' ? s : s.label;
      const text = typeof s === 'string' ? s : s.text;
      const title = text === label ? '' : ` title="${escapeHtml(text)}"`;
      return `<button class="chip" type="button" data-text="${escapeHtml(text)}"${title}>`
        + `${ico('spark', 'chip-ic')}<span>${escapeHtml(label)}</span></button>`;
    }).join('');
  suggestionsEl.querySelectorAll('.chip').forEach((c) =>
    c.addEventListener('click', () => { input.value = c.dataset.text; sendMessage(); }));
}

/* ---------------- view switching ---------------- */
function setView(view) {
  if (state.voice) stopVoice();
  state.view = view;
  document.querySelectorAll('.agent-switch button').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  viewTitle.textContent = AGENTS[view].title;
  input.placeholder = AGENTS[view].placeholder;
  $('#view-inventory').hidden = view !== 'inventory';
  $('#view-delivery').hidden = view !== 'delivery';
  $('#view-orchestration').hidden = view !== 'orchestration';
  $('#view-evals').hidden = view !== 'evals';
  $('#view-finops').hidden = view !== 'finops';
  const report = view === 'evals' || view === 'finops';
  // Voice Live is configured for the inventory + delivery agents only.
  $('#voiceBtn').style.display = (view === 'orchestration' || report) ? 'none' : '';
  // Evaluations and FinOps are read-only report views: there is nothing to chat with.
  $('#chatForm').style.display = report ? 'none' : '';
  if (view === 'orchestration') initOrchestration();
  if (view === 'delivery') loadMemory();
  if (view === 'evals') loadEvals();
  if (view === 'finops') loadFinops();
  renderHistory();
  renderSuggestions();
}
document.querySelectorAll('.agent-switch button').forEach((b) => {
  b.innerHTML = `${ico(b.dataset.icon)}<span>${b.textContent}</span>`;
  b.addEventListener('click', () => setView(b.dataset.view));
});
$('#clearChat').addEventListener('click', () => {
  state.history[state.view] = [];
  state.prevRespId[state.view] = null;
  // Incident carries live run state (flow, agent cards, shared plan, diff/compliance blocks),
  // so clearing the conversation has to reset that visualization too.
  if (state.view === 'orchestration') resetOrchestrationView();
  renderHistory();
});

/* ---------------- evaluations (Foundry evaluation service) ---------------- */
const EVAL_AGENT_ICON = { inventory: 'box', delivery: 'truck', orchestration: 'workflow', other: 'shield' };

function evalPct(rate) { return rate === null || rate === undefined ? '—' : `${Math.round(rate * 100)}%`; }
function evalRateClass(rate) {
  if (rate === null || rate === undefined) return 'muted';
  if (rate >= 0.999) return 'ok';
  if (rate >= 0.7) return 'warn';
  return 'bad';
}
function evalWhen(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString();
}
function evalScore(v) {
  if (v === null || v === undefined) return '—';
  return typeof v === 'number' ? (Number.isInteger(v) ? String(v) : v.toFixed(2)) : escapeHtml(v);
}

async function loadEvals() {
  const listEl = $('#evalList');
  try {
    const res = await fetch('/api/evals');
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    const evaluations = data.evaluations || [];
    state.evals.items = evaluations;
    if (!evaluations.length) {
      listEl.innerHTML = `<div class="eval-empty">${ico('shield')} No evaluations in this Foundry project yet. Run
        <code>agents/inventory-agent/run_eval.py</code>, <code>agents/delivery-support-agent/run_eval.py</code> or
        <code>agents/incident-orchestration/run_eval.py</code> — results appear here and in the Foundry portal.</div>`;
      $('#evalDetail').innerHTML = '';
      return;
    }
    listEl.innerHTML = evaluations.map((ev) => {
      const run = ev.latest_run;
      const kinds = ['builtin', 'custom', 'rubric']
        .map((k) => ({ k, n: (ev.criteria || []).filter((c) => c.kind === k).length }))
        .filter((x) => x.n > 0)
        .map((x) => `<span class="ev-kind ${x.k}">${x.k} ${x.n}</span>`).join('');
      const bars = run ? (run.criteria || []).map((c) => `
        <div class="ev-crit">
          <span class="ev-crit-name">${escapeHtml(c.name)}</span>
          <span class="ev-bar"><i class="${evalRateClass(c.pass_rate)}" style="width:${Math.round((c.pass_rate || 0) * 100)}%"></i></span>
          <span class="ev-crit-rate ${evalRateClass(c.pass_rate)}">${evalPct(c.pass_rate)}</span>
        </div>`).join('') : '';
      return `
      <article class="eval-card" data-eval="${escapeHtml(ev.id)}">
        <header class="ev-head">
          <span class="ev-ic">${ico(EVAL_AGENT_ICON[ev.agent] || 'shield')}</span>
          <div class="ev-title">
            <strong>${escapeHtml(ev.name || ev.id)}</strong>
            <span class="ev-sub">${kinds} <em>${evalWhen(ev.created_at)}</em></span>
          </div>
          ${run ? `<span class="ev-score ${evalRateClass(run.pass_rate)}">${evalPct(run.pass_rate)}</span>` : '<span class="ev-score muted">no runs</span>'}
        </header>
        ${run ? `<div class="ev-runline">
            <span class="ev-status ${escapeHtml(run.status)}">${escapeHtml(run.status)}</span>
            <span>${escapeHtml(run.counts.passed)}/${escapeHtml(run.counts.total)} rows passed</span>
            ${run.report_url ? `<a class="ev-link" href="${escapeHtml(run.report_url)}" target="_blank" rel="noopener">open in Foundry ${ico('chevron')}</a>` : ''}
          </div>
          <div class="ev-crits">${bars}</div>
          <button class="ev-more" type="button" data-eval="${escapeHtml(ev.id)}" data-run="${escapeHtml(run.id)}">Row-level results</button>` : ''}
      </article>`;
    }).join('');
    listEl.querySelectorAll('.ev-more').forEach((b) =>
      b.addEventListener('click', () => loadEvalItems(b.dataset.eval, b.dataset.run)));
  } catch (e) {
    listEl.innerHTML = `<div class="error">${ico('warn')} Could not load evaluations: ${escapeHtml(e.message)}</div>`;
  }
}

async function loadEvalItems(evalId, runId) {
  const detail = $('#evalDetail');
  detail.innerHTML = `<div class="loading">Loading row-level results&hellip;</div>`;
  try {
    const res = await fetch(`/api/evals/${encodeURIComponent(evalId)}/runs/${encodeURIComponent(runId)}/items`);
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    const items = data.items || [];
    state.evals.selectedRun = runId;
    detail.innerHTML = `
      <header class="ev-detail-head">${ico('checklist')} Row-level results <b>${items.length}</b></header>
      ${items.map((item) => `
        <article class="ev-row">
          <div class="ev-row-q">${ico('quote')}${escapeHtml(item.query || '(no query)')}</div>
          ${item.response ? `<div class="ev-row-a">${escapeHtml(item.response.slice(0, 700))}${item.response.length > 700 ? '…' : ''}</div>` : ''}
          <div class="ev-row-scores">
            ${(item.results || []).map((r) => `
              <span class="ev-pill ${r.passed === false ? 'bad' : 'ok'}" title="${escapeHtml(r.reason || '')}">
                ${escapeHtml(r.name)} <b>${evalScore(r.score)}</b>${r.threshold !== null && r.threshold !== undefined ? `<i>/${evalScore(r.threshold)}</i>` : ''}
              </span>`).join('')}
          </div>
          ${(item.results || []).filter((r) => r.reason).slice(0, 2).map((r) => `
            <div class="ev-reason"><b>${escapeHtml(r.name)}:</b> ${escapeHtml(r.reason)}</div>`).join('')}
        </article>`).join('')}`;
    detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (e) {
    detail.innerHTML = `<div class="error">${ico('warn')} Could not load row results: ${escapeHtml(e.message)}</div>`;
  }
}

$('#evalRefresh').addEventListener('click', () => { $('#evalDetail').innerHTML = ''; loadEvals(); });

/* ---------------- inventory dashboard ---------------- */
async function loadDashboard() {
  try {
    const res = await fetch('/api/dashboard');
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    const kpiIcon = { product_lines: 'layers', total_skus: 'box', facilities: 'server', retail_stores: 'pin', critical: 'warn', low_stock: 'clock', in_stock: 'check' };
    $('#kpis').innerHTML = Object.entries(data.kpis).map(([k, v]) => `
      <article class="kpi"><span class="kpi-ic">${ico(kpiIcon[k] || 'chart')}</span><div><strong>${escapeHtml(v)}</strong><span>${label(k)}</span></div></article>`).join('');
    $('#lines').innerHTML = data.lines.map((line) => `
      <article class="line-card">
        <header class="line-head"><span class="lh-name">${ico('layers')}${escapeHtml(line.name)}</span><span class="channel">${escapeHtml(line.channel)}</span></header>
        <div class="product-grid">
          ${line.cards.map((c) => `
            <div class="product">
              <div class="product-top"><span class="sku">${escapeHtml(c.sku)}</span><span class="badge ${statusClass(c.status)}">${escapeHtml(c.status)}</span></div>
              <div class="name">${escapeHtml(c.name)}</div>
              <div class="qty">${ico('box')} ${escapeHtml(c.qty)} units</div>
            </div>`).join('')}
        </div>
      </article>`).join('');
  } catch (e) {
    $('#lines').innerHTML = `<div class="error">${ico('warn')} Could not load live inventory: ${escapeHtml(e.message)}</div>`;
  }
}

/* ---------------- order tracking card ---------------- */
function statusTone(l) { const s = (l || '').toLowerCase(); if (s.includes('deliver') && !s.includes('out')) return 'ok'; if (s.includes('exception')) return 'bad'; if (s.includes('delay')) return 'warn'; return 'info'; }
const fmt = (o, k) => escapeHtml(o[k] ?? '—');
function renderOrderCard(order) {
  if (!order || !order.order_id) return;
  const to = order.delivering_to || [order.deliver_city, order.deliver_state, order.deliver_zip].filter(Boolean).join(', ');
  const eta = order.estimated_delivery_display || order.estimated_delivery || '—';
  const delay = order.delay_reason ? `<div class="order-delay"><span class="warnicon">${ico('warn')}</span><div><div class="k">DELAY REASON</div><div>${escapeHtml(order.delay_reason)}</div></div></div>` : '';
  const notes = order.notes ? `<div class="order-notes"><div class="k">NOTES</div><div>${escapeHtml(order.notes)}</div></div>` : '';
  $('#orderCard').innerHTML = `
    <article class="order-card">
      <header class="order-head">
        <div><span class="k">ORDER</span> <strong>${escapeHtml(order.order_id)}</strong></div>
        <span class="order-status ${statusTone(order.status_label)}">${fmt(order, 'status_label')}</span>
      </header>
      <div class="order-track"><span class="k">TRACKING</span> ${fmt(order, 'tracking_number')}</div>
      <div class="order-grid">
        <div class="oi"><span class="ic">${ico('truck')}</span><div><div class="k">CARRIER</div><div>${fmt(order, 'carrier')}</div></div></div>
        <div class="oi"><span class="ic">${ico('calendar')}</span><div><div class="k">ESTIMATED DELIVERY</div><div>${escapeHtml(eta)}</div></div></div>
        <div class="oi"><span class="ic">${ico('pin')}</span><div><div class="k">LAST LOCATION</div><div>${fmt(order, 'last_location')}</div></div></div>
        <div class="oi"><span class="ic">${ico('user')}</span><div><div class="k">RECIPIENT</div><div>${fmt(order, 'recipient') !== '—' ? fmt(order, 'recipient') : fmt(order, 'recipient_name')}</div></div></div>
      </div>
      <div class="order-to"><span class="k">DELIVERING TO</span> ${escapeHtml(to || '—')}</div>
      ${delay}${notes}
      <footer class="order-foot">${ico('clock')} Last updated: ${fmt(order, 'last_updated')}</footer>
    </article>`;
}
async function fetchAndRenderOrder(orderId) {
  try { const res = await fetch(`/api/order/${encodeURIComponent(orderId)}`); if (res.ok) renderOrderCard(await res.json()); } catch { /* ignore */ }
}

/* ---------------- Foundry Memory panel (DeliverySupport) ---------------- */
const MEM_KIND = {
  user_profile: { label: 'Profile', icon: 'user' },
  chat_summary: { label: 'Past conversation', icon: 'quote' },
  procedural: { label: 'Learned habit', icon: 'loop' },
};
function memoryText(item) {
  const c = (item.content || '').trim();
  if (item.kind === 'procedural' && c.startsWith('{')) {
    try { return JSON.parse(c).instruction || c; } catch { return c; }
  }
  return c;
}
const MEM_OPEN_KEY = 'zava.memoryOpen';
let memoryOpen = localStorage.getItem(MEM_OPEN_KEY) === '1';

/* Foundry consolidates memories asynchronously, so "did it save?" needs an explicit re-read.
   `memSeen` is the last snapshot the user acknowledged (first load, refresh click, or clear) —
   automatic post-turn reloads deliberately leave it alone, so the next click still shows the delta. */
const memSignature = (payload) => (payload?.items || []).map((m) => `${m.kind}:${memoryText(m)}`);
/* A failed read returns `{enabled, error, items: []}` — never let that become the baseline, or the
   next refresh reports the whole store as "new". */
const memUsable = (payload) => Boolean(payload && payload.enabled && !payload.error);
let memSeen = [];
let memLoaded = false;

function applyMemoryOpen() {
  const list = $('#memList');
  const btn = $('#memToggle');
  if (list) list.hidden = !memoryOpen;
  if (btn) {
    btn.innerHTML = ico('chevron-down');
    btn.classList.toggle('open', memoryOpen);
    btn.setAttribute('aria-expanded', memoryOpen ? 'true' : 'false');
  }
}

function renderMemory(payload) {
  const panel = $('#memoryPanel');
  if (!panel) return;
  if (!payload || !payload.enabled) { panel.hidden = true; return; }
  panel.hidden = false;
  $('#memIcon').innerHTML = `${ico('brain')}<b>Foundry Memory</b>`;
  const items = payload.items || [];
  $('#memSub').textContent = payload.error
    ? payload.error
    : `${items.length} memor${items.length === 1 ? 'y' : 'ies'} · scope ${payload.scope}`;
  $('#memList').innerHTML = items.length
    ? items.map((m) => {
      const k = MEM_KIND[m.kind] || { label: m.kind, icon: 'dot' };
      return `<div class="mem-item k-${escapeHtml(m.kind)}">
          <span class="mi-ic">${ico(k.icon)}</span>
          <div><span class="mi-k">${escapeHtml(k.label)}</span><p>${escapeHtml(memoryText(m))}</p></div>
        </div>`;
    }).join('')
    : `<div class="mem-empty">${ico('sparkles')} Nothing remembered yet. Tell the agent a preference &mdash; e.g. <em>&ldquo;I'm Ana; always leave my parcels with the concierge&rdquo;</em> &mdash; then start a new conversation.</div>`;
  applyMemoryOpen();
}
async function loadMemory() {
  const panel = $('#memoryPanel');
  if (panel && panel.hidden) {
    // Reading Foundry takes a moment on a cold client — show the panel immediately.
    panel.hidden = false;
    $('#memIcon').innerHTML = `${ico('brain')}<b>Foundry Memory</b>`;
    $('#memSub').textContent = 'reading memory store…';
    $('#memList').innerHTML = `<div class="mem-item skeleton"></div><div class="mem-item skeleton"></div><div class="mem-item skeleton"></div>`;
    applyMemoryOpen();
  }
  try {
    const r = await fetch('/api/memory');
    if (r.ok) {
      const payload = await r.json();
      renderMemory(payload);
      if (memUsable(payload) && !memLoaded) { memSeen = memSignature(payload); memLoaded = true; }
      return payload;
    }
  } catch { /* */ }
  return null;
}
$('#memToggle').onclick = () => {
  memoryOpen = !memoryOpen;
  localStorage.setItem(MEM_OPEN_KEY, memoryOpen ? '1' : '0');
  applyMemoryOpen();
};
applyMemoryOpen();

$('#refreshMemory').innerHTML = ico('loop');
$('#refreshMemory').onclick = async () => {
  const btn = $('#refreshMemory');
  const before = memSeen;
  const hadBaseline = memLoaded;          // first read still in flight? then there is nothing to diff
  btn.disabled = true; btn.classList.add('spinning');
  try {
    const payload = await loadMemory();
    if (!payload) return;
    if (!memUsable(payload)) {
      const g = beginTrace('brain', 'Foundry Memory refresh failed', payload.scope || '');
      addTrace(g, { kind: 'error', title: 'could not read the store', subtitle: payload.error || 'memory disabled', status: 'error' });
      return;
    }
    const after = memSignature(payload);
    const added = hadBaseline ? after.filter((s) => !before.includes(s)) : [];
    const removed = hadBaseline ? before.filter((s) => !after.includes(s)) : [];
    memSeen = after;
    memLoaded = true;

    const g = beginTrace('brain', 'Foundry Memory refreshed',
      hadBaseline ? `${after.length} in scope · ${added.length} new` : `${after.length} in scope`);
    addTrace(g, {
      kind: 'memory',
      title: !hadBaseline
        ? `${after.length} memor${after.length === 1 ? 'y' : 'ies'} loaded`
        : added.length ? `${added.length} new memor${added.length === 1 ? 'y' : 'ies'}` : 'no change yet',
      subtitle: added.length
        ? added.map((s) => s.split(':').slice(1).join(':')).join(' · ').slice(0, 140)
        : hadBaseline ? 'consolidation can take a few seconds — click again' : 'baseline for the next refresh',
      status: 'completed',
      detail: removed.length ? `removed: ${removed.length}` : null,
    });
    if (added.length || removed.length) {
      const panel = $('#memoryPanel');
      panel.classList.remove('mem-flash');
      void panel.offsetWidth;  // restart the CSS animation
      panel.classList.add('mem-flash');
    }
  } finally {
    btn.disabled = false; btn.classList.remove('spinning');
  }
};

$('#clearMemory').innerHTML = ico('trash');
$('#clearMemory').onclick = async () => {
  try {
    await fetch('/api/memory', { method: 'DELETE' });
    memSeen = []; memLoaded = false;
    await loadMemory();
    const g = beginTrace('brain', 'Foundry Memory cleared', 'demo reset — scope emptied');
    addTrace(g, { kind: 'memory', title: 'delete_scope', subtitle: 'all memories forgotten', status: 'completed' });
  } catch { /* */ }
};

/* ---------------- FinOps (AI Gateway telemetry) ---------------- */
let finHours = 24;

const money = (v) => (v >= 1 ? `$${v.toFixed(2)}` : v >= 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(6)}`);
const compact = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : `${n}`);

function finRows(items, key, max) {
  return items.map((it) => {
    // One bar per row, split so the cheap half and the expensive half are visually distinct:
    // output tokens usually cost 4x input, which is the whole point of showing them apart.
    const w = (v) => (max ? Math.max((v / max) * 100, v ? 1.5 : 0) : 0);
    const cached = it.cached || 0;
    return `<div class="fin-row">
      <div class="name">
        <b>${escapeHtml(String(it[key] ?? 'unknown'))}</b>
        <span>${it.calls} call${it.calls === 1 ? '' : 's'} · ${compact(it.total)} tokens${
          it.models && it.models.length > 1 ? ` · ${it.models.length} models` : ''}</span>
      </div>
      <div class="fin-bar" title="${it.prompt} in / ${it.completion} out">
        <i class="cache" style="width:${w(cached)}%"></i>
        <i class="in" style="width:${w(it.prompt - cached)}%"></i>
        <i class="out" style="width:${w(it.completion)}%"></i>
      </div>
      <div class="fin-cost"><b>${money(it.cost)}</b><span>${compact(it.prompt)} in · ${compact(it.completion)} out</span></div>
    </div>`;
  }).join('');
}

function finCard(title, hint, items, key) {
  if (!items || !items.length) return '';
  const max = Math.max(...items.map((i) => i.total || 0), 1);
  return `<section class="fin-card">
    <header><h3>${title}</h3><span class="hint">${hint}</span></header>
    <div class="fin-rows">${finRows(items, key, max)}</div>
    <div class="fin-legend">
      <span><i class="in"></i>input</span><span><i class="out"></i>output</span><span><i class="cache"></i>cached</span>
    </div>
  </section>`;
}

function finSpark(timeline) {
  if (!timeline || timeline.length < 2) return '';
  const max = Math.max(...timeline.map((p) => p.cost || 0), 1e-9);
  const bars = timeline.map((p) => {
    const when = new Date(p.t);
    const label = Number.isNaN(when.getTime()) ? '' : when.toLocaleString();
    return `<div class="b" style="height:${Math.max((p.cost / max) * 100, 2)}%"
      data-tip="${label} · ${money(p.cost)} · ${p.calls} calls"></div>`;
  }).join('');
  return `<section class="fin-card">
    <header><h3>Spend over time</h3><span class="hint">cost per bucket</span></header>
    <div class="fin-spark">${bars}</div>
  </section>`;
}

function renderFinops(d) {
  const body = $('#finBody');
  $('#finSource').innerHTML = `via <b>${escapeHtml(d.gateway || 'AI Gateway')}</b>`;

  if (!d.enabled) {
    body.innerHTML = `<div class="fin-empty">
      <h3>Gateway telemetry unavailable</h3>
      <p>${escapeHtml(d.error || 'Log Analytics could not be reached.')}</p>
    </div>`;
    return;
  }
  const t = d.totals || {};
  if (!t.calls) {
    body.innerHTML = `<div class="fin-empty">
      <h3>No gateway traffic in this window</h3>
      <p>Nothing has gone through <code>${escapeHtml(d.gateway)}</code> in the last ${d.hours}h.
      Only calls that use the gateway endpoint are costed here &mdash; traffic sent straight to the
      Foundry endpoint is invisible to FinOps, which is rather the point.</p>
    </div>`;
    return;
  }

  const proj = d.projection || {};
  body.innerHTML = `
    <section class="fin-kpis">
      <article class="fin-kpi accent"><span class="k">Spend</span><span class="v">${money(t.cost)}</span><span class="s">last ${d.hours}h</span></article>
      <article class="fin-kpi"><span class="k">Run rate</span><span class="v">${proj.per_month ? money(proj.per_month) : '—'}</span><span class="s">projected / month</span></article>
      <article class="fin-kpi"><span class="k">Calls</span><span class="v">${t.calls}</span><span class="s">${money(t.cost_per_call || 0)} each</span></article>
      <article class="fin-kpi"><span class="k">Tokens</span><span class="v">${compact(t.total)}</span><span class="s">${compact(t.prompt)} in · ${compact(t.completion)} out</span></article>
      <article class="fin-kpi"><span class="k">Cached</span><span class="v">${t.cached_pct}%</span><span class="s">of input tokens</span></article>
    </section>
    ${finCard('Cost by agent', 'which agent spends the money', d.by_agent, 'agent')}
    ${finCard('Cost by caller', 'which surface originated it', d.by_caller, 'caller')}
    ${finCard('Cost by model', 'rate applied per model', d.by_model, 'model')}
    ${finSpark(d.timeline)}
    <section class="fin-card">
      <header><h3>Rates used</h3><span class="hint">${d.currency} per 1M tokens · app/pricing.json</span></header>
      <table class="fin-price">
        <thead><tr><th>Model</th><th>Input</th><th>Output</th><th>Tokens</th><th>Cost</th></tr></thead>
        <tbody>${d.by_model.map((m) => `<tr>
          <td>${escapeHtml(m.model)}</td><td>${m.rate_in}</td><td>${m.rate_out}</td>
          <td>${compact(m.total)}</td><td>${money(m.cost)}</td></tr>`).join('')}</tbody>
      </table>
      <p class="fin-note">Token counts are measured at the gateway; prices come from a local table,
      so this models your bill rather than reproducing it. Attribution uses the
      <code>x-zava-caller</code> and <code>x-zava-agent</code> headers &mdash; callers that do not
      send them show up as <code>unknown</code>.</p>
    </section>`;
}

async function loadFinops() {
  const body = $('#finBody');
  body.innerHTML = `<div class="loading">Reading AI Gateway telemetry…</div>`;
  try {
    const r = await fetch(`/api/finops?hours=${finHours}`);
    if (r.ok) renderFinops(await r.json());
    else body.innerHTML = `<div class="fin-empty"><h3>Request failed</h3><p>HTTP ${r.status}</p></div>`;
  } catch (e) {
    body.innerHTML = `<div class="fin-empty"><h3>Request failed</h3><p>${escapeHtml(String(e))}</p></div>`;
  }
}

$('#finRange').addEventListener('click', (ev) => {
  const btn = ev.target.closest('button[data-hours]');
  if (!btn) return;
  finHours = Number(btn.dataset.hours);
  $('#finRange').querySelectorAll('button').forEach((b) => b.classList.toggle('active', b === btn));
  loadFinops();
});
$('#finRefresh').addEventListener('click', loadFinops);

/* ---------------- text chat ---------------- */
async function sendMessage() {
  const message = input.value.trim();
  if (!message) return;
  input.value = '';
  if (state.view === 'orchestration') { addBubble(message, 'user'); runOrchestration(message); return; }
  const view = state.view;
  addBubble(message, 'user');
  const group = beginTrace(AGENTS[view].icon, view === 'delivery' ? 'DeliverySupport' : 'InventoryAgent', message.slice(0, 90));
  const pending = addBubble(view === 'delivery' ? 'Checking your order…' : 'Checking live inventory…', 'assistant', 'notice', false);
  try {
    const res = await fetch('/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, agent: view, previous_response_id: state.prevRespId[view] }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Chat request failed');
    state.prevRespId[view] = data.response_id || state.prevRespId[view];
    addTraces(group, data.trace || []);
    setBubbleHtml(pending, data.answer);
    state.history[view].push({ text: data.answer, who: 'assistant' });
    if (view === 'delivery') {
      if (data.order) renderOrderCard(data.order);
      else { const m = message.match(/\b(\d{4,6})\b/); if (m) fetchAndRenderOrder(m[1]); }
      if (data.memory) renderMemory(data.memory);
      // Foundry consolidates memories a few seconds after the turn goes quiet.
      setTimeout(loadMemory, 8000);
    }
  } catch (err) {
    addTrace(group, { kind: 'error', title: 'request failed', subtitle: err.message, status: 'error' });
    setBubbleText(pending, err.message);
  }
}
form.addEventListener('submit', (e) => { e.preventDefault(); sendMessage(); });

/* ==================================================================
   Voice Live client — real Foundry Voice Live via the broker WS.
   ================================================================== */
const SAMPLE_RATE = 24000;
function floatTo16BitBase64(float32) {
  const buf = new ArrayBuffer(float32.length * 2), view = new DataView(buf);
  for (let i = 0; i < float32.length; i++) { let s = Math.max(-1, Math.min(1, float32[i])); view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true); }
  let bin = ''; const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}
function base64ToInt16(b64) { const bin = atob(b64), bytes = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i); return new Int16Array(bytes.buffer); }
function setVoiceStatus(text, cls = '', icon = '') {
  voiceStatus.hidden = !text;
  voiceStatus.innerHTML = text ? `${icon ? ico(icon) : ''}<span>${escapeHtml(text)}</span>` : '';
  voiceStatus.className = `voice-status ${cls}`;
}
function setVoiceActiveUI(active, speaking = false) {
  const btn = $('#voiceBtn');
  btn.classList.toggle('live', active);
  btn.classList.toggle('speaking', speaking);
  btn.title = active ? 'Stop Voice Live' : 'Start Voice Live';
  $('#voiceIcon').innerHTML = ico(active ? 'stop' : 'mic');
}

async function startVoice() {
  if (state.voice) return;
  const agent = state.view;
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } }); }
  catch { setVoiceStatus('Microphone access is required for voice.', 'err', 'micOff'); return; }
  const ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: SAMPLE_RATE });
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/api/voice/${agent}`);
  const group = beginTrace('broadcast', `Voice Live · ${agent === 'delivery' ? 'DeliverySupport' : 'InventoryAgent'}`, 'realtime session');
  const session = { agent, stream, ctx, ws, nextTime: 0, playing: [], liveRow: null, liveText: '', group, calls: {} };
  state.voice = session; setVoiceActiveUI(true); setVoiceStatus('Connecting to Voice Live…', 'wait', 'loop');

  ws.onopen = () => {
    setVoiceStatus('Listening — speak in any supported language. Click the button again to stop.', 'live', 'broadcast');
    addTrace(group, { kind: 'voice', title: 'session opened', subtitle: 'gpt-realtime-mini · pcm16 24 kHz · multilingual VAD', status: 'completed' });
    const source = ctx.createMediaStreamSource(stream);
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    const mute = ctx.createGain(); mute.gain.value = 0;
    source.connect(proc); proc.connect(mute); mute.connect(ctx.destination);
    session.proc = proc; session.source = source;
    proc.onaudioprocess = (ev) => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'input_audio_buffer.append', audio: floatTo16BitBase64(ev.inputBuffer.getChannelData(0)) })); };
  };
  ws.onmessage = (ev) => {
    let evt; try { evt = JSON.parse(ev.data); } catch { return; }
    const t = evt.type;
    if (t === 'error') {
      setVoiceStatus('Voice error: ' + (evt.error?.message || 'unknown'), 'err', 'warn');
      addTrace(group, { kind: 'error', title: 'voice error', subtitle: evt.error?.message || 'unknown', status: 'error' });
    }
    else if (t === 'input_audio_buffer.speech_started') { flushPlayback(session); setVoiceStatus('Hearing you…', 'live', 'mic'); }
    else if (t === 'input_audio_buffer.speech_stopped') { setVoiceStatus('Thinking…', 'wait', 'loop'); }
    else if (t === 'conversation.item.input_audio_transcription.completed' && evt.transcript) {
      const text = evt.transcript.trim();
      addBubble(text, 'user');
      addTrace(group, { kind: 'voice', title: 'you said', subtitle: text.slice(0, 110), status: 'completed' });
    }
    else if (t === 'response.audio.delta' && evt.delta) { setVoiceActiveUI(true, true); enqueueAudio(session, evt.delta); }
    else if (t === 'response.audio_transcript.delta' || t === 'response.output_text.delta') {
      session.liveText += (evt.delta || '');
      if (!session.liveRow) session.liveRow = addBubble(session.liveText, 'assistant', '', false);
      else setBubbleText(session.liveRow, session.liveText);
    }
    else if (t === 'response.function_call_arguments.done') {
      let args = {};
      try { args = JSON.parse(evt.arguments || '{}'); } catch { /* */ }
      addTrace(group, {
        kind: 'tool', title: evt.name || 'tool', subtitle: 'Voice Live function call',
        status: 'completed', args: JSON.stringify(args, null, 2), detail: null,
      });
      if (agent === 'delivery' && args.order_id) fetchAndRenderOrder(args.order_id);
    }
    else if (t === 'response.done') {
      setVoiceActiveUI(true, false);
      if (state.voice === session) setVoiceStatus('Listening — speak in any supported language. Click the button again to stop.', 'live', 'broadcast');
      if (session.liveRow) {
        setBubbleHtml(session.liveRow, session.liveText);
        state.history[agent].push({ text: session.liveText, who: 'assistant' });
        addTrace(group, { kind: 'voice', title: 'agent replied', subtitle: session.liveText.slice(0, 110), status: 'completed' });
      }
      session.liveRow = null; session.liveText = '';
    }
  };
  ws.onclose = () => { if (state.voice === session) teardownVoice(session); };
  ws.onerror = () => setVoiceStatus('Voice Live connection error.', 'err', 'warn');
}
function enqueueAudio(session, b64) {
  const int16 = base64ToInt16(b64), f32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) f32[i] = int16[i] / 32768;
  const buf = session.ctx.createBuffer(1, f32.length, SAMPLE_RATE); buf.getChannelData(0).set(f32);
  const src = session.ctx.createBufferSource(); src.buffer = buf; src.connect(session.ctx.destination);
  const now = session.ctx.currentTime; if (session.nextTime < now) session.nextTime = now;
  src.start(session.nextTime); session.nextTime += buf.duration; session.playing.push(src);
  src.onended = () => { session.playing = session.playing.filter((s) => s !== src); };
}
function flushPlayback(session) { for (const s of session.playing) { try { s.stop(); } catch { /* */ } } session.playing = []; session.nextTime = 0; }
function teardownVoice(session) {
  try { session.proc && session.proc.disconnect(); } catch { }
  try { session.source && session.source.disconnect(); } catch { }
  try { session.stream.getTracks().forEach((t) => t.stop()); } catch { }
  try { session.ctx.close(); } catch { }
  state.voice = null; setVoiceActiveUI(false); setVoiceStatus('');
}
function stopVoice() { const s = state.voice; if (!s) return; try { s.ws.close(); } catch { } teardownVoice(s); }
$('#voiceBtn').addEventListener('click', () => { if (state.voice) stopVoice(); else startVoice(); });

/* ==================================================================
   Incident-response orchestration — animated MAF flow + Agent Harness.
   ================================================================== */
const ORCH_NODES = ['triage', 'code_fix', 'compliance'];
const ORCH_FW = { triage: 'LangGraph', code_fix: 'GitHub Copilot SDK', compliance: 'Foundry prompt agent' };
const ORCH_NAME = { triage: 'Triage', code_fix: 'Code Fix', compliance: 'Compliance' };
const ORCH_ICON = { triage: 'filter', code_fix: 'code', compliance: 'shield' };
const ORCH_ADAPTER = { triage: 'LangGraphTriageClient', code_fix: 'CopilotCodeFixClient', compliance: 'FoundryComplianceClient' };
const TOOL_ICON = { graph: 'route', file: 'quote', shell: 'server', agent: 'bot', policy: 'book', mcp: 'wrench' };
const CAP_STATE_LABEL = { on: 'active', off: 'available', na: 'harness factory' };
const PARAMS_OPEN_KEY = 'zava.harnessParamsOpen';
const orch = {
  running: false,
  scenario: null,
  timers: {},
  group: null,
  ws: null,
  showParams: localStorage.getItem(PARAMS_OPEN_KEY) === '1',
  todos: [],
};

/* Map a live harness_step tool/step name onto one of the declared tool chips. */
function matchToolChip(agentId, step, tool) {
  const probe = `${tool || ''} ${step || ''}`.toLowerCase();
  if (agentId === 'code_fix') {
    if (/pytest|bash|shell|terminal|run|assess/.test(probe)) return 'shell';
    if (/write|edit|create|apply|patch|replace|execute/.test(probe)) return 'edit';
    if (/read|view|list|glob|grep|plan/.test(probe)) return 'read';
    return null;
  }
  if (agentId === 'triage') return /route/.test(probe) ? 'route' : 'classify';
  if (agentId === 'compliance') return /fallback/.test(probe) ? 'policy fallback' : (agentMeta('compliance').tools || [{}])[0].name;
  return null;
}
function agentMeta(id) {
  const list = (orch.scenario && orch.scenario.agents) || [];
  return list.find((a) => a.id === id) || { id, name: ORCH_NAME[id], framework: ORCH_FW[id], tools: [] };
}

async function initOrchestration() {
  if (!orch.scenario) {
    try { const r = await fetch('/api/orchestration/scenario'); if (r.ok) orch.scenario = await r.json(); } catch { /* */ }
  }
  renderFlow();
  renderAgentCards();
  renderIncidentDetail();
}

function toolChips(n) {
  const tools = agentMeta(n).tools || [];
  if (!tools.length) return '';
  return `<div class="fn-tools">${tools.map((t) => `
    <span class="tool-chip" id="tc-${n}-${cssId(t.name)}" title="${escapeHtml(t.note || '')}">
      ${ico(TOOL_ICON[t.kind] || 'wrench')}<b>${escapeHtml(t.name)}</b>
    </span>`).join('')}</div>`;
}
function cssId(v) { return String(v).replace(/[^a-z0-9]+/gi, '-').toLowerCase(); }

/* The shared remediation plan (MAF todo provider) — Triage writes it, Code Fix ticks items
   off from real signals, Compliance verifies. Re-rendered on every `todo_updated` event. */
function renderTodos() {
  const box = document.getElementById('harnessTodos');
  if (!box) return;
  const items = orch.todos || [];
  if (!items.length) { box.hidden = true; return; }
  box.hidden = false;
  const done = items.filter((t) => t.done).length;
  box.innerHTML = `
    <div class="ht-head">${ico('checklist')}<b>Shared plan</b>
      <span class="ht-count">${done}/${items.length} done</span>
      <span class="ht-src">SharedTodoStore &middot; MAF todo provider</span>
    </div>
    <ol class="ht-list">
      ${items.map((t) => `
        <li class="ht-item ${t.done ? 'done' : ''}">
          <span class="ht-box">${t.done ? ico('check') : ''}</span>
          <span class="ht-txt">${escapeHtml(t.title || '')}</span>
        </li>`).join('')}
    </ol>`;
}

function harnessParamsHtml(h) {
  if (!h || !h.parameters) return '';
  return `
    <div class="harness-params" id="harnessParams" ${orch.showParams ? '' : 'hidden'}>
      <div class="hp-grid">
        ${h.parameters.map((p) => `
          <div class="hp-item" title="${escapeHtml(p.note || '')}">
            <span class="hp-k">${escapeHtml(p.label)}</span>
            <span class="hp-v">${escapeHtml(p.value)}</span>
            <span class="hp-n">${escapeHtml(p.note || '')}</span>
          </div>`).join('')}
      </div>
      <div class="hp-caps">
        <span class="hp-caps-title">${ico('sparkles')} Harness capabilities</span>
        ${(h.capabilities || []).map((c) => `
          <span class="cap ${c.state}" title="${escapeHtml(c.note || '')}">
            ${ico(c.state === 'on' ? 'check' : c.state === 'off' ? 'dot' : 'x')}${escapeHtml(c.label)}
            <i>${escapeHtml(CAP_STATE_LABEL[c.state] || c.state)}</i>
          </span>`).join('')}
      </div>
    </div>`;
}

function renderFlow() {
  Object.values(orch.timers).forEach(clearInterval); orch.timers = {};
  const h = (orch.scenario && orch.scenario.harness) || null;
  const node = (n) => {
    const meta = agentMeta(n);
    return `
    <div class="flow-node" id="node-${n}" data-state="idle">
      <div class="fn-top"><span class="fn-ic">${ico(ORCH_ICON[n])}</span><span class="fn-fw">${escapeHtml(ORCH_FW[n])}</span></div>
      <div class="fn-name">${escapeHtml(ORCH_NAME[n])}</div>
      ${meta.model ? `<div class="fn-model">${ico('cpu')}${escapeHtml(meta.model)}</div>` : ''}
      ${toolChips(n)}
      <div class="fn-meta"><span class="fn-status" id="status-${n}">idle</span><span class="fn-time" id="time-${n}"></span></div>
      ${n === 'code_fix' ? '<div class="fn-loopwrap" id="loopWrap" hidden><div class="fn-loopbadge">' + ico('loop') + '<span id="loopIter">harness loop</span></div><div class="fn-loop" id="loopSteps"></div></div>' : ''}
    </div>`;
  };
  $('#orchFlow').innerHTML = `
    <div class="harness" id="harness">
      <header class="harness-head">
        <span class="hh-title">${ico('layers')} MAF Agent Harness</span>
        <span class="hh-meta">
          <span class="hh-pill">${ico('route')}${escapeHtml((h && h.pattern) || 'SequentialBuilder')}</span>
          <span class="hh-pill">${ico('layers')}${escapeHtml((h && h.surface) || 'BaseChatClient')}</span>
        </span>
        <button class="hh-toggle ${orch.showParams ? '' : 'off'}" id="toggleParams" title="Show/hide harness parameters">${ico('panel')}<span>Parameters</span></button>
        <span class="hh-badge">${ico('server')} ${escapeHtml((h && h.hosting) || 'in-process')} &middot; ${escapeHtml((h && h.name) || 'IncidentOrchestrator')}</span>
      </header>
      ${harnessParamsHtml(h)}
      <div class="harness-todos" id="harnessTodos" hidden></div>
      <div class="flow-track">
        ${node('triage')}
        <div class="flow-link" id="link-0" data-state="idle"><span class="fl-dot"></span></div>
        ${node('code_fix')}
        <div class="flow-link" id="link-1" data-state="idle"><span class="fl-dot"></span></div>
        ${node('compliance')}
      </div>
      <div class="harness-rail">
        <div class="rail-drops">${ORCH_NODES.map((n) => `<span class="drop" id="drop-${n}"></span>`).join('')}</div>
        <div class="adapters">
          ${ORCH_NODES.map((n) => `
            <div class="adapter" id="ad-${n}">
              <b>${escapeHtml(agentMeta(n).adapter || ORCH_ADAPTER[n])}</b>
              <span>BaseChatClient adapter</span>
            </div>`).join('')}
        </div>
        <div class="rail-line"><span class="rail-pulse" id="railPulse"></span></div>
        <div class="rail-foot">
          <span>${ico('zap')} MAF event bus</span>
          <span class="rf-events">${(((h && h.events) || ['agent_started', 'harness_step', 'agent_completed'])).map((e) => `<i id="ev-${cssId(e)}">${escapeHtml(e)}</i>`).join('')}</span>
          <span class="rf-right">${ico('route')} ${escapeHtml((h && h.pattern) || 'SequentialBuilder')}</span>
        </div>
      </div>
    </div>`;
  const toggle = $('#toggleParams');
  if (toggle) toggle.onclick = () => {
    orch.showParams = !orch.showParams;
    localStorage.setItem(PARAMS_OPEN_KEY, orch.showParams ? '1' : '0');
    const box = $('#harnessParams'); if (box) box.hidden = !orch.showParams;
    toggle.classList.toggle('off', !orch.showParams);
  };
  renderTodos();
}

/* Light up an event name on the bus footer whenever it fires. */
function pingEvent(name) {
  const el = document.getElementById(`ev-${cssId(name)}`);
  if (!el) return;
  el.classList.remove('fire'); void el.offsetWidth; el.classList.add('fire');
}
/* Light up the tool chip a live harness step used. */
function markTool(agentId, step, tool) {
  const name = matchToolChip(agentId, step, tool);
  if (!name) return;
  const el = document.getElementById(`tc-${agentId}-${cssId(name)}`);
  if (!el) return;
  el.classList.add('used');
  el.classList.remove('firing'); void el.offsetWidth; el.classList.add('firing');
}

function setLink(i, st) { const el = document.getElementById(`link-${i}`); if (el) el.dataset.state = st; }

function setNode(node, stateName, statusText) {
  const el = document.getElementById(`node-${node}`); if (!el) return;
  el.dataset.state = stateName;
  const st = document.getElementById(`status-${node}`); if (st && statusText) st.textContent = statusText;
  const i = ORCH_NODES.indexOf(node);
  const harness = document.getElementById('harness');
  const ad = document.getElementById(`ad-${node}`);
  const drop = document.getElementById(`drop-${node}`);

  if (stateName === 'active') {
    if (harness) harness.dataset.active = node;
    if (ad) ad.classList.add('on');
    if (drop) drop.classList.add('on');
    if (i > 0) setLink(i - 1, 'done');
    startNodeTimer(node);
  } else if (stateName === 'done' || stateName === 'fail') {
    if (ad) ad.classList.remove('on');
    if (drop) drop.classList.remove('on');
    if (i < ORCH_NODES.length - 1) setLink(i, stateName === 'fail' ? 'fail' : 'active');
    stopNodeTimer(node);
  } else {
    stopNodeTimer(node);
    const t = document.getElementById(`time-${node}`); if (t) t.textContent = '';
  }
}
function startNodeTimer(node) {
  if (orch.timers[node]) return; // already ticking — harness_step must not restart it
  const started = Date.now();
  const el = document.getElementById(`time-${node}`);
  const tick = () => { if (el) el.textContent = ((Date.now() - started) / 1000).toFixed(1) + 's'; };
  tick();
  orch.timers[node] = setInterval(tick, 100);
}
function stopNodeTimer(node) { if (orch.timers[node]) { clearInterval(orch.timers[node]); delete orch.timers[node]; } }

function addLoopStep(text, phase) {
  const wrap = document.getElementById('loopWrap');
  const box = document.getElementById('loopSteps');
  if (!box || !text) return;
  if (wrap) wrap.hidden = false;
  orch.loopCount = (orch.loopCount || 0) + 1;
  const it = document.getElementById('loopIter');
  if (it) it.textContent = `${phase ? phase + ' · ' : ''}step ${orch.loopCount}`;
  const line = document.createElement('div'); line.className = 'loop-step'; line.textContent = text;
  box.appendChild(line);
  while (box.children.length > 4) box.removeChild(box.firstChild);
}

function renderAgentCards(results = {}) {
  const meta = (orch.scenario && orch.scenario.agents) || ORCH_NODES.map((id) => ({ id, name: ORCH_NAME[id], framework: ORCH_FW[id], role: '' }));
  $('#orchAgents').innerHTML = meta.map((a) => `
    <article class="agent-card" id="card-${a.id}">
      <header><span class="ac-name">${ico(ORCH_ICON[a.id] || 'bot')}${escapeHtml(a.name)}</span><span class="ac-fw">${escapeHtml(a.framework)}</span></header>
      <div class="ac-role">${escapeHtml(a.role || '')}</div>
      <div class="ac-body" id="body-${a.id}"><span class="ac-idle">${ico('clock')} Waiting…</span></div>
    </article>`).join('');
  for (const [k, v] of Object.entries(results)) updateAgentCard(k, v);
}
function updateAgentCard(agent, result) {
  const body = document.getElementById(`body-${agent}`); if (!body || !result) return;
  const card = document.getElementById(`card-${agent}`); if (card) card.classList.add('filled');
  if (agent === 'triage') {
    body.innerHTML = `
      <div class="kv"><span>Severity</span><b class="sev-${escapeHtml(result.severity)}">${escapeHtml(result.severity)}</b></div>
      <div class="kv"><span>Category</span><b>${escapeHtml(result.category)}</b></div>
      <div class="kv"><span>Component</span><b>${escapeHtml(result.component)}</b></div>
      <div class="kv"><span>Route</span><b>${ico('route')} ${escapeHtml(result.route)}</b></div>`;
  } else if (agent === 'code_fix') {
    const badge = result.test_passed ? `<span class="pill ok">${ico('check')} tests pass</span>` : `<span class="pill bad">${ico('x')} tests fail</span>`;
    body.innerHTML = `
      <div class="kv"><span>Result</span>${badge}</div>
      <div class="kv"><span>Iterations</span><b>${escapeHtml(result.iterations)}</b></div>
      <div class="kv"><span>Files</span><b>${escapeHtml((result.files_changed || []).join(', ') || '—')}</b></div>
      <div class="kv"><span>Tools run</span><b>${escapeHtml(result.tool_calls ?? '—')}</b></div>`;
  } else if (agent === 'compliance') {
    const ok = result.decision === 'approved';
    const passed = (result.checks || []).filter((c) => c.status === 'pass').length;
    body.innerHTML = `
      <div class="kv"><span>Decision</span><span class="pill ${ok ? 'ok' : 'warn'}">${ico(ok ? 'shield' : 'warn')} ${escapeHtml(result.decision)}</span></div>
      <div class="kv"><span>Checks</span><b>${passed}/${(result.checks || []).length} pass</b></div>
      <div class="ac-rationale">${escapeHtml(result.rationale || '')}</div>`;
  }
}
function renderIncidentDetail() {
  const s = orch.scenario; if (!s) { $('#orchDetail').innerHTML = ''; return; }
  const inc = s.incident || {};
  $('#orchDetail').innerHTML = `
    <div class="detail-block">
      <h3>${ico('warn')} Incident ${escapeHtml(inc.incident_id || '')}</h3>
      <p>${escapeHtml(inc.description || '')}</p>
    </div>
    <div class="detail-block"><h3>${ico('code')} Seeded defect — reorder.py</h3>
      <pre class="code">${escapeHtml((s.buggy_code || '').slice(0, 1500))}</pre></div>`;
}
function renderCodeFixDetail(result) {
  if (!result) return;
  const diffHtml = escapeHtml(result.diff || '(no changes)').split('\n').map((l) => {
    const c = l.startsWith('+') && !l.startsWith('+++') ? 'add' : (l.startsWith('-') && !l.startsWith('---') ? 'del' : '');
    return `<span class="dl ${c}">${l || ' '}</span>`;
  }).join('\n');
  const el = document.createElement('div'); el.className = 'detail-block';
  el.innerHTML = `<h3>${ico('code')} Proposed fix — diff</h3><pre class="diff">${diffHtml}</pre>
    <h3>${ico('check')} Test output</h3><pre class="code">${escapeHtml(result.test_output || '')}</pre>`;
  $('#orchDetail').prepend(el);
}
function renderComplianceDetail(result) {
  if (!result) return;
  const rows = (result.checks || []).map((c) => `<span class="check ${(c.status || '').replace('/', '')}">${escapeHtml(c.id)}: ${escapeHtml(c.status)}</span>`).join('');
  const req = (result.required_changes || []).length ? `<h4>Required changes</h4><ul>${result.required_changes.map((r) => `<li>${escapeHtml(r)}</li>`).join('')}</ul>` : '';
  const el = document.createElement('div'); el.className = 'detail-block';
  el.innerHTML = `<h3>${ico('shield')} Compliance — ${escapeHtml(result.decision)}</h3><div class="checks">${rows}</div>${req}`;
  $('#orchDetail').prepend(el);
}

/** Build a readable chat summary from the pipeline's structured results.
 *  The raw `final_text` concatenates every agent's JSON payload, which reads poorly in a
 *  chat bubble — it stays available in full inside the traces panel. */
function orchestrationSummary(e) {
  const t = e.triage || {}, c = e.code_fix || {}, k = e.compliance || {};
  const checks = k.checks || [];
  const passed = checks.filter((x) => x.status === 'pass').length;
  const files = (c.files_changed || []).join(', ') || '—';
  const lines = [
    `### ${k.decision === 'approved' ? '✅' : '⚠️'} Incident pipeline complete`,
    '',
    '| Stage | Framework | Outcome |',
    '| --- | --- | --- |',
    `| **Triage** | LangGraph | ${t.severity || '—'} · ${t.category || '—'} · \`${t.component || '—'}\` → ${t.route || '—'} |`,
    `| **Code Fix** | GitHub Copilot SDK | ${c.test_passed ? 'tests pass' : 'tests fail'} · ${c.iterations ?? '—'} iteration(s) · \`${files}\` |`,
    `| **Compliance** | Foundry prompt agent | **${k.decision || '—'}** · ${passed}/${checks.length} checks pass |`,
  ];
  if (k.rationale) lines.push('', `**Rationale.** ${k.rationale}`);
  if ((k.required_changes || []).length) {
    lines.push('', '**Required changes**');
    for (const r of k.required_changes) lines.push(`- ${r}`);
  }
  return lines.join('\n');
}

/** Put the Incident visualization back to its pre-run state: flow nodes idle, agent cards
 *  waiting, shared plan empty and the detail column back to just the incident + seeded defect
 *  (dropping the diff / compliance blocks a previous run prepended). Any socket still open is
 *  torn down so a mid-run clear cannot keep painting the UI. */
function resetOrchestrationView() {
  if (orch.ws) {
    try { orch.ws.close(); } catch { /* already closing */ }
    orch.ws = null;          // stale socket handlers bail out on this identity check
  }
  orch.running = false;
  orch.todos = [];
  orch.loopCount = 0;
  orch.group = null;
  input.disabled = false;
  renderFlow(); renderAgentCards(); renderIncidentDetail();
  ORCH_NODES.forEach((n) => setNode(n, 'idle', 'queued'));
  setLink(0, 'idle'); setLink(1, 'idle');
}

function runOrchestration(message) {
  if (orch.running) { addBubble('An incident run is already in progress…', 'assistant', 'notice'); return; }
  resetOrchestrationView();
  orch.running = true;
  input.disabled = true;
  const group = beginTrace('workflow', 'IncidentOrchestrator', 'MAF SequentialBuilder · 3 frameworks');
  orch.group = group;
  const running = addBubble('Running the incident-response pipeline… (Triage → Code Fix → Compliance)', 'assistant', 'notice', false);

  // A short "run the sample" phrase replays the seeded ZAVA-INC-4821 incident; anything longer is
  // treated as a real incident report and sent to Triage verbatim.
  const isSample = !message || (message.length < 80 && /zava-inc-4821|reorder incident|sample incident/i.test(message));
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/api/orchestration/run`);
  orch.ws = ws;
  ws.onopen = () => ws.send(JSON.stringify({ incident: isSample ? '' : message }));
  ws.onmessage = (ev) => {
    if (orch.ws !== ws) return; // run was reset/superseded — ignore late events
    let e; try { e = JSON.parse(ev.data); } catch { return; }
    const a = e.agent;
    pingEvent(e.type);
    if (e.type === 'run_started') {
      addTrace(group, { kind: 'harness', title: 'harness started', subtitle: `event bus open · 3 BaseChatClient adapters${e.otel ? ' · OpenTelemetry on' : ''}`, status: 'completed' });
    }
    else if (e.type === 'todo_updated') {
      const prevDone = (orch.todos || []).filter((t) => t.done).length;
      orch.todos = e.todos || [];
      renderTodos();
      const done = orch.todos.filter((t) => t.done).length;
      addTrace(group, {
        kind: 'todo',
        title: done > prevDone ? `plan: ${done - prevDone} item(s) completed` : 'plan updated',
        subtitle: `SharedTodoStore · ${done}/${orch.todos.length} done`,
        status: 'completed',
        detail: orch.todos.map((t) => `${t.done ? '[x]' : '[ ]'} ${t.title}`).join('\n'),
      });
    }
    else if (e.type === 'agent_started') {
      setNode(a, 'active', 'running');
      addTrace(group, {
        kind: 'agent', title: `${ORCH_NAME[a] || a} started`,
        subtitle: `${ORCH_FW[a] || ''}${e.model ? ' · ' + e.model : ''}`, status: 'completed',
      });
      if (a === 'code_fix' && e.model) addLoopStep('model: ' + e.model);
    }
    else if (e.type === 'harness_step') {
      const detail = `${e.step || ''} · ${e.detail || e.tool || ''}`.trim();
      markTool(a, e.step, e.tool);
      if (a === 'code_fix') addLoopStep(detail, e.step);
      else setNode(a, 'active', e.step || 'working');
      addTrace(group, { kind: 'step', title: e.step || 'step', subtitle: `${ORCH_NAME[a] || a}${e.tool ? ' · ' + e.tool : ''}`, status: 'completed', detail: e.detail || null });
    }
    else if (e.type === 'agent_completed') {
      const failed = a === 'code_fix' && e.result && e.result.test_passed === false;
      setNode(a, failed ? 'fail' : 'done', failed ? 'tests fail' : 'done');
      updateAgentCard(a, e.result);
      addTrace(group, {
        kind: 'handoff', title: `${ORCH_NAME[a] || a} completed`,
        subtitle: a === 'compliance' ? `decision: ${e.result?.decision || '—'}` : 'handing off →',
        status: failed ? 'error' : 'completed',
        detail: e.result ? JSON.stringify(e.result, null, 2).slice(0, 1400) : null,
      });
      if (a === 'code_fix') renderCodeFixDetail(e.result);
      if (a === 'compliance') renderComplianceDetail(e.result);
    }
    else if (e.type === 'run_completed') {
      const ok = e.compliance && e.compliance.decision === 'approved';
      if (e.todos) { orch.todos = e.todos; renderTodos(); }
      setNode('compliance', ok ? 'done' : 'fail', (e.compliance && e.compliance.decision) || 'done');
      setLink(1, 'done');
      const summary = orchestrationSummary(e);
      setBubbleHtml(running, summary);
      state.history.orchestration.push({ text: summary, who: 'assistant' });
      addTrace(group, {
        kind: 'harness', title: 'run completed', subtitle: ok ? 'approved' : 'needs changes',
        status: ok ? 'completed' : 'error', detail: e.final_text || null,
      });
    }
    else if (e.type === 'error') {
      setBubbleText(running, 'Error: ' + (e.note || 'unknown'));
      addTrace(group, { kind: 'error', title: 'pipeline error', subtitle: e.note || 'unknown', status: 'error' });
    }
    else if (e.type === 'done') { try { ws.close(); } catch { /* */ } }
  };
  ws.onclose = () => {
    if (orch.ws !== ws) return;
    orch.ws = null; orch.running = false; input.disabled = false; ORCH_NODES.forEach(stopNodeTimer);
  };
  ws.onerror = () => {
    if (orch.ws !== ws) return;
    setBubbleText(running, 'Connection error running the pipeline.'); orch.running = false; input.disabled = false;
  };
}

/* ---------------- init ---------------- */
$('#sendBtn').innerHTML = ico('send');
$('#clearChat').innerHTML = ico('trash');
$('#tracesIcon').innerHTML = ico('activity');
$('#clearTraces').innerHTML = ico('trash');
$('#toggleTraces').innerHTML = ico('panel');
setVoiceActiveUI(false);
renderTraces();
setView('inventory');
loadDashboard();
setInterval(() => { if (state.view === 'inventory') loadDashboard(); }, 60000);
