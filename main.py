import discord
from discord.ext import commands, tasks
from fetch_transactions import fetch_recent_transactions, filter_and_sort_pending_transactions
from staking_contract import get_staking_balance
from decode_hex import decode_hex_data, get_function_name
from execute_transaction import fetch_transaction_by_nonce, execute_transaction  # Execution logic
import os
from dotenv import load_dotenv
import asyncio
import json
from datetime import datetime, timezone  # if not already imported

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
PERSISTENCE_FILE = "/data/last_scanned_block.json"  # /data is the mounted volume

# Initialize the Discord bot
intents = discord.Intents.default()
intents.guilds = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)  # Disables default help

# Hardcoded Guild ID, channel ID. # Add duplicate identical lines underneith for addiotnal guilds and channels.
designated_channels = {
    1056610911009386666: 1329968235004694619,
    885764705526882335: 911280330567208971,  
}

# Daily report anchor (UTC)
DAILY_REPORT_UTC_HOUR = 9
LAST_DAILY_REPORT_DATE = None

# Pause flag
paused = True

SONICSCAN_TX_URL = "https://sonicscan.org/tx/"

def load_last_scanned_block():
    """
    Loads the last scanned block number from the persistent JSON file.
    Returns the block number as an integer, or None if not found.
    """
    try:
        with open(PERSISTENCE_FILE, "r") as f:
            data = json.load(f)
            return data.get("last_scanned_block", None)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def save_last_scanned_block(block_number):
    """
    Saves the given block number to the persistent JSON file.
    """
    with open(PERSISTENCE_FILE, "w") as f:
        json.dump({"last_scanned_block": block_number}, f)

@bot.event
async def on_ready():
    print(f"Discord bot connected as {bot.user}")
    print("Bot is running and ready to accept commands!")
    # Start the periodic task when the bot is ready
    periodic_recheck.start()

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Check if the message is in the designated channel for the guild
    guild_id = message.guild.id
    if guild_id in designated_channels:
        if message.channel.id != designated_channels[guild_id]:
            return  # Ignore messages from non-designated channels

    await bot.process_commands(message)

@bot.command(name="help")
async def custom_help(ctx):
    """Custom Help Command with Thumbnail and Embed Image"""
    embed = discord.Embed(
        title="📜 \u2003**Command List**\u2003 📜",
        description="\u200b",  # smaller gap instead of a full empty field
        color=0xcc1d1b  # embed border color
    )

    # Set the thumbnail (Bot Avatar or Custom URL)
    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1333959203638874203/1334038056927494184/better_vizard_fire.png?ex=679b1342&is=6799c1c2&hm=9df98ede7f3eaff3df9b1f79cc737814cb79c88314bb7cc61c48d9ea86592f5e&")  # Change to your image URL

    # Add categorized commands in the specified order
    embed.add_field(name="📢 \u2003!report", value="Fetch and send a transaction report.", inline=False)
    embed.add_field(name="⏸️ \u2003!pause", value="Pause automated transaction execution.", inline=False)
    embed.add_field(name="▶️ \u2003!resume", value="Resume automated transaction execution.", inline=False)
    embed.add_field(name="⚔️ \u2003!execute", value="Execute lowest nonce. Respects pause state, token balance and payload data.", inline=False)
    embed.add_field(name="⚡ \u2003!shikai", value="Execute lowest nonce, ignores pause state.", inline=False)
    embed.add_field(name="🔥 \u2003!bankai", value="Execute lowest nonce, ignores pause state and token balance.", inline=False)
    embed.add_field(name="💀 \u2003!shukai9000", value="Ultimate execution weapon. ignores ALL checks (pause, balance, data).", inline=False)
    embed.add_field(name="🕒 \u2003!history", value="Scan large deposits for a past-hours window (no alerts triggered).", inline=False)
    embed.add_field(name="📄 \u2003!deposits", value="Export ALL deposits in a past-hours window to CSV.", inline=False)

    # Set the embed image
    embed.set_image(url="https://cdn.discordapp.com/attachments/1333959203638874203/1333963513177178204/beets_bleach.png?ex=679acdd5&is=67997c55&hm=eefc8ec5228ca7f64f2040ee8b112e99aaee90682def455f03018e1e5afd9125&")  # Change to your image URL

    # Send the embed
    await ctx.send(embed=embed)

@bot.command(name="pause")
async def pause(ctx):
    """Pause automated transaction execution."""
    global paused
    paused = True
    await ctx.send("⏸️ Automated transaction execution has been paused. Rechecks and reports will continue.")
    print("Transaction execution paused.")

@bot.command(name="resume")
async def resume(ctx):
    """Resume automated transaction execution."""
    global paused
    paused = False
    await ctx.send("▶️ Automated transaction execution has been resumed.")
    print("Transaction execution resumed.")

