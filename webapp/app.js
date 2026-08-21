/* Trading Journal — WebApp Logic */

"use strict";

const tg = window.Telegram?.WebApp;
const $ = (id) => document.getElementById(id);
const PAGES = ["home", "form", "stats", "history", "risk"];

let settings = { balance: 1000, risk: 1, usdjpy: 150, currency: "USD" };
let draft = { direction: null };
let currentPage = "home";

// ========== INIT ==========
tg?.ready();
tg?.expand();
tg?.disableVerticalSwipes?.();
tg?.setHeaderColor?.("secondary_bg_color");
tg?.setBackgroundColor?.("var(--tg-theme-bg-color, #0f172a)");

// ========== NAVIGATION ==========
function go(section) {
  currentPage = section;
  PAGES.forEach((p) => {
    const el = $("page-" + p);
    if (el) {
      el.classList.toggle("hidden", p !== section);
      if (p === section) {
        el.style.animation = "none";
        el.offsetHeight; // trigger reflow
        el.style.animation = "";
      }
    }
  });
  document.querySelectorAll(".tj-nav-item[data-page]").forEach((b) => {
    b.classList.toggle("active", b.dataset.page === section);
  });
  if (section === "stats") loadStats();
  if (section === "history") loadHistory();
  if (section === "home") loadHome();
}

document.querySelectorAll("[data-goto]").forEach((b) => {
  b.addEventListener("click", () => go(b.dataset.goto));
});
$("btn-form")?.addEventListener("click", () => go("form"));

// ========== SESSION ==========
function getNowSession() {
  const h = new Date().getUTCHours();
  if (h >= 0 && h < 8) return { name: "Asian", emoji: "🌏", color: "#f59e0b" };
  if (h >= 7 && h < 12) return { name: "London", emoji: "🌍", color: "#6366f1" };
  if (h >= 12 && h < 16) return { name: "London + NY", emoji: "🌐", color: "#a855f7" };
  if (h >= 16 && h < 21) return { name: "New York", emoji: "🌎", color: "#10b981" };
  return { name: "Off-hours", emoji: "🌙", color: "#64748b" };
}

function updateSessionBadge() {
  const s = getNowSession();
  const el = $("home-session");
  if (el) {
    el.textContent = s.emoji + " " + s.name;
    el.style.background = s.color + "20";
    el.style.color = s.color;
  }
}

// ========== DIRECTION ==========
document.querySelectorAll(".tj-btn-dir").forEach((b) => {
  b.addEventListener("click", () => {
    draft.direction = b.dataset.dir;
    document.querySelectorAll(".tj-btn-dir").forEach((x) =>
      x.classList.toggle("selected", x === b)
    );
    updatePreview();
  });
});

// ========== LIVE PREVIEW ==========
function calcPreview() {
  const pair = $("in-pair").value.trim().toUpperCase();
  const entry = parseFloat($("in-entry").value);
  const exit = parseFloat($("in-exit").value);
  const lot = parseFloat($("in-lot").value) || 0;
  const sl = parseFloat($("in-sl").value) || 0;

  if (!draft.direction || !pair || !isFinite(entry) || !isFinite(exit) || entry <= 0 || exit <= 0) return null;

  const jpy = pair.endsWith("JPY");
  const ps = jpy ? 0.01 : 0.0001;
  const move = draft.direction === "LONG" ? exit - entry : entry - exit;
  const pips = move / ps;
  const pipVal = 100000 * lot * ps;
  let pnl = pips * pipVal;
  if (jpy) pnl = pnl / (settings.usdjpy || 150);

  let rr = null;
  if (isFinite(sl) && sl > 0) {
    const riskPips = Math.abs(entry - sl) / ps;
    const rewardPips = Math.abs(exit - entry) / ps;
    if (riskPips > 0) rr = rewardPips / riskPips;
  }

  let riskAmt = null;
  if (isFinite(sl) && sl > 0 && settings.balance > 0) {
    riskAmt = settings.balance * settings.risk / 100;
  }

  return { pips, pnl, rr, riskAmt, lot };
}

function updatePreview() {
  const r = calcPreview();
  $("pv-dir").textContent = draft.direction || "—";
  if (!r) {
    ["pv-pips", "pv-pnl", "pv-rr", "pv-risk"].forEach((id) => $(id).textContent = "—");
    return;
  }
  $("pv-pips").textContent = (r.pips >= 0 ? "+" : "") + r.pips.toFixed(1) + " pip";
  $("pv-pnl").textContent = (r.pnl >= 0 ? "+" : "") + r.pnl.toFixed(2) + " " + settings.currency;
  $("pv-rr").textContent = r.rr !== null ? "1:" + r.rr.toFixed(2) : "—";
  $("pv-risk").textContent = r.riskAmt !== null ? r.riskAmt.toFixed(2) + " " + settings.currency : "—";

  $("pv-pnl").style.color = r.pnl >= 0 ? "var(--tj-success)" : "var(--tj-danger)";
  $("pv-pips").style.color = r.pips >= 0 ? "var(--tj-success)" : "var(--tj-danger)";

  // Animate preview on update
  const card = $("pv-pnl")?.closest(".tj-preview-card");
  if (card) {
    card.style.animation = "none";
    card.offsetHeight;
    card.style.animation = "glow 0.5s ease";
  }
}

