const API =
  window.location.protocol === "file:" || (window.location.port && window.location.port !== "8080")
    ? "http://localhost:8080/api/state"
    : "/api/state";
const POLL_MS = 8000;
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const usd = (n, d = 2) => {
  const digits = Math.min(d, 2);
  return (
    "$" +
    Number(n).toLocaleString("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    })
  );
};
const pct = (n) => Number(n).toFixed(1) + "%";
const shortAddr = (a) => (a ? a.slice(0, 6) + "..." + a.slice(-4) : "--");
const shortHash = (h) => (h ? h.slice(0, 5) + "..." + h.slice(-4) : "--");
const timeStr = (iso) => {
  if (!iso) return "--";
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });
};
const ALLOC_COLORS = ["#2dd4bf", "#f59e0b", "#a78bfa", "#38bdf8", "#10b981", "#f87171", "#ec4899"];
const POOL_COLORS = {
  "Curve on Arc": "#2dd4bf",
  "Aave USDC": "#38bdf8",
  "Uniswap V3 USDC/USDT": "#a78bfa",
  "Compound USDC": "#f59e0b",
  "Balancer USDC": "#10b981",
};
function getPoolColor(poolName, index = 0) {
  if (POOL_COLORS[poolName]) return POOL_COLORS[poolName];
  return ALLOC_COLORS[index % ALLOC_COLORS.length];
}
let allocChart, earnChart;
function initCharts() {
  const doughnutCtx = document.getElementById("allocChart").getContext("2d");
  allocChart = new Chart(doughnutCtx, {
    type: "doughnut",
    data: {
      labels: ["Idle"],
      datasets: [{ data: [1], backgroundColor: ["#1c1e25"], borderWidth: 0, borderColor: "transparent" }],
    },
    options: {
      cutout: "68%",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "bottom",
          labels: {
            color: "#e2e8f0",
            font: { size: 11, family: "'Inter', sans-serif" },
            padding: 14,
          },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => " " + ctx.label + ": " + usd(ctx.parsed, 0),
          },
        },
      },
      animation: { animateRotate: true, duration: 800 },
    },
  });
  const lineCtx = document.getElementById("earnChart").getContext("2d");
  earnChart = new Chart(lineCtx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Active (Agent)",
          data: [],
          borderColor: "#2dd4bf",
          backgroundColor: "rgba(45,212,191,0.12)",
          fill: true,
          tension: 0.35,
          pointRadius: 3,
          borderWidth: 2,
        },
        {
          label: "Passive (Benchmark)",
          data: [],
          borderColor: "#64748b",
          backgroundColor: "rgba(100,116,139,0.06)",
          fill: true,
          tension: 0.35,
          pointRadius: 3,
          borderWidth: 2,
          borderDash: [6, 3],
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          display: true,
          ticks: {
            color: "#94a3b8",
            font: { size: 10, family: "'Inter', sans-serif" },
            maxTicksLimit: 8,
          },
          grid: { color: "rgba(255,255,255,0.05)" },
        },
        y: {
          display: true,
          ticks: {
            color: "#94a3b8",
            font: { size: 10, family: "'Inter', sans-serif" },
            callback: (v) => "$" + v.toFixed(2),
          },
          grid: { color: "rgba(255,255,255,0.05)" },
        },
      },
      plugins: {
        legend: {
          labels: {
            color: "#e2e8f0",
            font: { size: 11, family: "'Inter', sans-serif" },
            padding: 14,
          },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => " " + ctx.dataset.label + ": " + usd(ctx.parsed.y, 2),
          },
        },
      },
      animation: { duration: 600 },
    },
  });
}
function update(data) {
  if (!data || !data.agent) return;
  const running = data.agent.status === "running";
  $("#statusBadge").innerHTML =
    `<span class="status-dot on" title="${running ? "Server & Agent Running" : "Server Running"}"></span>`;
  $("#cycleBadge").textContent = `Cycle #${data.agent.cycle}`;
  const btnStart = $("#btnStart");
  const btnStartText = $("#btnStartText");
  if (running) {
    btnStart.classList.add("connected");
    btnStart.style.borderColor = "var(--red)";
    btnStart.style.color = "var(--red)";
    btnStart.querySelector(".dot").style.background = "var(--red)";
    btnStartText.textContent = "Stop";
    btnStart.disabled = false;
  } else {
    btnStart.classList.remove("connected");
    btnStart.style.borderColor = "var(--amber)";
    btnStart.style.color = "var(--amber)";
    btnStart.querySelector(".dot").style.background = "var(--amber)";
    btnStartText.textContent = "Start";
    btnStart.disabled = false;
  }
  $("#walletBal").textContent = usd(data.wallet.balance, 2);
  const wAddr = $("#walletAddr");
  if (wAddr) {
    wAddr.textContent = shortAddr(data.wallet.address);
    wAddr.dataset.fullText = data.wallet.address || "";
    wAddr.title = data.wallet.address ? "Click to copy: " + data.wallet.address : "";
  }
  $("#modelCap").textContent = usd(data.allocation.total, 0);
  const idlePct = data.allocation.total > 0 ? ((data.allocation.idle / data.allocation.total) * 100).toFixed(0) : "0";
  $("#idleAmt").textContent = usd(data.allocation.idle, 0) + " idle (" + idlePct + "%)";
  $("#activeEarn").textContent = "+" + usd(data.earnings.active, 2);
  $("#passiveEarn").textContent = "+" + usd(data.earnings.passive, 2);
  updateAllocChart(data.allocation);
  updateEarnChart(data.earnings);
  updateSignals(data.snapshots);
  updateLog(data.ledger);
}
function updateAllocChart(alloc) {
  const labels = [];
  const values = [];
  const colors = [];

  if (alloc.idle && alloc.idle > 0) {
    labels.push("Idle");
    values.push(alloc.idle);
    colors.push("#1c1e25");
  }

  let i = 0;
  for (const [pool, amt] of Object.entries(alloc.pools || {})) {
    if (amt > 0) {
      labels.push(pool);
      values.push(amt);
      colors.push(getPoolColor(pool, i));
      i++;
    }
  }

  if (labels.length === 0) {
    labels.push("Idle");
    values.push(1);
    colors.push("#1c1e25");
  }

  allocChart.data.labels = labels;
  allocChart.data.datasets[0].data = values;
  allocChart.data.datasets[0].backgroundColor = colors;
  allocChart.update();
}
function updateEarnChart(earnings) {
  const hist = earnings.history || [];
  const labels = hist.map((h) => timeStr(h.t));
  const active = hist.map((h) => h.a);
  const passive = hist.map((h) => h.p);
  earnChart.data.labels = labels;
  earnChart.data.datasets[0].data = active;
  earnChart.data.datasets[1].data = passive;
  earnChart.update();
}
function updateSignals(snaps) {
  const tbody = $("#signalBody");
  const empty = $("#signalEmpty");
  if (!snaps || snaps.length === 0) {
    tbody.innerHTML = "";
    empty.style.display = "block";
    return;
  }
  empty.style.display = "none";
  let html = "";
  for (const s of snaps) {
    const ratio = s.vol24h > 0 ? s.vol1h / s.vol24h : 0;
    const ratioClass = ratio >= 2 ? "color:var(--teal);font-weight:700" : ratio >= 1.5 ? "color:var(--amber)" : "";
    const barW = Math.min(100, (ratio / 3) * 100);
    const srcLabel = s.src === "live" ? "LIVE" : "SIM";
    const srcClass = s.src === "live" ? "badge-live" : "badge-simulated";
    const srcBadge = `<span class="badge ${srcClass}">${srcLabel}</span>`;
    html += `<tr>
      <td style="font-weight:600">${s.pool}</td>
      <td class="mono">${usd(s.vol1h, 0)}</td>
      <td class="mono">${usd(s.vol24h, 0)}</td>
      <td>
        <span class="mono" style="${ratioClass}">${ratio.toFixed(1)}x</span>
        <span class="vol-bar-track"><span class="vol-bar-fill" style="width:${barW}%"></span></span>
      </td>
      <td class="mono">${usd(s.liq, 0)}</td>
      <td>${srcBadge}</td>
    </tr>`;
  }
  tbody.innerHTML = html;
  if (snaps[0] && snaps[0].timestamp) {
    $("#signalTime").textContent = "Updated " + timeStr(snaps[0].timestamp);
  }
}
function updateLog(ledger) {
  const tbody = $("#logBody");
  const empty = $("#logEmpty");
  if (!ledger || ledger.length === 0) {
    tbody.innerHTML = "";
    empty.style.display = "block";
    return;
  }
  empty.style.display = "none";
  const recent = ledger.slice(-50).reverse();
  let html = "";
  for (const e of recent) {
    const actionBadge = `<span class="badge badge-${e.action || "hold"}">${(e.action || "hold").replace(/_/g, " ")}</span>`;
    const statusBadge = `<span class="badge badge-${e.status || "skipped"}">${e.status || "?"}</span>`;
    const src = e.inputs && e.inputs.source;
    const isWalletCreated = e.action === "wallet_created";
    const srcBadge = isWalletCreated
      ? (src === "live"
        ? '<span class="badge badge-live">Live</span>'
        : src === "simulated"
          ? '<span class="badge badge-simulated">Sim</span>'
          : '<span class="badge badge-skipped">--</span>')
      : '<span class="badge badge-simulated">SIM</span>';
    const txLink = e.tx_hash
      ? `<a href="${e.explorer_url || "https://testnet.arcscan.app/tx/" + e.tx_hash}" target="_blank" rel="noopener">${shortHash(e.tx_hash)}</a>`
      : "--";
    const reason = (e.reason || "").length > 60 ? e.reason.slice(0, 57) + "..." : e.reason || "--";
    html += `<tr>
      <td class="mono" style="white-space:nowrap">${timeStr(e.logged_at || e.decision_timestamp)}</td>
      <td>${actionBadge}</td>
      <td style="font-weight:500;white-space:nowrap">${e.pool || "--"}</td>
      <td class="mono">${usd(e.amount_usdc || 0, 2)}</td>
      <td>${statusBadge}</td>
      <td>${srcBadge}</td>
      <td class="mono">${txLink}</td>
      <td style="color:var(--text-dim);font-size:0.75rem;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
          title="${(e.reason || "").replace(/"/g, "&quot;")}">${reason}</td>
    </tr>`;
  }
  tbody.innerHTML = html;
}
async function poll() {
  try {
    const res = await fetch(API);
    const data = await res.json();
    update(data);
  } catch (err) {
    $("#statusBadge").innerHTML = '<span class="status-dot off" title="Disconnected"></span>';
  }
}
let connectedAddress = null;
function disconnectWallet() {
  const btn = $("#btnConnect");
  const btnText = $("#btnConnectText");
  const info = $("#walletInfo");

  connectedAddress = null;
  localStorage.removeItem("ls_evm_addr");

  btn.classList.remove("connected");
  btnText.textContent = "Connect Wallet";
  info.style.display = "none";

  const evmEl = $("#evmAddr");
  if (evmEl) { evmEl.textContent = "--"; evmEl.dataset.fullText = ""; }
  const circleAddrEl = $("#circleAddr");
  if (circleAddrEl) { circleAddrEl.textContent = "--"; circleAddrEl.dataset.fullText = ""; }
  const circleIdEl = $("#circleId");
  if (circleIdEl) { circleIdEl.textContent = "--"; circleIdEl.dataset.fullText = ""; }
  const circleBalEl = $("#circleBal");
  if (circleBalEl) { circleBalEl.textContent = "--"; }
}