@bot.command(name="report")
async def report(ctx):
    """Fetch and send a transaction report."""
    await ctx.send("📢 Fetching transaction data...")
    print("📢 Fetching transaction data with REPORT command...")

    from deposit_monitor import check_large_deposits_with_block, FLAG_THRESHOLD, split_long_message

    try:
        # 1) Read the old block from JSON
        old_persisted_block = load_last_scanned_block()

        if old_persisted_block is None:
            print("No persisted last_scanned_block found. Using full 65-minute lookback.")
            start_block = None
        else:
            start_block = old_persisted_block + 1

        # Run deposit monitor from the appropriate block range
        alert_triggered, deposit_message, new_last_block = check_large_deposits_with_block(start_block)

        # If we get a new block from deposit_monitor:
        if new_last_block is not None:
            if old_persisted_block is not None:
                print(f"✅ Updating last scanned block from {old_persisted_block} to {new_last_block}")
            else:
                print(f"✅ Setting last_scanned_block for the first time: {new_last_block}")

            # Save the new block to JSON
            save_last_scanned_block(new_last_block)
        else:
            print("⚠️ Warning: new_last_block returned as None. Retrying from previous block next loop.")

        if alert_triggered:
            global paused
            paused = True
            deposit_report_message = deposit_message
        else:
            deposit_report_message = f"✅ No deposits over {FLAG_THRESHOLD:,.0f} S tokens were found between blocks {start_block} and {new_last_block}."

        # Fetch staking contract balance
        staking_balance = await asyncio.to_thread(get_staking_balance)
        staking_balance = round(staking_balance, 1) if staking_balance else 0.0

        # Fetch pending transactions
        transactions = await asyncio.to_thread(fetch_recent_transactions)
        if not transactions:
            await ctx.send(deposit_report_message + "\n\n📌 No pending transactions found.")
            return

        # Format the report
        report = format_transaction_report({
            "staking_balance": staking_balance,
            "pending_transactions": [
                {
                    "nonce": tx["nonce"],
                    "func": get_function_name(tx["data"]) if tx.get("data") else "No Data",
                    "validator_id": decode_hex_data(tx["data"])["validatorId"] if tx.get("data") else "No Data",
                    "amount": float(decode_hex_data(tx["data"])["amountInTokens"]) if tx.get("data") else "No Data",
                    "status": (
                        "Signatures Needed"
                        if tx['signature_count'] < tx['confirmations_required']
                        else (
                            "Ready to Execute"
                            if staking_balance >= float(decode_hex_data(tx["data"])["amountInTokens"]) else "Insufficient Balance"
                        )
                    ) if tx.get("data") else "No Data",
                    "signature_count": tx.get("signature_count", 0),
                    "confirmations_required": tx.get("confirmations_required", 0)
                }
                for tx in filter_and_sort_pending_transactions(transactions)
            ]
        })

        # Ensure deposit report results are included in the final report
        report += f"\n{deposit_report_message}"

        # Append pause state message **only if paused**
        if paused:
            report += "\n\n⏸️ **Note:** Automated transaction execution is currently paused. Rechecks and reports will continue."
        for part in split_long_message(report):
            await ctx.send(part)
    except Exception as e:
        await ctx.send(f"❌ An error occurred while generating the report: {e}")
        print(f"Error: {e}")

@bot.command(name="history")
async def historical_report(ctx, hours: float):
    """
    Fetch historical large deposit reports (≥ FLAG_THRESHOLD) for the past specified number of hours.
    This command does NOT trigger alerts or pause automation.
    Usage: !history 24
    """
    if hours <= 0:
        await ctx.send("❌ Invalid time range. Please enter a positive number of hours.")
        return

    await ctx.send(f"🔍 Scanning for large deposits in the last **{hours} hours**...")

    # Run scan in a separate asyncio task so the bot stays responsive
    bot.loop.create_task(run_historical_scan(ctx, hours))

async def run_historical_scan(ctx, hours):
    """Runs the historical scan asynchronously without blocking Discord."""
    try:
        from deposit_monitor import check_large_deposits_custom, split_long_message
        _, message = await asyncio.to_thread(check_large_deposits_custom, hours)  # Run in separate thread

        for part in split_long_message(message):
            await ctx.send(part)

    except Exception as e:
        await ctx.send(f"❌ Error during historical scan: {e}")

