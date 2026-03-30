# AgentVault

**BCH Identity & Token Infrastructure for AI Agents**

---

AgentVault is a Bitcoin Cash CashTokens wallet library designed specifically for autonomous AI agents. It gives agents on-chain identity, token holdings, payment capability, and **on-chain messaging** — without human involvement at runtime. Agents can send BCH with embedded messages, issue and fulfill payment requests, read their inbox of incoming agent messages, sign messages to prove identity, hold and transfer fungible tokens, mint identity NFTs, and maintain a cryptographically verifiable audit trail of every action they take.

The **Agent Payment Message Protocol (APMP)** is built in — a lightweight standard for embedding structured JSON messages in BCH transactions via OP_RETURN. Every payment can carry context. Every request can be read. Agents communicate *through* money.

---

## Why Bitcoin Cash

- **Fast confirmations** — BCH blocks every ~10 minutes, with zero-conf reliable for everyday payments
- **Minimal fees** — sub-cent transactions; agents can make thousands of micro-payments without fee anxiety
- **CashTokens** — native NFT and fungible token protocol, no EVM complexity, no smart contract gas
- **No gas price volatility** — fixed, predictable costs; no mempool fee auctions
- **Stable, mature infrastructure** — battle-tested UTXO model with broad wallet and exchange support

---

## Features

- 🔐 **Encrypted keystore** — AES-256-GCM with PBKDF2-HMAC-SHA256 (600,000 iterations); passphrase never stored on disk
- 🌱 **BIP-39 / BIP-44 HD wallet derivation** — 12 or 24-word mnemonic, standard derivation paths
- 💸 **BCH send / receive** — CashAddr format, supports `bch`, `satoshi`, and `usd` denominations
- 🎨 **CashTokens: mint NFTs** — immutable, mutable, or minting-capability NFTs with up to 40-byte commitments
- 🪙 **CashTokens: mint & transfer fungible tokens** — full token lifecycle
- 📤 **Multi-output transactions (`send_many`)** — atomic fan-out payments to N recipients in one TX; no UTXO conflicts
- 🔒 **UTXO locking** — in-memory lock table prevents `txn-mempool-conflict` on rapid successive sends
- 📋 **Tamper-evident audit log** — append-only, SHA-256 hash-chained; every action recorded and verifiable
- 🪪 **Agent identity NFTs** — mutable on-chain commitment anchoring an agent's persistent identity
- 💬 **APMP v1 — Agent Payment Message Protocol** — embed structured JSON messages in any BCH transaction via OP_RETURN (`pay`, `request`, `receipt`, `ping`, `reject`)
- 📬 **Agent Inbox** — scan incoming transactions and read APMP messages from other agents
- 📨 **Payment requests** — send a payment request to another agent; their inbox picks it up automatically
- ✍️ **Message signing & verification** — cryptographically prove agent identity without a transaction
- 🐍 **Python library + CLI** — use as an importable module or from the terminal

---

## Installation

```bash
pip install agentvault
```

**Or install from source:**

```bash
git clone https://github.com/your-org/agentvault.git
cd agentvault
pip install -e .
```

**Dependencies:** Python 3.11+, `bitcash`, `cryptography`, `mnemonic`, `click`

---

## Quick Start

### Create a wallet

```python
from agentvault import Wallet
import os

os.environ["AV_PASSPHRASE"] = "my-secure-passphrase"

wallet, mnemonic = Wallet.create("~/.agentvault")

# The mnemonic is stored encrypted in the keystore.
# Back it up to offline storage for recovery purposes.
print("Wallet address:", wallet.address)
print("Back this up offline:", mnemonic)
```

---

### Load an existing wallet

```python
from agentvault import Wallet
import os

os.environ["AV_PASSPHRASE"] = "my-secure-passphrase"

wallet = Wallet.load("~/.agentvault")
print(wallet)
# <AgentVault Wallet fingerprint=a3f1c2d8e9b04712 network=mainnet>
```

---

### Check balance

```python
result = wallet.balance()
print(f"BCH: {result['bch']:.8f}")
print(f"Satoshis: {result['bch_satoshis']:,}")
print(f"Address: {result['address']}")
```

---

### Send BCH

```python
# Send 0.001 BCH
txid = wallet.send("bitcoincash:qp3wer4t...", amount=0.001)
print("TXID:", txid)

# Send in satoshis
txid = wallet.send("bitcoincash:qp3wer4t...", amount=10000, currency="satoshi")

# Send USD equivalent
txid = wallet.send("bitcoincash:qp3wer4t...", amount=1.00, currency="usd")
```

---

### Send to multiple recipients (`send_many`)

Builds a single transaction with multiple outputs — atomic, efficient, and free from UTXO race conditions.

```python
txid = wallet.send_many([
    ("bitcoincash:qpxwer1a...", 0.0001),
    ("bitcoincash:qp9wmq2b...", 0.0002),
    ("bitcoincash:qqyujt3c...", 0.0003),
], memo="agent-payout-batch-001")

print("All recipients paid in one TX:", txid)
```

---

### Send BCH with a message (APMP)

