import requests
import time
import os
import json
import asyncio
from web3 import Web3

API_KEY = os.getenv("ETHERSCAN_API_KEY")
ETHERSCAN_V2 = "https://api.etherscan.io/v2/api?chainid=146"
CONTRACT_ADDRESS = "0xE5DA20F15420aD15DE0fa650600aFc998bbE3955"
DEPOSIT_EVENT_TOPIC = "0x73a19dd210f1a7f902193214c0ee91dd35ee5b4d920cba8d519eca65a7b488ca"
MAX_RETRIES = 5
INITIAL_DELAY = 1  # API rate limit handling
REQUEST_TIMEOUT = 5  # Limit API request timeouts to 5s max
DECIMALS = 10**18  # Convert wei to human-readable format
FLAG_THRESHOLD = 100000  # Flag deposits ≥ 100,000 S tokens
MAX_MESSAGE_LENGTH = 2000 # Split long discord messages into 2000-character chunks
PERSISTENCE_FILE = "/data/last_scanned_block.json"  # /data is the mounted volume

# Initialize Web3 for decoding hex values
w3 = Web3()

def load_last_scanned_block():
    """Read persisted last scanned block number from JSON file. Returns int or None."""
    try:
        if not os.path.exists(PERSISTENCE_FILE):
            return None
        with open(PERSISTENCE_FILE, "r") as f:
            data = json.load(f)
        return data.get("last_scanned_block")
    except Exception as e:
        print(f"⚠️ Failed to read {PERSISTENCE_FILE}: {e}")
        return None

def save_last_scanned_block(block_num: int):
    """Persist last scanned block number to JSON file."""
    try:
        with open(PERSISTENCE_FILE, "w") as f:
            json.dump({"last_scanned_block": int(block_num)}, f)
    except Exception as e:
        print(f"⚠️ Failed to write {PERSISTENCE_FILE}: {e}")

async def run_deposit_probe(start_block=None):
    """
    Checks for large deposits starting from `start_block` (or last persisted block if None).
    Saves the latest scanned block. Returns (alert_triggered, deposit_message, start_block, new_last_block).
    """
    from deposit_monitor import check_large_deposits_with_block, FLAG_THRESHOLD

    # Read last block if no start_block provided
    old_persisted_block = load_last_scanned_block()
    if start_block is None:
        start_block = old_persisted_block + 1 if old_persisted_block is not None else None

    # Run check
    alert_triggered, deposit_message, new_last_block = await asyncio.to_thread(
        check_large_deposits_with_block, start_block
    )

    # Save updated block
    if new_last_block is not None:
        if old_persisted_block is not None:
            print(f"✅ Updating last scanned block from {old_persisted_block} to {new_last_block}")
        else:
            print(f"✅ Setting last_scanned_block for the first time: {new_last_block}")
        save_last_scanned_block(new_last_block)
    else:
        print("⚠️ Warning: new_last_block returned as None. Retrying from previous block next loop.")

    # No deposit found
    if not alert_triggered:
        deposit_message = (
            f"✅ No deposits over {FLAG_THRESHOLD:,.0f} S tokens were found "
            f"between blocks {start_block} and {new_last_block}."
        )

    return alert_triggered, deposit_message, start_block, new_last_block

def make_request(url):
    """Helper function to make an API request with error handling and retries."""
    delay = INITIAL_DELAY
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(delay)  # Respect rate limits
            response = requests.get(url, timeout=REQUEST_TIMEOUT)  # Apply 5-second timeout
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

