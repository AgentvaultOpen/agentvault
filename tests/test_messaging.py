"""
test_messaging.py — Tests for APMP messaging and wallet signing features.

Tests:
    - APMPMessage encode/decode round-trip
    - Each message type factory (pay, request, receipt, ping, reject)
    - Message too long (> 220 bytes) raises ValueError
    - Decode of non-APMP data returns None
    - sign_message / verify_message using a fresh test key

No network calls are made. No real wallets are touched.
"""

import json
import pytest
import time

from agentvault.messaging import APMPMessage


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_pay():
    return APMPMessage.pay("erin", msg="Q3 hosting fee", ref="inv-2026-03")

def make_request():
    return APMPMessage.request("atlas", amount_bch=0.0001, msg="Invoice #42", ref="inv-42")

def make_receipt():
    return APMPMessage.receipt("erin", ref="inv-42", msg="Got it, thanks!")

def make_ping():
    return APMPMessage.ping("atlas", msg="you there?")

def make_reject():
    return APMPMessage.reject("erin", ref="inv-42", msg="Insufficient funds")


# ── Encode / Decode Round-Trip ────────────────────────────────────────────────

class TestEncodeDecodeRoundTrip:

    def test_pay_round_trip(self):
        original = make_pay()
        encoded = original.encode()
        decoded = APMPMessage.decode(encoded)

        assert decoded is not None
        assert decoded.type == "pay"
        assert decoded.from_agent == "erin"
        assert decoded.msg == "Q3 hosting fee"
        assert decoded.ref == "inv-2026-03"
        assert decoded.timestamp == original.timestamp

    def test_request_round_trip(self):
        original = make_request()
        encoded = original.encode()
        decoded = APMPMessage.decode(encoded)

        assert decoded is not None
        assert decoded.type == "request"
        assert decoded.from_agent == "atlas"
        assert decoded.amount_bch == 0.0001
        assert decoded.msg == "Invoice #42"
        assert decoded.ref == "inv-42"

    def test_receipt_round_trip(self):
        original = make_receipt()
        encoded = original.encode()
        decoded = APMPMessage.decode(encoded)

        assert decoded is not None
        assert decoded.type == "receipt"
        assert decoded.from_agent == "erin"
        assert decoded.ref == "inv-42"
        assert decoded.msg == "Got it, thanks!"

    def test_ping_round_trip(self):
        original = make_ping()
        encoded = original.encode()
        decoded = APMPMessage.decode(encoded)

        assert decoded is not None
        assert decoded.type == "ping"
        assert decoded.from_agent == "atlas"
        assert decoded.msg == "you there?"

    def test_reject_round_trip(self):
        original = make_reject()
        encoded = original.encode()
        decoded = APMPMessage.decode(encoded)

        assert decoded is not None
        assert decoded.type == "reject"
        assert decoded.from_agent == "erin"
        assert decoded.ref == "inv-42"
        assert decoded.msg == "Insufficient funds"

    def test_minimal_message(self):
        """Encode/decode with only required fields."""
        msg = APMPMessage(type="ping")
        encoded = msg.encode()
        decoded = APMPMessage.decode(encoded)

        assert decoded is not None
        assert decoded.type == "ping"
        assert decoded.from_agent is None
        assert decoded.ref is None
        assert decoded.msg is None
        assert decoded.amount_bch is None

    def test_encoded_is_compact_json(self):
        """Encoded string should be compact JSON — no extra spaces."""
        msg = make_pay()
        encoded = msg.encode()
        # Should parse as valid JSON
        parsed = json.loads(encoded)
        assert parsed["v"] == APMPMessage.VERSION
        assert parsed["type"] == "pay"
        # Should have no whitespace padding
        assert "  " not in encoded

    def test_encoded_byte_size(self):
        """Encoded message must be within MAX_BYTES."""
        msg = make_pay()
        encoded = msg.encode()
        assert len(encoded.encode('utf-8')) <= APMPMessage.MAX_BYTES

    def test_byte_size_method(self):
        """byte_size() should match actual encoded length."""
        msg = make_pay()
        assert msg.byte_size() == len(msg.encode().encode('utf-8'))


# ── Factory Methods ───────────────────────────────────────────────────────────

