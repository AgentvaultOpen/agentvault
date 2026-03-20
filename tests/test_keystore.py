"""
Tests for keystore.py — key storage and management.

Covers: creation, loading, address derivation, privacy (no address reuse),
error handling, and security boundaries.
"""

import os
import json
import pytest
import tempfile
import shutil

from agentvault.keystore import EncryptedFileKeyStore


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def passphrase():
    return "test-passphrase-agentvault-2026"


@pytest.fixture
def keystore(tmp_dir, passphrase):
    ks, _ = EncryptedFileKeyStore.create(
        os.path.join(tmp_dir, "keystore.json"),
        passphrase=passphrase
    )
    return ks


class TestKeystoreCreation:

    def test_create_generates_keystore_file(self, tmp_dir, passphrase):
        path = os.path.join(tmp_dir, "keystore.json")
        ks, phrase = EncryptedFileKeyStore.create(path, passphrase=passphrase)
        assert os.path.exists(path)

    def test_create_returns_24_word_mnemonic_by_default(self, tmp_dir, passphrase):
        path = os.path.join(tmp_dir, "keystore.json")
        _, phrase = EncryptedFileKeyStore.create(path, passphrase=passphrase)
        assert len(phrase.split()) == 24

    def test_create_12_word_mnemonic(self, tmp_dir, passphrase):
        path = os.path.join(tmp_dir, "keystore.json")
        _, phrase = EncryptedFileKeyStore.create(
            path, passphrase=passphrase, word_count=12
        )
        assert len(phrase.split()) == 12

    def test_keystore_file_permissions_are_600(self, tmp_dir, passphrase):
        path = os.path.join(tmp_dir, "keystore.json")
        EncryptedFileKeyStore.create(path, passphrase=passphrase)
        mode = oct(os.stat(path).st_mode)[-3:]
        assert mode == "600", f"Keystore permissions should be 600, got {mode}"

    def test_keystore_file_contains_no_plaintext_mnemonic(self, tmp_dir, passphrase):
        path = os.path.join(tmp_dir, "keystore.json")
        _, phrase = EncryptedFileKeyStore.create(path, passphrase=passphrase)
        raw = open(path).read()
        for word in phrase.split():
            assert word not in raw, f"Mnemonic word '{word}' found in plaintext keystore!"

    def test_duplicate_create_raises_fileexistserror(self, tmp_dir, passphrase):
        path = os.path.join(tmp_dir, "keystore.json")
        EncryptedFileKeyStore.create(path, passphrase=passphrase)
        with pytest.raises(FileExistsError):
            EncryptedFileKeyStore.create(path, passphrase=passphrase)

    def test_create_with_imported_mnemonic(self, tmp_dir, passphrase):
        known_phrase = (
            "abandon abandon abandon abandon abandon abandon "
            "abandon abandon abandon abandon abandon about"
        )
        path = os.path.join(tmp_dir, "keystore.json")
        ks, returned_phrase = EncryptedFileKeyStore.create(
            path, passphrase=passphrase, mnemonic=known_phrase
        )
        assert returned_phrase == known_phrase

    def test_create_with_invalid_mnemonic_raises(self, tmp_dir, passphrase):
        path = os.path.join(tmp_dir, "keystore.json")
        with pytest.raises(ValueError, match="Invalid mnemonic"):
            EncryptedFileKeyStore.create(
                path, passphrase=passphrase,
                mnemonic="this is not valid at all ever"
            )


