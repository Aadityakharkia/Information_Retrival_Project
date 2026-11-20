/* SearchBridge frontend — single file, no build step. */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => Number(n || 0).toLocaleString("en-US");
<<<<<<< HEAD
const qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== "" && v !== null && v !== undefined && v !== false)).toString();
=======
const qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== "" && v !== null && v !== undefined)).toString();
>>>>>>> 1d6f999a29f64cc4785f3e1f1baa07f014efb4c0
const S = { info: null, c: localStorage.getItem("sb.c") || "", results: null, dwell: null };

async function api(path, opts = {}) {
  const r = await fetch(path, { credentials: "same-origin", ...opts });
  let body = null;
  try { body = await r.json(); } catch { /* no body */ }
  if (!r.ok) { const e = new Error((body && body.detail) || `Request failed (${r.status})`); e.status = r.status; throw e; }
  return body;
}
const post = (path, data) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
function event(kind, data) { return post("/api/events", { c: S.c, kind, ...data }).catch(() => {}); }
function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 2600); }

const ICON = {
  lens: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  trend: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
  doc: '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
  up: '<path d="M7 11v9H4v-9zM7 11l4-8c1.5 0 2.5 1 2.5 2.5V9h5.2a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.5 20H7"/>',
  down: '<path d="M17 13V4h3v9zM17 13l-4 8c-1.5 0-2.5-1-2.5-2.5V15H5.3a2 2 0 0 1-2-2.3l1.2-7A2 2 0 0 1 6.5 4H17"/>',
  bars: '<path d="M4 20V10M10 20V4M16 20v-7"/>',
  memory: '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>',
  book: '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19a2 2 0 0 1 2-2h13"/>',
  atom: '<circle cx="12" cy="12" r="1.5"/><ellipse cx="12" cy="12" rx="9" ry="3.6"/><ellipse cx="12" cy="12" rx="9" ry="3.6" transform="rotate(60 12 12)"/><ellipse cx="12" cy="12" rx="9" ry="3.6" transform="rotate(120 12 12)"/>',
  net: '<circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><circle cx="12" cy="10" r="2"/><path d="M6.7 7l3.6 2M17.3 7l-3.6 2M12 12v4"/>',
  chip: '<rect x="7" y="7" width="10" height="10" rx="2"/><path d="M9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>',
  plane: '<path d="M2 13l8-1 6-8h2l-3 8 5 1 2-2h1l-1 4 1 4h-1l-2-2-5 1 3 8h-2l-6-8-8-1z"/>',
  folder: '<path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
};
const svg = (k, extra = "") => `<svg viewBox="0 0 24 24" aria-hidden="true" ${extra}>${ICON[k]}</svg>`;
const COLL_STYLE = { research: ["atom", "var(--lav)"], cs: ["chip", "var(--mint)"], cranfield: ["plane", "var(--cream)"], web: ["globe", "#FDE8EC"], library: ["folder", "var(--blue-soft)"] };

/* ------------------------------------------------------------------ collections */
async function loadInfo() {
  S.info = await api("/api/collections");
  const ids = S.info.collections.map((c) => c.id);
  if (!ids.includes(S.c)) S.c = S.info.default;
  const cur = coll();
  if (cur && !["ready", "building", "idle"].includes(cur.status)) {
    const ready = S.info.collections.find((c) => c.status === "ready");
    if (ready) S.c = ready.id;
  }
}
const coll = (id = S.c) => S.info && S.info.collections.find((c) => c.id === id);
function setCollection(id) { S.c = id; localStorage.setItem("sb.c", id); }
function collectionPicker(onChange) {
  const opts = S.info.collections.filter((c) => c.status !== "missing").map((c) =>
    `<option value="${c.id}" ${c.id === S.c ? "selected" : ""}>${esc(c.name)}${c.status === "ready" ? "" : c.status === "empty" ? " (empty)" : " (indexing…)"}</option>`).join("");
  const w = document.createElement("label");
  w.className = "collection-pick";
  w.innerHTML = `Searching <span class="sr">collection</span><select aria-label="Collection">${opts}</select>`;
  $("select", w).addEventListener("change", (e) => { setCollection(e.target.value); onChange && onChange(e.target.value); });
  return w;
}

/* ------------------------------------------------------------------ search box with live suggestions */
function searchBox({ q = "", compact = false, onSubmit, placeholder }) {
  const w = document.createElement("div");
  w.className = "search" + (compact ? " compact" : "");
  w.innerHTML = `<form role="search">${svg("lens", 'class="lens"')}
    <label class="sr" for="${compact ? "q2" : "q1"}">Search</label>
    <input id="${compact ? "q2" : "q1"}" type="search" autocomplete="off" spellcheck="false" value="${esc(q)}" placeholder="${esc(placeholder || "Search documents, topics or questions")}"
      role="combobox" aria-expanded="false" aria-controls="${compact ? "ac2" : "ac1"}" aria-autocomplete="list">
    <button class="go" type="submit">Search</button></form>
    <div class="ac" id="${compact ? "ac2" : "ac1"}" role="listbox" hidden></div>`;
  const input = $("input", w), box = $(".ac", w), form = $("form", w);
  let items = [], sel = -1, timer, seq = 0;
  const cache = new Map();
  const close = () => { box.hidden = true; input.setAttribute("aria-expanded", "false"); sel = -1; };
  const render = (r) => {
    items = [];
    const typed = input.value.trim().toLowerCase();
    const bold = (t) => { const i = t.toLowerCase().indexOf(typed); return i === 0 ? `${esc(t.slice(0, typed.length))}<b>${esc(t.slice(typed.length))}</b>` : esc(t); };
    let html = "";
    const group = (title, list, icon, kind) => {
      if (!list.length) return;
      html += `<div class="grp">${title}</div>`;
      for (const x of list) {
        const i = items.length;
        items.push({ kind, value: x });
        const text = kind === "title" ? x.title : x;
        html += `<div class="opt" role="option" id="opt-${i}" data-i="${i}" aria-selected="false">${svg(icon)}<span class="t">${kind === "title" ? esc(text) : bold(text)}</span>${kind === "title" ? '<span class="k">open document</span>' : ""}</div>`;
      }
    };
    if (r.correction) group("Did you mean", [r.correction], "spark", "q");
    group("Your recent searches", r.history || [], "clock", "q");
    group("Suggestions", r.completions || [], "lens", "q");
    group("Popular searches", r.popular || [], "trend", "q");
    group("Documents", r.titles || [], "doc", "title");
    if ((r.related || []).length) {
      html += `<div class="grp">Related topics</div><div class="rel">${r.related.map((x) => { const i = items.length; items.push({ kind: "q", value: x }); return `<button type="button" class="chip" data-i="${i}">${esc(x)}</button>`; }).join("")}</div>`;
    }
    if (!items.length) return close();
    html += `<div class="foot">Suggestions come from this collection's index${(r.history || []).length ? " and your own search history" : ""}.</div>`;
    box.innerHTML = html;
    box.hidden = false;
    input.setAttribute("aria-expanded", "true");
  };
  const pick = (i) => {
    const it = items[i];
    close();
    if (!it) return;
    if (it.kind === "title") { go(`doc/${S.c}/${encodeURIComponent(it.value.id)}`, { q: input.value.trim() }); return; }
    input.value = it.value;
    onSubmit(it.value);
  };
  const highlight = () => $$("[data-i]", box).forEach((el) => { const on = +el.dataset.i === sel; el.setAttribute("aria-selected", on); if (on) { input.setAttribute("aria-activedescendant", el.id || ""); el.scrollIntoView({ block: "nearest" }); } });
  const fetchSuggest = () => {
    const v = input.value;
    const key = S.c + "|" + v;
    if (cache.has(key)) return render(cache.get(key));
    const my = ++seq;
    api(`/api/suggest?${qs({ c: S.c, q: v })}`).then((r) => { cache.set(key, r); if (my === seq && document.activeElement === input) render(r); }).catch(close);
  };
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(fetchSuggest, 110); });
  input.addEventListener("focus", () => { if (!input.value.trim()) fetchSuggest(); });
  input.addEventListener("keydown", (e) => {
    if (box.hidden) return;
    if (e.key === "ArrowDown") { sel = Math.min(sel + 1, items.length - 1); highlight(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(sel - 1, -1); highlight(); e.preventDefault(); }
    else if (e.key === "Enter" && sel >= 0) { e.preventDefault(); pick(sel); }
    else if (e.key === "Escape") close();
  });
  input.addEventListener("blur", () => setTimeout(close, 150));
  box.addEventListener("mousedown", (e) => { const el = e.target.closest("[data-i]"); if (el) { e.preventDefault(); pick(+el.dataset.i); } });
  form.addEventListener("submit", (e) => { e.preventDefault(); close(); const v = input.value.trim(); if (v) onSubmit(v); });
  return w;
}

