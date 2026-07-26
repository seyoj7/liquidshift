import sys
from agent.config import ARC_TESTNET_RPC_URL, USDC_CONTRACT_ADDRESS
from web3 import Web3

# Minimal ERC-20 ABI — just the read-only metadata functions we need for
# validating that USDC_CONTRACT_ADDRESS points to a real token contract.
_ERC20_META_ABI = [
    {"constant": True, "inputs": [], "name": "name",     "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol",   "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}],  "type": "function"},
]


def _query_usdc_contract(w3: Web3, address: str) -> dict:
    """Query ERC-20 metadata from the USDC contract to verify the address."""
    checksum = Web3.to_checksum_address(address)
    contract = w3.eth.contract(address=checksum, abi=_ERC20_META_ABI)
    return {
        "name":     contract.functions.name().call(),
        "symbol":   contract.functions.symbol().call(),
        "decimals": contract.functions.decimals().call(),
    }


def main() -> None:
    rpc_url = ARC_TESTNET_RPC_URL
    usdc_address = USDC_CONTRACT_ADDRESS
    if not usdc_address:
        print(
            "[!] USDC_CONTRACT_ADDRESS not set in .env.\n"
            "    Check the official reference and paste the address:\n"
            "    https://developers.circle.com/stablecoins/usdc-contract-addresses\n"
            "    Then add it to your .env file."
        )
        sys.exit(1)

    print(f"Connecting to Arc testnet RPC: {rpc_url}")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print("[X] Failed to connect to Arc testnet RPC.")
        sys.exit(1)

    chain_id = w3.eth.chain_id
    block_number = w3.eth.block_number

    # Validate the USDC contract address by querying on-chain metadata.
    usdc_info = None
    usdc_status = "NOT VERIFIED"
    try:
        usdc_info = _query_usdc_contract(w3, usdc_address)
        usdc_status = f"{usdc_info['name']} ({usdc_info['symbol']}, {usdc_info['decimals']} decimals)"
    except Exception as exc:
        usdc_status = f"FAILED — {exc}"

    print()
    print("===================================================")
    print("  LiquidShift — Arc Testnet Connection OK")
    print("===================================================")
    print(f"  Chain ID       : {chain_id}")
    print(f"  Block Number   : {block_number}")
    print(f"  USDC Address   : {usdc_address}")
    print(f"  USDC Contract  : {usdc_status}")
    print("===================================================")
    print()
    print(
        "Source for USDC address:\n"
        "  https://developers.circle.com/stablecoins/usdc-contract-addresses"
    )
    print()


if __name__ == "__main__":
    main()
