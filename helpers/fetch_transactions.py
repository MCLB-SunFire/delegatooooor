import os
import time
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Constants
SAFE_ADDRESS = os.getenv("SAFE_ADDRESS")
BASE_URL = os.getenv("BASE_URL")
MAX_RETRIES    = 4          # 1 s → 2 s → 4 s → 8 s
BACKOFF_FACTOR = 2

def fetch_recent_transactions(limit=15):
    """Fetch the last `limit` transactions from the Gnosis Safe API."""
    if not SAFE_ADDRESS or not BASE_URL:
        raise ValueError("Environment variables SAFE_ADDRESS and BASE_URL must be set.")

    url = f"{BASE_URL}/api/v1/safes/{SAFE_ADDRESS}/multisig-transactions/?limit={limit}"
    delay = 1

    for attempt in range(MAX_RETRIES):
    
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            results = response.json().get("results", [])

            # Add signature counts to each transaction
            for tx in results:
                tx["signature_count"] = len(tx.get("confirmations", []))
                tx["confirmations_required"] = tx.get("confirmationsRequired", 0)
            return results
        
        except (requests.exceptions.RequestException, ValueError) as e:
            print(f"Gnosis API error (attempt {attempt+1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(delay)
                delay *= BACKOFF_FACTOR
    # if All retries failed
    print("Gnosis API unreachable after retries — returning empty list.")
    return []        # graceful fallback

def filter_and_sort_pending_transactions(transactions):
    """
    Filter transactions to exclude executed transactions and older pending transactions for the same nonce.
    Only retain the newest pending transaction (based on submissionDate) for each nonce.
    """
    latest_transactions = {}

    for tx in transactions:

        # Ignore executed transactions and remove all others with the same nonce
        if tx["isExecuted"]:
            # Mark this nonce as executed and remove any existing pending transactions for it
            latest_transactions[tx["nonce"]] = tx
            continue

        # Only add the newest pending transaction for each nonce
        if tx["nonce"] not in latest_transactions or \
           tx["submissionDate"] > latest_transactions[tx["nonce"]]["submissionDate"]:
            latest_transactions[tx["nonce"]] = tx
        else:
            print(f"Ignoring older transaction - Nonce: {tx['nonce']} (submissionDate: {tx['submissionDate']})")

    # Filter out any executed transactions before returning pending ones
    filtered_transactions = [
        tx for tx in latest_transactions.values() if not tx["isExecuted"]
    ]

    # Sort by nonce for execution order
    filtered_transactions.sort(key=lambda tx: tx["nonce"])

    return filtered_transactions

def main():
    """Main function to fetch and process transaction data."""
    print("Fetching the last 15 transactions...")
    transactions = fetch_recent_transactions()
    
    if not transactions:
        print("No transactions fetched.")
        return

    print(f"Fetched {len(transactions)} transactions.")
    
    pending_transactions = filter_and_sort_pending_transactions(transactions)
    if pending_transactions:
        print(f"Found {len(pending_transactions)} pending transactions.")
        for tx in pending_transactions:
            print(f"Nonce: {tx['nonce']}, Signatures: {tx['signature_count']}/{tx['confirmations_required']}, Executed: {tx['isExecuted']}")
    else:
        print("No pending transactions found.")

if __name__ == "__main__":
    main()
