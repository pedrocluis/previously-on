// Previously On — the page. Hash-routed, no framework; everything comes from
// window.pywebview.api (see app/api.py) as JSON and is rendered as HTML strings.
'use strict';

const main = document.getElementById('main');
const watchBox = document.getElementById('watch');
let lastStatus = null;
let pollTimer = null;

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}
function paras(text) {
  return String(text || '').trim().split(/\n\s*\n/).map(p => `<p>${esc(p).replace(/\n/g, '<br>')}</p>`).join('');
}
function plural(n, word) { return `${n} ${n === 1 ? word : word.endsWith('s') ? word + 'es' : word + 's'}`; }
function api() { return window.pywebview.api; }
async function call(name, ...args) {
  try {
    return await api()[name](...args);
  } catch (e) {
    return {error: String(e && e.message || e)};
  }
}
function errorBox(r) { return `<div class="card error">${esc(r.error)}</div>`; }

// --- watcher status (header) -------------------------------------------------

function stateLabel(s) {
  switch (s.state) {
    case 'waiting': return s.message || `Waiting for ${s.game}…`;
    case 'capturing': return `Capturing · ${plural(s.events, 'event')}`;
    case 'summarizing': return 'Writing the recap…';
    case 'error': return `Stopped: ${s.message}`;
    default: return s.running ? (s.message || 'Starting…') : 'Not watching';
  }
}

function renderWatch(s) {
  const btn = s.running
    ? `<button id="watch-btn" data-action="stop">Stop</button>`
    : `<button id="watch-btn" data-action="start" class="primary">Watch for ${esc(s.game)}</button>`;
  watchBox.innerHTML = `<span class="dot ${esc(s.state)}"></span><span>${esc(stateLabel(s))}</span>${btn}`;
  document.getElementById('watch-btn').onclick = async ev => {
    const r = await call(ev.target.dataset.action === 'stop' ? 'stop_watch' : 'start_watch');
    if (r.error) alert(r.error);
    poll();
  };
}

