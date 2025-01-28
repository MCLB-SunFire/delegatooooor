import discord
from discord.ext import commands, tasks
from fetch_transactions import fetch_recent_transactions, filter_and_sort_pending_transactions
from staking_contract import get_staking_balance
from decode_hex import decode_hex_data
from execute_transaction import fetch_transaction_by_nonce, execute_transaction  # Execution logic
import os
from dotenv import load_dotenv
import asyncio

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Initialize the Discord bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Hardcoded channel IDs for specific servers
designated_channels = {
    1056610911009386666: 1329968235004694619,
        # Replace with your server guild ID and channel ID. add duplicate identical lines underneith for addiotnal guilds and channels.
}

# Counter for periodic rechecks
recheck_counter = 0

# Pause flag
paused = True

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

@bot.command(name="pause")
async def pause(ctx):
    """Pause transaction execution."""
    global paused
    paused = True
    await ctx.send("⏸️ Transaction execution has been paused. Rechecks and reports will continue.")
    print("Transaction execution paused.")

@bot.command(name="resume")
async def resume(ctx):
    """Resume transaction execution."""
    global paused
    paused = False
    await ctx.send("▶️ Transaction execution has been resumed.")
    print("Transaction execution resumed.")

@bot.command(name="report")
async def report(ctx):
    """Fetch and send a transaction report when triggered by !report."""
    await ctx.send("Fetching transaction data...")
    try:
        # Fetch staking contract balance
        staking_balance = get_staking_balance()
        staking_balance = round(staking_balance, 1) if staking_balance else 0.0

        # Fetch pending transactions
        transactions = fetch_recent_transactions(limit=10)
        if not transactions:
            await ctx.send("No pending transactions found.")
            return

        # Format the report
        report = format_transaction_report({
            "staking_balance": staking_balance,
            "pending_transactions": [
                {
                    "nonce": tx["nonce"],
                    "validator_id": decode_hex_data(tx["data"])["validatorId"] if tx.get("data") else None,
                    "amount": float(decode_hex_data(tx["data"])["amountInTokens"]) if tx.get("data") else None,
                    "status": (
                        "Signatures Needed"
                        if tx['signature_count'] < tx['confirmations_required']
                        else (
                            "Ready to Execute"
                            if staking_balance >= float(decode_hex_data(tx["data"])["amountInTokens"]) else "Insufficient Balance"
                        )
                    ) if tx.get("data") else None,
                    "signature_count": tx.get("signature_count", 0),  # Add signature count
                    "confirmations_required": tx.get("confirmations_required", 0)  # Add confirmations required
                }
                for tx in filter_and_sort_pending_transactions(transactions)
            ]
        })
        await ctx.send(report)
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")
        print(f"Error: {e}")

@bot.command(name="execute")
async def execute(ctx):
    """Manually execute the lowest nonce transaction if possible."""
    global paused
    if paused:
        await ctx.send("⏸️ The bot is currently paused. Transaction execution is disabled.")
        print("Execution attempt blocked due to pause state.")
        return

    await ctx.send("Checking for executable transactions...")

    # Fetch staking contract balance
    staking_balance = get_staking_balance()
    staking_balance = round(staking_balance, 1) if staking_balance else 0.0

    # Fetch pending transactions
    transactions = fetch_recent_transactions(limit=10)
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
    hex_data = lowest_transaction.get("data", "")
    decoded = decode_hex_data(hex_data) if hex_data else None

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
            f"- **Required**: {amount} S tokens\n"
            f"- **Available**: {staking_balance} S tokens"
        )
        print(
            f"Transaction with nonce {nonce} cannot be executed due to insufficient staking contract balance.\n"
            f"- Signatures: {signature_count}/{confirmations_required}\n"
            f"- Required: {amount} S tokens\n"
            f"- Available: {staking_balance} S tokens"
        )
        return

    # Fetch the transaction details by nonce
    transaction = fetch_transaction_by_nonce(nonce)
    if not transaction:
        await ctx.send(f"❌ No transaction found for nonce {nonce}.")
        print(f"No transaction found for nonce {nonce}.")
        return

    # Execute the transaction
    result = execute_transaction(transaction)
    if result:
        await ctx.send(
            f"✅ Transaction {nonce} executed successfully!\n"
            f"- **Validator ID**: {decoded['validatorId']}\n"
            f"- **Signatures**: {signature_count}/{confirmations_required}\n"
            f"- **Amount**: {amount} S tokens\n"
            f"- **Transaction Hash**: {result}"
        )
        print(
            f"Transaction {nonce} executed successfully.\n"
            f"- Validator ID: {decoded['validatorId']}\n"
            f"- Signatures: {signature_count}/{confirmations_required}\n"
            f"- Amount: {amount} S tokens\n"
            f"- Transaction Hash: {result}"
        )
    else:
        await ctx.send(f"❌ Transaction {nonce} could not be executed.")
        print(
            f"Transaction {nonce} could not be executed.\n"            
        )

