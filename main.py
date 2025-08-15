import discord
import asyncio
import os
from helpers.fetch_transactions import fetch_recent_transactions, filter_and_sort_pending_transactions
from helpers.staking_contract import get_staking_balance
from helpers.decode_hex import decode_hex_data, get_function_name
from helpers.execute_transaction import fetch_transaction_by_nonce, execute_transaction
from helpers.report_builder import compose_full_report
from helpers.deposit_monitor import run_deposit_probe, split_long_message
from commands.boring import register_boring_commands
from commands.hot import register_hot_commands
from dotenv import load_dotenv
from datetime import datetime, timezone
from discord.ext import commands, tasks

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
def get_paused():
    return paused

def set_paused(v: bool):
    global paused
    paused = v

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

register_boring_commands(
    bot,
    run_deposit_probe=run_deposit_probe,
    split_long_message=split_long_message,
    compose_full_report=compose_full_report,
    get_staking_balance=get_staking_balance,
    fetch_recent_transactions=fetch_recent_transactions,
    decode_hex_data=decode_hex_data,
    get_function_name=get_function_name,
    filter_and_sort_pending_transactions=filter_and_sort_pending_transactions,
    get_paused=get_paused,
    set_paused=set_paused,
)

register_hot_commands(
    bot,
    get_paused=get_paused,
    SONICSCAN_TX_URL=SONICSCAN_TX_URL,
    get_staking_balance=get_staking_balance,
    fetch_recent_transactions=fetch_recent_transactions,
    filter_and_sort_pending_transactions=filter_and_sort_pending_transactions,
    decode_hex_data=decode_hex_data,
    fetch_transaction_by_nonce=fetch_transaction_by_nonce,
    execute_transaction=execute_transaction,
)

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

        # Preserve your Safe queue link at the end, only if atleast 1 sig is missing.
        if any(tx["signature_count"] < tx["confirmations_required"] for tx in pending_transactions):
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
                                # After 3 failures, pause and ping same IDs as >100k alert
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

        global LAST_DAILY_REPORT_DATE
        if LAST_DAILY_REPORT_DATE is None:
            # If started after today's 09:00 UTC, skip report until tomorrow.
            if now_utc >= target_today:
                LAST_DAILY_REPORT_DATE = today
        else:
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