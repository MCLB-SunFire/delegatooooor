import discord
from discord.ext import commands
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
intents.messages = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Discord bot connected as {bot.user}")
    print("Bot is running and ready to accept commands!")

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

        # Prepare the report
        report = f"Staking Contract Balance: {staking_balance} S tokens\nPending Transactions:\n"
        for tx in filter_and_sort_pending_transactions(transactions):
            nonce = tx["nonce"]
            hex_data = tx.get("data", "")
            decoded = decode_hex_data(hex_data) if hex_data else None

            if decoded:
                validator_id = decoded["validatorId"]
                amount = float(decoded["amountInTokens"])
                status = (
                    "Ready to Execute"
                    if staking_balance >= amount
                    else "Insufficient Balance"
                )
                report += f"- Nonce: {nonce}, Validator ID: {validator_id}, Amount: {amount} S tokens, Status: {status}\n"
        await ctx.send(report)
    except Exception as e:
        await ctx.send(f"An error occurred: {e}")
        print(f"Error: {e}")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
