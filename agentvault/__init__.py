"""
AgentVault — A CashTokens Wallet for Autonomous AI Agents on Bitcoin Cash

Founding Document: March 17, 2026
Authors: Dirk Jenkins (CEO), Agent Erin (Chief of Staff)

Ad Maiorem Dei Gloriam
"""

__version__ = "0.1.0"
__author__ = "Dirk Jenkins & Agent Erin"
__license__ = "MIT"

from agentvault.wallet import Wallet
from agentvault.keystore import EncryptedFileKeyStore
from agentvault.audit import AuditLog
from agentvault.messaging import APMPMessage
from agentvault.inbox import AgentInbox, InboxMessage

__all__ = [
    "Wallet",
    "EncryptedFileKeyStore",
    "AuditLog",
    "APMPMessage",
    "AgentInbox",
    "InboxMessage",
]