class TestKeystoreLoading:

    def test_load_with_correct_passphrase(self, tmp_dir, passphrase):
        path = os.path.join(tmp_dir, "keystore.json")
        ks1, _ = EncryptedFileKeyStore.create(path, passphrase=passphrase)
        ks2 = EncryptedFileKeyStore(path, passphrase=passphrase)
        assert ks1.fingerprint == ks2.fingerprint

    def test_load_wrong_passphrase_raises_valueerror(self, tmp_dir, passphrase):
        path = os.path.join(tmp_dir, "keystore.json")
        EncryptedFileKeyStore.create(path, passphrase=passphrase)
        with pytest.raises(ValueError, match="Decryption failed"):
            EncryptedFileKeyStore(path, passphrase="WRONG-passphrase")

    def test_load_missing_file_raises_filenotfounderror(self, tmp_dir, passphrase):
        path = os.path.join(tmp_dir, "does_not_exist.json")
        with pytest.raises(FileNotFoundError):
            EncryptedFileKeyStore(path, passphrase=passphrase)

    def test_fingerprint_is_deterministic(self, tmp_dir, passphrase):
        path = os.path.join(tmp_dir, "keystore.json")
        ks1, _ = EncryptedFileKeyStore.create(path, passphrase=passphrase)
        ks2 = EncryptedFileKeyStore(path, passphrase=passphrase)
        assert ks1.fingerprint == ks2.fingerprint

    def test_fingerprint_differs_between_wallets(self, tmp_dir, passphrase):
        path1 = os.path.join(tmp_dir, "ks1.json")
        path2 = os.path.join(tmp_dir, "ks2.json")
        ks1, _ = EncryptedFileKeyStore.create(path1, passphrase=passphrase)
        ks2, _ = EncryptedFileKeyStore.create(path2, passphrase=passphrase)
        assert ks1.fingerprint != ks2.fingerprint

    def test_env_var_passphrase(self, tmp_dir):
        os.environ["AV_PASSPHRASE"] = "env-var-passphrase"
        path = os.path.join(tmp_dir, "keystore.json")
        try:
            ks, _ = EncryptedFileKeyStore.create(path)
            ks2 = EncryptedFileKeyStore(path)
            assert ks.fingerprint == ks2.fingerprint
        finally:
            del os.environ["AV_PASSPHRASE"]

    def test_missing_env_var_raises_environmenterror(self, tmp_dir):
        os.environ.pop("AV_PASSPHRASE", None)
        path = os.path.join(tmp_dir, "keystore.json")
        with pytest.raises(EnvironmentError, match="AV_PASSPHRASE"):
            EncryptedFileKeyStore.create(path)


class TestAddressDerivation:

    def test_get_address_returns_cashaddr(self, keystore):
        addr = keystore.get_address(0, 0, 0, testnet=False)
        assert addr.startswith("bitcoincash:"), f"Expected cashaddr, got: {addr}"

    def test_get_address_testnet_returns_bchtest(self, keystore):
        addr = keystore.get_address(0, 0, 0, testnet=True)
        assert addr.startswith("bchtest:"), f"Expected testnet addr, got: {addr}"

    def test_different_indexes_produce_different_addresses(self, keystore):
        addrs = [keystore.get_address(0, 0, i) for i in range(20)]
        assert len(set(addrs)) == 20, "Index derivation produced duplicate addresses"

    def test_different_accounts_produce_different_addresses(self, keystore):
        addr0 = keystore.get_address(account=0, change=0, index=0)
        addr1 = keystore.get_address(account=1, change=0, index=0)
        assert addr0 != addr1

    def test_address_derivation_is_deterministic(self, keystore):
        addr1 = keystore.get_address(0, 0, 5)
        addr2 = keystore.get_address(0, 0, 5)
        assert addr1 == addr2

    def test_get_next_address_increments_each_call(self, keystore):
        """Privacy: get_next_address must return a fresh address each time."""
        addr1, idx1 = keystore.get_next_address()
        addr2, idx2 = keystore.get_next_address()
        addr3, idx3 = keystore.get_next_address()
        assert addr1 != addr2 != addr3
        # Counter starts at 1 — index 0 is reserved for wallet.address (primary)
        assert idx1 == 1
        assert idx2 == 2
        assert idx3 == 3

    def test_fresh_address_never_equals_primary(self, keystore):
        """Fresh addresses must never equal the primary address (index 0)."""
        primary = keystore.get_address(account=0, change=0, index=0)
        for _ in range(10):
            fresh, _ = keystore.get_next_address()
            assert fresh != primary, "fresh_address() returned the primary address — privacy violation"

    def test_50_unique_fresh_addresses(self, keystore):
        """Generate 50 fresh addresses — all must be unique."""
        addresses = set()
        for _ in range(50):
            addr, _ = keystore.get_next_address()
            addresses.add(addr)
        assert len(addresses) == 50, "Address reuse detected — privacy violation"

    def test_same_wallet_same_address_at_same_index(self, tmp_dir, passphrase):
        """Two instances of the same wallet must produce identical addresses."""
        path = os.path.join(tmp_dir, "keystore.json")
        known_phrase = (
            "abandon abandon abandon abandon abandon abandon "
            "abandon abandon abandon abandon abandon about"
        )
        ks1, _ = EncryptedFileKeyStore.create(
            path, passphrase=passphrase, mnemonic=known_phrase
        )
        ks2 = EncryptedFileKeyStore(path, passphrase=passphrase)
        for i in range(10):
            assert ks1.get_address(0, 0, i) == ks2.get_address(0, 0, i)
