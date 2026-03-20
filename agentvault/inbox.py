"""
inbox.py — Agent Inbox

Scans incoming BCH transactions and extracts APMP messages, giving
agents a structured view of what other agents have sent them.

The inbox parses OP_RETURN outputs from incoming transactions and
surfaces them as InboxMessage objects — ready to act on.

Data sources (tried in order, fallback gracefully):
    1. Fulcrum REST API (fountainhead.cash) — fast, BCH-native
    2. FullStack.cash ElectrumX API — good backup

OP_RETURN parsing:
    - Output scriptPubKey starting with '6a' is OP_RETURN
    - Bytes after '6a <len>' are the data payload (UTF-8 text for APMP)
    - Non-APMP OP_RETURN data is preserved as raw_memo and apmp=None

Usage:
    inbox = AgentInbox("bitcoincash:qp...")
    messages = inbox.fetch(limit=20)
    for m in messages:
        if m.apmp:
            print(m.apmp.type, m.apmp.from_agent, m.amount_bch)

    # Filter helpers
    requests = inbox.get_requests()   # unpaid invoices
    payments = inbox.get_payments()   # received payments
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

import requests as _requests

from agentvault.messaging import APMPMessage


logger = logging.getLogger(__name__)


# ── REST API endpoints ─────────────────────────────────────────────────────────

_FULCRUM_BASE    = "https://fulcrum.fountainhead.cash"
_FULLSTACK_BASE  = "https://api.fullstack.cash/v5/electrumx"
_REQUEST_TIMEOUT = 10   # seconds


# ── InboxMessage ──────────────────────────────────────────────────────────────

@dataclass
class InboxMessage:
    """
    A single message received in the agent inbox.

    Represents one incoming transaction — with or without an APMP payload.
    Transactions without OP_RETURN data have apmp=None and raw_memo=None.

    Attributes:
        txid (str): Transaction ID.
        from_address (str): Sender's BCH address (cashaddr format).
        amount_bch (float): BCH received in this transaction.
        timestamp (int): Unix timestamp (block time or mempool first-seen).
        apmp (APMPMessage | None): Parsed APMP message, or None if absent.
        raw_memo (str | None): Raw OP_RETURN text (before APMP parsing).
    """
    txid: str
    from_address: str
    amount_bch: float
    timestamp: int
    apmp: Optional[APMPMessage] = None
    raw_memo: Optional[str] = None

    def __repr__(self) -> str:
        apmp_repr = repr(self.apmp) if self.apmp else "None"
        return (
            f"<InboxMessage txid={self.txid[:12]}… "
            f"from={self.from_address[:20]}… "
            f"amount={self.amount_bch:.8f} BCH "
            f"apmp={apmp_repr}>"
        )


# ── AgentInbox ────────────────────────────────────────────────────────────────

class AgentInbox:
    """
    Scans incoming transactions to a BCH address and extracts APMP messages.

    Provides a structured inbox of messages received from other agents.
    Network calls fail gracefully — if the API is unreachable, fetch()
    returns an empty list rather than raising an exception.

    Args:
        address (str): BCH address to scan (cashaddr preferred).
        testnet (bool): If True, use testnet API endpoints.

    Example:
        inbox = AgentInbox("bitcoincash:qp...")
        msgs  = inbox.fetch(limit=20)
        reqs  = inbox.get_requests()    # type=request (invoices)
        pays  = inbox.get_payments()    # type=pay (received payments)
    """

    def __init__(self, address: str, testnet: bool = False):
        self.address  = address
        self.testnet  = testnet
        self._cache: list[InboxMessage] = []

    # ── Public API ─────────────────────────────────────────────────────────────

    def fetch(self, limit: int = 20) -> list[InboxMessage]:
        """
        Fetch recent incoming transactions and parse APMP messages.

        Tries multiple API providers; returns empty list on all failures
        rather than propagating network errors.

        Args:
            limit: Maximum number of transactions to process.

        Returns:
            List of InboxMessage objects, sorted newest-first.
        """
        txids = self._fetch_tx_history(limit=limit)
        messages = []

        for txid in txids:
            try:
                tx_data = self._fetch_tx(txid)
                if tx_data is None:
                    continue
                msg = self._parse_tx(txid, tx_data)
                if msg is not None:
                    messages.append(msg)
            except Exception as exc:
                logger.debug("Error parsing tx %s: %s", txid, exc)
                continue

        # Sort newest-first by timestamp
        messages.sort(key=lambda m: m.timestamp, reverse=True)
        self._cache = messages
        return messages

    def get_requests(self) -> list[InboxMessage]:
        """
        Return only type=request messages — unpaid invoices from other agents.

        Operates on the cached result of the last fetch() call.
        Call fetch() first to populate the cache.

        Returns:
            List of InboxMessage objects where apmp.type == 'request'.
        """
        return [
            m for m in self._cache
            if m.apmp is not None and m.apmp.type == "request"
        ]

    def get_payments(self) -> list[InboxMessage]:
        """
        Return only type=pay messages — payments received from other agents.

        Operates on the cached result of the last fetch() call.
        Call fetch() first to populate the cache.

        Returns:
            List of InboxMessage objects where apmp.type == 'pay'.
        """
        return [
            m for m in self._cache
            if m.apmp is not None and m.apmp.type == "pay"
        ]

    # ── Internal: API Fetching ─────────────────────────────────────────────────

    def _fetch_tx_history(self, limit: int) -> list[str]:
        """
        Fetch list of recent transaction IDs for this address.

        Tries Fulcrum first, then FullStack.cash as backup.

        Returns:
            List of txid strings (most recent first), up to `limit`.
        """
        # Try Fulcrum first
        txids = self._fulcrum_history(limit)
        if txids is not None:
            return txids

        # Fallback: FullStack.cash
        txids = self._fullstack_history(limit)
        if txids is not None:
            return txids

        logger.warning(
            "AgentInbox: Could not fetch transaction history for %s — "
            "all API providers failed. Returning empty inbox.",
            self.address,
        )
        return []

    def _fetch_tx(self, txid: str) -> Optional[dict]:
        """
        Fetch full transaction data for a txid.

        Tries Fulcrum first, then FullStack.cash.

        Returns:
            Transaction dict, or None on failure.
        """
        tx = self._fulcrum_tx(txid)
        if tx is not None:
            return tx

        tx = self._fullstack_tx(txid)
        return tx

    # ── Fulcrum REST API ───────────────────────────────────────────────────────

    def _fulcrum_history(self, limit: int) -> Optional[list[str]]:
        """Fetch tx history from Fulcrum fountainhead.cash REST API."""
        # Strip prefix for Fulcrum
        addr = self.address
        url = f"{_FULCRUM_BASE}/history/{addr}"
        try:
            resp = _requests.get(url, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            # Fulcrum returns list of {"tx_hash": ..., "height": ...}
            if isinstance(data, list):
                txids = [item["tx_hash"] for item in data if "tx_hash" in item]
                # Reverse so newest (highest height) comes first
                txids.reverse()
                return txids[:limit]
        except Exception as exc:
            logger.debug("Fulcrum history failed: %s", exc)
        return None

    def _fulcrum_tx(self, txid: str) -> Optional[dict]:
        """Fetch full TX from Fulcrum REST API."""
        url = f"{_FULCRUM_BASE}/tx/{txid}"
        try:
            resp = _requests.get(url, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.debug("Fulcrum tx fetch failed for %s: %s", txid, exc)
        return None

    # ── FullStack.cash ElectrumX API ──────────────────────────────────────────

    def _fullstack_history(self, limit: int) -> Optional[list[str]]:
        """Fetch tx history from FullStack.cash ElectrumX API."""
        url = f"{_FULLSTACK_BASE}/transactions/{self.address}"
        try:
            resp = _requests.get(url, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            # FullStack returns {"success": true, "transactions": [...]}
            txns = data.get("transactions", [])
            txids = [t["tx_hash"] for t in txns if "tx_hash" in t]
            txids.reverse()
            return txids[:limit]
        except Exception as exc:
            logger.debug("FullStack history failed: %s", exc)
        return None

    def _fullstack_tx(self, txid: str) -> Optional[dict]:
        """Fetch TX details from FullStack.cash."""
        url = f"{_FULLSTACK_BASE}/tx/data/{txid}"
        try:
            resp = _requests.get(url, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            return data.get("txdata") or data
        except Exception as exc:
            logger.debug("FullStack tx fetch failed for %s: %s", txid, exc)
        return None

    # ── Transaction Parsing ───────────────────────────────────────────────────

    def _parse_tx(self, txid: str, tx_data: dict) -> Optional[InboxMessage]:
        """
        Parse a transaction dict into an InboxMessage.

        Extracts:
        - Incoming BCH amount (outputs to our address)
        - OP_RETURN memo (if any output starts with OP_RETURN 6a)
        - Sender address (from the first input)
        - Block timestamp (or current time for mempool)

        Returns:
            InboxMessage, or None if this tx has no outputs to our address.
        """
        # Normalize address for comparison
        our_address = self.address
        # Strip cashaddr prefix for loose matching
        our_bare = our_address.replace("bitcoincash:", "").replace("bchtest:", "")

        # Find outputs to our address and collect BCH received
        amount_satoshis = 0
        raw_memo: Optional[str] = None

        vout = tx_data.get("vout", [])
        for output in vout:
            value = output.get("value", 0)
            script_pubkey = output.get("scriptPubKey", {})
            script_hex = script_pubkey.get("hex", "")
            addresses = script_pubkey.get("addresses", [])
            address = script_pubkey.get("address", "")
            cashaddrs = addresses or ([address] if address else [])

            # Check if this output is OP_RETURN (data carrier)
            if script_hex.startswith("6a"):
                raw_memo = self._decode_op_return(script_hex)
                continue

            # Check if any of this output's addresses match ours
            for addr in cashaddrs:
                bare = addr.replace("bitcoincash:", "").replace("bchtest:", "")
                if bare == our_bare or addr == our_address:
                    # value in BTC/BCH units
                    amount_satoshis += int(round(float(value) * 1e8))
                    break

        # If no outputs to us, this isn't an incoming transaction
        if amount_satoshis == 0 and raw_memo is None:
            return None

        # Extract sender address from inputs
        from_address = self._extract_sender(tx_data)

        # Get timestamp
        timestamp = tx_data.get("time") or tx_data.get("blocktime") or int(time.time())

        # Parse APMP if there's a memo
        apmp: Optional[APMPMessage] = None
        if raw_memo:
            apmp = APMPMessage.decode(raw_memo)

        amount_bch = amount_satoshis / 1e8

        return InboxMessage(
            txid=txid,
            from_address=from_address or "unknown",
            amount_bch=amount_bch,
            timestamp=int(timestamp),
            apmp=apmp,
            raw_memo=raw_memo,
        )

    def _decode_op_return(self, script_hex: str) -> Optional[str]:
        """
        Decode an OP_RETURN script hex into a UTF-8 string.

        OP_RETURN format: 6a <pushdata> <data bytes>
        The pushdata byte(s) indicate the length of the following data.

        Args:
            script_hex: Full scriptPubKey hex string starting with '6a'.

        Returns:
            UTF-8 decoded string, or None if decoding fails.
        """
        try:
            script_bytes = bytes.fromhex(script_hex)
            # script_bytes[0] = 0x6a (OP_RETURN)
            # script_bytes[1] = pushdata opcode (e.g. 0x4c for OP_PUSHDATA1)
            # or direct push if 0x01..0x4b
            if len(script_bytes) < 2:
                return None

            pos = 1  # skip OP_RETURN (0x6a)
            opcode = script_bytes[pos]

            if opcode == 0x4c:
                # OP_PUSHDATA1: next byte is length
                pos += 1
                data_len = script_bytes[pos]
                pos += 1
            elif opcode == 0x4d:
                # OP_PUSHDATA2: next two bytes are length (little-endian)
                pos += 1
                data_len = int.from_bytes(script_bytes[pos:pos+2], 'little')
                pos += 2
            elif 0x01 <= opcode <= 0x4b:
                # Direct push: opcode is the length
                data_len = opcode
                pos += 1
            else:
                return None

            data_bytes = script_bytes[pos:pos + data_len]
            return data_bytes.decode('utf-8', errors='replace')

        except Exception as exc:
            logger.debug("OP_RETURN decode failed for %s: %s", script_hex, exc)
            return None

    def _extract_sender(self, tx_data: dict) -> Optional[str]:
        """
        Extract the primary sender address from transaction inputs.

        Uses the first input's scriptSig or coinbase data.

        Returns:
            BCH address string, or None if not determinable.
        """
        vin = tx_data.get("vin", [])
        if not vin:
            return None

        first_input = vin[0]

        # Some APIs populate 'addr' directly on the input
        addr = first_input.get("addr") or first_input.get("address")
        if addr:
            return addr

        # Some APIs provide scriptSig with addresses
        script_sig = first_input.get("scriptSig", {})
        addresses = script_sig.get("addresses", [])
        if addresses:
            return addresses[0]

        return None

    def __repr__(self) -> str:
        return (
            f"<AgentInbox address={self.address[:20]}… "
            f"cached={len(self._cache)} messages "
            f"testnet={self.testnet}>"
        )
