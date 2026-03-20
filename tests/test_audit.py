"""
Tests for audit.py — the hash-chained audit log.

The audit trail is a security and compliance feature.
These tests verify that tampering is always detected.
"""

import os
import json
import pytest
import tempfile
import shutil

from agentvault.audit import AuditLog


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def log(tmp_dir):
    return AuditLog(os.path.join(tmp_dir, "audit.log"))


class TestAuditLogBasics:

    def test_creates_log_file(self, tmp_dir):
        path = os.path.join(tmp_dir, "test.log")
        AuditLog(path)
        assert os.path.exists(path)

    def test_log_entry_is_written(self, log, tmp_dir):
        log.log("test_action", {"key": "value"})
        entries = log.entries()
        assert len(entries) == 1
        assert entries[0]["action"] == "test_action"

    def test_log_entry_has_required_fields(self, log):
        log.log("test", {"foo": "bar"})
        entry = log.entries()[0]
        assert "timestamp" in entry
        assert "seq" in entry
        assert "action" in entry
        assert "details" in entry
        assert "prev_hash" in entry
        assert "hash" in entry

    def test_sequential_numbers_increment(self, log):
        for i in range(5):
            log.log(f"action_{i}", {})
        entries = log.entries()
        seqs = [e["seq"] for e in entries]
        assert seqs == [1, 2, 3, 4, 5]

    def test_first_entry_prev_hash_is_genesis(self, log):
        log.log("first", {})
        entry = log.entries()[0]
        assert entry["prev_hash"] == AuditLog.GENESIS_HASH

    def test_chain_links_entries(self, log):
        log.log("first", {})
        log.log("second", {})
        entries = log.entries()
        assert entries[1]["prev_hash"] == entries[0]["hash"]

    def test_details_preserved(self, log):
        log.log("send", {"to": "bitcoincash:qp...", "amount": 0.001})
        entry = log.entries()[0]
        assert entry["details"]["to"] == "bitcoincash:qp..."
        assert entry["details"]["amount"] == 0.001

    def test_policy_result_stored(self, log):
        log.log("send", {}, policy_result={"passed": True, "remaining": 0.9})
        entry = log.entries()[0]
        assert entry["policy_result"]["passed"] is True


class TestAuditLogIntegrity:

    def test_empty_log_is_valid(self, log):
        valid, err = log.verify()
        assert valid is True
        assert err is None

    def test_single_entry_is_valid(self, log):
        log.log("action", {})
        valid, err = log.verify()
        assert valid is True

    def test_100_entries_chain_is_valid(self, log):
        for i in range(100):
            log.log(f"action_{i}", {"i": i})
        valid, err = log.verify()
        assert valid is True

    def test_tampered_hash_detected(self, log, tmp_dir):
        """Modifying a hash should break the chain verification."""
        log.log("action1", {})
        log.log("action2", {})
        log.log("action3", {})

        # Read and tamper with entry #2's hash
        path = os.path.join(tmp_dir, "audit.log")
        lines = path and open(log._path).readlines()
        entry2 = json.loads(lines[1])
        entry2["hash"] = "a" * 64  # Replace hash with garbage
        lines[1] = json.dumps(entry2, separators=(',', ':')) + '\n'
        log._path.write_text(''.join(lines))

        valid, err = log.verify()
        assert valid is False
        assert err is not None

    def test_tampered_content_detected(self, log, tmp_dir):
        """Modifying entry content (not hash) should break verification."""
        log.log("send", {"amount": 0.001, "to": "addr1"})
        log.log("send", {"amount": 0.002, "to": "addr2"})

        # Tamper with the amount in entry #1
        lines = log._path.open().readlines()
        entry1 = json.loads(lines[0])
        entry1["details"]["amount"] = 999.999  # Change the amount
        lines[0] = json.dumps(entry1, separators=(',', ':')) + '\n'
        log._path.write_text(''.join(lines))

        valid, err = log.verify()
        assert valid is False
        assert "modified" in err.lower() or "mismatch" in err.lower()

    def test_deleted_entry_detected(self, log):
        """Removing an entry breaks the chain."""
        for i in range(5):
            log.log(f"action_{i}", {})

        # Delete entry #3 (middle of chain)
        lines = log._path.open().readlines()
        del lines[2]
        log._path.write_text(''.join(lines))

        valid, err = log.verify()
        assert valid is False

    def test_prev_hash_tampering_detected(self, log):
        """Changing prev_hash in an entry breaks verification."""
        log.log("action1", {})
        log.log("action2", {})

        lines = log._path.open().readlines()
        entry2 = json.loads(lines[1])
        entry2["prev_hash"] = "b" * 64  # Wrong prev_hash
        lines[1] = json.dumps(entry2, separators=(',', ':')) + '\n'
        log._path.write_text(''.join(lines))

        valid, err = log.verify()
        assert valid is False


class TestAuditLogQuerying:

    def test_query_by_action(self, log):
        log.log("send", {"amount": 1})
        log.log("receive", {"amount": 2})
        log.log("send", {"amount": 3})
        sends = log.entries(action="send")
        assert len(sends) == 2
        assert all(e["action"] == "send" for e in sends)

    def test_query_limit(self, log):
        for i in range(20):
            log.log(f"action", {"i": i})
        limited = log.entries(limit=5)
        assert len(limited) == 5
        # Should be the 5 most recent
        assert limited[-1]["details"]["i"] == 19

    def test_query_since(self, log):
        from datetime import datetime, timezone, timedelta
        log.log("old_action", {})
        # All entries are recent so this tests the filtering logic
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        entries = log.entries(since=future)
        assert len(entries) == 0

    def test_empty_log_returns_empty_list(self, log):
        assert log.entries() == []
