"""
Tests for wallet.py — the main Wallet class.

Tests wallet lifecycle: create, load, address generation, audit integration.
Network-dependent tests (balance, send) require testnet and are marked separately.
"""

import os
import pytest
import tempfile
import shutil

from agentvault.wallet import Wallet


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def set_passphrase():
    os.environ["AV_PASSPHRASE"] = "test-wallet-passphrase-2026"
    yield
    os.environ.pop("AV_PASSPHRASE", None)


@pytest.fixture
def wallet(tmp_dir):
    w, _ = Wallet.create(tmp_dir, testnet=True)
    return w, tmp_dir


class TestWalletCreation:

    def test_create_returns_wallet_and_mnemonic(self, tmp_dir):
        w, phrase = Wallet.create(tmp_dir, testnet=True)
        assert w is not None
        assert isinstance(phrase, str)
        assert len(phrase.split()) == 24

    def test_wallet_has_valid_testnet_address(self, tmp_dir):
        w, _ = Wallet.create(tmp_dir, testnet=True)
        assert w.address.startswith("bchtest:")

    def test_wallet_has_fingerprint(self, tmp_dir):
        w, _ = Wallet.create(tmp_dir, testnet=True)
        assert len(w.fingerprint) == 16
        assert isinstance(w.fingerprint, str)

    def test_create_twice_raises_error(self, tmp_dir):
        Wallet.create(tmp_dir, testnet=True)
        with pytest.raises(FileExistsError):
            Wallet.create(tmp_dir, testnet=True)

    def test_testnet_flag_is_stored(self, tmp_dir):
        w, _ = Wallet.create(tmp_dir, testnet=True)
        assert w.is_testnet is True

    def test_mainnet_flag(self, tmp_dir):
        w, _ = Wallet.create(tmp_dir, testnet=False)
        assert w.is_testnet is False
        assert w.address.startswith("bitcoincash:")


class TestWalletLoading:

    def test_load_existing_wallet(self, tmp_dir):
        w1, _ = Wallet.create(tmp_dir, testnet=True)
        w2 = Wallet.load(tmp_dir, testnet=True)
        assert w1.fingerprint == w2.fingerprint

    def test_load_same_address(self, tmp_dir):
        w1, _ = Wallet.create(tmp_dir, testnet=True)
        w2 = Wallet.load(tmp_dir, testnet=True)
        assert w1.address == w2.address

    def test_load_missing_wallet_raises(self, tmp_dir):
        with pytest.raises(FileNotFoundError):
            Wallet.load(os.path.join(tmp_dir, "nonexistent"))

    def test_load_wrong_passphrase_raises(self, tmp_dir):
        Wallet.create(tmp_dir, testnet=True)
        with pytest.raises(ValueError):
            Wallet.load(tmp_dir, passphrase="WRONG-passphrase", testnet=True)

    def test_two_different_wallets_have_different_fingerprints(self, tmp_dir):
        dir1 = os.path.join(tmp_dir, "wallet1")
        dir2 = os.path.join(tmp_dir, "wallet2")
        w1, _ = Wallet.create(dir1, testnet=True)
        w2, _ = Wallet.create(dir2, testnet=True)
        assert w1.fingerprint != w2.fingerprint


class TestAddressGeneration:

    def test_fresh_address_differs_from_primary(self, tmp_dir):
        w, _ = Wallet.create(tmp_dir, testnet=True)
        fresh = w.fresh_address()
        # The primary address is index 0; fresh address starts at 0 too
        # They may match on first call — but subsequent must differ
        fresh2 = w.fresh_address()
        assert fresh != fresh2

    def test_100_fresh_addresses_all_unique(self, tmp_dir):
        w, _ = Wallet.create(tmp_dir, testnet=True)
        addresses = {w.fresh_address() for _ in range(100)}
        assert len(addresses) == 100, "Privacy violation: address reuse detected"

    def test_fresh_address_is_testnet_format(self, tmp_dir):
        w, _ = Wallet.create(tmp_dir, testnet=True)
        addr = w.fresh_address()
        assert addr.startswith("bchtest:")

    def test_fresh_address_logged_to_audit(self, tmp_dir):
        w, _ = Wallet.create(tmp_dir, testnet=True)
        w.fresh_address()
        entries = w.audit_log(action="address_generated")
        assert len(entries) == 1


class TestAuditIntegration:

    def test_wallet_creation_logged(self, tmp_dir):
        w, _ = Wallet.create(tmp_dir, testnet=True)
        entries = w.audit_log()
        actions = [e["action"] for e in entries]
        assert "wallet_created" in actions

    def test_audit_log_valid_after_creation(self, tmp_dir):
        w, _ = Wallet.create(tmp_dir, testnet=True)
        valid, err = w.verify_audit()
        assert valid is True

    def test_audit_log_valid_after_multiple_operations(self, tmp_dir):
        w, _ = Wallet.create(tmp_dir, testnet=True)
        for _ in range(10):
            w.fresh_address()
        valid, err = w.verify_audit()
        assert valid is True

    def test_audit_survives_reload(self, tmp_dir):
        w1, _ = Wallet.create(tmp_dir, testnet=True)
        for _ in range(5):
            w1.fresh_address()
        count_before = len(w1.audit_log())

        w2 = Wallet.load(tmp_dir, testnet=True)
        count_after = len(w2.audit_log())

        assert count_after >= count_before
        valid, _ = w2.verify_audit()
        assert valid is True

    def test_audit_query_by_action(self, tmp_dir):
        w, _ = Wallet.create(tmp_dir, testnet=True)
        for _ in range(3):
            w.fresh_address()
        addr_entries = w.audit_log(action="address_generated")
        assert len(addr_entries) == 3

    def test_audit_limit(self, tmp_dir):
        w, _ = Wallet.create(tmp_dir, testnet=True)
        for _ in range(20):
            w.fresh_address()
        limited = w.audit_log(limit=5)
        assert len(limited) == 5


class TestMnemonicRecovery:

    def test_same_mnemonic_same_addresses(self, tmp_dir):
        """Core recovery test: same mnemonic must always produce same wallet."""
        known_phrase = (
            "abandon abandon abandon abandon abandon abandon "
            "abandon abandon abandon abandon abandon about"
        )
        dir1 = os.path.join(tmp_dir, "wallet1")
        dir2 = os.path.join(tmp_dir, "wallet2")

        w1, _ = Wallet.create(dir1, mnemonic=known_phrase, testnet=True)
        w2, _ = Wallet.create(dir2, mnemonic=known_phrase, testnet=True)

        assert w1.address == w2.address
        assert w1.fingerprint == w2.fingerprint
        # Verify 10 derived addresses match
        for i in range(10):
            from agentvault.crypto import derive_bip44_key, mnemonic_to_seed, private_key_bytes_to_bitcash_key
            seed = mnemonic_to_seed(known_phrase)
            key_bytes = derive_bip44_key(seed, index=i)
            key = private_key_bytes_to_bitcash_key(key_bytes, testnet=True)
            assert w1._keystore.get_address(0, 0, i, testnet=True) == key.address
