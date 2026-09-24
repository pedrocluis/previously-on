// Previously On — the page. Hash-routed, no framework; everything comes from
// window.pywebview.api (see app/api.py) as JSON and is rendered as HTML strings.
'use strict';

const main = document.getElementById('main');
const watchBox = document.getElementById('watch');
const gameSelect = document.getElementById('game');
let lastStatus = null;
let viewGame = null;  // the game the screens show (api picks it; see api.py)
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
function errorBox(r) { return `<p class="error">${esc(r.error)}</p>`; }

// --- small pieces ---------------------------------------------------------------

// "Dark Souls II: Scholar of the First Sin" → the subtitle on its own line.
function gameTitle(name, tail = '') {
  const i = String(name || '').indexOf(': ');
  return i < 0 ? esc(name) + tail : `${esc(name.slice(0, i))}<span class="sub">${esc(name.slice(i + 2))}${tail}</span>`;
}
// "Wed 16 Sep 2026, 23:44" → ["Wed 16 Sep", "23:44", "2026"] for a two-line date;
// the year only shows when it is not this one.
function splitDate(d) {
  const m = /^(\S+ \d+ \S+) (\d{4}), (.*)$/.exec(d || '');
  if (!m) return [d || '', '', ''];
  const year = Number(m[2]) === new Date().getFullYear() ? '' : m[2];
  return [m[1], year ? `${m[3]} · ${year}` : m[3], m[2]];
}
function sep() { return '<span class="sep">/</span>'; }
function typeLabel(t) { return String(t || '').replace(/_/g, ' '); }

// --- watcher status (rail) ---------------------------------------------------------

function stateLabel(s) {
  switch (s.state) {
    case 'waiting': return ['Watching', s.message || `Waiting for ${s.watching}…`];
    case 'capturing': return ['Capturing', `${s.game} · ${plural(s.events, 'event')}`];
    case 'summarizing': return ['Writing the recap', 'One model call, text only.'];
    case 'error': return ['Stopped', s.message];
    default: return s.running ? ['Starting', s.message || ''] : ['Not watching', 'Nothing is being captured.'];
  }
}