/* ------------------------------------------------------------------ routing */
function parse() {
  const h = location.hash.slice(2) || "";
  const [path, query] = h.split("?");
  return { parts: path.split("/").filter(Boolean).map(decodeURIComponent), params: Object.fromEntries(new URLSearchParams(query || "")) };
}
const go = (path, params = {}) => { const s = qs(params); location.hash = `#/${path}${s ? "?" + s : ""}`; };
async function route() {
  flushDwell();
  const { parts, params } = parse();
  const name = parts[0] || "";
  $$(".links a").forEach((a) => a.classList.toggle("active", a.dataset.r === name));
  if (!S.info) {
    try { await loadInfo(); } catch (e) { $("#main").innerHTML = `<div class="wrap page"><p class="error">Cannot reach the SearchBridge server: ${esc(e.message)}</p></div>`; return; }
  }
  if (params.c && coll(params.c)) setCollection(params.c);
  const nav = $("#nav");
  const showNavSearch = ["search", "doc", "memory", "library", "insights"].includes(name);
  nav.classList.toggle("has-search", showNavSearch && name !== "search");
  $("#nav-search").innerHTML = "";
  if (showNavSearch && name !== "search") $("#nav-search").appendChild(searchBox({ compact: true, onSubmit: (q) => go("search", { q, c: S.c }) }));
  const page = { "": pageHome, search: pageSearch, doc: pageDoc, memory: pageMemory, insights: pageInsights, library: pageLibrary }[name] || pageHome;
  try { await page(params, parts); } catch (e) { $("#main").innerHTML = `<div class="wrap page"><p class="error">${esc(e.message)}</p></div>`; }
  if (!params.keep) window.scrollTo({ top: 0 });
}
window.addEventListener("hashchange", route);
window.addEventListener("scroll", () => $("#nav").classList.toggle("solid", scrollY > 4), { passive: true });

/* ------------------------------------------------------------------ HOME */
const ART = {
  memory: `<svg viewBox="0 0 220 170"><rect x="40" y="30" width="62" height="110" rx="10" fill="#fff"/><path d="M52 52h38M52 64h30M52 76h36"/>
    <circle cx="150" cy="58" r="16" fill="#fff"/><path d="M144 58l4 4 8-8"/><path d="M102 64c18 0 22-6 32-6"/><circle cx="168" cy="110" r="10" fill="#F6C343" stroke="none"/>
    <path d="M118 150c0-18 8-28 22-28s22 10 22 28"/><circle cx="140" cy="104" r="11" fill="#fff"/><path d="M62 150h96"/><path d="M60 100l10 10 22-22" stroke="#2E4BE6"/></svg>`,
  explain: `<svg viewBox="0 0 220 170"><rect x="34" y="26" width="120" height="96" rx="12" fill="#fff"/><path d="M50 50h60" /><rect x="50" y="62" width="70" height="8" rx="4" fill="#C7F0DE"/>
    <rect x="50" y="78" width="46" height="8" rx="4" fill="#DCE3FF"/><rect x="50" y="94" width="28" height="8" rx="4" fill="#FFE7A6"/><circle cx="160" cy="112" r="24" fill="#fff"/><path d="M177 129l18 18"/>
    <path d="M150 112h20M160 102v20" stroke="#2E4BE6"/><path d="M40 150h130"/></svg>`,
  related: `<svg viewBox="0 0 220 170"><rect x="24" y="40" width="54" height="68" rx="8" fill="#fff"/><rect x="142" y="22" width="54" height="68" rx="8" fill="#fff"/><rect x="132" y="104" width="54" height="52" rx="8" fill="#fff"/>
    <path d="M36 58h30M36 70h22M154 40h30M154 52h22M144 120h30"/><path d="M78 74c30 0 34-22 64-22" stroke-dasharray="4 4"/><path d="M78 86c26 0 30 34 54 34" stroke-dasharray="4 4"/>
    <circle cx="104" cy="66" r="5" fill="#F6C343" stroke="none"/><circle cx="108" cy="104" r="5" fill="#22A06B" stroke="none"/><path d="M30 156h70"/></svg>`,
};
async function pageHome() {
  const c = coll();
  const st = (c && c.stats) || {};
  const ex = (c && c.examples) || [];
  const bubbles = [["book", 92, "8%", "54%", "var(--lav)"], ["net", 70, "13%", "14%", "var(--mint)"], ["atom", 58, "4%", "84%", "var(--cream)"],
    ["chip", 84, "81%", "8%", "var(--blue-soft)"], ["globe", 64, "88%", "50%", "#FDE8EC"], ["doc", 74, "86%", "66%", "var(--mint)"]];
  const dots = [["16%", "40%", 12, "var(--green)"], ["70%", "86%", 18, "var(--yellow)"], ["93%", "28%", 11, "var(--blue)"], ["24%", "84%", 9, "var(--pink)"]];
  const others = S.info.collections;
  $("#main").innerHTML = `
  <section class="hero"><div class="hero-bg"></div>
    ${bubbles.map(([ic, s, x, y, bg], i) => `<div class="bubble float" style="width:${s}px;height:${s}px;left:${x};top:${y};background:${bg};animation-delay:${i * .7}s" aria-hidden="true">${svg(ic)}</div>`).join("")}
    ${dots.map(([x, y, s, c_]) => `<span class="dot" style="left:${x};top:${y};width:${s}px;height:${s}px;background:${c_}" aria-hidden="true"></span>`).join("")}
    <div class="wrap">
      <h1>Find the documents that answer your question</h1>
      <p class="lede">Search in your own words. SearchBridge understands related terms, explains every result and learns which documents you find useful.</p>
      <div id="hero-search"></div>
      <div id="hero-coll"></div>
      ${ex.length ? `<div class="try">${ex.slice(0, 4).map((x) => `<button class="chip" data-q="${esc(x)}">${esc(x)}</button>`).join("")}</div>` : ""}
    </div>
  </section>

  <section class="section"><div class="wrap split">
    <div><h2>One search engine for every collection</h2>
      <p>Research papers, a classic benchmark, pages you crawl from the web and your own PDFs. Each collection gets its own index, link graph, topics and suggestions.</p>
      ${st.documents ? `<div class="stats">
        <div><b>${fmt(st.documents)}</b><span>documents</span></div><div><b>${fmt(st.vocabulary)}</b><span>dictionary terms</span></div><div><b>${st.topics}</b><span>topics</span></div></div>` : ""}
    </div>
    <div class="orbit" aria-label="Collections">
      <div class="ring"></div><div class="ring inner"></div>
      <div class="center"><svg viewBox="0 0 32 32"><rect x="4" y="4" width="9" height="14" rx="4.5" fill="#2E4BE6"/><rect x="4" y="20" width="9" height="8" rx="4" fill="#F6C343"/><rect x="16" y="4" width="9" height="9" rx="4.5" fill="#2E4BE6"/></svg></div>
      ${others.map((o, i) => { const a = -Math.PI / 2 + i * 2 * Math.PI / others.length; const [ic, bg] = COLL_STYLE[o.id] || ["doc", "var(--canvas)"];
        return `<a class="node" href="#/search?c=${o.id}" style="left:${50 + 50 * Math.cos(a)}%;top:${50 + 50 * Math.sin(a)}%" data-c="${o.id}"><div class="ic" style="background:${bg}">${svg(ic)}</div><span>${esc(o.name.replace(/ \(benchmark\)/, ""))}</span><small>${o.stats ? fmt(o.stats.documents) + " docs" : o.status === "missing" ? "not added yet" : o.status === "empty" ? "empty" : "indexing"}</small></a>`; }).join("")}
    </div></div></section>

  <section class="section" style="padding-top:20px"><div class="wrap">
    <div class="center-head"><h2>A search engine that learns what helps you</h2><p>Simple on the surface. Every ranking decision can be opened and inspected.</p></div>
    <div class="cards3">
      <a class="pcard lav" href="#/memory"><h3>Remembers what you found useful</h3><p>Documents you read, return to and explore from are ranked higher in related searches. Quick clicks you abandon are not.</p><div class="art">${ART.memory}</div></a>
      <a class="pcard mint" href="#/insights/ranking"><h3>Explains every result</h3><p>See how keyword matches, meaning, link authority and your own history each placed a document where it is.</p><div class="art">${ART.explain}</div></a>
      <a class="pcard cream" href="#/insights/topics"><h3>Finds related work</h3><p>Discover documents about the same idea in different words, grouped into topics and connected by citations and links.</p><div class="art">${ART.related}</div></a>
    </div></div></section>`;
  $("#hero-search").appendChild(searchBox({ onSubmit: (q) => go("search", { q, c: S.c }), placeholder: ex[0] ? `Try "${ex[0]}"` : "Search documents, topics or questions" }));
  $("#hero-coll").appendChild(collectionPicker(() => pageHome()));
  $$(".try .chip").forEach((b) => b.addEventListener("click", () => go("search", { q: b.dataset.q, c: S.c })));
  $$(".orbit .node").forEach((a) => a.addEventListener("click", (e) => { const o = coll(a.dataset.c); if (o.status === "missing") { e.preventDefault(); go("library"); } else setCollection(a.dataset.c); }));
}

/* ------------------------------------------------------------------ SEARCH */
const SIG = { relevance: ["Relevance to your query", "#2E4BE6"], pagerank: ["Link authority (PageRank)", "#22A06B"], hits: ["Hub/authority (HITS)", "#7FD1AE"],
  context: ["Your previous search", "#9AA0B1"], personal: ["Your search memory", "#F6C343"] };
