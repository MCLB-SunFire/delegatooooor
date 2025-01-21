# Delegatooooor

Delegatooooor is a Python-based Discord bot that interacts with a Gnosis Safe on the Sonic blockchain. It continuously fetches pending
transactions from a Gnosis Safe, checks if they have enough signatures and if the staking contract has enough tokens, and then executes
them when conditions are met.

---

## What the Bot Does

- **Manages Gnosis Safe Transactions**  
  - Continuously fetches pending transactions from a Gnosis Safe Transaction Service on an automated loop.
  - Decodes transaction parameters (validator ID, amount in tokens, signatures).
  - Executes transactions on the Sonic network once they have sufficient signatures and balance.

- **Staking Contract Interaction**  
  - Checks the staking contract’s token balance to confirm enough funds are available for delegations.

- **Automated Hourly Checks**  
  - Runs every hour to:
    1. Fetch and log pending transactions.
    2. Check if any are ready to execute (enough signatures, sufficient balance).
    3. Execute those transactions in sequence.
    4. Forces fresh recheck after any successful execution to handle large deposit amounts between hourly checks.
  - Broadcasts results, warnings, or success messages to a designated channel and logs.
  - Separated logic for hourly rechecks on chain and 6 rechecks interval for recheck report discord message minimizing spam.

- **Designated Channel**  
  - Each server (guild) can configure one channel for sending and receiving updates.
  - The bot only processes commands sent, and sends messages, in the designated channel.

---

## How It Works (Blockchain Side)

1. **Fetch Transactions**  
   - Communicates with the Gnosis Safe API using a base URL and Safe address.
2. **Decode & Validate**  
   - Extracts parameters (validator ID, amount) from transaction data.
   - Confirms required signatures and checks if the staking contract has enough tokens.
3. **Execute**  
   - Signs transactions with the bot’s private key.
   - Submits them to the Sonic network via the Gnosis Safe’s `execTransaction` method.
   - logs all relevant data and provides relevant messaging in discord.

---

## How It Works (Discord Side)

1. **Commands**  
   - **`!report`**: Manual intervention to summarize pending transactions and staking balance with a comprehensive color coded table.  
   - **`!execute`**: Manual intervention to execute the lowest-nonce transaction if conditions are met.
   - - Commands are loaded with appropriate logs and messaging for errors, process, results, and data.
2. **Messaging**  
   - The bot sends relevant status updates or warnings to the channel as needed in a prioritized fashion with minimal message spam.
     (e.g., headroom, insufficient balance, missing signatures, successful execution, errors)
   - The bot will PING designated discocrd IDs in the automated recheck reports when conditions exist that need attention soon before
     they become potential process blockers.

---

**Delegatooooor** serves as a streamlined bridge between Discord and the Sonic blockchain via a Gnosis Safe, handling staking contract
checks, transaction decoding, and execution in a single automated workflow.

**Bot wallet address** = 0xeeFd7DC3F9899FcDF6229b9f1EB5328e298E29fE
