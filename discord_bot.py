import discord_bot
from main import process_transactions  # Import the transaction processing logic
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Discord bot token from .env
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Create a client instance
intents = discord_bot.Intents.default()
intents.messages = True
client = discord_bot.Client(intents=intents)

@client.event
async def on_ready():
    """Event triggered when the bot is ready."""
    print(f"Logged in as {client.user}")
    print("Bot is ready to send transaction reports!")

@client.event
async def on_message(message):
    """Respond to messages in channels the bot has access to."""
    # Ignore messages sent by the bot itself
    if message.author == client.user:
        return

    # Check if the message starts with a command to trigger the report
    if message.content.lower() == "!report":
        await message.channel.send("Fetching transaction data...")
        try:
            # Fetch and process transaction data
            result = process_transactions()
            if result:
                report = format_transaction_report(result)
                await message.channel.send(report)  # Send the formatted report
            else:
                await message.channel.send("No pending transactions or data to report.")
        except Exception as e:
            await message.channel.send(f"An error occurred: {e}")
            print(f"Error: {e}")

def format_transaction_report(result):
    """Format the transaction report for Discord."""
    report_lines = [
        f"Staking Contract Balance: {result['staking_balance']} S tokens",
        f"Number of Pending Transactions: {len(result['pending_transactions'])}",
        "Details of Pending Transactions:"
    ]
    for tx in result['pending_transactions']:
        report_lines.append(
            f"- Nonce: {tx['nonce']}, Validator ID: {tx['validator_id']}, "
            f"Amount: {tx['amount']} S tokens, Status: {tx['status']}"
        )
    return "\n".join(report_lines)

# Run the bot
client.run(DISCORD_TOKEN)
