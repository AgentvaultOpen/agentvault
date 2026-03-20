# UTXO Fix Results
**Date:** 2026-03-20  
**Author:** Agent Erin (subagent)

---

## Summary

Two improvements were made to `agentvault/wallet.py`:

1. **UTXO locking** — prevents `txn-mempool-conflict` on rapid sequential sends  
2. **`send_many()`** — multi-output transactions (fan-out) in a single TX

---

## Fix 1 — UTXO Locking

### What Changed

Added an in-memory pending UTXO lock table to the `Wallet` class:

```python
self._pending_utxos: dict[tuple, float] = {}
```

Three new internal methods:

| Method | Purpose |
|--------|---------|
| `_expire_utxo_locks()` | Clears locks older than `UTXO_LOCK_TTL` (60 seconds) |
| `_lock_utxos(unspents)` | Marks a list of Unspent objects as in-flight |
| `_filter_unlocked_utxos(unspents)` | Returns only UTXOs not currently locked |

One new public method:

| Method | Purpose |
|--------|---------|
| `unlock_utxos() -> int` | Manually release all locks (e.g. after block confirmation) |

### How It Works

All send methods (`send`, `send_many`, `mint_nft`, `send_token`) now:

1. Call `key.get_unspents()` to fetch the latest UTXO set from the network
2. Pass `key.unspents` through `_filter_unlocked_utxos()` to skip pending UTXOs
3. Pass the filtered list to `key.send(..., unspents=available)` — bitcash accepts explicit UTXO lists
4. After broadcast, call `_lock_utxos(available)` to mark all used UTXOs as pending

Locks auto-expire after **60 seconds** (`UTXO_LOCK_TTL` constant at module level). This handles the case where a TX fails to broadcast — locks won't persist indefinitely.

### Why This Fixes the Bug

Before: `key.send()` without an explicit `unspents=` argument always calls `get_unspents()` internally. Two rapid sends would both fetch the same UTXO set and try to spend the same inputs — causing `txn-mempool-conflict` on the second TX.

After: The first send locks its UTXOs. The second send filters them out before building the transaction. No conflict.

---

## Fix 2 — `send_many()` Method

### Signature

```python
def send_many(self, recipients: list[tuple[str, float]], memo: str = None) -> str:
    """
    Send BCH to multiple recipients in a single transaction.
    recipients = [(address, amount_bch), ...]
    Returns single TXID covering all outputs.
    """
```

### Implementation

Builds a single `outputs` list from all recipients and calls `key.send()` once:

```python
outputs = [(addr, amt, "bch") for addr, amt in recipients]
txid = key.send(outputs, unspents=available)
```

bitcash natively supports multi-output transactions — one call, one TX, one TXID.

**Advantages over looping `send()`:**
- **Atomic** — all recipients funded or none
- **Cheaper** — one TX fee vs. N fees
- **No UTXO race** — impossible to conflict with itself
- **Faster** — one network round-trip

---

## Test Transaction — 3 Agent Wallets Funded

### Transaction

| Field | Value |
|-------|-------|
| **TXID** | `3c4218c57f973928dd50ffe6e85e5ddd3c402380dc724c8a74ab1387ff9cd12b` |
| **Status** | Broadcast (mempool) |
| **Inputs** | 2 UTXOs |
| **Outputs** | 5 (3 recipients + 1 change + 1 fee structure) |
| **Total sent** | 6,617,236 satoshis |
| **Fee** | 599 satoshis (~0.000006 BCH) |
| **Sender** | `[redacted — mainnet wallet address]` |

**Explorer:** https://blockchair.com/bitcoin-cash/transaction/3c4218c57f973928dd50ffe6e85e5ddd3c402380dc724c8a74ab1387ff9cd12b

### Recipient Confirmations

| Agent | Address | Amount | Confirmed |
|-------|---------|--------|-----------|
| **Sentinel** | `bitcoincash:qpxwerqqyn6jgc98fke2d3yj85rmw38ck5ltc6hrmh` | 0.0001 BCH (10,000 sat) | ✅ 1 UTXO |
| **Herald** | `bitcoincash:qp9wmqtrxa0x426mqp9xsck9xggeqj3unv95pmu0hv` | 0.0001 BCH (10,000 sat) | ✅ 1 UTXO |
| **Salesman** | `bitcoincash:qqyujtyqrd25yrml43jjcjwvaat93hsc3sdn4qtgh2` | 0.0001 BCH (10,000 sat) | ✅ 1 UTXO |

All 3 agent wallets verified via `bitcash.network.NetworkAPI.get_unspent()` — each holds exactly 10,000 satoshis (0.0001 BCH).

---

## Files Changed

- `agentvault/wallet.py` — UTXO locking + `send_many()` method
  - Added: `import time`
  - Added: `UTXO_LOCK_TTL = 60` module constant
  - Added: `self._pending_utxos` instance dict in `__init__`
  - Added: `_expire_utxo_locks()`, `_lock_utxos()`, `_filter_unlocked_utxos()`, `unlock_utxos()` methods
  - Modified: `send()`, `mint_nft()`, `send_token()` — now use UTXO locking
  - Added: `send_many()` — new multi-output send method

---

## Issues Encountered

None. The implementation worked cleanly on first broadcast. Transaction confirmed in mempool immediately after broadcast.