@bot.command(name="deposits")
async def export_all_deposits_csv(ctx, hours: float):
    """
    Fetches ALL deposits to the staking contract in the last `hours` hours,
    writes them to a CSV (TxHash, Address, Amount, RunningTotal),
    and sends that CSV as an attachment in Discord.
    Usage: !deposits 24
    """
    # 1) Validate user input
    if hours <= 0:
        await ctx.send("❌ Invalid time range. Please enter a positive number of hours.")
        return

    # 2) Acknowledge in Discord
    await ctx.send(f"🔍 Fetching ALL deposits for the last {hours} hours...")

    # 3) Fetch deposits (this may take a while if hours is large, so run in a thread)
    from deposit_monitor import fetch_all_deposits_custom
    try:
        deposit_list = await asyncio.to_thread(fetch_all_deposits_custom, hours)
    except Exception as e:
        await ctx.send(f"❌ Error retrieving deposits: {e}")
        return

    # 4) If no deposits found, let the user know
    if not deposit_list:
        await ctx.send(f"✅ No deposits found in the past {hours} hours.")
        return

    # 5) Build the CSV file in-memory or in a temp file
    import csv
    import tempfile

    # We'll keep a running total
    running_total = 0.0

    # Create a temporary file
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as tmpfile:
        csv_writer = csv.writer(tmpfile)
        # Write the header
        csv_writer.writerow(["Tx Hash", "Depositor Address", "Deposit Amount", "Running Total"])

        # Iterate over each deposit, compute running total
        for deposit in deposit_list:
            tx_hash = deposit["tx_hash"]
            sender = deposit["sender"]
            amount = deposit["amount"]
            # Update running total
            running_total += amount

            # Round both the deposit amount and the running total to 1 decimal place
            csv_writer.writerow([
                tx_hash,
                sender,
                f"{amount:,.1f}",
                f"{running_total:,.1f}"
            ])

        temp_csv_filename = tmpfile.name  # We'll send this file in Discord

    # 6) Send the CSV as an attachment
    try:
        await ctx.send(
            content=f"✅ Found {len(deposit_list)} deposits in the past {hours} hours totaling {running_total:,.1f} S tokens. Here is the CSV file:",
            file=discord.File(temp_csv_filename, filename="all_deposits.csv")
        )
    finally:
        # 7) Clean up the temp file from the filesystem
        import os
        if os.path.exists(temp_csv_filename):
            os.remove(temp_csv_filename)

@bot.command(name="execute")
async def execute(ctx):
    """Execute lowest nonce. Respects pause state AND token balance."""
    if paused:
        await ctx.send("⏸️ The bot is currently paused. Transaction execution is disabled.")
        print("Execution attempt blocked due to pause state.")
        return

    await ctx.send("⚔️ Checking for executable transactions...")

    # Fetch staking contract balance
    staking_balance = get_staking_balance()
    staking_balance = round(staking_balance, 1) if staking_balance else 0.0

    # Fetch pending transactions
    transactions = fetch_recent_transactions()
    pending_transactions = filter_and_sort_pending_transactions(transactions)

    if not pending_transactions:
        await ctx.send("❌ No pending transactions found.")
        print("No pending transactions found.")
        return

    # Get the lowest nonce transaction
    lowest_transaction = pending_transactions[0]
    nonce = lowest_transaction["nonce"]
    signature_count = lowest_transaction["signature_count"]
    confirmations_required = lowest_transaction["confirmations_required"]
    hex_data = lowest_transaction.get("data", b"")
    decoded = decode_hex_data(hex_data) if hex_data else {}

    if not decoded:
        await ctx.send(f"❌ Failed to decode transaction data for nonce {nonce}.")
        print(f"Failed to decode transaction data for nonce {nonce}.")
        return

    # Extract required amount from the decoded payload
    amount = float(decoded["amountInTokens"])

    # Check if the transaction has enough signatures
    if signature_count < confirmations_required:
        await ctx.send(
            f"❌ Transaction with nonce {nonce} cannot be executed due to insufficient signatures.\n"
            f"- **Signatures**: {signature_count}/{confirmations_required}"
        )
        print(
            f"Transaction with nonce {nonce} cannot be executed due to insufficient signatures.\n"
            f"- Signatures: {signature_count}/{confirmations_required}"
        )
        return

    # Check if the staking contract has enough tokens
    if staking_balance < amount:
        await ctx.send(
            f"❌ Insufficient staking contract balance to execute the transaction.\n"
            f"- **Nonce**: {nonce}\n"
            f"- **Signatures**: {signature_count}/{confirmations_required}\n"
            f"- **Required**: {amount:,.1f} S tokens\n"
            f"- **Available**: {staking_balance:,.1f} S tokens"
        )
        print(
            f"Transaction with nonce {nonce} cannot be executed due to insufficient staking contract balance.\n"
            f"- Signatures: {signature_count}/{confirmations_required}\n"
            f"- Required: {amount:,.1f} S tokens\n"
            f"- Available: {staking_balance:,.1f} S tokens"
        )
        return

    # Fetch the transaction details by nonce
    transaction = fetch_transaction_by_nonce(nonce)
    if not transaction:
        await ctx.send(f"❌ No transaction found for nonce {nonce}.")
        print(f"No transaction found for nonce {nonce}.")
        return

    # Execute the transaction and check for receipt boolean
    transaction["_wait_for_receipt"] = True
    res = execute_transaction(transaction)

    if isinstance(res, dict) and res.get("ok"):
        txh = res["tx_hash"]
        await ctx.send(
            f"✅ Transaction {nonce} executed successfully!\n"
            f"- **Validator ID**: {decoded['validatorId']}\n"
            f"- **Amount**: {amount:,.1f} S tokens\n"
            f"- **Transaction Hash**: [View on SonicScan]({SONICSCAN_TX_URL}{txh})\u200B"
        )
        print(
            f"Transaction {nonce} executed successfully.\n"
            f"- Validator ID: {decoded['validatorId']}\n"            
            f"- Amount: {amount:,.1f} S tokens\n"
            f"- Transaction Hash: {txh}"
        )
    else:
        await ctx.send(f"❌ Transaction {nonce} could not be executed.")
        print(f"Transaction {nonce} could not be executed.\n")

