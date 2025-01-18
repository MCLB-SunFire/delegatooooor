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
    """Execute a Safe transaction using execTransaction."""
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

        # Prepare the parameters for execTransaction
        to = transaction["to"]
        value = int(transaction["value"])
        data = transaction["data"]
        operation = transaction.get("operation", 0)  # Default to 0 if not specified
        safeTxGas = transaction.get("safeTxGas", 0)
        baseGas = transaction.get("baseGas", 0)
        gasPrice = int(transaction.get("gasPrice", 0))  # uint256
        gasToken = transaction.get("gasToken", "0x0000000000000000000000000000000000000000")
        refundReceiver = transaction.get("refundReceiver", "0x0000000000000000000000000000000000000000")

        # Process and concatenate signatures
        if "confirmations" not in transaction or not transaction["confirmations"]:
            print(f"No confirmations (signatures) found for transaction with nonce {transaction['nonce']}.")
            return None

        signatures = b''
        for confirmation in transaction["confirmations"]:
            signature = confirmation["signature"]
            if not signature:
                print(f"Invalid signature found: {confirmation}")
                continue
            signatures += bytes.fromhex(signature[2:])  # Remove '0x' prefix and convert to bytes

        if not signatures:
            print("No valid signatures found for this transaction.")
            return None
        
        # Fetch the current network gas price
        network_gas_price = web3.eth.gas_price  # Ensure this is defined before use

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

        print(f"Transaction executed successfully. Hash: {tx_hash.hex()}")
        return tx_hash.hex()
    except Exception as e:
        print(f"Error executing transaction: {e}")
        return None