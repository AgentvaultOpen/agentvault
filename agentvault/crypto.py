"""
crypto.py — HD key derivation, encryption, and signing primitives.

Security-critical module. Every change here requires careful review.
Built on BIP-39 (mnemonic) and BIP-44 (HD derivation) standards.
Encryption: AES-256-GCM with random nonce, passphrase via PBKDF2-HMAC-SHA256.
"""

import os
import json
import hashlib
import hmac
import struct
from typing import Tuple

from mnemonic import Mnemonic
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from bitcash import Key
from bitcash.crypto import ECPrivateKey


# ── Constants ─────────────────────────────────────────────────────────────────

PBKDF2_ITERATIONS = 600_000   # OWASP 2023 recommendation for PBKDF2-SHA256
SALT_SIZE         = 32         # bytes
NONCE_SIZE        = 12         # bytes (AES-GCM standard)
KEY_SIZE          = 32         # bytes (AES-256)

# BIP-44 coin type for BCH: m/44'/145'/account'/change/index
BCH_COIN_TYPE = 145


# ── Mnemonic Generation ────────────────────────────────────────────────────────

def generate_mnemonic(strength: int = 256) -> str:
    """
    Generate a BIP-39 mnemonic phrase.
    strength=128 → 12 words, strength=256 → 24 words.
    Default: 24 words (maximum entropy).
    """
    mnemo = Mnemonic("english")
    return mnemo.generate(strength=strength)


def validate_mnemonic(phrase: str) -> bool:
    """Return True if the mnemonic phrase is valid BIP-39."""
    mnemo = Mnemonic("english")
    return mnemo.check(phrase)


def mnemonic_to_seed(phrase: str, passphrase: str = "") -> bytes:
    """Derive 64-byte BIP-39 seed from mnemonic + optional passphrase."""
    mnemo = Mnemonic("english")
    return mnemo.to_seed(phrase, passphrase)


# ── Simplified HD Derivation ──────────────────────────────────────────────────
# We implement a lightweight BIP-32/44 derivation using HMAC-SHA512.
# This derives deterministic keys from the master seed without a full HD lib.

def _hmac_sha512(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha512).digest()


def derive_master_key(seed: bytes) -> Tuple[bytes, bytes]:
    """
    BIP-32 master key derivation.
    Returns (master_private_key_bytes, master_chain_code).
    """
    I = _hmac_sha512(b"Bitcoin seed", seed)
    return I[:32], I[32:]


def derive_child_key(parent_key: bytes, parent_chain: bytes,
                     index: int, hardened: bool = False) -> Tuple[bytes, bytes]:
    """
    BIP-32 child key derivation (private → private).
    Hardened derivation uses index + 0x80000000.
    """
    if hardened:
        index = index + 0x80000000
        data = b'\x00' + parent_key + struct.pack('>I', index)
    else:
        # Get compressed public key from private key
        pub = _private_to_public_compressed(parent_key)
        data = pub + struct.pack('>I', index)

    I = _hmac_sha512(parent_chain, data)
    child_key_int = (int.from_bytes(I[:32], 'big') +
                     int.from_bytes(parent_key, 'big')) % _curve_order()
    child_key = child_key_int.to_bytes(32, 'big')
    child_chain = I[32:]
    return child_key, child_chain


def _curve_order() -> int:
    """secp256k1 curve order n."""
    return 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def _private_to_public_compressed(private_key_bytes: bytes) -> bytes:
    """Derive compressed public key from private key bytes."""
    import coincurve
    key = coincurve.PrivateKey(private_key_bytes)
    return key.public_key.format(compressed=True)


def derive_bip44_key(seed: bytes, account: int = 0,
                     change: int = 0, index: int = 0) -> bytes:
    """
    Derive a BCH private key via BIP-44 path:
    m/44'/145'/{account}'/{change}/{index}

    Returns raw 32-byte private key.
    """
    master_key, master_chain = derive_master_key(seed)

    # m/44' (purpose, hardened)
    k, c = derive_child_key(master_key, master_chain, 44, hardened=True)
    # m/44'/145' (coin type BCH, hardened)
    k, c = derive_child_key(k, c, BCH_COIN_TYPE, hardened=True)
    # m/44'/145'/{account}' (account, hardened)
    k, c = derive_child_key(k, c, account, hardened=True)
    # m/44'/145'/{account}'/{change} (not hardened)
    k, c = derive_child_key(k, c, change, hardened=False)
    # m/44'/145'/{account}'/{change}/{index} (not hardened)
    k, c = derive_child_key(k, c, index, hardened=False)

    return k


def private_key_to_wif(private_key_bytes: bytes, mainnet: bool = True) -> str:
    """Convert raw private key bytes to WIF (Wallet Import Format)."""
    import base58
    prefix = b'\x80' if mainnet else b'\xef'
    key_with_prefix = prefix + private_key_bytes + b'\x01'  # compressed
    checksum = hashlib.sha256(hashlib.sha256(key_with_prefix).digest()).digest()[:4]
    return base58.b58encode(key_with_prefix + checksum).decode()


def private_key_bytes_to_bitcash_key(private_key_bytes: bytes,
                                      testnet: bool = False) -> Key:
    """Create a bitcash Key object from raw private key bytes."""
    import coincurve
    # Convert to WIF and import
    prefix = b'\xef' if testnet else b'\x80'
    key_with_prefix = prefix + private_key_bytes + b'\x01'
    checksum = hashlib.sha256(
        hashlib.sha256(key_with_prefix).digest()
    ).digest()[:4]
    import base58
    wif = base58.b58encode(key_with_prefix + checksum).decode()
    if testnet:
        from bitcash import PrivateKeyTestnet
        return PrivateKeyTestnet(wif)
    return Key(wif)


# ── Encryption / Decryption ───────────────────────────────────────────────────

def derive_encryption_key(passphrase: str, salt: bytes) -> bytes:
    """
    Derive a 256-bit encryption key from passphrase using PBKDF2-HMAC-SHA256.
    Uses 600,000 iterations per OWASP 2023 recommendation.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_SIZE,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(passphrase.encode('utf-8'))


def encrypt_data(plaintext: bytes, passphrase: str) -> bytes:
    """
    Encrypt data with AES-256-GCM.
    Output format: salt (32B) + nonce (12B) + ciphertext + tag (16B)
    """
    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    key = derive_encryption_key(passphrase, salt)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return salt + nonce + ciphertext


def decrypt_data(ciphertext_blob: bytes, passphrase: str) -> bytes:
    """
    Decrypt AES-256-GCM encrypted data.
    Raises ValueError on authentication failure (wrong passphrase or tampered).
    """
    salt = ciphertext_blob[:SALT_SIZE]
    nonce = ciphertext_blob[SALT_SIZE:SALT_SIZE + NONCE_SIZE]
    ciphertext = ciphertext_blob[SALT_SIZE + NONCE_SIZE:]
    key = derive_encryption_key(passphrase, salt)
    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(nonce, ciphertext, None)
    except Exception:
        raise ValueError(
            "Decryption failed — wrong passphrase or corrupted keystore."
        )