function renderWatch(s) {
  const [what, detail] = stateLabel(s);
  const btn = s.running
    ? `<button id="watch-btn" data-action="stop">Stop watching</button>`
    : `<button id="watch-btn" data-action="start" class="primary">Watch for ${esc(s.watching && s.watching !== 'a game' ? s.watching : 'games')}</button>`;
  watchBox.innerHTML = `<div class="state"><span class="dot ${esc(s.state)}"></span><span class="what">${esc(what)}</span></div>
    <div class="detail">${esc(detail)}</div>${btn}`;
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
  if (s.view !== viewGame) {
    // A capture started on another game: the screens follow it.
    await renderGames();
    if (location.hash.startsWith('#session/')) location.hash = '#home';  // hashchange routes
    else route();
    return;
  }
  const page = location.hash.replace(/^#/, '') || 'home';
  // A capture ending (recap written or skipped) adds a session to the picker's count.
  const finished = prev && prev.state === 'summarizing' && s.state !== 'summarizing';
  if (finished) renderGames();
  const welcome = document.getElementById('fr-status');
  if (page === 'home' && welcome) {
    // The first capture turns the welcome screen into the resume screen.
    if (s.state === 'capturing') renderHome();
    else welcome.innerHTML = firstRunStatus(s);
    return;
  }
  if (page === 'home') {
    // ...and changes the resume screen.
    const backfilled = prev && prev.summarize.state === 'running' && s.summarize.state !== 'running';
    if (finished || backfilled) renderHome();
    else if (s.state === 'capturing') renderFeed();
  }
}

// --- game picker (rail) ------------------------------------------------------------

async function renderGames() {
  const r = await call('games');
  if (r.error) return;
  viewGame = r.current;
  gameSelect.innerHTML = r.games.map(g =>
    `<option value="${esc(g.id)}" ${g.id === r.current ? 'selected' : ''}>${esc(g.name)}${g.sessions ? ` (${g.sessions})` : ''}</option>`).join('');
}

gameSelect.onchange = async () => {
  const r = await call('select_game', gameSelect.value);
  if (r.error) { alert(r.error); return; }
  viewGame = r.current;
  // A session page belongs to the game it came from.
  if (location.hash.startsWith('#session/')) location.hash = '#sessions';
  else route();
};

// --- home ---------------------------------------------------------------------

// The recap text opens with "Last played …" — the eyebrow already says it.
function recapBody(text) {
  return String(text || '').trim().replace(/^Last played[^\n]*\n\s*\n/, '');
}

// Nothing logged for any game yet: which games, what the window is doing,
// what leaves the machine, where the key goes, how it stays out of the way.
function firstRunStatus(s) {
  if (!s || !s.running) return 'Not watching yet. Press <strong>Watch for games</strong> below the menu, then start one of these:';
  if (s.state === 'waiting') return 'Watching. Start one of these and this window picks it up on its own:';
  return esc(stateLabel(s)[1]);
}

function renderFirstRun(f) {
  const key = f.has_key
    ? '<strong>A key is set.</strong> Each session gets a written recap when it ends.'
    : '<strong>For written recaps, paste an OpenAI key in <a href="#settings">Settings</a>.</strong> Without one, the one-line recap, stats, the timeline and search still work.';
  const auto = f.autostart.supported
    ? `<label class="check"><input type="checkbox" id="fr-autostart" ${f.autostart.enabled ? 'checked' : ''}>Start when I sign in, in the ${f.tray ? 'tray' : 'background'}</label>` : '';
  const stay = f.tray ? 'Closing this window keeps it watching from the tray.' : 'Leave this window open while you play.';
  main.innerHTML = `<p class="eyebrow">Welcome</p>
    <h1><span class="pre">Previously on</span>your playthrough…</h1>
    <hr class="rule">
    <p class="fr-status" id="fr-status">${firstRunStatus(lastStatus)}</p>
    <ul class="supported">${f.games.map(g => `<li>${esc(g)}</li>`).join('')}</ul>
    <div class="first"><ol>
      <li><span><strong>Frames never leave this machine.</strong> The screen is read here and thrown away. Areas, bosses, deaths, pickups and dialogue are logged as plain text on this PC.</span></li>
      <li><span>${key} Only the text log is sent, once per session, to the model you pick. Never a frame.</span></li>
      <li><span><strong>Leave it running.</strong> ${stay}${auto}</span></li>
    </ol></div>
    <div id="feed"></div>`;
  const box = document.getElementById('fr-autostart');
  if (box) box.onchange = async () => {
    const r = await call('save_settings', {start_at_login: box.checked});
    if (r.error) { alert(r.error); box.checked = !box.checked; }
  };
}

async function renderHome() {
  const h = await call('home');
  if (h.error) { main.innerHTML = errorBox(h); return; }
  if (h.first_run) { renderFirstRun(h.first_run); return; }
  if (h.empty) {
    main.innerHTML = `<p class="eyebrow">Nothing logged yet</p>
      <h1><span class="pre">Previously on</span>${gameTitle(h.game, '…')}</h1>
      <hr class="rule">
      <div class="first"><ol>
        <li><span><strong>Start the game.</strong> This window notices it and starts watching the screen.</span></li>
        <li><span><strong>Play.</strong> Areas, bosses, deaths, pickups and dialogue are logged as the game announces them. Frames never leave this machine.</span></li>
        <li><span><strong>Come back whenever.</strong> This page tells you where you left off — stats offline, a written recap with an API key in <a href="#settings">Settings</a>.</span></li>
      </ol></div>
      <div id="feed"></div>`;
    renderFeed();
    return;
  }
  let recap;
  if (h.tier === 'one_line') {
    recap = `<p class="oneline">${esc(h.text)}</p>` +
      (h.full_text ? `<button class="link" id="show-full">Show the full recap anyway</button><div id="full" class="prose lede" hidden>${paras(recapBody(h.full_text))}</div>` : '');
  } else {
    recap = `<div class="prose lede">${paras(recapBody(h.text))}</div>`;
  }
  let notice = '';
  if (h.needs_recap) {
    const st = lastStatus ? lastStatus.summarize : {state: 'idle'};
    const busy = st.state === 'running';
    notice = `<div class="notice"><p>This session has no written recap yet` +
      (st.state === 'failed' && st.session === h.session ? ` — ${esc(st.message)}` : '') + `.</p>
      <div class="row"><button id="summarize" class="primary" ${busy ? 'disabled' : ''}>${busy ? 'Writing the recap…' : 'Write it now'}</button>
      <span class="hint">Needs an API key (<a href="#settings">Settings</a>). Only the text log is sent, never a frame.</span></div></div>`;
  }
  const st = h.state;
  let margin = '';
  if (st && (st.location || st.objective || st.threads.length || st.npcs.length)) {
    margin = `<aside class="margin">` +
      (st.location ? `<section><h4>Where you are</h4><div class="place">${esc(st.location)}</div></section>` : '') +
      (st.objective ? `<section><h4>What you were doing</h4><div class="aim">${esc(st.objective)}</div></section>` : '') +
      (st.threads.length ? `<section><h4>Open threads</h4><ul class="threads">` +
        st.threads.map(t => `<li><strong>${esc(t.who)}</strong> — ${esc(t.what)}${t.status === 'unclear' ? ' <span class="tag">unclear</span>' : ''}</li>`).join('') + `</ul></section>` : '') +
      (st.npcs.length ? `<details><summary>${plural(st.npcs.length, 'NPC')} met</summary><ul>` +
        st.npcs.map(n => `<li><strong>${esc(n.name)}</strong>${n.location ? ` · ${esc(n.location)}` : ''}${n.notes ? ` — ${esc(n.notes)}` : ''}</li>`).join('') + `</ul></details>` : '') +
      (st.items.length ? `<details><summary>Notable items</summary><ul>${st.items.map(i => `<li>${esc(i)}</li>`).join('')}</ul></details>` : '') +
      (h.state_from && h.state_from !== h.session ? `<p class="hint">As of session ${esc(h.state_from)}, the newest one with a recap.</p>` : '') +
      `</aside>`;
  }
  main.innerHTML = `<p class="eyebrow">Last played ${esc(h.gap)}${sep()}${esc(h.date)}${sep()}${esc(h.duration)}${sep()}<a href="#session/${esc(h.session)}">session</a></p>
    <h1><span class="pre">Previously on</span>${gameTitle(h.game, '…')}</h1>
    <hr class="rule">
    <div class="page-grid"><div>${recap}${notice}</div>${margin}</div>
    <div id="feed"></div>`;
  const link = document.getElementById('show-full');
  if (link) link.onclick = () => { document.getElementById('full').hidden = false; link.remove(); };
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
  if (!s || !s.running || s.state === 'waiting' || s.game_id !== viewGame) { box.innerHTML = ''; return; }
  const r = await call('recent_events');
  const events = (r.events || []).slice().reverse();
  box.innerHTML = `<h2>${s.state === 'capturing' ? 'This session, as it happens' : 'Last capture'}</h2>
    <p class="live-meta">${esc(s.message)}${s.state === 'capturing' ? ` · ${s.frames} frames · ${s.ocr_calls} OCR calls` : ''}</p>
    <ul class="ledger feed">${events.map(e => `<li><span class="t">${esc(clock(e.t_rel))}</span><span class="k">${esc(typeLabel(e.type))}</span><span class="x">${esc(e.text)}</span></li>`).join('')
      || '<li><span></span><span></span><span class="x muted">Nothing announced yet.</span></li>'}</ul>`;
}

function clock(t) {
  t = Math.floor(t); const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60;
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

// --- sessions -----------------------------------------------------------------

function outcome(b) {
  return b.defeated
    ? `<span class="outcome felled">Felled <span class="n">· ${b.attempts} ${b.attempts === 1 ? 'try' : 'tries'}</span></span>`
    : `<span class="outcome standing">Still standing <span class="n">· ${plural(b.attempts, 'death')}</span></span>`;
}

async function renderSessions() {
  const r = await call('sessions');
  if (r.error) { main.innerHTML = errorBox(r); return; }
  if (!r.sessions.length) {
    main.innerHTML = `<h1 class="small">Sessions</h1><hr class="rule"><p class="empty-note">Nothing logged yet. Every time you play, a session lands here.</p>`;
    return;
  }
  main.innerHTML = `<p class="eyebrow">${plural(r.sessions.length, 'session')}, newest first</p>
    <h1 class="small">Sessions</h1><hr class="rule">
    <ul class="ledger sessions">` + r.sessions.map(s => {
      const [day, time] = splitDate(s.date);
      return `<li><a href="#session/${esc(s.session)}">
        <span class="when"><span class="day">${esc(day)}</span><span class="time">${esc(time)}</span></span>
        <span><span class="line">${esc(s.one_line)}</span>${s.summary ? `<span class="gist">${esc(s.summary)}</span>` : ''}</span>
        <span>${s.has_recap ? '' : '<span class="tag warn">no recap</span>'}</span>
      </a></li>`;
    }).join('') + `</ul>`;
}

async function renderSession(stamp) {
  const s = await call('session', stamp);
  if (s.error) { main.innerHTML = errorBox(s); return; }
  const types = [...new Set(s.event_list.map(e => e.type))];
  const [day, time, year] = splitDate(s.date);
  const conv = s.conversations.map(c => {
    const who = c.basis === 'named' ? esc(c.speaker) : c.basis === 'inferred' ? `probably ${esc(c.speaker)}` : 'Unknown speaker';
    const where = [c.location, c.at].filter(Boolean).map(esc).join(' · ');
    return `<li><span class="who ${esc(c.basis)}">${who}</span>${where ? `<span class="where">${where}</span>` : ''}<div class="gist">${esc(c.gist)}</div></li>`;
  }).join('');
  main.innerHTML = `<p class="eyebrow"><a href="#sessions">Sessions</a>${sep()}${esc(time)}${sep()}${plural(s.events, 'event')}</p>
    <h1 class="small">${esc(day)} <span class="muted">${esc(year)}</span></h1>
    <p class="totals-sub">${esc(s.one_line)}</p>
    <hr class="rule">
    ${s.summary ? `<div class="prose lede">${paras(s.summary)}</div>`
      : `<div class="notice"><p>No written recap for this session. <a href="#home">Write it from the recap page</a> when it is the latest one, or run <code>previously-on summarize</code>.</p></div>`}
    ${s.full_recap ? `<details class="block"><summary>The short and full recap as written</summary><div class="prose quiet">${paras(s.short_recap)}<hr class="rule">${paras(s.full_recap)}</div></details>` : ''}
    ${s.dropped.length ? `<details class="block"><summary>${plural(s.dropped.length, 'detail')} left out by verification</summary><ul>${s.dropped.map(d => `<li>${esc(d)}</li>`).join('')}</ul></details>` : ''}
    ${s.bosses.length ? `<h2>Fights</h2><ul class="ledger fights">${s.bosses.map(b => `<li><span class="name">${esc(b.name)}${b.phases.length ? `<span class="phases">also ${b.phases.map(esc).join(', ')}</span>` : ''}</span>${outcome(b)}</li>`).join('')}</ul>` : ''}
    ${s.areas.length ? `<h2>Places</h2><p class="places">${s.areas.map(a => `<span>${esc(a)}</span>`).join('')}</p>` : ''}
    ${conv ? `<h2>Conversations</h2><ul class="ledger talk">${conv}</ul>` : ''}
    <h2>Every event</h2>
    <div class="filters" id="type-filter">${types.map(t => `<label><input type="checkbox" value="${esc(t)}" checked><span>${esc(typeLabel(t))}</span></label>`).join('')}</div>
    <table><thead><tr><th>#</th><th>At</th><th>Kind</th><th>What the screen said</th></tr></thead><tbody id="events"></tbody></table>
    <div class="notice"><p>Something here the screen never showed, or something it showed that is missing? Export this session and attach it to an issue: the event log and the recap, as text. No frame, no key.</p>
      <div class="row"><button id="export">Export for a bug report…</button><span class="hint" id="export-note"></span></div></div>`;
  const draw = () => {
    const on = new Set([...document.querySelectorAll('#type-filter input:checked')].map(i => i.value));
    document.getElementById('events').innerHTML = s.event_list.filter(e => on.has(e.type)).map(e =>
      `<tr><td class="t">${e.index}</td><td class="t">${esc(e.at)}</td><td class="k">${esc(typeLabel(e.type))}</td><td class="x">${esc(e.text)}</td></tr>`).join('');
  };
  document.getElementById('type-filter').onchange = draw;
  draw();
  document.getElementById('export').onclick = () => exportSession(stamp);
}

async function exportSession(stamp) {
  const note = document.getElementById('export-note');
  const r = await call('export_session', stamp);
  if (r.error) { note.innerHTML = `<span class="error">${esc(r.error)}</span>`; return; }
  if (!r.saved) return;
  note.innerHTML = `Saved to ${esc(r.saved)}. <a href="#" id="export-issue">Open a new issue</a>, say which event is wrong (its # above) and what the screen showed, and attach the zip.`;
  document.getElementById('export-issue').onclick = e => { e.preventDefault(); call('open_url', r.issue_url); };
}

// --- timeline -------------------------------------------------------------------

async function renderTimeline() {
  const r = await call('timeline');
  if (r.error) { main.innerHTML = errorBox(r); return; }
  if (!r.sessions.length) {
    main.innerHTML = `<h1 class="small">Timeline</h1><hr class="rule"><p class="empty-note">The playthrough, session by session, once there is one.</p>`;
    return;
  }
  const t = r.totals;
  main.innerHTML = `<p class="eyebrow">The playthrough so far</p>
    <p class="totals">${esc(t.line)}</p>
    <p class="totals-sub">${plural(t.sessions, 'session')} · ${plural(t.bosses_felled, 'boss')} felled</p>
    <div class="row share"><button id="share">Share card</button></div>
    <div id="card"></div>
    <hr class="rule">
    <div class="chron">` +
    r.sessions.map(s => {
      const [day, time] = splitDate(s.date);
      return `<div class="entry">
        <div class="when"><a href="#session/${esc(s.session)}">${esc(day)}</a><span>${esc(s.duration)} · ${plural(s.deaths, 'death')}</span><span>${esc(time)}</span></div>
        <div>
          ${s.summary ? `<p class="gist">${esc(s.summary)}</p>` : ''}
          <ul class="moments">${s.moments.map(m => `<li class="${esc(m.kind)}"><span class="t">${esc(m.at)}</span><span><span class="name">${esc(m.name)}</span>${m.detail ? `<span class="detail ${m.detail.startsWith('felled') ? 'felled' : ''}">${esc(m.detail)}</span>` : ''}</span></li>`).join('')}</ul>
          ${s.item_names.length ? `<details><summary>${plural(s.items, 'item')}${s.checkpoints ? ` · ${plural(s.checkpoints, 'checkpoint')}` : ''}</summary><ul>${s.item_names.map(i => `<li>${esc(i)}</li>`).join('')}</ul></details>` : ''}
        </div>
      </div>`;
    }).join('') + `</div>`;
  document.getElementById('share').onclick = showCard;
}

// The playthrough as one image to post: drawn by the app (card.py), shown
// here, saved through the window's save dialog or copied to the clipboard.
async function showCard() {
  const box = document.getElementById('card');
  const btn = document.getElementById('share');
  if (!box.hidden && box.innerHTML) { box.hidden = true; btn.textContent = 'Share card'; return; }
  btn.disabled = true;
  const r = await call('card');
  btn.disabled = false;
  if (r.error) { box.hidden = false; box.innerHTML = errorBox(r); return; }
  const canCopy = !!(window.ClipboardItem && navigator.clipboard && navigator.clipboard.write);
  box.hidden = false;
  btn.textContent = 'Hide card';
  box.innerHTML = `<figure class="card"><img src="${r.png}" alt="${esc(r.line)}" width="1600" height="900">
    <figcaption class="row"><button class="primary" id="card-save">Save image…</button>
    ${canCopy ? '<button id="card-copy">Copy image</button>' : ''}
    <span class="hint" id="card-note">Made from the session logs on this PC. Nothing is uploaded; post it wherever you like.</span></figcaption></figure>`;
  const note = document.getElementById('card-note');
  document.getElementById('card-save').onclick = async () => {
    const s = await call('save_card');
    if (s.error) note.innerHTML = `<span class="error">${esc(s.error)}</span>`;
    else if (s.saved) note.textContent = `Saved to ${s.saved}`;
  };
  const copy = document.getElementById('card-copy');
  if (copy) copy.onclick = async () => {
    try {
      const blob = await (await fetch(r.png)).blob();
      await navigator.clipboard.write([new ClipboardItem({'image/png': blob})]);
      note.textContent = 'Copied. Paste it into a post or a chat.';
    } catch (e) {
      note.innerHTML = `<span class="error">Could not copy here (${esc(e && e.message || e)}). Save it instead.</span>`;
    }
  };
}

// --- search -----------------------------------------------------------------------

async function renderSearch() {
  const kinds = ['item', 'area', 'checkpoint', 'boss', 'npc'];
  const names = {item: 'items', area: 'places', checkpoint: 'checkpoints', boss: 'bosses', npc: 'people'};
  main.innerHTML = `<p class="eyebrow">Where did I get that · who said that · where was that</p>
    <form class="search" id="search-form"><input type="text" id="q" placeholder="an item, a place, a boss…" autofocus><button class="primary">Search</button></form>
    <div class="filters kinds">${kinds.map(k => `<label><input type="checkbox" value="${k}" checked><span>${names[k]}</span></label>`).join('')}</div>
    <div id="hits"></div>`;
  document.getElementById('search-form').onsubmit = async e => {
    e.preventDefault();
    const q = document.getElementById('q').value.trim();
    if (!q) return;
    const on = [...document.querySelectorAll('.kinds input:checked')].map(i => i.value);
    const r = await call('search', q, on.length === kinds.length ? null : on);
    const box = document.getElementById('hits');
    if (r.error) { box.innerHTML = errorBox(r); return; }
    box.innerHTML = r.hits.length ? `<h2>${plural(r.hits.length, 'match')}</h2><table class="hits"><thead><tr><th>Kind</th><th>Name</th><th>Near</th><th>When</th><th></th></tr></thead><tbody>` +
      r.hits.map(h => `<tr><td class="k">${esc(h.kind)}</td><td class="x">${esc(h.name)}</td><td class="muted">${esc(h.location || '')}</td>
        <td class="t"><a href="#session/${esc(h.session)}">${esc(h.date)}</a> +${esc(h.at)}</td><td class="muted">${esc(h.detail || '')}</td></tr>`).join('') + `</tbody></table>`
      : `<p class="empty-note">Nothing in the log matches “${esc(q)}”.</p>`;
  };
}

// --- settings ---------------------------------------------------------------------

async function renderSettings(saved) {
  const s = saved || await call('get_settings');
  if (s.error) { main.innerHTML = errorBox(s); return; }
  const keyField = (id, label, masked, has, env) => `<div class="field">
    <label for="${id}">${label}${env ? ' <span class="tag warn">set in the environment — overrides this</span>' : ''}</label>
    <input type="password" id="${id}" placeholder="${masked ? `stored: ${esc(masked)} — paste a new key to replace it` : 'paste a key'}">
    ${masked ? `<label class="check"><input type="checkbox" id="clear_${id}">Remove the stored key</label>` : ''}</div>`;
  main.innerHTML = `<h1 class="small">Settings</h1><hr class="rule"><form id="settings">
    <div class="set">
      <div class="about"><h3>Recaps</h3>
        <p class="hint">One model call per session, when it ends. Only the text event log is sent, never a frame. It costs cents per session. Stats, the timeline and search work without a key.</p></div>
      <div>
        ${keyField('openai_api_key', 'OpenAI API key', s.openai_api_key, s.has_openai_key, s.env_overrides.includes('OPENAI_API_KEY'))}
        ${keyField('anthropic_api_key', 'Anthropic API key, for claude-* models', s.anthropic_api_key, s.has_anthropic_key, s.env_overrides.includes('ANTHROPIC_API_KEY'))}
        <div class="field"><label for="model">Model</label>
          <input type="text" id="model" value="${esc(s.model)}" placeholder="${esc(s.default_model)} (default)">
          <p class="hint">gpt-* models use the OpenAI key, claude-* models the Anthropic key.</p></div>
      </div>
    </div>
    <div class="set">
      <div class="about"><h3>Capture</h3><p class="hint">Which screen the game is on, and when to watch.</p></div>
      <div>
        <div class="field"><label for="monitor">Monitor (1 is the primary)</label>
          <input type="number" id="monitor" min="1" value="${s.monitor}"></div>
        <label class="check"><input type="checkbox" id="watch_on_start" ${s.watch_on_start ? 'checked' : ''}>Watch for a game when the app opens</label>
        ${s.start_at_login.supported ? `<label class="check"><input type="checkbox" id="start_at_login" ${s.start_at_login.enabled ? 'checked' : ''}>Start when I sign in, with the window hidden${s.tray ? ' in the tray' : ''}</label>` : ''}
        <p class="hint" style="margin-top:12px">${s.tray ? 'Closing the window keeps capture running from the tray icon; quit from its menu.' : 'Closing the window stops capture.'}</p>
      </div>
    </div>
    <div class="set">
      <div class="about"><h3>Data</h3><p class="hint">Everything stays on this machine as plain text files.</p></div>
      <div>
        <div class="field"><label>Session logs and recaps</label><p class="hint"><code>${esc(s.data_dir)}</code></p>
          <div class="row" style="margin-top:10px"><button type="button" id="open-dir">Open folder</button></div></div>
        ${s.config_path ? `<div class="field"><label>Settings file</label><p class="hint"><code>${esc(s.config_path)}</code></p></div>` : ''}
      </div>
    </div>
    <div class="save-bar"><button class="primary">Save</button><span id="saved" class="muted"></span></div>
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
    if (v('start_at_login')) changes.start_at_login = v('start_at_login').checked;
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
  main.innerHTML = '<p class="loading">Loading…</p>';
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
  await renderGames();
  await poll();
  await route();
  pollTimer = setInterval(poll, 2000);
});
