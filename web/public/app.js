"use strict";

// Static site: fetch the cron-published JSON at runtime, render. No build, no deps.
const REPO_URL = "https://github.com/tj-chakravarthy/World-Cup-2026-Gap-Index";

// FIFA code -> display name, the fixed 48-team field (data/raw/team_codes.csv).
const TEAM = {
  ALG:"Algeria", ARG:"Argentina", AUS:"Australia", AUT:"Austria", BEL:"Belgium",
  BIH:"Bosnia & Herzegovina", BRA:"Brazil", CAN:"Canada", CIV:"Côte d'Ivoire",
  COD:"Congo DR", COL:"Colombia", CPV:"Cabo Verde", CRO:"Croatia", CUW:"Curaçao",
  CZE:"Czechia", ECU:"Ecuador", EGY:"Egypt", ENG:"England", ESP:"Spain", FRA:"France",
  GER:"Germany", GHA:"Ghana", HAI:"Haiti", IRN:"IR Iran", IRQ:"Iraq", JOR:"Jordan",
  JPN:"Japan", KOR:"Korea Republic", KSA:"Saudi Arabia", MAR:"Morocco", MEX:"Mexico",
  NED:"Netherlands", NOR:"Norway", NZL:"New Zealand", PAN:"Panama", PAR:"Paraguay",
  POR:"Portugal", QAT:"Qatar", RSA:"South Africa", SCO:"Scotland", SEN:"Senegal",
  SUI:"Switzerland", SWE:"Sweden", TUN:"Tunisia", TUR:"Türkiye", URU:"Uruguay",
  USA:"USA", UZB:"Uzbekistan",
};
const name = (c) => esc(TEAM[c] || c);   // all name() output goes into innerHTML -> escape at the source

const COLS = [
  ["p_R32", "Advance"], ["p_R16", "Last 16"], ["p_QF", "Quarters"],
  ["p_SF", "Semis"], ["p_final", "Final"], ["p_winner", "Champion"],
];

// volt heat ramp (matches the shareable PNG), piecewise-linear over these stops.
const STOPS = [
  [0.00, [18, 18, 26]], [0.18, [23, 42, 12]], [0.40, [47, 74, 8]],
  [0.62, [95, 122, 0]], [0.82, [169, 196, 0]], [1.00, [232, 255, 0]],
];
function heat(p) {
  p = Number.isFinite(p) ? Math.max(0, Math.min(1, p)) : 0;   // NaN/undefined -> dark, not bright-yellow
  for (let i = 1; i < STOPS.length; i++) {
    const [p1, c1] = STOPS[i - 1], [p2, c2] = STOPS[i];
    if (p <= p2) {
      const t = (p - p1) / (p2 - p1 || 1);
      const m = (a, b) => Math.round(a + (b - a) * t);
      return `rgb(${m(c1[0], c2[0])},${m(c1[1], c2[1])},${m(c1[2], c2[2])})`;
    }
  }
  return "rgb(232,255,0)";
}

const pct = (p) => (p >= 0.005 ? Math.round(p * 100) + "%" : "·");

