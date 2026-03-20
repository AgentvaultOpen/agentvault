# AgentVault — Live Testing Log
*For review in Opus founding session*

---

## Overview

This document records every live testnet test run against AgentVault, including bugs found, fixes applied, and transactions confirmed on-chain. It is the honest account of how the software was validated before GitHub publication.

**Wallet under test:**
- Address: `bchtest:qqwheje003t3gt2rg9zae7hj8mm2hgu80u2t6j6dlt`
- Fingerprint: `df13868e228590f2`
- Network: BCH Chipnet (primary BCH development testnet)
- Fulcrum server: `chipnet.imaginary.cash:50002`
- Block explorer: https://chipnet.imaginary.cash

---

## Pre-Live: Unit Test Suite

**Date:** March 17, 2026  
**Result:** 90/90 tests passing  
**Coverage:** crypto, keystore, audit, wallet modules

### What the unit tests proved:
- BIP-39 mnemonic generation and validation
- BIP-44 HD key derivation (correct per known test vectors)
- AES-256-GCM encrypt/decrypt roundtrip
- Wrong passphrase always rejected
- Keystore file permissions enforced at chmod 600
- Mnemonic never written in plaintext to disk
- Audit log hash-chain integrity
- Tamper detection (modified hash, content, prev_hash, deleted entry)
- 100 consecutive fresh addresses — all unique

