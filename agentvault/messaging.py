"""
messaging.py — Agent Payment Message Protocol (APMP)

A lightweight protocol for embedding structured messages in BCH transactions
via OP_RETURN. Enables agent-to-agent communication without a separate
messaging layer — the blockchain IS the channel.

Schema (compact JSON, max 220 bytes):
    {
        "v": 1,           # protocol version (int)
        "type": "pay",    # pay | request | receipt | ping | reject
        "from": "atlas",  # sender agent name (str, optional)
        "ref": "inv-001", # invoice/reference ID (str, optional)
        "msg": "Q3 fee",  # human-readable message (str, optional)
        "amt": 0.0001,    # amount in BCH — used in type=request (float, optional)
        "ts": 1711000000  # unix timestamp (int)
    }

Design:
    - Short keys ("v", "type", "from", etc.) to conserve the 220-byte budget
    - ts always included so inbox can sort without blockchain timestamp
    - "from" is agent name (human-readable), NOT an address
    - Compact JSON with no whitespace

Usage:
    msg = APMPMessage.pay("erin", msg="Q3 hosting fee", ref="inv-2026-03")
    encoded = msg.encode()   # → compact JSON string ≤ 220 bytes

    # Decode on the receiving end
    msg = APMPMessage.decode(encoded)
    if msg:
        print(msg.type, msg.from_agent)
"""

import json
import time
from typing import Optional