async function connectWallet() {
  const btn = $("#btnConnect");
  const btnText = $("#btnConnectText");
  if (btn.classList.contains("connected")) {
    disconnectWallet();
    return;
  }
  if (typeof window.ethereum === "undefined") {
    alert("Please install MetaMask, Revu, or another EVM wallet extension.");
    return;
  }
  btn.disabled = true;
  btnText.textContent = "Connecting...";
  try {
    const provider = new ethers.BrowserProvider(window.ethereum);
    const accounts = await provider.send("eth_requestAccounts", []);
    const address = accounts[0];
    if (!address) {
      btnText.textContent = "Connect Wallet";
      btn.disabled = false;
      return;
    }
    connectedAddress = address;
    btnText.textContent = "Registering...";
    const apiBase = API.replace("/api/state", "");
    const res = await fetch(apiBase + "/api/wallet/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ evm_address: address }),
    });
    const data = await res.json();
    if (data.error) {
      alert("Wallet connect error: " + data.error);
      btnText.textContent = "Connect Wallet";
      btn.disabled = false;
      return;
    }
    showWalletInfo(data);
    localStorage.setItem("ls_evm_addr", address);
  } catch (err) {
    console.error("Wallet connect error:", err);
    alert("Failed to connect wallet: " + (err.message || err));
    btnText.textContent = "Connect Wallet";
    btn.disabled = false;
  }
}
function showWalletInfo(data) {
  const btn = $("#btnConnect");
  const btnText = $("#btnConnectText");
  const info = $("#walletInfo");
  btn.classList.add("connected");
  btn.disabled = false;
  btnText.textContent = shortAddr(data.evm_address);
  info.style.display = "flex";
  const evmEl = $("#evmAddr");
  evmEl.textContent = shortAddr(data.evm_address);
  evmEl.dataset.fullText = data.evm_address || "";
  evmEl.title = data.evm_address ? "Click to copy: " + data.evm_address : "";

  const circleAddrEl = $("#circleAddr");
  circleAddrEl.textContent = shortAddr(data.circle_address);
  circleAddrEl.dataset.fullText = data.circle_address || "";
  circleAddrEl.title = data.circle_address ? "Click to copy: " + data.circle_address : "";

  const circleIdEl = $("#circleId");
  circleIdEl.textContent = data.circle_wallet_id
    ? data.circle_wallet_id.slice(0, 5) + "..." + data.circle_wallet_id.slice(-4)
    : "--";
  circleIdEl.dataset.fullText = data.circle_wallet_id || "";
  circleIdEl.title = data.circle_wallet_id ? "Click to copy: " + data.circle_wallet_id : "";
  $("#circleBal").textContent = usd(data.usdc_balance || 0, 2);
  const mode = data.mode || "simulated";
  const circleModeEl = $("#circleMode");
  if (circleModeEl) {
    circleModeEl.innerHTML =
      mode === "live"
        ? '<span class="badge badge-live">Live</span>'
        : '<span class="badge badge-simulated">Simulated</span>';
  }
}
async function toggleAgent() {
  if (!$("#btnConnect").classList.contains("connected")) {
    alert("Please connect a wallet first.");
    return;
  }
  const btn = $("#btnStart");
  const btnText = $("#btnStartText");
  const isRunning = btnText.textContent === "Stop";
  const endpoint = isRunning ? "/api/agent/stop" : "/api/agent/start";
  btn.disabled = true;
  btnText.textContent = isRunning ? "Stopping..." : "Starting...";
  try {
    const apiBase = API.replace("/api/state", "");
    const res = await fetch(apiBase + endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const data = await res.json();
    if (data.error) {
      alert("Failed to toggle agent: " + data.error);
      btn.disabled = false;
      btnText.textContent = isRunning ? "Stop" : "Start";
      return;
    }
  } catch (err) {
    console.error("Agent toggle error:", err);
    alert("Failed to toggle agent: " + (err.message || err));
    btn.disabled = false;
    btnText.textContent = isRunning ? "Stop" : "Start";
  }
}
async function autoReconnect() {
  const saved = localStorage.getItem("ls_evm_addr");
  if (!saved) return;
  try {
    const apiBase = API.replace("/api/state", "");
    const res = await fetch(apiBase + "/api/wallet/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ evm_address: saved }),
    });
    const data = await res.json();
    if (!data.error) {
      connectedAddress = saved;
      showWalletInfo(data);
    }
  } catch (e) { }
}
initCharts();
autoReconnect();
poll();
setInterval(poll, POLL_MS);

document.addEventListener("click", (e) => {
  const target = e.target.closest(".copyable");
  if (!target) return;
  const text = target.dataset.fullText || target.getAttribute("title") || target.textContent;
  if (!text || text === "--" || text === "Copied") return;
  const copyValue = target.dataset.fullText || (text.startsWith("Click to copy:") ? text.replace("Click to copy:", "").trim() : text);
  if (!copyValue || copyValue === "--") return;

  navigator.clipboard.writeText(copyValue).then(() => {
    const origText = target.textContent;
    const origColor = target.style.color;
    target.textContent = "Copied";
    target.style.color = "var(--green)";
    setTimeout(() => {
      target.textContent = origText;
      target.style.color = origColor;
    }, 1200);
  }).catch(err => {
    console.error("Clipboard copy failed:", err);
  });
});