["in-pair", "in-entry", "in-exit", "in-lot", "in-sl"].forEach((id) => {
  $(id)?.addEventListener("input", updatePreview);
});

// ========== SEND ==========
function showError(id, msg) {
  const el = $(id);
  if (!el) return;
  el.textContent = msg || "";
  el.classList.toggle("hidden", !msg);
}

function toast(msg) {
  const t = $("toast");
  if (!t) return;
  t.textContent = msg;
  t.classList.remove("hidden");
  t.style.animation = "none";
  t.offsetHeight;
  t.style.animation = "";
  setTimeout(() => t.classList.add("hidden"), 2500);
}

$("nav-send")?.addEventListener("click", () => {
  const pair = $("in-pair").value.trim().toUpperCase();
  const entry = parseFloat($("in-entry").value);
  const exit = parseFloat($("in-exit").value);
  const lot = parseFloat($("in-lot").value);
  const sl = $("in-sl").value.trim() === "" ? null : parseFloat($("in-sl").value);
  const notes = $("in-notes").value.trim();
  const tags = $("in-tags").value.trim();

  let ok = true;
  showError("err-pair", "");
  showError("err-dir", "");
  if (!/^[A-Z]{6}$/.test(pair)) { showError("err-pair", "Format pair: 6 huruf (mis. EURUSD)"); ok = false; }
  if (!draft.direction) { showError("err-dir", "Pilih arah LONG / SHORT"); ok = false; }
  if (!isFinite(entry) || entry <= 0) { showError("err-pair", "Entry harus angka > 0"); ok = false; }
  if (!isFinite(exit) || exit <= 0) { showError("err-pair", "Exit harus angka > 0"); ok = false; }
  if (!isFinite(lot) || lot <= 0) { showError("err-pair", "Lot harus angka > 0"); ok = false; }
  if (!ok) return;

  const payload = {
    action: "add_trade",
    pair, direction: draft.direction, entry, exit, lot,
    sl: sl || null, notes: notes || null, tags: tags || null,
  };

  tg?.sendData(JSON.stringify(payload));
  toast("📤 Trade dikirim!");

  setTimeout(() => {
    $("in-pair").value = "";
    $("in-entry").value = "";
    $("in-exit").value = "";
    $("in-sl").value = "";
    $("in-notes").value = "";
    $("in-tags").value = "";
    draft.direction = null;
    document.querySelectorAll(".tj-btn-dir").forEach((x) => x.classList.remove("selected"));
    updatePreview();
  }, 500);
});

// ========== STATISTICS ==========
async function loadStats() {
  const sel = $("sel-period");
  const period = sel ? sel.value : "all";
  $("stats-body").innerHTML = '<div class="text-center opacity-40 py-6 anim-fade-in">Memuat...</div>';

  try {
    const r = await fetch("/stats.json?" + Date.now());
    if (!r.ok) throw new Error(String(r.status));
    const data = await r.json();
    const s = data[period] || { trades: 0 };
    s.currency = data.meta?.currency || "USD";
    renderStats(s);
  } catch (e) {
    $("stats-body").innerHTML = '<div class="text-center opacity-40 py-6">Gagal memuat</div>';
  }
}