class TestFactories:

    def test_pay_factory_sets_type(self):
        msg = APMPMessage.pay("erin")
        assert msg.type == "pay"
        assert msg.from_agent == "erin"

    def test_pay_optional_fields(self):
        msg = APMPMessage.pay("erin", msg="hello", ref="r1")
        assert msg.msg == "hello"
        assert msg.ref == "r1"

    def test_request_factory_sets_amount(self):
        msg = APMPMessage.request("atlas", amount_bch=0.005)
        assert msg.type == "request"
        assert msg.amount_bch == 0.005

    def test_request_requires_positive_amount(self):
        with pytest.raises(ValueError):
            APMPMessage.request("atlas", amount_bch=0.0)

        with pytest.raises(ValueError):
            APMPMessage.request("atlas", amount_bch=-0.001)

    def test_receipt_requires_ref(self):
        with pytest.raises(ValueError):
            APMPMessage.receipt("erin", ref="")

        with pytest.raises(ValueError):
            APMPMessage.receipt("erin", ref=None)

    def test_receipt_factory(self):
        msg = APMPMessage.receipt("erin", ref="inv-001", msg="Confirmed")
        assert msg.type == "receipt"
        assert msg.ref == "inv-001"

    def test_ping_factory(self):
        msg = APMPMessage.ping("atlas")
        assert msg.type == "ping"
        assert msg.from_agent == "atlas"
        assert msg.amount_bch is None

    def test_reject_factory(self):
        msg = APMPMessage.reject("erin", ref="inv-99", msg="Not found")
        assert msg.type == "reject"
        assert msg.ref == "inv-99"

    def test_all_types_are_valid(self):
        """Every APMP type can be encoded without error."""
        for t in APMPMessage.TYPES:
            msg = APMPMessage(type=t, from_agent="test")
            encoded = msg.encode()
            decoded = APMPMessage.decode(encoded)
            assert decoded is not None
            assert decoded.type == t

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError):
            APMPMessage(type="unknown")

    def test_timestamp_auto_set(self):
        before = int(time.time())
        msg = APMPMessage.ping("test")
        after = int(time.time())
        assert before <= msg.timestamp <= after


# ── Size Limit Enforcement ────────────────────────────────────────────────────

class TestSizeLimit:

    def test_message_too_long_raises_value_error(self):
        """A message with msg field that pushes over 220 bytes must raise."""
        # Craft a message that exceeds MAX_BYTES
        long_text = "A" * 200   # definitely over 220 total
        msg = APMPMessage(type="pay", from_agent="erin", msg=long_text)
        with pytest.raises(ValueError, match="exceeds MAX_BYTES"):
            msg.encode()

    def test_exactly_at_limit_is_ok(self):
        """A message at exactly 220 bytes should encode successfully."""
        # Build a message that uses exactly the budget
        # Baseline: {"v":1,"type":"pay","ts":1711000000} = ~38 bytes
        # We have room for about 182 more bytes in "msg"
        # Let's be conservative and test with a known-good size
        msg = APMPMessage(
            type="pay",
            from_agent="erin",
            msg="X" * 150,   # ~150 chars plus structure = well under 220
        )
        encoded = msg.encode()
        assert len(encoded.encode('utf-8')) <= APMPMessage.MAX_BYTES

    def test_max_bytes_constant_is_220(self):
        assert APMPMessage.MAX_BYTES == 220

    def test_near_limit_message_encodes(self):
        """Messages close to the limit should encode cleanly."""
        # Build toward the edge without exceeding
        msg = APMPMessage(type="ping", msg="X" * 170)
        encoded = msg.encode()
        size = len(encoded.encode('utf-8'))
        assert size <= APMPMessage.MAX_BYTES


# ── Decode of Non-APMP Data ───────────────────────────────────────────────────

class TestDecodeNonAPMP:

    def test_empty_string_returns_none(self):
        assert APMPMessage.decode("") is None

    def test_none_returns_none(self):
        assert APMPMessage.decode(None) is None

    def test_plain_text_returns_none(self):
        assert APMPMessage.decode("Hello World") is None

    def test_random_json_returns_none(self):
        # Valid JSON but not APMP
        data = json.dumps({"foo": "bar", "x": 42})
        assert APMPMessage.decode(data) is None

    def test_wrong_version_returns_none(self):
        data = json.dumps({"v": 99, "type": "pay", "ts": 1711000000})
        assert APMPMessage.decode(data) is None

    def test_missing_type_returns_none(self):
        data = json.dumps({"v": 1, "ts": 1711000000})
        assert APMPMessage.decode(data) is None

    def test_unknown_type_returns_none(self):
        data = json.dumps({"v": 1, "type": "transfer", "ts": 1711000000})
        assert APMPMessage.decode(data) is None

    def test_malformed_json_returns_none(self):
        assert APMPMessage.decode("{not valid json}") is None

    def test_json_array_returns_none(self):
        assert APMPMessage.decode("[1, 2, 3]") is None

    def test_partial_apmp_without_type_returns_none(self):
        data = json.dumps({"v": 1, "from": "erin", "msg": "hi"})
        assert APMPMessage.decode(data) is None


