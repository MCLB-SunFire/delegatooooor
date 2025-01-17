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