@bot.command(name="shikai")
async def force_execute(ctx):
    """Execute lowest nonce, ignores pause state."""
    await ctx.send("⚡ Overriding pause state, executing the lowest nonce transaction...")

    # Fetch staking contract balance
    staking_balance = get_staking_balance()
    staking_balance = round(staking_balance, 1) if staking_balance else 0.0

    # Fetch pending transactions
    transactions = fetch_recent_transactions()
    pending_transactions = filter_and_sort_pending_transactions(transactions)

    if not pending_transactions:
        await ctx.send("❌ No pending transactions found.")
        print("No pending transactions found.")
        return

    # Get the lowest nonce transaction
    lowest_transaction = pending_transactions[0]
    nonce = lowest_transaction["nonce"]
    signature_count = lowest_transaction["signature_count"]
    confirmations_required = lowest_transaction["confirmations_required"]
    hex_data = lowest_transaction.get("data", b"")
    decoded = decode_hex_data(hex_data) if hex_data else {}

    if not decoded:
        await ctx.send(f"❌ Failed to decode transaction data for nonce {nonce}.")
        print(f"Failed to decode transaction data for nonce {nonce}.")
        return

    # Extract required amount from the decoded payload
    amount = float(decoded["amountInTokens"])

    # Check if the transaction has enough signatures
    if signature_count < confirmations_required:
        await ctx.send(
            f"❌ Transaction with nonce {nonce} cannot be executed due to insufficient signatures.\n"
            f"- **Signatures**: {signature_count}/{confirmations_required}"
        )
        print(
            f"Transaction with nonce {nonce} cannot be executed due to insufficient signatures.\n"
            f"- Signatures: {signature_count}/{confirmations_required}"
        )
        return

    # Check if the staking contract has enough tokens
    if staking_balance < amount:
        await ctx.send(
            f"❌ Insufficient staking contract balance to execute the transaction.\n"
            f"- **Nonce**: {nonce}\n"
            f"- **Signatures**: {signature_count}/{confirmations_required}\n"
            f"- **Required**: {amount:,.1f} S tokens\n"
            f"- **Available**: {staking_balance:,.1f} S tokens"
        )
        print(
            f"Transaction with nonce {nonce} cannot be executed due to insufficient staking contract balance.\n"
            f"- Signatures: {signature_count}/{confirmations_required}\n"
            f"- Required: {amount:,.1f} S tokens\n"
            f"- Available: {staking_balance:,.1f} S tokens"
        )
        return

    # Fetch the transaction details by nonce
    transaction = fetch_transaction_by_nonce(nonce)
    if not transaction:
        await ctx.send(f"❌ No transaction found for nonce {nonce}.")
        print(f"No transaction found for nonce {nonce}.")
        return

    # Execute the transaction
    transaction["_wait_for_receipt"] = True
    res = execute_transaction(transaction)

    if isinstance(res, dict) and res.get("ok"):
        txh = res["tx_hash"]
        await ctx.send(
            f"✅ Transaction {nonce} executed successfully!\n"
            f"- **Validator ID**: {decoded['validatorId']}\n"
            f"- **Amount**: {amount:,.1f} S tokens\n"
            f"- **Transaction Hash**: [View on SonicScan]({SONICSCAN_TX_URL}{txh})\u200B"
        )
        print(
            f"Transaction {nonce} executed successfully.\n"
            f"- Validator ID: {decoded['validatorId']}\n"            
            f"- Amount: {amount:,.1f} S tokens\n"
            f"- Transaction Hash: {txh}"
        )
    else:
        await ctx.send(f"❌ Transaction {nonce} could not be executed.")
        print(f"Transaction {nonce} could not be executed.\n")