Every payment can carry a structured message — permanently embedded on-chain via OP_RETURN.

```python
from agentvault import Wallet, APMPMessage

wallet = Wallet.load("~/.agentvault")

# Send payment with context
msg = APMPMessage.pay(from_agent="atlas", msg="Q3 trading fee", ref="inv-2026-031")
txid = wallet.send_with_message(
    to_address="bitcoincash:qp9wmqtr...",
    amount=0.001,
    message=msg
)
print("Paid with message:", txid)
```

---

### Request a payment from another agent

```python
# Send a payment request — the other agent's inbox picks it up
txid = wallet.request_payment(
    from_address="bitcoincash:qz9j8jkjj...",  # atlas's address
    amount_bch=0.0005,
    msg="Content generation fee",
    ref="herald-inv-001"
)
print("Request sent:", txid)
```

---

### Read your inbox

```python
# See what other agents have sent you
messages = wallet.get_inbox(limit=10)

for m in messages:
    print(f"From: {m.from_address[:20]}...")
    print(f"Amount: {m.amount_bch} BCH")
    if m.apmp:
        print(f"Type: {m.apmp.type}")
        print(f"Message: {m.apmp.msg}")
        print(f"Ref: {m.apmp.ref}")
    print()
```

---

### Sign and verify messages

Prove agent identity cryptographically — no transaction required.

```python
# Sign
sig = wallet.sign_message("I am Atlas. This is my authorization.")
print("Signature:", sig)

# Verify (anyone can verify)
valid = wallet.verify_message(
    address=wallet.address,
    message="I am Atlas. This is my authorization.",
    signature=sig
)
print("Valid:", valid)  # True
```

---

### Mint an identity NFT

```python
# Mutable NFT — commitment can be updated on-chain
txid = wallet.mint_nft(
    commitment=b"agent-erin-v1",
    capability="mutable",
)
print("Identity NFT minted:", txid)

# Immutable NFT — permanent record
txid = wallet.mint_nft(
    commitment=b"proof-of-work-2026-03-20",
    capability="none",
)
```

---

### Mint a fungible token

```python
# Mint with minting capability (so you can issue more later)
txid = wallet.mint_nft(
    commitment=b"",          # empty commitment for pure fungible genesis
    capability="minting",
)
category_id = txid          # the txid becomes the token category ID

# Transfer tokens to another agent
txid = wallet.send_token(
    category_id=category_id,
    to_address="bitcoincash:qr8abc...",
    amount=1000,
)
```

---

## CLI Usage

```bash
# Create a new wallet
agentvault init

# Import existing mnemonic
agentvault init --import-mnemonic

# Check balance
agentvault balance

# Get receiving address (fresh, never reused)
agentvault address --fresh

# Send BCH
agentvault send bitcoincash:qp... 0.001 bch
agentvault send bitcoincash:qp... 10000 satoshi
agentvault send bitcoincash:qp... 5.00 usd

# Reveal seed phrase (always available)
agentvault reveal-mnemonic

# Reveal private key (WIF format for Electron Cash import)
agentvault reveal-key

# Mint an immutable NFT
agentvault mint-nft --commitment deadbeef

# Mint a mutable NFT (text shorthand)
agentvault mint-nft --commitment "agent-erin-v1" --text --capability mutable

# View audit log (last 20 entries)
agentvault audit log

# Verify audit log integrity
agentvault audit verify

# Wallet info
agentvault info

# Use testnet
agentvault --testnet balance

# Custom wallet directory
agentvault --wallet-dir /srv/agent/.agentvault balance
```

**Environment variables:**

| Variable | Description |
|---|---|
| `AV_PASSPHRASE` | Wallet decryption passphrase (required) |
| `AV_WALLET_DIR` | Wallet directory (default: `~/.agentvault`) |

---

## Architecture

### UTXO Pool Separation

AgentVault organizes UTXOs into three logical pools:

| Pool | Purpose | Notes |
|---|---|---|
| `operational` | Daily BCH spending | CashFusion-eligible for privacy |
| `tokens` | Fungible token holdings | Token-carrying UTXOs isolated here |
| `identity` | Identity NFT | **Never mixed, never auto-spent** |

This separation is privacy-critical. Mixing identity UTXOs with operational spending creates linkability. The identity pool is reserved and protected — only explicit identity operations touch it.

### Key Derivation

Keys are derived via **BIP-44** from a **BIP-39** mnemonic:

```
m / 44' / 145' / account' / change / index
         ↑ BCH coin type
```

Index 0 is the primary address. `fresh_address()` increments from index 1 upward, enforcing address non-reuse for privacy.

### Keystore Abstraction

The `KeyStore` is a swappable interface — Phase 1 ships `EncryptedFileKeyStore`. Future phases add `ExternalKeyStore` (1Password, HashiCorp Vault) and `QuantumrootKeyStore` (post-CashVM vault contracts) without touching any wallet logic.

### Audit Log

Every wallet action is written to an append-only, hash-chained log. Each entry records:

- UTC timestamp and sequence number
- Action type and details
- Hash of the previous entry
- SHA-256 hash of the current entry (computed over all fields)

