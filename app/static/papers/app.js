/* SearchBridge frontend — no build step, no dependencies. */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => Number(n).toLocaleString("en-IN");

const state = {
  coll: localStorage.getItem("sb.coll") || "",
  collections: [],
  modes: [],
  prefs: Object.assign({ mode: "bridge", k: 10, spell: true, diversify: false, mmr: 0.7, pagerank: 0, fair: "" },
    JSON.parse(localStorage.getItem("sb.prefs") || "{}")),
  liked: new Set(),
  lastResp: null,
};
const savePrefs = () => localStorage.setItem("sb.prefs", JSON.stringify(state.prefs));

/* ---------------------------------------------------------------- api */
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let body = null;
  try { body = await res.json(); } catch { /* empty */ }
  if (!res.ok) {
    const err = new Error((body && body.detail) || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return body;
}
const qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== "" && v !== null && v !== undefined)).toString();
const collParam = () => ({ c: state.coll });

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}

/* ---------------------------------------------------------------- theme */
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem("sb.theme", t);
}
applyTheme(localStorage.getItem("sb.theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
$("#theme").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));

/* ---------------------------------------------------------------- collections */
async function loadCollections() {
  const data = await api("/api/collections");
  state.collections = data.collections;
  state.modes = data.modes;
  if (!state.coll || !data.collections.find((c) => c.id === state.coll)) state.coll = data.default;
  const sel = $("#collection");
  sel.innerHTML = data.collections.map((c) => `<option value="${c.id}">${esc(c.name)}${c.status === "ready" ? "" : c.status === "empty" ? " (empty)" : c.status === "missing" ? " (not downloaded)" : " (indexing…)"}</option>`).join("");
  sel.value = state.coll;
  const cur = currentColl();
  const strip = $("#status-strip");
  const busy = data.collections.filter((c) => c.status === "building" || c.status === "idle");
  if (cur && !["ready", "empty", "missing"].includes(cur.status)) {
    strip.hidden = false;
    strip.textContent = cur.status === "error" ? `Indexing ${cur.name} failed: ${cur.error}` : `Indexing ${cur.name}… the first start takes about 20 seconds; later starts load from cache.`;
  } else strip.hidden = true;
  if (busy.length) setTimeout(async () => { const before = cur && cur.status; await loadCollections(); if (before !== "ready" && currentColl().status === "ready") route(); }, 2500);
  return data;
}
const currentColl = () => state.collections.find((c) => c.id === state.coll);
$("#collection").addEventListener("change", (e) => {
  state.coll = e.target.value;
  localStorage.setItem("sb.coll", state.coll);
  state.liked.clear();
  loadCollections().then(() => { location.hash = location.hash.startsWith("#/?") || location.hash === "#/" || !location.hash ? "#/" : location.hash; route(); });
});

/* ---------------------------------------------------------------- router */
function parseHash() {
  const h = location.hash.slice(1) || "/";
  const [path, query] = h.split("?");
  return { path: path || "/", params: Object.fromEntries(new URLSearchParams(query || "")) };
}
const routes = { "/": pageSearch, "/compare": pageCompare, "/library": pageLibrary, "/graph": pageGraph, "/insights": pageInsights, "/evaluation": pageEvaluation, "/trust": pageTrust };
function route() {
  const { path, params } = parseHash();
  const name = { "/": "search" }[path] || path.slice(1);
  $$(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === name));
  closeDrawer();
  (routes[path] || pageSearch)(params);
}
window.addEventListener("hashchange", route);

function needReady(main) {
  const c = currentColl();
  if (!c) return false;
  if (c.status === "ready") return true;
  if (c.status === "missing") {
    main.innerHTML = `<div class="empty"><h2>${esc(c.name)} is not downloaded yet</h2><p class="muted">Stop the server, then run <code>python scripts/fetch_openalex.py</code> (about 3 minutes, needs internet) and start it again. <code>./start.sh</code> does this for you.</p><p>Meanwhile you can switch to another collection in the top-right menu.</p></div>`;
  } else if (c.status === "empty") {
    main.innerHTML = `<div class="empty"><h2>This library is empty</h2><p class="muted">Add PDFs, text, Markdown or HTML files and SearchBridge will index them.</p><a class="btn" href="#/library">Add documents</a></div>`;
  } else if (c.status === "error") {
    main.innerHTML = `<div class="empty"><h2>Indexing failed</h2><p class="error">${esc(c.error)}</p></div>`;
  } else {
    main.innerHTML = `<div class="empty"><h2>Indexing ${esc(c.name)}</h2><p class="loading">Building the inverted index, embeddings, topics and concept map</p></div>`;
  }
  return false;
}

/* ---------------------------------------------------------------- search box with autocomplete */
function searchBox({ q = "", compact = false, onSubmit }) {
  const wrap = document.createElement("div");
  wrap.className = "searchbox" + (compact ? " compact" : "");
  wrap.innerHTML = `
    <form role="search">
      <label class="sr" for="q">Search</label>
      <input id="q" type="search" autocomplete="off" spellcheck="false" placeholder="Search by topic, phrase or question" value="${esc(q)}"
        role="combobox" aria-expanded="false" aria-controls="sugg" aria-autocomplete="list">
      <label class="sr" for="mode">Ranking model</label>
      <select class="mode" id="mode" title="Ranking model">${state.modes.map((m) => `<option value="${m.id}" title="${esc(m.description)}" ${m.id === state.prefs.mode ? "selected" : ""}>${esc(m.name)}${m.id === "bridge" ? " (ours)" : ""}</option>`).join("")}</select>
      <button class="go" type="submit">Search</button>
    </form>
    <ul class="suggest" id="sugg" role="listbox" hidden></ul>`;
  const input = $("input", wrap), list = $(".suggest", wrap), form = $("form", wrap);
  let items = [], sel = -1, timer;
  const close = () => { list.hidden = true; input.setAttribute("aria-expanded", "false"); sel = -1; };
  const show = () => {
    if (!items.length) return close();
    const v = input.value.toLowerCase();
    list.innerHTML = items.map((s, i) => `<li role="option" id="sg${i}" aria-selected="${i === sel}">${s.startsWith(v) ? `${esc(s.slice(0, v.length))}<b>${esc(s.slice(v.length))}</b>` : esc(s)}</li>`).join("");
    list.hidden = false; input.setAttribute("aria-expanded", "true");
    $$("li", list).forEach((li, i) => li.addEventListener("mousedown", (e) => { e.preventDefault(); input.value = items[i]; close(); form.requestSubmit(); }));
  };
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const v = input.value.trim();
    if (v.length < 2 || /[":()*]|\b(AND|OR|NOT)\b/.test(v)) { items = []; return close(); }
    timer = setTimeout(async () => { try { items = (await api(`/api/suggest?${qs({ c: state.coll, q: v })}`)).suggestions; sel = -1; show(); } catch { close(); } }, 140);
  });
  input.addEventListener("keydown", (e) => {
    if (list.hidden) return;
    if (e.key === "ArrowDown") { sel = Math.min(sel + 1, items.length - 1); show(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(sel - 1, -1); show(); e.preventDefault(); }
    else if (e.key === "Enter" && sel >= 0) { input.value = items[sel]; close(); }
    else if (e.key === "Escape") close();
  });
  input.addEventListener("blur", () => setTimeout(close, 120));
  $(".mode", wrap).addEventListener("change", (e) => { state.prefs.mode = e.target.value; savePrefs(); if (input.value.trim()) form.requestSubmit(); });
  form.addEventListener("submit", (e) => { e.preventDefault(); close(); onSubmit(input.value.trim()); });
  return wrap;
}

function optionsRow(onChange) {
  const p = state.prefs;
  const row = document.createElement("div");
  row.className = "search-options";
  const coll = currentColl();
  const fairOpt = state.coll === "cranfield" ? "venue" : "category";
  row.innerHTML = `
    <label><input type="checkbox" data-k="spell" ${p.spell ? "checked" : ""}> Fix spelling</label>
    <label title="Maximal marginal relevance: trade a little relevance for less redundant results"><input type="checkbox" data-k="diversify" ${p.diversify ? "checked" : ""}> Diversify</label>
    <label ${p.diversify ? "" : "hidden"} data-show="diversify">relevance <input type="range" min="0.3" max="1" step="0.05" data-k="mmr" value="${p.mmr}"> variety</label>
    <label title="Blend in citation / link authority (PageRank)">Authority boost <input type="range" min="0" max="0.5" step="0.05" data-k="pagerank" value="${p.pagerank}"></label>
    <label title="Re-rank so each ${fairOpt} gets exposure in proportion to its relevance"><input type="checkbox" data-k="fair" ${p.fair ? "checked" : ""}> Fair exposure by ${fairOpt}</label>
    <label>Show <select data-k="k">${[10, 20, 30].map((n) => `<option ${n == p.k ? "selected" : ""}>${n}</option>`).join("")}</select></label>`;
  row.addEventListener("change", (e) => {
    const k = e.target.dataset.k;
    if (!k) return;
    if (k === "fair") p.fair = e.target.checked ? fairOpt : "";
    else if (e.target.type === "checkbox") p[k] = e.target.checked;
    else p[k] = Number(e.target.value);
    $$("[data-show]", row).forEach((el) => (el.hidden = !p[el.dataset.show]));
    savePrefs();
    onChange && onChange();
  });
  return row;
}

/* ---------------------------------------------------------------- SEARCH page */
function go(params) {
  const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => v));
  location.hash = "#/?" + qs(clean);
}

