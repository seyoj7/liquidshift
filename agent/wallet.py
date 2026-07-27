import os
import sys
from decimal import Decimal
from agent.config import ARC_TESTNET_RPC_URL
from web3 import Web3

NATIVE_DECIMALS = 18


def get_web3() -> Web3:
    rpc_url = ARC_TESTNET_RPC_URL
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    import time as _time

    for attempt in range(3):
        if w3.is_connected():
            return w3
        if attempt < 2:
            _time.sleep(1)
            w3 = Web3(Web3.HTTPProvider(rpc_url))
    print("[X] Failed to connect to Arc testnet RPC after 3 attempts.")
    sys.exit(1)


def read_usdc_balance(w3: Web3, address: str) -> Decimal:
    checksum_address = Web3.to_checksum_address(address)
    raw_balance = w3.eth.get_balance(checksum_address)
    return Decimal(raw_balance) / Decimal(10**NATIVE_DECIMALS)


def main() -> None:
    from agent.circle_wallet import create_agent_wallet, get_circle_wallet_balance

    w3 = get_web3()
    agent_wallet = create_agent_wallet()
    address = agent_wallet["circle_address"]
    mode = agent_wallet["mode"]
    if address:
        balance = read_usdc_balance(w3, address)
    else:
        balance = Decimal(0)
    circle_balance = get_circle_wallet_balance(agent_wallet["circle_wallet_id"])
    chain_id = w3.eth.chain_id
    block = w3.eth.block_number
    print()
    print("===================================================")
    print("  LiquidShift -- Wallet Info (Circle Wallet)")
    print("===================================================")
    print(f"  Chain ID          : {chain_id}")
    print(f"  Block             : {block}")
    print(f"  Circle Wallet ID  : {agent_wallet['circle_wallet_id']}")
    print(f"  On-chain Address  : {address}")
    print(f"  Mode              : {mode}")
    print(f"  On-chain Balance  : ${balance:,.6f} USDC")
    print(f"  Circle Balance    : ${circle_balance:,.6f} USDC")
    print("===================================================")
    print()
    if address:
        print("Verify on explorer: https://testnet.arcscan.app/address/" + address)
        print()


if __name__ == "__main__":
    main()
