"""
Tests for crypto.py — the most security-critical module.

Every cryptographic operation must be verified:
- Mnemonic generation and validation
- Seed derivation
- HD key derivation (BIP-44)
- Encryption/decryption (AES-256-GCM)
- Edge cases and failure modes
"""

import os
import pytest
from agentvault.crypto import (
    generate_mnemonic, validate_mnemonic, mnemonic_to_seed,
    derive_bip44_key, private_key_bytes_to_bitcash_key,
    encrypt_data, decrypt_data,
)


# ── Mnemonic Tests ─────────────────────────────────────────────────────────────

class TestMnemonic:

    def test_generate_24_words(self):
        phrase = generate_mnemonic(strength=256)
        assert len(phrase.split()) == 24

    def test_generate_12_words(self):
        phrase = generate_mnemonic(strength=128)
        assert len(phrase.split()) == 12

    def test_generated_mnemonic_is_valid(self):
        phrase = generate_mnemonic()
        assert validate_mnemonic(phrase) is True

    def test_each_mnemonic_is_unique(self):
        phrases = {generate_mnemonic() for _ in range(10)}
        assert len(phrases) == 10, "Two identical mnemonics generated — RNG failure"

    def test_validate_known_good_mnemonic(self):
        # BIP-39 test vector
        phrase = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
        assert validate_mnemonic(phrase) is True

    def test_validate_invalid_mnemonic(self):
        assert validate_mnemonic("this is not a valid mnemonic phrase at all") is False

    def test_validate_wrong_checksum(self):
        # Valid words but wrong checksum
        assert validate_mnemonic(
            "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon"
        ) is False

    def test_seed_deterministic(self):
        phrase = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
        seed1 = mnemonic_to_seed(phrase)
        seed2 = mnemonic_to_seed(phrase)
        assert seed1 == seed2, "Same mnemonic must produce same seed"

    def test_seed_is_64_bytes(self):
        phrase = generate_mnemonic()
        seed = mnemonic_to_seed(phrase)
        assert len(seed) == 64

    def test_different_mnemonics_produce_different_seeds(self):
        phrase1 = generate_mnemonic()
        phrase2 = generate_mnemonic()
        assert mnemonic_to_seed(phrase1) != mnemonic_to_seed(phrase2)

    def test_passphrase_changes_seed(self):
        phrase = generate_mnemonic()
        seed_no_pass = mnemonic_to_seed(phrase, "")
        seed_with_pass = mnemonic_to_seed(phrase, "my-passphrase")
        assert seed_no_pass != seed_with_pass


# ── HD Key Derivation Tests ────────────────────────────────────────────────────

class TestHDDerivation:

    def test_derive_returns_32_bytes(self):
        phrase = generate_mnemonic()
        seed = mnemonic_to_seed(phrase)
        key = derive_bip44_key(seed)
        assert len(key) == 32

    def test_derivation_is_deterministic(self):
        phrase = generate_mnemonic()
        seed = mnemonic_to_seed(phrase)
        key1 = derive_bip44_key(seed, account=0, change=0, index=0)
        key2 = derive_bip44_key(seed, account=0, change=0, index=0)
        assert key1 == key2

    def test_different_indexes_produce_different_keys(self):
        phrase = generate_mnemonic()
        seed = mnemonic_to_seed(phrase)
        keys = [derive_bip44_key(seed, index=i) for i in range(20)]
        assert len(set(keys)) == 20, "Index derivation produced duplicate keys"

    def test_different_accounts_produce_different_keys(self):
        phrase = generate_mnemonic()
        seed = mnemonic_to_seed(phrase)
        key0 = derive_bip44_key(seed, account=0)
        key1 = derive_bip44_key(seed, account=1)
        assert key0 != key1

    def test_different_seeds_produce_different_keys(self):
        seed1 = mnemonic_to_seed(generate_mnemonic())
        seed2 = mnemonic_to_seed(generate_mnemonic())
        key1 = derive_bip44_key(seed1)
        key2 = derive_bip44_key(seed2)
        assert key1 != key2

    def test_derived_key_produces_valid_bch_address(self):
        phrase = generate_mnemonic()
        seed = mnemonic_to_seed(phrase)
        key_bytes = derive_bip44_key(seed)
        key = private_key_bytes_to_bitcash_key(key_bytes, testnet=True)
        addr = key.address
        assert addr.startswith("bchtest:"), f"Unexpected testnet address format: {addr}"

    def test_fresh_addresses_are_all_unique(self):
        phrase = generate_mnemonic()
        seed = mnemonic_to_seed(phrase)
        addresses = set()
        for i in range(50):
            key_bytes = derive_bip44_key(seed, index=i)
            key = private_key_bytes_to_bitcash_key(key_bytes, testnet=True)
            addresses.add(key.address)
        assert len(addresses) == 50, "Address reuse detected in HD derivation"


# ── Encryption / Decryption Tests ──────────────────────────────────────────────

class TestEncryption:

    def test_encrypt_decrypt_roundtrip(self):
        data = b"this is my secret seed phrase data"
        passphrase = "strong-test-passphrase-2026"
        encrypted = encrypt_data(data, passphrase)
        decrypted = decrypt_data(encrypted, passphrase)
        assert decrypted == data

    def test_wrong_passphrase_raises_valueerror(self):
        data = b"secret data"
        encrypted = encrypt_data(data, "correct-passphrase")
        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_data(encrypted, "wrong-passphrase")

    def test_each_encryption_produces_different_ciphertext(self):
        """AES-GCM uses random nonce — same plaintext always encrypts differently."""
        data = b"same plaintext"
        passphrase = "same-passphrase"
        enc1 = encrypt_data(data, passphrase)
        enc2 = encrypt_data(data, passphrase)
        assert enc1 != enc2, "Encryption must be non-deterministic (random nonce)"

    def test_encrypted_output_is_larger_than_input(self):
        """Output includes salt(32) + nonce(12) + ciphertext + tag(16)."""
        data = b"hello world"
        encrypted = encrypt_data(data, "passphrase")
        assert len(encrypted) >= len(data) + 32 + 12 + 16

    def test_tampered_ciphertext_raises_valueerror(self):
        """AES-GCM authentication tag catches any modification."""
        data = b"important financial data"
        encrypted = bytearray(encrypt_data(data, "passphrase"))
        # Flip a bit in the ciphertext (after salt+nonce)
        encrypted[50] ^= 0xFF
        with pytest.raises(ValueError):
            decrypt_data(bytes(encrypted), "passphrase")

    def test_empty_passphrase_works(self):
        """Edge case: empty passphrase should work (though not recommended)."""
        data = b"test data"
        encrypted = encrypt_data(data, "")
        decrypted = decrypt_data(encrypted, "")
        assert decrypted == data

    def test_large_data_roundtrip(self):
        """Encryption should handle large payloads."""
        data = os.urandom(100_000)
        passphrase = "test-passphrase"
        encrypted = encrypt_data(data, passphrase)
        decrypted = decrypt_data(encrypted, passphrase)
        assert decrypted == data

    def test_unicode_passphrase(self):
        """Passphrase can contain unicode characters."""
        data = b"secret"
        passphrase = "pàssphräse-wïth-ünïcödé"
        encrypted = encrypt_data(data, passphrase)
        decrypted = decrypt_data(encrypted, passphrase)
        assert decrypted == data
