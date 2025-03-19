import requests
import time
import os
from web3 import Web3

API_KEY = os.getenv("SONICSCAN_API_KEY")
CONTRACT_ADDRESS = "0xE5DA20F15420aD15DE0fa650600aFc998bbE3955"
DEPOSIT_EVENT_TOPIC = "0x73a19dd210f1a7f902193214c0ee91dd35ee5b4d920cba8d519eca65a7b488ca"
MAX_RETRIES = 5
INITIAL_DELAY = 1  # API rate limit handling
REQUEST_TIMEOUT = 5  # Limit API request timeouts to 5s max
DECIMALS = 10**18  # Convert wei to human-readable format
FLAG_THRESHOLD = 100000  # Flag deposits ≥ 100,000 S tokens
MAX_MESSAGE_LENGTH = 2000 # Split long discord messages into 2000-character chunks

# Initialize Web3 for decoding hex values
w3 = Web3()

def make_request(url):
    """Helper function to make an API request with error handling and retries."""
    delay = INITIAL_DELAY
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(delay)  # Respect rate limits
            response = requests.get(url, timeout=5)  # Apply 5-second timeout
            response.raise_for_status()  # Handle HTTP errors

            # Parse JSON safely
            data = response.json()
            if "result" in data:
                return data

        except (requests.exceptions.Timeout):
            print(f"⏳ Timeout error (attempt {attempt + 1}): API did not respond within 5 seconds.")
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
                f"[{tx_hash}]({sonicscan_tx_url}{tx_hash}), which is above the current alert threshold of {FLAG_THRESHOLD:,.0f} S tokens."
            )
        # Optionally, you can add non-alert deposits to the message (or skip them)
    
    if alert_triggered:
        message = "\n\n".join(messages) + "\n\nAutomated executions are now paused. Please investigate <@538717564067381249> and resume automation when satisfied."
        return True, message
    else:
        return False, f"No deposits over {FLAG_THRESHOLD:,.0f} were made in the last hour."

def check_large_deposits_with_block(start_block=None):
    """
    Runs the deposit monitor check.
    If start_block is provided, scans from that block; otherwise, defaults to a 65-minute lookback.
    Returns a tuple: (alert_triggered, message, last_block_scanned)
    """
    # If no start block provided, do a full 65-minute lookback.
    if start_block is None:
        one_hour_ago = int(time.time()) - 3900  # 65 minutes ago
        block_time_url = f"https://api.sonicscan.org/api?module=block&action=getblocknobytime&timestamp={one_hour_ago}&closest=before&apikey={API_KEY}"
        block_response = make_request(block_time_url)
        if not block_response:
            return False, "Error: Could not fetch block time.", None
        start_block = int(block_response["result"])
    
    # Get the latest block number
    latest_block_url = f"https://api.sonicscan.org/api?module=proxy&action=eth_blockNumber&apikey={API_KEY}"
    latest_block_response = make_request(latest_block_url)
    if not latest_block_response:
        return False, "Error: Could not fetch latest block.", None
    latest_block = int(latest_block_response["result"], 16)

    # Debug log for block numbers
    print(f"🟢 Scanning from block {start_block} to {latest_block}")
    
    # Fetch deposit transactions from start_block to latest_block
    tx_url = f"https://api.sonicscan.org/api?module=logs&action=getLogs&fromBlock={start_block}&toBlock={latest_block}&address={CONTRACT_ADDRESS}&topic0={DEPOSIT_EVENT_TOPIC}&apikey={API_KEY}"
    tx_response = make_request(tx_url)
    if not tx_response:
        return False, "Error: Could not fetch deposit logs.", None
    deposits = tx_response.get("result", [])
    
    # Process deposits and build the alert message; track the highest block scanned.
    alert_triggered = False
    messages = []
    sonicscan_tx_url = f"https://sonicscan.org/tx/"
    debank_url = f"https://debank.com/profile/"

    if deposits:
    # Use the last deposit block instead of the latest block if deposits were found
        last_block_scanned = max(
            int(deposit["blockNumber"], 16) if isinstance(deposit["blockNumber"], str) else int(deposit["blockNumber"])
            for deposit in deposits
    )
    else:
        # If no deposits were found, default to the latest block
        last_block_scanned = latest_block


    for deposit in deposits:
        tx_hash = deposit.get('transactionHash', 'N/A')
        sender = f"0x{deposit['topics'][1][-40:]}"
        raw_amount_assets = deposit.get("data", "0x0")[:66]
        deposit_amount_wei = w3.to_int(hexstr=raw_amount_assets)
        deposit_amount = deposit_amount_wei / DECIMALS

        # Update last_block_scanned (if blockNumber is hex, convert it)
        deposit_block = int(deposit.get("blockNumber"), 16) if isinstance(deposit.get("blockNumber"), str) else int(deposit.get("blockNumber"))
        last_block_scanned = max(last_block_scanned, deposit_block)

        if deposit_amount >= FLAG_THRESHOLD:
            alert_triggered = True
            messages.append(
                f"**ALERT!**, {deposit_amount:,.2f} $S deposit by [DeBank Wallet](<{debank_url}{sender}>) at [SonicScan TX]({sonicscan_tx_url}{tx_hash}). Alert threshold = {FLAG_THRESHOLD:,.0f} $S."
            )

    if alert_triggered:
        message = "\n\n".join(messages) + "\n\nAutomated executions are now paused. Please investigate <@538717564067381249> and resume automation when satisfied."
        return True, message, last_block_scanned
    else:
        return False, f"No deposits over {FLAG_THRESHOLD:,.0f} S tokens were made in the last hour.", last_block_scanned

