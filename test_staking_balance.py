from web3 import Web3

# Configuration
SONIC_RPC_URL = "https://rpc.soniclabs.com"  # Replace with your RPC URL
STAKING_CONTRACT_ADDRESS = "0xE5DA20F15420aD15DE0fa650600aFc998bbE3955"  # Replace with your proxy contract address

# Initialize Web3
web3 = Web3(Web3.HTTPProvider(SONIC_RPC_URL))
if not web3.is_connected():
    print("Error: Unable to connect to the Sonic blockchain.")
    exit()

# Fetch the native S token balance of the staking contract
try:
    # Query the balance in Wei
    balance_wei = web3.eth.get_balance(web3.to_checksum_address(STAKING_CONTRACT_ADDRESS))
    
    # Convert Wei to S tokens (18 decimals for native tokens)
    balance_tokens = web3.from_wei(balance_wei, 'ether')

    print(f"Staking Contract S Token Balance: {balance_tokens} S tokens")
except Exception as e:
    print(f"Error fetching S token balance: {e}")