function whenLabel(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString(undefined, {
    weekday: "short", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

async function getJSON(path) {
  const r = await fetch(`${path}?t=${Date.now()}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

function renderMeta(sim, live) {
  const when = new Date(sim.generated_at);
  const stale = (live.sources || []).some((s) => s.stale);
  document.getElementById("meta").innerHTML =
    `Updated ${isNaN(when) ? sim.generated_at : when.toLocaleString()} · ` +
    `${sim.n_sims.toLocaleString("en-US").replace(/,/g, " ")} simulations` +
    (stale ? ` · <span class="stale">data stale</span>` : "");
}

function renderForecast(sim) {
  const teams = [...sim.teams].sort((a, b) => b.p_winner - a.p_winner);
  const thead = document.querySelector("#forecast-table thead");
  thead.innerHTML =
    `<tr><th class="rk">#</th><th class="team">Team</th>` +
    COLS.map(([, label]) => `<th>${label}</th>`).join("") + `</tr>`;

  const body = document.querySelector("#forecast-table tbody");
  body.innerHTML = teams.map((t, i) => {
    const cells = COLS.map(([key]) => {
      const p = t[key];
      const fg = p >= 0.62 ? "#0A0A0F" : "#f5f5f7";
      return `<td><span class="cell" style="background:${heat(p)};color:${fg}">${pct(p)}</span></td>`;
    }).join("");
    return `<tr class="${i >= 5 ? "extra" : ""}"><td class="rk">${i + 1}</td>` +
      `<td class="team">${name(t.country_code)}<span class="code">${t.country_code}</span></td>` +
      cells + `</tr>`;
  }).join("");

  // collapsed by default: top 5 shown, rest behind a toggle
  const table = document.getElementById("forecast-table");
  const btn = document.getElementById("forecast-toggle");
  table.classList.add("collapsed");
  const collapsedLabel = `Show all ${teams.length} teams ▾`;
  btn.textContent = collapsedLabel;
  btn.setAttribute("aria-expanded", "false");
  btn.onclick = () => {
    const collapsed = table.classList.toggle("collapsed");
    btn.setAttribute("aria-expanded", String(!collapsed));
    btn.textContent = collapsed ? collapsedLabel : "Show top 5 ▴";
  };
}

// "tale of the tape": the model's two inputs for a fixture (Elo + squad value), each as the
// two teams' percentile in the 48-team field, drawn as a split bar. inp from model_inputs.json.
function tapeHTML(inp) {
  if (!inp) return "";
  const row = (lab, a, b) => {
    const av = a == null ? "—" : a, bv = b == null ? "—" : b;
    const share = a != null && b != null && a + b > 0 ? (a / (a + b)) * 100 : 50;
    return `<div class="tape-row"><span class="tlab">${lab}</span>` +
      `<span class="tnum">${av}</span>` +
      `<div class="tbar"><i style="width:${share}%"></i></div>` +
      `<span class="tnum">${bv}</span></div>`;
  };
  return `<div class="tape" title="strength percentile in the field — the model's two inputs">` +
    row("Elo", inp.elo1, inp.elo2) + row("Value", inp.mkt1, inp.mkt2) + `</div>`;
}

const fmtDelta = (x) => (x >= 0 ? "+" : "−") + Math.abs(x * 100).toFixed(1) + "pp";

function renderMovement(mv) {
  const sec = document.getElementById("movement");
  const body = document.getElementById("movement-body");
  if (!sec || !body) return;
  if (!mv || !(mv.newly_resolved || []).length) { sec.hidden = true; return; }

  // the results that caused the move — a terse one-line list. The per-match detail (predicted
  // vs actual + the model's inputs) lives in the track-record cards below; no need to repeat it.
  const n = mv.newly_resolved.length;
  const since = mv.newly_resolved
    .map((c) => `${name(c.team1)} <b>${c.score.replace("-", "–")}</b> ${name(c.team2)}`)
    .join(" · ");

  const rows = (arr) => arr.map((m) =>
    `<div class="mv-row"><span class="mv-team">${name(m.country_code)}</span>` +
    `<span class="mv-delta ${m.delta >= 0 ? "up" : "down"}">${fmtDelta(m.delta)}</span></div>`).join("");
  const col = (title, arr) => arr.length ? `<div class="mv-col"><h3>${title}</h3>${rows(arr)}</div>` : "";

  body.innerHTML =
    `<p class="mv-since"><span class="mv-n">${n} result${n > 1 ? "s" : ""} in:</span> ${since}</p>` +
    `<div class="mv-movers">` +
    col("Biggest swing — reach knockouts", mv.advance_movers || []) +
    col("Biggest swing — win it all", mv.title_movers || []) +
    `</div>`;
  sec.hidden = false;
}

function renderLive(live) {
  // matches that have kicked off but aren't resolved yet — shown with a blinking LIVE badge, no
  // odds (the pre-kickoff forecast already moved to the track record). Bounded client-side to
  // ~2.5h after kickoff so a finished-but-feed-lagging match drops off on its own.
  const sec = document.getElementById("live");
  const el = document.getElementById("live-list");
  const navLive = document.getElementById("nav-live");
  if (!sec || !el) return;
  const now = Date.now();
  const games = (live.live_now || []).filter((g) => {
    const ko = new Date(g.kickoff_utc).getTime();
    return ko <= now && now - ko < 2.5 * 3600e3;
  });
  if (!games.length) { sec.hidden = true; if (navLive) navLive.hidden = true; return; }
  el.innerHTML = games.map((g) =>
    `<div class="live-row"><span class="live-badge">● LIVE</span>` +
    `<span class="live-teams">${name(g.team1)} <span class="v">v</span> ${name(g.team2)}</span></div>`
  ).join("");
  sec.hidden = false;
  if (navLive) navLive.hidden = false;   // surface the nav pill only while a match is live
}

// collapse a list to its first `topN` items behind a Show more / Show fewer toggle. Items beyond
// topN must carry class "extra" (CSS hides them while the container has class "collapsed").
function setupCollapse(listEl, btn, topN, total) {
  if (!listEl || !btn) return;
  if (total <= topN) { btn.hidden = true; listEl.classList.remove("collapsed"); return; }
  btn.hidden = false;
  listEl.classList.add("collapsed");
  const more = `Show all ${total} ▾`, less = "Show fewer ▴";
  btn.textContent = more;
  btn.setAttribute("aria-expanded", "false");
  btn.onclick = () => {
    const collapsed = listEl.classList.toggle("collapsed");
    btn.setAttribute("aria-expanded", String(!collapsed));
    btn.textContent = collapsed ? more : less;
  };
}

// highlight the sticky-nav pill for whichever section is currently centered in the viewport
function setupSectionNav() {
  const links = [...document.querySelectorAll(".sectnav a")];
  if (!links.length || !("IntersectionObserver" in window)) return;
  const byId = new Map(links.map((a) => [a.getAttribute("href").slice(1), a]));
  const obs = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      const a = byId.get(e.target.id);
      if (a) links.forEach((x) => x.classList.toggle("active", x === a));
    });
  }, { rootMargin: "-45% 0px -45% 0px" });   // active when the section crosses the viewport middle
  byId.forEach((_, id) => { const s = document.getElementById(id); if (s) obs.observe(s); });
}