async function pageSearch(params) {
  const q = params.q || "";
  const filters = { topic: params.topic || "", category: params.category || "", type: params.type || "", tag: params.tag || "" };
  $("#main").innerHTML = `<div class="wrap page">
    <div style="max-width:760px;margin-left:260px" class="search-top" id="stop"></div>
    <div class="layout" style="margin-top:24px"><aside class="side" id="side"></aside><section id="res" aria-live="polite">${'<div class="skel"></div>'.repeat(3)}</section></div></div>`;
  const top = $("#stop");
  top.appendChild(searchBox({ q, onSubmit: (nq) => { sessionStorage.setItem("sb.prev", q); go("search", { q: nq, c: S.c }); } }));
  top.appendChild(collectionPicker(() => go("search", { q, c: S.c })));
  if (innerWidth < 960) top.style.marginLeft = "0";
  if (!q && !Object.values(filters).some(Boolean)) { $("#res").innerHTML = `<div class="empty"><h3>Search ${esc(coll().name)}</h3><p>Type a question, a topic or a few keywords.</p></div>`; return; }
  const mode = params.mode || "smart";
  const personalize = params.personal !== "off";
  const prev = sessionStorage.getItem("sb.prev") || "";
<<<<<<< HEAD
  let r;
  try { r = await api(`/api/search?${qs({ c: S.c, q, mode, k: 10, offset: 0, ...filters, personalize, context: prev !== q ? prev : "" })}`); }
=======
  const spell = params.spell !== "false";
  let r;
  try { r = await api(`/api/search?${qs({ c: S.c, q, mode, k: 10, offset: 0, ...filters, personalize, spell, context: prev !== q ? prev : "" })}`); }
>>>>>>> 1d6f999a29f64cc4785f3e1f1baa07f014efb4c0
  catch (e) {
    $("#res").innerHTML = e.status === 503 ? `<p class="loading">${esc(e.message)}. Results will appear when indexing finishes.</p>` : `<p class="error">${esc(e.message)}</p>`;
    if (e.status === 503) setTimeout(route, 3000);
    return;
  }
<<<<<<< HEAD
  S.results = { r, q, params, hits: r.hits, offset: r.hits.length, filters, mode, personalize };
=======
  S.results = { r, q, params, hits: r.hits, offset: r.hits.length, filters, mode, personalize, spell };
>>>>>>> 1d6f999a29f64cc4785f3e1f1baa07f014efb4c0
  renderSide(r, params);
  renderResults();
}
function renderSide(r, params) {
  const f = r.facets || {};
  const opt = (key, val, n) => `<button class="opt ${params[key] === val ? "on" : ""}" data-k="${key}" data-v="${esc(val)}"><span>${esc(val)}</span><span class="n">${n}</span></button>`;
  const grp = (title, key, list) => list && list.length > 1 ? `<div class="grp"><h4>${title}</h4>${list.slice(0, 8).map(([v, n]) => opt(key, v, n)).join("")}</div>` : "";
  const active = ["topic", "category", "type", "tag"].filter((k) => params[k]);
  $("#side").innerHTML = `${active.length ? `<div class="grp"><button class="btn btn-ghost btn-sm" data-clear>Clear filters</button></div>` : ""}
    ${grp("Topic", "topic", f.topic)}${grp("Category", "category", f.category)}${grp("Type", "type", f.type)}${grp("Keyphrase", "tag", f.tag)}
    <div class="grp"><details ${params.mode && params.mode !== "smart" ? "open" : ""}><summary>Ranking method</summary>
      <select id="mode" style="margin-top:8px" aria-label="Ranking method">${S.info.modes.map((m) => `<option value="${m.id}" ${m.id === (params.mode || "smart") ? "selected" : ""} title="${esc(m.description)}">${esc(m.name)}</option>`).join("")}</select>
      <p class="tiny muted" style="margin-top:6px">Smart is the default. Others are here to compare; <a href="#/insights/ranking?q=${encodeURIComponent(params.q || "")}">see them side by side</a>.</p></details></div>`;
  $("#side").onclick = (e) => {
    const b = e.target.closest("[data-k],[data-clear]");
    if (!b) return;
    if (b.dataset.clear !== undefined) return go("search", { q: params.q, c: S.c, mode: params.mode });
    go("search", { ...params, [b.dataset.k]: params[b.dataset.k] === b.dataset.v ? "" : b.dataset.v });
  };
  $("#mode").addEventListener("change", (e) => go("search", { ...params, mode: e.target.value === "smart" ? "" : e.target.value }));
}
function resultCard(h, i) {
  const st = COLL_STYLE[S.c] || ["doc", "var(--canvas)"];
  const m = h.meta || {};
  const src = [m.type, h.category, m.venue && m.venue !== h.category ? m.venue : "", m.year, m.author ? m.author.split(/[;,]/)[0] + (m.author.split(/[;,]/).length > 1 ? " et al." : "") : ""].filter(Boolean);
  const fb = S.results.fb && S.results.fb[h.doc_id];
  return `<article class="result" data-i="${i}" data-id="${esc(h.doc_id)}">
    <div class="src"><span class="ic" style="background:${st[1]}">${svg(st[0])}</span>${src.map(esc).join(" · ")}${h.topic && h.topic !== "All documents" ? ` · <span>${esc(h.topic)}</span>` : ""}</div>
    <h3><a href="#/doc/${S.c}/${encodeURIComponent(h.doc_id)}?q=${encodeURIComponent(S.results.q)}" data-open>${esc(h.title)}</a></h3>
    <div class="snip">${h.snippet_html}</div>
    ${h.missing && h.missing.length ? `<div class="tiny muted" style="margin-top:4px">Missing: <s>${h.missing.map(esc).join("</s> <s>")}</s></div>` : ""}
    <div class="meta">${h.personal.length ? `<span class="pbadge" title="${esc(h.personal.join(". "))}">${svg("memory")}${esc(h.personal[0])}</span>` : ""}
      ${h.tags.slice(0, 4).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>
    ${h.duplicates.length ? `<div class="dups">Also in the collection as a near-identical copy: ${h.duplicates.map((d) => `<a href="#/doc/${S.c}/${encodeURIComponent(d.id)}">${esc(d.title)}</a>`).join(", ")}</div>` : ""}
    <div class="actions">
      <button class="ibtn" data-why aria-expanded="false">${svg("bars")}Why this result</button>
      <span class="sp"></span>
      <button class="ibtn ${fb === 1 ? "on-up" : ""}" data-fb="1" aria-pressed="${fb === 1}" title="Relevant">${svg("up")}<span class="sr">Relevant</span></button>
      <button class="ibtn ${fb === -1 ? "on-down" : ""}" data-fb="-1" aria-pressed="${fb === -1}" title="Not relevant">${svg("down")}<span class="sr">Not relevant</span></button>
    </div><div class="slot"></div></article>`;
}
function whyPanel(h) {
  const b = h.breakdown || {};
  const rows = Object.keys(SIG).filter((k) => k in b && (k === "relevance" || Math.abs(b[k]) > 0.0005));
  const scale = Math.max(1, ...rows.map((k) => Math.abs(b[k])));
  const terms = (h.explanation || []).filter((t) => t[3] > 0);
  const sig = h.signal || {};
  return `<div class="why">
    ${rows.length ? rows.map((k) => `<div class="row"><span>${SIG[k][0]}</span><span class="bar"><i style="width:${Math.min(100, Math.abs(b[k]) / scale * 100)}%;background:${b[k] < 0 ? "var(--red)" : SIG[k][1]}"></i></span><span class="v">${b[k] >= 0 ? "+" : ""}${b[k].toFixed(3)}</span></div>`).join("")
      + `<p class="tiny muted" style="margin-top:6px">Relevance is the Bridge-PRF score (BM25 keywords + semantic similarity, with feedback expansion), scaled 0–1 within this result set. The other signals are small, bounded additions.</p>`
      : `<p class="small">Score ${h.score} with ${esc(S.results.r.mode_name)}.</p>`}
    ${sig.terms ? `<p class="terms">${sig.matched} of ${sig.terms} query terms appear in the text. Evidence split: ${Math.round((sig.lexical || 0) * 100)}% word match, ${Math.round((sig.semantic || 0) * 100)}% meaning.</p>` : ""}
    ${terms.length ? `<p class="terms">BM25 contributions: ${terms.slice(0, 6).map(([t, tf, idf, c]) => `<b>${esc(t)}</b> ${c.toFixed(2)} <span class="muted">(tf ${tf}, idf ${idf})</span>`).join(", ")}</p>` : ""}
    ${h.personal.length ? `<p class="terms">From your history: ${h.personal.map(esc).join("; ")}.</p>` : ""}</div>`;
}
function renderResults() {
  const { r, q, params, hits } = S.results;
  const notes = [];
  if (r.corrected_query) notes.push(`<div class="note"><span>Showing results for <b>${esc(r.corrected_query)}</b>.</span><button class="link" data-orig>Search for “${esc(q)}” instead</button></div>`);
  if (r.notice) notes.push(`<div class="note"><span>${esc(r.notice)}</span></div>`);
  const cv = r.coverage || {};
<<<<<<< HEAD
  if (cv.terms && cv.terms.length > 1 && (cv.all === 0 || cv.top_partial)) {
    const words = cv.terms.map((t) => `<b>${esc(t)}</b>`).join(" and ");
    notes.push(`<div class="note yellow"><span>${cv.all === 0 ? `No document in ${esc(coll().name)} contains all of ${words}.` : `Only ${cv.all} document${cv.all > 1 ? "s" : ""} in ${esc(coll().name)} contain${cv.all > 1 ? "" : "s"} all of ${words}, and ${cv.all > 1 ? "they mention" : "it mentions"} them only in passing.`} These are the closest matches; each shows which of your words it is missing.</span>
      ${cv.all ? `<button class="link" data-allwords>Show only documents with all words</button>` : ""}${S.info.collections.filter((c) => c.status === "ready" && c.id !== S.c).length ? `<button class="link" data-othercoll>Search another collection</button>` : ""}</div>`);
  } else if (cv.any === 0) notes.push(`<div class="note yellow"><span>None of your words appear in ${esc(coll().name)}; these results are matched by meaning only.</span></div>`);
=======
  if (hits.length && cv.terms && cv.terms.length > 1 && (cv.all === 0 || cv.top_partial)) {
    const words = cv.terms.map((t) => `<b>${esc(t)}</b>`).join(" and ");
    notes.push(`<div class="note yellow"><span>${cv.all === 0 ? `No document in ${esc(coll().name)} contains all of ${words}.` : `Only ${cv.all} document${cv.all > 1 ? "s" : ""} in ${esc(coll().name)} contain${cv.all > 1 ? "" : "s"} all of ${words}, and ${cv.all > 1 ? "they mention" : "it mentions"} them only in passing.`} These are the closest matches; each shows which of your words it is missing.</span>
      ${cv.all ? `<button class="link" data-allwords>Show only documents with all words</button>` : ""}${S.info.collections.filter((c) => c.status === "ready" && c.id !== S.c).length ? `<button class="link" data-othercoll>Search another collection</button>` : ""}</div>`);
  } else if (hits.length && cv.any === 0) notes.push(`<div class="note yellow"><span>None of your words appear in ${esc(coll().name)}; these results are matched by meaning only.</span></div>`);
>>>>>>> 1d6f999a29f64cc4785f3e1f1baa07f014efb4c0
  if (r.personalized) notes.push(`<div class="note yellow">${svg("memory", 'width="16" height="16" style="stroke:#7A5A00;fill:none;stroke-width:2"')}<span>${r.personalized} result${r.personalized > 1 ? "s were" : " was"} moved by your search memory.</span><button class="link" data-personal="off">Show without it</button></div>`);
  else if (params.personal === "off") notes.push(`<div class="note"><span>Search memory is off for this search.</span><button class="link" data-personal="on">Turn it back on</button></div>`);
  if (r.context_used) notes.push(`<div class="note"><span>Using your previous search “${esc(r.context_used)}” as context.</span></div>`);
  if (r.intent && !params.category) notes.push(`<div class="note blue"><span>This looks like a <b>${esc(r.intent[0])}</b> question.</span><button class="link" data-cat="${esc(r.intent[0])}">Show only ${esc(r.intent[0])}</button></div>`);
  const groups = (r.clusters || []).filter((g) => g.docs.length > 1);
  $("#res").innerHTML = `<div class="summary"><span class="count">${fmt(r.total_matches)} document${r.total_matches === 1 ? "" : "s"} ${r.mode === "boolean" ? "match" : "contain your words"} · ${r.took_ms} ms${r.collapsed ? ` · ${r.collapsed} near-duplicate${r.collapsed > 1 ? "s" : ""} folded` : ""}</span>
</div>
    ${notes.join("")}
    ${groups.length > 1 ? `<div class="groups"><span class="lbl">Topics in these results</span><button class="chip on" data-g="-1">All</button>${groups.map((g, i) => `<button class="chip" data-g="${i}">${esc(g.label.join(" · "))} <span class="muted">${g.docs.length}</span></button>`).join("")}</div>` : ""}
    <div id="list">${hits.length ? hits.map(resultCard).join("") : `<div class="empty"><h3>No documents match</h3><p>Try fewer or different words${Object.values(S.results.filters).some(Boolean) ? ", or clear the filters" : ""}.</p></div>`}</div>
    ${r.total_matches > hits.length && hits.length >= 10 ? `<div class="more"><button class="btn btn-ghost" data-more>Show more results</button></div>` : ""}
    <div class="fbbar" id="fbbar"></div>
    ${(r.related_concepts || []).length ? `<div class="related"><span class="lbl">Related searches</span>${r.related_concepts.slice(0, 6).map(([t]) => `<button class="chip" data-q="${esc(t)}">${esc(t)}</button>`).join("")}</div>` : ""}`;
  updateFbBar();
  $("#res").onclick = onResultsClick;
}
function updateFbBar() {
  const fb = S.results.fb || {};
  const up = Object.keys(fb).filter((k) => fb[k] === 1), down = Object.keys(fb).filter((k) => fb[k] === -1);
  $("#fbbar").innerHTML = up.length ? `<div class="note blue" style="margin-top:14px"><span>You marked ${up.length} relevant${down.length ? ` and ${down.length} not relevant` : ""}.</span><button class="link" data-refine>Refine these results with your feedback</button></div>` : "";
}
async function onResultsClick(e) {
  const t = e.target.closest("button, a");
  if (!t) return;
  const { r, q, params } = S.results;
  const card = t.closest(".result");
  if (t.dataset.open !== undefined) {
    const h = S.results.hits[+card.dataset.i];
    sessionStorage.setItem("sb.from", JSON.stringify({ q, rank: +card.dataset.i + 1, id: h.doc_id }));
    return;
  }
<<<<<<< HEAD
  if (t.dataset.orig !== undefined) return api(`/api/search?${qs({ c: S.c, q, spell: false, k: 10 })}`).then((x) => { S.results.r = x; S.results.hits = x.hits; renderResults(); });
=======
  if (t.dataset.orig !== undefined) return go("search", { ...params, spell: false });
>>>>>>> 1d6f999a29f64cc4785f3e1f1baa07f014efb4c0
  if (t.dataset.personal) return go("search", { ...params, personal: t.dataset.personal === "off" ? "off" : "" });
  if (t.dataset.cat) return go("search", { ...params, category: t.dataset.cat });
  if (t.dataset.allwords !== undefined) return go("search", { q: (r.coverage.terms || []).join(" AND "), c: S.c, mode: "boolean" });
  if (t.dataset.othercoll !== undefined) { const sel = $(".collection-pick select"); if (sel) { sel.focus(); sel.showPicker && sel.showPicker(); } return; }
  if (t.dataset.q) { sessionStorage.setItem("sb.prev", q); return go("search", { q: t.dataset.q, c: S.c }); }
  if (t.dataset.g !== undefined) {
    $$("[data-g]").forEach((b) => b.classList.toggle("on", b === t));
    const ids = +t.dataset.g < 0 ? null : new Set(r.clusters.filter((g) => g.docs.length > 1)[+t.dataset.g].docs);
    $$(".result").forEach((el) => { el.hidden = ids && !ids.has(el.dataset.id); });
    return;
  }
  if (t.dataset.why !== undefined) {
    const open = t.getAttribute("aria-expanded") === "true";
    t.setAttribute("aria-expanded", String(!open));
    $(".slot", card).innerHTML = open ? "" : whyPanel(S.results.hits[+card.dataset.i]);
    return;
  }
  if (t.dataset.fb) {
    const id = card.dataset.id, v = +t.dataset.fb;
    S.results.fb = S.results.fb || {};
    const now = S.results.fb[id] === v ? 0 : v;
    S.results.fb[id] = now;
    $$("[data-fb]", card).forEach((b) => { b.classList.toggle("on-up", +b.dataset.fb === 1 && now === 1); b.classList.toggle("on-down", +b.dataset.fb === -1 && now === -1); b.setAttribute("aria-pressed", +b.dataset.fb === now); });
    event("feedback", { doc: id, q, value: now, rank: +card.dataset.i + 1 });
    if (now) toast(now > 0 ? "Noted. Similar searches will rank this higher." : "Noted. It will be ranked lower for you.");
    updateFbBar();
    return;
  }
  if (t.dataset.refine !== undefined) {
    const fb = S.results.fb;
    const rel = Object.keys(fb).filter((k) => fb[k] === 1), non = Object.keys(fb).filter((k) => fb[k] === -1);
    const hits = await post("/api/feedback", { c: S.c, q, relevant: rel, nonrelevant: non, k: 10 });
    S.results.hits = hits.map((h) => ({ ...h, breakdown: {}, personal: h.personal || [], duplicates: h.duplicates || [] }));
    S.results.r = { ...r, clusters: [], mode_name: "Rocchio relevance feedback", personalized: 0 };
    renderResults();
    $("#res").insertAdjacentHTML("afterbegin", `<div class="note blue">Re-ranked with Rocchio relevance feedback: the query moved toward the ${rel.length} document${rel.length > 1 ? "s" : ""} you marked relevant${non.length ? " and away from the others" : ""}.</div>`);
    return;
  }
  if (t.dataset.more !== undefined) {
    t.disabled = true;
<<<<<<< HEAD
    const x = await api(`/api/search?${qs({ c: S.c, q, mode: S.results.mode, k: 10, offset: S.results.offset, ...S.results.filters, personalize: S.results.personalize, log: false })}`);
=======
    const x = await api(`/api/search?${qs({ c: S.c, q, mode: S.results.mode, k: 10, offset: S.results.offset, ...S.results.filters, personalize: S.results.personalize, spell: S.results.spell, log: false })}`);
>>>>>>> 1d6f999a29f64cc4785f3e1f1baa07f014efb4c0
    const start = S.results.hits.length;
    S.results.hits.push(...x.hits);
    S.results.offset += x.hits.length;
    $("#list").insertAdjacentHTML("beforeend", x.hits.map((h, i) => resultCard(h, start + i)).join(""));
    if (!x.hits.length || S.results.offset >= r.total_matches) t.parentElement.remove(); else t.disabled = false;
  }
}