async function poll() {
  const s = await call('status');
  if (s.error) return;
  const prev = lastStatus;
  lastStatus = s;
  renderWatch(s);
  const page = location.hash.replace(/^#/, '') || 'home';
  if (page === 'home') {
    // A capture ending (recap written or skipped) changes the resume screen.
    const finished = prev && prev.state === 'summarizing' && s.state !== 'summarizing';
    const backfilled = prev && prev.summarize.state === 'running' && s.summarize.state !== 'running';
    if (finished || backfilled) renderHome();
    else if (s.state === 'capturing') renderFeed();
  }
}

// --- home ---------------------------------------------------------------------

async function renderHome() {
  const h = await call('home');
  if (h.error) { main.innerHTML = errorBox(h); return; }
  if (h.empty) {
    main.innerHTML = `<h1>Nothing logged yet</h1>
      <div class="card"><p>Start ${esc(h.game)}; this window watches the screen and logs what the game announces.
      When you come back, it tells you where you left off.</p>
      <p class="muted">Recaps need an API key — see <a href="#settings">Settings</a>.</p></div>
      <div id="feed"></div>`;
    renderFeed();
    return;
  }
  let recap;
  if (h.tier === 'one_line') {
    recap = `<p class="oneline">${esc(h.text)}</p>` +
      (h.full_text ? `<p><a href="#" id="show-full">Show the full recap anyway</a></p><div id="full" hidden>${paras(h.full_text)}</div>` : '');
  } else {
    recap = `<div class="recap">${paras(h.text)}</div>`;
  }
  let notice = '';
  if (h.needs_recap) {
    const st = lastStatus ? lastStatus.summarize : {state: 'idle'};
    const busy = st.state === 'running';
    notice = `<div class="card notice"><p>No recap for this session yet` +
      (st.state === 'failed' && st.session === h.session ? ` — ${esc(st.message)}` : '') + `.</p>
      <div class="row"><button id="summarize" class="primary" ${busy ? 'disabled' : ''}>${busy ? 'Writing the recap…' : 'Write it now'}</button>
      <span class="muted">Needs an API key (<a href="#settings">Settings</a>); only the text log is sent, never a frame.</span></div></div>`;
  }
  const st = h.state;
  let state = '';
  if (st && (st.location || st.objective || st.threads.length)) {
    state = `<h2>Where you are</h2><div class="card">` +
      (st.location ? `<p><strong>Location:</strong> ${esc(st.location)}</p>` : '') +
      (st.objective ? `<p><strong>Objective:</strong> ${esc(st.objective)}</p>` : '') +
      (st.threads.length ? `<p><strong>Open threads</strong></p><ul class="list">` +
        st.threads.map(t => `<li><strong>${esc(t.who)}</strong> — ${esc(t.what)}${t.status === 'unclear' ? ' <span class="badge">unclear</span>' : ''}</li>`).join('') + `</ul>` : '') +
      (st.npcs.length ? `<details><summary>${plural(st.npcs.length, 'NPC')} met</summary><ul>` +
        st.npcs.map(n => `<li><strong>${esc(n.name)}</strong>${n.location ? ` (${esc(n.location)})` : ''}${n.notes ? ` — ${esc(n.notes)}` : ''}</li>`).join('') + `</ul></details>` : '') +
      (st.items.length ? `<details><summary>Notable items</summary><ul>${st.items.map(i => `<li>${esc(i)}</li>`).join('')}</ul></details>` : '') +
      (h.state_from && h.state_from !== h.session ? `<p class="hint">From session ${esc(h.state_from)} — the newest one with a recap.</p>` : '') +
      `</div>`;
  }
  main.innerHTML = `<h1>Previously on ${esc(h.game)}…</h1>
    <p class="muted">Last played ${esc(h.gap)} · ${esc(h.date)} · ${esc(h.duration)} · <a href="#session/${esc(h.session)}">session details</a></p>
    <div class="card">${recap}</div>${notice}${state}<div id="feed"></div>`;
  const link = document.getElementById('show-full');
  if (link) link.onclick = e => { e.preventDefault(); document.getElementById('full').hidden = false; link.remove(); };
  const btn = document.getElementById('summarize');
  if (btn) btn.onclick = async () => {
    btn.disabled = true; btn.textContent = 'Writing the recap…';
    const r = await call('summarize', h.session);
    if (r.error) { alert(r.error); renderHome(); }
  };
  renderFeed();
}

async function renderFeed() {
  const box = document.getElementById('feed');
  if (!box) return;
  const s = lastStatus;
  if (!s || !s.running || s.state === 'waiting') { box.innerHTML = ''; return; }
  const r = await call('recent_events');
  const events = (r.events || []).slice().reverse();
  box.innerHTML = `<h2>${s.state === 'capturing' ? 'This session, live' : 'Last capture'}</h2>
    <div class="card"><p class="muted">${esc(s.message)}${s.state === 'capturing' ? ` · ${s.frames} frames · ${s.ocr_calls} OCR calls` : ''}</p>
    <ul class="list feed">${events.map(e => `<li><span class="t">${esc(clock(e.t_rel))}</span> <span class="muted">${esc(e.type)}</span> ${esc(e.text)}</li>`).join('') || '<li class="muted">No events yet.</li>'}</ul></div>`;
}

function clock(t) {
  t = Math.floor(t); const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60;
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

// --- sessions -----------------------------------------------------------------

function bossLine(b) {
  return b.defeated ? `${b.name} felled in ${b.attempts} ${b.attempts === 1 ? 'try' : 'tries'}`
                    : `${b.name}: ${plural(b.attempts, 'death')}, still standing`;
}

async function renderSessions() {
  const r = await call('sessions');
  if (r.error) { main.innerHTML = errorBox(r); return; }
  if (!r.sessions.length) { main.innerHTML = `<h1>Sessions</h1><p class="muted">Nothing logged yet.</p>`; return; }
  main.innerHTML = `<h1>Sessions</h1><ul class="list">` + r.sessions.map(s => `
    <li><div class="session-row">
      <a href="#session/${esc(s.session)}" class="date">${esc(s.date)}</a>
      <div>${esc(s.one_line)}${s.summary ? `<div class="muted">${esc(s.summary)}</div>` : ''}</div>
      <span class="badge ${s.has_recap ? 'good' : 'warn'}">${s.has_recap ? 'recap' : 'no recap'}</span>
    </div></li>`).join('') + `</ul>`;
}

async function renderSession(stamp) {
  const s = await call('session', stamp);
  if (s.error) { main.innerHTML = errorBox(s); return; }
  const types = [...new Set(s.event_list.map(e => e.type))];
  const conv = s.conversations.map(c => {
    const who = c.basis === 'named' ? esc(c.speaker) : c.basis === 'inferred' ? `probably ${esc(c.speaker)}` : 'Unknown speaker';
    return `<li><span class="speaker ${esc(c.basis)}">${who}</span>${c.location ? ` <span class="muted">· ${esc(c.location)}</span>` : ''}${c.at ? ` <span class="muted">· ${esc(c.at)}</span>` : ''}<br>${esc(c.gist)}</li>`;
  }).join('');
  main.innerHTML = `<h1>${esc(s.date)}</h1>
    <p class="muted">${esc(s.one_line)} · ${plural(s.events, 'event')}</p>
    ${s.summary ? `<div class="card recap">${paras(s.summary)}</div>` : `<div class="card notice"><p>No recap for this session. <a href="#home">Write it from the resume screen</a> when it is the latest one, or run <code>previously-on summarize</code>.</p></div>`}
    ${s.bosses.length ? `<h2>Fights</h2><div class="card"><ul class="list">${s.bosses.map(b => `<li>${esc(bossLine(b))}</li>`).join('')}</ul></div>` : ''}
    ${s.areas.length ? `<h2>Areas</h2><div class="card">${s.areas.map(esc).join(' · ')}</div>` : ''}
    ${conv ? `<h2>Conversations</h2><div class="card"><ul class="list">${conv}</ul></div>` : ''}
    ${s.full_recap ? `<details class="card"><summary>Short and full recap text</summary>${paras(s.short_recap)}<hr>${paras(s.full_recap)}</details>` : ''}
    ${s.dropped.length ? `<details class="card"><summary>${plural(s.dropped.length, 'detail')} left out by verification</summary><ul>${s.dropped.map(d => `<li>${esc(d)}</li>`).join('')}</ul></details>` : ''}
    <h2>Events</h2>
    <div class="row kinds" id="type-filter">${types.map(t => `<label><input type="checkbox" value="${esc(t)}" checked>${esc(t)}</label>`).join('')}</div>
    <table><thead><tr><th>#</th><th>at</th><th>type</th><th>text</th></tr></thead><tbody id="events"></tbody></table>`;
  const draw = () => {
    const on = new Set([...document.querySelectorAll('#type-filter input:checked')].map(i => i.value));
    document.getElementById('events').innerHTML = s.event_list.filter(e => on.has(e.type)).map(e =>
      `<tr><td class="t">${e.index}</td><td class="t">${esc(e.at)}</td><td class="type">${esc(e.type)}</td><td>${esc(e.text)}</td></tr>`).join('');
  };
  document.getElementById('type-filter').onchange = draw;
  draw();
}

// --- timeline -------------------------------------------------------------------

async function renderTimeline() {
  const r = await call('timeline');
  if (r.error) { main.innerHTML = errorBox(r); return; }
  if (!r.sessions.length) { main.innerHTML = `<h1>Timeline</h1><p class="muted">Nothing logged yet.</p>`; return; }
  const t = r.totals;
  main.innerHTML = `<h1>Timeline</h1><p class="totals">${esc(t.line)}</p>
    <p class="muted">${plural(t.sessions, 'session')} · ${plural(t.bosses_felled, 'boss')} felled</p>` +
    r.sessions.map(s => `<div class="card">
      <h3><a href="#session/${esc(s.session)}">${esc(s.date)}</a> <span class="muted">· ${esc(s.duration)} · ${plural(s.deaths, 'death')}</span></h3>
      ${s.summary ? `<p class="muted">${esc(s.summary)}</p>` : ''}
      ${s.moments.map(m => `<div class="moment ${esc(m.kind)}"><span class="t">${esc(m.at)}</span><span><span class="name">${esc(m.name)}</span>${m.detail ? ` <span class="detail ${m.detail.startsWith('felled') ? 'felled' : ''}">— ${esc(m.detail)}</span>` : ''}</span></div>`).join('')}
      ${s.item_names.length ? `<details><summary>${plural(s.items, 'item')}${s.checkpoints ? ` · ${plural(s.checkpoints, 'checkpoint')}` : ''}</summary><ul>${s.item_names.map(i => `<li>${esc(i)}</li>`).join('')}</ul></details>` : ''}
    </div>`).join('');
}

// --- search -----------------------------------------------------------------------

async function renderSearch() {
  const kinds = ['item', 'area', 'checkpoint', 'boss', 'npc'];
  main.innerHTML = `<h1>Search</h1>
    <form class="search" id="search-form"><input type="text" id="q" placeholder="an item, a place, a boss, an NPC…" autofocus><button class="primary">Search</button></form>
    <div class="kinds">${kinds.map(k => `<label><input type="checkbox" value="${k}" checked>${k}</label>`).join('')}</div>
    <div id="hits"></div>`;
  document.getElementById('search-form').onsubmit = async e => {
    e.preventDefault();
    const q = document.getElementById('q').value.trim();
    if (!q) return;
    const on = [...document.querySelectorAll('.kinds input:checked')].map(i => i.value);
    const r = await call('search', q, on.length === kinds.length ? null : on);
    const box = document.getElementById('hits');
    if (r.error) { box.innerHTML = errorBox(r); return; }
    box.innerHTML = r.hits.length ? `<table><thead><tr><th>kind</th><th>name</th><th>where</th><th>when</th><th></th></tr></thead><tbody>` +
      r.hits.map(h => `<tr><td class="type">${esc(h.kind)}</td><td>${esc(h.name)}</td><td class="muted">${esc(h.location || '')}</td>
        <td class="t"><a href="#session/${esc(h.session)}">${esc(h.date)}</a> +${esc(h.at)}</td><td class="muted">${esc(h.detail || '')}</td></tr>`).join('') + `</tbody></table>`
      : `<p class="muted">Nothing found.</p>`;
  };
}

// --- settings ---------------------------------------------------------------------

async function renderSettings(saved) {
  const s = saved || await call('get_settings');
  if (s.error) { main.innerHTML = errorBox(s); return; }
  const keyField = (id, label, masked, has, env) => `
    <label for="${id}">${label}${env ? ' <span class="badge warn">set in the environment — overrides this</span>' : ''}</label>
    <input type="password" id="${id}" placeholder="${masked ? `stored: ${esc(masked)} — paste a new key to replace it` : 'paste a key'}">
    ${masked ? `<label style="display:inline"><input type="checkbox" id="clear_${id}">remove the stored key</label>` : ''}`;
  main.innerHTML = `<h1>Settings</h1><form id="settings">
    <div class="card">
      <h3>Recaps</h3>
      <p class="hint">One model call per session, at session end. Only the text event log is sent — never a frame. Costs cents per session.</p>
      ${keyField('openai_api_key', 'OpenAI API key', s.openai_api_key, s.has_openai_key, s.env_overrides.includes('OPENAI_API_KEY'))}
      ${keyField('anthropic_api_key', 'Anthropic API key (for claude-* models)', s.anthropic_api_key, s.has_anthropic_key, s.env_overrides.includes('ANTHROPIC_API_KEY'))}
      <label for="model">Model</label>
      <input type="text" id="model" value="${esc(s.model)}" placeholder="${esc(s.default_model)} (default)">
      <p class="hint">gpt-* models use the OpenAI key, claude-* models the Anthropic key.</p>
    </div>
    <div class="card">
      <h3>Capture</h3>
      <label for="monitor">Monitor (1 = primary)</label>
      <input type="number" id="monitor" min="1" value="${s.monitor}">
      <label style="margin-top:14px"><input type="checkbox" id="watch_on_start" ${s.watch_on_start ? 'checked' : ''}>Watch for the game when the app opens</label>
    </div>
    <div class="card">
      <h3>Data</h3>
      <p class="hint">Session logs and recaps: <code>${esc(s.data_dir)}</code> <button type="button" id="open-dir">Open folder</button></p>
      ${s.config_path ? `<p class="hint">Settings file: <code>${esc(s.config_path)}</code></p>` : ''}
    </div>
    <div class="row"><button class="primary">Save</button><span id="saved" class="muted"></span></div>
  </form>`;
  document.getElementById('open-dir').onclick = () => call('open_data_dir');
  document.getElementById('settings').onsubmit = async e => {
    e.preventDefault();
    const v = id => document.getElementById(id);
    const changes = {
      openai_api_key: v('openai_api_key').value,
      anthropic_api_key: v('anthropic_api_key').value,
      clear_openai_api_key: !!(v('clear_openai_api_key') && v('clear_openai_api_key').checked),
      clear_anthropic_api_key: !!(v('clear_anthropic_api_key') && v('clear_anthropic_api_key').checked),
      model: v('model').value.trim(),
      monitor: parseInt(v('monitor').value, 10),
      watch_on_start: v('watch_on_start').checked,
    };
    const r = await call('save_settings', changes);
    if (r.error) { document.getElementById('saved').innerHTML = `<span class="error">${esc(r.error)}</span>`; return; }
    await renderSettings(r);
    document.getElementById('saved').textContent = 'Saved.';
  };
}

// --- routing ------------------------------------------------------------------------

async function route() {
  const hash = location.hash.replace(/^#/, '') || 'home';
  const [page, arg] = hash.split('/', 2);
  document.querySelectorAll('nav a').forEach(a => a.classList.toggle('active', a.dataset.page === page));
  main.innerHTML = '<p class="muted">Loading…</p>';
  switch (page) {
    case 'sessions': return renderSessions();
    case 'session': return renderSession(arg);
    case 'timeline': return renderTimeline();
    case 'search': return renderSearch();
    case 'settings': return renderSettings();
    default: return renderHome();
  }
}

window.addEventListener('hashchange', route);
window.addEventListener('pywebviewready', async () => {
  await poll();
  await route();
  pollTimer = setInterval(poll, 2000);
});
