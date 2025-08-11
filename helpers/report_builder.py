# report_builder.py
from typing import Any, Callable, Dict, List

def format_transaction_report(result, header=None):
    """Format the transaction report for Discord with color-coded statuses."""
    report_lines = []

    # Add a custom header if provided
    if header:
        report_lines.append(f"### {header} ###\n")

    # Add the standard report content
    report_lines += [
        f"## Staking Contract Balance: {result['staking_balance']:,.1f} S tokens\n",  # Bold and larger header
        "**Pending Transactions:**",
        "```diff",  # Use Markdown code block with 'diff' syntax
        f"{'+/-':<5} {'Nonce':<7} {'Val':<6} {'Amount':<13} {'Status':<24} {'Sig':<7} {'Function':<9}",
        f"{'-'*80}",  # Adjusted table separator length
    ]
    for tx in result['pending_transactions']:
        status_value = tx['status'] or "No Data"  # Ensure status is always a string

        # Determine the prefix based on status
        if status_value.startswith("Signatures Needed"):
            status_prefix = "-"  # Red highlight for missing signatures
        elif status_value == "Insufficient Balance":
            status_prefix = "-"  # Red highlight for insufficient balance
        elif status_value == "Ready to Execute":
            status_prefix = "+"  # Green highlight for ready to execute
        elif status_value == "No Data":
            status_prefix = "?"  # Neutral or gray highlight for missing data
        else:
            status_prefix = "-"  # Default red highlight for unknown status

        # Add the line to the report with Signatures column
        report_lines.append(
            f"{status_prefix:<5} {tx['nonce']:<7} {tx['validator_id']:<6} {tx['amount']:<13,.1f} {tx['status']:<24} {tx.get('signature_count', 0)}/{tx.get('confirmations_required', 0):<5} {tx.get('func','N/A'):<9}"
        )
    report_lines.append("```")  # Close the code block
    return "\n".join(report_lines)

SignerMap = Dict[str, int]

def compose_full_report(
    *,
    transactions: List[Dict[str, Any]],
    staking_balance: float,
    decode_hex_data: Callable[[Any], Dict[str, Any]],
    get_function_name: Callable[[Any], str],
    filter_and_sort_pending_transactions: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]],
    signer_discord_map: SignerMap | None = None,
    ping_missing_signers: bool = True,  # NEW
) -> str:
    """
    Build + format the report using your EXACT logic and wording.
    Set ping_missing_signers=False to omit <@discord_id> mentions.
    """
    if signer_discord_map is None:
        signer_discord_map = {
            "0x69503B52764138e906C883eD6ef4Cac939eb998C": 892276475045249064,
            "0x693f30c37D5a0Db9258C636E93Ccf011ACd8c90c": 232514597200855040,
            "0xB3B1B2d1C9745E98e93F21DC2e4D816DA8a2440c": 538717564067381249,
            "0xf05Ea14723d6501AfEeA3bcFF8c36e375f3a7129": 771222144780206100,
            "0xa01Bfd7F1Be1ccF81A02CF7D722c30bDCc029718": 258369063124860928,
        }

    pending = filter_and_sort_pending_transactions(transactions or [])

    # 1) Payload — unchanged
    payload = {
        "staking_balance": staking_balance,
        "pending_transactions": [
            {
                "nonce": tx["nonce"],
                "func": get_function_name(tx["data"]) if tx.get("data") else "No Data",
                "validator_id": (decode_hex_data(tx["data"]) or {}).get("validatorId", "No Data") if tx.get("data") else "No Data",
                "amount": float((decode_hex_data(tx["data"]) or {}).get("amountInTokens", 0.0)) if tx.get("data") else 0.0,
                "status": (
                    "Signatures Needed"
                    if tx['signature_count'] < tx['confirmations_required']
                    else ("Ready to Execute"
                          if staking_balance >= float((decode_hex_data(tx["data"]) or {}).get("amountInTokens", 0.0))
                          else "Insufficient Balance")
                ) if tx.get("data") else "No Data",
                "signature_count": tx.get("signature_count", 0),
                "confirmations_required": tx.get("confirmations_required", 0),
            }
            for tx in pending
        ],
    }

    # 2) Format exactly as before
    full_report = format_transaction_report(payload)

    # 3) Headroom warning — unchanged
    total_pending_tokens = sum(
        float((decode_hex_data(tx["data"]) or {}).get("amountInTokens", 0.0))
        for tx in pending if tx.get("data")
    )
    total_available_tokens = total_pending_tokens - float(staking_balance)

    # match previous behavior and wording
    if total_available_tokens < 1_000_000:
        full_report += (
            "\n\n"
            f"⚠️ **Warning:** The token staking headroom (total pending - staking contract balance) "
            f"has dropped below 1 million.\n"
            f"**Current Headroom:** {total_available_tokens} S tokens\n"
            f"<@771222144780206100>, <@538717564067381249> please queue up more transactions."
        )

    # 4) Missing signatures — now respects ping_missing_signers
    missing_signatures: Dict[int, List[int]] = {}
    for tx in pending:
        if tx["signature_count"] < tx["confirmations_required"]:
            signed_addresses = {conf["owner"] for conf in tx["confirmations"]}
            for address, discord_id in signer_discord_map.items():
                if address not in signed_addresses:
                    missing_signatures.setdefault(discord_id, []).append(tx["nonce"])

    if missing_signatures:
        lines = ["⚠️ **Warning:** The following transactions are missing signatures:"]
        for discord_id, nonces in missing_signatures.items():
            nonces_str = ", ".join(map(str, sorted(nonces)))
            if ping_missing_signers:
                lines.append(f"- <@{discord_id}>: Nonce(s) {nonces_str}")
            else:
                lines.append(f"- Signer {discord_id}: Nonce(s) {nonces_str}")
        full_report += "\n\n" + "\n".join(lines)

    return full_report
