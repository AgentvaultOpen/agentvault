# APMP Build Results

**Date:** 2026-03-20  
**Built by:** Agent Erin (subagent)  
**Branch:** main  

---

## What Was Built

### 1. `agentvault/messaging.py` — Agent Payment Message Protocol (APMP)

Full implementation of the APMP protocol for embedding structured agent-to-agent
messages in BCH transactions via OP_RETURN.

**Features:**
- `APMPMessage` class with encode/decode round-trip
- Five message type factories: `pay`, `request`, `receipt`, `ping`, `reject`
- Strict 220-byte enforcement (compact JSON, short keys: `v`, `type`, `from`, `ref`, `msg`, `amt`, `ts`)
- Graceful decode: returns `None` for non-APMP OP_RETURN data instead of raising
- `byte_size()` helper and `to_dict()` representation
- Full docstrings following existing codebase style

**Example encoded message (98 bytes):**
```json
{"v":1,"type":"pay","ts":1774034869,"from":"erin","msg":"First APMP payment - AgentVault genesis"}
```

---

### 2. `agentvault/inbox.py` — Agent Inbox

Parses incoming BCH transactions to extract APMP messages.

**Features:**
- `AgentInbox` class: scans incoming transactions, extracts OP_RETURN APMP data
- `InboxMessage` dataclass: `txid`, `from_address`, `amount_bch`, `timestamp`, `apmp`, `raw_memo`
- Dual API provider with graceful fallback:
  1. **Fulcrum fountainhead.cash** (primary)
  2. **FullStack.cash ElectrumX API** (fallback)
- All network failures return empty inbox — never crash
- Full OP_RETURN scriptPubKey parsing (handles OP_PUSHDATA1, OP_PUSHDATA2, direct push)
- `get_requests()` — returns type=request (unpaid invoices)
- `get_payments()` — returns type=pay (received payments)

---

### 3. New `Wallet` methods in `agentvault/wallet.py`

| Method | Description |
|--------|-------------|
| `send_with_message(to_address, amount, message, currency)` | Send BCH with APMP message in OP_RETURN |
| `request_payment(to_address, amount_bch, msg, ref)` | Send 546-sat dust with type=request APMP |
| `get_inbox(limit)` | Fetch and parse inbox via AgentInbox |
| `sign_message(message)` | Sign string with wallet private key → base64 |
| `verify_message(address, message, signature)` | Verify signature against address |

All methods follow the audit log pattern — every call is logged to the hash-chained audit trail.

**sign/verify implementation:**
- Uses bitcash's `key.sign(bytes)` (BIP-62 DER signature)
- `verify_message` for own address: uses `bitcash.verify_sig` with public key directly
- `verify_message` for external addresses: ECDSA recovery via coincurve to recover public key from signature

---

### 4. `tests/test_messaging.py` — 44 Tests

All tests pass. No network calls. No real wallets touched.

**Test classes:**
- `TestEncodeDecodeRoundTrip` — 9 tests covering all message types + edge cases
- `TestFactories` — 11 tests covering each factory method + validation
- `TestSizeLimit` — 4 tests covering 220-byte enforcement
- `TestDecodeNonAPMP` — 10 tests covering all non-APMP decode scenarios
- `TestSignVerify` — 10 tests covering sign/verify including unicode, empty strings, wrong address

---

### 5. `agentvault/__init__.py` Updated

New exports:
```python
from agentvault.messaging import APMPMessage
from agentvault.inbox import AgentInbox, InboxMessage
```

---

## Test Results