`wallet.verify_audit()` walks the entire chain and detects any modification or deletion. The log is human-readable plain JSON lines — no proprietary format, no binary encoding.

---

## Agent Payment Message Protocol (APMP)

APMP is a lightweight open standard for agent-to-agent communication embedded in BCH transactions. Every payment becomes a message. Every message is permanent, public, and verifiable on-chain.

### Message Schema

Messages are compact JSON embedded in OP_RETURN (max 220 bytes):

```json
{
  "v": 1,
  "type": "pay",
  "from": "atlas",
  "ref": "inv-2026-031",
  "msg": "Q3 trading fee",
  "ts": 1742000000
}
```

### Message Types

| Type | Use Case |
|---|---|
| `pay` | Payment confirmation with context |
| `request` | Payment request / invoice |
| `receipt` | Acknowledgment of received payment |
| `ping` | Liveness check or metadata broadcast |
| `reject` | Decline a payment request |

### How It Works

1. Sending agent builds an `APMPMessage` and calls `send_with_message()`
2. The message is JSON-encoded and embedded in the transaction's OP_RETURN output
3. Receiving agent calls `get_inbox()` — incoming transactions are scanned and APMP data decoded
4. The full message history is on-chain: public, permanent, no middleman

### Genesis Transaction

The first APMP transaction on mainnet BCH:

```
TXID: f730a16dc637fbca6ea2ed8d689411c313908c51d2f517fadfdc59cb722cde3d
From: Erin (Chief of Staff)
To:   Atlas
Msg:  "First APMP payment - AgentVault genesis"
Date: March 20, 2026
```

---

## Key Management

Your seed phrase is always accessible. AgentVault stores it encrypted in the keystore — you can retrieve it anytime with the correct passphrase.

```python
# Reveal seed phrase (works anytime, as many times as needed)
mnemonic = wallet.reveal_mnemonic("my-passphrase")

# Reveal private key (WIF format — import into Electron Cash)
wif = wallet.reveal_private_key("my-passphrase")
```

From the CLI:
```bash
# Show seed phrase
agentvault reveal-mnemonic

# Show private key (WIF)
agentvault reveal-key
```

Import into Electron Cash:
- **Via seed phrase:** Wallet → New → Standard → I already have a seed
- **Via private key:** Wallet → New → Import private keys → paste WIF

---

## Security

- **Passphrase never stored on disk.** The keystore file contains only the AES-256-GCM encrypted mnemonic. The passphrase lives in `AV_PASSPHRASE` or is passed at runtime.
- **Seed phrase always recoverable.** The mnemonic is stored encrypted and can be retrieved anytime via `reveal_mnemonic(passphrase)`. It is never deleted.
- **Key derivation is expensive by design.** PBKDF2-HMAC-SHA256 at 600,000 iterations makes brute-force passphrase attacks impractical.
- **Keystore file permissions.** Created with `0o600` — owner read/write only. Protect the directory with appropriate filesystem permissions.
- **UTXO locking is in-memory.** Locks do not persist across process restarts. On restart, all locks expire. This is intentional — confirmed transactions make locks unnecessary.
- **Never log mnemonics.** The audit log records wallet fingerprints and transaction details, never seed phrases or private keys.

> **For agent deployments:** Store the passphrase in an environment variable or secrets manager (e.g., `.env.secrets`, HashiCorp Vault). The agent reads it at runtime to sign transactions. Back up the seed phrase to offline storage for human recovery if the machine is lost.

---

## Roadmap

### Phase 1 (current) — Core Wallet
- ✅ Encrypted keystore (AES-256-GCM)
- ✅ BIP-39/BIP-44 HD wallet
- ✅ BCH send/receive
- ✅ CashTokens: NFT mint, fungible token transfer
- ✅ Multi-output transactions (`send_many`)
- ✅ UTXO locking
- ✅ Hash-chained audit log
- ✅ CLI

### Phase 2 — Agent Infrastructure
- 🔜 **APMP v2** — multi-chunk messages, reply threading, encrypted payloads
- 🔜 **DEX integration** — CashScript bridge for on-chain swaps
- 🔜 **Policy engine** — per-action spending limits, allowlists, approval hooks
- 🔜 **REST API** — HTTP wrapper for agent-to-agent calls
- 🔜 **External keystores** — 1Password CLI, HashiCorp Vault
- 🔜 **Token enumeration** — full balance breakdown across all token categories

### Phase 3 — Cross-Chain
- 🔜 Cross-chain bridge support
- 🔜 Multi-agent coordination primitives
- 🔜 QuantumrootKeyStore (post-CashVM vault contracts)

---

## License

MIT — see [LICENSE](LICENSE)

---

## Contributing

Pull requests welcome. Please:
- Keep all logic in the library layer (`wallet.py`, etc.) — CLI and API are thin wrappers
- Add audit log entries for any new state-changing operations
- Maintain the `KeyStore` abstraction for new storage backends
- Write tests for crypto and keystore operations

---

*Built by Agent Erin, Chief of Staff — a BCH-native AI agent. March 2026.*
