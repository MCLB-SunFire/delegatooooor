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
        return response.json()['results']
    except requests.exceptions.RequestException as e:
        print(f"Error fetching transactions: {e}")
        return []

def filter_and_sort_pending_transactions(transactions):
    """Filter for unexecuted transactions and sort by nonce in ascending order."""
    pending_transactions = [tx for tx in transactions if not tx['isExecuted']]
    return sorted(pending_transactions, key=lambda tx: tx['nonce'])

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
            print(f"Nonce: {tx['nonce']}, Executed: {tx['isExecuted']}")
    else:
        print("No pending transactions found.")

if __name__ == "__main__":
    main()
