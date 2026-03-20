"""
audit.py — Append-only, hash-chained audit log.

Every wallet action is recorded here. The chain of hashes ensures
that tampering with any entry is detectable — each entry includes
the hash of the previous entry.

This is both a security feature and a compliance feature.
"""

import json
import hashlib
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Iterator


class AuditLog:
    """
    Append-only, hash-chained audit log.

    Each entry contains:
    - timestamp (ISO 8601 UTC)
    - action type
    - details (dict)
    - previous entry hash
    - this entry hash (SHA256 of all the above)

    Properties:
    - Append-only: no entry can be modified or deleted without breaking the chain
    - Detectable tampering: verify() checks the entire chain
    - Human readable: plain JSON lines, one per entry
    """

    GENESIS_HASH = "0" * 64  # The "previous hash" for the first entry

    def __init__(self, log_path: str):
        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.touch()
        self._last_hash = self._compute_last_hash()

    def _compute_last_hash(self) -> str:
        """Find the hash of the most recent entry (or genesis hash if empty)."""
        last = None
        for entry in self._iter_raw():
            last = entry.get("hash", self.GENESIS_HASH)
        return last or self.GENESIS_HASH

    def _iter_raw(self) -> Iterator[dict]:
        """Iterate over raw log entries."""
        try:
            for line in self._path.read_text().splitlines():
                line = line.strip()
                if line:
                    yield json.loads(line)
        except (json.JSONDecodeError, FileNotFoundError):
            return

    def log(self, action: str, details: dict,
            policy_result: Optional[dict] = None) -> str:
        """
        Append an entry to the audit log.

        Args:
            action: Short action descriptor (e.g. "send", "receive", "mint_nft")
            details: Action-specific details dict
            policy_result: Policy engine result (optional)

        Returns:
            The hash of the new entry.
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "seq": self._count() + 1,
            "action": action,
            "details": details,
            "prev_hash": self._last_hash,
        }
        if policy_result is not None:
            entry["policy_result"] = policy_result

        # Compute this entry's hash (over everything except "hash" field)
        entry_hash = self._hash_entry(entry)
        entry["hash"] = entry_hash

        # Append to log
        with self._path.open('a') as f:
            f.write(json.dumps(entry, separators=(',', ':')) + '\n')

        self._last_hash = entry_hash
        return entry_hash

    def verify(self) -> tuple[bool, Optional[str]]:
        """
        Verify the integrity of the entire audit log.

        Returns:
            (True, None) if log is intact
            (False, error_message) if tampering detected
        """
        prev_hash = self.GENESIS_HASH
        for i, entry in enumerate(self._iter_raw(), 1):
            # Verify chain linkage
            if entry.get("prev_hash") != prev_hash:
                return False, (
                    f"Chain broken at entry #{i} (seq {entry.get('seq', '?')}): "
                    f"prev_hash mismatch. Log may have been tampered with."
                )
            # Verify entry hash
            stored_hash = entry.get("hash")
            entry_copy = {k: v for k, v in entry.items() if k != "hash"}
            computed_hash = self._hash_entry(entry_copy)
            if stored_hash != computed_hash:
                return False, (
                    f"Hash mismatch at entry #{i} (seq {entry.get('seq', '?')}): "
                    f"entry content has been modified."
                )
            prev_hash = stored_hash

        return True, None

    def entries(self, since: Optional[str] = None,
                action: Optional[str] = None,
                limit: Optional[int] = None) -> list[dict]:
        """
        Query audit log entries.

        Args:
            since: ISO datetime string — only entries after this time
            action: Filter by action type
            limit: Maximum entries to return (most recent)
        """
        results = []
        for entry in self._iter_raw():
            if since and entry["timestamp"] < since:
                continue
            if action and entry["action"] != action:
                continue
            results.append(entry)

        if limit:
            results = results[-limit:]
        return results

    def _count(self) -> int:
        count = 0
        for _ in self._iter_raw():
            count += 1
        return count

    @staticmethod
    def _hash_entry(entry: dict) -> str:
        """Compute SHA256 hash of an entry (excluding the 'hash' field)."""
        canonical = json.dumps(entry, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def __repr__(self):
        valid, err = self.verify()
        status = "✅ intact" if valid else f"🚨 TAMPERED: {err}"
        return f"<AuditLog path={self._path} entries={self._count()} {status}>"