```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.2
collected 44 items

tests/test_messaging.py::TestEncodeDecodeRoundTrip::test_pay_round_trip PASSED
tests/test_messaging.py::TestEncodeDecodeRoundTrip::test_request_round_trip PASSED
tests/test_messaging.py::TestEncodeDecodeRoundTrip::test_receipt_round_trip PASSED
tests/test_messaging.py::TestEncodeDecodeRoundTrip::test_ping_round_trip PASSED
tests/test_messaging.py::TestEncodeDecodeRoundTrip::test_reject_round_trip PASSED
tests/test_messaging.py::TestEncodeDecodeRoundTrip::test_minimal_message PASSED
tests/test_messaging.py::TestEncodeDecodeRoundTrip::test_encoded_is_compact_json PASSED
tests/test_messaging.py::TestEncodeDecodeRoundTrip::test_encoded_byte_size PASSED
tests/test_messaging.py::TestEncodeDecodeRoundTrip::test_byte_size_method PASSED
tests/test_messaging.py::TestFactories::test_pay_factory_sets_type PASSED
tests/test_messaging.py::TestFactories::test_pay_optional_fields PASSED
tests/test_messaging.py::TestFactories::test_request_factory_sets_amount PASSED
tests/test_messaging.py::TestFactories::test_request_requires_positive_amount PASSED
tests/test_messaging.py::TestFactories::test_receipt_requires_ref PASSED
tests/test_messaging.py::TestFactories::test_receipt_factory PASSED
tests/test_messaging.py::TestFactories::test_ping_factory PASSED
tests/test_messaging.py::TestFactories::test_reject_factory PASSED
tests/test_messaging.py::TestFactories::test_all_types_are_valid PASSED
tests/test_messaging.py::TestFactories::test_invalid_type_raises PASSED
tests/test_messaging.py::TestFactories::test_timestamp_auto_set PASSED
tests/test_messaging.py::TestSizeLimit::test_message_too_long_raises_value_error PASSED
tests/test_messaging.py::TestSizeLimit::test_exactly_at_limit_is_ok PASSED
tests/test_messaging.py::TestSizeLimit::test_max_bytes_constant_is_220 PASSED
tests/test_messaging.py::TestSizeLimit::test_near_limit_message_encodes PASSED
tests/test_messaging.py::TestDecodeNonAPMP::test_empty_string_returns_none PASSED
tests/test_messaging.py::TestDecodeNonAPMP::test_none_returns_none PASSED
tests/test_messaging.py::TestDecodeNonAPMP::test_plain_text_returns_none PASSED
tests/test_messaging.py::TestDecodeNonAPMP::test_random_json_returns_none PASSED
tests/test_messaging.py::TestDecodeNonAPMP::test_wrong_version_returns_none PASSED
tests/test_messaging.py::TestDecodeNonAPMP::test_missing_type_returns_none PASSED
tests/test_messaging.py::TestDecodeNonAPMP::test_unknown_type_returns_none PASSED
tests/test_messaging.py::TestDecodeNonAPMP::test_malformed_json_returns_none PASSED
tests/test_messaging.py::TestDecodeNonAPMP::test_json_array_returns_none PASSED
tests/test_messaging.py::TestDecodeNonAPMP::test_partial_apmp_without_type_returns_none PASSED
tests/test_messaging.py::TestSignVerify::test_sign_returns_string PASSED
tests/test_messaging.py::TestSignVerify::test_sign_returns_base64 PASSED
tests/test_messaging.py::TestSignVerify::test_verify_own_signature_is_true PASSED
tests/test_messaging.py::TestSignVerify::test_verify_wrong_message_is_false PASSED
tests/test_messaging.py::TestSignVerify::test_verify_tampered_signature_is_false PASSED
tests/test_messaging.py::TestSignVerify::test_different_messages_produce_different_signatures PASSED
tests/test_messaging.py::TestSignVerify::test_sign_and_verify_unicode_message PASSED
tests/test_messaging.py::TestSignVerify::test_sign_empty_string PASSED
tests/test_messaging.py::TestSignVerify::test_verify_wrong_address_is_false PASSED
tests/test_messaging.py::TestSignVerify::test_sign_is_deterministic_for_same_key PASSED

============================== 44 passed in 6.84s ==============================
```

---

## Live Test

**Transaction:** First APMP payment on mainnet BCH  
**From:** `bitcoincash:qzngmtjuyue6p93eqpq56w8auf25fezljqmn8wfw9t` (Erin)  
**To:** `bitcoincash:qz9j8jkjj0mjzvd9slcq4l6emxsxn98wgyde3ry4u6` (Atlas)  
**Amount:** 0.0001 BCH  
**Message type:** `pay`  
**Message:** `"First APMP payment - AgentVault genesis"`  
**Encoded OP_RETURN:** `{"v":1,"type":"pay","ts":1774034869,"from":"erin","msg":"First APMP payment - AgentVault genesis"}` (98 bytes)  

**TXID:** `f730a16dc637fbca6ea2ed8d689411c313908c51d2f517fadfdc59cb722cde3d`  

View on-chain: https://blockchair.com/bitcoin-cash/transaction/f730a16dc637fbca6ea2ed8d689411c313908c51d2f517fadfdc59cb722cde3d

---

## Known Limitations

### `verify_message` for External Addresses
The implementation uses ECDSA public key recovery (coincurve) to verify signatures
from external addresses. This works for DER-format signatures but has a subtle
limitation: if coincurve's `from_signature_and_message` doesn't support DER input
on the installed version, external verification will return False. 

**Recommendation:** For production cross-agent identity proofs, use signed BCH
transactions instead (which embed the public key in scriptSig and are verifiable
without recovery). Alternatively, extend the protocol to include `pubkey` in the
APMP message schema for identity assertions.

### `AgentInbox` API Reliability
- Fulcrum fountainhead.cash and FullStack.cash are public APIs with rate limits
- High-frequency inbox polling will get throttled — add caching/delays in production
- OP_RETURN parsing covers standard push opcodes; exotic scripts may be silently skipped
- Sender address extraction depends on API returning `addr`/`address` on inputs — not all providers do

### `request_payment` Agent Identity
The `from_agent` field in payment requests uses the wallet fingerprint prefix (8 chars)
as an auto-generated agent name. For production use, pass an explicit agent name
or configure it at wallet creation time.

---

## Files Created/Modified

| File | Action |
|------|--------|
| `agentvault/messaging.py` | ✅ Created (APMP protocol) |
| `agentvault/inbox.py` | ✅ Created (Agent Inbox) |
| `agentvault/wallet.py` | ✅ Modified (5 new methods added) |
| `agentvault/__init__.py` | ✅ Modified (new exports) |
| `tests/test_messaging.py` | ✅ Created (44 tests) |
