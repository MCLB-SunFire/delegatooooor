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
    885764705526882335: 911280330567208971,    # Replace with your server guild ID and channel ID. add duplicate identical lines underneith for addiotnal guilds and channels.
}

# Counter for periodic rechecks
recheck_counter = 0

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

@bot.command(name="report")
async def report(ctx):
    """Fetch and send a transaction report when triggered by !report."""
    await ctx.send("Fetching transaction data...")
    try:
        # Fetch staking contract balance
        staking_balance = get_staking_balance()
        staking_balance = round(staking_balance, 1) if staking_balance else 0.0

        # Fetch pending transactions
        transactions = fetch_recent_transactions(limit=20)
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
                    ) if tx.get("data") else None
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
    await ctx.send("Checking for executable transactions...")

    # Fetch staking contract balance
    staking_balance = get_staking_balance()
    staking_balance = round(staking_balance, 1) if staking_balance else 0.0

    # Fetch pending transactions
    transactions = fetch_recent_transactions(limit=20)
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

        # Fetch staking contract balance
        staking_balance = get_staking_balance()
        staking_balance = round(staking_balance, 1) if staking_balance else 0.0
        print(f"Staking Contract Balance: {staking_balance} S tokens")

        # Fetch pending transactions
        transactions = fetch_recent_transactions(limit=20)
        pending_transactions = filter_and_sort_pending_transactions(transactions)

        # Log pending transactions
        if not pending_transactions:
            print("No pending transactions found.")
            await broadcast_message("Periodic Recheck: No pending transactions found.")
            return
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
                    f"- Nonce: {nonce}, Status: {status}, Validator ID: {validator_id}, Amount: {amount} S tokens"
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
                    ) if tx.get("data") else None
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

        # Check if the lowest nonce transaction is missing signatures
        lowest_transaction = pending_transactions[0]
        if lowest_transaction["signature_count"] < lowest_transaction["confirmations_required"]:
            signatures_warning = (
                f"⚠️ **Warning:** The lowest nonce transaction does not have all required signatures.\n"
                f"**Nonce**: {lowest_transaction['nonce']}\n"
                f"**Signatures**: {lowest_transaction['signature_count']}/{lowest_transaction['confirmations_required']}\n"
                f"<@771222144780206100>, <@538717564067381249> please address this issue." # add more IDs linearly as needed.
            )
            full_report += f"\n\n{signatures_warning}"
    
        # Check if any transaction can be executed
        executed = False
        lowest_transaction = pending_transactions[0]
        nonce = lowest_transaction["nonce"]
        hex_data = lowest_transaction.get("data", "")
        decoded = decode_hex_data(hex_data) if hex_data else None

        if decoded:
            while True:
                amount = float(decoded["amountInTokens"])
                if staking_balance >= amount:
                    print(f"Transaction {nonce} is ready to execute. Executing now...")

                    # Execute the transaction
                    transaction = fetch_transaction_by_nonce(nonce)
                    if transaction:
                        result = execute_transaction(transaction)
                        if result:
                            executed = True
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
                            await asyncio.sleep(60)

                            # Refetch staking balance and pending transactions
                            staking_balance = get_staking_balance()
                            staking_balance = round(staking_balance, 1) if staking_balance else 0.0
                            transactions = fetch_recent_transactions(limit=20)
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

        # Increment the counter and send the full report every 6 rechecks
        recheck_counter += 1
        if recheck_counter >= 6:
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
        f"{'+/-':<3} {'Nonce':<8} {'Validator ID':<15} {'Amount':<15} {'Status'}",
        f"{'-'*60}",  # Table separator
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

        # Add the line to the report
        report_lines.append(
            f"{status_prefix:<3} {tx['nonce']:<8} {tx['validator_id']:<15} {tx['amount']:<15} {tx['status']}"
        )
    report_lines.append("```")  # Close the code block
    return "\n".join(report_lines)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)