function renderStats(s) {
  const cur = s.currency || "USD";
  const wr = s.win_rate ?? 0;
  const pf = s.profit_factor;

  let html = `
    <div class="tj-card mb-3 anim-fade-up">
      <div class="grid grid-cols-3 gap-2 text-center mb-3">
        <div>
          <div class="text-xl font-bold anim-fade-up ${s.net_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}">
            ${(s.net_pnl >= 0 ? "+" : "") + (s.net_pnl ?? 0).toFixed(2)}
          </div>
          <div class="text-[0.65rem] opacity-40 mt-0.5">P&L ${cur}</div>
        </div>
        <div>
          <div class="text-xl font-bold anim-fade-up">${wr.toFixed(1)}%</div>
          <div class="text-[0.65rem] opacity-40 mt-0.5">Win Rate</div>
        </div>
        <div>
          <div class="text-xl font-bold anim-fade-up">${pf === null || pf === undefined ? "∞" : pf.toFixed(2)}</div>
          <div class="text-[0.65rem] opacity-40 mt-0.5">Profit Factor</div>
        </div>
      </div>
      <div class="flex justify-between text-[0.7rem] opacity-50 mb-1.5">
        <span>${s.trades ?? 0} trade</span>
        <span>${s.wins ?? 0}W / ${s.losses ?? 0}L</span>
        <span>${(s.net_pips >= 0 ? "+" : "") + (s.net_pips ?? 0).toFixed(1)} pip</span>
      </div>
      <div class="tj-stat-bar">
        <div class="tj-stat-bar-fill" style="width:${wr}%;background:${wr >= 50 ? 'var(--tj-success)' : 'var(--tj-danger)'}"></div>
      </div>
    </div>`;

  const pairs = Object.keys(s.by_pair || {});
  if (pairs.length) {
    html += '<div class="tj-card anim-fade-up" style="animation-delay:50ms"><div class="text-[0.65rem] font-bold opacity-40 uppercase tracking-widest mb-2">Per Pair</div>';
    pairs.forEach((k, i) => {
      const g = s.by_pair[k];
      const pnl = g.net_pnl ?? 0;
      html += `
        <div class="flex justify-between items-center py-1.5 border-b border-white/5 last:border-0 anim-slide-right" style="animation-delay:${i * 50}ms">
          <span class="font-mono font-bold">${k}</span>
          <div class="text-right">
            <div class="font-bold ${pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}">${(pnl >= 0 ? "+" : "") + pnl.toFixed(2)} ${cur}</div>
            <div class="text-[0.65rem] opacity-40">${g.trades} trade</div>
          </div>
        </div>`;
    });
    html += "</div>";
  }

  $("stats-body").innerHTML = html;
}

// ========== HISTORY ==========
async function loadHistory() {
  $("history-body").innerHTML = '<div class="text-center opacity-40 py-6 anim-fade-in">Memuat...</div>';
  try {
    const r = await fetch("/trades.json?" + Date.now());
    if (!r.ok) throw new Error(String(r.status));
    const data = await r.json();
    renderHistory(data);
  } catch (e) {
    $("history-body").innerHTML = '<div class="text-center opacity-40 py-6">Gagal memuat</div>';
  }
}

function renderHistory(data) {
  const trades = data.trades || [];
  const cur = data.currency || "USD";

  if (!trades.length) {
    $("history-body").innerHTML = '<div class="text-center opacity-30 py-12 text-lg">Belum ada trade</div>';
    return;
  }

  let html = `<div class="text-[0.7rem] opacity-40 mb-2">${trades.length} trade terakhir</div>`;
  trades.forEach((t, i) => {
    const pnlColor = t.pnl >= 0 ? "text-emerald-400" : "text-red-400";
    const dirEmoji = t.dir === "LONG" ? "🔺" : "🔻";
    const tagsHtml = t.tags ? t.tags.split(",").filter(Boolean).map((tag) =>
      `<span class="tj-tag">${tag.trim()}</span>`
    ).join("") : "";

    html += `
      <div class="tj-trade-item anim-slide-right" style="animation-delay:${Math.min(i * 30, 300)}ms">
        <div class="flex justify-between items-start">
          <div>
            <span class="font-mono font-bold">${t.pair}</span>
            <span class="text-xs ml-1">${dirEmoji} ${t.dir}</span>
            ${t.r != null ? `<span class="text-[0.65rem] ml-1 opacity-40">${t.r >= 0 ? "+" : ""}${t.r}R</span>` : ""}
          </div>
          <div class="text-right">
            <div class="font-bold ${pnlColor}">${(t.pnl >= 0 ? "+" : "") + t.pnl.toFixed(2)} ${cur}</div>
            <div class="text-[0.65rem] opacity-40">${t.pips >= 0 ? "+" : ""}${t.pips.toFixed(1)} pip</div>
          </div>
        </div>
        <div class="flex justify-between items-center mt-1">
          <div class="text-[0.65rem] opacity-40">${t.time}</div>
          <div>${tagsHtml}</div>
        </div>
        ${t.notes ? `<div class="text-[0.65rem] opacity-30 mt-1 truncate">${t.notes}</div>` : ""}
      </div>`;
  });

  $("history-body").innerHTML = html;
}

