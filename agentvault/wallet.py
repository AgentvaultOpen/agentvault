"""
wallet.py — The main Wallet class. The primary interface for all operations.

This is what agents and humans interact with. Everything else is implementation.

Design: Library-first. The Wallet class is the Python API.
The CLI wraps it. The REST API (Phase 2) wraps that.
"""

import os
import time
import base64
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

from bitcash import verify_sig

from agentvault.keystore import KeyStore, EncryptedFileKeyStore
from agentvault.audit import AuditLog
from agentvault.messaging import APMPMessage


# Default paths
DEFAULT_WALLET_DIR   = os.path.expanduser("~/.agentvault")
DEFAULT_KEYSTORE     = os.path.join(DEFAULT_WALLET_DIR, "keystore.json")
DEFAULT_AUDIT_LOG    = os.path.join(DEFAULT_WALLET_DIR, "audit.log")

# UTXO Pool names — privacy-critical separation
POOL_OPERATIONAL = "operational"   # BCH for daily spending — CashFusion eligible
POOL_TOKENS      = "tokens"        # Fungible token holdings
POOL_IDENTITY    = "identity"      # Identity NFT — NEVER mixed, NEVER auto-spent

# UTXO lock expiry (seconds) — locks expire if TX was never broadcast
UTXO_LOCK_TTL = 60


