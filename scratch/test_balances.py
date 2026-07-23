import os
from dotenv import load_dotenv
import httpx
import json

load_dotenv()

CIRCLE_API_BASE = "https://api.circle.com/v1/w3s"
CIRCLE_WALLET_SET_ID = os.getenv("CIRCLE_WALLET_SET_ID")
CIRCLE_API_KEY = os.getenv("CIRCLE_API_KEY")

headers = {
    "Authorization": f"Bearer {CIRCLE_API_KEY}",
    "Content-Type": "application/json",
}

print(f"Fetching wallets for WalletSet: {CIRCLE_WALLET_SET_ID}")

# Fetch all wallets in set
resp = httpx.get(f"{CIRCLE_API_BASE}/wallets?walletSetId={CIRCLE_WALLET_SET_ID}", headers=headers)
if resp.status_code != 200:
    print("Error:", resp.text)
else:
    wallets = resp.json().get("data", {}).get("wallets", [])
    print(f"Found {len(wallets)} wallets.")

    for w in wallets:
        w_id = w["id"]
        print(f"\nWallet {w_id} ({w.get('refId')}):")

        # Get balances
        bal_resp = httpx.get(f"{CIRCLE_API_BASE}/wallets/{w_id}/balances", headers=headers)
        if bal_resp.status_code == 200:
            bals = bal_resp.json().get("data", {}).get("tokenBalances", [])
            print("  Balances:", json.dumps(bals, indent=2))
        else:
            print("  Balance fetch error:", bal_resp.text)
