import discord
from discord.ext import commands, tasks
from fetch_transactions import fetch_recent_transactions, filter_and_sort_pending_transactions
from staking_contract import get_staking_balance
from decode_hex import decode_hex_data
from execute_transaction import fetch_transaction_by_nonce, execute_transaction  # Execution logic
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Initialize the Discord bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Discord bot connected as {bot.user}")
    print("Bot is running and ready to accept commands!")
    # Start the periodic task when the bot is ready
    periodic_recheck.start()


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
                        "Ready to Execute"
                        if staking_balance >= float(decode_hex_data(tx["data"])["amountInTokens"]) else "Insufficient Balance"
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
        return

    # Get the lowest nonce transaction
    lowest_transaction = pending_transactions[0]
    nonce = lowest_transaction["nonce"]
    hex_data = lowest_transaction.get("data", "")
    decoded = decode_hex_data(hex_data) if hex_data else None

    if not decoded:
        await ctx.send(f"❌ Failed to decode transaction data for nonce {nonce}.")
        return

    # Extract required amount from the decoded payload
    amount = float(decoded["amountInTokens"])

    # Check if the staking contract has enough tokens
    if staking_balance < amount:
        await ctx.send(
            f"❌ Insufficient staking contract balance to execute the transaction.\n"
            f"- **Nonce**: {nonce}\n"
            f"- **Required**: {amount} S tokens\n"
            f"- **Available**: {staking_balance} S tokens"
        )
        return

    # Fetch the transaction details by nonce
    transaction = fetch_transaction_by_nonce(nonce)
    if not transaction:
        await ctx.send(f"❌ No transaction found for nonce {nonce}.")
        return

    # Execute the transaction
    result = execute_transaction(transaction)
    if result:
        await ctx.send(
            f"✅ Transaction {nonce} executed successfully!\n"
            f"- **Validator ID**: {decoded['validatorId']}\n"
            f"- **Amount**: {amount} S tokens\n"
            f"- **Transaction Hash**: {result}"
        )
    else:
        await ctx.send(f"❌ Transaction {nonce} could not be executed.")

@tasks.loop(hours=1)
async def periodic_recheck():
    """Periodic task to recheck transaction data and automatically execute the lowest nonce transaction."""
    try:
        print("Performing periodic recheck...")

        # Fetch staking contract balance
        staking_balance = get_staking_balance()
        staking_balance = round(staking_balance, 1) if staking_balance else 0.0
        print(f"Staking Contract Balance: {staking_balance} S tokens")

        # Fetch pending transactions
        transactions = fetch_recent_transactions(limit=20)
        pending_transactions = filter_and_sort_pending_transactions(transactions)

        if not pending_transactions:
            print("No pending transactions found.")
            await broadcast_message("Periodic Recheck: No pending transactions found.")
            return

        # Prepare the full report for all pending transactions
        full_report = format_transaction_report({
            "staking_balance": staking_balance,
            "pending_transactions": [
                {
                    "nonce": tx["nonce"],
                    "validator_id": decode_hex_data(tx["data"])["validatorId"] if tx.get("data") else None,
                    "amount": float(decode_hex_data(tx["data"])["amountInTokens"]) if tx.get("data") else None,
                    "status": (
                        "Ready to Execute"
                        if staking_balance >= float(decode_hex_data(tx["data"])["amountInTokens"]) else "Insufficient Balance"
                    ) if tx.get("data") else None
                }
                for tx in pending_transactions
            ]
        }, header="Periodic Recheck Report")

        # Check if any transaction can be executed
        executed = False
        lowest_transaction = pending_transactions[0]
        nonce = lowest_transaction["nonce"]
        hex_data = lowest_transaction.get("data", "")
        decoded = decode_hex_data(hex_data) if hex_data else None

        if decoded:
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

        # Append a note if no transactions were executed
        if not executed:
            full_report += "\nNo transactions were executed during this recheck."

        # Send the full report
        await broadcast_message(full_report)

    except Exception as e:
        print(f"Error during periodic recheck: {e}")
        await broadcast_message(f"Error during periodic recheck: {e}")

async def broadcast_message(message):
    """Broadcast a message to all servers the bot is in."""
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.permissions_for(channel.guild.me).send_messages:
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
        "**Pending Transactions:**\n",
        "```diff",  # Use Markdown code block with 'diff' syntax
        f"{'+/-':<3} {'Nonce':<8} {'Validator ID':<15} {'Amount':<15} {'Status'}",
        f"{'-'*60}",  # Table separator
    ]
    for tx in result['pending_transactions']:
        # Add + or - at the start of the line for coloring
        status_prefix = "+" if tx['status'] == "Ready to Execute" else "-"
        report_lines.append(
            f"{status_prefix:<3} {tx['nonce']:<8} {tx['validator_id']:<15} {tx['amount']:<15} {tx['status']}"
        )
    report_lines.append("```")  # Close the code block
    return "\n".join(report_lines)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
