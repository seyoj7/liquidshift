const API =
  window.location.protocol === "file:" || (window.location.port && window.location.port !== "8080")
    ? "http://localhost:8080/api/state"
    : "/api/state";
const POLL_MS = 8000;
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const usd = (n, d = 2) =>
  "$" +
  Number(n).toLocaleString("en-US", {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  });
const pct = (n) => Number(n).toFixed(1) + "%";
const shortAddr = (a) => (a ? a.slice(0, 6) + "..." + a.slice(-4) : "--");
const shortHash = (h) => (h ? h.slice(0, 10) + "..." : "--");
const timeStr = (iso) => {
  if (!iso) return "--";
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
};
const ALLOC_COLORS = ["#a78bfa", "#2dd4bf", "#60a5fa", "#fbbf24", "#f87171", "#34d399"];
let allocChart, earnChart;
function initCharts() {
  const doughnutCtx = document.getElementById("allocChart").getContext("2d");
  allocChart = new Chart(doughnutCtx, {
    type: "doughnut",
    data: {
      labels: ["Idle"],
      datasets: [{ data: [1], backgroundColor: ["#1e293b"], borderWidth: 0 }],
    },
    options: {
      cutout: "68%",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "bottom",
          labels: {
            color: "#94a3b8",
            font: { size: 11, family: "Inter" },
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
          backgroundColor: "rgba(45,212,191,0.08)",
          fill: true,
          tension: 0.35,
          pointRadius: 2,
          borderWidth: 2,
        },
        {
          label: "Passive (Benchmark)",
          data: [],
          borderColor: "#64748b",
          backgroundColor: "rgba(100,116,139,0.05)",
          fill: true,
          tension: 0.35,
          pointRadius: 2,
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
            color: "#475569",
            font: { size: 10 },
            maxTicksLimit: 8,
          },
          grid: { color: "rgba(255,255,255,0.03)" },
        },
        y: {
          display: true,
          ticks: {
            color: "#475569",
            font: { size: 10 },
            callback: (v) => "$" + v.toFixed(2),
          },
          grid: { color: "rgba(255,255,255,0.04)" },
        },
      },
      plugins: {
        legend: {
          labels: {
            color: "#94a3b8",
            font: { size: 11, family: "Inter" },
            padding: 14,
          },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => " " + ctx.dataset.label + ": " + usd(ctx.parsed.y, 4),
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
    `<span class="status-dot ${running ? "on" : "off"}" title="${running ? "Running" : data.agent.status === "waiting" ? "Waiting for Start" : "Stopped"}"></span>`;
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
  $("#walletBal").textContent = usd(data.wallet.balance, 6);
  $("#walletAddr").textContent = shortAddr(data.wallet.address);
  $("#modelCap").textContent = usd(data.allocation.total, 0);
  const idlePct = data.allocation.total > 0 ? ((data.allocation.idle / data.allocation.total) * 100).toFixed(0) : "0";
  $("#idleAmt").textContent = usd(data.allocation.idle, 0) + " idle (" + idlePct + "%)";
  $("#activeEarn").textContent = "+" + usd(data.earnings.active, 4);
  $("#passiveEarn").textContent = "+" + usd(data.earnings.passive, 4);
  updateAllocChart(data.allocation);
  updateEarnChart(data.earnings);
  updateSignals(data.snapshots);
  updateLog(data.ledger);
}
function updateAllocChart(alloc) {
  const labels = ["Idle"];
  const values = [alloc.idle];
  const colors = ["#1e293b"];
  let i = 0;
  for (const [pool, amt] of Object.entries(alloc.pools || {})) {
    labels.push(pool);
    values.push(amt);
    colors.push(ALLOC_COLORS[i % ALLOC_COLORS.length]);
    i++;
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
    const srcBadge =
      s.src === "live"
        ? '<span class="badge badge-live">Live</span>'
        : '<span class="badge badge-simulated">Simulated</span>';
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
    const srcBadge =
      src === "live"
        ? '<span class="badge badge-live">Live</span>'
        : src === "simulated"
          ? '<span class="badge badge-simulated">Sim</span>'
          : '<span class="badge badge-skipped">--</span>';
    const txLink = e.tx_hash
      ? `<a href="${e.explorer_url || "https://testnet.arcscan.app/tx/" + e.tx_hash}" target="_blank" rel="noopener">${shortHash(e.tx_hash)}</a>`
      : "--";
    const reason = (e.reason || "").length > 60 ? e.reason.slice(0, 57) + "..." : e.reason || "--";
    html += `<tr>
      <td class="mono" style="white-space:nowrap">${timeStr(e.logged_at || e.decision_timestamp)}</td>
      <td>${actionBadge}</td>
      <td style="font-weight:500">${e.pool || "--"}</td>
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
async function connectWallet() {
  const btn = $("#btnConnect");
  const btnText = $("#btnConnectText");
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
  $("#evmAddr").textContent = shortAddr(data.evm_address);
  $("#evmAddr").title = data.evm_address;
  $("#circleAddr").textContent = shortAddr(data.circle_address);
  $("#circleAddr").title = data.circle_address || "";
  $("#circleId").textContent = data.circle_wallet_id ? data.circle_wallet_id.slice(0, 12) + "..." : "--";
  $("#circleId").title = data.circle_wallet_id || "";
  $("#circleBal").textContent = usd(data.usdc_balance || 0, 6);
  const mode = data.mode || "simulated";
  $("#circleMode").innerHTML =
    mode === "live"
      ? '<span class="badge badge-live">Live</span>'
      : '<span class="badge badge-simulated">Simulated</span>';
  if (data.is_new) {
    $("#circleId").style.animation = "pulse 1s ease 3";
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
  } catch (e) {}
}
initCharts();
poll();
setInterval(poll, POLL_MS);
