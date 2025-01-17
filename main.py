from staking_contract import get_staking_balance
from fetch_transactions import fetch_recent_transactions, filter_and_sort_pending_transactions
from decode_hex import decode_hex_data  # Import the decoding logic

def process_transactions():
    """Main function to fetch, decode, and evaluate pending transactions."""
    # Fetch the last 20 transactions
    transactions = fetch_recent_transactions(limit=20)

    # Filter and sort pending transactions
    pending_transactions = filter_and_sort_pending_transactions(transactions)

    if not pending_transactions:
        print("No pending transactions found.")
        return

    print(f"Processing {len(pending_transactions)} pending transactions...")

    # Fetch the staking contract balance
    staking_balance = get_staking_balance()
    if staking_balance is None:
        print("Failed to fetch staking contract balance.")
        return

    # Round the staking balance to 1 decimal place
    staking_balance = round(staking_balance, 1)
    print(f"Staking Contract Balance: {staking_balance} S tokens")

    for tx in pending_transactions:
        nonce = tx['nonce']
        hex_data = tx.get("data", "")

        if not hex_data:
            print(f"Transaction with Nonce {nonce} has no data.")
            continue

        # Decode the transaction data
        decoded_data = decode_hex_data(hex_data)
        if decoded_data:
            validator_id = decoded_data["validatorId"]
            amount_in_tokens = float(decoded_data["amountInTokens"])

            print(f"Nonce: {nonce}")
            print(f"Validator ID: {validator_id}, Amount: {amount_in_tokens} S tokens")

            # Compare staking balance with the required amount
            if staking_balance >= amount_in_tokens:
                print(f"Transaction with Nonce {nonce} is ready to execute.")
                # Placeholder: Add transaction execution logic here
            else:
                print(f"Insufficient balance for transaction with Nonce {nonce}.")
        else:
            print(f"Failed to decode data for Nonce {nonce}.")

if __name__ == "__main__":
    process_transactions()