function renderFixtures(live, inputs) {
  const now = Date.now();
  const up = (live.predictions || [])
    .filter((p) => new Date(p.kickoff_utc).getTime() > now) // strictly upcoming — kicked-off matches move to the LIVE strip
    .sort((a, b) => new Date(a.kickoff_utc) - new Date(b.kickoff_utc))
    .slice(0, 14);

  const el = document.getElementById("fixture-list");
  if (!up.length) {
    el.innerHTML = `<p class="meta">No upcoming fixtures in the forecast right now.</p>`;
    document.getElementById("fixtures-toggle").hidden = true;
    return;
  }
  el.innerHTML = up.map((p, i) => {
    const w = p.wdl.team1, d = p.wdl.draw, l = p.wdl.team2;
    const top = (p.scorelines || []).slice().sort((a, b) => b.p - a.p)[0];
    return `<div class="fx${i >= 3 ? " extra" : ""}">
      <div class="when"><span>${whenLabel(p.kickoff_utc)}</span><span class="stage">${p.stage}</span></div>
      <div class="teams">
        <span class="t">${name(p.team1)}</span>
        <span class="v">vs</span>
        <span class="t away">${name(p.team2)}</span>
      </div>
      <div class="bar">
        <i class="w" style="width:${w * 100}%"></i>
        <i class="d" style="width:${d * 100}%"></i>
        <i class="l" style="width:${l * 100}%"></i>
      </div>
      <div class="pct">
        <span><b>${Math.round(w * 100)}%</b> ${p.team1}</span>
        <span>draw <b>${Math.round(d * 100)}%</b></span>
        <span>${p.team2} <b>${Math.round(l * 100)}%</b></span>
      </div>
      ${top ? `<div class="top">Most likely score <b>${top.score}</b> (${Math.round(top.p * 100)}%)</div>` : ""}
      ${tapeHTML((inputs || {})[p.fixture_id])}
    </div>`;
  }).join("");
  setupCollapse(el, document.getElementById("fixtures-toggle"), 3, up.length);
}

