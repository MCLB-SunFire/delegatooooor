import discord
from discord.ext import commands, tasks
from fetch_transactions import fetch_recent_transactions, filter_and_sort_pending_transactions
from staking_contract import get_staking_balance
from decode_hex import decode_hex_data, get_function_name
from execute_transaction import fetch_transaction_by_nonce, execute_transaction
from report_builder import compose_full_report
from deposit_monitor import run_deposit_probe, split_long_message
import os
from dotenv import load_dotenv
import asyncio
from datetime import datetime, timezone  # if not already imported

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

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
    try:
        await ctx.send("📢 Fetching transaction data...")
        print("📢 Fetching transaction data with REPORT command...")

        # Run deposit check (do not persist pings here)
        alert_triggered, deposit_report_message, _, _ = await run_deposit_probe()

        if alert_triggered:
            paused = True

            # Fetch staking contract balance
            staking_balance = await asyncio.to_thread(get_staking_balance)
            staking_balance = round(staking_balance, 1) if staking_balance else 0.0

            # Fetch pending transactions
            transactions = await asyncio.to_thread(fetch_recent_transactions)
            if not transactions:
                await ctx.send(deposit_report_message + "\n\n📌 No pending transactions found.")
                return

            # Build the consolidated report (no signer pings in !report)
            report = compose_full_report(
                transactions=transactions,
                staking_balance=staking_balance,
                decode_hex_data=decode_hex_data,
                get_function_name=get_function_name,
                filter_and_sort_pending_transactions=filter_and_sort_pending_transactions,
                ping_missing_signers=False,
            )

            # Append deposit results
            report += f"\n{deposit_report_message}"

            # Append pause state message only if paused
            if paused:
                report += "\n\n⏸️ **Note:** Automated transaction execution is currently paused. Rechecks and reports will continue."

            # Send in chunks
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
    try:
        alert_triggered, deposit_message, _, _ = await run_deposit_probe()

        if alert_triggered:
            for chunk in split_long_message(deposit_message):
                await broadcast_message(chunk)
            if not paused:
                paused = True
                print("Deposit monitor triggered a pause due to a large deposit.")
            else:
                print("Deposit monitor detected large deposit while already paused.")
            return

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

        # Build the consolidated report via shared helper (with signer pings ON for the daily/periodic path)
        full_report = compose_full_report(
            transactions=transactions,
            staking_balance=staking_balance,
            decode_hex_data=decode_hex_data,
            get_function_name=get_function_name,
            filter_and_sort_pending_transactions=filter_and_sort_pending_transactions,
            ping_missing_signers=True,  # ping signers in periodic/daily report
        )

        # Preserve your "Periodic Recheck Report" header
        full_report = "### Periodic Recheck Report ###\n\n" + full_report

        # Preserve your "no pending transactions" note behavior
        if not pending_transactions:
            full_report += no_tx_message

        # Preserve your Safe queue link at the end
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

        if (now_utc >= target_today) and (LAST_DAILY_REPORT_DATE != today):
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

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)