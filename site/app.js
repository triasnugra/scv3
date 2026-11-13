"use strict";
/* Dashboard statis: membaca data/*.json yang dibuat mesin. Semua teks lewat textContent (aman dari injeksi). */
const $ = (id) => document.getElementById(id);
const SETUP = {range_deviation: "Deviasi Range", level_sweep: "Stop Run Level",
  breakout_retest: "Breakout-Retest", squeeze_expansion: "Squeeze Ekspansi"};

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v; else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
function fmtP(x) {
  if (x === null || x === undefined || isNaN(x)) return "—";
  const a = Math.abs(x), d = a >= 100 ? 2 : a >= 10 ? 3 : a >= 1 ? 4 : a >= 0.1 ? 5 : 7;
  return x.toLocaleString("en-US", {minimumFractionDigits: d, maximumFractionDigits: d});
}
const fmtR = (r) => (r === null || r === undefined) ? "—" : (r > 0 ? "+" : "") + r.toFixed(2) + "R";
const cls = (r) => r > 0 ? "pos" : r < 0 ? "neg" : "";
function ago(iso) {
  if (!iso) return "—";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "baru saja"; if (m < 60) return m + " mnt lalu";
  if (m < 1440) return Math.round(m / 60) + " jam lalu";
  return Math.round(m / 1440) + " hari lalu";
}
function when(iso) {
  return iso ? new Date(iso).toLocaleString("id-ID", {day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"}) : "—";
}
async function load(name) {
  try { const r = await fetch("data/" + name + ".json?t=" + Date.now()); return r.ok ? await r.json() : null; }
  catch (e) { return null; }
}

function equitySvg(points) {
  if (!points || points.length < 2) return h("div", {class: "empty"}, "Belum cukup data");
  const W = 600, H = 120, pad = 6;
  const lo = Math.min(0, ...points), hi = Math.max(0, ...points), span = (hi - lo) || 1;
  const x = (i) => pad + i * (W - 2 * pad) / (points.length - 1);
  const y = (v) => H - pad - (v - lo) / span * (H - 2 * pad);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "eq"); svg.setAttribute("preserveAspectRatio", "none");
  const zero = document.createElementNS(ns, "line");
  zero.setAttribute("x1", 0); zero.setAttribute("x2", W); zero.setAttribute("y1", y(0)); zero.setAttribute("y2", y(0));
  zero.setAttribute("stroke", "currentColor"); zero.setAttribute("opacity", ".25"); zero.setAttribute("stroke-dasharray", "4 4");
  const pl = document.createElementNS(ns, "polyline");
  pl.setAttribute("points", points.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" "));
  pl.setAttribute("fill", "none"); pl.setAttribute("stroke-width", "2");
  pl.setAttribute("stroke", points[points.length - 1] >= 0 ? "var(--long)" : "var(--short)");
  pl.setAttribute("vector-effect", "non-scaling-stroke");
  svg.append(zero, pl);
  return svg;
}

function statsBlock(st) {
  const o = st && st.overall;
  if (!o || !o.n) return h("div", {class: "empty"}, "Belum ada trade selesai");
  const rows = [["Trade", o.n], ["Win rate", o.win_rate + "%"], ["Rata-rata R", fmtR(o.avg_r)],
    ["Total R", fmtR(o.total_r)], ["Profit factor", o.profit_factor ?? "—"], ["Max drawdown", (st.max_drawdown_r ?? 0) + "R"]];
  const t = h("table", {}, ...rows.map(([k, v]) => h("tr", {}, h("td", {class: "muted"}, k), h("td", {}, v))));
  const grp = (title, obj) => {
    const keys = Object.keys(obj || {});
    if (!keys.length) return null;
    return h("div", {class: "tablewrap", style: "margin-top:10px"}, h("table", {},
      h("tr", {}, h("th", {}, title), h("th", {}, "n"), h("th", {}, "WR"), h("th", {}, "avg R"), h("th", {}, "total R")),
      ...keys.map(k => { const b = obj[k]; return h("tr", {}, h("td", {}, SETUP[k] || k.toUpperCase()), h("td", {}, b.n),
        h("td", {}, b.win_rate === null ? "—" : b.win_rate + "%"), h("td", {class: cls(b.avg_r)}, fmtR(b.avg_r)),
        h("td", {class: cls(b.total_r)}, fmtR(b.total_r))); })));
  };
  return h("div", {}, t, grp("Arah", st.by_side), grp("Setup", st.by_setup));
}

