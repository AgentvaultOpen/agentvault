"""
test_testnet_live.py — Live testnet integration tests.

These tests require:
1. Network connection to BCH testnet
2. A funded testnet wallet (run faucet first)

Run with:
    AV_PASSPHRASE=<your-testnet-passphrase> python3 -m pytest tests/test_testnet_live.py -v -s

These are NOT run in the standard test suite (requires network + funds).
Mark: @pytest.mark.live
"""

import os
import time
import pytest

TESTNET_WALLET_DIR = os.path.expanduser("~/.agentvault-testnet")

# Passphrase is read from environment — never hardcoded.
# Set before running: export AV_PASSPHRASE="your-testnet-passphrase"
TESTNET_PASSPHRASE = os.environ.get("AV_PASSPHRASE", "")

# A second testnet address to send to (Electron Cash generated — for interop testing)
SECOND_ADDRESS = "bchtest:qzpvq9l9lzxf4v8n8ka6l7yj7q4d4wc8jys4p7sxy"  # placeholder


@pytest.fixture(scope="module")
def wallet():
    os.environ["AV_PASSPHRASE"] = TESTNET_PASSPHRASE
    from agentvault.wallet import Wallet
    return Wallet.load(TESTNET_WALLET_DIR, testnet=True)


# ── Stage 1: Basic Network Tests ──────────────────────────────────────────────

class TestStage1Network:

    def test_wallet_connects_to_network(self, wallet):
        """Can we fetch balance without error?"""
        result = wallet.balance()
        assert result is not None
        assert "bch" in result
        print(f"\n✅ Connected. Balance: {result['bch']} tBCH")

    def test_wallet_has_testnet_funds(self, wallet):
        """Wallet has been funded by faucet."""
        result = wallet.balance()
        assert result["bch"] > 0, (
            f"Wallet has no funds! Fund it at: https://tbch.googol.cash\n"
            f"Address: {wallet.address}"
        )
        print(f"\n✅ Funded: {result['bch']} tBCH ({result['bch_satoshis']:,} satoshis)")

    def test_address_is_correct_format(self, wallet):
        assert wallet.address.startswith("bchtest:")
        print(f"\n✅ Address: {wallet.address}")


# ── Stage 1: Send/Receive ─────────────────────────────────────────────────────

class TestStage1SendReceive:

    def test_send_to_fresh_address_self(self, wallet):
        """Send to a fresh address derived from the same wallet (self-send)."""
        result = wallet.balance()
        if result["bch"] < 0.00001:
            pytest.skip("Insufficient funds for send test")

        fresh = wallet.fresh_address()
        print(f"\n📤 Sending 1000 satoshi to fresh address: {fresh}")
        txid = wallet.send(fresh, 1000, "satoshi")
        assert txid is not None
        assert len(txid) == 64
        print(f"✅ TXID: {txid}")
        print(f"   Explorer: https://tbch.loping.net/tx/{txid}")

        # Log it
        audit = wallet.audit_log(action="send", limit=1)
        assert audit[0]["details"]["txid"] == txid

    def test_audit_records_send(self, wallet):
        """Every send must appear in the audit log."""
        sends = wallet.audit_log(action="send")
        assert len(sends) >= 1
        for s in sends:
            assert "txid" in s["details"]
            assert s["details"]["status"] == "broadcast"
        print(f"\n✅ Audit log has {len(sends)} send(s)")

    def test_audit_integrity_after_send(self, wallet):
        """Audit log must remain valid after real transactions."""
        valid, err = wallet.verify_audit()
        assert valid is True, f"Audit chain broken: {err}"
        print(f"\n✅ Audit chain intact after real transactions")


# ── Stage 2: CashTokens ───────────────────────────────────────────────────────