class APMPMessage:
    """
    Represents an Agent Payment Message Protocol (APMP) message.

    APMP messages are embedded in BCH transactions via OP_RETURN.
    They allow agents to communicate payment intent, acknowledgments,
    and requests directly on-chain — no intermediary required.

    Class Attributes:
        VERSION (int): Current protocol version.
        TYPES (tuple): Valid message type strings.
        MAX_BYTES (int): Maximum encoded size in bytes (OP_RETURN limit).

    Args:
        type (str): Message type — one of TYPES.
        from_agent (str, optional): Sender agent name.
        ref (str, optional): Invoice or reference ID.
        msg (str, optional): Human-readable message text.
        amount_bch (float, optional): Amount in BCH (used in type=request).
        timestamp (int, optional): Unix timestamp. Defaults to now.
    """

    VERSION = 1
    TYPES = ("pay", "request", "receipt", "ping", "reject")
    MAX_BYTES = 220

    def __init__(
        self,
        type: str,
        from_agent: Optional[str] = None,
        ref: Optional[str] = None,
        msg: Optional[str] = None,
        amount_bch: Optional[float] = None,
        timestamp: Optional[int] = None,
    ):
        if type not in self.TYPES:
            raise ValueError(
                f"Invalid APMP type '{type}'. Must be one of: {self.TYPES}"
            )
        self.type = type
        self.from_agent = from_agent
        self.ref = ref
        self.msg = msg
        self.amount_bch = amount_bch
        self.timestamp = timestamp or int(time.time())

    # ── Encoding / Decoding ───────────────────────────────────────────────────

    def encode(self) -> str:
        """
        Encode this message to a compact JSON string for OP_RETURN embedding.

        Uses short keys to conserve the 220-byte OP_RETURN budget.

        Returns:
            Compact JSON string, always ≤ 220 bytes.

        Raises:
            ValueError: If the encoded message exceeds MAX_BYTES.
        """
        payload = {
            "v": self.VERSION,
            "type": self.type,
            "ts": self.timestamp,
        }
        if self.from_agent is not None:
            payload["from"] = self.from_agent
        if self.ref is not None:
            payload["ref"] = self.ref
        if self.msg is not None:
            payload["msg"] = self.msg
        if self.amount_bch is not None:
            payload["amt"] = self.amount_bch

        encoded = json.dumps(payload, separators=(',', ':'))
        byte_len = len(encoded.encode('utf-8'))
        if byte_len > self.MAX_BYTES:
            raise ValueError(
                f"Encoded APMP message is {byte_len} bytes — exceeds "
                f"MAX_BYTES ({self.MAX_BYTES}). Shorten 'msg', 'ref', or 'from'."
            )
        return encoded

    @classmethod
    def decode(cls, data: str) -> Optional["APMPMessage"]:
        """
        Decode an APMP message from an OP_RETURN string.

        Silently returns None if the data is not a valid APMP message
        (wrong format, missing required fields, or unknown version).
        This is intentional — non-APMP OP_RETURN data should be ignored,
        not raise exceptions.

        Args:
            data: Raw string from an OP_RETURN output.

        Returns:
            APMPMessage if data is valid APMP, otherwise None.
        """
        if not data or not isinstance(data, str):
            return None

        try:
            payload = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            return None

        # Must be a dict with required APMP fields
        if not isinstance(payload, dict):
            return None
        if payload.get("v") != cls.VERSION:
            return None
        msg_type = payload.get("type")
        if msg_type not in cls.TYPES:
            return None

        return cls(
            type=msg_type,
            from_agent=payload.get("from"),
            ref=payload.get("ref"),
            msg=payload.get("msg"),
            amount_bch=payload.get("amt"),
            timestamp=payload.get("ts") or int(time.time()),
        )

    # ── Factory Methods ───────────────────────────────────────────────────────

    @classmethod
    def pay(
        cls,
        from_agent: str,
        msg: Optional[str] = None,
        ref: Optional[str] = None,
    ) -> "APMPMessage":
        """
        Create a type=pay message — a payment notification.

        Use when sending BCH to notify the recipient of what the payment
        is for, or to link it to an invoice reference.

        Args:
            from_agent: Sender agent name (e.g. "erin", "atlas").
            msg: Optional human-readable payment description.
            ref: Optional invoice or reference ID.

        Returns:
            APMPMessage of type 'pay'.
        """
        return cls(type="pay", from_agent=from_agent, msg=msg, ref=ref)

    @classmethod
    def request(
        cls,
        from_agent: str,
        amount_bch: float,
        msg: Optional[str] = None,
        ref: Optional[str] = None,
    ) -> "APMPMessage":
        """
        Create a type=request message — a payment request / invoice.

        Sent as a dust transaction to the payer's address. Their inbox
        will surface it as an unpaid invoice. The recipient is expected
        to respond with a type=pay transaction for amount_bch BCH.

        Args:
            from_agent: Requesting agent name.
            amount_bch: Amount being requested, in BCH.
            msg: Optional description or invoice note.
            ref: Optional reference ID to include in the payment response.

        Returns:
            APMPMessage of type 'request'.
        """
        if amount_bch <= 0:
            raise ValueError("amount_bch must be positive.")
        return cls(
            type="request",
            from_agent=from_agent,
            amount_bch=amount_bch,
            msg=msg,
            ref=ref,
        )

    @classmethod
    def receipt(
        cls,
        from_agent: str,
        ref: str,
        msg: Optional[str] = None,
    ) -> "APMPMessage":
        """
        Create a type=receipt message — a payment acknowledgment.

        Confirms that a payment was received and processed. Links back
        to the original invoice/request via ref.

        Args:
            from_agent: Acknowledging agent name.
            ref: Reference ID of the original payment or invoice.
            msg: Optional confirmation note.

        Returns:
            APMPMessage of type 'receipt'.
        """
        if not ref:
            raise ValueError("receipt requires a non-empty ref.")
        return cls(type="receipt", from_agent=from_agent, ref=ref, msg=msg)

    @classmethod
    def ping(
        cls,
        from_agent: str,
        msg: Optional[str] = None,
    ) -> "APMPMessage":
        """
        Create a type=ping message — a liveness/reachability signal.

        Useful for confirming that an agent address is monitored and
        its inbox is processing messages. No payment expected in response.

        Args:
            from_agent: Sending agent name.
            msg: Optional ping payload or challenge string.

        Returns:
            APMPMessage of type 'ping'.
        """
        return cls(type="ping", from_agent=from_agent, msg=msg)

    @classmethod
    def reject(
        cls,
        from_agent: str,
        ref: Optional[str] = None,
        msg: Optional[str] = None,
    ) -> "APMPMessage":
        """
        Create a type=reject message — a rejection or refusal.

        Used to signal that a payment request was denied, a transaction
        was invalid, or a service is unavailable.

        Args:
            from_agent: Rejecting agent name.
            ref: Optional reference ID being rejected.
            msg: Optional reason for rejection.

        Returns:
            APMPMessage of type 'reject'.
        """
        return cls(type="reject", from_agent=from_agent, ref=ref, msg=msg)

    # ── Utilities ─────────────────────────────────────────────────────────────

    def byte_size(self) -> int:
        """Return the encoded byte size of this message."""
        return len(self.encode().encode('utf-8'))

    def to_dict(self) -> dict:
        """Return a full Python dict representation of this message."""
        return {
            "version": self.VERSION,
            "type": self.type,
            "from_agent": self.from_agent,
            "ref": self.ref,
            "msg": self.msg,
            "amount_bch": self.amount_bch,
            "timestamp": self.timestamp,
        }

    def __repr__(self) -> str:
        parts = [f"type={self.type!r}"]
        if self.from_agent:
            parts.append(f"from={self.from_agent!r}")
        if self.ref:
            parts.append(f"ref={self.ref!r}")
        if self.amount_bch is not None:
            parts.append(f"amt={self.amount_bch}")
        return f"<APMPMessage {' '.join(parts)} ts={self.timestamp}>"