/* ------------------------------------------------------------------ DOCUMENT */
function flushDwell() {
  if (!S.dwell) return;
  const d = S.dwell;
  S.dwell = null;
  const secs = (d.visible + (document.visibilityState === "visible" ? Date.now() - d.since : 0)) / 1000;
  if (secs < 1) return;
  const body = JSON.stringify({ c: d.c, kind: "dwell", doc: d.id, q: d.q, value: Math.round(secs) });
  if (navigator.sendBeacon) navigator.sendBeacon("/api/events", new Blob([body], { type: "application/json" }));
  else fetch("/api/events", { method: "POST", body, headers: { "Content-Type": "application/json" }, keepalive: true });
}
document.addEventListener("visibilitychange", () => {
  if (!S.dwell) return;
  if (document.visibilityState === "hidden") { S.dwell.visible += Date.now() - S.dwell.since; flushDwell(); }
});
window.addEventListener("pagehide", flushDwell);

async function pageDoc(params, parts) {
  const c = parts[1], id = parts[2];
  if (c && coll(c)) setCollection(c);
  $("#main").innerHTML = `<div class="wrap page"><p class="loading">Opening document</p></div>`;
  const q = params.q || "";
  const [d, rel] = await Promise.all([api(`/api/doc?${qs({ c: S.c, id, q })}`), api(`/api/related?${qs({ c: S.c, id, k: 6 })}`).catch(() => [])]);
  // record how the document was reached: from a result list, from a link inside another document, or directly
  let from = null;
  try { from = JSON.parse(sessionStorage.getItem("sb.from") || "null"); } catch { /* ignore */ }
  sessionStorage.removeItem("sb.from");
  if (from && from.link) event("link", { doc: from.link, to_doc: id, q: from.q || "" });
  event("open", { doc: id, q: from && from.id === id ? from.q : q, rank: from && from.rank ? from.rank : 0, source: from ? (from.link ? "link" : from.related ? "related" : "results") : "direct" });
  S.dwell = { c: S.c, id, q: from && from.q ? from.q : q, since: Date.now(), visible: 0 };
  const m = d.meta || {};
  const plain = d.html.replace(/<[^>]+>/g, "").slice(0, 1500);
  const abstract = m.abstract && m.abstract.length > 80 && !plain.includes(m.abstract.slice(0, 60)) ? m.abstract : "";
  const linkList = (title, list, note) => list.length ? `<div class="panel"><h3>${title}</h3>${note ? `<p class="tiny muted" style="margin:-4px 0 8px">${note}</p>` : ""}<ul>${list.map((x) => `<li><a href="#/doc/${S.c}/${encodeURIComponent(x.id)}?q=${encodeURIComponent(q)}" data-link="${esc(x.id)}">${esc(x.title)}</a></li>`).join("")}</ul></div>` : "";
  const web = d.link_kind === "hyperlinks";
  $("#main").innerHTML = `<div class="wrap page"><div class="doc-grid"><article class="doc">
      <a href="javascript:history.back()" class="small">← Back</a>
      <div class="src small muted" style="margin-top:14px">${[m.type, d.category + (d.category_predicted ? " (predicted)" : ""), m.venue, m.year, m.site].filter((x) => x && x.trim() && x !== " (predicted)").map(esc).join(" · ")}</div>
      <h1>${esc(d.title)}</h1>
      ${m.author ? `<p class="small muted">${esc(m.author)}</p>` : ""}
      ${m.source && /^https?:/.test(m.source) ? `<p class="small" style="margin-top:6px"><a href="${esc(m.source)}" target="_blank" rel="noopener">${esc(m.source)}</a></p>` : ""}
      <div class="meta" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:12px">${d.tags.slice(0, 10).map((t) => `<a class="chip" href="#/search?c=${S.c}&q=${encodeURIComponent(t)}">${esc(t)}</a>`).join("")}</div>
      ${abstract ? `<p class="abstract">${esc(abstract)}</p>` : ""}
      ${d.file_url ? `<p style="margin:14px 0"><a class="btn btn-ghost btn-sm" href="${d.file_url}" target="_blank" rel="noopener">Open original file</a></p>` : ""}
      <div class="body" style="margin-top:${abstract ? 0 : 20}px">${d.html}${d.truncated ? "\n\n…" : ""}</div>
    </article>
    <aside>
      ${linkList(web ? "Links on this page" : "References in this collection", d.cites, web ? "Pages in this collection that this page links to." : "")}
      ${linkList(web ? "Pages linking here" : "Cited by", d.cited_by)}
      ${rel.length ? `<div class="panel"><h3>Related documents</h3><ul>${rel.map((x) => `<li><a href="#/doc/${S.c}/${encodeURIComponent(x.id)}?q=${encodeURIComponent(q)}" data-related="${esc(x.id)}">${esc(x.title)}</a><small>${Object.entries(x.components).filter(([, v]) => v > 0.15).map(([k]) => k === "graph" ? "linked" : k === "entities" ? "shared concepts" : k === "lexical" ? "shared words" : "similar meaning").join(", ")}</small></li>`).join("")}</ul></div>` : ""}
      <div class="panel"><h3>About this document</h3><div class="kv"><span>Words</span><span>${fmt(d.words)}</span><span>Topic</span><span>${esc(d.topic)}</span>
        ${d.authority && d.authority.v3 !== undefined ? `<span>PageRank (V3)</span><span>${d.authority.v3.toExponential(2)}</span>` : ""}
        <span>Credibility</span><span>${d.credibility}</span>${d.duplicates.length ? `<span>Near-duplicates</span><span>${d.duplicates.length}</span>` : ""}</div></div>
    </aside></div></div>`;
  $("#main").addEventListener("click", (e) => {
    const a = e.target.closest("[data-link],[data-related]");
    if (!a) return;
    if (a.dataset.link) sessionStorage.setItem("sb.from", JSON.stringify({ link: id, q }));
    else sessionStorage.setItem("sb.from", JSON.stringify({ related: id, q }));
  });
}

