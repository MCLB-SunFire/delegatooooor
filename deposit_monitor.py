import requests
import time
import os
from web3 import Web3

API_KEY = os.getenv("SONICSCAN_API_KEY")
CONTRACT_ADDRESS = "0xE5DA20F15420aD15DE0fa650600aFc998bbE3955"
DEPOSIT_EVENT_TOPIC = "0x73a19dd210f1a7f902193214c0ee91dd35ee5b4d920cba8d519eca65a7b488ca"
MAX_RETRIES = 5
INITIAL_DELAY = 1  # API rate limit handling
DECIMALS = 10**18  # Convert wei to human-readable format
FLAG_THRESHOLD = 100000  # Flag deposits ≥ 100,000 S tokens

# Initialize Web3 for decoding hex values
w3 = Web3()

def make_request(url):
    """Helper function to make an API request with error handling and retries."""
    delay = INITIAL_DELAY
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(delay)  # Respect rate limits
            response = requests.get(url)
            response.raise_for_status()  # Handle HTTP errors

            # Parse JSON safely
            data = response.json()
            if "result" in data:
                return data

        except (requests.exceptions.RequestException, ValueError) as e:
            print(f"❌ API request failed (attempt {attempt + 1}): {e}")

        delay *= 2  # Exponential backoff (1s, 2s, 4s, 8s, 16s)

    print("🚨 Max retries reached. Skipping this request.")
    return None  # Return None if all retries fail

# Step 1: Get the block number from 1 hour ago plus 5 minute overlap
one_hour_ago = int(time.time()) - 3900  # Unix timestamp for 65 minutes ago
block_time_url = f"https://api.sonicscan.org/api?module=block&action=getblocknobytime&timestamp={one_hour_ago}&closest=before&apikey={API_KEY}"

block_response = make_request(block_time_url)
if not block_response:
    exit()
block_one_hour_ago = int(block_response["result"])

# Step 2: Get the latest block number
latest_block_url = f"https://api.sonicscan.org/api?module=proxy&action=eth_blockNumber&apikey={API_KEY}"

latest_block_response = make_request(latest_block_url)
if not latest_block_response:
    exit()
latest_block = int(latest_block_response["result"], 16)

# Step 3: Fetch deposit transactions within the block range
tx_url = f"https://api.sonicscan.org/api?module=logs&action=getLogs&fromBlock={block_one_hour_ago}&toBlock={latest_block}&address={CONTRACT_ADDRESS}&topic0={DEPOSIT_EVENT_TOPIC}&apikey={API_KEY}"

tx_response = make_request(tx_url)
if not tx_response:
    exit()
deposits = tx_response.get("result", [])

# Step 4: Process deposits and extract `amountAssets`
for deposit in deposits:
    tx_hash = deposit.get('transactionHash', 'N/A')

    # Extract sender from `topics[1]`
    sender_topic = deposit["topics"][1]  # Extract raw hex sender address
    sender = f"0x{sender_topic[-40:]}"  # Convert to standard Ethereum address format

    # Extract deposit amount from `data`
    raw_amount_assets = deposit.get("data", "0x0")[:66]  # First 32 bytes (amountAssets)
    deposit_amount_wei = w3.to_int(hexstr=raw_amount_assets)

    # Convert to standard decimal format
    deposit_amount = deposit_amount_wei / DECIMALS  

    # Flag large deposits
    if deposit_amount >= FLAG_THRESHOLD:
        print(f"🚨 **LARGE DEPOSIT ALERT** 🚨")
        print(f"Deposit Tx: {tx_hash} | From: {sender} | Amount: {deposit_amount:,.2f} S tokens")
        print("-----------------------------------------------------")
    else:
        print(f"Deposit Tx: {tx_hash} | From: {sender} | Amount: {deposit_amount:,.2f} S tokens")

def check_large_deposits():
    """
    Runs the deposit monitor check over the last 65 minutes.
    Returns a tuple: (alert_triggered, message)
      - alert_triggered: True if any deposit ≥ FLAG_THRESHOLD was found.
      - message: A string containing details of large deposits or a 'no deposits' message.
    """
    # Step 1: Get the block number from 65 minutes ago
    one_hour_ago = int(time.time()) - 3900  # 65 minutes ago
    block_time_url = f"https://api.sonicscan.org/api?module=block&action=getblocknobytime&timestamp={one_hour_ago}&closest=before&apikey={API_KEY}"
    block_response = make_request(block_time_url)
    if not block_response:
        return False, "Error: Could not fetch block time."
    block_one_hour_ago = int(block_response["result"])

    # Step 2: Get the latest block number
    latest_block_url = f"https://api.sonicscan.org/api?module=proxy&action=eth_blockNumber&apikey={API_KEY}"
    latest_block_response = make_request(latest_block_url)
    if not latest_block_response:
        return False, "Error: Could not fetch latest block."
    latest_block = int(latest_block_response["result"], 16)

    # Step 3: Fetch deposit transactions within the block range
    tx_url = f"https://api.sonicscan.org/api?module=logs&action=getLogs&fromBlock={block_one_hour_ago}&toBlock={latest_block}&address={CONTRACT_ADDRESS}&topic0={DEPOSIT_EVENT_TOPIC}&apikey={API_KEY}"
    tx_response = make_request(tx_url)
    if not tx_response:
        return False, "Error: Could not fetch deposit logs."
    deposits = tx_response.get("result", [])

    # Step 4: Process deposits and build the alert message
    alert_triggered = False
    messages = []
    sonicscan_tx_url = "https://sonicscan.org/tx/"

    for deposit in deposits:
        tx_hash = deposit.get('transactionHash', 'N/A')
        # Extract sender from topics[1]
        sender_topic = deposit["topics"][1]
        sender = f"0x{sender_topic[-40:]}"
        raw_amount_assets = deposit.get("data", "0x0")[:66]
        deposit_amount_wei = w3.to_int(hexstr=raw_amount_assets)
        deposit_amount = deposit_amount_wei / DECIMALS

        if deposit_amount >= FLAG_THRESHOLD:
            alert_triggered = True
            messages.append(
                f"A deposit for {deposit_amount:,.2f} S tokens was made by {sender} at "
                f"[{tx_hash}]({sonicscan_tx_url}{tx_hash}), which is above the current alert threshold of {FLAG_THRESHOLD} S tokens."
            )
        # Optionally, you can add non-alert deposits to the message (or skip them)
    
    if alert_triggered:
        message = "\n".join(messages) + "\nAutomated executions are now paused. Please investigate <@538717564067381249> and resume automation when satisfied."
        return True, message
    else:
        return False, f"No deposits over {FLAG_THRESHOLD} were made in the last hour."