@bot.command(name="bankai")
async def force_execute_no_checks(ctx):
    """Execute lowest nonce, ignores pause state AND token balance."""
    await ctx.send("🔥 Overriding pause state AND token balance, executing the lowest nonce transaction...")

    # Fetch staking contract balance
    staking_balance = get_staking_balance()
    staking_balance = round(staking_balance, 1) if staking_balance else 0.0

    # Fetch pending transactions
    transactions = fetch_recent_transactions()
    pending_transactions = filter_and_sort_pending_transactions(transactions)

    if not pending_transactions:
        await ctx.send("❌ No pending transactions found.")
        print("No pending transactions found.")
        return

    # Get the lowest nonce transaction
    lowest_transaction = pending_transactions[0]
    nonce = lowest_transaction["nonce"]
    signature_count = lowest_transaction["signature_count"]
    confirmations_required = lowest_transaction["confirmations_required"]
    hex_data = lowest_transaction.get("data", b"")
    decoded = decode_hex_data(hex_data) if hex_data else {}

    if not decoded:
        await ctx.send(f"❌ Failed to decode transaction data for nonce {nonce}.")
        print(f"Failed to decode transaction data for nonce {nonce}.")
        return

    # Extract required amount from the decoded payload
    amount = float(decoded["amountInTokens"])  # This is the "Amount Queued"

    # Check if the transaction has enough signatures
    if signature_count < confirmations_required:
        await ctx.send(
            f"❌ Transaction with nonce {nonce} cannot be executed due to insufficient signatures.\n"
            f"- **Signatures**: {signature_count}/{confirmations_required}"
        )
        print(
            f"Transaction with nonce {nonce} cannot be executed due to insufficient signatures.\n"
            f"- Signatures: {signature_count}/{confirmations_required}"
        )
        return

    # Fetch the transaction details by nonce
    transaction = fetch_transaction_by_nonce(nonce)
    if not transaction:
        await ctx.send(f"❌ No transaction found for nonce {nonce}.")
        print(f"No transaction found for nonce {nonce}.")
        return

    # Execute the transaction and wait for receipt boolean
    transaction["_wait_for_receipt"] = True
    res = execute_transaction(transaction)

    if isinstance(res, dict) and res.get("ok"):
        txh = res["tx_hash"]
        await ctx.send(
            f"✅ Transaction {nonce} executed successfully!\n"
            f"- **Validator ID**: {decoded['validatorId']}\n"
            f"- **Amount**: {amount:,.1f} S tokens\n"
            f"- **Transaction Hash**: [View on SonicScan]({SONICSCAN_TX_URL}{txh})\u200B"
        )
        print(
            f"Transaction {nonce} executed successfully.\n"
            f"- Validator ID: {decoded['validatorId']}\n"           
            f"- Amount Queued: {amount:,.1f} S tokens\n"  # Add Amount Queued
            f"- Amount Staked: {staking_balance:,.1f} S tokens\n"  # Add Amount Staked
            f"- Transaction Hash: {txh}"
        )
    else:
        await ctx.send(f"❌ Transaction {nonce} could not be executed.")
        print(f"Transaction {nonce} could not be executed.\n")

@bot.command(name="shukai9000")
async def ultimate_force_execute(ctx):
    """Ultimate command to execute the lowest nonce, ignoring all checks except signature count."""
    await ctx.send("💀 Unleashing ultimate power! Executing the lowest nonce transaction...")

    # Fetch staking contract balance
    staking_balance = get_staking_balance()
    staking_balance = round(staking_balance, 1) if staking_balance else 0.0

    # Fetch pending transactions
    transactions = fetch_recent_transactions()
    pending_transactions = filter_and_sort_pending_transactions(transactions)

    if not pending_transactions:
        await ctx.send("❌ No pending transactions found.")
        print("No pending transactions found.")
        return

    # Get the lowest nonce transaction
    lowest_transaction = pending_transactions[0]
    nonce = lowest_transaction["nonce"]
    signature_count = lowest_transaction["signature_count"]
    confirmations_required = lowest_transaction["confirmations_required"]
    # Ensure hex_data is always bytes, never None
    hex_data = lowest_transaction.get("data")
    if hex_data is None:
        hex_data = b""  # Ensure `data` is always bytes, never `None`
    elif isinstance(hex_data, str):  # If it's a hex string, convert it
        hex_data = bytes.fromhex(hex_data.lstrip("0x"))

    # Attempt to decode; proceed regardless of success
    decoded = decode_hex_data(hex_data) if hex_data else {}
    if not isinstance(decoded, dict):
        decoded = {}  # Force empty dict if decoding fails

    # Check if the transaction has enough signatures
    if signature_count < confirmations_required:
        await ctx.send(
            f"❌ Transaction with nonce {nonce} cannot be executed due to insufficient signatures.\n"
            f"- **Signatures**: {signature_count}/{confirmations_required}"
        )
        print(
            f"Transaction with nonce {nonce} cannot be executed due to insufficient signatures.\n"
            f"- Signatures: {signature_count}/{confirmations_required}"
        )
        return

    # Fetch the actual transaction details by nonce
    transaction = fetch_transaction_by_nonce(nonce)
    if not transaction:
        await ctx.send(f"❌ No transaction found for nonce {nonce}.")
        print(f"No transaction found for nonce {nonce}.")
        return

    # Execute the transaction regardless of data decode status
    transaction["_wait_for_receipt"] = True
    res = execute_transaction(transaction)

    if isinstance(res, dict) and res.get("ok"):
        result = res["tx_hash"]  # keep your existing message formatting below

        # Provide detailed information if decoded
        if decoded:
            amount = float(decoded.get("amountInTokens", 0.0))
            validator_id = decoded.get("validatorId", "N/A")
            await ctx.send(
                f"✅ Transaction {nonce} executed successfully!\n"
                f"- **Validator ID**: {validator_id}\n"                
                f"- **Amount**: {amount:,.1f} S tokens\n"
                f"- **Transaction Hash**: [View on SonicScan]({SONICSCAN_TX_URL}{result})\u200B"
            )
            print(
                f"Transaction {nonce} executed successfully.\n"
                f"- Validator ID: {validator_id}\n"               
                f"- Amount: {amount:,.1f} S tokens\n"
                f"- Transaction Hash: {result}"
            )
        else:
            await ctx.send(
                f"✅ Transaction {nonce} executed successfully!\n"
                f"- **No decodeable data**\n"               
                f"- **Transaction Hash**: [View on SonicScan]({SONICSCAN_TX_URL}{result})\u200B"
            )
            print(
                f"Transaction {nonce} executed successfully.\n"
                f"- No decodeable data\n"               
                f"- Transaction Hash: {result}"
            )
    else:
        await ctx.send(f"❌ Transaction {nonce} could not be executed.")
        print(f"Transaction {nonce} could not be executed.\n")

