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
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Discord bot connected as {bot.user}")
    print("Bot is running and ready to accept commands!")

@bot.command(name="report")
async def report(ctx):
    """Fetch and send a transaction report as an embed when triggered by !report."""
    try:
        # Fetch staking contract balance
        staking_balance = get_staking_balance()
        staking_balance = round(staking_balance, 1) if staking_balance else 0.0

        # Fetch pending transactions
        transactions = fetch_recent_transactions(limit=20)
        if not transactions:
            await ctx.send("No pending transactions found.")
            return

        # Create the embed
        embed = discord.Embed(
            title="Transaction Report",
            description=f"Staking Contract Balance: **{staking_balance} S tokens**",
            color=discord.Color.blue(),  # Embed border color
        )

        # Add pending transactions to the embed
        pending_transactions = filter_and_sort_pending_transactions(transactions)
        if not pending_transactions:
            embed.add_field(name="No Pending Transactions", value="All caught up!", inline=False)
        else:
            for tx in pending_transactions:
                nonce = tx["nonce"]
                hex_data = tx.get("data", "")
                decoded = decode_hex_data(hex_data) if hex_data else None

                if decoded:
                    validator_id = decoded["validatorId"]
                    amount = float(decoded["amountInTokens"])
                    status = (
                        "🟢 Ready to Execute"
                        if staking_balance >= amount
                        else "🔴 Insufficient Balance"
                    )
                    embed.add_field(
                        name=f"Nonce: {nonce}",
                        value=(
                            f"**Validator ID:** {validator_id}\n"
                            f"**Amount:** {amount:.1f} S tokens\n"
                            f"**Status:** {status}"
                        ),
                        inline=False
                    )

        # Send the embed
        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"An error occurred: {e}")
        print(f"Error: {e}")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
