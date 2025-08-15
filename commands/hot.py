# commands/hot.py
from discord.ext import commands

def register_hot_commands(
    bot: commands.Bot,
    *,
    get_paused,                              # callable -> bool
    SONICSCAN_TX_URL: str,                   # string constant
    get_staking_balance,                     # callable -> float
    fetch_recent_transactions,               # callable -> list[dict]
    filter_and_sort_pending_transactions,    # callable -> list[dict]
    decode_hex_data,                         # callable -> dict
    fetch_transaction_by_nonce,              # callable -> dict | None
    execute_transaction,                     # callable -> dict | str (legacy)
):
    async def _run_execute_command(
        ctx: commands.Context,
        *,
        initial_message: str,
        check_pause: bool,
        check_balance: bool,
        allow_no_data_branch: bool,  # only shukai9000 uses this
    ):
        # pause-gate (only for !execute)
        if check_pause and get_paused():
            await ctx.send("⏸️ The bot is currently paused. Transaction execution is disabled.")
            print("Execution attempt blocked due to pause state.")
            return

        # intro line (different per command)
        await ctx.send(initial_message)

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

        # Lowest nonce tx + decode
        lowest_transaction = pending_transactions[0]
        nonce = lowest_transaction["nonce"]
        signature_count = lowest_transaction["signature_count"]
        confirmations_required = lowest_transaction["confirmations_required"]

        # decode rules differ for shukai9000
        hex_data = lowest_transaction.get("data", "")
        if allow_no_data_branch:
            # Accept empty, but keep as string for the decoder
            decoded = decode_hex_data(hex_data) if hex_data else {}
            if not isinstance(decoded, dict):
                decoded = {}
        else:
            decoded = decode_hex_data(hex_data) if hex_data else {}
            if not decoded:
                await ctx.send(f"❌ Failed to decode transaction data for nonce {nonce}.")
                print(f"Failed to decode transaction data for nonce {nonce}.")
                return

        # Signature check (all commands require signatures)
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

        # Balance check (execute + shikai only)
        amount = float(decoded.get("amountInTokens", 0.0)) if decoded else 0.0
        if check_balance and (staking_balance < amount):
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

        # Execute with receipt gating
        transaction["_wait_for_receipt"] = True
        res = execute_transaction(transaction)

        if isinstance(res, dict) and res.get("ok"):
            txh = res["tx_hash"]

            if allow_no_data_branch:
                # shukai9000 has two success bodies depending on decoded/no decoded
                if decoded:
                    validator_id = decoded.get("validatorId", "N/A")
                    await ctx.send(
                        f"✅ Transaction {nonce} executed successfully!\n"
                        f"- **Validator ID**: {validator_id}\n"
                        f"- **Amount**: {amount:,.1f} S tokens\n"
                        f"- **Transaction Hash**: [View on SonicScan]({SONICSCAN_TX_URL}{txh})\u200B"
                    )
                    print(
                        f"Transaction {nonce} executed successfully.\n"
                        f"- Validator ID: {validator_id}\n"
                        f"- Amount: {amount:,.1f} S tokens\n"
                        f"- Transaction Hash: {txh}"
                    )
                else:
                    await ctx.send(
                        f"✅ Transaction {nonce} executed successfully!\n"
                        f"- **No decodeable data**\n"
                        f"- **Transaction Hash**: [View on SonicScan]({SONICSCAN_TX_URL}{txh})\u200B"
                    )
                    print(
                        f"Transaction {nonce} executed successfully.\n"
                        f"- No decodeable data\n"
                        f"- Transaction Hash: {txh}"
                    )
            else:
                # execute / shikai / bankai use same success message
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

    # ---- Command registrations ----

    @bot.command(name="execute")
    async def execute(ctx):
        """Execute lowest nonce. Respects pause state AND token balance."""
        await _run_execute_command(
            ctx,
            initial_message="⚔️ Checking for executable transactions...",
            check_pause=True,
            check_balance=True,
            allow_no_data_branch=False,
        )

    @bot.command(name="shikai")
    async def force_execute(ctx):
        """Execute lowest nonce, ignores pause state."""
        await _run_execute_command(
            ctx,
            initial_message="⚡ Overriding pause state, executing the lowest nonce transaction...",
            check_pause=False,
            check_balance=True,
            allow_no_data_branch=False,
        )

    @bot.command(name="bankai")
    async def force_execute_no_checks(ctx):
        """Execute lowest nonce, ignores pause state AND token balance."""
        await _run_execute_command(
            ctx,
            initial_message="🔥 Overriding pause state AND token balance, executing the lowest nonce transaction...",
            check_pause=False,
            check_balance=False,
            allow_no_data_branch=False,
        )

    @bot.command(name="shukai9000")
    async def ultimate_force_execute(ctx):
        """Ultimate command to execute the lowest nonce, ignoring all checks except signature count."""
        await _run_execute_command(
            ctx,
            initial_message="💀 Unleashing ultimate power! Executing the lowest nonce transaction...",
            check_pause=False,
            check_balance=False,
            allow_no_data_branch=True,  # uses the special success message when decode fails
        )