function renderTrack(tr, inputs, live) {
  const meta = document.getElementById("track-meta");
  const banner = document.getElementById("track-stale");
  const el = document.getElementById("track-list");

  // receipts freshness: track_record is regenerated in the same hard-gated run as the forecast,
  // so its timestamp should track predictions_live's. If it falls meaningfully behind (a stale
  // deploy, an older committed file), say so rather than pass off lagging receipts as current.
  const recAt = new Date(tr.generated_at);
  const fcAt = live ? new Date(live.generated_at) : new Date(NaN);
  const lagMin = !isNaN(recAt) && !isNaN(fcAt) ? (fcAt - recAt) / 60000 : 0;
  const stale = lagMin > 30;  // > ~30 min behind the forecast = missed at least one update cycle
  const asOf = isNaN(recAt) ? tr.generated_at : recAt.toLocaleString();

  if (meta) meta.innerHTML =
    `${tr.n_receipts} standing pre-kickoff receipts (from ${tr.n_audit_rows} audit-log rows) · ` +
    `${tr.n_resolved} resolved so far · receipts as of ${asOf}` +
    (stale ? ` · <span class="stale">lagging the forecast</span>` : "");
  if (banner) {
    banner.hidden = !stale;
    if (stale) banner.textContent =
      `These receipts are from ${asOf}, behind the current forecast — they’ll catch up on the next update.`;
  }
  const toggle = document.getElementById("track-toggle");
  if (!el) return;
  if (!tr.resolved || !tr.resolved.length) {
    el.innerHTML = `<p class="meta">No games resolved yet.</p>`;
    if (toggle) toggle.hidden = true;
    return;
  }
  const games = [...tr.resolved].sort(
    (a, b) => new Date(b.kickoff_utc) - new Date(a.kickoff_utc));  // most recent game first
  el.innerHTML = games.map((g, i) => {
    const w = g.p_team1, d = g.p_draw, l = g.p_team2;
    const result = g.outcome === 0 ? `${name(g.team1)} won`
                 : g.outcome === 2 ? `${name(g.team2)} won` : "draw";
    const mark = g.called ? `<span class="ok">✓ called</span>` : `<span class="no">missed</span>`;
    const exact = g.exact_hit ? ` · <span class="exact">🎯 exact score</span>` : "";
    const model = g.model && g.model !== "live" ? `<span class="tr-model">${g.model}</span>` : "";
    return `<div class="tr${i >= 3 ? " extra" : ""}">
      <div class="tr-teams">${name(g.team1)} <span class="v">v</span> ${name(g.team2)}${model}</div>
      <div class="bar">
        <i class="w" style="width:${w * 100}%"></i>
        <i class="d" style="width:${d * 100}%"></i>
        <i class="l" style="width:${l * 100}%"></i>
      </div>
      <div class="tr-line">
        <span>predicted <b>${Math.round(w * 100)}/${Math.round(d * 100)}/${Math.round(l * 100)}</b></span>
        <span>actual <b>${g.actual}</b> · ${result}</span>
        <span>${mark}${exact}</span>
      </div>
      ${tapeHTML((inputs || {})[g.fixture_id])}
    </div>`;
  }).join("");
  setupCollapse(el, toggle, 3, games.length);
}

const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// reveal a bottom section + its (hidden-by-default) nav pill once its data has loaded
function showSection(id) {
  const sec = document.getElementById(id);
  const nav = document.getElementById("nav-" + id);
  if (sec) sec.hidden = false;
  if (nav) nav.hidden = false;
}