def check_large_deposits_with_block(start_block=None):
    """
    Runs the deposit monitor check.
    If start_block is provided, scans from that block; otherwise, defaults to a 65-minute lookback.
    Returns a tuple: (alert_triggered, message, last_block_scanned)
    """
    # If no start block provided, do a full 65-minute lookback.
    if start_block is None:
        one_hour_ago = int(time.time()) - 3900  # 65 minutes ago
        block_time_url = f"{ETHERSCAN_V2}&module=block&action=getblocknobytime&timestamp={one_hour_ago}&closest=before&apikey={API_KEY}"
        block_response = make_request(block_time_url)
        if not block_response:
            return False, "Error: Could not fetch block time.", None
        start_block = int(block_response["result"])
    
    # Get the latest block number
    latest_block_url = f"{ETHERSCAN_V2}&module=proxy&action=eth_blockNumber&apikey={API_KEY}"
    latest_block_response = make_request(latest_block_url)
    if not latest_block_response:
        return False, "Error: Could not fetch latest block.", None
    latest_block = int(latest_block_response["result"], 16)

    # Debug log for block numbers
    print(f"🟢 Scanning from block {start_block} to {latest_block}")
    
    # Fetch deposit transactions from start_block to latest_block
    tx_url = f"{ETHERSCAN_V2}&module=logs&action=getLogs&fromBlock={start_block}&toBlock={latest_block}&address={CONTRACT_ADDRESS}&topic0={DEPOSIT_EVENT_TOPIC}&apikey={API_KEY}"
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
        return False, "message", last_block_scanned

def check_large_deposits_custom(hours):
    """
    Runs a historical large deposit check for a user-specified time window (in hours).
    This function does NOT trigger alerts or pause automation.
    Returns a tuple: (alert_triggered, message).
    """
    BLOCK_CHUNK_SIZE = 25_000 # for history command deep search
    MIN_BLOCK_CHUNK = 3_125  # Minimum chunk size before failing completely
    RETRY_LIMIT = 2  # Number of retries before reducing chunk size

    window_seconds = int(hours * 3600)
    start_time = int(time.time()) - window_seconds
    block_time_url = f"{ETHERSCAN_V2}&module=block&action=getblocknobytime&timestamp={start_time}&closest=before&apikey={API_KEY}"

    block_response = make_request(block_time_url)
    if not block_response:
        print("🚨 Error: Could not fetch block time. Exiting history scan.")
        return False, "Error: Could not fetch block time."

    start_block = int(block_response["result"])

    latest_block_url = f"{ETHERSCAN_V2}&module=proxy&action=eth_blockNumber&apikey={API_KEY}"
    latest_block_response = make_request(latest_block_url)
    if not latest_block_response:
        print("🚨 Error: Could not fetch latest block number. Exiting history scan.")
        return False, "Error: Could not fetch latest block."

    latest_block = int(latest_block_response["result"], 16)

    # Start with large chunk size but adjust dynamically if API struggles
    deposits = []
    current_start_block = start_block

    while current_start_block <= latest_block:
        current_end_block = min(current_start_block + BLOCK_CHUNK_SIZE, latest_block)
        retries = 0

        while retries < RETRY_LIMIT:
            print(f"🔄 Querying blocks {current_start_block} to {current_end_block} (Chunk size: {BLOCK_CHUNK_SIZE})")
            
            tx_url = (
                f"{ETHERSCAN_V2}&module=logs&action=getLogs"
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
                f"{deposit_amount:,.2f} $S deposited by [DeBank Wallet](<{debank_url}{sender}>) at [SonicScan TX]({sonicscan_tx_url}{tx_hash})."
            )

    if messages:
        print(f"🚀 Found {len(messages)} large deposits in the last {hours} hours.")
        return True, "\n\n".join(messages)
    else:
        print(f"✅ No large deposits (≥ {FLAG_THRESHOLD:,.0f} S tokens) found in the last {hours} hours.")
        return False, f"✅ No large deposits (≥ {FLAG_THRESHOLD:,.0f} S tokens) were found in the last {hours} hours."