async function pageSearch(params) {
  const main = $("#main");
  if (!needReady(main)) return;
  const coll = currentColl();
  if (!params.q && !params.category && !params.topic && !params.tag && !params.type) return renderHome(main, coll);

  main.innerHTML = `<div class="results-page"><div class="results-head"><div></div></div><div class="results-grid"><nav class="facets" aria-label="Filters"></nav><section class="results" aria-live="polite"><p class="loading">Searching</p></section><aside class="context"></aside></div></div>`;
  const head = $(".results-head", main);
  const sb = searchBox({ q: params.q || "", compact: true, onSubmit: (q) => go({ q }) });
  sb.appendChild(optionsRow(() => route()));
  head.appendChild(sb);

  const p = state.prefs;
  const req = { c: state.coll, q: params.q || "", mode: p.mode, k: p.k, spell: p.spell, diversify: p.diversify, mmr: p.mmr,
    pagerank: p.pagerank, fair: p.fair, category: params.category, type: params.type, topic: params.topic, tag: params.tag };
  let resp;
  try { resp = await api(`/api/search?${qs(req)}`); }
  catch (e) { $(".results", main).innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
  state.lastResp = resp;
  state.liked.clear();
  renderFacets($(".facets", main), resp, params);
  renderResults($(".results", main), resp, params, req);
  renderContext($(".context", main), resp, params);
  if (params.doc) openDoc(params.doc, params.q);
}

function renderHome(main, coll) {
  const s = coll.stats || {};
  main.innerHTML = `
    <div class="home">
      <div>
        <h1>Find the paper you need, even when it uses different words.</h1>
        <p class="lede">${esc(coll.description)}. Every result shows why it matched: exact words, shared meaning, or both.</p>
        <div id="home-search"></div>
      </div>
      <aside>
        <h3>Try a search</h3>
        <ul class="examples">${(coll.examples || []).map((x) => `<li><button data-q="${esc(x)}">${esc(x)}</button></li>`).join("") || `<li class="muted">Upload documents on the <a href="#/library">library page</a>, then search them here.</li>`}</ul>
        <div class="legend">
          <div><span style="background:var(--lex)"></span>matched on exact words</div>
          <div><span style="background:var(--sem)"></span>matched on meaning</div>
          <div><span style="background:var(--hl)"></span>your search terms</div>
        </div>
        <p class="small muted" style="margin-top:22px">${fmt(s.documents || 0)} documents, ${fmt(s.vocabulary || 0)} distinct terms, ${s.topics || 0} automatic topics.</p>
      </aside>
    </div>`;
  const box = searchBox({ onSubmit: (q) => q && go({ q }) });
  box.appendChild(optionsRow());
  $("#home-search").appendChild(box);
  $("#q").focus();
  $$(".examples button", main).forEach((b) => b.addEventListener("click", () => go({ q: b.dataset.q })));
}

const FACET_NAMES = { topic: "Topic", category: "Category", type: "Document type", tag: "Keyphrases" };
function renderFacets(el, resp, params) {
  const active = ["topic", "category", "type", "tag"].filter((f) => params[f]);
  let html = active.length ? `<button class="clear-filters" data-clear>Clear filters</button>` : "";
  for (const f of ["topic", "category", "type", "tag"]) {
    const vals = resp.facets[f];
    if (!vals || !vals.length) continue;
    if (f === "tag") {
      html += `<div class="facet"><h4>${FACET_NAMES[f]}</h4><div class="tagcloud">${vals.map(([v, n]) => `<button class="${params.tag === v ? "on" : ""}" data-f="tag" data-v="${esc(v)}" title="${n} results">${esc(v)}</button>`).join("")}</div></div>`;
    } else {
      html += `<div class="facet"><h4>${FACET_NAMES[f]}</h4>${vals.map(([v, n]) => `<button class="${params[f] === v ? "on" : ""}" data-f="${f}" data-v="${esc(v)}"><span>${esc(v)}</span><span class="n">${n}</span></button>`).join("")}</div>`;
    }
  }
  if (html) html += `<p class="small muted">Counts cover the top 300 matches.</p>`;
  el.innerHTML = html;
  el.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    const next = { ...params };
    if (b.dataset.clear !== undefined) ["topic", "category", "type", "tag"].forEach((f) => delete next[f]);
    else next[b.dataset.f] = next[b.dataset.f] === b.dataset.v ? "" : b.dataset.v;
    go(next);
  });
}

function bridgeMeter(sig) {
  if (!sig || sig.lexical == null || !sig.terms) return "";
  const l = Math.round(sig.lexical * 100), s = Math.round(sig.semantic * 100);
  const label = sig.matched === sig.terms ? (s >= 25 ? "all your words, close in meaning" : "all your words")
    : sig.matched === 0 ? "matched on meaning only" : `${sig.matched} of ${sig.terms} words, plus meaning`;
  return `<span class="bridge" title="Contains ${sig.matched} of your ${sig.terms} search terms; blue = word evidence, green = meaning similarity"><span class="bar"><i class="l" style="width:${l}%"></i><i class="s" style="width:${s}%"></i></span>${label}</span>`;
}
const cites = (n) => (n && +n > 0 ? `cited ${fmt(n)} times` : "");
const shortAuthors = (a) => { if (!a) return ""; const p = a.split(", "); return p.length > 3 ? `${p.slice(0, 3).join(", ")} et al.` : a.replace(/ et al\.$/, " et al."); };

