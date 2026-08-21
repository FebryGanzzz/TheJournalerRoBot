/* Trading Journal Pro — App Logic & Telegram WebApp Bridge */

"use strict";

(function () {
  // Telegram WebApp Object Safe Reference
  const tg = window.Telegram?.WebApp;
  const $ = (id) => document.getElementById(id);
  const PAGES = ["home", "form", "stats", "history", "risk"];

  let state = {
    currentPage: "home",
    settings: { balance: 1000, risk: 1.0, usdjpy: 150.0, currency: "USD" },
    draft: { pair: "EURUSD", direction: null, entry: null, exit: null, lot: 0.10, sl: null, notes: "", tags: "" },
    selectedPeriod: "all",
  };

  // ========== HAPTIC FEEDBACK ==========
  function haptic(type = "light") {
    try {
      if (!tg?.HapticFeedback) return;
      if (type === "selection") tg.HapticFeedback.selectionChanged();
      else if (type === "success") tg.HapticFeedback.notificationOccurred("success");
      else if (type === "warning") tg.HapticFeedback.notificationOccurred("warning");
      else if (type === "error") tg.HapticFeedback.notificationOccurred("error");
      else tg.HapticFeedback.impactOccurred(type);
    } catch (e) {
      // ignore
    }
  }

  // ========== INITIALIZATION ==========
  function initTelegram() {
    try {
      tg?.ready();
      tg?.expand();
      tg?.enableClosingConfirmation?.();
      
      // Set Header and Background color safely using supported hex or keys
      if (tg?.setHeaderColor) {
        tg.setHeaderColor("secondary_bg_color");
      }
      if (tg?.setBackgroundColor) {
        tg.setBackgroundColor("#0a0d14");
      }

      // Sync Telegram BackButton
      if (tg?.BackButton) {
        tg.BackButton.onClick(() => {
          haptic("light");
          go("home");
        });
      }

      // Sync Telegram MainButton
      if (tg?.MainButton) {
        tg.MainButton.setParams({
          text: "🚀 SIMPAN TRADE",
          color: "#6366f1",
          text_color: "#ffffff",
          is_active: true,
          is_visible: false,
        });
        tg.MainButton.onClick(submitTrade);
      }
    } catch (e) {
      console.warn("Telegram WebApp init error:", e);
    }
  }

  // ========== NAVIGATION ==========
  function go(pageId) {
    if (!PAGES.includes(pageId)) pageId = "home";
    state.currentPage = pageId;

    PAGES.forEach((p) => {
      const el = $("page-" + p);
      if (el) {
        if (p === pageId) {
          el.classList.add("active");
        } else {
          el.classList.remove("active");
        }
      }
    });

    // Update Bottom Nav Active State
    document.querySelectorAll(".nav-tab, .nav-tab-center").forEach((tab) => {
      if (tab.dataset.page === pageId) {
        tab.classList.add("active");
      } else {
        tab.classList.remove("active");
      }
    });

    // Update Telegram BackButton & MainButton visibility
    if (tg?.BackButton) {
      if (pageId === "home") {
        tg.BackButton.hide();
      } else {
        tg.BackButton.show();
      }
    }

    if (tg?.MainButton) {
      if (pageId === "form") {
        tg.MainButton.show();
      } else {
        tg.MainButton.hide();
      }
    }

    // Scroll to top
    window.scrollTo({ top: 0, behavior: "smooth" });

    // Load data for specific pages
    if (pageId === "home") loadHome();
    else if (pageId === "stats") loadStats();
    else if (pageId === "history") loadHistory();
    else if (pageId === "risk") runRiskCalc();
  }

  // Event Listeners for Navigation Buttons
  document.querySelectorAll("[data-goto]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      haptic("selection");
      go(btn.dataset.goto);
    });
  });

  // ========== TOAST NOTIFICATION ==========
  let toastTimer = null;
  function toast(msg, icon = "✨") {
    const t = $("toast");
    const txt = $("toast-text");
    if (!t || !txt) return;

    txt.textContent = msg;
    const iconEl = t.querySelector(".toast-icon");
    if (iconEl) iconEl.textContent = icon;

    t.classList.remove("hidden");
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      t.classList.add("hidden");
    }, 2800);
  }

  // ========== MARKET SESSIONS ==========
  function getMarketSession() {
    const now = new Date();
    const h = now.getUTCHours();
    if (h >= 0 && h < 7) return { name: "Tokyo / Asian", color: "#f59e0b" };
    if (h >= 7 && h < 12) return { name: "London Open", color: "#6366f1" };
    if (h >= 12 && h < 16) return { name: "London + NY", color: "#8b5cf6" };
    if (h >= 16 && h < 21) return { name: "New York Open", color: "#10b981" };
    return { name: "Market Off-hours", color: "#64748b" };
  }

  function updateMarketSession() {
    const s = getMarketSession();
    const lbl = $("session-label");
    const badge = $("home-session");
    if (lbl) lbl.textContent = s.name;
    if (badge) {
      badge.style.color = s.color;
      badge.style.borderColor = s.color + "40";
      badge.style.backgroundColor = s.color + "15";
    }
  }

  // ========== FORM & LIVE PREVIEW ==========
  function getPipDetails(pair) {
    const isJpy = pair.endsWith("JPY");
    return {
      pipSize: isJpy ? 0.01 : 0.0001,
      decimals: isJpy ? 2 : 4,
    };
  }

  function setupFormControls() {
    // Quick Pair Chips
    document.querySelectorAll(".pair-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        haptic("selection");
        const pair = chip.dataset.pair;
        $("in-pair").value = pair;
        
        document.querySelectorAll(".pair-chip").forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");

        const info = getPipDetails(pair);
        $("pair-pip-type").textContent = info.pipSize;
        
        // Auto adjust step in price inputs
        $("in-entry").step = String(info.pipSize);
        $("in-exit").step = String(info.pipSize);
        if ($("in-sl")) $("in-sl").step = String(info.pipSize);

        updateLiveCalc();
      });
    });

    // Direction Buttons
    document.querySelectorAll(".dir-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        haptic("medium");
        const dir = btn.dataset.dir;
        state.draft.direction = dir;

        document.querySelectorAll(".dir-btn").forEach((b) => b.classList.remove("selected"));
        btn.classList.add("selected");
        
        $("err-dir").classList.add("hidden");
        updateLiveCalc();
      });
    });

    // Live calculation on input typing
    ["in-pair", "in-entry", "in-exit", "in-lot", "in-sl"].forEach((id) => {
      const el = $(id);
      if (el) {
        el.addEventListener("input", () => {
          if (id === "in-pair") {
            const pair = el.value.trim().toUpperCase();
            if (pair.length >= 3) {
              const info = getPipDetails(pair);
              $("pair-pip-type").textContent = info.pipSize;
            }
          }
          updateLiveCalc();
        });
      }
    });

    // Submit button in form
    $("btn-submit-trade")?.addEventListener("click", () => {
      haptic("medium");
      submitTrade();
    });
  }

  function calculateFormPnl() {
    const pair = ($("in-pair")?.value || "").trim().toUpperCase();
    const entry = parseFloat($("in-entry")?.value);
    const exit = parseFloat($("in-exit")?.value);
    const lot = parseFloat($("in-lot")?.value) || 0;
    const sl = parseFloat($("in-sl")?.value);
    const dir = state.draft.direction;

    if (!dir || !pair || isNaN(entry) || isNaN(exit) || entry <= 0 || exit <= 0 || lot <= 0) {
      return null;
    }

    const { pipSize } = getPipDetails(pair);
    const priceDiff = dir === "LONG" ? (exit - entry) : (entry - exit);
    const pips = priceDiff / pipSize;
    const contractUnits = 100000 * lot;
    let pnl = (priceDiff / pipSize) * (contractUnits * pipSize);

    // Convert JPY quote to USD
    if (pair.endsWith("JPY")) {
      pnl = pnl / (state.settings.usdjpy || 150.0);
    }

    let rr = null;
    let riskAtSl = null;
    if (!isNaN(sl) && sl > 0 && sl !== entry) {
      const riskPips = Math.abs(entry - sl) / pipSize;
      const rewardPips = Math.abs(exit - entry) / pipSize;
      if (riskPips > 0) {
        rr = rewardPips / riskPips;
      }
      let rawRisk = riskPips * (contractUnits * pipSize);
      if (pair.endsWith("JPY")) {
        rawRisk /= (state.settings.usdjpy || 150.0);
      }
      riskAtSl = rawRisk;
    }

    return { pair, dir, pips, pnl, rr, riskAtSl };
  }

  function updateLiveCalc() {
    const res = calculateFormPnl();
    const badge = $("pv-status-badge");
    const pnlEl = $("pv-pnl");
    const pipsEl = $("pv-pips");
    const rrEl = $("pv-rr");
    const riskEl = $("pv-risk");

    if (!res) {
      if (badge) {
        badge.className = "calc-badge neutral";
        badge.textContent = "Menunggu Input";
      }
      if (pnlEl) pnlEl.textContent = "—";
      if (pipsEl) pipsEl.textContent = "—";
      if (rrEl) rrEl.textContent = "—";
      if (riskEl) riskEl.textContent = "—";
      return;
    }

    const isProfit = res.pnl >= 0;
    if (badge) {
      badge.className = isProfit ? "calc-badge win" : "calc-badge loss";
      badge.textContent = isProfit ? "PROFIT" : "LOSS";
    }

    if (pnlEl) {
      pnlEl.textContent = `${isProfit ? "+" : ""}${res.pnl.toFixed(2)} ${state.settings.currency}`;
      pnlEl.style.color = isProfit ? "var(--color-emerald)" : "var(--color-rose)";
    }

    if (pipsEl) {
      pipsEl.textContent = `${res.pips >= 0 ? "+" : ""}${res.pips.toFixed(1)} pip`;
      pipsEl.style.color = res.pips >= 0 ? "var(--color-emerald)" : "var(--color-rose)";
    }

    if (rrEl) {
      rrEl.textContent = res.rr !== null ? `1 : ${res.rr.toFixed(2)}` : "—";
    }

    if (riskEl) {
      riskEl.textContent = res.riskAtSl !== null ? `-$${res.riskAtSl.toFixed(2)}` : "—";
    }
  }

  // ========== SUBMIT TRADE ==========
  function submitTrade() {
    const pair = ($("in-pair")?.value || "").trim().toUpperCase();
    const entry = parseFloat($("in-entry")?.value);
    const exit = parseFloat($("in-exit")?.value);
    const lot = parseFloat($("in-lot")?.value);
    const slRaw = $("in-sl")?.value?.trim();
    const sl = slRaw ? parseFloat(slRaw) : null;
    const notes = ($("in-notes")?.value || "").trim();
    const tags = ($("in-tags")?.value || "").trim();
    const dir = state.draft.direction;

    let valid = true;

    // Validation
    const errPair = $("err-pair");
    const errDir = $("err-dir");
    if (errPair) errPair.classList.add("hidden");
    if (errDir) errDir.classList.add("hidden");

    if (!dir) {
      if (errDir) {
        errDir.textContent = "Pilih arah posisi (LONG atau SHORT)";
        errDir.classList.remove("hidden");
      }
      valid = false;
    }

    if (!pair || !/^[A-Z]{6}$/.test(pair)) {
      if (errPair) {
        errPair.textContent = "Pair harus 6 huruf standar (misal: EURUSD)";
        errPair.classList.remove("hidden");
      }
      valid = false;
    }

    if (isNaN(entry) || entry <= 0 || isNaN(exit) || exit <= 0 || isNaN(lot) || lot <= 0) {
      if (errPair) {
        errPair.textContent = "Entry, Exit, dan Lot harus berupa angka positif!";
        errPair.classList.remove("hidden");
      }
      valid = false;
    }

    if (!valid) {
      haptic("error");
      toast("Periksa kembali input Anda", "⚠️");
      return;
    }

    const payload = {
      action: "add_trade",
      pair,
      direction: dir,
      entry,
      exit,
      lot,
      sl: sl && !isNaN(sl) ? sl : null,
      notes: notes || null,
      tags: tags || null,
    };

    // Send payload to Telegram Bot
    if (tg?.sendData) {
      tg.sendData(JSON.stringify(payload));
      haptic("success");
      toast("Trade berhasil dikirim!", "✅");
    } else {
      // Standalone browser testing fallback
      haptic("success");
      toast("Trade tersimpan (mode preview)", "✅");
      console.log("WebApp Payload:", payload);
    }

    // Reset Form
    setTimeout(() => {
      $("in-pair").value = "EURUSD";
      $("in-entry").value = "";
      $("in-exit").value = "";
      if ($("in-sl")) $("in-sl").value = "";
      if ($("in-notes")) $("in-notes").value = "";
      if ($("in-tags")) $("in-tags").value = "";
      state.draft.direction = null;
      document.querySelectorAll(".dir-btn").forEach((b) => b.classList.remove("selected"));
      updateLiveCalc();
      go("home");
    }, 600);
  }

  // ========== STATS LOADER & RENDERER ==========
  async function loadStats() {
    const container = $("stats-content");
    if (!container) return;

    container.innerHTML = `
      <div class="loading-state">
        <div class="spinner"></div>
        <span>Mengambil data statistik...</span>
      </div>`;

    try {
      const res = await fetch("/stats.json?" + Date.now());
      if (!res.ok) throw new Error("Status " + res.status);
      const data = await res.json();
      renderStats(data);
    } catch (e) {
      container.innerHTML = `
        <div class="glass-card text-center" style="padding: 24px 16px;">
          <div style="font-size: 2rem; margin-bottom: 8px;">📊</div>
          <div style="font-weight: 700; color: #fff; margin-bottom: 4px;">Belum Ada Data Statistik</div>
          <div style="font-size: 0.78rem; color: var(--text-dim);">Mulai catat trade untuk melihat analisis performa lengkap.</div>
        </div>`;
    }
  }

  function renderStats(data) {
    const container = $("stats-content");
    if (!container) return;

    const period = state.selectedPeriod;
    const cur = data.meta?.currency || state.settings.currency || "USD";
    const st = data[period] || { trades: 0, wins: 0, losses: 0, win_rate: 0, net_pnl: 0, net_pips: 0, profit_factor: null, avg_r: null, by_pair: {} };

    const netPnl = st.net_pnl ?? 0;
    const isProf = netPnl >= 0;
    const wr = st.win_rate ?? 0;
    const pf = st.profit_factor;

    let html = `
      <div class="glass-card">
        <div class="card-header-compact">
          <span class="card-tag">PERFORMA UTAMA (${period.toUpperCase()})</span>
          <span class="badge-pill">${st.trades} Trade</span>
        </div>

        <div class="hero-stats-grid">
          <div class="hero-stat-box">
            <span class="stat-label">Net Profit / Loss</span>
            <div class="stat-value-hero ${isProf ? 'text-emerald' : 'text-rose'}">
              ${isProf ? '+' : ''}${netPnl.toFixed(2)} ${cur}
            </div>
            <span class="stat-foot">${(st.net_pips >= 0 ? '+' : '') + (st.net_pips ?? 0).toFixed(1)} Pips</span>
          </div>
          <div class="hero-divider"></div>
          <div class="hero-stat-box">
            <span class="stat-label">Win Rate</span>
            <div class="stat-value-hero ${wr >= 50 ? 'text-emerald' : 'text-rose'}">
              ${wr.toFixed(1)}%
            </div>
            <span class="stat-foot">${st.wins}W / ${st.losses}L</span>
          </div>
        </div>

        <div class="progress-bar-container">
          <div class="progress-bar-track">
            <div class="progress-bar-fill" style="width: ${Math.min(wr, 100)}%; background: ${wr >= 50 ? 'var(--color-emerald)' : 'var(--color-rose)'};"></div>
          </div>
        </div>
      </div>

      <div class="stat-grid-3">
        <div class="stat-mini-box">
          <div class="stat-mini-val font-mono">${pf !== null && pf !== undefined ? pf.toFixed(2) : '—'}</div>
          <div class="stat-mini-lbl">Profit Factor</div>
        </div>
        <div class="stat-mini-box">
          <div class="stat-mini-val font-mono">${st.avg_r !== null && st.avg_r !== undefined ? (st.avg_r >= 0 ? '+' : '') + st.avg_r.toFixed(2) + 'R' : '—'}</div>
          <div class="stat-mini-lbl">Avg R-Multiple</div>
        </div>
        <div class="stat-mini-box">
          <div class="stat-mini-val font-mono">${st.trades}</div>
          <div class="stat-mini-lbl">Total Selesai</div>
        </div>
      </div>
    `;

    // Breakdown per Pair
    const pairs = Object.keys(st.by_pair || {});
    if (pairs.length > 0) {
      html += `
        <div class="glass-card mt-3">
          <div class="card-header-compact">
            <span class="card-tag">BREAKDOWN PER PAIR</span>
          </div>
      `;

      pairs.forEach((p) => {
        const item = st.by_pair[p];
        const pPnl = item.net_pnl ?? 0;
        const pIsWin = pPnl >= 0;
        html += `
          <div class="pair-stat-row">
            <div>
              <div class="pair-name font-mono">${p}</div>
              <div style="font-size: 0.7rem; color: var(--text-dim);">${item.trades} transaksi</div>
            </div>
            <div style="text-align: right;">
              <div class="pair-pnl font-mono ${pIsWin ? 'text-emerald' : 'text-rose'}">
                ${pIsWin ? '+' : ''}${pPnl.toFixed(2)} ${cur}
              </div>
            </div>
          </div>
        `;
      });

      html += `</div>`;
    }

    container.innerHTML = html;
  }

  // ========== HISTORY LOADER & RENDERER ==========
  async function loadHistory() {
    const container = $("history-content");
    if (!container) return;

    container.innerHTML = `
      <div class="loading-state">
        <div class="spinner"></div>
        <span>Mengambil riwayat trade...</span>
      </div>`;

    try {
      const res = await fetch("/trades.json?" + Date.now());
      if (!res.ok) throw new Error("Status " + res.status);
      const data = await res.json();
      renderHistory(data);
    } catch (e) {
      container.innerHTML = `
        <div class="glass-card text-center" style="padding: 24px 16px;">
          <div style="font-size: 2rem; margin-bottom: 8px;">📋</div>
          <div style="font-weight: 700; color: #fff; margin-bottom: 4px;">Belum Ada Riwayat</div>
          <div style="font-size: 0.78rem; color: var(--text-dim);">Trade yang Anda catat akan otomatis muncul di sini.</div>
        </div>`;
    }
  }

  function renderHistory(data) {
    const container = $("history-content");
    if (!container) return;

    const trades = data.trades || [];
    const cur = data.currency || state.settings.currency || "USD";

    if (trades.length === 0) {
      container.innerHTML = `
        <div class="glass-card text-center" style="padding: 28px 16px;">
          <div style="font-size: 2.2rem; margin-bottom: 8px;">📝</div>
          <div style="font-weight: 700; color: #fff; margin-bottom: 4px;">Belum Ada Transaksi</div>
          <div style="font-size: 0.78rem; color: var(--text-dim); margin-bottom: 16px;">Mulai dengan mencatat trade pertama Anda sekarang.</div>
          <button class="btn-primary-glow" data-goto="form" style="height: 42px; font-size: 0.88rem;">➕ Catat Trade Baru</button>
        </div>`;
      container.querySelector("[data-goto='form']")?.addEventListener("click", () => go("form"));
      return;
    }

    let html = "";
    trades.forEach((t) => {
      const isWin = t.pnl >= 0;
      const isLong = t.dir === "LONG";
      const tagsList = t.tags ? t.tags.split(",").filter(Boolean) : [];

      html += `
        <div class="trade-card-item">
          <div class="trade-card-head">
            <div class="trade-pair-badge">
              <span class="trade-dir-tag ${isLong ? 'tag-long' : 'tag-short'} font-mono">${t.dir}</span>
              <strong class="font-mono" style="font-size: 1rem; color: #fff;">${t.pair}</strong>
              <span style="font-size: 0.75rem; color: var(--text-dim); font-weight: 600;">${t.lot} Lot</span>
            </div>
            <div class="trade-pnl-badge font-mono ${isWin ? 'text-emerald' : 'text-rose'}">
              ${isWin ? '+' : ''}${t.pnl.toFixed(2)} ${cur}
            </div>
          </div>

          <div class="trade-card-details">
            <div>
              <span class="font-mono">${t.entry} → ${t.exit}</span>
              ${t.sl ? `<span style="color: var(--text-dim); margin-left: 4px;">(SL: ${t.sl})</span>` : ''}
            </div>
            <div style="text-align: right;">
              <span class="font-mono ${t.pips >= 0 ? 'text-emerald' : 'text-rose'}">${t.pips >= 0 ? '+' : ''}${t.pips.toFixed(1)} pip</span>
              ${t.r !== null && t.r !== undefined ? `<span style="color: var(--accent-primary); margin-left: 6px; font-weight: 700;">${t.r >= 0 ? '+' : ''}${t.r}R</span>` : ''}
            </div>
          </div>

          ${tagsList.length > 0 ? `
            <div class="trade-tags-row">
              ${tagsList.map((tag) => `<span class="custom-tag">${tag.trim()}</span>`).join('')}
            </div>
          ` : ''}

          ${t.notes ? `<div class="trade-notes">${t.notes}</div>` : ''}

          <div style="font-size: 0.65rem; color: var(--text-dim); margin-top: 6px; text-align: right;">
            ${t.time}
          </div>
        </div>
      `;
    });

    container.innerHTML = html;
  }

  // ========== RISK CALCULATOR ==========
  function setupRiskCalc() {
    document.querySelectorAll(".risk-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        haptic("selection");
        document.querySelectorAll(".risk-chip").forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");
        state.settings.risk = parseFloat(chip.dataset.risk) || 1.0;
        runRiskCalc();
      });
    });

    ["rc-pair", "rc-entry", "rc-stop", "rc-target"].forEach((id) => {
      $(id)?.addEventListener("input", runRiskCalc);
    });
  }

  function runRiskCalc() {
    const pair = ($("rc-pair")?.value || "").trim().toUpperCase();
    const entry = parseFloat($("rc-entry")?.value);
    const stop = parseFloat($("rc-stop")?.value);
    const target = parseFloat($("rc-target")?.value);

    if (!pair || isNaN(entry) || isNaN(stop) || entry <= 0 || stop <= 0) {
      return;
    }

    const { pipSize } = getPipDetails(pair);
    const riskPips = Math.abs(entry - stop) / pipSize;
    if (riskPips <= 0) return;

    let rewardPips = 0;
    let rr = 0;
    if (!isNaN(target) && target > 0) {
      rewardPips = Math.abs(target - entry) / pipSize;
      rr = rewardPips / riskPips;
    }

    // 1 pip value per standard lot (100,000)
    let pipValPerLot = 100000 * pipSize;
    let riskUsdPerLot = riskPips * pipValPerLot;
    let rewardUsdPerLot = rewardPips * pipValPerLot;

    if (pair.endsWith("JPY")) {
      riskUsdPerLot /= (state.settings.usdjpy || 150.0);
      rewardUsdPerLot /= (state.settings.usdjpy || 150.0);
    }

    const maxRiskAmount = (state.settings.balance * state.settings.risk) / 100.0;
    const safeLot = riskUsdPerLot > 0 ? Math.floor((maxRiskAmount / riskUsdPerLot) * 100) / 100 : 0.01;

    const totalRiskUsd = safeLot * riskUsdPerLot;
    const totalRewardUsd = safeLot * rewardUsdPerLot;

    // Update UI
    $("rc-lots").textContent = safeLot.toFixed(2);
    $("rc-risk-pip").textContent = riskPips.toFixed(1);
    $("rc-reward-pip").textContent = rewardPips > 0 ? rewardPips.toFixed(1) : "—";
    $("rc-rr").textContent = rr > 0 ? `1 : ${rr.toFixed(2)}` : "—";
    $("rc-risk-usd").textContent = `-$${totalRiskUsd.toFixed(2)}`;
    $("rc-reward-usd").textContent = totalRewardUsd > 0 ? `+$${totalRewardUsd.toFixed(2)}` : "—";

    const badge = $("rc-verdict-badge");
    if (badge) {
      if (rr >= 2.5) {
        badge.className = "badge-pill bg-emerald";
        badge.textContent = "R:R SANGAT BAGUS";
      } else if (rr >= 1.5) {
        badge.className = "badge-pill bg-emerald";
        badge.textContent = "R:R BAGUS";
      } else if (rr >= 1.0) {
        badge.className = "badge-pill bg-amber";
        badge.textContent = "R:R SEDANG";
      } else {
        badge.className = "badge-pill bg-rose";
        badge.textContent = "RISK TINGGI";
      }
    }
  }

  // ========== HOME LOADER ==========
  async function loadHome() {
    updateMarketSession();

    // Fetch settings
    try {
      const res = await fetch("/settings.json?" + Date.now());
      if (res.ok) {
        const s = await res.json();
        state.settings.balance = Number(s.balance) || 1000;
        state.settings.risk = Number(s.risk_percent) || 1.0;
        state.settings.usdjpy = Number(s.usdjpy_rate) || 150.0;
        state.settings.currency = s.currency || "USD";

        if ($("home-balance")) $("home-balance").textContent = `$${state.settings.balance.toLocaleString()}`;
        if ($("home-risk")) $("home-risk").textContent = `${state.settings.risk}%`;
        if ($("home-usdjpy")) $("home-usdjpy").textContent = `${state.settings.usdjpy}`;
        if ($("home-currency")) $("home-currency").textContent = state.settings.currency;
      }
    } catch (e) {
      // ignore
    }

    // Fetch monthly stats snapshot
    try {
      const res = await fetch("/stats.json?" + Date.now());
      if (res.ok) {
        const d = await res.json();
        const m = d.month || { trades: 0, wins: 0, losses: 0, net_pnl: 0, net_pips: 0, win_rate: 0 };
        
        const pnl = m.net_pnl ?? 0;
        const wr = m.win_rate ?? 0;
        const cur = d.meta?.currency || state.settings.currency || "USD";

        const pnlEl = $("home-month-pnl");
        if (pnlEl) {
          pnlEl.textContent = `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)} ${cur}`;
          pnlEl.className = `stat-value-hero ${pnl >= 0 ? 'text-emerald' : 'text-rose'}`;
        }

        if ($("home-month-pips")) {
          $("home-month-pips").textContent = `${m.net_pips >= 0 ? '+' : ''}${(m.net_pips ?? 0).toFixed(1)} pip`;
        }

        if ($("home-month-wr")) {
          $("home-month-wr").textContent = `${wr.toFixed(0)}%`;
        }

        if ($("home-month-ratio")) {
          $("home-month-ratio").textContent = `${m.wins}W / ${m.losses}L (${m.trades} trades)`;
        }

        if ($("home-wr-bar")) {
          $("home-wr-bar").style.width = `${Math.min(wr, 100)}%`;
          $("home-wr-bar").style.background = wr >= 50 ? 'var(--color-emerald)' : 'var(--color-rose)';
        }
      }
    } catch (e) {
      // ignore
    }

    // Streak detection
    try {
      const trRes = await fetch("/trades.json?" + Date.now());
      if (trRes.ok) {
        const td = await trRes.json();
        const trades = td.trades || [];
        const streakEl = $("home-streak");

        if (trades.length > 0 && streakEl) {
          let count = 0;
          let isWinStreak = trades[0].pnl > 0;
          for (let i = 0; i < trades.length; i++) {
            const win = trades[i].pnl > 0;
            if (win === isWinStreak) count++;
            else break;
          }

          if (count >= 2) {
            streakEl.classList.remove("hidden");
            if (isWinStreak) {
              $("streak-emoji").textContent = "🔥";
              $("streak-text").textContent = `Win Streak ${count}x Beruntun!`;
              $("streak-sub").textContent = "Pertahankan disiplin trading & risk management.";
            } else {
              $("streak-emoji").textContent = "❄️";
              $("streak-text").textContent = `Loss Streak ${count}x`;
              $("streak-sub").textContent = "Jaga psikologi, evaluasi strategi sebelum entry lagi.";
            }
          } else {
            streakEl.classList.add("hidden");
          }
        }
      }
    } catch (e) {
      // ignore
    }
  }

  // ========== PERIOD SWITCHER (STATS PAGE) ==========
  document.querySelectorAll(".seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      haptic("selection");
      document.querySelectorAll(".seg-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.selectedPeriod = btn.dataset.period || "all";
      loadStats();
    });
  });

  // Refresh Buttons
  $("btn-refresh-home")?.addEventListener("click", () => {
    haptic("light");
    loadHome();
    toast("Data diperbarui", "🔄");
  });
  $("btn-refresh-stats")?.addEventListener("click", () => {
    haptic("light");
    loadStats();
    toast("Statistik diperbarui", "🔄");
  });
  $("btn-refresh-history")?.addEventListener("click", () => {
    haptic("light");
    loadHistory();
    toast("Riwayat diperbarui", "🔄");
  });

  // Start app
  document.addEventListener("DOMContentLoaded", () => {
    initTelegram();
    setupFormControls();
    setupRiskCalc();
    updateMarketSession();
    setInterval(updateMarketSession, 60000);
    go("home");
  });
})();
