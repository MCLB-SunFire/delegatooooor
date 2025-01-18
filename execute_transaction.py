import os
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

# Connect to the Sonic RPC
web3 = Web3(Web3.HTTPProvider(SONIC_RPC_URL))
if web3.is_connected():
    print("Connected to Sonic network")
else:
    raise ConnectionError("Failed to connect to Sonic network")

# Load account from private key
account = Account.from_key(PRIVATE_KEY)
print(f"Executor Address: {account.address}")

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
                        print(f"Found transaction for nonce {nonce}: {tx}")
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

def execute_transaction(transaction):
    """Execute a transaction if it is ready."""
    try:
        # Ensure the transaction has all required fields
        if not transaction:
            print("Transaction object is None.")
            return None

        if "to" not in transaction or "data" not in transaction or "value" not in transaction:
            print(f"Transaction object is missing required fields: {transaction}")
            return None

        # Log transaction details
        print(f"Executing transaction: {transaction}")

        # Prepare the transaction
        execution_tx = {
            "to": transaction["to"],
            "value": int(transaction["value"]),
            "data": transaction["data"],
            "gas": 350000,  # Adjust gas limit if necessary
            "gasPrice": web3.eth.gas_price,
            "nonce": web3.eth.get_transaction_count(account.address),
            "chainId": web3.eth.chain_id,  # Include chain ID for EIP-155
        }

        print(f"Prepared transaction: {execution_tx}")

        # Sign and send the transaction
        signed_tx = web3.eth.account.sign_transaction(execution_tx, PRIVATE_KEY)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)

        print(f"Transaction executed successfully. Hash: {web3.to_hex(tx_hash)}")  # Updated here
        return web3.to_hex(tx_hash)  # Updated here
    except Exception as e:
        print(f"Error executing transaction: {e}")
        return None