@tasks.loop(hours=1)
async def periodic_recheck():
    """Periodic task to recheck transaction data and send a report every 6 hours."""
    global recheck_counter
    try:
        print("Performing periodic recheck...")

        # Initialize the full report
        full_report = ""

        # Fetch staking contract balance
        staking_balance = get_staking_balance()
        staking_balance = round(staking_balance, 1) if staking_balance else 0.0
        print(f"Staking Contract Balance: {staking_balance} S tokens")

        # Fetch pending transactions
        transactions = fetch_recent_transactions(limit=10)
        pending_transactions = filter_and_sort_pending_transactions(transactions)

        # Log pending transactions
        if not pending_transactions:
            print("No pending transactions found.")
            full_report += "\n\n⏸️ **Note:** No pending transactions found during this recheck."
        else:
            print("Pending Transactions:")
            for tx in pending_transactions:
                nonce = tx["nonce"]
                amount = (
                    float(decode_hex_data(tx["data"])["amountInTokens"])
                    if tx.get("data")
                    else "N/A"
                )
                validator_id = (
                    decode_hex_data(tx["data"])["validatorId"]
                    if tx.get("data")
                    else "N/A"
                )
                status = (
                    f"Signatures Needed {tx['signature_count']}/{tx['confirmations_required']}"
                    if tx['signature_count'] < tx['confirmations_required']
                    else (
                        "Ready to Execute"
                        if staking_balance >= float(decode_hex_data(tx["data"])["amountInTokens"])
                        else "Insufficient Balance"
                    )
                )
                print(
                    f"- Nonce: {nonce}, Status: {status}, Validator ID: {validator_id}, Amount: {amount} S tokens, Signatures: {tx.get('signature_count', 0)}/{tx.get('confirmations_required', 0)}"
                )

        # Calculate the total sum of tokens in pending transactions
        total_pending_tokens = sum(
            float(decode_hex_data(tx["data"])["amountInTokens"]) for tx in pending_transactions if tx.get("data")
        )

        # Convert staking_balance to float if necessary and calculate total available tokens
        staking_balance = float(staking_balance)
        total_available_tokens = total_pending_tokens - staking_balance

        print(f"Total Available Tokens (Pending - Staking Contract): {total_available_tokens} S tokens")

        # Prepare the full report for all pending transactions
        full_report = format_transaction_report({
            "staking_balance": staking_balance,
            "pending_transactions": [
                {
                    "nonce": tx["nonce"],
                    "validator_id": decode_hex_data(tx["data"])["validatorId"] if tx.get("data") else None,
                    "amount": float(decode_hex_data(tx["data"])["amountInTokens"]) if tx.get("data") else None,
                    "status": (
                        "Signatures Needed"
                        if tx['signature_count'] < tx['confirmations_required']
                        else (
                            "Ready to Execute"
                            if staking_balance >= float(decode_hex_data(tx["data"])["amountInTokens"])
                            else "Insufficient Balance"
                        )
                    ) if tx.get("data") else None,
                    "signature_count": tx.get("signature_count", 0),  # Add signature count
                    "confirmations_required": tx.get("confirmations_required", 0)  # Add confirmations required
                }
                for tx in pending_transactions
            ]
        }, header="Periodic Recheck Report")

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
            "0xa01Bfd7F1Be1ccF81A02CF7D722c30bDCc029718": 258369063124860928,
            "0xB3B1B2d1C9745E98e93F21DC2e4D816DA8a2440c": 538717564067381249,
            "0xf05Ea14723d6501AfEeA3bcFF8c36e375f3a7129": 771222144780206100
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
    