/* ------------------------------------------------------------------ SEARCH MEMORY */
async function pageMemory() {
  const m = await api(`/api/me?${qs({ c: S.c })}`);
  const li = (x) => `<li><a href="#/doc/${S.c}/${encodeURIComponent(x.id)}">${esc(x.title)}</a><small><span class="aff"><i style="width:${Math.round(Math.abs(x.affinity) * 100)}%"></i></span>${x.reasons.map(esc).join(" · ") || "Read before"}</small></li>`;
  $("#main").innerHTML = `<div class="wrap page">
    <div class="mem-hero lav"><div><h1>Your search memory</h1>
      <p>SearchBridge remembers which documents in <b>${esc(coll().name)}</b> you read, return to, explore from and rate, and gently ranks them and similar documents higher when they match a new search. Older activity fades with a ${m.half_life_days}-day half-life. This history stays on this server, tied to this browser only.</p></div>
      <div style="display:grid;gap:10px;justify-items:end"><label class="switch"><input type="checkbox" id="pause" ${m.paused ? "" : "checked"}> Learn from my activity</label>
        <button class="btn btn-danger btn-sm" id="clear">Clear my history</button></div></div>
    ${m.events ? "" : `<div class="note">Nothing recorded yet for this collection. Search, open a few documents and come back.</div>`}
    <div class="mem-grid">
      <div class="panel"><h3>Documents you found useful</h3>${m.useful.length ? `<ul>${m.useful.map(li).join("")}</ul>` : `<p class="small muted">Documents you read for a while, revisit or mark relevant appear here.</p>`}</div>
      <div>
        <div class="panel"><h3>Your interests</h3>${m.interests.length ? m.interests.map((t) => `<a class="chip" style="margin:0 6px 6px 0" href="#/search?c=${S.c}&topic=${encodeURIComponent(t.topic)}">${esc(t.topic)}</a>`).join("") : `<p class="small muted">Topics of the documents you found useful.</p>`}</div>
        <div class="panel"><h3>Recent searches</h3>${m.recent_queries.length ? m.recent_queries.map((q) => `<a class="chip" style="margin:0 6px 6px 0" href="#/search?c=${S.c}&q=${encodeURIComponent(q)}">${esc(q)}</a>`).join("") : `<p class="small muted">None yet.</p>`}</div>
        <div class="panel"><h3>Links you followed</h3>${m.links.length ? `<ul>${m.links.map((l) => `<li><a href="#/doc/${S.c}/${encodeURIComponent(l.from_id)}">${esc(l.from)}</a><small>→ ${esc(l.to)}</small></li>`).join("")}</ul>` : `<p class="small muted">Citations and links you open from inside a document.</p>`}</div>
        ${m.not_useful.length ? `<div class="panel"><h3>Ranked lower for you</h3><ul>${m.not_useful.map(li).join("")}</ul></div>` : ""}
      </div></div></div>`;
  $("#pause").addEventListener("change", async (e) => { await post("/api/me/pause", { paused: !e.target.checked }); toast(e.target.checked ? "Learning from your activity" : "Paused. Nothing new will be recorded."); });
  $("#clear").addEventListener("click", async () => {
    if (!confirm("Delete your search history for every collection? This cannot be undone.")) return;
    const r = await api("/api/me/history", { method: "DELETE" });
    toast(`Deleted ${r.deleted} recorded interactions`);
    pageMemory();
  });
}