@tasks.loop(hours=1)
async def periodic_recheck():
    print("Performing periodic recheck...")
    global paused, LAST_DAILY_REPORT_DATE

    from deposit_monitor import check_large_deposits_with_block, split_long_message
    import asyncio

    try:
        # 1) Read the old block from JSON
        old_persisted_block = load_last_scanned_block()

        if old_persisted_block is None:
            print("No persisted last_scanned_block found. Using full 65-minute lookback.")
            start_block = None
        else:
            start_block = old_persisted_block + 1

        # Run deposit monitor from the appropriate block range inside a seperate thread to avoid bricking discord heart beat.
        alert_triggered, deposit_message, new_last_block = \
            await asyncio.to_thread(check_large_deposits_with_block, start_block)

        # If we get a new block from deposit_monitor:
        if new_last_block is not None:
            if old_persisted_block is not None:
                print(f"✅ Updating last scanned block from {old_persisted_block} to {new_last_block}")
            else:
                print(f"✅ Setting last_scanned_block for the first time: {new_last_block}")

            # Save the new block to JSON
            save_last_scanned_block(new_last_block)
        else:
            print("⚠️ Warning: new_last_block returned as None. Retrying from previous block next loop.")

        # 4) Failsafe: re-check that we actually have a persisted value
        check_block = load_last_scanned_block()
        if check_block is None:
            print("🚨 Critical: last_scanned_block is STILL None! Will revert to full 65-minute lookback next loop.")

        # Handle deposit alerts and pause logic
        if alert_triggered:
            for chunk in split_long_message(deposit_message):
                await broadcast_message(chunk)
            if not paused:  # Only pause if not already paused
                paused = True                
                print("Deposit monitor triggered a pause due to a large deposit.")
            else:
                print("Deposit monitor detected large deposit while already paused.")
            return  # Exit early if a large deposit was found

        # Fetch staking contract balance
        staking_balance = await asyncio.to_thread(get_staking_balance)
        staking_balance = round(staking_balance, 1) if staking_balance else 0.0
        print(f"Staking Contract Balance: {staking_balance} S tokens")

        # Fetch pending transactions
        transactions = await asyncio.to_thread(fetch_recent_transactions)
        pending_transactions = filter_and_sort_pending_transactions(transactions)
        if transactions == []:
            await broadcast_message(
                "⚠️  Gnosis Safe API either shat the bed again or there are legitimately no pending transactions."
                "If the CEO of staking is on smoke break...again, then don't tell franz, you fucken snitch.")

        # Log pending transactions
        if not pending_transactions:
            print("No pending transactions found.")
            no_tx_message = "\n\n📋 **Note:** No pending transactions found during this recheck."

        else:
            print("Pending Transactions:")
            for tx in pending_transactions:
                nonce = tx["nonce"]

                # Ensure decode_hex_data never fails due to NoneType
                decoded = decode_hex_data(tx["data"]) if tx.get("data") else {}

                if not isinstance(decoded, dict):  
                    decoded = {}  # Force to empty dict if decoding fails

                # Extract amount and validator_id safely
                amount = float(decoded.get("amountInTokens", 0.0)) if "amountInTokens" in decoded else 0.0
                validator_id = decoded.get("validatorId", "N/A") if "validatorId" in decoded else "N/A"

                # Ensure status is always a string
                status = (
                    f"Signatures Needed {tx['signature_count']}/{tx['confirmations_required']}"
                    if tx['signature_count'] < tx['confirmations_required']
                    else (
                        "Ready to Execute"
                        if staking_balance >= amount else "Insufficient Balance"
                    )
                ) if decoded else "No Data"  # <-- Ensures status is never None

                print(
                    f"- Nonce: {nonce}, Status: {status}, Validator ID: {validator_id}, Amount: {amount} S tokens, "
                    f"Signatures: {tx.get('signature_count', 0)}/{tx.get('confirmations_required', 0)}"
                )

        # Calculate the total sum of tokens in pending transactions
        total_pending_tokens = sum(
            float((decode_hex_data(tx["data"]) or {}).get("amountInTokens", 0.0))
            for tx in pending_transactions if tx.get("data")
        )

        # Convert staking_balance to float if necessary and calculate total available tokens
        staking_balance = float(staking_balance)
        total_available_tokens = total_pending_tokens - staking_balance

        print(f"Staking Headroom (Pending Total - Staking Contract Balance): {total_available_tokens} S tokens")

        # Prepare the full report for all pending transactions
        full_report = format_transaction_report({
            "staking_balance": staking_balance,
            "pending_transactions": [
                {
                    "nonce": tx["nonce"],
                    "func": get_function_name(tx["data"]) if tx.get("data") else "No Data",
                    "validator_id": (decode_hex_data(tx["data"]) or {}).get("validatorId", "No Data"),
                    "amount": float((decode_hex_data(tx["data"]) or {}).get("amountInTokens", 0.0)),

                    "status": (
                        "Signatures Needed"
                        if tx['signature_count'] < tx['confirmations_required']
                        else (
                            "Ready to Execute"
                            if staking_balance >= float(decode_hex_data(tx["data"])["amountInTokens"])
                            else "Insufficient Balance"
                        )
                    ) if tx.get("data") else "No Data",
                    "signature_count": tx.get("signature_count", 0),  # Add signature count
                    "confirmations_required": tx.get("confirmations_required", 0)  # Add confirmations required
                }
                for tx in pending_transactions
            ]
        }, header="Periodic Recheck Report")

        # Append no_tx_message if there are no transactions
        if not pending_transactions:
            full_report += no_tx_message

        # Check if total available tokens are below 1 million and append to the report
        if total_available_tokens < 1_000_000:
            warning_message = (
                f"⚠️ **Warning:** The token staking headroom (total pending - staking contract balance) "
                f"has dropped below 1 million.\n"
                f"**Current Headroom:** {total_available_tokens} S tokens\n"
                f"<@771222144780206100>, <@538717564067381249> please queue up more transactions." # add more IDs linearly as needed.
            )
            full_report += f"\n\n{warning_message}"

        # Check if any transaction is missing signatures
        signer_discord_map = {
            "0x69503B52764138e906C883eD6ef4Cac939eb998C": 892276475045249064,
            "0x693f30c37D5a0Db9258C636E93Ccf011ACd8c90c": 232514597200855040,
            "0xB3B1B2d1C9745E98e93F21DC2e4D816DA8a2440c": 538717564067381249,
            "0xf05Ea14723d6501AfEeA3bcFF8c36e375f3a7129": 771222144780206100,
            "0xa01Bfd7F1Be1ccF81A02CF7D722c30bDCc029718": 258369063124860928,
        }
        missing_signatures = {}

        for tx in pending_transactions:
            if tx["signature_count"] < tx["confirmations_required"]:
                signed_addresses = {conf["owner"] for conf in tx["confirmations"]}
                for address, discord_id in signer_discord_map.items():
                    if address not in signed_addresses:
                        if discord_id not in missing_signatures:
                            missing_signatures[discord_id] = []
                        missing_signatures[discord_id].append(tx["nonce"])

        # Create a grouped warning message for all signers
        if missing_signatures:
            # Group all warnings into a single block
            signature_warning_lines = ["⚠️ **Warning:** The following transactions are missing signatures:"]
            for discord_id, nonces in missing_signatures.items():
                signature_warning_lines.append(
                    f"- <@{discord_id}>: Nonce: {', '.join(map(str, nonces))}"
                )

            # Add the grouped warnings to the full report
            full_report += "\n\n" + "\n".join(signature_warning_lines)
            full_report += "\n\n <https://app.safe.global/transactions/queue?safe=sonic:0x6840Bd91417373Af296cc263e312DfEBcAb494ae>"
    
    # Check if any transaction can be executed
        decoded = {}
        if pending_transactions:
            lowest_transaction = pending_transactions[0]
            nonce = lowest_transaction["nonce"]
            hex_data = lowest_transaction.get("data", b"")
            decoded = decode_hex_data(hex_data) if hex_data else {}
            signature_count = lowest_transaction["signature_count"]
            confirmations_required = lowest_transaction["confirmations_required"]

        # Add paused state message to the report
        if paused:
            print("Periodic recheck: Execution is paused.")
            full_report += "\n\n⏸️ **Note:** Automated transaction execution is currently paused. Rechecks and reports will continue."
        else:
            if decoded:
                while True:
                    if paused:  # Break the execution loop if pause is triggered during execution
                        print("Pause detected during execution. Stopping transaction execution.")
                        break
                    if signature_count < confirmations_required:
                        print(f"Skipping execution for nonce {nonce} because it only has {signature_count}/{confirmations_required} signatures.")
                        break  # Exit the while loop without executing
                    amount = float(decoded["amountInTokens"])
                    if staking_balance >= amount:
                        print(f"Transaction {nonce} is ready to execute. Executing now...")

                        # Execute with receipt gating and 3 attempts spaced 60s
                        transaction = fetch_transaction_by_nonce(nonce)
                        if transaction:
                            attempts = 0
                            succeeded = False
                            while attempts < 3 and not succeeded:
                                transaction["_wait_for_receipt"] = True
                                res = execute_transaction(transaction)
                                if isinstance(res, dict) and res.get("ok"):
                                    txh = res["tx_hash"]
                                    await broadcast_message(
                                        f"✅ Successfully executed transaction:\n"
                                        f"- **Nonce**: {nonce}\n"
                                        f"- **Validator ID**: {decoded['validatorId']}\n"
                                        f"- **Amount**: {amount:,.1f} S tokens\n"
                                        f"- **Transaction Hash**: [View on SonicScan]({SONICSCAN_TX_URL}{txh})\u200B"
                                    )
                                    print(
                                    f"Transaction {nonce} executed successfully.\n"
                                    f"- Validator ID: {decoded['validatorId']}\n"            
                                    f"- Amount: {amount} S tokens\n"
                                    f"- Transaction Hash: {txh}"
                                    )
                                    succeeded = True
                                    break
                                else:
                                    attempts += 1
                                    if attempts < 3:
                                        await broadcast_message(
                                            f"❌ Transaction reverted (attempt {attempts}/3) for nonce {nonce}. "
                                            f"Retrying in 60 seconds…"
                                        )
                                        for _ in range(60):
                                            if paused:  # respect pause during cooldown
                                                break
                                            await asyncio.sleep(1)

                            if not succeeded:
                                # After 3 failures, pause and ping same IDs as your >100k alert
                                paused = True
                                await broadcast_message(
                                    "🚨 **Transaction Reverted Alert** 🚨\n"
                                    "This transaction reverted 3 consecutive times and automation is now paused. "
                                    "<@538717564067381249>, <@771222144780206100> please investigate."
                                )
                                print("Three consecutive transaction reverts. Automation is paused.")
                        else:
                            print(f"Transaction {nonce} not found for execution.")
                            break
                    else:
                        print("Insufficient balance for the next transaction.")
                        break

        # Anchored daily report (once after 09:00 UTC)
        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()
        target_today = now_utc.replace(hour=DAILY_REPORT_UTC_HOUR, minute=0, second=0, microsecond=0)

        if (now_utc >= target_today) and (LAST_DAILY_REPORT_DATE != today) and (not paused):
            for part in split_long_message(full_report):
                await broadcast_message(part)
            LAST_DAILY_REPORT_DATE = today

    except Exception as e:
        print(f"Error during periodic recheck: {e}")
        await broadcast_message(f"Error during periodic recheck: {e}")

