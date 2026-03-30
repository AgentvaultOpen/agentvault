"""
keystore.py — Key storage abstraction and implementations.

The KeyStore abstraction is the most important architectural decision in AgentVault.
By abstracting key storage, we can swap implementations (encrypted file → 1Password →
hardware → Quantumroot) without changing any other part of the system.

Phase 1: EncryptedFileKeyStore (AES-256-GCM, passphrase from env var)
Phase 2: ExternalKeyStore (1Password CLI, HashiCorp Vault)
Phase 4: QuantumrootKeyStore (post-CashVM Quantumroot vault contracts)
"""

import os
import json
import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

from agentvault.crypto import (
    generate_mnemonic, validate_mnemonic, mnemonic_to_seed,
    derive_bip44_key, private_key_bytes_to_bitcash_key,
    encrypt_data, decrypt_data
)

# ── Abstract Base ─────────────────────────────────────────────────────────────

class KeyStore(ABC):
    """
    Abstract key storage interface.
    All implementations must provide these methods.
    Swap implementations without changing wallet core.
    """

    @abstractmethod
    def get_key(self, account: int = 0, change: int = 0,
                index: int = 0, testnet: bool = False):
        """Return a bitcash Key object for the given derivation path."""
        ...

    @abstractmethod
    def get_address(self, account: int = 0, change: int = 0,
                    index: int = 0, testnet: bool = False) -> str:
        """Return the BCH address for the given derivation path."""
        ...

    @abstractmethod
    def get_next_address(self, account: int = 0,
                         testnet: bool = False) -> tuple[str, int]:
        """
        Return the next unused address and its index.
        Enforces address non-reuse (privacy).
        """
        ...

    @property
    @abstractmethod
    def fingerprint(self) -> str:
        """Return a non-sensitive wallet identifier (first address hash)."""
        ...


# ── Encrypted File KeyStore ───────────────────────────────────────────────────