function resultCard(h, q) {
  const m = h.meta || {};
  const cred = h.flags && h.flags.length ? `<span class="flag" title="${esc((h.credibility_reasons || []).map((r) => r[0] + " " + r[1]).join(", "))}">Low credibility signals</span>` : "";
  const meta = m.source === "OpenAlex"
    ? [esc(shortAuthors(m.author)), [m.venue, m.year].filter(Boolean).map(esc).join(", "), cites(m.citations), esc(m.category)].filter(Boolean).map((x) => `<span>${x}</span>`).join("")
    : [m.author ? esc(shortAuthors(m.author)) : "", m.category && m.category !== "My documents" ? esc(m.category) : "", h.topic ? esc(h.topic) : "", m.type ? esc(m.type) : "",
      h.words ? `${fmt(h.words)} terms` : ""].filter(Boolean).map((x) => `<span>${x}</span>`).join("");
  return `
    <article class="result" data-id="${esc(h.doc_id)}">
      <h3><span class="rank">${h.rank}</span><button class="title" data-open="${esc(h.doc_id)}">${esc(h.title)}</button></h3>
      <div class="meta">${meta}${cred}</div>
      <div class="snippet">${h.snippet_html}</div>
      ${h.tags && h.tags.length ? `<div class="tags">${h.tags.map((t) => `<button class="chip" data-tag="${esc(t)}">${esc(t)}</button>`).join("")}</div>` : ""}
      <div class="result-foot">
        ${bridgeMeter(h.signal)}
        <button class="linkbtn" data-explain aria-expanded="false">Why this result</button>
        <button class="linkbtn" data-related aria-expanded="false">Similar papers</button>
        <button class="linkbtn" data-like aria-pressed="false">Mark relevant</button>
        ${m.url && /^https?:/.test(m.url) ? `<a class="linkbtn" href="${esc(m.url)}" target="_blank" rel="noopener">Open paper</a>` : ""}
      </div>
      <div class="slot"></div>
    </article>`;
}

function explainBox(h) {
  const rows = (h.explanation || []).filter((r) => r[3] > 0);
  const max = Math.max(...rows.map((r) => r[3]), 1e-9);
  const sig = h.signal || {};
  return `<div class="explain">
    ${rows.length ? `<p class="small muted">Term contributions to the BM25 score (term frequency in this document, rarity across the collection):</p>
    <table>${rows.map(([t, tf, idf, c]) => `<tr><td style="width:130px">${esc(t)}</td><td><div class="contrib" style="width:${(c / max) * 100}%"></div></td><td class="num">tf ${tf}</td><td class="num">idf ${idf.toFixed(2)}</td><td class="num">+${c.toFixed(2)}</td></tr>`).join("")}</table>`
      : `<p class="small muted">None of the query words appear in this document, so it was found through semantic similarity.</p>`}
    <p class="small muted" style="margin:10px 0 0">Evidence mix: ${Math.round((sig.lexical || 0) * 100)}% exact-word, ${Math.round((sig.semantic || 0) * 100)}% semantic. Credibility ${h.credibility}${(h.credibility_reasons || []).length ? ` (${(h.credibility_reasons || []).map((r) => esc(r[0])).join(", ")})` : ""}.</p>
  </div>`;
}

function renderResults(el, resp, params, req) {
  const s = resp;
  let html = `<div class="summary"><span><strong>${fmt(s.total_matches)}</strong> matching documents</span><span>${s.took_ms} ms</span><span>${esc(s.mode_name)}${s.alpha != null ? `, word weight ${Number(s.alpha).toFixed(2)}` : ""}</span></div>`;
  if (s.corrected_query) html += `<p class="didyoumean">Showing results for <em>${esc(s.corrected_query)}</em>. <a href="#/?${qs({ q: params.q + " " })}" data-nospell>Search for ${esc(params.q)} instead</a></p>`;
  const af = ["topic", "category", "type", "tag"].filter((f) => params[f]);
  if (af.length) html += `<div class="active-filters">${af.map((f) => `<button class="chip lex" data-unfilter="${f}">${esc(FACET_NAMES[f])}: ${esc(params[f])} <span class="x" aria-hidden="true">×</span><span class="sr">remove</span></button>`).join("")}</div>`;
  if (!s.hits.length) {
    html += `<div class="empty" style="margin:30px 0"><h2>No documents match</h2><p class="muted">Try fewer words, remove a filter, or switch the ranking model to Semantic to match on meaning instead of exact words.</p></div>`;
    el.innerHTML = html;
  } else {
    html += `<div class="list">${s.hits.map((h) => resultCard(h, params.q)).join("")}</div>`;
    if (s.total_matches > s.hits.length) html += `<button class="more">Show more results</button>`;
    html += `<div class="feedback-bar" hidden><span></span><button data-refine>Find more like these</button></div><div class="refined-slot"></div>`;
    el.innerHTML = html;
  }
  if (req.spell === false) {/* noop */}
  const hitsById = Object.fromEntries(s.hits.map((h) => [h.doc_id, h]));
  let offset = s.hits.length;

  el.addEventListener("click", async (e) => {
    const t = e.target.closest("button, a");
    if (!t) return;
    if (t.dataset.nospell !== undefined) { e.preventDefault(); state.prefs.spell = false; savePrefs(); go({ ...params, q: params.q }); route(); return; }
    if (t.dataset.unfilter) { const n = { ...params }; delete n[t.dataset.unfilter]; return go(n); }
    if (t.dataset.open) return openDoc(t.dataset.open, params.q);
    if (t.dataset.tag) return go({ ...params, tag: t.dataset.tag });
    const card = t.closest(".result");
    const h = card && hitsById[card.dataset.id];
    if (t.dataset.explain !== undefined) {
      const open = t.getAttribute("aria-expanded") === "true";
      $$(".linkbtn[aria-expanded]", card).forEach((b) => b.setAttribute("aria-expanded", "false"));
      $(".slot", card).innerHTML = open ? "" : explainBox(h);
      t.setAttribute("aria-expanded", String(!open));
    }
    if (t.dataset.related !== undefined) {
      const open = t.getAttribute("aria-expanded") === "true";
      $$(".linkbtn[aria-expanded]", card).forEach((b) => b.setAttribute("aria-expanded", "false"));
      if (open) { $(".slot", card).innerHTML = ""; return; }
      t.setAttribute("aria-expanded", "true");
      $(".slot", card).innerHTML = `<div class="related-box"><p class="loading small">Finding similar papers</p></div>`;
      try {
        const rel = await api(`/api/related?${qs({ c: state.coll, id: h.doc_id, k: 5 })}`);
        $(".slot", card).innerHTML = `<div class="related-box"><ul>${rel.map((r) => `<li><a href="#" data-open="${esc(r.id)}">${esc(r.title)}</a><span class="why" title="semantic ${r.components.semantic}, lexical ${r.components.lexical}, shared concepts ${r.components.entities}, citation/graph link ${r.components.graph}">${relWhy(r.components)}</span></li>`).join("")}</ul></div>`;
        $$("[data-open]", $(".slot", card)).forEach((a) => a.addEventListener("click", (ev) => { ev.preventDefault(); ev.stopPropagation(); openDoc(a.dataset.open, params.q); }));
      } catch (err) { $(".slot", card).innerHTML = `<p class="error">${esc(err.message)}</p>`; }
    }
    if (t.dataset.like !== undefined) {
      const on = !state.liked.has(h.doc_id);
      on ? state.liked.add(h.doc_id) : state.liked.delete(h.doc_id);
      t.classList.toggle("on", on); t.setAttribute("aria-pressed", String(on)); t.textContent = on ? "Marked relevant" : "Mark relevant";
      const bar = $(".feedback-bar", el);
      bar.hidden = state.liked.size === 0;
      $("span", bar).textContent = `${state.liked.size} marked relevant. SearchBridge can move your query toward ${state.liked.size === 1 ? "it" : "them"} (Rocchio feedback).`;
    }
    if (t.dataset.refine !== undefined) {
      t.disabled = true;
      try {
        const hits = await api("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ c: state.coll, q: s.corrected_query || params.q || "", relevant: [...state.liked], k: 10 }) });
        $(".refined-slot", el).innerHTML = `<div class="refined"><h3>More like the ones you marked</h3><p class="small muted">The query was re-weighted toward the documents you marked relevant.</p></div>${hits.filter((x) => !state.liked.has(x.doc_id)).map((x) => resultCard(x, params.q)).join("")}`;
        hits.forEach((x) => (hitsById[x.doc_id] = hitsById[x.doc_id] || x));
        $(".refined-slot", el).scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (err) { toast(err.message); }
      t.disabled = false;
    }
    if (t.classList.contains("more")) {
      t.disabled = true; t.textContent = "Loading";
      try {
        const more = await api(`/api/search?${qs({ ...req, offset, clusters: false })}`);
        more.hits.forEach((x) => (hitsById[x.doc_id] = x));
        $(".list", el).insertAdjacentHTML("beforeend", more.hits.map((x) => resultCard(x, params.q)).join(""));
        offset += more.hits.length;
        if (offset >= s.total_matches || !more.hits.length) t.remove(); else { t.disabled = false; t.textContent = "Show more results"; }
      } catch (err) { toast(err.message); }
    }
  });
}
function relWhy(c) {
  const parts = [];
  if (c.semantic > 0.5) parts.push("similar meaning");
  if (c.lexical > 0.4) parts.push("shared terms");
  if (c.entities > 0.15) parts.push("shared concepts");
  if (c.graph > 0) parts.push("linked");
  return parts.join(", ") || "related";
}

function renderContext(el, resp, params) {
  let html = "";
  if (resp.related_concepts && resp.related_concepts.length) {
    html += `<section><h4>Related concepts</h4><div class="chips">${resp.related_concepts.slice(0, 8).map(([n]) => `<button class="chip sem" data-q="${esc(n)}">${esc(n)}</button>`).join("")}</div><p class="note">From the concept map built from keyphrases and co-occurrence.</p></section>`;
  }
  if (resp.expansion_terms && resp.expansion_terms.length) {
    html += `<section><h4>Query was expanded with</h4><div class="chips">${resp.expansion_terms.slice(0, 8).map(([t]) => `<span class="chip lex">${esc(t)}</span>`).join("")}</div><p class="note">Terms from the top lexical and semantic results (Bridge-PRF feedback).</p></section>`;
  }
  if (resp.clusters && resp.clusters.length > 1) {
    html += `<section><h4>Results group into</h4>${resp.clusters.map((c, i) => `<button class="cluster" data-cluster="${i}">${esc(c.label.join(" and "))}<small>${c.docs.length} of these results</small></button>`).join("")}</section>`;
  }
  if (params.q) html += `<section class="mini-graph"><h4>Concept neighbourhood</h4><div id="mini"></div></section>`;
  el.innerHTML = html;
  el.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.q) go({ q: b.dataset.q });
    if (b.dataset.cluster !== undefined) {
      const on = !b.classList.contains("on");
      $$(".cluster", el).forEach((x) => x.classList.remove("on"));
      const ids = new Set(on ? resp.clusters[+b.dataset.cluster].docs : []);
      b.classList.toggle("on", on);
      $$(".results .list > .result").forEach((r) => (r.hidden = on && !ids.has(r.dataset.id)));
    }
  });
  const seeds = [...new Set(resp.hits.slice(0, 5).flatMap((h) => (h.tags || []).slice(0, 2)))].join("|");
  if (params.q) api(`/api/kg?${qs({ c: state.coll, q: params.q, n: 10, seeds, strict: true })}`).then((g) => {
    const box = $("#mini");
    if (!box) return;
    if (!g.nodes.length) { box.closest("section").remove(); return; }
    forceGraph(box, g, { height: 260, small: true, onClick: (n) => go({ q: n.label }) });
  }).catch(() => {});
}