/* ------------------------------------------------------------------ charts */
function lineChart(series, { w = 560, h = 230, xlabel = "", ylabel = "", ymin = null, ymax = null } = {}) {
  const pts = series.flatMap((s) => s.points);
  const x0 = Math.min(...pts.map((p) => p[0])), x1 = Math.max(...pts.map((p) => p[0]));
  const y0 = ymin ?? Math.min(...pts.map((p) => p[1])), y1 = ymax ?? Math.max(...pts.map((p) => p[1]));
  const L = 46, B = 34, T = 8, R = 10;
  const X = (v) => L + (v - x0) / (x1 - x0 || 1) * (w - L - R), Y = (v) => h - B - (v - y0) / (y1 - y0 || 1) * (h - B - T);
  const tk = [0, .25, .5, .75, 1];
  return `<svg viewBox="0 0 ${w} ${h}" role="img"><g stroke="#E7E9F2">${tk.map((t) => `<line x1="${L}" x2="${w - R}" y1="${Y(y0 + t * (y1 - y0))}" y2="${Y(y0 + t * (y1 - y0))}"/>`).join("")}</g>
    ${tk.map((t) => `<text x="${L - 6}" y="${Y(y0 + t * (y1 - y0)) + 4}" text-anchor="end">${(y0 + t * (y1 - y0)).toFixed(2)}</text><text x="${X(x0 + t * (x1 - x0))}" y="${h - B + 15}" text-anchor="middle">${Math.round(x0 + t * (x1 - x0))}</text>`).join("")}
    <text x="${(L + w) / 2}" y="${h - 2}" text-anchor="middle">${esc(xlabel)}</text><text x="10" y="${(h - B) / 2}" transform="rotate(-90 10 ${(h - B) / 2})" text-anchor="middle">${esc(ylabel)}</text>
    ${series.map((s) => `<path d="${s.points.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("")}" fill="none" stroke="${s.color}" stroke-width="2.4" ${s.dash ? 'stroke-dasharray="5 4"' : ""}/>`).join("")}</svg>`;
}
function barChart(rows, { w = 560, bar = 18, max = null, label = 200, f = (v) => v.toFixed(3) } = {}) {
  const m = max ?? Math.max(...rows.map((r) => r[1]), 1e-9), h = rows.length * (bar + 10);
  return `<svg viewBox="0 0 ${w} ${h}" role="img">${rows.map(([l, v, c], i) => `<text x="${label - 8}" y="${i * (bar + 10) + bar / 2 + 4}" text-anchor="end" style="fill:var(--ink-2);font-size:12px">${esc(l)}</text>
    <rect x="${label}" y="${i * (bar + 10)}" width="${Math.max(2, v / m * (w - label - 64))}" height="${bar}" rx="5" fill="${c || "#2E4BE6"}"/><text x="${label + Math.max(2, v / m * (w - label - 64)) + 6}" y="${i * (bar + 10) + bar / 2 + 4}">${f(v)}</text>`).join("")}</svg>`;
}
const PAL = ["#2E4BE6", "#22A06B", "#F6C343", "#F28BA0", "#7FD1AE", "#9AA7F5", "#E58E3B", "#1E2230", "#B48EE6", "#5BC0EB", "#C2A15E", "#D9475A", "#6B7183", "#A3D977", "#3B8ED9", "#E07AC0"];