class EncryptedFileKeyStore(KeyStore):
    """
    Tier 1 (Hot) key storage: encrypted file on disk.

    The keystore file contains the encrypted seed phrase.
    The passphrase is NEVER stored on disk — it must come from
    an environment variable (AV_PASSPHRASE) or be passed explicitly.

    Security properties:
    - AES-256-GCM encryption (authenticated encryption)
    - PBKDF2-HMAC-SHA256 key derivation (600,000 iterations)
    - Random salt + nonce per encryption operation
    - Wrong passphrase raises ValueError (fail closed)
    - Seed phrase never written to disk unencrypted
    """

    KEYSTORE_VERSION = 1
    DEFAULT_ENV_VAR  = "AV_PASSPHRASE"

    def __init__(self, keystore_path: str, passphrase: Optional[str] = None):
        """
        Load an existing keystore from disk.

        Args:
            keystore_path: Path to the encrypted keystore file
            passphrase: Decryption passphrase. If None, reads from AV_PASSPHRASE env var.

        Raises:
            FileNotFoundError: If keystore file doesn't exist
            ValueError: If passphrase is wrong or keystore is corrupted
            EnvironmentError: If passphrase not provided and AV_PASSPHRASE not set
        """
        self._path = Path(keystore_path)
        if not self._path.exists():
            raise FileNotFoundError(
                f"Keystore not found: {keystore_path}\n"
                f"Create one with: EncryptedFileKeyStore.create('{keystore_path}')"
            )
        self._passphrase = passphrase or self._get_passphrase_from_env()
        self._seed = self._load_seed()
        self._address_index: dict[tuple, int] = {}  # (account, testnet) → next_index

    @classmethod
    def create(cls, keystore_path: str, passphrase: Optional[str] = None,
               mnemonic: Optional[str] = None,
               word_count: int = 24) -> tuple['EncryptedFileKeyStore', str]:
        """
        Create a new keystore with a fresh or imported mnemonic.

        Args:
            keystore_path: Where to save the encrypted keystore
            passphrase: Encryption passphrase. If None, reads from AV_PASSPHRASE.
            mnemonic: Import existing mnemonic. If None, generates a new one.
            word_count: 12 or 24 words (only used if generating new mnemonic)

        Returns:
            (keystore_instance, mnemonic_phrase)

        NOTE: The mnemonic is encrypted and stored in the keystore permanently.
        It can be retrieved at any time using reveal_mnemonic(passphrase).
        Back it up to offline storage as a recovery option.
        """
        path = Path(keystore_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            raise FileExistsError(
                f"Keystore already exists at {keystore_path}. "
                f"Delete it first if you want to create a new one."
            )

        passphrase = passphrase or cls._get_passphrase_from_env_static()
        strength = 256 if word_count == 24 else 128

        if mnemonic:
            if not validate_mnemonic(mnemonic):
                raise ValueError("Invalid mnemonic phrase.")
            phrase = mnemonic
        else:
            phrase = generate_mnemonic(strength=strength)

        # Encrypt and save
        keystore_data = {
            "version": cls.KEYSTORE_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "word_count": len(phrase.split()),
        }
        # Encrypt the mnemonic
        encrypted_seed = encrypt_data(phrase.encode('utf-8'), passphrase)

        # Save: JSON metadata header + encrypted seed (hex)
        full_data = {
            **keystore_data,
            "encrypted_mnemonic": encrypted_seed.hex()
        }
        path.write_text(json.dumps(full_data, indent=2))

        # Secure the file: owner read/write only
        path.chmod(0o600)

        instance = cls(keystore_path, passphrase=passphrase)
        return instance, phrase

    def _load_seed(self) -> bytes:
        """Decrypt and return the BIP-39 seed bytes."""
        return mnemonic_to_seed(self._decrypt_mnemonic())

    def _decrypt_mnemonic(self) -> str:
        """Decrypt and return the raw mnemonic phrase. Internal use."""
        data = json.loads(self._path.read_text())
        if data.get("version") != self.KEYSTORE_VERSION:
            raise ValueError(
                f"Unsupported keystore version: {data.get('version')}. "
                f"Expected: {self.KEYSTORE_VERSION}"
            )
        encrypted_mnemonic = bytes.fromhex(data["encrypted_mnemonic"])
        phrase = decrypt_data(encrypted_mnemonic, self._passphrase).decode('utf-8')
        if not validate_mnemonic(phrase):
            raise ValueError(
                "Keystore mnemonic is invalid — keystore may be corrupted."
            )
        return phrase

    def reveal_mnemonic(self, passphrase: str) -> str:
        """
        Reveal the wallet's mnemonic phrase.

        Requires passphrase authentication. The mnemonic is stored encrypted
        in the keystore and is always recoverable with the correct passphrase.

        Args:
            passphrase: The wallet's encryption passphrase.

        Returns:
            The 12 or 24 word mnemonic phrase.

        Raises:
            ValueError: If passphrase is incorrect.
        """
        # Authenticate with provided passphrase (may differ from loaded passphrase
        # if called from an external context)
        data = json.loads(self._path.read_text())
        encrypted_mnemonic = bytes.fromhex(data["encrypted_mnemonic"])
        try:
            phrase = decrypt_data(encrypted_mnemonic, passphrase).decode('utf-8')
        except Exception:
            raise ValueError("Incorrect passphrase.")
        if not validate_mnemonic(phrase):
            raise ValueError("Keystore mnemonic is invalid or corrupted.")
        return phrase

    def reveal_private_key(self, passphrase: str,
                           account: int = 0, change: int = 0,
                           index: int = 0, testnet: bool = False) -> str:
        """
        Reveal the WIF private key for a given derivation path.

        Requires passphrase authentication.

        Args:
            passphrase: The wallet's encryption passphrase.
            account, change, index: BIP44 derivation path components.
            testnet: If True, return testnet key.

        Returns:
            WIF-encoded private key string.
        """
        # Re-authenticate
        self.reveal_mnemonic(passphrase)  # raises ValueError if wrong passphrase
        key = self.get_key(account, change, index, testnet)
        return key.to_wif()

    def get_key(self, account: int = 0, change: int = 0,
                index: int = 0, testnet: bool = False):
        """Return a bitcash Key (or PrivateKeyTestnet) for the given path."""
        private_key_bytes = derive_bip44_key(self._seed, account, change, index)
        return private_key_bytes_to_bitcash_key(private_key_bytes, testnet=testnet)

    def get_address(self, account: int = 0, change: int = 0,
                    index: int = 0, testnet: bool = False) -> str:
        """Return the BCH address for the given derivation path."""
        key = self.get_key(account, change, index, testnet)
        return key.address

    def get_next_address(self, account: int = 0,
                         testnet: bool = False) -> tuple[str, int]:
        """
        Return the next unused external address (change=0) and its index.
        Increments the internal counter — each call gives a fresh address.
        This enforces address non-reuse for privacy.
        """
        slot = (account, testnet)
        # Start at index 1: index 0 is always the primary address (wallet.address).
        # Fresh addresses must never collide with the primary receiving address.
        current = self._address_index.get(slot, 1)
        address = self.get_address(account, change=0, index=current, testnet=testnet)
        self._address_index[slot] = current + 1
        return address, current

    @property
    def fingerprint(self) -> str:
        """
        Non-sensitive wallet identifier.
        SHA256 of the first address (account=0, change=0, index=0).
        Safe to log and share — reveals nothing about the seed.
        """
        first_address = self.get_address(0, 0, 0)
        return hashlib.sha256(first_address.encode()).hexdigest()[:16]

    @staticmethod
    def _get_passphrase_from_env_static() -> str:
        passphrase = os.environ.get(EncryptedFileKeyStore.DEFAULT_ENV_VAR)
        if not passphrase:
            raise EnvironmentError(
                f"Passphrase not provided and {EncryptedFileKeyStore.DEFAULT_ENV_VAR} "
                f"environment variable is not set.\n"
                f"Set it with: export AV_PASSPHRASE='your-passphrase'"
            )
        return passphrase

    def _get_passphrase_from_env(self) -> str:
        return self._get_passphrase_from_env_static()
