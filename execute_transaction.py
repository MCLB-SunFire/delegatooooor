import os
import time
import requests
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Fetch environment variables
BASE_URL = os.getenv("BASE_URL")
SAFE_ADDRESS = os.getenv("SAFE_ADDRESS")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
SONIC_RPC_URL = os.getenv("SONIC_RPC_URL")

# Define the Safe ABI (only the `execTransaction` method is needed)
SAFE_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "data", "type": "bytes"},
            {"name": "operation", "type": "uint8"},
            {"name": "safeTxGas", "type": "uint256"},
            {"name": "baseGas", "type": "uint256"},
            {"name": "gasPrice", "type": "uint256"},
            {"name": "gasToken", "type": "address"},
            {"name": "refundReceiver", "type": "address"},
            {"name": "signatures", "type": "bytes"},
        ],
        "name": "execTransaction",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

# Connect to the Sonic RPC
web3 = Web3(Web3.HTTPProvider(SONIC_RPC_URL))
if web3.is_connected():
    print("Connected to Sonic network")
else:
    raise ConnectionError("Failed to connect to Sonic network")

# Load account from private key
account = Account.from_key(PRIVATE_KEY)
print(f"Executor Address: {account.address}")

# Create the Safe contract instance
safe_contract = web3.eth.contract(address=Web3.to_checksum_address(SAFE_ADDRESS), abi=SAFE_ABI)

def wait_for_receipt(tx_hash, timeout=240, poll_interval=3):
    try:
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout, poll_latency=poll_interval)
        return receipt
    except Exception as e:
        print(f"Error waiting for receipt: {e}")
        return None

def fetch_transaction_by_nonce(nonce):
    """Fetch transaction details from the Safe API by nonce."""
    try:
        # Fetch all pending transactions
        url = f"{BASE_URL}/api/v1/safes/{SAFE_ADDRESS}/multisig-transactions/"
        response = requests.get(url)
        print(f"Fetching transactions for Safe {SAFE_ADDRESS}: {response.status_code}")

        # Check for successful response
        if response.status_code == 200:
            data = response.json()
            if "results" in data:
                # Filter for the transaction with the specific nonce
                for tx in data["results"]:
                    if tx["nonce"] == nonce:
                        return tx

            print(f"No transaction found for nonce {nonce}.")
            return None

        # Handle API errors
        print(f"Failed to fetch transactions. Status code: {response.status_code}")
        print(f"Response: {response.text}")
        return None

    except Exception as e:
        print(f"Error fetching transaction by nonce: {e}")
        return None

def is_transaction_executable(transaction):
    """Check if a transaction is ready for execution."""
    if not transaction:
        return False
    if transaction["isExecuted"]:
        print(f"Transaction with nonce {transaction['nonce']} has already been executed.")
        return False
    if len(transaction["confirmations"]) < transaction["confirmationsRequired"]:
        print(f"Transaction with nonce {transaction['nonce']} is missing signatures.")
        return False
    return True

def collect_and_sort_signatures(transaction):
    """Collect and sort signatures based on the owner's address."""
    if "confirmations" not in transaction or not transaction["confirmations"]:
        print(f"No confirmations (signatures) found for transaction with nonce {transaction['nonce']}.")
        return None

    # Sort confirmations by owner address
    confirmations = sorted(transaction["confirmations"], key=lambda x: x["owner"].lower())

    signatures = b''
    for confirmation in confirmations:
        signature = confirmation["signature"]
        if not signature:
            print(f"Invalid signature found: {confirmation}")
            continue
        signatures += bytes.fromhex(signature[2:])  # Remove '0x' prefix and convert to bytes

    if not signatures:
        print("No valid signatures found for this transaction.")
        return None

    return signatures

def execute_transaction(transaction):
    """Execute a Safe transaction using execTransaction with retry mechanism and exponential backoff."""
    max_retries = 5
    attempt = 0
    delay = 1  # Initial delay in seconds
    while attempt < max_retries:
        try:
            # Ensure the transaction has all required fields
            if not transaction:
                print("Transaction object is None.")
                return None

            if "to" not in transaction or "data" not in transaction or "value" not in transaction:
                print(f"Transaction object is missing required fields: {transaction}")
                return None

            # Prepare the parameters for execTransaction
            to = transaction["to"]
            value = int(transaction["value"])
            data = transaction.get("data", b"")  # Ensure default to empty bytes
            if data is None:
                data = b""  # Explicitly set None to empty bytes
            elif isinstance(data, str):  # Convert hex string to bytes if needed
                data = bytes.fromhex(data.lstrip("0x"))
            operation = transaction.get("operation", 0)  # Default to 0 if not specified
            safeTxGas = transaction.get("safeTxGas", 0)
            baseGas = transaction.get("baseGas", 0)
            gasPrice = int(transaction.get("gasPrice", 0))  # uint256
            gasToken = transaction.get("gasToken", "0x0000000000000000000000000000000000000000")
            refundReceiver = transaction.get("refundReceiver", "0x0000000000000000000000000000000000000000")

            # Collect and sort signatures
            signatures = collect_and_sort_signatures(transaction)
            if not signatures:
                print("No valid signatures available.")
                return None

            # Fetch the current network gas price
            network_gas_price = web3.eth.gas_price

            # Call the Safe's execTransaction function
            tx = safe_contract.functions.execTransaction(
                to,
                value,
                data,
                operation,
                safeTxGas,
                baseGas,
                gasPrice,
                gasToken,
                refundReceiver,
                signatures,
            ).build_transaction({
                "from": account.address,
                "gas": 350000,
                "gasPrice": network_gas_price,  # Network-level gas price for blockchain
                "nonce": web3.eth.get_transaction_count(account.address),
                "chainId": web3.eth.chain_id,
            })

            # Sign and send the transaction
            signed_tx = web3.eth.account.sign_transaction(tx, PRIVATE_KEY)
            tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)

            # If the caller wants to gate on mining, wait and return status
            if transaction.get("_wait_for_receipt", False):
                receipt = wait_for_receipt(tx_hash)
                ok = bool(receipt and getattr(receipt, "status", 0) == 1)
                return {"ok": ok, "tx_hash": web3.to_hex(tx_hash), "receipt": receipt}

            # Legacy behavior (return immediately)
            return web3.to_hex(tx_hash)
        
        except Exception as e:
            attempt += 1
            print(f"Error executing transaction (Attempt {attempt}/{max_retries}): {e}")
            if attempt == max_retries:
                print("Max retries reached. Transaction execution failed.")
                return None
            time.sleep(delay)
            delay *= 2  # Exponential backoff
