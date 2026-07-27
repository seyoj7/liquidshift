# LiquidShift

**Autonomous USDC liquidity agent on Arc testnet — monitors DeFi pools, reallocates capital to the highest-yield opportunity, and executes transfers via Circle Programmable Wallets.**

> **Hackathon checkpoint submission** — core agent loop, decision engine, Circle wallet integration, and live dashboard are functional. Further features (multi-strategy, on-chain pool contracts, historical analytics) are planned.

---

## What It Does

LiquidShift is an AI-driven liquidity agent that continuously:

1. **Monitors** volume, liquidity, and volatility signals across multiple DeFi pools on Arc testnet (Curve on Arc, XyloNet, DefiOnARC)
2. **Decides** where to allocate capital using a heuristic engine that chases the highest volume-to-liquidity yield
3. **Executes** USDC transfers via [Circle Programmable Wallets](https://developers.circle.com/w3s) — no raw private keys required
4. **Tracks** every decision in an append-only ledger with on-chain tx hashes
5. **Visualizes** everything in a real-time browser dashboard

---

## What's Simulated vs Real

| Component | Real (on-chain / API) | Simulated (fallback) |
|---|---|---|
| **Wallet creation & management** | Circle Programmable Wallets API — real wallets on Arc testnet | Deterministic mock wallet IDs & addresses |
| **USDC transfers** | Circle transfer API → real on-chain txns (capped at `$0.01` per tx for testnet safety) | In-memory transfer stubs returning `COMPLETE` |
| **Pool data feed** | Live Swap event logs from on-chain pool contracts + on-chain balance queries | Time-of-day + sinusoidal noise model producing realistic volume/liquidity curves |
| **On-chain balance reads** | `web3.eth.get_balance` against Arc testnet RPC | Falls back to `0.0` |
| **Decision engine** | Always real — same heuristic runs regardless of data source | — |
| **Ledger** | Always real — persisted to `data/ledger.json` | — |
| **Dashboard** | Always real — served by the agent's HTTP server | — |

> **One-liner:** Wallet ops and USDC transfers are real on-chain via Circle when API keys are configured; pool volume/liquidity data falls back to a deterministic simulation when no on-chain pool contracts are deployed.

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│                  Dashboard (browser)             │
│   index.html + script.js + styles.css            │
│   Charts (Chart.js) · MetaMask connect (ethers)  │
└──────────────────┬───────────────────────────────┘
                   │  HTTP  (GET /api/state, POST /api/wallet/connect, ...)
┌──────────────────▼───────────────────────────────┐
│               agent/main.py (HTTP server)        │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │ data_feed  │→ │  decision  │→ │  executor  │  │
│  │ (live/sim) │  │  engine    │  │ (Circle)   │  │
│  └────────────┘  └────────────┘  └─────┬──────┘  │
│                                        │         │
│  ┌──────────────┐  ┌───────────────────▼──────┐  │
│  │  ledger.py   │← │  circle_wallet.py        │  │
│  │  (JSON log)  │  │  (live / simulated)      │  │
│  └──────────────┘  └─────────────────────────┘  │
└──────────────────────────────────────────────────┘
         │                         │
         ▼                         ▼
   Arc Testnet RPC          Circle W3S API
   (web3 / EVM)             (wallet + transfer)
```

---

## Tech Stack

- **Agent**: Python 3.12+ — `web3.py`, `httpx`, `pycryptodome`
- **Wallets**: Circle Programmable Wallets (W3S API) on `ARC-TESTNET`
- **Dashboard**: Vanilla HTML/CSS/JS — Chart.js for charts, ethers.js for MetaMask
- **Blockchain**: Arc Testnet (`https://rpc.testnet.arc.network`)
- **Explorer**: `https://testnet.arcscan.app`

---

## Quick Start

### 1. Clone & install

```bash
git clone https://github.com/<your-org>/liquidshift.git
cd liquidshift
pip install -r requirements.txt
```

### 2. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials:

| Variable | Required? | Description |
|---|---|---|
| `ARC_TESTNET_RPC_URL` | Has default | Arc testnet RPC endpoint |
| `USDC_CONTRACT_ADDRESS` | Has default | USDC contract on Arc testnet |
| `CIRCLE_API_KEY` | For live mode | Circle Console API key |
| `CIRCLE_ENTITY_SECRET` | For live mode | 64-char hex secret (generate below) |
| `CIRCLE_WALLET_SET_ID` | For live mode | Wallet set ID (create below) |
| `CIRCLE_ARC_USDC_TOKEN_ID` | For live transfers | USDC token ID for Circle transfer API |
| `CURVE_POOL_ADDRESS` | Optional | Enables live data for Curve pool |
| `XYLONET_POOL_ADDRESS` | Optional | Enables live data for XyloNet pool |
| `DEFIONARC_POOL_ADDRESS` | Optional | Enables live data for DefiOnARC pool |

> Without Circle credentials, the agent runs in **simulated mode** — no real transactions, but the full decision loop and dashboard still work.

### 3. (Optional) Set up Circle Programmable Wallets

```bash
# Step 1: Generate an entity secret
python agent/scripts/generate_entity_secret.py
# → Copy the output into .env as CIRCLE_ENTITY_SECRET

# Step 2: Register it with Circle
python agent/scripts/register_entity_secret.py

# Step 3: Create a wallet set
python agent/scripts/create_wallet_set.py
# → Copy the wallet set ID into .env as CIRCLE_WALLET_SET_ID
```

### 4. Run

```bash
python agent/main.py --interval 30
```

Open **http://localhost:8080** in your browser.

### 5. Use the dashboard

1. Click **Connect Wallet** → MetaMask prompt → signs your EVM address
2. The agent creates a Circle Programmable Wallet mapped to your address
3. Click **Start** → the agent begins its monitor → decide → execute loop
4. Watch pool signals, capital allocation, and earnings update in real time

---

## Project Structure

```
liquidshift/
├── agent/
│   ├── main.py              # Agent loop + HTTP server + dashboard API
│   ├── config.py            # Environment config loader
│   ├── connect.py           # Arc testnet connection verifier
│   ├── data_feed.py         # Live on-chain + simulated pool data
│   ├── decision.py          # Heuristic rebalance engine
│   ├── executor.py          # Executes decisions via Circle transfers
│   ├── ledger.py            # Append-only JSON decision log
│   ├── wallet.py            # web3 balance reads
│   ├── circle_wallet.py     # Circle Programmable Wallets (live + sim)
│   └── scripts/
│       ├── generate_entity_secret.py
│       ├── register_entity_secret.py
│       └── create_wallet_set.py
├── dashboard/
│   ├── index.html           # Single-page dashboard
│   ├── script.js            # Polling, charts, wallet connect
│   ├── styles.css           # Dark-theme UI
│   └── logo/
│       └── favicon.png
├── data/
│   └── ledger.json          # Persisted decision ledger
├── .env.example             # Template for environment variables
├── requirements.txt         # Python dependencies
└── README.md
```

---

## Standalone Module Tests

Each module has a `main()` you can run independently:

```bash
python -m agent.connect        # Verify Arc testnet RPC + USDC contract
python -m agent.wallet         # Show Circle wallet info + balance
python -m agent.circle_wallet  # Smoke-test Circle wallet creation
python -m agent.data_feed      # Print current + 24h simulated pool data
python -m agent.decision       # Run decision engine over 24h simulated history
python -m agent.executor       # Manual transfer test (sends $0.01 to a pool)
python -m agent.ledger         # Print ledger contents
```

---

## Roadmap (Post-Checkpoint)

- [ ] Multi-strategy decision engine (momentum, mean-reversion, risk-parity)
- [ ] Deploy actual liquidity pool contracts on Arc testnet
- [ ] Historical analytics & backtesting mode
- [ ] Multi-wallet portfolio support
- [ ] Gas cost tracking & optimization
- [ ] WebSocket-based dashboard updates (replace polling)
- [ ] Mobile-responsive dashboard layout

---

## License

MIT