// Gap Index: talent-vs-result residual per team, a diverging bar (over right / under left). The
// headline is the 6 biggest over- and under-performers; the middle unfolds behind the toggle.
function renderGap(gap) {
  const el = document.getElementById("gap-list");
  if (!el || !gap || !(gap.teams || []).length) return;
  const r2 = document.getElementById("gap-r2");
  if (r2 && gap.r2 != null) r2.textContent = gap.r2.toFixed(2);
  const teams = gap.teams;                                  // sorted gap desc (over -> under)
  const maxAbs = Math.max(...teams.map((t) => Math.abs(t.gap))) || 1;
  const headline = new Set([...teams.slice(0, 6), ...teams.slice(-6)]);
  el.innerHTML = teams.map((t) => {
    const over = t.gap >= 0;
    const w = Math.min(50, (Math.abs(t.gap) / maxAbs) * 50);
    const fill = over ? `left:50%;width:${w}%` : `right:50%;width:${w}%`;
    // most gap teams are past tournaments, so they're outside the 48-team 2026 map — fall back to
    // the full name the data carries (else they'd show as a bare FIFA code: VEN, SRB, DEN…)
    const label = TEAM[t.code] || t.team || t.code;
    return `<div class="gap-row${headline.has(t) ? "" : " extra"}">
      <div class="gap-team">${esc(label)}<span class="gap-t">${esc(t.t)}</span></div>
      <div class="gap-track"><i class="gap-fill ${over ? "over" : "under"}" style="${fill}"></i></div>
      <div class="gap-num ${over ? "over" : "under"}">${t.gap >= 0 ? "+" : "−"}${Math.abs(t.gap).toFixed(2)}
        <span class="gap-band">[${t.lo.toFixed(1)}, ${t.hi.toFixed(1)}]</span></div>
    </div>`;
  }).join("");
  const btn = document.getElementById("gap-toggle");
  if (btn && teams.length > headline.size) {
    el.classList.add("collapsed");
    btn.hidden = false;
    const more = `Show all ${teams.length} ▾`;
    btn.textContent = more;
    btn.onclick = () => {
      const c = el.classList.toggle("collapsed");
      btn.setAttribute("aria-expanded", String(!c));
      btn.textContent = c ? more : "Show fewer ▴";
    };
  }
  showSection("gap");
}

// Player ratings: top club-stats scores (0-100), the score chip on the same heat ramp as the board.
function renderPlayers(players, rated) {
  const el = document.getElementById("players-list");
  if (!el || !(players || []).length) return;
  const shown = document.getElementById("players-shown");
  const total = document.getElementById("players-rated");
  if (shown) shown.textContent = players.length;
  if (total) total.textContent = rated ? rated.toLocaleString("en-US").replace(/,/g, " ") : "all";
  el.innerHTML = players.map((p, i) => {
    const fg = p.score / 100 >= 0.62 ? "#0A0A0F" : "#f5f5f7";   // dark text once the heat goes bright (matches the forecast cells)
    const mv = p.mv != null ? `€${p.mv}m` : "—";
    return `<div class="pl-row${i >= 12 ? " extra" : ""}">
      <span class="pl-rk">${i + 1}</span>
      <span class="pl-name">${esc(p.name)}<span class="code">${esc(p.code)}</span></span>
      <span class="pl-pos">${esc(p.pos)}</span>
      <span class="pl-mv">${mv}</span>
      <span class="pl-score" style="background:${heat(p.score / 100)};color:${fg}">${p.score.toFixed(1)}</span>
    </div>`;
  }).join("");
  setupCollapse(el, document.getElementById("players-toggle"), 12, players.length);
  showSection("players");
}

// Calibration: a reliability diagram (predicted vs observed per outcome) drawn as a small SVG.
const CAL_COLORS = { "team1 win": "#E8FF00", draw: "#8b8b9e", "team2 win": "#7a93c4" };
function renderCalibration(cal) {
  const el = document.getElementById("calibration-chart");
  if (!el || !(cal || []).length) return;
  const W = 300, H = 300, m = 34, pad = 14;
  const sx = (v) => m + v * (W - pad - m);
  const sy = (v) => (H - m) - v * (H - m - pad);
  const grid = [0, 0.5, 1];
  const axes =
    grid.map((v) => `<line x1="${sx(v)}" y1="${sy(0)}" x2="${sx(v)}" y2="${sy(1)}" class="cal-grid"/>` +
                    `<line x1="${sx(0)}" y1="${sy(v)}" x2="${sx(1)}" y2="${sy(v)}" class="cal-grid"/>`).join("") +
    `<line x1="${sx(0)}" y1="${sy(0)}" x2="${sx(1)}" y2="${sy(1)}" class="cal-diag"/>` +
    grid.map((v) => `<text x="${sx(v)}" y="${H - m + 16}" class="cal-tick" text-anchor="middle">${v}</text>` +
                    `<text x="${m - 8}" y="${sy(v) + 4}" class="cal-tick" text-anchor="end">${v}</text>`).join("");
  const dots = cal.map((p) => {
    const r = Math.min(12, 3 + Math.sqrt(p.n) * 0.7);
    return `<circle cx="${sx(p.pred)}" cy="${sy(p.obs)}" r="${r}" fill="${CAL_COLORS[p.outcome] || "#fff"}"
            fill-opacity="0.78"><title>${p.outcome}: predicted ${Math.round(p.pred * 100)}%, observed ${Math.round(p.obs * 100)}% (${p.n} games)</title></circle>`;
  }).join("");
  el.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" class="cal-svg" role="img" aria-label="reliability diagram">` +
    axes + dots +
    `<text x="${sx(0.5)}" y="${H - 4}" class="cal-axis" text-anchor="middle">predicted probability</text>` +
    `<text x="12" y="${sy(0.5)}" class="cal-axis" text-anchor="middle" transform="rotate(-90 12 ${sy(0.5)})">observed frequency</text>` +
    `</svg>`;
  const legend = document.getElementById("calibration-legend");
  if (legend) legend.innerHTML = Object.entries(CAL_COLORS).map(([k, c]) =>
    `<span class="cal-key"><i style="background:${c}"></i>${k}</span>`).join("");
  showSection("calibration");
}

