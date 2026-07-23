from __future__ import annotations
import base64
import codecs
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import httpx
from agent.config import (
    CIRCLE_API_BASE,
    ARC_BLOCKCHAIN,
    CIRCLE_ARC_USDC_TOKEN_ID,
    CIRCLE_API_KEY,
    CIRCLE_ENTITY_SECRET,
    CIRCLE_WALLET_SET_ID,
)

IS_LIVE = bool(CIRCLE_API_KEY and CIRCLE_ENTITY_SECRET and CIRCLE_WALLET_SET_ID)


def _circle_headers() -> dict:
    return {
        "Authorization": f"Bearer {CIRCLE_API_KEY}",
        "Content-Type": "application/json",
    }


def _encrypt_entity_secret() -> str:

    secret_bytes = codecs.decode(CIRCLE_ENTITY_SECRET, "hex")
    assert len(secret_bytes) == 32, "Entity secret must be 32 bytes (64 hex chars)"
    try:
        from Crypto.PublicKey import RSA
        from Crypto.Cipher import PKCS1_OAEP
        from Crypto.Hash import SHA256

        with httpx.Client(timeout=10.0, transport=httpx.HTTPTransport(retries=3)) as client:
            resp = client.get(
                f"{CIRCLE_API_BASE}/config/entity/publicKey",
                headers=_circle_headers(),
            )
            resp.raise_for_status()
            pub_key_pem = resp.json()["data"]["publicKey"]
        pub_key = RSA.import_key(pub_key_pem)
        cipher = PKCS1_OAEP.new(
            pub_key,
            hashAlgo=SHA256,
            mgfunc=lambda x, y: PKCS1_OAEP.MGF1(x, y, SHA256),
        )
        encrypted = cipher.encrypt(secret_bytes)
        return base64.b64encode(encrypted).decode("utf-8")
    except ImportError:
        print("  [circle] WARNING: pycryptodome not installed, using base64 fallback")
        return base64.b64encode(secret_bytes).decode("utf-8")