# Check if any transaction can be executed
    if pending_transactions:
        executed = False
        lowest_transaction = pending_transactions[0]
        nonce = lowest_transaction["nonce"]
        hex_data = lowest_transaction.get("data", "")
        decoded = decode_hex_data(hex_data) if hex_data else None

        # Add paused state message to the report
        if paused:
            print("Periodic recheck: Execution is paused.")
            full_report += "\n\n⏸️ **Note:** Transaction execution is currently paused. Rechecks and reports will continue."
        else:
            if decoded:
                while True:
                    if paused:  # Break the execution loop if pause is triggered during execution
                        print("Pause detected during execution. Stopping transaction execution.")
                        break

                    amount = float(decoded["amountInTokens"])
                    if staking_balance >= amount:
                        print(f"Transaction {nonce} is ready to execute. Executing now...")

                        # Execute the transaction
                        transaction = fetch_transaction_by_nonce(nonce)
                        if transaction:
                            result = execute_transaction(transaction)
                            if result:
                                print(f"Transaction {nonce} executed successfully!")

                                # Notify about the executed transaction
                                await broadcast_message(
                                    f"✅ Successfully executed transaction:\n"
                                    f"- **Nonce**: {nonce}\n"
                                    f"- **Validator ID**: {decoded['validatorId']}\n"
                                    f"- **Amount**: {amount} S tokens\n"
                                    f"- **Transaction Hash**: {result}"
                                )

                                # Introduce a delay before rechecking
                                for _ in range(60):  # Breakable countdown
                                    if paused:
                                        print("Pause detected during delay. Breaking out of execution cycle.")
                                        break
                                    await asyncio.sleep(10)  # Sleep in 10-second intervals to allow checking pause state

                                # Refetch staking balance and pending transactions
                                staking_balance = get_staking_balance()
                                staking_balance = round(staking_balance, 1) if staking_balance else 0.0
                                transactions = fetch_recent_transactions(limit=10)
                                pending_transactions = filter_and_sort_pending_transactions(transactions)

                                if not pending_transactions:
                                    print("No more transactions to execute.")
                                    break

                                # Prepare the next transaction for evaluation
                                lowest_transaction = pending_transactions[0]
                                nonce = lowest_transaction["nonce"]
                                hex_data = lowest_transaction.get("data", "")
                                decoded = decode_hex_data(hex_data) if hex_data else None

                                if not decoded:
                                    print(f"Failed to decode transaction data for nonce {nonce}.")
                                    break
                            else:
                                print(f"Failed to execute transaction {nonce}.")
                                break
                        else:
                            print(f"Transaction {nonce} not found for execution.")
                            break
                    else:
                        print("Insufficient balance for the next transaction.")
                        break

        # Periodic reports and counter increment remain outside of the execution loop!
        recheck_counter += 1
        if recheck_counter >= 1:
            await broadcast_message(full_report)
            recheck_counter = 0

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
        f"## Staking Contract Balance: {result['staking_balance']} S tokens\n",  # Bold and larger header
        "**Pending Transactions:**",
        "```diff",  # Use Markdown code block with 'diff' syntax
        f"{'+/-':<3} {'Nonce':<8} {'Validator ID':<15} {'Amount':<15} {'Status':<25} {'Signatures':<10}",  # Added Signatures column
        f"{'-'*80}",  # Adjusted table separator length
    ]
    for tx in result['pending_transactions']:
        # Determine the prefix based on status
        if tx['status'].startswith("Signatures Needed"):
            status_prefix = "-"  # Red highlight for missing signatures
        elif tx['status'] == "Insufficient Balance":
            status_prefix = "-"  # Red highlight for insufficient balance
        elif tx['status'] == "Ready to Execute":
            status_prefix = "+"  # Green highlight for ready to execute
        else:
            status_prefix = "-"  # Default red highlight for unknown status

        # Add the line to the report with Signatures column
        report_lines.append(
            f"{status_prefix:<3} {tx['nonce']:<8} {tx['validator_id']:<15} {tx['amount']:<15} {tx['status']:<25} {tx.get('signature_count', 0)}/{tx.get('confirmations_required', 0):<10}"
        )
    report_lines.append("```")  # Close the code block
    return "\n".join(report_lines)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)