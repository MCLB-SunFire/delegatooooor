# commands/boring.py
import discord
from discord.ext import commands
import asyncio

# These two are safe direct imports (helpers module; no cycles)
from helpers.deposit_monitor import check_large_deposits_custom, fetch_all_deposits_custom

def register_boring_commands(
    bot: commands.Bot,
    *,
    # pass functions that live in main.py or other modules (no cycles)
    run_deposit_probe,                       # from helpers.deposit_monitor (you can pass the function itself)
    split_long_message,                      # from helpers.deposit_monitor
    compose_full_report,                     # from helpers.report_builder
    get_staking_balance,                     # from helpers.staking_contract
    fetch_recent_transactions,               # from helpers.fetch_transactions
    decode_hex_data,                         # from helpers.decode_hex
    get_function_name,                       # from helpers.decode_hex
    filter_and_sort_pending_transactions,    # from helpers.fetch_transactions
    get_paused,                              # function that returns current paused state
    set_paused,                              # function that sets paused state
):
    
    # ---------------- HELP ----------------

    @bot.command(name="help")
    async def custom_help(ctx: commands.Context):
        """Custom Help Command with Thumbnail and Embed Image"""
        embed = discord.Embed(
            title="📜 \u2003**Command List**\u2003 📜",
            description="\u200b",
            color=0xcc1d1b
        )
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1333959203638874203/1334038056927494184/better_vizard_fire.png?ex=679b1342&is=6799c1c2&hm=9df98ede7f3eaff3df9b1f79cc737814cb79c88314bb7cc61c48d9ea86592f5e&")

        embed.add_field(name="📢 \u2003!report",  value="Fetch and send a transaction report.", inline=False)
        embed.add_field(name="⏸️ \u2003!pause",   value="Pause automated transaction execution.", inline=False)
        embed.add_field(name="▶️ \u2003!resume",  value="Resume automated transaction execution.", inline=False)
        embed.add_field(name="⚔️ \u2003!execute", value="Execute lowest nonce. Respects pause state, token balance and payload data.", inline=False)
        embed.add_field(name="⚡ \u2003!shikai",   value="Execute lowest nonce, ignores pause state.", inline=False)
        embed.add_field(name="🔥 \u2003!bankai",  value="Execute lowest nonce, ignores pause state and token balance.", inline=False)
        embed.add_field(name="💀 \u2003!shukai9000", value="Ultimate execution weapon. ignores ALL checks (pause, balance, data).", inline=False)
        embed.add_field(name="🕒 \u2003!history", value="Scan large deposits for a past-hours window (no alerts triggered).", inline=False)
        embed.add_field(name="📄 \u2003!deposits", value="Export ALL deposits in a past-hours window to CSV.", inline=False)

        embed.set_image(url="https://cdn.discordapp.com/attachments/1333959203638874203/1333963513177178204/beets_bleach.png?ex=679acdd5&is=67997c55&hm=eefc8ec5228ca7f64f2040ee8b112e99aaee90682def455f03018e1e5afd9125&")
        await ctx.send(embed=embed)

    # ---------------- PAUSE / RESUME ----------------

    @bot.command(name="pause")
    async def pause(ctx: commands.Context):
        """Pause automated transaction execution."""
        set_paused(True)
        await ctx.send("⏸️ Automated transaction execution has been paused. Rechecks and reports will continue.")
        print("Transaction execution paused.")

    @bot.command(name="resume")
    async def resume(ctx: commands.Context):
        """Resume automated transaction execution."""
        set_paused(False)
        await ctx.send("▶️ Automated transaction execution has been resumed.")
        print("Transaction execution resumed.")

    # ---------------- REPORT ----------------

    @bot.command(name="report")
    async def report(ctx: commands.Context):
        """Fetch and send a transaction report."""
        try:
            await ctx.send("📢 Fetching transaction data...")
            print("📢 Fetching transaction data with REPORT command...")

            # Deposit probe (always run)
            alert_triggered, deposit_report_message, _, _ = await run_deposit_probe()
            if alert_triggered:
                set_paused(True)

            # Staking balance + transactions
            staking_balance = await asyncio.to_thread(get_staking_balance)
            staking_balance = round(staking_balance, 1) if staking_balance else 0.0

            transactions = await asyncio.to_thread(fetch_recent_transactions)
            if not transactions:
                await ctx.send(deposit_report_message + "\n\n📌 No pending transactions found.")
                return

            # Build consolidated report (no signer pings in !report)
            report_text = compose_full_report(
                transactions=transactions,
                staking_balance=staking_balance,
                decode_hex_data=decode_hex_data,
                get_function_name=get_function_name,
                filter_and_sort_pending_transactions=filter_and_sort_pending_transactions,
                ping_missing_signers=False,
            )

            # Always include the deposit outcome line
            report_text += f"\n{deposit_report_message}"

            if get_paused():
                report_text += (
                    "\n\n⏸️ **Note:** Automated transaction execution is currently paused. "
                    "Rechecks and reports will continue."
                )

            for part in split_long_message(report_text):
                await ctx.send(part)

        except Exception as e:
            await ctx.send(f"❌ An error occurred while generating the report: {e}")
            print(f"Error: {e}")

    # ---------------- HISTORY ----------------

    @bot.command(name="history")
    async def historical_report(ctx: commands.Context, hours: float):
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
        asyncio.create_task(_run_historical_scan(ctx, hours))

    async def _run_historical_scan(ctx, hours):
        """Runs the historical scan asynchronously without blocking Discord."""
        try:
            _, message = await asyncio.to_thread(check_large_deposits_custom, hours)
            for part in split_long_message(message):
                await ctx.send(part)
        except Exception as e:
            await ctx.send(f"❌ Error during historical scan: {e}")

    # ---------------- DEPOSITS CSV ----------------

    @bot.command(name="deposits")
    async def export_all_deposits_csv(ctx: commands.Context, hours: float):
        """
        Fetches ALL deposits to the staking contract in the last `hours` hours,
        writes them to a CSV (TxHash, Address, Amount, RunningTotal),
        and sends that CSV as an attachment in Discord.
        Usage: !deposits 24
        """
        if hours <= 0:
            await ctx.send("❌ Invalid time range. Please enter a positive number of hours.")
            return

        await ctx.send(f"🔍 Fetching ALL deposits for the last {hours} hours...")

        # Fetch deposits (thread to keep bot responsive)
        try:
            deposit_list = await asyncio.to_thread(fetch_all_deposits_custom, hours)
        except Exception as e:
            await ctx.send(f"❌ Error retrieving deposits: {e}")
            return

        if not deposit_list:
            await ctx.send(f"✅ No deposits found in the past {hours} hours.")
            return

        # Build CSV
        import csv, tempfile, os
        running_total = 0.0

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as tmpfile:
            writer = csv.writer(tmpfile)
            writer.writerow(["Tx Hash", "Depositor Address", "Deposit Amount", "Running Total"])
            for deposit in deposit_list:
                tx_hash = deposit["tx_hash"]
                sender = deposit["sender"]
                amount = deposit["amount"]
                running_total += amount
                writer.writerow([tx_hash, sender, f"{amount:,.1f}", f"{running_total:,.1f}"])
            temp_csv_filename = tmpfile.name

        try:
            await ctx.send(
                content=f"✅ Found {len(deposit_list)} deposits in the past {hours} hours totaling {running_total:,.1f} S tokens. Here is the CSV file:",
                file=discord.File(temp_csv_filename, filename="all_deposits.csv"),
            )
        finally:
            if os.path.exists(temp_csv_filename):
                os.remove(temp_csv_filename)
