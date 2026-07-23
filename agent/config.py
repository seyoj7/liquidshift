import os
from dotenv import load_dotenv

load_dotenv()

AGENT_LOOP_INTERVAL_S = int(os.getenv("AGENT_LOOP_INTERVAL_S", "30"))
MODEL_CAPITAL_USDC = float(os.getenv("MODEL_CAPITAL_USDC", "10000"))
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
TESTNET_MAX_TX_USDC = float(os.getenv("TESTNET_MAX_TX_USDC", "0.01"))
ARC_TESTNET_RPC_URL = os.getenv("ARC_TESTNET_RPC_URL", "https://rpc.testnet.arc.network")
USDC_CONTRACT_ADDRESS = os.getenv("USDC_CONTRACT_ADDRESS", "")
CIRCLE_API_KEY = os.getenv("CIRCLE_API_KEY", "")
CIRCLE_ENTITY_SECRET = os.getenv("CIRCLE_ENTITY_SECRET", "")
CIRCLE_WALLET_SET_ID = os.getenv("CIRCLE_WALLET_SET_ID", "")
CIRCLE_ARC_USDC_TOKEN_ID = os.getenv("CIRCLE_ARC_USDC_TOKEN_ID", "")
CIRCLE_API_BASE = "https://api.circle.com/v1/w3s"
ARC_BLOCKCHAIN = "ARC-TESTNET"
