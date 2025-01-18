import discord
from discord.ext import commands, tasks
from fetch_transactions import fetch_recent_transactions, filter_and_sort_pending_transactions
from staking_contract import get_staking_balance
from decode_hex import decode_hex_data
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


@tasks.loop(minutes=1)
async def periodic_recheck():
    """Periodic task to recheck transaction data and post the report."""
    # Find the first text channel the bot has access to
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:  # Ensure the bot can send messages
                try:
                    print("Performing periodic recheck...")
                    # Fetch staking contract balance
                    staking_balance = get_staking_balance()
                    staking_balance = round(staking_balance, 1) if staking_balance else 0.0

                    # Fetch pending transactions
                    transactions = fetch_recent_transactions(limit=20)
                    if not transactions:
                        print("No pending transactions found.")
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

                    # Send the report to the channel
                    await channel.send(report)
                    return  # Stop searching after sending to one channel
                except Exception as e:
                    print(f"Error during periodic recheck: {e}")
    print("No accessible text channel found to send periodic updates.")


def format_transaction_report(result):
    """Format the transaction report for Discord with color-coded statuses."""
    report_lines = [
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