def _create_wallet_live(label: str) -> dict:

    ref_id = label.lower()
    with httpx.Client(timeout=10.0, transport=httpx.HTTPTransport(retries=3)) as client:
        resp = client.get(
            f"{CIRCLE_API_BASE}/wallets?refId={ref_id}&walletSetId={CIRCLE_WALLET_SET_ID}",
            headers=_circle_headers(),
        )
        if resp.status_code == 200:
            data = resp.json()
            wallets = data.get("data", {}).get("wallets", [])
            if wallets:
                w = wallets[0]
                return {
                    "circle_wallet_id": w["id"],
                    "circle_address": w["address"],
                    "blockchain": w["blockchain"],
                    "state": w["state"],
                    "mode": "live",
                }
    idempotency_key = str(uuid.uuid4())
    payload = {
        "idempotencyKey": idempotency_key,
        "blockchains": [ARC_BLOCKCHAIN],
        "walletSetId": CIRCLE_WALLET_SET_ID,
        "count": 1,
        "entitySecretCiphertext": _encrypt_entity_secret(),
        "metadata": [
            {
                "name": f"LiquidShift-{label[:20]}",
                "refId": label.lower(),
            }
        ],
    }
    with httpx.Client(timeout=15.0, transport=httpx.HTTPTransport(retries=3)) as client:
        resp = client.post(
            f"{CIRCLE_API_BASE}/developer/wallets",
            headers=_circle_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    wallets = data.get("data", {}).get("wallets", [])
    if not wallets:
        raise ValueError(f"Circle API returned no wallets: {data}")
    w = wallets[0]
    return {
        "circle_wallet_id": w["id"],
        "circle_address": w.get("address", ""),
        "blockchain": w.get("blockchain", ARC_BLOCKCHAIN),
        "state": w.get("state", ""),
        "mode": "live",
    }


def _get_balance_live(wallet_id: str) -> float:
    with httpx.Client(timeout=10.0, transport=httpx.HTTPTransport(retries=3)) as client:
        resp = client.get(
            f"{CIRCLE_API_BASE}/wallets/{wallet_id}/balances",
            headers=_circle_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
    balances = data.get("data", {}).get("tokenBalances", [])
    for b in balances:
        if b.get("token", {}).get("symbol", "").upper() == "USDC":
            return float(b["amount"])
    return 0.0


def _transfer_usdc_live(
    source_wallet_id: str,
    destination_address: str,
    amount_usdc: float,
) -> dict:

    idempotency_key = str(uuid.uuid4())
    payload = {
        "idempotencyKey": idempotency_key,
        "entitySecretCiphertext": _encrypt_entity_secret(),
        "amounts": [str(amount_usdc)],
        "destinationAddress": destination_address,
        "walletId": source_wallet_id,
        "blockchain": ARC_BLOCKCHAIN,
        "feeLevel": "MEDIUM",
    }
    if CIRCLE_ARC_USDC_TOKEN_ID:
        payload["tokenId"] = CIRCLE_ARC_USDC_TOKEN_ID
    with httpx.Client(timeout=30.0, transport=httpx.HTTPTransport(retries=3)) as client:
        resp = client.post(
            f"{CIRCLE_API_BASE}/developer/transactions/transfer",
            headers=_circle_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    transfer = data.get("data", {})
    tx_id = transfer.get("id", "")
    state = transfer.get("state", "")
    tx_hash = transfer.get("txHash", "")
    attempts = 0
    while state in ("INITIATED", "PENDING") and not tx_hash and attempts < 10:
        time.sleep(1.5)
        status = _get_transfer_status_live(tx_id)
        state = status.get("state", state)
        tx_hash = status.get("tx_hash", "")
        attempts += 1
    return {
        "transfer_id": tx_id,
        "state": state,
        "tx_hash": tx_hash,
        "amount_usdc": amount_usdc,
        "destination": destination_address,
        "mode": "live",
    }


def _get_transfer_status_live(transfer_id: str) -> dict:
    with httpx.Client(timeout=10.0, transport=httpx.HTTPTransport(retries=3)) as client:
        resp = client.get(
            f"{CIRCLE_API_BASE}/transactions/{transfer_id}",
            headers=_circle_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
    tx = data.get("data", {}).get("transaction", data.get("data", {}))
    return {
        "transfer_id": transfer_id,
        "state": tx.get("state", ""),
        "tx_hash": tx.get("txHash", ""),
    }


def _create_wallet_sim(label: str) -> dict:
    h = hashlib.sha256(f"circle-sim:{label.lower()}".encode()).hexdigest()
    wallet_id = str(uuid.UUID(h[:32]))
    addr_hash = hashlib.sha256(f"circle-addr:{label.lower()}".encode()).hexdigest()
    circle_addr = "0x" + addr_hash[:40]
    return {
        "circle_wallet_id": wallet_id,
        "circle_address": circle_addr,
        "blockchain": ARC_BLOCKCHAIN,
        "state": "LIVE",
        "mode": "simulated",
    }


def _get_balance_sim(_wallet_id: str) -> float:
    return 0.0


def _transfer_usdc_sim(
    source_wallet_id: str,
    destination_address: str,
    amount_usdc: float,
) -> dict:
    fake_id = str(uuid.uuid4())
    return {
        "transfer_id": fake_id,
        "state": "COMPLETE",
        "tx_hash": "",
        "amount_usdc": amount_usdc,
        "destination": destination_address,
        "mode": "simulated",
    }


def _get_transfer_status_sim(transfer_id: str) -> dict:
    return {
        "transfer_id": transfer_id,
        "state": "COMPLETE",
        "tx_hash": "",
    }


def create_circle_wallet(label: str) -> dict:

    if IS_LIVE:
        return _create_wallet_live(label)
    return _create_wallet_sim(label)


def create_agent_wallet() -> dict:

    return create_circle_wallet("agent-main")


def get_circle_wallet_balance(wallet_id: str) -> float:
    if IS_LIVE:
        return _get_balance_live(wallet_id)
    return _get_balance_sim(wallet_id)


def transfer_usdc(
    source_wallet_id: str,
    destination_address: str,
    amount_usdc: float,
) -> dict:

    if IS_LIVE:
        return _transfer_usdc_live(source_wallet_id, destination_address, amount_usdc)
    return _transfer_usdc_sim(source_wallet_id, destination_address, amount_usdc)


def get_transfer_status(transfer_id: str) -> dict:
    if IS_LIVE:
        return _get_transfer_status_live(transfer_id)
    return _get_transfer_status_sim(transfer_id)


def get_mode() -> str:
    return "live" if IS_LIVE else "simulated"


if __name__ == "__main__":
    print()
    print("===================================================")
    print(f"  Circle Wallet Client -- Smoke Test")
    print(f"  Mode: {get_mode().upper()}")
    print("===================================================")
    print()
    print("  [1] Creating agent wallet...")
    agent = create_agent_wallet()
    print(f"      Wallet ID : {agent['circle_wallet_id']}")
    print(f"      Address   : {agent['circle_address']}")
    print(f"      Mode      : {agent['mode']}")
    print()
    bal = get_circle_wallet_balance(agent["circle_wallet_id"])
    print(f"  [2] Balance: ${bal:,.6f} USDC")
    print()
    test_addr = "0x8b98c38947A5659f61831ecF7E67cb30bde0beb5"
    print(f"  [3] Creating user wallet for: {test_addr}")
    user = create_circle_wallet(test_addr)
    print(f"      Wallet ID : {user['circle_wallet_id']}")
    print(f"      Address   : {user['circle_address']}")
    print()