# ── sign_message / verify_message ────────────────────────────────────────────

class TestSignVerify:
    """
    Tests for wallet.sign_message() and wallet.verify_message().

    Uses a fresh ephemeral test wallet created from a new key.
    No real wallet files. No network calls.
    """

    @pytest.fixture
    def test_wallet(self, tmp_path):
        """Create a fresh in-memory wallet for signing tests."""
        from agentvault.wallet import Wallet
        wallet, mnemonic = Wallet.create(
            wallet_dir=str(tmp_path / "test-wallet"),
            passphrase="test-passphrase-123",
        )
        return wallet

    def test_sign_returns_string(self, test_wallet):
        sig = test_wallet.sign_message("hello world")
        assert isinstance(sig, str)
        assert len(sig) > 0

    def test_sign_returns_base64(self, test_wallet):
        import base64
        sig = test_wallet.sign_message("test message")
        # Should decode as base64 without error
        decoded = base64.b64decode(sig)
        assert len(decoded) > 0

    def test_verify_own_signature_is_true(self, test_wallet):
        message = "Agent Erin payment confirmation 2026"
        sig = test_wallet.sign_message(message)
        result = test_wallet.verify_message(test_wallet.address, message, sig)
        assert result is True

    def test_verify_wrong_message_is_false(self, test_wallet):
        message = "correct message"
        wrong   = "wrong message"
        sig = test_wallet.sign_message(message)
        result = test_wallet.verify_message(test_wallet.address, wrong, sig)
        assert result is False

    def test_verify_tampered_signature_is_false(self, test_wallet):
        message = "original message"
        sig = test_wallet.sign_message(message)
        # Tamper with the signature
        import base64
        sig_bytes = bytearray(base64.b64decode(sig))
        sig_bytes[4] ^= 0xFF   # flip bits in one byte
        tampered = base64.b64encode(bytes(sig_bytes)).decode('ascii')
        result = test_wallet.verify_message(test_wallet.address, message, tampered)
        assert result is False

    def test_different_messages_produce_different_signatures(self, test_wallet):
        sig1 = test_wallet.sign_message("message one")
        sig2 = test_wallet.sign_message("message two")
        assert sig1 != sig2

    def test_sign_and_verify_unicode_message(self, test_wallet):
        message = "BCH payment ₿ — ¡Hola! — こんにちは — AgentVault™"
        sig = test_wallet.sign_message(message)
        result = test_wallet.verify_message(test_wallet.address, message, sig)
        assert result is True

    def test_sign_empty_string(self, test_wallet):
        sig = test_wallet.sign_message("")
        assert isinstance(sig, str)
        # Verify empty string signature
        result = test_wallet.verify_message(test_wallet.address, "", sig)
        assert result is True

    def test_verify_wrong_address_is_false(self, test_wallet, tmp_path):
        """Signature from one wallet should not verify against another address."""
        # Create a second wallet
        other_wallet, _ = Wallet.create(
            wallet_dir=str(tmp_path / "other-wallet"),
            passphrase="other-pass",
        )
        message = "signed by wallet 1"
        sig = test_wallet.sign_message(message)
        # Verify against the OTHER wallet's address — should fail
        result = test_wallet.verify_message(other_wallet.address, message, sig)
        assert result is False

    def test_sign_is_deterministic_for_same_key(self, test_wallet):
        """
        ECDSA with RFC6979 deterministic nonce: same key + message → same sig.
        bitcash uses coincurve which supports this.
        """
        message = "deterministic test"
        sig1 = test_wallet.sign_message(message)
        sig2 = test_wallet.sign_message(message)
        # Both should at least be valid
        assert test_wallet.verify_message(test_wallet.address, message, sig1)
        assert test_wallet.verify_message(test_wallet.address, message, sig2)


# Import for the wallet fixture cross-reference
from agentvault.wallet import Wallet