function card(s) {
  const long = s.side === "long";
  const z = s.size || {};
  return h("div", {class: "card " + s.side},
    h("div", {class: "hd"}, h("span", {class: "sym"}, s.symbol), h("span", {class: "side " + s.side}, long ? "LONG" : "SHORT"),
      h("span", {class: "score"}, "skor " + s.score)),
    h("div", {class: "muted", style: "font-size:12px"}, (SETUP[s.setup] || s.setup) + " · " + s.level_name + " · " + when(s.bar_close)),
    h("div", {class: "lv"},
      h("span", {class: "k"}, "Entry"), h("span", {}), h("span", {class: "v"}, fmtP(s.entry)),
      h("span", {class: "k"}, "SL"), h("span", {class: "muted"}, s.sl_pct.toFixed(2) + "%"), h("span", {class: "v sl"}, fmtP(s.sl)),
      h("span", {class: "k"}, "TP1"), h("span", {class: "muted"}, s.rr1 + "R · " + s.tp1_basis), h("span", {class: "v tp"}, fmtP(s.tp1)),
      h("span", {class: "k"}, "TP2"), h("span", {class: "muted"}, s.rr2 + "R · " + s.tp2_basis), h("span", {class: "v tp"}, fmtP(s.tp2))),
    h("div", {class: "muted", style: "font-size:12px"},
      `Status: ${s.status === "TP1" ? "TP1 kena → SL di BE" : "berjalan"} · risiko $${z.risk_usd ?? "—"} · lev ${z.leverage_x ?? "—"}x · ${s.bars} candle`),
    h("div", {class: "chips"}, ...(s.reasons || []).map(r => h("span", {class: "chip"}, r))));
}

function marketTable(markets) {
  const th = h("tr", {}, ...["Simbol", "Harga", "Rezim", "Bias H4", "Posisi di range", "RSI", "Vol", "Rencana"].map(t => h("th", {}, t)));
  const arrow = (b) => b > 0 ? h("span", {class: "pos"}, "▲") : b < 0 ? h("span", {class: "neg"}, "▼") : h("span", {class: "muted"}, "—");
  const rows = markets.map(m => {
    let bar = h("span", {class: "muted"}, "—");
    if (m.range_ok && m.range_pos !== null) {
      const p = Math.max(-0.1, Math.min(1.1, m.range_pos));
      bar = h("div", {class: "rbar", title: `${fmtP(m.range_low)} – ${fmtP(m.range_high)}`}, h("u"), h("i", {style: `left:${(p + 0.1) / 1.2 * 100}%`}));
    }
    return h("tr", {}, h("td", {}, h("b", {}, m.symbol.replace("USDT", ""))), h("td", {}, fmtP(m.price)),
      h("td", {}, h("span", {class: "reg " + m.regime}, m.regime.replace("_", " "))), h("td", {}, arrow(m.bias_h4)),
      h("td", {}, bar), h("td", {}, m.rsi.toFixed(0)), h("td", {}, m.relvol.toFixed(1) + "x"), h("td", {class: "wrapcell"}, m.plan));
  });
  return [th, ...rows];
}

function historyTable(sigs) {
  const th = h("tr", {}, ...["Waktu", "Simbol", "Arah", "Setup", "Entry", "SL", "TP2", "Skor", "Status", "Hasil"].map(t => h("th", {}, t)));
  const rows = sigs.slice().reverse().slice(0, 60).map(s => h("tr", {}, h("td", {}, when(s.bar_close)), h("td", {}, s.symbol.replace("USDT", "")),
    h("td", {class: s.side === "long" ? "pos" : "neg"}, s.side.toUpperCase()), h("td", {}, SETUP[s.setup] || s.setup),
    h("td", {}, fmtP(s.entry)), h("td", {}, fmtP(s.sl)), h("td", {}, fmtP(s.tp2)), h("td", {}, s.score),
    h("td", {}, s.status), h("td", {class: cls(s.r)}, fmtR(s.r))));
  return rows.length ? [th, ...rows] : [h("tr", {}, h("td", {class: "muted"}, "Belum ada sinyal"))];
}