/* ---------------------------------------------------------------- document reader */
async function openDoc(id, q = "") {
  const d = $("#drawer"), body = $("#drawer-body");
  d.classList.add("open"); d.setAttribute("aria-hidden", "false"); $("#scrim").hidden = false;
  body.innerHTML = `<p class="loading">Opening document</p>`;
  try {
    const doc = await api(`/api/doc?${qs({ c: state.coll, id, q })}`);
    const m = doc.meta || {};
    const reasons = (doc.credibility_reasons || []).map(([r, v]) => `<li><span>${esc(r)}</span><span class="${v >= 0 ? "pos" : "neg"}">${v >= 0 ? "+" : ""}${v}</span></li>`).join("");
    body.innerHTML = `
      <button class="icon-btn close" aria-label="Close reader" data-close>✕</button>
      <p class="small muted">${esc(m.category || "")}</p>
      <h2>${esc(doc.title)}</h2>
      ${m.author ? `<p class="muted">${esc(m.author)}</p>` : ""}
      ${m.venue || m.year ? `<p class="small muted">${[m.venue, m.year].filter(Boolean).map(esc).join(", ")}${+m.citations ? `. ${cites(m.citations)}.` : ""}</p>` : ""}
      ${doc.tags.length ? `<div class="chips" style="display:flex;flex-wrap:wrap;gap:6px">${doc.tags.map((t) => `<button class="chip" data-q="${esc(t)}">${esc(t)}</button>`).join("")}</div>` : ""}
      <div class="facts">
        <div><b>${fmt(doc.words)}</b><span>indexed terms</span></div>
        <div><b style="font-size:14px;line-height:1.35">${esc(doc.topic)}</b><span>topic</span></div>
        <div><b>${doc.credibility}</b><span>credibility score</span></div>
        <div><b>${doc.pagerank}</b><span>authority (PageRank)</span></div>
      </div>
      ${doc.file_url ? `<p><a class="btn ghost" href="${doc.file_url}" target="_blank" rel="noopener">Open original file</a></p>` : ""}
      ${m.url && /^https?:/.test(m.url) ? `<p><a class="btn ghost" href="${esc(m.url)}" target="_blank" rel="noopener">Open the paper</a></p>` : ""}
      ${reasons ? `<details><summary class="small">How the credibility score was computed</summary><ul class="reasons">${reasons}</ul></details>` : ""}
      ${doc.cites.length ? `<h4>Cites in this collection</h4><ul>${doc.cites.map((c) => `<li><a href="#" data-open="${esc(c.id)}">${esc(c.title)}</a></li>`).join("")}</ul>` : ""}
      ${doc.cited_by.length ? `<h4>Cited by</h4><ul>${doc.cited_by.map((c) => `<li><a href="#" data-open="${esc(c.id)}">${esc(c.title)}</a></li>`).join("")}</ul>` : ""}
      <h4>Similar papers</h4><div id="drawer-related" class="small muted">Loading</div>
      <div class="fulltext">${doc.html}${doc.truncated ? "\n\n[…document continues]" : ""}</div>`;
    api(`/api/related?${qs({ c: state.coll, id, k: 5 })}`).then((rel) => {
      $("#drawer-related").innerHTML = `<ul>${rel.map((r) => `<li><a href="#" data-open="${esc(r.id)}">${esc(r.title)}</a> <span class="muted small">${relWhy(r.components)}</span></li>`).join("")}</ul>`;
    }).catch(() => ($("#drawer-related").textContent = "Not available"));
    body.onclick = (e) => {
      const t = e.target.closest("[data-open],[data-close],[data-q]");
      if (!t) return;
      e.preventDefault();
      if (t.dataset.close !== undefined) closeDrawer();
      else if (t.dataset.open) openDoc(t.dataset.open, q);
      else if (t.dataset.q) { closeDrawer(); go({ q: t.dataset.q }); }
    };
    $("[data-close]", body).focus();
  } catch (e) { body.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}
function closeDrawer() {
  const d = $("#drawer");
  d.classList.remove("open"); d.setAttribute("aria-hidden", "true"); $("#scrim").hidden = true;
}
$("#scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

/* ---------------------------------------------------------------- COMPARE */
async function pageCompare(params) {
  const main = $("#main");
  if (!needReady(main)) return;
  const opts = (sel) => state.modes.map((m) => `<option value="${m.id}" ${m.id === sel ? "selected" : ""}>${esc(m.name)}</option>`).join("");
  const a = params.a || "bm25", b = params.b || "bridge";
  main.innerHTML = `<div class="page">
    <header><h1>Compare ranking models</h1><p>Run one query through two models and see where they agree. Shared documents are tinted; hover one to find it in the other list.</p></header>
    <form class="compare-head" id="cmp">
      <div class="field" style="flex:1;min-width:260px"><label for="cq">Query</label><input id="cq" value="${esc(params.q || (currentColl().examples || [""])[0])}"></div>
      <div class="field"><label for="ca">Left</label><select id="ca">${opts(a)}</select></div>
      <div class="field"><label for="cb">Right</label><select id="cb">${opts(b)}</select></div>
      <button class="btn" type="submit">Compare</button>
    </form>
    <div id="cmp-out"></div></div>`;
  $("#cmp").addEventListener("submit", (e) => { e.preventDefault(); location.hash = "#/compare?" + qs({ q: $("#cq").value, a: $("#ca").value, b: $("#cb").value }); });
  if (!params.q) return;
  const out = $("#cmp-out");
  out.innerHTML = `<p class="loading">Running both models</p>`;
  try {
    const r = await api(`/api/compare?${qs({ c: state.coll, q: params.q, a, b, k: 10 })}`);
    const shared = new Set(r.a.hits.map((h) => h.doc_id).filter((x) => r.b.hits.some((h) => h.doc_id === x)));
    const col = (run, name) => `<div><h3>${esc(name)}</h3><p class="small muted">${fmt(run.total_matches)} matches, ${run.took_ms} ms</p><ol>${run.hits.map((h) => `<li class="${shared.has(h.doc_id) ? "shared" : ""}" data-id="${esc(h.doc_id)}"><span class="rank">${h.rank}</span><div><div class="t" data-open="${esc(h.doc_id)}">${esc(h.title)}</div><small>${esc(h.topic || "")}</small></div></li>`).join("")}</ol></div>`;
    out.innerHTML = `<p class="note-callout">${shared.size} of 10 documents appear in both lists. Overlap (Jaccard) ${r.jaccard}, rank-biased overlap ${r.rbo ?? "–"}: values near 1 mean the models agree on order too.</p><div class="compare-cols">${col(r.a, r.a_name)}${col(r.b, r.b_name)}</div>`;
    out.addEventListener("mouseover", (e) => { const li = e.target.closest("li[data-id]"); $$("li.hot", out).forEach((x) => x.classList.remove("hot")); if (li) $$(`li[data-id="${CSS.escape(li.dataset.id)}"]`, out).forEach((x) => x.classList.add("hot")); });
    out.addEventListener("click", (e) => { const t = e.target.closest("[data-open]"); if (t) openDoc(t.dataset.open, params.q); });
  } catch (e) { out.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}

/* ---------------------------------------------------------------- LIBRARY */
async function pageLibrary() {
  const main = $("#main");
  main.innerHTML = `<div class="page">
    <header><h1>My library</h1><p>Add your own papers and notes. SearchBridge extracts the text from PDFs, indexes it with every model, and keeps it on this computer in <code>data/library/</code>.</p></header>
    <label class="dropzone" id="drop" tabindex="0">
      <h3>Drop files here, or choose files</h3>
      <p class="muted small">PDF, TXT, Markdown, HTML or JSONL, up to 50 MB each</p>
      <input type="file" id="files" multiple accept=".pdf,.txt,.md,.html,.htm,.json,.jsonl" hidden>
    </label>
    <div id="lib-status" class="small muted" style="margin-top:12px"></div>
    <ul class="filelist" id="filelist"></ul>
    <p style="margin-top:20px"><button class="btn ghost" id="samples">Add the sample documents</button> <a class="btn" href="#/" id="search-lib">Search my library</a></p></div>`;
  const drop = $("#drop"), input = $("#files");
  drop.addEventListener("click", (e) => { if (e.target !== input) input.click(); });
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => upload(e.dataTransfer.files));
  input.addEventListener("change", () => upload(input.files));
  $("#samples").addEventListener("click", async () => { await api("/api/library/load-samples", { method: "POST" }); toast("Sample documents added. Indexing…"); watchLibrary(); });
  $("#search-lib").addEventListener("click", () => { state.coll = "library"; localStorage.setItem("sb.coll", "library"); $("#collection").value = "library"; });
  await refreshLibrary();
}
async function refreshLibrary() {
  const data = await api("/api/library");
  const list = $("#filelist");
  if (!list) return data;
  list.innerHTML = data.files.length ? data.files.map((f) => `<li><span class="type">${esc(f.type)}</span><span>${esc(f.name)}</span><span class="muted small">${(f.bytes / 1024).toFixed(0)} KB</span><button class="linkbtn" data-del="${esc(f.name)}">Remove</button></li>`).join("") : `<li style="display:block" class="muted">No files yet.</li>`;
  $$("[data-del]", list).forEach((b) => b.addEventListener("click", async () => { await api(`/api/library/${encodeURIComponent(b.dataset.del)}`, { method: "DELETE" }); toast(`Removed ${b.dataset.del}`); watchLibrary(); }));
  const st = { ready: "Indexed and ready to search.", building: "Indexing…", empty: "Nothing indexed yet.", error: `Indexing failed: ${data.error}`, idle: "Waiting to index…" }[data.status];
  $("#lib-status").textContent = st || "";
  return data;
}
async function upload(files) {
  if (!files || !files.length) return;
  const fd = new FormData();
  [...files].forEach((f) => fd.append("files", f));
  $("#lib-status").textContent = `Uploading ${files.length} file(s)…`;
  try {
    const r = await api("/api/library/upload", { method: "POST", body: fd });
    toast(`Added ${r.saved.length} file(s)${r.rejected.length ? `, skipped ${r.rejected.length}` : ""}. Indexing…`);
    watchLibrary();
  } catch (e) { $("#lib-status").textContent = e.message; }
}
async function watchLibrary() {
  await new Promise((r) => setTimeout(r, 600));
  const data = await refreshLibrary();
  await loadCollections();
  if (data.status === "building" || data.status === "idle") setTimeout(watchLibrary, 1500);
}

/* ---------------------------------------------------------------- CONCEPT MAP */
async function pageGraph(params) {
  const main = $("#main");
  if (!needReady(main)) return;
  main.innerHTML = `<div class="page">
    <header><h1>Concept map</h1><p>Concepts are author keyphrases, mined phrases and ontology terms; lines join concepts that appear in the same documents more often than chance (NPMI). Drag to explore, click a concept to search for it.</p></header>
    <form id="gform" class="compare-head" style="margin-bottom:16px"><div class="field" style="flex:1"><label for="gq">Centre the map on</label><input id="gq" placeholder="e.g. information retrieval" value="${esc(params.q || "")}"></div><button class="btn">Show</button></form>
    <div class="graph-wrap"><div id="graph"></div><div class="graph-legend"><span><i style="background:var(--lex)"></i>matches your query</span><span><i style="background:var(--sem)"></i>related concept</span><span><i style="background:var(--faint)"></i>ontology concept</span></div></div></div>`;
  $("#gform").addEventListener("submit", (e) => { e.preventDefault(); location.hash = "#/graph?" + qs({ q: $("#gq").value }); });
  try {
    const g = await api(`/api/kg?${qs({ c: state.coll, q: params.q || "", n: 60 })}`);
    if (!g.nodes.length) { $("#graph").innerHTML = `<p class="empty">No concepts found${params.q ? ` for “${esc(params.q)}”` : ""}. Try a broader phrase.</p>`; return; }
    forceGraph($("#graph"), g, { height: 620, onClick: (n) => go({ q: n.label }) });
  } catch (e) { $("#graph").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}

function forceGraph(el, g, { height = 500, small = false, onClick } = {}) {
  const W = el.clientWidth || 700, H = height;
  const nodes = g.nodes.map((n, i) => ({ ...n, x: W / 2 + Math.cos(i) * 80 * Math.random() + (Math.random() - .5) * W * .5, y: H / 2 + Math.sin(i) * 80 * Math.random() + (Math.random() - .5) * H * .5, vx: 0, vy: 0 }));
  const idx = Object.fromEntries(nodes.map((n, i) => [n.id, i]));
  const edges = g.edges.filter((e) => e.source in idx && e.target in idx).map((e) => ({ s: idx[e.source], t: idx[e.target], w: e.weight }));
  const maxDocs = Math.max(...nodes.map((n) => n.docs), 1);
  const r = (n) => (small ? 4 : 5) + (small ? 6 : 14) * Math.sqrt(n.docs / maxDocs);
  // simple force simulation: repulsion + springs + centring
  for (let it = 0; it < 320; it++) {
    const alpha = 1 - it / 320;
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      let dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy + 0.01;
      const f = (small ? 2200 : 2600) / d2 * alpha;
      a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
    }
    for (const e of edges) {
      const a = nodes[e.s], b = nodes[e.t];
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
      const k = (d - (small ? 70 : 90)) * 0.02 * (0.5 + e.w) * alpha;
      a.vx += dx / d * k; a.vy += dy / d * k; b.vx -= dx / d * k; b.vy -= dy / d * k;
    }
    for (const n of nodes) {
      n.vx += (W / 2 - n.x) * (small ? 0.006 : 0.004); n.vy += (H / 2 - n.y) * (small ? 0.008 : 0.006);
      n.x += Math.max(-12, Math.min(12, n.vx)); n.y += Math.max(-12, Math.min(12, n.vy));
      n.vx *= 0.6; n.vy *= 0.6;
      n.x = Math.max(r(n) + 8, Math.min(W - r(n) - 8, n.x)); n.y = Math.max(r(n) + 10, Math.min(H - r(n) - (small ? 10 : 40), n.y));
    }
  }
  const color = (n) => (n.seed ? "var(--lex)" : n.concept ? "var(--faint)" : "var(--sem)");
  const svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Concept map with ${nodes.length} concepts">
    <g class="edges">${edges.map((e) => `<line class="edge" x1="${nodes[e.s].x}" y1="${nodes[e.s].y}" x2="${nodes[e.t].x}" y2="${nodes[e.t].y}" stroke-width="${0.6 + 2.2 * e.w}" stroke-opacity="${0.35 + 0.5 * e.w}"/>`).join("")}</g>
    <g>${nodes.map((n, i) => `<g class="node ${n.seed ? "seed" : ""}" data-i="${i}" transform="translate(${n.x},${n.y})" tabindex="0" role="button" aria-label="${esc(n.label)}, ${n.docs} documents"><circle r="${r(n)}" fill="${color(n)}"/><text x="${n.x > W * 0.62 ? -(r(n) + 4) : r(n) + 4}" y="4" text-anchor="${n.x > W * 0.62 ? "end" : "start"}">${esc(n.label)}</text><title>${esc(n.label)} (${n.docs} documents)</title></g>`).join("")}</g></svg>`;
  el.innerHTML = svg;
  const s = $("svg", el);
  // drag nodes
  let drag = null;
  const pt = (e) => { const b = s.getBoundingClientRect(); return { x: (e.clientX - b.left) * W / b.width, y: (e.clientY - b.top) * H / b.height }; };
  const redraw = () => {
    $$(".node", s).forEach((g_) => { const n = nodes[g_.dataset.i]; g_.setAttribute("transform", `translate(${n.x},${n.y})`); });
    $$("line", s).forEach((l, k) => { const e = edges[k]; l.setAttribute("x1", nodes[e.s].x); l.setAttribute("y1", nodes[e.s].y); l.setAttribute("x2", nodes[e.t].x); l.setAttribute("y2", nodes[e.t].y); });
  };
  let moved = false;
  s.addEventListener("pointerdown", (e) => { const g_ = e.target.closest(".node"); if (g_) { drag = nodes[g_.dataset.i]; moved = false; s.setPointerCapture(e.pointerId); } });
  s.addEventListener("pointermove", (e) => { if (!drag) return; const p = pt(e); drag.x = p.x; drag.y = p.y; moved = true; redraw(); });
  s.addEventListener("pointerup", (e) => { const g_ = e.target.closest(".node"); if (drag && !moved && onClick) onClick(drag); drag = null; });
  s.addEventListener("keydown", (e) => { const g_ = e.target.closest(".node"); if (g_ && e.key === "Enter" && onClick) onClick(nodes[g_.dataset.i]); });
}

/* ---------------------------------------------------------------- charts */
function lineChart(points, { w = 460, h = 260, logx = false, logy = false, xlabel = "", ylabel = "", fit = null } = {}) {
  const tx = (v) => (logx ? Math.log10(v) : v), ty = (v) => (logy ? Math.log10(v) : v);
  const xs = points.map((p) => tx(p[0])), ys = points.map((p) => ty(p[1]));
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const L = 52, B = 36, T = 10, R = 12;
  const X = (v) => L + (tx(v) - x0) / (x1 - x0 || 1) * (w - L - R);
  const Y = (v) => h - B - (ty(v) - y0) / (y1 - y0 || 1) * (h - B - T);
  const path = points.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
  const ticks = (a, b, log) => { const out = []; if (log) { for (let e = Math.ceil(a); e <= Math.floor(b); e++) out.push(10 ** e); } else { for (let i = 0; i <= 4; i++) out.push(a + (b - a) * i / 4); } return out; };
  const fmtT = (v) => (v >= 1000 ? (v / 1000).toFixed(v >= 10000 ? 0 : 1) + "k" : Math.round(v));
  const fitPath = fit ? points.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(Math.max(1e-9, fit(p[0]))).toFixed(1)}`).join("") : "";
  return `<svg viewBox="0 0 ${w} ${h}">
    <line class="axis" x1="${L}" y1="${h - B}" x2="${w - R}" y2="${h - B}"/><line class="axis" x1="${L}" y1="${T}" x2="${L}" y2="${h - B}"/>
    ${ticks(x0, x1, logx).map((v) => `<text x="${X(v)}" y="${h - B + 15}" text-anchor="middle">${fmtT(v)}</text>`).join("")}
    ${ticks(y0, y1, logy).map((v) => `<text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end">${fmtT(v)}</text>`).join("")}
    <text x="${(L + w - R) / 2}" y="${h - 4}" text-anchor="middle">${esc(xlabel)}</text>
    <text x="12" y="${(T + h - B) / 2}" text-anchor="middle" transform="rotate(-90 12 ${(T + h - B) / 2})">${esc(ylabel)}</text>
    ${fitPath ? `<path d="${fitPath}" fill="none" stroke="var(--sem)" stroke-width="1.5" stroke-dasharray="5 4"/>` : ""}
    <path d="${path}" fill="none" stroke="var(--lex)" stroke-width="2"/>
  </svg>`;
}

/* ---------------------------------------------------------------- INSIGHTS */
async function pageInsights() {
  const main = $("#main");
  if (!needReady(main)) return;
  main.innerHTML = `<div class="page"><header><h1>Inside the index</h1><p>How ${esc(currentColl().name)} is stored: the inverted index, its compression, and the term statistics that ranking relies on.</p></header><p class="loading">Reading index statistics</p></div>`;
  let d;
  try { d = await api(`/api/insights?${qs(collParam())}`); } catch (e) { $(".page", main).insertAdjacentHTML("beforeend", `<p class="error">${esc(e.message)}</p>`); return; }
  const s = d.stats;
  const maxRatio = 1;
  $(".page", main).innerHTML = `
    <header><h1>Inside the index</h1><p>How ${esc(currentColl().name)} is stored: the inverted index, its compression, and the term statistics that ranking relies on.</p></header>
    <div class="stats">
      <div><b>${fmt(s.documents)}</b><span>documents</span></div><div><b>${fmt(s.vocabulary)}</b><span>distinct terms</span></div>
      <div><b>${fmt(s.postings)}</b><span>postings</span></div><div><b>${fmt(s.tokens)}</b><span>tokens indexed</span></div>
      <div><b>${s.avg_doc_len}</b><span>average document length</span></div><div><b>${s.topics}</b><span>automatic topics</span></div>
      <div><b>${esc(s.dense_encoder)}</b><span>semantic encoder</span></div><div><b>${s.build_seconds}s</b><span>build time</span></div>
    </div>
    <div class="grid2">
      <div class="panel chart"><h3>Zipf's law</h3><p class="small muted">Collection frequency falls as rank<sup>−${d.zipf.exponent.toFixed(2)}</sup> (R² ${d.zipf.r2.toFixed(2)}); a few terms account for most tokens.</p>${lineChart(d.zipf.points, { logx: true, logy: true, xlabel: "term rank", ylabel: "frequency" })}</div>
      <div class="panel chart"><h3>Heaps' law</h3><p class="small muted">Vocabulary keeps growing as M = ${d.heaps.k.toFixed(1)}·T<sup>${d.heaps.b.toFixed(2)}</sup> (R² ${d.heaps.r2.toFixed(3)}); the dashed line is the fit.</p>${lineChart(d.heaps.points, { xlabel: "tokens read", ylabel: "distinct terms", fit: (t) => d.heaps.k * t ** d.heaps.b })}</div>
    </div>
    <div class="panel" style="margin-top:24px"><h3>Compression</h3><p class="small muted">Document-ID gaps are small for frequent terms, so variable-length codes shrink the postings to about a quarter of their size.</p>
      <table class="data"><thead><tr><th>Structure</th><th class="num">Bytes</th><th class="num" style="width:40%">Size vs. uncompressed</th></tr></thead>
      <tbody>${d.compression.map((c) => `<tr><td>${esc(c.structure)}</td><td class="num">${fmt(c.bytes)}</td><td><div class="barcell"><i style="width:${(c.ratio / maxRatio) * 85}%"></i>${(c.ratio * 100).toFixed(0)}%</div></td></tr>`).join("")}</tbody></table></div>
    <div class="grid2" style="margin-top:24px">
      <div class="panel"><h3>Look up a term</h3><form id="pform" class="compare-head"><div class="field" style="flex:1"><label for="pt">Term or wildcard (e.g. retriev*)</label><input id="pt" value="retrieval"></div><button class="btn">Look up</button></form><div id="pout" style="margin-top:12px"></div></div>
      <div class="panel"><h3>Most authoritative documents</h3><p class="small muted">PageRank over the ${esc(s.link_graph)} graph.</p><ol>${d.pagerank_top.map((p) => `<li><a href="#" data-open="${esc(p.id)}">${esc(p.title)}</a> <span class="muted small">${p.score.toFixed(2)}</span></li>`).join("")}</ol>
        <h3 style="margin-top:18px">Topics</h3><ul class="small">${d.topics.map(([t, n]) => `<li><a href="#/?${qs({ topic: t })}">${esc(t)}</a> <span class="muted">${n}</span></li>`).join("")}</ul></div>
    </div>`;
  $$("[data-open]", main).forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openDoc(a.dataset.open); }));
  const lookup = async () => {
    const out = $("#pout");
    try {
      const p = await api(`/api/postings?${qs({ c: state.coll, term: $("#pt").value })}`);
      out.innerHTML = `${p.spelling.length && p.spelling[0][1] > 0 ? `<p>Did you mean <a href="#" data-term="${esc(p.spelling[0][0])}">${esc(p.spelling[0][0])}</a>?</p>` : ""}
        <p class="small">Stem <b>${esc(p.stem || "–")}</b> appears in <b>${fmt(p.df)}</b> documents (idf ${p.idf}). Postings: ${fmt(p.raw_bytes)} bytes raw, ${fmt(p.vb_bytes)} with variable-byte codes, ${fmt(Math.ceil(p.gamma_bits / 8))} with gamma codes.</p>
        ${p.gaps_preview.length ? `<p class="small muted">First gaps: ${p.gaps_preview.join(", ")}</p>` : ""}
        ${p.postings.length ? `<table class="data"><thead><tr><th>Document</th><th class="num">tf</th><th>Positions</th></tr></thead><tbody>${p.postings.slice(0, 8).map((x) => `<tr><td><a href="#" data-open="${esc(x.doc)}">${esc(x.title)}</a></td><td class="num">${x.tf}</td><td class="small muted">${x.positions.join(", ")}</td></tr>`).join("")}</tbody></table>` : ""}
        ${p.wildcard.length ? `<p class="small" style="margin-top:10px">Wildcard matches: ${p.wildcard.map(esc).join(", ")}</p>` : ""}`;
      $$("[data-open]", out).forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openDoc(a.dataset.open); }));
      $$("[data-term]", out).forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); $("#pt").value = a.dataset.term; lookup(); }));
    } catch (e) { out.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  };
  $("#pform").addEventListener("submit", (e) => { e.preventDefault(); lookup(); });
  lookup();
}

/* ---------------------------------------------------------------- EVALUATION */
async function pageEvaluation() {
  const main = $("#main");
  main.innerHTML = `<div class="page"><p class="loading">Loading results</p></div>`;
  let d;
  try { d = await api("/api/eval"); } catch (e) { main.innerHTML = `<div class="page"><p class="error">${esc(e.message)}</p></div>`; return; }
  const R = d.cranfield, cols = ["MAP", "P@10", "nDCG@10", "MRR", "R@100"];
  const rows = Object.entries(R.main_table);
  const best = Object.fromEntries(cols.map((c) => [c, Math.max(...rows.map(([, r]) => r[c]))]));
  const maxMap = best.MAP;
  const table = (rowsIn, colsIn, bestIn, showBar) => `<table class="data"><thead><tr><th>System</th>${colsIn.map((c) => `<th class="num">${c}</th>`).join("")}${showBar ? `<th style="width:22%"></th>` : ""}</tr></thead><tbody>
    ${rowsIn.map(([n, r]) => `<tr class="${/ours/.test(n) ? "ours" : ""}"><td>${esc(n)}${r.p_vs_bm25_rand != null && r.p_vs_bm25_rand < 0.05 && r.MAP > rowsIn.find(([x]) => /^BM25 \(/.test(x))?.[1].MAP ? " <span class='muted small' title='significantly better than BM25 (p<0.05)'>†</span>" : ""}</td>${colsIn.map((c) => `<td class="num ${r[c] === bestIn[c] ? "best" : ""}">${r[c] == null ? "–" : Number(r[c]).toFixed(4)}</td>`).join("")}${showBar ? `<td><div class="barcell" style="justify-content:flex-start"><i style="width:${(r.MAP / maxMap) * 100}%"></i></div></td>` : ""}</tr>`).join("")}</tbody></table>`;
  const w = R.win_tie_loss_vs_bm25;
  const kp = d.keyphrase;
  main.innerHTML = `<div class="page">
    <header><h1>Evaluation</h1><p>Every model is evaluated on the Cranfield test collection (${R.collection.docs} documents, ${R.collection.queries} queries with relevance judgements). Tuned settings use 5-fold cross-validation; † marks a significant improvement over BM25 (paired randomisation test, p &lt; 0.05).</p></header>
    <div class="stats">
      <div><b>${(R.main_table["Bridge-PRF (ours, 5-fold CV-tuned)"].MAP).toFixed(3)}</b><span>MAP, Bridge-PRF</span></div>
      <div><b>+${((R.main_table["Bridge-PRF (ours, 5-fold CV-tuned)"].MAP / R.main_table["BM25 (k1=1.2, b=0.75)"].MAP - 1) * 100).toFixed(1)}%</b><span>over BM25</span></div>
      <div><b>${w.wins} / ${w.losses}</b><span>queries won / lost vs BM25</span></div>
      <div><b>${R.oracle_per_query_alpha_MAP.toFixed(3)}</b><span>oracle hybrid upper bound</span></div>
    </div>
    <div class="panel">${table(rows, cols, best, true)}</div>
    ${kp ? `<h2 style="margin:34px 0 8px">Second collection: CS Research Library</h2><p class="muted" style="max-width:75ch">${esc(kp.description)}</p><div class="panel">${table(Object.entries(kp.table), ["MAP", "P@10", "nDCG@10", "MRR"], Object.fromEntries(["MAP", "P@10", "nDCG@10", "MRR"].map((c) => [c, Math.max(...Object.values(kp.table).map((r) => r[c]))])), false)}</div>` : ""}
    <h2 style="margin:34px 0 12px">Bridge-PRF ablation</h2>
    <div class="panel"><table class="data"><thead><tr><th>Variant</th>${cols.map((c) => `<th class="num">${c}</th>`).join("")}</tr></thead><tbody>${Object.entries(R.bridge_ablation).map(([n, r]) => `<tr><td>${esc(n.replace(/^\s*-\s*/, ""))}</td>${cols.map((c) => `<td class="num">${r[c].toFixed(4)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
    <h2 style="margin:34px 0 12px">Figures</h2>
    <div class="figs">${d.figures.map((f) => `<figure><img src="/figures/${f}" alt="${esc(f.replace(/_/g, " ").replace(".png", ""))}" loading="lazy"><figcaption>${esc({ "pr_curves.png": "Interpolated precision–recall", "per_query_delta.png": "Per-query AP gain over BM25", "alpha_curve.png": "Lexical/semantic interpolation weight", "bm25_sweep.png": "BM25 parameter sweep", "mmr_tradeoff.png": "Diversity vs relevance (MMR)", "zipf_heaps.png": "Zipf and Heaps laws" }[f] || f)}</figcaption></figure>`).join("")}</div>
    <p class="small muted" style="margin-top:20px">Reproduce with <code>python experiments/run_benchmark.py</code>; the full write-up is in <code>results/RESULTS.md</code> and <code>docs/REPORT.md</code>.</p></div>`;
}

/* ---------------------------------------------------------------- TRUST */
async function pageTrust() {
  const main = $("#main");
  main.innerHTML = `<div class="page">
    <header><h1>Trust &amp; privacy</h1><p>SearchBridge flags low-credibility writing, hides personal data in snippets, and only releases search statistics that cannot identify a user.</p></header>
    <div class="grid2">
      <div class="panel"><h3>Check a passage</h3><p class="small muted">Paste any text to see its credibility signals and the personal data SearchBridge would redact.</p>
        <div class="field"><label for="tt">Text</label><textarea id="tt">SHOCKING!!! This miracle algorithm ALWAYS finds every paper, 100% guaranteed. Contact preksha.c@example.com or +91 98765 43210.</textarea></div>
        <div class="field"><label for="ts">Source URL (optional)</label><input id="ts" placeholder="https://arxiv.org/abs/..."></div>
        <button class="btn" id="tcheck">Check text</button><div id="tout" style="margin-top:16px"></div></div>
      <div class="panel"><h3>Query log in this session</h3><p class="small muted">User IDs are salted hashes and queries are PII-redacted. A query is releasable only when at least <span id="kval">3</span> different users searched for it (k-anonymity); released counts get Laplace noise (ε = 1 differential privacy).</p><div id="logout"><p class="loading">Loading</p></div></div>
    </div></div>`;
  const check = async () => {
    const r = await api("/api/trust/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: $("#tt").value, source: $("#ts").value }) });
    $("#tout").innerHTML = `<p><b style="font:400 30px var(--serif)">${r.score}</b> <span class="${r.flag ? "flag" : "muted"}" style="color:${r.flag ? "var(--warn)" : "var(--ok)"}">${r.flag ? "Low credibility" : "No strong warning signs"}</span></p>
      <ul class="reasons">${r.reasons.map(([n, v]) => `<li><span>${esc(n)}</span><span class="${v >= 0 ? "pos" : "neg"}">${v >= 0 ? "+" : ""}${v}</span></li>`).join("") || "<li class='muted'>No signals found</li>"}</ul>
      <h4 style="margin:16px 0 6px;font:600 14px var(--sans)">Personal data found: ${r.pii.length}</h4><p class="small" style="background:var(--paper);padding:10px;border-radius:6px">${esc(r.redacted)}</p>`;
  };
  $("#tcheck").addEventListener("click", check);
  check();
  try {
    const l = await api(`/api/trust/log?${qs(collParam())}`);
    $("#kval").textContent = l.k;
    $("#logout").innerHTML = `<p class="small">${l.logged} searches logged. Most recent:</p><table class="data"><thead><tr><th>User (hashed)</th><th>Query (redacted)</th></tr></thead><tbody>${l.sample.reverse().map((x) => `<tr><td class="small muted">${esc(x.user)}</td><td>${esc(x.query)}</td></tr>`).join("") || "<tr><td colspan=2 class='muted'>Search something first.</td></tr>"}</tbody></table>
      <p class="small" style="margin-top:12px">Releasable queries: ${Object.keys(l.releasable).length ? Object.entries(l.dp_counts).map(([q, n]) => `${esc(q)} (≈${n})`).join(", ") : "none yet, since every query so far comes from a single user."}</p>`;
  } catch (e) { $("#logout").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}

/* ---------------------------------------------------------------- boot */
loadCollections().then(route).catch((e) => { $("#main").innerHTML = `<div class="page"><p class="error">Cannot reach the SearchBridge server: ${esc(e.message)}</p></div>`; });