def fetch_all_deposits_custom(hours):
    """
    Fetches ALL deposits to the staking contract within the specified number of hours.
    Returns a list of deposit dictionaries, each containing:
      - 'tx_hash'
      - 'sender'
      - 'amount'  (float)
    """
    BLOCK_CHUNK_SIZE = 25_000
    MIN_BLOCK_CHUNK = 3_125
    RETRY_LIMIT = 2

    # 1) Convert hours to a Unix timestamp
    window_seconds = int(hours * 3600)
    start_time = int(time.time()) - window_seconds

    # 2) Convert start_time to a block number
    block_time_url = (
        f"{ETHERSCAN_V2}"
        f"&module=block"
        f"&action=getblocknobytime"
        f"&timestamp={start_time}"
        f"&closest=before"
        f"&apikey={API_KEY}"
    )
    block_response = make_request(block_time_url)
    if not block_response:
        print("🚨 Error: Could not fetch block time. Returning empty list.")
        return []

    start_block = int(block_response["result"])

    # 3) Get latest block
    latest_block_url = f"{ETHERSCAN_V2}&module=proxy&action=eth_blockNumber&apikey={API_KEY}"
    latest_block_response = make_request(latest_block_url)
    if not latest_block_response:
        print("🚨 Error: Could not fetch latest block number. Returning empty list.")
        return []

    latest_block = int(latest_block_response["result"], 16)

    # 4) Walk through blocks in chunks, collecting all deposit logs
    deposits = []
    current_start_block = start_block

    while current_start_block <= latest_block:
        current_end_block = min(current_start_block + BLOCK_CHUNK_SIZE, latest_block)
        retries = 0

        while retries < RETRY_LIMIT:
            print(f"🔄 Querying blocks {current_start_block} to {current_end_block}")
            tx_url = (
                f"{ETHERSCAN_V2}&module=logs&action=getLogs"
                f"&fromBlock={current_start_block}"
                f"&toBlock={current_end_block}"
                f"&address={CONTRACT_ADDRESS}"
                f"&topic0={DEPOSIT_EVENT_TOPIC}"
                f"&apikey={API_KEY}"
            )

            tx_response = make_request(tx_url)
            if tx_response and "result" in tx_response:
                these_logs = tx_response["result"]
                print(f"✅ Retrieved {len(these_logs)} deposit logs from blocks {current_start_block} to {current_end_block}.")
                deposits.extend(these_logs)
                break
            else:
                retries += 1
                print(f"⚠️ Attempt {retries} failed for blocks {current_start_block} to {current_end_block}. Retrying...")
                time.sleep(10 * retries)

                # If we exhaust retries, reduce chunk size if possible
                if retries == RETRY_LIMIT and BLOCK_CHUNK_SIZE > MIN_BLOCK_CHUNK:
                    BLOCK_CHUNK_SIZE = max(BLOCK_CHUNK_SIZE // 2, MIN_BLOCK_CHUNK)
                    print(f"⚠️ Reducing block chunk size to {BLOCK_CHUNK_SIZE} and retrying.")

        # **Fail condition** if chunk size is already minimal
        if retries == RETRY_LIMIT and BLOCK_CHUNK_SIZE == MIN_BLOCK_CHUNK:
            print("🚨 ERROR: All retries failed at minimal chunk size. Returning partial results we have so far.")
            break

        current_start_block = current_end_block + 1

    # 5) Convert logs to a more convenient structure: (tx_hash, sender, amount)
    deposit_list = []
    for deposit in deposits:
        tx_hash = deposit.get('transactionHash', 'N/A')
        # sender is in topics[1]
        sender_topic = deposit["topics"][1]  # raw
        sender_address = f"0x{sender_topic[-40:]}"
        
        # amount is in the first 32 bytes of data
        raw_amount_assets = deposit.get("data", "0x0")[:66]  # Just the first 32 bytes
        deposit_amount_wei = w3.to_int(hexstr=raw_amount_assets)
        deposit_amount = deposit_amount_wei / DECIMALS

        deposit_list.append({
            "tx_hash": tx_hash,
            "sender": sender_address,
            "amount": deposit_amount
        })

    return deposit_list

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