// Ablation: Brier per feature set, lower = better. The bar is the 90% CI mapped across a zoomed
// domain (the scores are close), the dot the point estimate; the live model's row is flagged.
function renderAblation(model) {
  const el = document.getElementById("model-list");
  if (!el || !model || !(model.rows || []).length) return;
  const rows = model.rows;
  const lo = Math.min(...rows.map((r) => r.lo)) - 0.002;
  const hi = Math.max(...rows.map((r) => r.hi)) + 0.002;
  const pos = (v) => ((v - lo) / (hi - lo)) * 100;
  el.innerHTML = rows.map((r) => {
    const live = r.set === "+ market value";
    const badge = live ? `<span class="ab-badge">live model</span>` : "";
    return `<div class="ab-row${live ? " live" : ""}">
      <div class="ab-set">${esc(r.set)}${badge}</div>
      <div class="ab-track">
        <i class="ab-ci" style="left:${pos(r.lo)}%;width:${pos(r.hi) - pos(r.lo)}%"></i>
        <i class="ab-pt" style="left:${pos(r.brier)}%"></i>
      </div>
      <div class="ab-num">${r.brier.toFixed(3)}</div>
    </div>`;
  }).join("");
  el.insertAdjacentHTML("beforeend",
    `<div class="ab-foot"><span>← better</span><span>${model.n}-game backtest · Brier</span></div>`);
  showSection("model");
}

async function main() {
  document.getElementById("repo").href = REPO_URL;

  // intro: show the lead line; the rest unfolds on "more"
  const introBtn = document.getElementById("intro-toggle");
  const introMore = document.getElementById("intro-more");
  if (introBtn && introMore) introBtn.onclick = () => {
    const open = !introMore.hidden;
    introMore.hidden = open;
    introBtn.setAttribute("aria-expanded", String(!open));
    introBtn.textContent = open ? "more ▾" : "less ▴";
  };

  try {
    const [sim, live, track, mi, mv, analysis] = await Promise.all([
      getJSON("data/simulation.json"),
      getJSON("data/predictions_live.json"),
      getJSON("data/track_record.json").catch(() => null),
      getJSON("data/model_inputs.json").catch(() => null),
      getJSON("data/movement.json").catch(() => null),
      getJSON("data/analysis.json").catch(() => null),
    ]);
    const inputs = (mi && mi.fixtures) || {};
    renderMeta(sim, live);
    renderForecast(sim);
    renderMovement(mv);
    renderLive(live);
    renderFixtures(live, inputs);
    if (track) renderTrack(track, inputs, live);
    if (analysis) {
      renderGap(analysis.gap);
      renderPlayers(analysis.players, analysis.players_rated);
      renderCalibration(analysis.calibration);
      renderAblation(analysis.ablation);
    }
    setupSectionNav();
  } catch (e) {
    document.getElementById("meta").innerHTML =
      `<span class="err">Could not load the forecast (${e.message}).</span>`;
  }
}

main();