class Wallet:
    """
    AgentVault Wallet — the main interface.

    Usage:
        # Create new wallet
        wallet, mnemonic = Wallet.create("~/.agentvault")

        # Load existing wallet
        wallet = Wallet.load("~/.agentvault")

        # Check balance
        print(wallet.balance())

        # Send BCH
        tx = wallet.send("bitcoincash:qp...", amount=0.001)

        # Send BCH to multiple recipients in one TX (no UTXO conflicts)
        tx = wallet.send_many([
            ("bitcoincash:qp...", 0.001),
            ("bitcoincash:qr...", 0.002),
        ])

        # Mint an NFT
        tx = wallet.mint_nft(commitment=b"my-agent-identity")
    """

    def __init__(self, keystore: KeyStore, audit_log: AuditLog,
                 testnet: bool = False):
        self._keystore = keystore
        self._audit = audit_log
        self._testnet = testnet

        # In-memory UTXO lock table: {(txid, txindex): locked_at_timestamp}
        # Prevents "txn-mempool-conflict" when sending multiple TXs rapidly.
        # Locks auto-expire after UTXO_LOCK_TTL seconds (default 60s).
        self._pending_utxos: dict[tuple, float] = {}

        # Log wallet initialization
        self._audit.log("wallet_init", {
            "fingerprint": keystore.fingerprint,
            "testnet": testnet,
            "version": "0.1.0",
        })

    # ── Factory Methods ────────────────────────────────────────────────────────

    @classmethod
    def create(cls, wallet_dir: str = DEFAULT_WALLET_DIR,
               passphrase: Optional[str] = None,
               mnemonic: Optional[str] = None,
               testnet: bool = False) -> tuple['Wallet', str]:
        """
        Create a new AgentVault wallet.

        Args:
            wallet_dir: Directory to store keystore and audit log
            passphrase: Encryption passphrase (reads AV_PASSPHRASE env var if None)
            mnemonic: Import existing mnemonic (generates new one if None)
            testnet: Use BCH testnet (chipnet/testnet4)

        Returns:
            (wallet_instance, mnemonic_phrase)

        ⚠️  SECURITY: Save the returned mnemonic phrase immediately.
                      It is your only recovery mechanism.
                      Store it in 1Password AND a physical backup.
        """
        wallet_dir = os.path.expanduser(wallet_dir)
        Path(wallet_dir).mkdir(parents=True, exist_ok=True)

        keystore_path = os.path.join(wallet_dir, "keystore.json")
        audit_path    = os.path.join(wallet_dir, "audit.log")

        keystore, phrase = EncryptedFileKeyStore.create(
            keystore_path,
            passphrase=passphrase,
            mnemonic=mnemonic,
        )
        audit_log = AuditLog(audit_path)

        wallet = cls(keystore, audit_log, testnet=testnet)

        audit_log.log("wallet_created", {
            "fingerprint": keystore.fingerprint,
            "testnet": testnet,
            "word_count": len(phrase.split()),
            "note": "Mnemonic shown once — store it immediately.",
        })

        return wallet, phrase

    @classmethod
    def load(cls, wallet_dir: str = DEFAULT_WALLET_DIR,
             passphrase: Optional[str] = None,
             testnet: bool = False) -> 'Wallet':
        """
        Load an existing AgentVault wallet.

        Args:
            wallet_dir: Directory containing keystore.json and audit.log
            passphrase: Decryption passphrase (reads AV_PASSPHRASE env var if None)
            testnet: Use BCH testnet

        Raises:
            FileNotFoundError: If wallet_dir or keystore doesn't exist
            ValueError: If passphrase is wrong
        """
        wallet_dir = os.path.expanduser(wallet_dir)
        keystore_path = os.path.join(wallet_dir, "keystore.json")
        audit_path    = os.path.join(wallet_dir, "audit.log")

        keystore  = EncryptedFileKeyStore(keystore_path, passphrase=passphrase)
        audit_log = AuditLog(audit_path)

        return cls(keystore, audit_log, testnet=testnet)

    # ── UTXO Locking ──────────────────────────────────────────────────────────

    def _expire_utxo_locks(self) -> None:
        """Remove any pending UTXO locks older than UTXO_LOCK_TTL seconds."""
        now = time.monotonic()
        expired = [
            k for k, locked_at in self._pending_utxos.items()
            if (now - locked_at) >= UTXO_LOCK_TTL
        ]
        for k in expired:
            del self._pending_utxos[k]

    def _lock_utxos(self, unspents) -> None:
        """Mark a list of Unspent objects as pending (in-flight)."""
        now = time.monotonic()
        for u in unspents:
            self._pending_utxos[(u.txid, u.txindex)] = now

    def _filter_unlocked_utxos(self, unspents) -> list:
        """
        Return only UTXOs not currently locked as pending.
        Cleans up expired locks first.
        """
        self._expire_utxo_locks()
        return [
            u for u in unspents
            if (u.txid, u.txindex) not in self._pending_utxos
        ]

    def unlock_utxos(self) -> int:
        """
        Manually release all pending UTXO locks (e.g. after confirmed block).
        Returns number of locks released.
        """
        count = len(self._pending_utxos)
        self._pending_utxos.clear()
        return count

    # ── Addresses ─────────────────────────────────────────────────────────────

    @property
    def address(self) -> str:
        """Primary receiving address (account 0, change 0, index 0)."""
        return self._keystore.get_address(0, 0, 0, self._testnet)

    def fresh_address(self, account: int = 0) -> str:
        """
        Generate a fresh, unused receiving address.
        Privacy: Never reuse addresses. Each call returns a new one.
        """
        address, index = self._keystore.get_next_address(account, self._testnet)
        self._audit.log("address_generated", {
            "address": address,
            "account": account,
            "index": index,
        })
        return address

    # ── Balance ───────────────────────────────────────────────────────────────

    def balance(self) -> dict:
        """
        Return current BCH balance and token holdings.

        Returns dict with:
            - bch: BCH balance as float
            - bch_satoshis: BCH balance in satoshis
            - tokens: list of token holdings
            - address: primary address
            - testnet: whether this is testnet
        """
        key = self._keystore.get_key(0, 0, 0, self._testnet)

        try:
            key.get_unspents()
            bch_balance = key.balance_as('bch')

            self._audit.log("balance_check", {
                "address": key.address,
                "bch": float(bch_balance),
                "testnet": self._testnet,
            })

            return {
                "bch": float(bch_balance),
                "bch_satoshis": key.balance,
                "address": key.address,
                "testnet": self._testnet,
                "tokens": [],  # Phase 1: token enumeration in next iteration
            }
        except Exception as e:
            self._audit.log("balance_check_failed", {
                "error": str(e),
                "address": key.address,
            })
            raise

    # ── Send BCH ──────────────────────────────────────────────────────────────

    def send(self, to_address: str, amount: float,
             currency: str = "bch",
             memo: Optional[str] = None) -> str:
        """
        Send BCH to an address.

        Args:
            to_address: Recipient BCH address (cashaddr or legacy format)
            amount: Amount to send
            currency: 'bch', 'usd', 'satoshi'
            memo: Optional memo (not broadcast on-chain, logged internally)

        Returns:
            Transaction ID (txid)

        Note: All transactions pass through the audit log.
              Policy engine (Phase 2) will be added here.
              Uses UTXO locking to prevent mempool-conflict on rapid sends.
        """
        key = self._keystore.get_key(0, 0, 0, self._testnet)

        details = {
            "to": to_address,
            "amount": amount,
            "currency": currency,
            "testnet": self._testnet,
        }
        if memo:
            details["memo"] = memo

        try:
            key.get_unspents()
            available = self._filter_unlocked_utxos(key.unspents)

            if not available:
                raise RuntimeError(
                    "No unlocked UTXOs available — all UTXOs are pending in "
                    "unconfirmed transactions. Wait ~60s or call unlock_utxos()."
                )

            txid = key.send([(to_address, amount, currency)], unspents=available)

            # Lock the UTXOs we just spent so rapid subsequent sends skip them
            self._lock_utxos(available)

            details["txid"] = txid
            details["status"] = "broadcast"
            details["utxos_used"] = len(available)
            self._audit.log("send", details)

            return txid

        except Exception as e:
            details["error"] = str(e)
            details["status"] = "failed"
            self._audit.log("send_failed", details)
            raise

    # ── Multi-Output Send ─────────────────────────────────────────────────────

    def send_many(self, recipients: list[tuple[str, float]],
                  memo: Optional[str] = None) -> str:
        """
        Send BCH to multiple recipients in a single transaction.

        Builds ONE transaction with multiple outputs — efficient, atomic,
        and avoids UTXO conflicts entirely (no rapid-send race condition).

        Args:
            recipients: List of (address, amount_bch) tuples.
                        Example: [("bitcoincash:qp...", 0.001), ...]
            memo: Optional internal memo (logged, not broadcast on-chain)

        Returns:
            Single TXID covering all outputs.

        Example:
            txid = wallet.send_many([
                ("bitcoincash:qpxwer...", 0.0001),
                ("bitcoincash:qp9wmq...", 0.0001),
                ("bitcoincash:qqyujt...", 0.0001),
            ])
        """
        if not recipients:
            raise ValueError("recipients list cannot be empty.")

        key = self._keystore.get_key(0, 0, 0, self._testnet)

        total_bch = sum(amt for _, amt in recipients)
        details = {
            "type": "send_many",
            "recipient_count": len(recipients),
            "total_bch": total_bch,
            "recipients": [{"to": addr, "amount_bch": amt} for addr, amt in recipients],
            "testnet": self._testnet,
        }
        if memo:
            details["memo"] = memo

        try:
            key.get_unspents()
            available = self._filter_unlocked_utxos(key.unspents)

            if not available:
                raise RuntimeError(
                    "No unlocked UTXOs available — all UTXOs are pending in "
                    "unconfirmed transactions. Wait ~60s or call unlock_utxos()."
                )

            # Build outputs list: [(address, amount, 'bch'), ...]
            outputs = [(addr, amt, "bch") for addr, amt in recipients]

            txid = key.send(outputs, unspents=available)

            # Lock the UTXOs we just spent
            self._lock_utxos(available)

            details["txid"] = txid
            details["status"] = "broadcast"
            details["utxos_used"] = len(available)
            self._audit.log("send_many", details)

            return txid

        except Exception as e:
            details["error"] = str(e)
            details["status"] = "failed"
            self._audit.log("send_many_failed", details)
            raise

    # ── CashTokens: NFT Minting ───────────────────────────────────────────────

    def mint_nft(self, commitment: bytes,
                 capability: str = "none",
                 category_id: Optional[str] = None,
                 recipient: Optional[str] = None) -> str:
        """
        Mint a CashTokens NFT.

        Args:
            commitment: Up to 40 bytes of data attached to the NFT
            capability: 'none' (immutable), 'mutable', or 'minting'
            category_id: Token category (uses genesis UTXO if None)
            recipient: Where to send the minted NFT (self if None)

        Returns:
            Transaction ID (txid)

        Note: 'minting' capability allows creating more NFTs of same category.
              'mutable' allows updating the commitment.
              'none' creates an immutable NFT — permanent once created.
        """
        if len(commitment) > 40:
            raise ValueError(
                f"NFT commitment must be ≤ 40 bytes, got {len(commitment)} bytes."
            )

        valid_capabilities = {"none", "mutable", "minting"}
        if capability not in valid_capabilities:
            raise ValueError(
                f"capability must be one of {valid_capabilities}, got '{capability}'"
            )

        key = self._keystore.get_key(0, 0, 0, self._testnet)
        to_address = recipient or key.address

        details = {
            "type": "mint_nft",
            "commitment_hex": commitment.hex(),
            "commitment_length": len(commitment),
            "capability": capability,
            "to": to_address,
            "testnet": self._testnet,
        }

        try:
            key.get_unspents()
            available = self._filter_unlocked_utxos(key.unspents)

            if not available:
                raise RuntimeError(
                    "No unlocked UTXOs available for NFT mint."
                )

            # Find a genesis UTXO (output index 0) for the category
            # bitcash CashToken format:
            # (address, amount, currency, category_id, capability, commitment, token_amount)
            if category_id:
                outputs = [(to_address, 1000, 'satoshi',
                           category_id, capability, commitment, 0)]
            else:
                # Use genesis UTXO — let bitcash handle category creation
                # Amount: 1000 satoshi (dust limit for token output)
                outputs = [(to_address, 1000, 'satoshi',
                           None, capability, commitment, 0)]

            txid = key.send(outputs, unspents=available)
            self._lock_utxos(available)

            details["txid"] = txid
            details["status"] = "broadcast"
            if category_id:
                details["category_id"] = category_id
            self._audit.log("mint_nft", details)

            return txid

        except Exception as e:
            details["error"] = str(e)
            details["status"] = "failed"
            self._audit.log("mint_nft_failed", details)
            raise

    # ── CashTokens: Fungible Tokens ───────────────────────────────────────────

    def send_token(self, category_id: str, to_address: str,
                   amount: int, memo: Optional[str] = None) -> str:
        """
        Send fungible CashTokens to an address.

        Args:
            category_id: The 32-byte token category hex string
            to_address: Recipient address
            amount: Number of tokens to send (integer units)
            memo: Optional internal memo

        Returns:
            Transaction ID (txid)
        """
        key = self._keystore.get_key(0, 0, 0, self._testnet)

        details = {
            "type": "send_token",
            "category_id": category_id,
            "to": to_address,
            "amount": amount,
            "testnet": self._testnet,
        }
        if memo:
            details["memo"] = memo

        try:
            key.get_unspents()
            available = self._filter_unlocked_utxos(key.unspents)

            if not available:
                raise RuntimeError(
                    "No unlocked UTXOs available for token send."
                )

            outputs = [(to_address, 1000, 'satoshi',
                       category_id, None, None, amount)]
            txid = key.send(outputs, unspents=available)
            self._lock_utxos(available)

            details["txid"] = txid
            details["status"] = "broadcast"
            self._audit.log("send_token", details)

            return txid

        except Exception as e:
            details["error"] = str(e)
            details["status"] = "failed"
            self._audit.log("send_token_failed", details)
            raise

    # ── APMP Messaging ────────────────────────────────────────────────────────

    def send_with_message(
        self,
        to_address: str,
        amount: float,
        message: APMPMessage,
        currency: str = "bch",
    ) -> str:
        """
        Send BCH with an APMP message embedded in OP_RETURN.

        Encodes the APMPMessage to compact JSON and passes it to bitcash's
        ``message=`` parameter, which creates an OP_RETURN output in the TX.

        Args:
            to_address: Recipient BCH address (cashaddr or legacy).
            amount: Amount to send.
            message: APMPMessage to embed in OP_RETURN.
            currency: 'bch', 'usd', or 'satoshi'. Defaults to 'bch'.

        Returns:
            Transaction ID (txid).

        Raises:
            ValueError: If the message exceeds MAX_BYTES when encoded.
            RuntimeError: If no unlocked UTXOs are available.
        """
        key = self._keystore.get_key(0, 0, 0, self._testnet)
        encoded_msg = message.encode()   # raises ValueError if too long

        details = {
            "type": "send_with_message",
            "to": to_address,
            "amount": amount,
            "currency": currency,
            "apmp_type": message.type,
            "apmp_from": message.from_agent,
            "apmp_ref": message.ref,
            "apmp_msg": message.msg,
            "testnet": self._testnet,
        }

        try:
            key.get_unspents()
            available = self._filter_unlocked_utxos(key.unspents)

            if not available:
                raise RuntimeError(
                    "No unlocked UTXOs available — all UTXOs are pending in "
                    "unconfirmed transactions. Wait ~60s or call unlock_utxos()."
                )

            txid = key.send(
                [(to_address, amount, currency)],
                message=encoded_msg,
                unspents=available,
            )

            self._lock_utxos(available)

            details["txid"] = txid
            details["status"] = "broadcast"
            details["apmp_bytes"] = len(encoded_msg.encode('utf-8'))
            self._audit.log("send_with_message", details)

            return txid

        except Exception as e:
            details["error"] = str(e)
            details["status"] = "failed"
            self._audit.log("send_with_message_failed", details)
            raise

    def request_payment(
        self,
        to_address: str,
        amount_bch: float,
        msg: Optional[str] = None,
        ref: Optional[str] = None,
    ) -> str:
        """
        Send a payment request to another agent.

        Sends a dust transaction (546 satoshis) to ``to_address`` with a
        type=request APMP message embedded in OP_RETURN. The recipient's
        inbox will surface it as an unpaid invoice.

        Args:
            to_address: Address of the agent being asked to pay.
            amount_bch: Amount being requested, in BCH.
            msg: Optional description or invoice note.
            ref: Optional reference/invoice ID.

        Returns:
            Transaction ID (txid).
        """
        # Build the payment request message
        apmp = APMPMessage.request(
            from_agent=self.fingerprint[:8],   # use fingerprint prefix as agent ID
            amount_bch=amount_bch,
            msg=msg,
            ref=ref,
        )

        details = {
            "type": "request_payment",
            "to": to_address,
            "amount_requested_bch": amount_bch,
            "ref": ref,
            "testnet": self._testnet,
        }

        try:
            txid = self.send_with_message(
                to_address=to_address,
                amount=546,
                message=apmp,
                currency="satoshi",
            )
            details["txid"] = txid
            details["status"] = "broadcast"
            self._audit.log("request_payment", details)
            return txid

        except Exception as e:
            details["error"] = str(e)
            details["status"] = "failed"
            self._audit.log("request_payment_failed", details)
            raise

    def get_inbox(self, limit: int = 20) -> list:
        """
        Return recent incoming messages from other agents.

        Parses APMP data from incoming transaction OP_RETURN fields by
        scanning this wallet's primary address via the Fulcrum/ElectrumX API.

        Args:
            limit: Maximum number of recent transactions to scan.

        Returns:
            List of InboxMessage objects, sorted newest-first.
            Returns empty list if network is unavailable.
        """
        from agentvault.inbox import AgentInbox

        inbox = AgentInbox(address=self.address, testnet=self._testnet)
        messages = inbox.fetch(limit=limit)

        self._audit.log("inbox_fetch", {
            "address": self.address,
            "limit": limit,
            "messages_found": len(messages),
            "apmp_count": sum(1 for m in messages if m.apmp is not None),
            "testnet": self._testnet,
        })

        return messages

    # ── Identity: Message Signing ─────────────────────────────────────────────

    def sign_message(self, message: str) -> str:
        """
        Sign a message with this wallet's private key.

        Returns a base64-encoded DER signature (BIP-62 compliant).
        Useful for proving agent identity off-chain without broadcasting
        a transaction.

        Args:
            message: The message string to sign.

        Returns:
            Base64-encoded signature string.

        Example:
            sig = wallet.sign_message("I am Atlas, timestamp=1711000000")
            # → "MEUCIQD..."

            # Another party verifies:
            ok = wallet.verify_message(wallet.address, msg, sig)
        """
        key = self._keystore.get_key(0, 0, 0, self._testnet)
        sig_bytes = key.sign(message.encode('utf-8'))
        sig_b64 = base64.b64encode(sig_bytes).decode('ascii')

        self._audit.log("sign_message", {
            "address": key.address,
            "message_length": len(message),
            "signature_b64_length": len(sig_b64),
        })

        return sig_b64

    def verify_message(self, address: str, message: str, signature: str) -> bool:
        """
        Verify a message was signed by the owner of a BCH address.

        Uses the public key derived from the address to verify the signature.
        Works for any BCH address — not just this wallet's own address.

        Args:
            address: The BCH address claimed to have signed the message.
            message: The original message string.
            signature: Base64-encoded signature (as returned by sign_message).

        Returns:
            True if the signature is valid for the given address and message.
            False otherwise (invalid signature, wrong key, tampered message).

        Note:
            BCH address → public key verification requires the public key.
            bitcash's verify_sig() takes the raw public key bytes, not an address.
            To verify against an address, we need the signer to also provide
            their public key — or we derive it from ECDSA recovery.
            This implementation uses bitcash's verify_sig with the public key
            from this wallet if verifying self-signed messages, otherwise
            requires the signer to have previously shared their public key.

            For cross-agent identity proofs, use a signed transaction instead
            (which embeds the public key in the scriptSig).
        """
        try:
            sig_bytes = base64.b64decode(signature)
            message_bytes = message.encode('utf-8')

            # If verifying our own address, use our public key directly
            key = self._keystore.get_key(0, 0, 0, self._testnet)
            if key.address == address or key.cashaddress == address:
                result = verify_sig(sig_bytes, message_bytes, key.public_key)
            else:
                # For external addresses, we can only verify if we have
                # the public key. bitcash verify_sig needs the raw public key.
                # Attempt ECDSA recovery to get the public key from signature.
                result = self._verify_external(
                    sig_bytes, message_bytes, address
                )

            self._audit.log("verify_message", {
                "address": address,
                "result": result,
                "message_length": len(message),
            })
            return result

        except Exception as e:
            self._audit.log("verify_message_failed", {
                "address": address,
                "error": str(e),
            })
            return False

    def _verify_external(
        self, sig_bytes: bytes, message_bytes: bytes, address: str
    ) -> bool:
        """
        Verify a signature against an external address using ECDSA recovery.

        Recovers the public key from the signature and checks if it
        matches the given address.

        Returns:
            True if signature is valid and matches the address.
        """
        try:
            import coincurve
            from cashaddress import convert

            # Try recovering all possible public keys (recovery ID 0 and 1)
            for recovery_id in (0, 1):
                try:
                    # ECDSA recovery: get public key from (signature, message)
                    # sig_bytes is DER-encoded; coincurve expects compact (r,s)
                    pub = coincurve.PublicKey.from_signature_and_message(
                        sig_bytes, message_bytes, hasher='sha256',
                        recovery_id=recovery_id,
                    )
                    recovered_key_bytes = pub.format(compressed=True)
                    if verify_sig(sig_bytes, message_bytes, recovered_key_bytes):
                        # Check if this public key maps to the claimed address
                        # by letting bitcash reconstruct the address
                        from bitcash.crypto import ECPublicKey
                        ec = ECPublicKey(recovered_key_bytes)
                        recovered_addr = ec.address
                        bare_recovered = recovered_addr.replace("bitcoincash:", "")
                        bare_claimed   = address.replace("bitcoincash:", "")
                        if bare_recovered == bare_claimed:
                            return True
                except Exception:
                    continue
            return False
        except Exception:
            return False

    # ── Audit ─────────────────────────────────────────────────────────────────

    def audit_log(self, since: Optional[str] = None,
                  action: Optional[str] = None,
                  limit: Optional[int] = None) -> list[dict]:
        """Query the audit log."""
        return self._audit.entries(since=since, action=action, limit=limit)

    def verify_audit(self) -> tuple[bool, Optional[str]]:
        """Verify the integrity of the audit log. Returns (is_valid, error_msg)."""
        return self._audit.verify()

    # ── Info ──────────────────────────────────────────────────────────────────

    @property
    def fingerprint(self) -> str:
        """Non-sensitive wallet identifier."""
        return self._keystore.fingerprint

    @property
    def is_testnet(self) -> bool:
        return self._testnet

    def __repr__(self):
        net = "testnet" if self._testnet else "mainnet"
        return f"<AgentVault Wallet fingerprint={self.fingerprint} network={net}>"
