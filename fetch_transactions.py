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
    """
    Filter transactions to exclude executed transactions and older pending transactions for the same nonce.
    Only retain the newest pending transaction (based on submissionDate) for each nonce.
    """
    latest_transactions = {}

    for tx in transactions:
        print(f"Processing Transaction - Nonce: {tx['nonce']}, Submission Date: {tx['submissionDate']}, isExecuted: {tx['isExecuted']}")

        # Ignore executed transactions entirely
        if tx["isExecuted"]:
            # If a nonce is executed, ensure all other pending transactions for the same nonce are ignored
            if tx["nonce"] in latest_transactions:
                del latest_transactions[tx["nonce"]]
            print(f"Ignoring executed transaction - Nonce: {tx['nonce']}")
            continue

        # Only add the newest pending transaction for each nonce
        if tx["nonce"] not in latest_transactions:
            # Add the transaction if it's the first one for this nonce
            print(f"Adding transaction - Nonce: {tx['nonce']} (submissionDate: {tx['submissionDate']})")
            latest_transactions[tx["nonce"]] = tx
        else:
            # Compare submission dates to keep the newest transaction
            current_tx = latest_transactions[tx["nonce"]]
            if tx["submissionDate"] > current_tx["submissionDate"]:
                print(f"Updating transaction - Keeping newer Nonce: {tx['nonce']} (submissionDate: {tx['submissionDate']})")
                latest_transactions[tx["nonce"]] = tx
            else:
                print(f"Ignoring older transaction - Nonce: {tx['nonce']} (submissionDate: {tx['submissionDate']})")

    # Convert to a sorted list by nonce
    filtered_transactions = sorted(latest_transactions.values(), key=lambda tx: tx["nonce"])

    # Debugging: Log the final filtered list
    print("Filtered Transactions (Final):")
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
