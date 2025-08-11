from eth_utils import decode_hex
from eth_abi.abi import decode

def decode_hex_data(hex_data):
    """Decode hex-encoded data for the staking contract."""
    try:
        # Remove the 0x prefix if it exists
        hex_data = hex_data[2:] if hex_data.startswith("0x") else hex_data

        # Function selector is the first 4 bytes, skip it (8 characters in hex)
        params = decode(['uint256', 'uint256'], decode_hex(hex_data[8:]))

        # Parse the decoded data
        validator_id = str(params[0])  # First parameter: Validator ID
        amount_in_tokens = params[1] / 10**18  # Convert from Wei to tokens

        return {
            "validatorId": validator_id,
            "amountInTokens": str(amount_in_tokens)
        }
    except Exception as e:
        print(f"Error decoding hex data: {e}")
        return None
    
_SELECTOR_TO_NAME = {
    "095ea7b3": "approve",
    "42966c68": "burn",
    "79cc6790": "burnFrom",
    "5eac6239": "claimRewards",
    "d9a34952": "delegate",
    "d0e30db0": "deposit",
    "ed88c68e": "donate",
    "2f2ff15d": "grantRole",
    "485cc955": "initialize",
    "cf5c3eb7": "operatorExecuteClawBack",
    "71bbf3e7": "operatorInitiateClawBack",
    "8456cb59": "pause",
    "d505accf": "permit",
    "715018a6": "renounceOwnership",
    "36568abe": "renounceRole",
    "d547741f": "revokeRole",
    "543f66a4": "setDepositPaused",
    "98176a01": "setProtocolFeeBIPS",
    "f0f44260": "setTreasury",
    "e882e4ef": "setUndelegateFromPoolPaused",
    "cc90ef5c": "setUndelegatePaused",
    "72f0cb30": "setWithdrawDelay",
    "37d15139": "setWithdrawPaused",
    "a9059cbb": "transfer",
    "23b872dd": "transferFrom",
    "f2fde38b": "transferOwnership",
    "634b91e3": "undelegate",
    "d02e92a6": "undelegateFromPool",
    "2f3cd672": "undelegateMany",
    "4f1ef286": "upgradeToAndCall",
    "38d07436": "withdraw",
    "ac697e3f": "withdrawMany",
}

def get_function_name(hex_data: str | bytes) -> str:
    """
    Return the staking‑contract function name for a given calldata payload.
    Falls back to 'Unknown' or 'No Data' gracefully.
    """
    try:
        if not hex_data:
            return "No Data"
        if isinstance(hex_data, bytes):
            hex_data = hex_data.hex()
        hex_data = hex_data[2:] if hex_data.startswith("0x") else hex_data
        selector = hex_data[:8].lower()
        return _SELECTOR_TO_NAME.get(selector, "Unknown")
    except Exception as e:
        print(f"Error decoding selector: {e}")
        return "Unknown"
