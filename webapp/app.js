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
tg?.setBackgroundColor?.("var(--tg-theme-bg-color, #f8fafc)");

// ========== NAVIGATION ==========
function go(section) {
  currentPage = section;
  PAGES.forEach((p) => {
    const el = $("page-" + p);
    if (el) el.classList.toggle("hidden", p !== section);
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

// ========== SESSION DETECTION ==========
function getNowSession() {
  const h = new Date().getUTCHours();
  if (h >= 0 && h < 8) return { name: "Asian", emoji: "🌏", color: "#f59e0b" };
  if (h >= 7 && h < 12) return { name: "London", emoji: "🌍", color: "#3b82f6" };
  if (h >= 12 && h < 16) return { name: "London + NY", emoji: "🌐", color: "#8b5cf6" };
  if (h >= 16 && h < 21) return { name: "New York", emoji: "🌎", color: "#22c55e" };
  return { name: "Off-hours", emoji: "🌙", color: "#64748b" };
}

function updateSessionBadge() {
  const s = getNowSession();
  const el = $("home-session");
  if (el) {
    el.textContent = s.emoji + " " + s.name;
    el.style.background = s.color + "18";
    el.style.color = s.color;
  }
}

// ========== DIRECTION BUTTONS ==========
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

  if (!draft.direction || !pair || !isFinite(entry) || !isFinite(exit) || entry <= 0 || exit <= 0) {
    return null;
  }

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
    const riskPips = Math.abs(entry - sl) / ps;
    const pipValPerLot = 100000 * ps;
    riskAmt = (settings.balance * settings.risk / 100);
  }

  return { pips, pnl, rr, riskAmt, lot };
}

function updatePreview() {
  const r = calcPreview();
  $("pv-dir").textContent = draft.direction || "—";
  if (!r) {
    $("pv-pips").textContent = "—";
    $("pv-pnl").textContent = "—";
    $("pv-rr").textContent = "—";
    $("pv-risk").textContent = "—";
    return;
  }
  $("pv-pips").textContent = (r.pips >= 0 ? "+" : "") + r.pips.toFixed(1) + " pip";
  $("pv-pnl").textContent = (r.pnl >= 0 ? "+" : "") + r.pnl.toFixed(2) + " " + settings.currency;
  $("pv-rr").textContent = r.rr !== null ? "1:" + r.rr.toFixed(2) : "—";
  $("pv-risk").textContent = r.riskAmt !== null ? r.riskAmt.toFixed(2) + " " + settings.currency : "—";

  // Color coding
  $("pv-pnl").style.color = r.pnl >= 0 ? "var(--tj-success)" : "var(--tj-danger)";
  $("pv-pips").style.color = r.pips >= 0 ? "var(--tj-success)" : "var(--tj-danger)";
}

["in-pair", "in-entry", "in-exit", "in-lot", "in-sl"].forEach((id) => {
  $(id)?.addEventListener("input", updatePreview);
});

// ========== VALIDATION & SEND ==========
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
  setTimeout(() => t.classList.add("hidden"), 2500);
}

