from web3 import Web3
from eth_account import Account
import secrets

# Generate a random private key
private_key = secrets.token_hex(32)  # Generate a 32-byte hex private key
private_key = "0x" + private_key  # Prefix with '0x' for Ethereum compatibility

# Derive the public address
account = Account.from_key(private_key)
public_address = account.address

print(f"Private Key: {private_key}")
print(f"Public Address: {public_address}")
