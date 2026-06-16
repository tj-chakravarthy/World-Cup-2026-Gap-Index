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
const name = (c) => TEAM[c] || c;

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
  p = Math.max(0, Math.min(1, p));
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
    `${sim.n_sims.toLocaleString()} simulations · 48 teams` +
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
    return `<tr><td class="rk">${i + 1}</td>` +
      `<td class="team">${name(t.country_code)}<span class="code">${t.country_code}</span></td>` +
      cells + `</tr>`;
  }).join("");
}

function renderFixtures(live) {
  const now = Date.now();
  const up = (live.predictions || [])
    .filter((p) => new Date(p.kickoff_utc).getTime() >= now - 2 * 3600e3) // keep just-started too
    .sort((a, b) => new Date(a.kickoff_utc) - new Date(b.kickoff_utc))
    .slice(0, 14);

  const el = document.getElementById("fixture-list");
  if (!up.length) {
    el.innerHTML = `<p class="meta">No upcoming fixtures in the forecast right now.</p>`;
    return;
  }
  el.innerHTML = up.map((p) => {
    const w = p.wdl.team1, d = p.wdl.draw, l = p.wdl.team2;
    const top = (p.scorelines || []).slice().sort((a, b) => b.p - a.p)[0];
    return `<div class="fx">
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
    </div>`;
  }).join("");
}

async function main() {
  document.getElementById("repo").href = REPO_URL;
  try {
    const [sim, live] = await Promise.all([
      getJSON("data/simulation.json"),
      getJSON("data/predictions_live.json"),
    ]);
    renderMeta(sim, live);
    renderForecast(sim);
    renderFixtures(live);
  } catch (e) {
    document.getElementById("meta").innerHTML =
      `<span class="err">Could not load the forecast (${e.message}).</span>`;
  }
}

main();
