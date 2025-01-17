from web3 import Web3
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Configuration
SONIC_RPC_URL = os.getenv("SONIC_RPC_URL")
STAKING_CONTRACT_ADDRESS = os.getenv("STAKING_CONTRACT_ADDRESS")

# Initialize Web3
web3 = Web3(Web3.HTTPProvider(SONIC_RPC_URL))
if not web3.is_connected():
    raise ConnectionError("Unable to connect to the Sonic blockchain. Check the SONIC_RPC_URL.")

def get_staking_balance():
    """Fetch the S token balance (native token) of the staking contract."""
    try:
        # Query the native token balance of the staking contract
        balance_wei = web3.eth.get_balance(web3.to_checksum_address(STAKING_CONTRACT_ADDRESS))
        
        # Convert from Wei to human-readable S tokens (18 decimals)
        balance_tokens = web3.from_wei(balance_wei, 'ether')
        return balance_tokens
    except Exception as e:
        print(f"Error fetching S token balance: {e}")
        return None
