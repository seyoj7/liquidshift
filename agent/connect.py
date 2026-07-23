import os
import sys
from agent.config import ARC_TESTNET_RPC_URL, USDC_CONTRACT_ADDRESS
from web3 import Web3


def main() -> None:
    rpc_url = ARC_TESTNET_RPC_URL
    usdc_address = USDC_CONTRACT_ADDRESS
    if not usdc_address:
        print(
            "[!] USDC_CONTRACT_ADDRESS not set in .env.\n"
            "   Check the official reference and paste the address:\n"
            "   https://developers.circle.com/stablecoins/usdc-contract-addresses\n"
            "   Then add it to your .env file."
        )
        sys.exit(1)
    print(f"Connecting to Arc testnet RPC: {rpc_url}")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print("[X] Failed to connect to Arc testnet RPC.")
        sys.exit(1)
    chain_id = w3.eth.chain_id
    block_number = w3.eth.block_number
    print()
    print("===================================================")
    print("  LiquidShift -- Arc Testnet Connection OK")
    print("===================================================")
    print(f"  Chain ID       : {chain_id}")
    print(f"  Block Number   : {block_number}")
    print(f"  USDC Address   : {usdc_address}")
    print("===================================================")
    print()
    print("Source for USDC address:\n" "  https://developers.circle.com/stablecoins/usdc-contract-addresses")
    print()


if __name__ == "__main__":
    main()
