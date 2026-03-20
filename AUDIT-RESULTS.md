# AgentVault — Security Audit Results

**Date:** 2026-03-20  
**Auditor:** Agent Erin (subagent)  
**Scope:** Pre-publication security review — scrub hardcoded secrets before GitHub release  

---

## Summary

**Status: CLEARED FOR PUBLICATION** ✅ (with fixes applied below)

Three findings were identified and fixed. No critical secrets (private keys, seed phrases, mainnet passphrases) remain in the codebase. The source code itself was clean; issues were in a test file and documentation.

---

## Findings

### 🔴 CRITICAL — Hardcoded Testnet Passphrase in Test File

**File:** `tests/test_testnet_live.py`  
**Line:** `TESTNET_PASSPHRASE = "[REDACTED]"` (real passphrase was hardcoded here)  
**Also in:** Module docstring run command: `AV_PASSPHRASE=[REDACTED] python3 -m pytest ...`

**Risk:** Real passphrase used to encrypt the testnet wallet published publicly. Anyone cloning the repo would have the passphrase for the testnet wallet. While testnet funds have no monetary value, this:
- Trains bad operational habits (passphrase in code)
- Would be a critical mistake if the same passphrase were ever reused for mainnet
- Demonstrates insecure practices in a security-focused library

**Fix Applied:**
- Replaced hardcoded passphrase string with `TESTNET_PASSPHRASE = os.environ.get("AV_PASSPHRASE", "")`
- Updated module docstring run command to use `AV_PASSPHRASE=<your-testnet-passphrase>`

---

### 🟡 MEDIUM — Passphrase Exposed in Documentation Run Command

**File:** `TESTING-LOG.md`  
**Section:** "Running live tests" — passphrase was hardcoded inline in the shell example command

**Risk:** Same passphrase as finding #1, embedded in developer documentation. Would be indexed by GitHub search.

**Fix Applied:**  
Replaced with `export AV_PASSPHRASE="your-testnet-passphrase"   # set before running — never commit this`

---

### 🟡 MEDIUM — Mainnet Wallet Address Identified in Documentation

**File:** `UTXO-FIX-RESULTS.md`  
**Line:** `bitcoincash:qzngmtjuyue6p93eqpq56w8auf25fezljqmn8wfw9t` labeled as `(Erin mainnet)`

**Risk:** Publishing the real mainnet wallet address with the identity label `(Erin mainnet)` in a public repository:
- Permanently associates this wallet address with this project and its operators
- Enables on-chain surveillance and deanonymization of future transactions from this address
- Creates a fingerprint that can be used to link otherwise unrelated transactions

**Fix Applied:**  
Replaced with `[redacted — mainnet wallet address]`

---

## Items Reviewed and Cleared

### Source Code (all clean ✅)

| File | Finding |
|------|---------|
| `agentvault/crypto.py` | No hardcoded secrets. Passphrase handling via PBKDF2. Constants only. |
| `agentvault/keystore.py` | Passphrase read from `AV_PASSPHRASE` env var only. No hardcoded values. |
| `agentvault/wallet.py` | No secrets. Delegates all key handling to KeyStore. |
| `agentvault/audit.py` | No secrets. Hash-chain only. |
| `agentvault/cli.py` | Passphrase via env var or interactive prompt. No hardcoded values. |
| `agentvault/__init__.py` | Metadata only. |

### Test Files

| File | Finding |
|------|---------|
| `tests/test_crypto.py` | Test passphrases (`"strong-test-passphrase-2026"`, etc.) are dummy values for unit testing encryption — not real credentials. **Safe.** |
| `tests/test_keystore.py` | Test passphrase `"test-passphrase-agentvault-2026"` is a dummy fixture value. **Safe.** |
| `tests/test_wallet.py` | `"test-wallet-passphrase-2026"` set via env var fixture — not a real wallet passphrase. **Safe.** |
| `tests/test_testnet_live.py` | **Fixed** — real passphrase removed. |
| `tests/test_audit.py` | No secrets. Hash/chain tests only. |

### BIP-39 Test Vectors (all safe ✅)

The `"abandon abandon abandon..."` mnemonic phrases throughout the test files are the **canonical BIP-39 test vectors** published by the BIP-39 specification authors. They appear in virtually every HD wallet implementation's test suite and are publicly known. They do not represent any real wallet.

### Configuration Files (all clean ✅)

| File | Finding |
|------|---------|
| `pyproject.toml` | No secrets. Build metadata only. |
| `README.md` | No secrets. References `AV_PASSPHRASE` env var correctly. |

### Documentation Files

| File | Finding |
|------|---------|
| `TESTING-LOG.md` | **Fixed** — passphrase removed from run command. Testnet addresses and TXIDs retained (testnet only, no real funds, valuable historical record). |
| `UTXO-FIX-RESULTS.md` | **Fixed** — mainnet wallet address redacted. Agent wallet addresses (Sentinel, Herald, Salesman) retained as they are receiving addresses used in documented test transactions. |

---

## .gitignore Created ✅

A comprehensive `.gitignore` was created at the repo root covering:

- `__pycache__/`, `*.egg-info/`, `dist/`, `build/` — Python artifacts
- `venv/`, `.venv/` — Virtual environments  
- `.env`, `.env.*` — Environment variable files (with passphrase)
- `keystore.json`, `*.keystore.json` — Encrypted wallet keystores
- `audit.log`, `*.log` — Audit logs (may contain wallet fingerprints)
- `nft_store.db` — Token store database
- `.agentvault/`, `.agentvault-testnet/`, `wallets/` — Wallet directories
- `.pytest_cache/`, `.coverage`, `htmlcov/` — Test artifacts
- `.idea/`, `.vscode/` — IDE files

---

## Security Posture — Source Code

The production source code has excellent security practices:

- ✅ Passphrase **never** stored on disk — env var only (`AV_PASSPHRASE`)
- ✅ Keystore file locked to `chmod 600` (owner read/write only)
- ✅ AES-256-GCM with random salt + nonce per encryption
- ✅ 600,000 PBKDF2 iterations (OWASP 2023 recommendation)
- ✅ Mnemonic never written to disk in plaintext (verified by unit test)
- ✅ Wrong passphrase raises `ValueError` — fail closed
- ✅ Address non-reuse enforced in `get_next_address()`

---

## Recommendations Before GitHub Publication

1. **Do not push `.agentvault-testnet/`** — contains the live keystore. Confirm it's excluded by `.gitignore`.
2. **Rotate the testnet passphrase** — even though it's testnet, best practice after any exposure.
3. **Consider adding `SECURITY.md`** — tell contributors how to report security issues privately.
4. **Consider adding `.env.example`** — template showing which env vars are needed, with placeholder values.

---

*Audit complete. Repository is clear for GitHub publication.*