async def broadcast_message(message):
    """Broadcast a message to all servers the bot is in."""
    for guild in bot.guilds:
        if guild.id in designated_channels:
            channel_id = designated_channels[guild.id]
            channel = discord.utils.get(guild.text_channels, id=channel_id)
            if channel and channel.permissions_for(guild.me).send_messages:
                try:
                    await channel.send(message)
                except Exception as send_error:
                    print(f"Error sending message to channel {channel.name}: {send_error}")

def format_transaction_report(result, header=None):
    """Format the transaction report for Discord with color-coded statuses."""
    report_lines = []

    # Add a custom header if provided
    if header:
        report_lines.append(f"### {header} ###\n")

    # Add the standard report content
    report_lines += [
        f"## Staking Contract Balance: {result['staking_balance']:,.1f} S tokens\n",  # Bold and larger header
        "**Pending Transactions:**",
        "```diff",  # Use Markdown code block with 'diff' syntax
        f"{'+/-':<5} {'Nonce':<7} {'Val':<6} {'Amount':<13} {'Status':<24} {'Sig':<7} {'Function':<9}",
        f"{'-'*80}",  # Adjusted table separator length
    ]
    for tx in result['pending_transactions']:
        status_value = tx['status'] or "No Data"  # Ensure status is always a string

        # Determine the prefix based on status
        if status_value.startswith("Signatures Needed"):
            status_prefix = "-"  # Red highlight for missing signatures
        elif status_value == "Insufficient Balance":
            status_prefix = "-"  # Red highlight for insufficient balance
        elif status_value == "Ready to Execute":
            status_prefix = "+"  # Green highlight for ready to execute
        elif status_value == "No Data":
            status_prefix = "?"  # Neutral or gray highlight for missing data
        else:
            status_prefix = "-"  # Default red highlight for unknown status

        # Add the line to the report with Signatures column
        report_lines.append(
            f"{status_prefix:<5} {tx['nonce']:<7} {tx['validator_id']:<6} {tx['amount']:<13,.1f} {tx['status']:<24} {tx.get('signature_count', 0)}/{tx.get('confirmations_required', 0):<5} {tx.get('func','N/A'):<9}"
        )
    report_lines.append("```")  # Close the code block
    return "\n".join(report_lines)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)