class TestStage2CashTokens:

    def test_mint_immutable_nft(self, wallet):
        """Mint an immutable NFT on testnet."""
        result = wallet.balance()
        if result["bch"] < 0.00005:
            pytest.skip("Insufficient funds for NFT mint")

        commitment = b"agentvault-test-nft-001"
        print(f"\n🎨 Minting immutable NFT with commitment: {commitment}")
        txid = wallet.mint_nft(commitment, capability="none")
        assert txid is not None
        assert len(txid) == 64
        print(f"✅ NFT minted! TXID: {txid}")
        print(f"   Explorer: https://tbch.loping.net/tx/{txid}")

    def test_mint_mutable_nft(self, wallet):
        """Mint a mutable NFT — this is the type used for agent identity."""
        result = wallet.balance()
        if result["bch"] < 0.00005:
            pytest.skip("Insufficient funds")

        commitment = b"agent-erin-identity-testnet-v1"
        print(f"\n🆔 Minting mutable NFT (agent identity type):")
        print(f"   Commitment: {commitment.decode()}")
        txid = wallet.mint_nft(commitment, capability="mutable")
        assert txid is not None
        print(f"✅ Identity-type NFT minted! TXID: {txid}")
        print(f"   Explorer: https://tbch.loping.net/tx/{txid}")

    def test_mint_minting_nft(self, wallet):
        """Mint a 'minting' NFT — can create more of the same category."""
        result = wallet.balance()
        if result["bch"] < 0.00005:
            pytest.skip("Insufficient funds")

        commitment = b"genesis-token-agentvault"
        print(f"\n🏭 Minting 'minting' NFT (can create more of same category):")
        txid = wallet.mint_nft(commitment, capability="minting")
        assert txid is not None
        print(f"✅ Minting NFT created! TXID: {txid}")

    def test_commitment_preserved_on_chain(self, wallet):
        """After minting, the NFT commitment should be readable from the blockchain."""
        # This test verifies UTXO contains correct commitment data
        # Full implementation requires reading UTXO token data from explorer
        # For now: verify the mint went into audit log correctly
        mints = wallet.audit_log(action="mint_nft")
        assert len(mints) >= 1
        for m in mints:
            assert "commitment_hex" in m["details"]
            assert m["details"]["status"] == "broadcast"
        print(f"\n✅ {len(mints)} NFT mint(s) in audit log")


# ── Stage 2: Interoperability ─────────────────────────────────────────────────

class TestStage2Interop:

    def test_mnemonic_imports_to_electron_cash(self, wallet):
        """
        MANUAL TEST — Cannot be automated.

        Instructions:
        1. Open Electron Cash
        2. File → New/Restore → Standard wallet → "I already have a seed"
        3. Enter the mnemonic from ~/.agentvault-testnet/keystore.json
        4. Check "BIP39 seed" option
        5. Derivation path: m/44'/145'/0'/0
        6. Verify the FIRST address matches AgentVault's primary address

        Expected address: bchtest:qqwheje003t3gt2rg9zae7hj8mm2hgu80u2t6j6dlt

        If addresses match → BIP-44 interoperability CONFIRMED ✅
        """
        print(f"\n📋 MANUAL INTEROP TEST")
        print(f"   Import this wallet's mnemonic into Electron Cash as BIP-39/BIP-44")
        print(f"   Expected address (index 0): {wallet.address}")
        print(f"   If Electron Cash shows the same address → PASS")
        pytest.skip("Manual test - run in Electron Cash")


# ── Stage 3: Edge Cases ───────────────────────────────────────────────────────

class TestStage3EdgeCases:

    def test_send_with_insufficient_funds_raises(self, wallet):
        """Sending more than balance should fail cleanly, not crash."""
        result = wallet.balance()
        too_much = result["bch"] + 100.0  # Way more than we have
        with pytest.raises(Exception):
            wallet.send(wallet.address, too_much, "bch")
        print(f"\n✅ Insufficient funds handled cleanly")

    def test_invalid_address_raises(self, wallet):
        """Sending to an invalid address should fail cleanly."""
        with pytest.raises(Exception):
            wallet.send("not-a-valid-address", 1000, "satoshi")
        print(f"\n✅ Invalid address rejected cleanly")

    def test_commitment_too_long_raises(self, wallet):
        """NFT commitment over 40 bytes must be rejected before broadcast."""
        from agentvault.wallet import Wallet
        with pytest.raises(ValueError, match="40 bytes"):
            wallet.mint_nft(b"x" * 41, capability="none")
        print(f"\n✅ Oversized commitment rejected cleanly")

    def test_audit_valid_after_failed_transaction(self, wallet):
        """Failed transactions must not corrupt the audit log."""
        try:
            wallet.send("bad-address", 999999, "bch")
        except Exception:
            pass
        valid, err = wallet.verify_audit()
        assert valid is True
        print(f"\n✅ Audit log intact after failed transaction")