def check_large_deposits_custom(hours):
    """
    Runs a historical large deposit check for a user-specified time window (in hours).
    This function does NOT trigger alerts or pause automation.
    Returns a tuple: (alert_triggered, message).
    """
    BLOCK_CHUNK_SIZE = 100_000 # for history command deep search
    MIN_BLOCK_CHUNK = 3_125  # Minimum chunk size before failing completely
    RETRY_LIMIT = 2  # Number of retries before reducing chunk size

    window_seconds = int(hours * 3600)
    start_time = int(time.time()) - window_seconds
    block_time_url = f"https://api.sonicscan.org/api?module=block&action=getblocknobytime&timestamp={start_time}&closest=before&apikey={API_KEY}"

    block_response = make_request(block_time_url)
    if not block_response:
        print("🚨 Error: Could not fetch block time. Exiting history scan.")
        return False, "Error: Could not fetch block time."

    start_block = int(block_response["result"])

    latest_block_url = f"https://api.sonicscan.org/api?module=proxy&action=eth_blockNumber&apikey={API_KEY}"
    latest_block_response = make_request(latest_block_url)
    if not latest_block_response:
        print("🚨 Error: Could not fetch latest block number. Exiting history scan.")
        return False, "Error: Could not fetch latest block."

    latest_block = int(latest_block_response["result"], 16)

    # Start with large chunk size but adjust dynamically if API struggles
    deposits = []
    current_start_block = start_block

    while current_start_block < latest_block:
        current_end_block = min(current_start_block + BLOCK_CHUNK_SIZE, latest_block)
        retries = 0

        while retries < RETRY_LIMIT:
            print(f"🔄 Querying blocks {current_start_block} to {current_end_block} (Chunk size: {BLOCK_CHUNK_SIZE})")
            
            tx_url = (
                f"https://api.sonicscan.org/api?module=logs&action=getLogs"
                f"&fromBlock={current_start_block}&toBlock={current_end_block}"
                f"&address={CONTRACT_ADDRESS}&topic0={DEPOSIT_EVENT_TOPIC}&apikey={API_KEY}"
            )

            tx_response = make_request(tx_url)

            if tx_response and "result" in tx_response:
                print(f"✅ Retrieved {len(tx_response['result'])} transactions from blocks {current_start_block} to {current_end_block}.")
                deposits.extend(tx_response["result"])
                break  # Success, exit retry loop

            else:
                print(f"⚠️ Warning: No response or empty data for blocks {current_start_block} to {current_end_block}. Possible timeout or rate limit.")
                retries += 1
                time.sleep(10 * retries)  # Wait longer on each retry
            
                # If we hit retry limit, reduce block chunk size
                if retries == RETRY_LIMIT and BLOCK_CHUNK_SIZE > MIN_BLOCK_CHUNK:
                    BLOCK_CHUNK_SIZE = max(BLOCK_CHUNK_SIZE // 2, MIN_BLOCK_CHUNK)
                    print(f"⚠️ Reducing block chunk size to {BLOCK_CHUNK_SIZE} and retrying.")

        # **🚨 Final Failure Condition**
        if retries == RETRY_LIMIT and BLOCK_CHUNK_SIZE == MIN_BLOCK_CHUNK:
            print("🚨 ERROR: All retries failed! Could not retrieve deposit history.")
            return False, "Error: API rate limits or network failures prevented retrieving historical deposits."                    

        # Move to the next chunk
        current_start_block = current_end_block + 1

    # Process deposits and filter only large ones
    messages = []
    sonicscan_tx_url = "https://sonicscan.org/tx/"
    debank_url = f"https://debank.com/profile/"

    for deposit in deposits:
        tx_hash = deposit.get('transactionHash', 'N/A')
        sender = f"0x{deposit['topics'][1][-40:]}"
        raw_amount_assets = deposit.get("data", "0x0")[:66]
        deposit_amount_wei = w3.to_int(hexstr=raw_amount_assets)
        deposit_amount = deposit_amount_wei / DECIMALS

        if deposit_amount >= FLAG_THRESHOLD:
            messages.append(
                f"{deposit_amount:,.2f} $S deposited by [DeBank Wallet](<{debank_url}{sender}>) at [SonicScan TX]({sonicscan_tx_url}{tx_hash})\u200B"
            )

    if messages:
        print(f"🚀 Found {len(messages)} large deposits in the last {hours} hours.")
        return True, "\n\n".join(messages)
    else:
        print(f"✅ No large deposits (≥ {FLAG_THRESHOLD:,.0f} S tokens) found in the last {hours} hours.")
        return False, f"✅ No large deposits (≥ {FLAG_THRESHOLD:,.0f} S tokens) were found in the last {hours} hours."

def split_long_message(msg, max_length=MAX_MESSAGE_LENGTH):
    """Splits a long message into multiple messages under Discord's 2000-character limit."""
    messages = []
    while len(msg) > max_length:
        split_index = msg.rfind("\n", 0, max_length)  # Find a good place to split (newline)
        if split_index == -1:  # If no newline found, split at the max length
            split_index = max_length
        messages.append(msg[:split_index])
        msg = msg[split_index:].lstrip()  # Remove leading whitespace from next part
    messages.append(msg)
    return messages