#!/usr/bin/env python3
"""Deploy a GenLayer intelligent contract to studionet and report the new
contract address + source-match verification.

Usage:
  .venv/bin/python scripts/deploy_studionet.py contracts/VeriGrant_flat.py [KEYFILE]

KEYFILE (default /root/.verigrant-deployer.env) holds DEPLOYER_KEY=0x...
If the keyfile is missing, creates a fresh account, funds it via the
sim_fundAccount faucet RPC, and prints the new key (save it yourself).

Requires: genlayer-py, eth-account, web3 in the active venv.
"""
import sys
import os
import base64
import hashlib

from eth_account import Account
from web3 import Web3
from genlayer_py.chains import studionet
from genlayer_py.client import GenLayerClient
from genlayer_py.types import TransactionStatus


def load_or_create_key(keyfile):
    if os.path.exists(keyfile):
        for line in open(keyfile):
            if line.startswith("DEPLOYER_KEY"):
                return Account.from_key(line.split("=", 1)[1].strip())
    acct = Account.create()
    with open(keyfile, "w") as f:
        f.write(f"DEPLOYER_ADDR={acct.address}\nDEPLOYER_KEY={acct.key.hex()}\n")
    os.chmod(keyfile, 0o600)
    print(f"CREATED new deployer {acct.address}, key saved to {keyfile}")
    return acct


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: deploy_studionet.py <contract.py> [keyfile]")
    contract_path = sys.argv[1]
    keyfile = sys.argv[2] if len(sys.argv) > 2 else "/root/.verigrant-deployer.env"

    acct = load_or_create_key(keyfile)
    client = GenLayerClient(studionet)
    client.local_account = acct
    addr = Web3.to_checksum_address(acct.address)

    # Fund via faucet (works on studionet despite SDK fund_account refusing it)
    if client.get_balance(addr) < 10**18:
        r = client.provider.make_request(
            method="sim_fundAccount", params=[addr, 10 * 10**18]
        )
        print("funded:", r.get("result", r))

    code = open(contract_path).read()
    tx = client.deploy_contract(code=code, account=acct)
    tx = tx.hex() if hasattr(tx, "hex") else str(tx)
    print("DEPLOY_TX:", tx)

    client.wait_for_transaction_receipt(
        tx, status=TransactionStatus.FINALIZED, retries=60, interval=3000
    )

    t = client.get_transaction(tx)
    data = t.get("data") or {}
    contract_address = data.get("contract_address")
    print("CONTRACT_ADDRESS:", contract_address)
    print("STATUS:", t.get("status_name"), t.get("result_name"))

    # Verify deployed source == local source (contract_code is base64)
    deployed_b64 = data.get("contract_code")
    if deployed_b64:
        deployed = base64.b64decode(deployed_b64).decode()
        match = deployed.strip() == code.strip()
        print("SOURCE_MATCH:", match,
              "sha256:", hashlib.sha256(deployed.encode()).hexdigest()[:16])

    # Smoke-read a view if present
    if contract_address:
        try:
            r = client.read_contract(
                address=Web3.to_checksum_address(contract_address),
                function_name="get_stats",
            )
            print("READ_OK get_stats:", r)
        except Exception as e:
            print("read note:", str(e)[:120])

    print("EXPLORER: https://explorer-studio.genlayer.com/address/" + contract_address)


if __name__ == "__main__":
    main()
