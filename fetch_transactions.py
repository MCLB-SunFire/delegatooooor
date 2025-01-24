import os
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Constants
SAFE_ADDRESS = os.getenv("SAFE_ADDRESS")
BASE_URL = os.getenv("BASE_URL")

def fetch_recent_transactions(limit=20):
    """Fetch the last `limit` transactions from the Gnosis Safe API."""
    if not SAFE_ADDRESS or not BASE_URL:
        raise ValueError("Environment variables SAFE_ADDRESS and BASE_URL must be set.")

    url = f"{BASE_URL}/api/v1/safes/{SAFE_ADDRESS}/multisig-transactions/?limit={limit}"
    
    try:
        response = requests.get(url)
        response.raise_for_status()
        results = response.json()['results']

        # Add signature counts to each transaction
        for tx in results:
            tx["signature_count"] = len(tx.get("confirmations", []))
            tx["confirmations_required"] = tx.get("confirmationsRequired", 0)

        return results
    except requests.exceptions.RequestException as e:
        print(f"Error fetching transactions: {e}")
        return []

def filter_and_sort_pending_transactions(transactions):
    """Filter for unexecuted transactions, remove duplicates by nonce, and sort by nonce."""
    pending_transactions = [tx for tx in transactions if not tx['isExecuted']]
    
    # Filter out duplicate nonces, keeping only the latest submissionDate
    unique_transactions = {}
    for tx in pending_transactions:
        # If a nonce is not yet in the dictionary or has an older submissionDate, replace it
        if tx["nonce"] not in unique_transactions or \
           tx["submissionDate"] > unique_transactions[tx["nonce"]]["submissionDate"]:
            unique_transactions[tx["nonce"]] = tx

    # Get the filtered transactions and sort them by nonce
    filtered_transactions = sorted(unique_transactions.values(), key=lambda tx: tx['nonce'])
    
    # Debugging: Print filtered transactions
    print("Filtered Transactions:")
    for tx in filtered_transactions:
        print(f"Nonce: {tx['nonce']}, Submission Date: {tx['submissionDate']}, Execution Date: {tx.get('executionDate', 'null')}")

    return filtered_transactions

def main():
    """Main function to fetch and process transaction data."""
    print("Fetching the last 20 transactions...")
    transactions = fetch_recent_transactions(limit=20)
    
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