$("nav-send")?.addEventListener("click", () => {
  const pair = $("in-pair").value.trim().toUpperCase();
  const entry = parseFloat($("in-entry").value);
  const exit = parseFloat($("in-exit").value);
  const lot = parseFloat($("in-lot").value);
  const slRaw = $("in-sl").value.trim();
  const sl = slRaw === "" ? null : parseFloat(slRaw);
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
  toast("📤 Mengirim ke bot...");

  // Reset form
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
  $("stats-body").innerHTML = '<div class="text-center opacity-50 py-4">Memuat...</div>';

  try {
    const r = await fetch("./stats.json?" + Date.now());
    if (!r.ok) throw new Error(String(r.status));
    const data = await r.json();
    const s = data[period] || { trades: 0 };
    s.currency = data.meta?.currency || "USD";
    renderStats(s);
  } catch (e) {
    $("stats-body").innerHTML = '<div class="text-center opacity-50 py-4">Gagal memuat statistik</div>';
  }
}

function renderStats(s) {
  const cur = s.currency || "USD";
  const wr = s.win_rate ?? 0;
  const pf = s.profit_factor;

  let html = `
    <div class="tj-card mb-3">
      <div class="grid grid-cols-3 gap-2 text-center mb-3">
        <div>
          <div class="text-xl font-bold ${s.net_pnl >= 0 ? 'text-green-500' : 'text-red-500'}">
            ${(s.net_pnl >= 0 ? "+" : "") + (s.net_pnl ?? 0).toFixed(2)}
          </div>
          <div class="text-xs opacity-60">P&L ${cur}</div>
        </div>
        <div>
          <div class="text-xl font-bold">${wr.toFixed(1)}%</div>
          <div class="text-xs opacity-60">Win Rate</div>
        </div>
        <div>
          <div class="text-xl font-bold">${pf === null || pf === undefined ? "∞" : pf.toFixed(2)}</div>
          <div class="text-xs opacity-60">Profit Factor</div>
        </div>
      </div>
      <div class="flex justify-between text-xs opacity-60 mb-1">
        <span>${s.trades ?? 0} trade</span>
        <span>${s.wins ?? 0}W / ${s.losses ?? 0}L</span>
        <span>${(s.net_pips >= 0 ? "+" : "") + (s.net_pips ?? 0).toFixed(1)} pip</span>
      </div>
      <div class="tj-stat-bar">
        <div class="tj-stat-bar-fill" style="width:${wr}%;background:${wr >= 50 ? 'var(--tj-success)' : 'var(--tj-danger)'}"></div>
      </div>
    </div>`;

  // By pair
  const pairs = Object.keys(s.by_pair || {});
  if (pairs.length) {
    html += '<div class="tj-card"><div class="text-xs font-bold opacity-50 uppercase tracking-wider mb-2">Per Pair</div>';
    pairs.forEach((k) => {
      const g = s.by_pair[k];
      const pnl = g.net_pnl ?? 0;
      html += `
        <div class="flex justify-between items-center py-1.5 border-b border-opacity-10 last:border-0">
          <span class="font-mono font-bold">${k}</span>
          <div class="text-right">
            <div class="font-bold ${pnl >= 0 ? 'text-green-500' : 'text-red-500'}">${(pnl >= 0 ? "+" : "") + pnl.toFixed(2)} ${cur}</div>
            <div class="text-xs opacity-50">${g.trades} trade</div>
          </div>
        </div>`;
    });
    html += "</div>";
  }

  $("stats-body").innerHTML = html;
}

// ========== HISTORY ==========
async function loadHistory() {
  $("history-body").innerHTML = '<div class="text-center opacity-50 py-4">Memuat...</div>';
  try {
    const r = await fetch("./trades.json?" + Date.now());
    if (!r.ok) throw new Error(String(r.status));
    const data = await r.json();
    renderHistory(data);
  } catch (e) {
    $("history-body").innerHTML = '<div class="text-center opacity-50 py-4">Gagal memuat riwayat</div>';
  }
}

function renderHistory(data) {
  const trades = data.trades || [];
  const cur = data.currency || "USD";

  if (!trades.length) {
    $("history-body").innerHTML = '<div class="text-center opacity-50 py-8">Belum ada trade</div>';
    return;
  }

  let html = `<div class="text-xs opacity-50 mb-2">${trades.length} trade terakhir</div>`;
  trades.forEach((t) => {
    const pnlColor = t.pnl >= 0 ? "text-green-500" : "text-red-500";
    const dirEmoji = t.dir === "LONG" ? "🔺" : "🔻";
    const tagsHtml = t.tags ? t.tags.split(",").filter(Boolean).map((tag) =>
      `<span class="inline-block text-xs px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300 mr-1">${tag.trim()}</span>`
    ).join("") : "";

    html += `
      <div class="tj-trade-item">
        <div class="flex justify-between items-start">
          <div>
            <span class="font-mono font-bold">${t.pair}</span>
            <span class="text-xs ml-1">${dirEmoji} ${t.dir}</span>
            ${t.r != null ? `<span class="text-xs ml-1 opacity-50">${t.r >= 0 ? "+" : ""}${t.r}R</span>` : ""}
          </div>
          <div class="text-right">
            <div class="font-bold ${pnlColor}">${(t.pnl >= 0 ? "+" : "") + t.pnl.toFixed(2)} ${cur}</div>
            <div class="text-xs opacity-50">${t.pips >= 0 ? "+" : ""}${t.pips.toFixed(1)} pip</div>
          </div>
        </div>
        <div class="flex justify-between items-center mt-1">
          <div class="text-xs opacity-50">${t.time}</div>
          <div>${tagsHtml}</div>
        </div>
        ${t.notes ? `<div class="text-xs opacity-40 mt-1 truncate">${t.notes}</div>` : ""}
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
  const riskPerLot = riskPips * pipValPerLot;
  const rewardPerLot = rewardPips * pipValPerLot;

  // Convert to account currency
  let riskUsd = riskPerLot;
  let rewardUsd = rewardPerLot;
  if (jpy) {
    riskUsd = riskPerLot / (settings.usdjpy || 150);
    rewardUsd = rewardPerLot / (settings.usdjpy || 150);
  }

  // Position size
  const riskAmount = settings.balance * settings.risk / 100;
  let lots = 0;
  if (riskUsd > 0) lots = Math.floor((riskAmount / riskUsd) * 100) / 100;

  // Verdict
  let verdict = "";
  let verdictColor = "";
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
}

$("btn-calc")?.addEventListener("click", runRiskCalc);

// ========== HOME ==========
async function loadHome() {
  updateSessionBadge();

  try {
    const r = await fetch("./settings.json?" + Date.now());
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
  } catch (e) { /* use defaults */ }

  try {
    const r = await fetch("./stats.json?" + Date.now());
    const data = await r.json();
    const m = data.month || { trades: 0 };
    const a = data.all || { trades: 0 };

    $("home-month-count").textContent = m.trades ?? 0;
    $("home-month-count").className = "text-2xl font-bold";

    const mpnl = m.net_pnl ?? 0;
    $("home-month-pnl").textContent = (mpnl >= 0 ? "+" : "") + mpnl.toFixed(0);
    $("home-month-pnl").className = `text-2xl font-bold ${mpnl >= 0 ? 'text-green-500' : 'text-red-500'}`;

    $("home-month-wr").textContent = (m.win_rate ?? 0).toFixed(0) + "%";
    $("home-month-wr").className = "text-2xl font-bold";

    // Streak from all-time
    if (a.trades > 0) {
      const streakEl = $("home-streak");
      const sText = $("streak-text");
      const sSub = $("streak-sub");
      const sEmoji = $("streak-emoji");
      streakEl.classList.remove("hidden");

      // Simple streak calc from recent trades
      try {
        const tr = await fetch("./trades.json?" + Date.now());
        const td = await tr.json();
        const trades = td.trades || [];
        if (trades.length > 0) {
          let streak = 0;
          let streakType = "";
          for (const t of trades.reverse()) {
            const type = t.pnl > 0 ? "win" : "loss";
            if (type === streakType || streakType === "") {
              streak++;
              streakType = type;
            } else break;
          }
          if (streakType === "win") {
            sEmoji.textContent = "🔥";
            sText.textContent = `Win ${streak}x beruntun!`;
            sSub.textContent = "Pertahankan disiplin";
          } else {
            sEmoji.textContent = "❄️";
            sText.textContent = `Loss ${streak}x beruntun`;
            sSub.textContent = "Pertimbangkan istirahat";
          }
        }
      } catch (e) { /* ignore */ }
    }
  } catch (e) { /* use defaults */ }
}

// ========== INIT ==========
loadHome();
go("home");

// Update session every minute
setInterval(updateSessionBadge, 60000);