// ========== RISK CALCULATOR ==========
function runRiskCalc() {
  const pair = ($("rc-pair").value || "").trim().toUpperCase();
  const entry = parseFloat($("rc-entry").value);
  const stop = parseFloat($("rc-stop").value);
  const target = parseFloat($("rc-target").value);

  if (!pair || !/^[A-Z]{6}$/.test(pair) || !isFinite(entry) || !isFinite(stop) || !isFinite(target)) {
    toast("❌ Isi semua field dengan benar");
    return;
  }

  const jpy = pair.endsWith("JPY");
  const ps = jpy ? 0.01 : 0.0001;
  const riskPips = Math.abs(entry - stop) / ps;
  const rewardPips = Math.abs(target - entry) / ps;

  if (riskPips <= 0) { toast("❌ Stop harus berbeda dari entry"); return; }

  const rr = rewardPips / riskPips;
  const pipValPerLot = 100000 * ps;
  let riskUsd = riskPips * pipValPerLot;
  let rewardUsd = rewardPips * pipValPerLot;
  if (jpy) {
    riskUsd /= (settings.usdjpy || 150);
    rewardUsd /= (settings.usdjpy || 150);
  }

  const riskAmount = settings.balance * settings.risk / 100;
  let lots = riskUsd > 0 ? Math.floor((riskAmount / riskUsd) * 100) / 100 : 0;

  let verdict = "", verdictColor = "";
  if (rr >= 3) { verdict = "🟢 Sangat Bagus"; verdictColor = "var(--tj-success)"; }
  else if (rr >= 2) { verdict = "🟢 Bagus"; verdictColor = "var(--tj-success)"; }
  else if (rr >= 1.5) { verdict = "🟡 Cukup"; verdictColor = "var(--tj-warning)"; }
  else if (rr >= 1) { verdict = "🟠 Marginal"; verdictColor = "var(--tj-warning)"; }
  else { verdict = "🔴 Risk Tinggi"; verdictColor = "var(--tj-danger)"; }

  $("rc-lots").textContent = lots.toFixed(2);
  $("rc-risk-pip").textContent = riskPips.toFixed(1) + " pip";
  $("rc-reward-pip").textContent = rewardPips.toFixed(1) + " pip";
  $("rc-rr").textContent = "1:" + rr.toFixed(2);
  $("rc-risk-usd").textContent = riskUsd.toFixed(2) + " " + settings.currency;
  $("rc-reward-usd").textContent = rewardUsd.toFixed(2) + " " + settings.currency;
  $("rc-verdict").textContent = verdict;
  $("rc-verdict").style.color = verdictColor;
  $("rc-result").classList.remove("hidden");
  $("rc-result").style.animation = "none";
  $("rc-result").offsetHeight;
  $("rc-result").style.animation = "fadeInUp 0.4s ease-out";
}

$("btn-calc")?.addEventListener("click", runRiskCalc);

// ========== HOME ==========
async function loadHome() {
  updateSessionBadge();

  try {
    const r = await fetch("/settings.json?" + Date.now());
    const st = await r.json();
    settings = {
      balance: Number(st.balance) || 1000,
      risk: Number(st.risk_percent) || 1,
      usdjpy: Number(st.usdjpy_rate) || 150,
      currency: st.currency || "USD",
    };
    $("home-balance").textContent = settings.balance.toLocaleString() + " " + settings.currency;
    $("home-risk").textContent = settings.risk + "%";
    $("home-usdjpy").textContent = settings.usdjpy;
  } catch (e) {}

  try {
    const r = await fetch("/stats.json?" + Date.now());
    const data = await r.json();
    const m = data.month || { trades: 0 };

    $("home-month-count").textContent = m.trades ?? 0;

    const mpnl = m.net_pnl ?? 0;
    $("home-month-pnl").textContent = (mpnl >= 0 ? "+" : "") + mpnl.toFixed(0);
    $("home-month-pnl").className = `text-2xl font-bold anim-fade-up ${mpnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`;

    $("home-month-wr").textContent = (m.win_rate ?? 0).toFixed(0) + "%";

    // Streak
    try {
      const tr = await fetch("/trades.json?" + Date.now());
      const td = await tr.json();
      const trades = td.trades || [];
      if (trades.length > 0) {
        let streak = 0, streakType = "";
        const reversed = [...trades].reverse();
        for (const t of reversed) {
          const type = t.pnl > 0 ? "win" : "loss";
          if (type === streakType || streakType === "") { streak++; streakType = type; } else break;
        }
        const streakEl = $("home-streak");
        streakEl.classList.remove("hidden");
        if (streakType === "win") {
          $("streak-emoji").textContent = "🔥";
          $("streak-text").textContent = `Win ${streak}x beruntun!`;
          $("streak-sub").textContent = "Pertahankan disiplin";
        } else {
          $("streak-emoji").textContent = "❄️";
          $("streak-text").textContent = `Loss ${streak}x beruntun`;
          $("streak-sub").textContent = "Pertimbangkan istirahat";
        }
      }
    } catch (e) {}
  } catch (e) {}
}

// ========== INIT ==========
loadHome();
go("home");
setInterval(updateSessionBadge, 60000);