### What the unit tests did NOT catch:
- The `fresh_address()` privacy bug (see Bug #1 below) — only found through live testing

---

## Network Discovery — March 17, 2026

### Problem: bitcash library was hanging on balance checks

**Root cause:** bitcash's default testnet server list includes two servers:
1. `testnet.imaginary.cash:50002` — TCP open but SSL handshake slow/stalling
2. `testnet.bitcoincash.network:60002` — completely unreachable

When bitcash tries to use both in parallel, the dead server caused all calls to time out.

**Fix:** Override via environment variable:
```bash
export FULCRUM_API_TESTNET="chipnet.imaginary.cash:50002"
```

### Network selection: Chipnet over Testnet4

Initially funded on testnet4 (faucet default). Dirk correctly identified that **chipnet** is the right choice:
- Chipnet = BCH's primary development testnet
- Where every new CHIP (Bitcoin Cash Improvement Proposal) is tested first
- Where CashVM (May 2026) will activate before mainnet
- Where CashTokens was first live (pre-mainnet)

Switched to chipnet. Refunded via faucet. All subsequent tests run on chipnet.

**Chipnet Fulcrum:** `chipnet.imaginary.cash:50002`  
**Block height at first connection:** 297,399

---

## Bug #1 — Privacy: `fresh_address()` returned primary address

**Found:** March 17, 2026 — during Stage 1 live testing  
**Severity:** HIGH — would have caused address reuse on mainnet  
**Status:** FIXED ✅

### Description
`wallet.fresh_address()` was returning the same address as `wallet.address` on the first call. Every subsequent call returned a new unique address. But that first call was a privacy violation — address reuse links transactions and destroys on-chain privacy.

### Root cause
In `keystore.py`, the address counter `get_next_address()` was initialized to index 0:
```python
current = self._address_index.get(slot, 0)  # BUG: starts at 0
```
But `wallet.address` is always index 0 (BIP-44 path `m/44'/145'/0'/0/0`). First fresh address was therefore also index 0 — identical to the primary address.

### Fix
```python
# Counter starts at 1 — index 0 is reserved for wallet.address (primary)
current = self._address_index.get(slot, 1)  # FIXED: starts at 1
```

### New test added
```python
def test_fresh_address_never_equals_primary(self, keystore):
    """Fresh addresses must never equal the primary address (index 0)."""
    primary = keystore.get_address(account=0, change=0, index=0)
    for _ in range(10):
        fresh, _ = keystore.get_next_address()
        assert fresh != primary, "fresh_address() returned the primary address"
```

### Why the unit tests missed it
The unit test checked that 100 consecutive fresh addresses were all unique with each other. It never compared them against `wallet.address`. Added the explicit check above.

**Lesson:** Unit tests prove internal consistency. Live testing proves correctness against the real world. Both are required.

---

## Stage 1 — Basic Network Tests (Chipnet)

**Date:** March 17, 2026  
**Network:** BCH Chipnet  
**Status:** ALL PASSED ✅

### Test 1: Balance check
- Connected to chipnet Fulcrum server
- Queried wallet balance
- **Result:** 0.01015 tBCH confirmed ✅

### Test 2: Fresh address privacy
- Generated 5 consecutive fresh addresses
- Verified: none equal `wallet.address` (primary, index 0)
- Verified: all 5 are unique from each other
- **Result:** Privacy enforced ✅ (bug fix confirmed working)

### Test 3: Send BCH — Real On-Chain Transaction
- Sent 5,000 satoshi to a fresh address (self-send)
- **Result: BROADCAST AND CONFIRMED** ✅

```
TXID:     454cb81977b5b74716bc3cb5b7642a5a7a25013220d1c1586eab0fcf8be65a15
Amount:   5,000 satoshi (0.00005 tBCH)
From:     bchtest:qqwheje003t3gt2rg9zae7hj8mm2hgu80u2t6j6dlt
To:       bchtest:qr9pt0mlgatzatjvveakucnv5aduf99y0ctpmnzqkq (fresh address #6)
Network:  Chipnet
Explorer: https://chipnet.imaginary.cash/tx/454cb81977b5b74716bc3cb5b7642a5a7a25013220d1c1586eab0fcf8be65a15
```

This was AgentVault's **first real transaction** on any BCH network.

### Test 4: Audit log integrity after real transaction
- Verified hash-chain after real send
- 32 entries at time of check (including all debug sessions)
- **Result:** Chain VALID ✅

### Test 5: Edge case — invalid address rejected cleanly
- Attempted send to `"not-a-real-address"`
- **Result:** `InvalidAddress: Cash address is missing prefix` ✅
- Audit chain still valid after failed tx ✅

---

## Stage 2 — CashTokens NFT Minting

**Date:** March 17, 2026  
**Network:** BCH Chipnet  
**Status:** ALL PASSED ✅

### Bug #2 — mint_nft() used wrong token_amount value

**Severity:** MEDIUM — would prevent all NFT minting  
**Fixed:** March 17, 2026 ✅

CashTokens protocol: for a pure NFT with no fungible tokens, `token_amount` must be `None`, not `0`. Passing `0` triggers validation: `1 <= valid token amount <= 9223372036854775807`. Fixed in wallet.py.

### Bug #3 — genesis UTXO must have txindex == 0

**Severity:** MEDIUM — prevents genesis NFT minting without prep  
**Fixed:** March 17, 2026 ✅

bitcash's `select_cashtoken_utxo()` only accepts genesis UTXOs where `txindex == 0`. Initial UTXO was at `txindex=1` (change output). Fix: before minting a new category, send a prep tx to CATKN address as primary recipient — creates a txindex=0 UTXO. This prep step is now documented in the mint workflow.

### NFT 1 — Immutable (`capability="none"`) ✅
```
TXID:       f59c8e992a7d3675566bc5576db6d1007e5558da69bf1879d198a30ece34296f
Category:   80c7cc1fd6aec6f5444e745f302cfb7edf81e5ec15e8317850cbab3e73bc7eb9
Commitment: agentvault-immutable-001
Explorer:   https://chipnet.imaginary.cash/tx/f59c8e992a7d3675566bc5576db6d1007e5558da69bf1879d198a30ece34296f
```

### NFT 2 — Mutable (`capability="mutable"`) ✅ — Agent Identity Type
Commitment updatable. This is the type used for QUBES agent identity NFTs.
```
TXID:       73ce7b4860e1407877ac9bed737626f3a9c5ffbc4d1882258d56e652ce90a890
Category:   5a1dc248b2866ccdb4cc2fc60ab39f3df43022a736902ba0855aea2f73b00039
Commitment: agent-erin-identity-v1
Explorer:   https://chipnet.imaginary.cash/tx/73ce7b4860e1407877ac9bed737626f3a9c5ffbc4d1882258d56e652ce90a890
```

### NFT 3 — Minting (`capability="minting"`) ✅ — Genesis Category
Can issue more NFTs of the same category. The factory token for collections and fungible token issuance.
```
TXID:       6977ad12c6a7f92f3889c0f1115a5f0c9cf5260f770cdcd2489d9fc404f5fea0
Category:   eca0421ab6f7325d0abd3912b9815bed18a14244347ea6d2d4a0049e064bef12
Commitment: agentvault-genesis
Explorer:   https://chipnet.imaginary.cash/tx/6977ad12c6a7f92f3889c0f1115a5f0c9cf5260f770cdcd2489d9fc404f5fea0
```

### Remaining planned test:
- Transfer an NFT to a second address (Stage 2 extension)

---

## Stage 3 — Edge Cases & Stress

**Status:** PENDING

### Planned tests:
1. UTXO accumulation — receive many small amounts, then send
2. Send with insufficient funds
3. Oversized NFT commitment (>40 bytes) — should be rejected before broadcast
4. Rapid back-to-back sends — UTXO management under load
5. Network timeout simulation

---

## Stage 4 — Interoperability

**Status:** PENDING — requires Electron Cash or Paytaca

### Planned tests:
1. Import AgentVault mnemonic into Electron Cash as BIP-39/BIP-44
2. Verify index 0 address matches `wallet.address`
3. Send from Electron Cash → receive in AgentVault
4. Send from AgentVault → verify in Electron Cash
5. Transfer a CashToken NFT between wallets

**Note:** BIP-44 derivation was verified mathematically (private key matches known test vector). Live interop test confirms the real-world wallet behavior matches theory.

---

## Stage 5 — CashVM Contracts (Future)

**Status:** PENDING — CashVM activates on chipnet before mainnet (May 2026)

### Planned tests (post-CashVM activation):
1. Deploy a simple spending covenant
2. Interact with a DEX contract (TapSwap or CauldronDEX)
3. Test Quantumroot vault interactions (Phase 4)

---

## Configuration Reference

### Environment variables
```bash
# Required — never stored on disk
export AV_PASSPHRASE="your-passphrase"

# Override Fulcrum server (chipnet)
export FULCRUM_API_TESTNET="chipnet.imaginary.cash:50002"
```

### Running live tests
```bash
cd /path/to/agentvault
source venv/bin/activate
export AV_PASSPHRASE="your-testnet-passphrase"   # set before running — never commit this
FULCRUM_API_TESTNET="chipnet.imaginary.cash:50002" \
python3 -m pytest tests/test_testnet_live.py -v -s
```

### Running unit tests (no network required)
```bash
cd /home/agenterin/.openclaw/workspace/projects/agentvault
source venv/bin/activate
python3 -m pytest tests/ -q
# Expected: 91 passed (90 original + 1 new privacy regression test)
```

---

## Audit Log Snapshot — End of Stage 1

The audit log is the living record of the wallet's history. Every entry is hash-chained — modify any entry and `verify_audit()` immediately detects it.

```
#01  wallet_init               2026-03-17T18:23:48  (wallet created)
#02  wallet_created            2026-03-17T18:23:48
#03  wallet_init               2026-03-17T18:50:10  (session reloads)
...
#22  send_failed               2026-03-17T19:15:22  (during Fulcrum server hunt)
#23  send_failed               2026-03-17T19:17:38
#24  wallet_init               2026-03-17T19:25:46  (chipnet session begins)
#25  balance_check             2026-03-17T19:25:52  ← first successful balance
#26  address_generated         2026-03-17T19:25:52  ← fresh addresses
...
#32  send                      2026-03-17T19:25:52  ← FIRST REAL TRANSACTION ✅
#33  wallet_init               2026-03-17T19:26:04
#34  send_failed               2026-03-17T19:26:10  (bad address test — expected)
```

The failed entries (#22, #23) are important: they show the wallet correctly logged attempts that didn't go through, and the audit chain remained valid throughout. Failures are auditable too.

---

## Key Decisions Made During Testing

1. **Chipnet over testnet4** — Dirk's call, correct. Chipnet is where CashVM lands.
2. **Fresh address counter starts at 1, not 0** — privacy-critical fix found only in live testing
3. **FULCRUM_API_TESTNET env var** — correct override mechanism for bitcash; bake into wallet config for Phase 2
4. **Both unit AND live tests required** — unit tests missed a real privacy bug; both layers are necessary

---

## For the Opus Session

This log represents the honest state of AgentVault as of March 17, 2026:

**What works:**
- Full wallet lifecycle (create, load, persist)
- BIP-39/44 key derivation (correct per known vectors)
- AES-256-GCM encryption (600K PBKDF2 iterations)
- Address privacy (fresh address counter starts at 1, never reuses primary)
- Real BCH send on chipnet (first transaction confirmed)
- Audit log (32 entries, hash-chain valid through debug sessions AND real txns)
- 91 unit tests passing

**What's next:**
- Stage 2: CashTokens NFT minting on chipnet
- Stage 3: Edge cases and stress
- Stage 4: Electron Cash interop (manual)
- GitHub publication (after Stage 2 minimum)

**What we learned:**
- Live testing found a privacy bug that 90 unit tests missed
- The Opus architecture session (Phase 1 design) held up under real conditions
- The audit log is already beautiful — every session, every failure, every success, all chained

*The foundation is solid. The work continues.*

---
*Last updated: March 17, 2026 — Stage 1 complete*