/* ------------------------------------------------------------------ INSIGHTS */
const TABS = [["ranking", "Ranking"], ["links", "Links & authority"], ["topics", "Topics & categories"], ["index", "Index"], ["evaluation", "Evaluation"], ["crawler", "Crawler & duplicates"]];
async function pageInsights(params, parts) {
  const tab = parts[1] || "ranking";
  $("#main").innerHTML = `<div class="wrap"><div class="page-head"><h1>Insights</h1><p>How SearchBridge finds and orders documents in <b>${esc(coll().name)}</b>. Every view runs on the live index.</p>
    <div id="ins-coll"></div></div>
    <nav class="tabs">${TABS.map(([k, l]) => `<a href="#/insights/${k}" class="${k === tab ? "on" : ""}">${l}</a>`).join("")}</nav><div id="ins" style="padding-bottom:70px"><p class="loading">Loading</p></div></div>`;
  $("#ins-coll").appendChild(collectionPicker(() => route()));
  const el = $("#ins");
  try { await ({ ranking: insRanking, links: insLinks, topics: insTopics, index: insIndex, evaluation: insEval, crawler: insCrawler }[tab] || insRanking)(el, params); }
  catch (e) { el.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}
async function insRanking(el, params) {
  const ex = (coll().examples || [])[0] || "information retrieval";
  const q = params.q || ex;
  const modes = (params.m || "boolean,bm25,dense,smart").split(",").slice(0, 4);
  el.innerHTML = `<p class="explain">A query goes through text pre-processing (tokenising, stop-word removal, Porter stemming, spelling correction with a k-gram index), candidate retrieval from the inverted index, scoring, and result assembly (filters, near-duplicate folding, snippets). Compare how four ranking methods order the same query; shared documents are highlighted.</p>
    <form class="form-row" id="rf"><label style="flex:1;min-width:240px">Query<input class="input" id="rq" value="${esc(q)}"></label>
      ${[0, 1, 2, 3].map((i) => `<label>Method ${i + 1}<select class="input" data-m>${S.info.modes.map((m) => `<option value="${m.id}" ${modes[i] === m.id ? "selected" : ""}>${esc(m.name)}</option>`).join("")}</select></label>`).join("")}
      <button class="btn btn-primary">Compare</button></form><div id="cmp" class="cmp"><p class="loading">Ranking</p></div>`;
  $("#rf").addEventListener("submit", (e) => { e.preventDefault(); go("insights/ranking", { q: $("#rq").value, m: $$("[data-m]").map((s) => s.value).join(",") }); });
  const runs = await Promise.all(modes.map((m) => api(`/api/search?${qs({ c: S.c, q, mode: m, k: 10, personalize: false, log: false, clusters: false })}`).catch((e) => ({ error: e.message, hits: [] }))));
  const count = {};
  runs.forEach((r) => r.hits.forEach((h) => { count[h.doc_id] = (count[h.doc_id] || 0) + 1; }));
  $("#cmp").style.gridTemplateColumns = `repeat(${runs.length}, minmax(0,1fr))`;
  $("#cmp").innerHTML = runs.map((r, i) => `<div class="panel"><h3>${esc(S.info.modes.find((m) => m.id === modes[i]).name)}</h3><p class="tiny muted" style="margin-bottom:8px">${r.error ? esc(r.error) : `${fmt(r.total_matches)} matches · ${r.took_ms} ms`}</p>
    <ol>${r.hits.map((h, j) => `<li class="${count[h.doc_id] > 1 ? "shared" : ""}"><span class="r">${j + 1}</span><a href="#/doc/${S.c}/${encodeURIComponent(h.doc_id)}?q=${encodeURIComponent(q)}">${esc(h.title)}</a></li>`).join("") || '<li class="muted"><span></span>No results</li>'}</ol></div>`).join("");
}
async function insLinks(el, params) {
  const r = await api(`/api/lab/links?${qs({ c: S.c })}`);
  if (!r.links) {
    el.innerHTML = `<div class="note">${esc(coll().name)} has no links between its documents, so PageRank and HITS have nothing to work with here and add nothing to its ranking. Link analysis is never computed on invented links. Try the <b>Web pages</b> collection (crawl a site on the <a href="#/library">Library</a> page) or the Research Papers collection, whose citations are real links.</div>`;
    return;
  }
  const C = { v1: "#D9475A", v2: "#F6C343", v3: "#2E4BE6" };
  const N = { v1: "V1 · simplified, no teleport", v2: "V2 · with teleportation", v3: "V3 · dead ends handled + teleport" };
  const V = r.versions;
  el.innerHTML = `<p class="explain">${fmt(r.documents)} documents, ${fmt(r.links)} real ${esc(r.kind)} (${fmt(r.linked_docs)} documents take part), ${fmt(r.dead_ends)} dead ends. V3 PageRank and query-time HITS authority are small additions to the Smart ranking.</p>
    <div class="grid2"><div class="panel"><h3>Total PageRank per iteration</h3><div class="chart">${lineChart(Object.entries(V).map(([k, v]) => ({ color: C[k], points: v.mass_curve.map((m, i) => [i * v.step, m]) })), { xlabel: "iteration", ylabel: "sum of scores", ymin: 0, ymax: 1.02 })}</div>
      <div class="legend">${Object.keys(V).map((k) => `<span><i style="background:${C[k]}"></i>${N[k]} · ${V[k].iterations} it. · total ${V[k].final_mass}</span>`).join("")}</div>
      <p class="small muted" style="margin-top:8px">V1 loses score through dead ends (documents that link nowhere). V2's random jumps stop rank getting trapped, but dead ends still leak. V3 hands dead-end score back to every page, so it stays a probability distribution.</p></div>
    <div class="panel"><h3>Do the versions agree?</h3><p class="small">Shared documents in the top 10: V1–V2 ${Math.round(r.top_overlap["v1-v2"] * 100)}%, V2–V3 ${Math.round(r.top_overlap["v2-v3"] * 100)}%, V1–V3 ${Math.round(r.top_overlap["v1-v3"] * 100)}%.</p>
      <h3 style="margin-top:16px">HITS for a query</h3><form class="form-row" id="hf"><input class="input" id="hq" style="flex:1" value="${esc(params.hq || (coll().examples || [""])[0])}"><button class="btn btn-ghost btn-sm">Run HITS</button></form><div id="hits"></div></div>
    <div class="panel wide"><h3>Top documents by version</h3><table class="t"><thead><tr><th>#</th>${Object.keys(V).map((k) => `<th>${N[k]}</th>`).join("")}</tr></thead><tbody>
      ${[...Array(8).keys()].map((i) => `<tr><td>${i + 1}</td>${Object.keys(V).map((k) => { const x = V[k].top[i]; return `<td>${x ? `<a href="#/doc/${S.c}/${encodeURIComponent(x.id)}">${esc(x.title.slice(0, 70))}</a><div class="tiny muted">${x.in_links} in-links · ${x.score.toExponential(2)}</div>` : ""}</td>`; }).join("")}</tr>`).join("")}</tbody></table></div></div>`;
  const runHits = async (q) => {
    if (!q) return;
    const h = await api(`/api/lab/hits?${qs({ c: S.c, q })}`);
    const list = (xs) => xs.length ? `<ul style="list-style:none;padding:0;margin:0">${xs.slice(0, 6).map((x) => `<li class="small" style="padding:4px 0"><a href="#/doc/${S.c}/${encodeURIComponent(x.id)}">${esc(x.title.slice(0, 64))}</a> <span class="muted">${x.score}</span></li>`).join("")}</ul>` : '<p class="small muted">None</p>';
    $("#hits").innerHTML = h.edges ? `<p class="tiny muted">Root set ${h.root} results, base set ${h.base} documents, ${h.edges} links.</p><div class="grid2" style="gap:12px"><div><h4 class="small">Authorities</h4>${list(h.authorities)}</div><div><h4 class="small">Hubs</h4>${list(h.hubs)}</div></div>`
      : `<p class="small muted">The results for this query have no links among them, so HITS has nothing to score.</p>`;
  };
  $("#hf").addEventListener("submit", (e) => { e.preventDefault(); runHits($("#hq").value); });
  runHits($("#hq").value);
}
async function insTopics(el) {
  const t = await api(`/api/lab/topics?${qs({ c: S.c })}`);
  const pts = t.points, xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  const W = 560, H = 360, x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = (v) => 10 + (v - x0) / (x1 - x0 || 1) * (W - 20), Y = (v) => 10 + (v - y0) / (y1 - y0 || 1) * (H - 20);
  let dendro = "";
  if (t.dendrogram) {
    const d = t.dendrogram, n = d.order.length, dh = n * 22 + 16, mx = Math.max(...d.dcoord.flat()) || 1;
    const DX = (v) => 250 + v / mx * 290, DY = (v) => v / 10 * 22 + 8;
    dendro = `<svg viewBox="0 0 560 ${dh}">${d.icoord.map((ic, i) => `<path d="M${DX(d.dcoord[i][0])},${DY(ic[0])}H${DX(d.dcoord[i][1])}V${DY(ic[2])}H${DX(d.dcoord[i][3])}" fill="none" stroke="#2E4BE6" stroke-width="1.6"/>`).join("")}
      ${d.order.map((l, i) => `<text x="242" y="${DY(5 + 10 * i) + 4}" text-anchor="end" style="font-size:11.5px;fill:var(--ink-2)">${esc(l.length > 36 ? l.slice(0, 35) + "…" : l)}</text>`).join("")}</svg>`;
  }
  const cat = t.categories.report;
  const best = cat ? Object.entries(cat.models).sort((a, b) => b[1].accuracy - a[1].accuracy)[0] : null;
  el.innerHTML = `<p class="explain">Flat clustering (spherical k-means on document embeddings) gives each collection its topics, which appear as the Topic filter and as groups inside every result list. Hierarchical clustering (average link, cosine) of the topic centroids shows how topics relate. Classifiers learn the labelled categories, suggest a category for a query and label documents only when confident.</p>
    <div class="grid2"><div class="panel"><h3>Documents by topic</h3><p class="tiny muted">${pts.length} documents projected on two principal components.</p>
      <div class="chart"><svg viewBox="0 0 ${W} ${H}" style="background:var(--canvas);border-radius:12px">${pts.map((p) => `<circle cx="${X(p.x).toFixed(1)}" cy="${Y(p.y).toFixed(1)}" r="3.2" fill="${PAL[p.t % PAL.length]}" opacity=".75"><title>${esc(p.title)}</title></circle>`).join("")}</svg></div>
      <div class="legend">${t.topics.map((x, i) => `<span><i style="background:${PAL[i % PAL.length]}"></i>${esc(x.label)} (${x.size})</span>`).join("")}</div></div>
    <div class="panel"><h3>How the topics relate</h3>${dendro ? `<div class="chart">${dendro}</div>` : '<p class="small muted">Too few topics for a hierarchy.</p>'}</div>
    <div class="panel wide"><h3>Category classifiers</h3>${cat ? `<p class="small muted">Trained on ${cat.train} labelled documents, tested on ${cat.test} held out. Majority-class baseline ${cat.majority_baseline}. ${t.categories.predicted} unlabelled documents were given a category because Naive Bayes and Rocchio agreed with high confidence; ${t.categories.uncategorised} stay uncategorised rather than being forced into a class.</p>
      <table class="t" style="margin-top:10px"><thead><tr><th>Model</th><th class="n">Accuracy</th><th class="n">Macro-F1</th></tr></thead><tbody>${Object.entries(cat.models).map(([n, m]) => `<tr class="${n === best[0] ? "hl" : ""}"><td>${esc(n)}</td><td class="n">${m.accuracy}</td><td class="n">${m.macro_F1}</td></tr>`).join("")}</tbody></table>
      <p class="small" style="margin:14px 0 6px"><b>Confusion matrix (${esc(best[0])})</b>, rows = true category</p>
      <table class="t" style="width:auto"><thead><tr><th></th>${cat.classes.map((c) => `<th class="n">${esc(c.split(" ")[0])}</th>`).join("")}</tr></thead><tbody>${best[1].confusion.map((row, i) => `<tr><td>${esc(cat.classes[i])}</td>${row.map((v, j) => `<td class="n" style="${i === j ? "font-weight:700;color:var(--blue)" : ""}">${v}</td>`).join("")}</tr>`).join("")}</tbody></table>`
      : `<p class="small muted">This collection has no topical category labels to learn from (for Cranfield the only labels are publication venues).</p>`}</div></div>`;
}
async function insIndex(el, params) {
  const term = params.term || ((coll().examples || [""])[0].split(" ")[0]) || "search";
  const [p, ins] = await Promise.all([api(`/api/postings?${qs({ c: S.c, term })}`), api(`/api/insights?${qs({ c: S.c })}`)]);
  el.innerHTML = `<div class="grid2"><div class="panel"><h3>Dictionary and postings</h3>
      <form class="form-row" id="tf"><input class="input" id="tt" style="flex:1" value="${esc(term)}" placeholder="term or wild*card"><button class="btn btn-ghost btn-sm">Look up</button></form>
      ${p.spelling && p.spelling.length && p.spelling[0][1] > 0 ? `<p class="small">Did you mean <a href="#/insights/index?term=${encodeURIComponent(p.spelling[0][0])}">${esc(p.spelling[0][0])}</a>? (k-gram index + edit distance)</p>` : ""}
      <div class="kv"><span>Index term after stemming</span><span>${esc(p.stem)}</span><span>Document frequency</span><span>${fmt(p.df)}</span><span>idf</span><span>${p.idf}</span>
        <span>Gaps (first 15)</span><span class="tiny">${p.gaps_preview.join(", ")}</span><span>Postings size</span><span>${fmt(p.raw_bytes)} B raw · ${fmt(p.vb_bytes)} B variable-byte · ${fmt(Math.ceil(p.gamma_bits / 8))} B γ-code</span>
        ${p.wildcard.length ? `<span>Wildcard matches</span><span class="tiny">${p.wildcard.map(esc).join(", ")}</span>` : ""}</div>
      <table class="t" style="margin-top:12px"><thead><tr><th>Document</th><th class="n">tf</th><th>Positions</th></tr></thead><tbody>${p.postings.slice(0, 8).map((x) => `<tr><td><a href="#/doc/${S.c}/${encodeURIComponent(x.doc)}">${esc(x.title)}</a></td><td class="n">${x.tf}</td><td class="tiny muted">${x.positions.join(", ")}</td></tr>`).join("")}</tbody></table></div>
    <div class="panel"><h3>Index size and compression</h3><div class="chart">${barChart(ins.compression.map((c) => [c.structure.replace("Postings, ", "").replace("Dictionary, ", "Dict: "), c.ratio * 100]), { f: (v) => v.toFixed(0) + "%", label: 240, max: 100 })}</div>
      <div class="kv" style="margin-top:12px"><span>Documents</span><span>${fmt(ins.stats.documents)}</span><span>Terms</span><span>${fmt(ins.stats.vocabulary)}</span><span>Postings</span><span>${fmt(ins.stats.postings)}</span><span>Tokens</span><span>${fmt(ins.stats.tokens)}</span>
        <span>Zipf exponent</span><span>${ins.zipf.exponent.toFixed(2)} (R² ${ins.zipf.r2.toFixed(2)})</span><span>Heaps' law</span><span>M = ${ins.heaps.k.toFixed(1)} · T^${ins.heaps.b.toFixed(2)}</span></div></div></div>`;
  $("#tf").addEventListener("submit", (e) => { e.preventDefault(); go("insights/index", { term: $("#tt").value }); });
}
async function insEval(el) {
  const r = await api("/api/eval").catch(() => null);
  const p = r && r.personalization;
  if (!p) { el.innerHTML = `<div class="note">Run <code>python experiments/personalization_benchmark.py</code> to produce the evaluation.</div>`; return; }
  const cols = ["P@10", "R@10", "F1@10", "MAP", "nDCG@10"];
  const best = Object.fromEntries(cols.map((c) => [c, Math.max(...Object.values(p.models).map((v) => v[c]))]));
  el.innerHTML = `<p class="explain">Measured on the Cranfield collection: ${p.collection.docs} documents and ${p.collection.queries} queries with human relevance judgements. Rankings are cut at ${p.depth} results.</p>
    <div class="panel"><h3>Retrieval methods</h3><table class="t"><thead><tr><th>Method</th>${cols.map((c) => `<th class="n">${c}</th>`).join("")}</tr></thead><tbody>
      ${Object.entries(p.models).map(([n, v]) => `<tr><td>${esc(n)}</td>${cols.map((c) => `<td class="n ${v[c] === best[c] ? "best" : ""}">${v[c].toFixed(4)}</td>`).join("")}</tr>`).join("")}</tbody></table>
      <p class="small muted" style="margin-top:10px">Smart equals Bridge-PRF on Cranfield because the collection has no links and these runs use no search history; its extra signals only act where they exist. Smart vs BM25: p ${p.p_smart_vs_bm25 < 0.001 ? "< 0.001" : "= " + p.p_smart_vs_bm25} (paired randomisation test).</p></div>
    <div class="panel"><h3>Does search memory help?</h3><p class="small muted" style="margin-bottom:10px">Simulated users with real judgements: a user searches one query, reads the relevant results (and opens a few wrong ones briefly), then searches again. Personal weight ${p.beta} chosen by cross-validation.</p>
      <table class="t"><thead><tr><th>Scenario</th><th class="n">Pairs</th><th class="n">MAP without</th><th class="n">MAP with</th><th class="n">nDCG@10 without</th><th class="n">nDCG@10 with</th><th class="n">p</th></tr></thead><tbody>
      ${Object.entries(p.memory).map(([n, v]) => `<tr><td>${esc(n)}</td><td class="n">${v.pairs}</td><td class="n">${v.without_memory.MAP.toFixed(4)}</td><td class="n ${v.with_memory.MAP > v.without_memory.MAP + 0.001 ? "best" : ""}">${v.with_memory.MAP.toFixed(4)}</td><td class="n">${v.without_memory["nDCG@10"].toFixed(4)}</td><td class="n">${v.with_memory["nDCG@10"].toFixed(4)}</td><td class="n">${v.p_MAP < 0.001 ? "< 0.001" : v.p_MAP}</td></tr>`).join("")}</tbody></table>
      <div class="chart" style="margin-top:16px;max-width:560px">${barChart(Object.entries(p.beta_sweep_related_MAP).map(([b, v]) => [`personal weight ${b}`, v, "#F6C343"]), { label: 150 })}</div><p class="tiny muted">MAP on related searches by personal weight.</p></div>`;
}
async function insCrawler(el) {
  const [c, d] = await Promise.all([api("/api/crawl"), api(`/api/lab/duplicates?${qs({ c: S.c })}`)]);
  const L = c.last;
  el.innerHTML = `<div class="grid2"><div class="panel"><h3>Web crawler</h3>
      ${L ? `<div class="kv"><span>Seed</span><span class="tiny">${esc((L.seeds || []).join(", "))}</span><span>Pages kept</span><span>${fmt(L.pages)}</span><span>Links between them</span><span>${fmt(L.links)}</span><span>Refused by robots.txt</span><span>${fmt(L.robots_blocked)}</span><span>Out of scope</span><span>${fmt(L.out_of_scope)}</span><span>Exact / near duplicates skipped</span><span>${fmt(L.dup_exact)} / ${fmt(L.dup_near)}</span><span>Errors</span><span>${fmt(L.errors)}</span><span>Time</span><span>${L.seconds}s</span></div>`
        : `<p class="small muted">No crawl yet. Start one from the <a href="#/library">Library</a> page.</p>`}
      <p class="small muted" style="margin-top:10px">Breadth-first frontier, robots.txt and Crawl-delay obeyed, at least one second between requests to a host, MinHash near-duplicate filter, links kept only between crawled pages.</p></div>
    <div class="panel"><h3>Near-duplicate documents</h3><p class="small muted">MinHash signatures with LSH banding find pairs with Jaccard ≥ 0.8 over 4-word shingles; duplicates are folded into one result.</p>
      <p style="margin:10px 0"><b>${fmt(d.pairs)}</b> pairs in ${esc(coll().name)}</p>
      <ul style="list-style:none;padding:0;margin:0">${d.examples.map((x) => `<li class="small" style="padding:6px 0;border-top:1px solid var(--line)"><a href="#/doc/${S.c}/${encodeURIComponent(x.a.id)}">${esc(x.a.title.slice(0, 60))}</a> ≈ <a href="#/doc/${S.c}/${encodeURIComponent(x.b.id)}">${esc(x.b.title.slice(0, 60))}</a> <span class="muted">${x.jaccard}</span></li>`).join("")}</ul></div></div>`;
}

/* ------------------------------------------------------------------ LIBRARY */
async function pageLibrary() {
  const [lib, cr] = await Promise.all([api("/api/library"), api("/api/crawl")]);
  $("#main").innerHTML = `<div class="wrap page" style="padding-top:34px"><div class="page-head" style="padding-top:0"><h1>Library</h1><p>Add your own documents, or crawl a website into a searchable collection with its real hyperlinks.</p></div>
    <div class="grid2"><div class="panel"><h3>My files</h3><p class="small muted">PDF, text, Markdown, HTML or JSON, up to 50 MB each. They form the “My Library” collection.</p>
      <form id="up" class="form-row" style="margin-top:12px"><input type="file" id="files" multiple accept=".pdf,.txt,.md,.html,.htm,.json,.jsonl" class="input" style="flex:1"><button class="btn btn-primary btn-sm">Upload</button></form>
      ${lib.files.length ? `<table class="t"><tbody>${lib.files.map((f) => `<tr><td>${esc(f.name)}</td><td class="n tiny muted">${f.type} · ${fmt(Math.round(f.bytes / 1024))} KB</td><td class="n"><button class="ibtn" data-del="${esc(f.name)}">Remove</button></td></tr>`).join("")}</tbody></table>`
        : `<p class="small">No files yet. <button class="btn btn-ghost btn-sm" id="samples">Add the sample documents</button></p>`}
<<<<<<< HEAD
      <p class="tiny muted" style="margin-top:8px">Status: ${esc(lib.status)}</p></div>
=======
      <p class="tiny muted" style="margin-top:8px">Status: ${esc(lib.status)}${lib.error ? ` · Last build failed: ${esc(lib.error)}` : ""}</p></div>
>>>>>>> 1d6f999a29f64cc4785f3e1f1baa07f014efb4c0
    <div class="panel"><h3>Crawl a website</h3><p class="small muted">Pages become the “Web pages” collection. The crawler obeys robots.txt, waits at least a second between requests and stays inside the path you give. Check the site's terms before crawling.</p>
      <form id="cf" style="display:grid;gap:10px;margin-top:12px">
        <label class="small muted">Start page<input class="input" id="seed" style="width:100%" placeholder="https://en.wikipedia.org/wiki/Information_retrieval" required></label>
        <div class="form-row" style="margin:0"><label>Stay under path<input class="input" id="prefix" placeholder="/wiki/"></label><label>Skip URLs containing<input class="input" id="excl" placeholder=":"></label>
          <label>Max pages<input class="input" id="maxp" type="number" value="200" min="10" max="1000" style="width:100px"></label></div>
        <div><button class="btn btn-primary btn-sm" ${cr.status === "running" ? "disabled" : ""}>${cr.status === "running" ? "Crawling…" : "Start crawl"}</button></div></form>
      <p class="small" id="crawl-status" style="margin-top:10px">${cr.status === "running" ? `Crawling ${esc(cr.seed)}: ${fmt((cr.progress || {}).fetched || 0)} of up to ${fmt(cr.max_pages || 0)} pages fetched${(cr.progress || {}).last_url ? `, latest <span class="tiny muted">${esc(decodeURIComponent(cr.progress.last_url.split("/").pop()))}</span>` : ""}. Updates every few seconds.` : cr.status === "error" ? `<span style="color:var(--red)">Last crawl failed: ${esc(cr.error)}</span>` : cr.last && cr.last.pages ? `Last crawl: ${fmt(cr.last.pages)} pages, ${fmt(cr.last.links)} links. <a href="#/search?c=web">Search them</a>` : ""}</p></div></div></div>`;
  $("#up").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData();
    [...$("#files").files].forEach((f) => fd.append("files", f));
    if (!fd.has("files")) return;
    const r = await api("/api/library/upload", { method: "POST", body: fd });
<<<<<<< HEAD
    toast(`Added ${r.saved.length} file${r.saved.length === 1 ? "" : "s"}${r.rejected.length ? `, ${r.rejected.length} rejected` : ""}. Indexing…`);
=======
    const messages = r.saved.length ? [`Indexing ${r.saved.length} uploaded file(s).`] : [];
    for (const file of r.rejected) messages.push(`${file.name}: ${file.reason}`);
    toast(messages.join(" "));
>>>>>>> 1d6f999a29f64cc4785f3e1f1baa07f014efb4c0
    S.info = null; pageLibrary();
  });
  const sm = $("#samples");
  if (sm) sm.addEventListener("click", async () => { await post("/api/library/load-samples", {}); toast("Sample documents added. Indexing…"); S.info = null; pageLibrary(); });
  $$("[data-del]").forEach((b) => b.addEventListener("click", async () => { await api(`/api/library/${encodeURIComponent(b.dataset.del)}`, { method: "DELETE" }); toast("Removed"); pageLibrary(); }));
  $("#cf").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await post("/api/crawl", { seed: $("#seed").value.trim(), prefix: $("#prefix").value.trim(), exclude: $("#excl").value.trim() ? [$("#excl").value.trim()] : [], max_pages: +$("#maxp").value || 200 });
      toast("Crawl started. This takes about a second per page.");
      S.info = null;
      pageLibrary();
    } catch (err) { toast(err.message); }
  });
  if (cr.status === "running") setTimeout(() => { if (parse().parts[0] === "library") pageLibrary(); }, 5000);
}

route();