async function main() {
  const [sig, mk, bt, meta] = await Promise.all([load("signals"), load("market"), load("backtest"), load("meta")]);
  const mode = (meta && meta.mode) || (mk && mk.mode) || "—";
  $("mode").textContent = mode === "demo" ? "DEMO" : mode === "live" ? "LIVE" : mode;
  $("mode").classList.add(mode === "demo" ? "demo" : "live");
  $("demo-banner").hidden = mode !== "demo";
  const upd = (mk && mk.updated) || (sig && sig.updated);
  $("updated").textContent = "diperbarui " + ago(upd) + (meta ? " · v" + meta.version : "");

  const signals = (sig && sig.signals) || [];
  const active = signals.filter(s => s.status === "OPEN" || s.status === "TP1");
  const live = (sig && sig.stats) || {};
  const lo = live.overall || {}, bo = (bt && bt.stats && bt.stats.overall) || {};
  const kp = (v, l, c) => h("div", {class: "kpi"}, h("b", {class: c || ""}, v), h("span", {}, l));
  $("kpis").replaceChildren(
    kp(active.length, "Sinyal aktif"),
    kp(lo.n ? lo.win_rate + "%" : "—", "Win rate live (" + (lo.n || 0) + " trade)"),
    kp(lo.n ? fmtR(lo.total_r) : "—", "Total R live", cls(lo.total_r)),
    kp(bo.n ? bo.win_rate + "%" : "—", "Win rate backtest (" + (bo.n || 0) + ")"),
    kp(bo.n ? fmtR(bo.avg_r) : "—", "Avg R backtest", cls(bo.avg_r)),
    kp(bo.profit_factor ?? "—", "Profit factor backtest"));

  $("active").replaceChildren(...(active.length ? active.map(card)
    : [h("div", {class: "empty"}, "Tidak ada sinyal aktif. Menunggu trigger — tidak trading juga posisi yang sah.")]));
  $("market").replaceChildren(...marketTable((mk && mk.markets) || []));
  $("history").replaceChildren(...historyTable(signals.filter(s => s.status !== "OPEN" && s.status !== "TP1")));

  $("eq-live").replaceChildren(equitySvg(live.equity_r)); $("st-live").replaceChildren(statsBlock(live));
  if (bt) {
    $("bt-span").textContent = bt.days ? "· " + bt.days + " hari" : "";
    $("eq-bt").replaceChildren(equitySvg(bt.stats && bt.stats.equity_r)); $("st-bt").replaceChildren(statsBlock(bt.stats));
    $("assump").replaceChildren(...(bt.assumptions || []).map(a => h("li", {}, a)));
  } else {
    $("eq-bt").replaceChildren(h("div", {class: "empty"}, "Backtest belum dijalankan"));
  }
  const rep = (mk && mk.data_report) || {};
  $("feeds").replaceChildren(h("table", {}, ...Object.entries(rep).map(([k, v]) => h("tr", {}, h("td", {}, k),
    h("td", {class: v.ok ? "pos" : "neg"}, v.ok ? "OK · " + v.source + " · " + v.bars + " candle" : "GAGAL"),
    h("td", {class: "muted", style: "white-space:normal"}, v.ok ? (v.issues || []).join("; ") : v.error)))));
  const fl = (mk && mk.filtered) || {};
  const ks = Object.keys(fl);
  $("filtered").replaceChildren(ks.length ? h("table", {}, ...ks.map(k => h("tr", {}, h("td", {}, k.replaceAll("_", " ")), h("td", {}, fl[k]))))
    : h("div", {class: "muted"}, "—"));
}
main();
