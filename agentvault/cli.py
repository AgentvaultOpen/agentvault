"""
cli.py — Command-line interface for AgentVault.

The CLI wraps the Python API. Every command calls Wallet methods.
No logic lives here that doesn't belong in the library.

Usage:
    agentvault init
    agentvault balance
    agentvault address
    agentvault send <address> <amount> <currency>
    agentvault mint-nft --commitment <hex>
    agentvault reveal-mnemonic
    agentvault reveal-key
    agentvault audit log
    agentvault audit verify
"""

import os
import sys
import json
import click
from typing import Optional

from agentvault.wallet import Wallet, DEFAULT_WALLET_DIR


# ── CLI Group ─────────────────────────────────────────────────────────────────

@click.group()
@click.option('--wallet-dir', default=DEFAULT_WALLET_DIR,
              envvar='AV_WALLET_DIR',
              show_default=True,
              help='Wallet directory (or set AV_WALLET_DIR)')
@click.option('--testnet', is_flag=True, default=False,
              help='Use BCH testnet (chipnet/testnet4)')
@click.pass_context
def cli(ctx, wallet_dir, testnet):
    """
    AgentVault — CashTokens Wallet for Autonomous AI Agents

    A Bitcoin Cash wallet designed for headless Linux servers and AI agents.
    Supports CashTokens (NFTs + fungible tokens), encrypted key storage,
    and cryptographic audit trails.

    \b
    Quick start:
        agentvault init          Create a new wallet
        agentvault balance       Check your balance
        agentvault address       Get your receiving address
    """
    ctx.ensure_object(dict)
    ctx.obj['wallet_dir'] = wallet_dir
    ctx.obj['testnet'] = testnet


# ── init ──────────────────────────────────────────────────────────────────────

@cli.command()
@click.option('--import-mnemonic', is_flag=True, default=False,
              help='Import an existing mnemonic phrase instead of generating one')
@click.option('--words', type=click.Choice(['12', '24']), default='24',
              help='Mnemonic word count (ignored if --import-mnemonic)')
@click.pass_context
def init(ctx, import_mnemonic, words):
    """Create a new AgentVault wallet.

    \b
    ⚠️  IMPORTANT: You will be shown your mnemonic phrase ONCE.
    Write it down immediately and store it safely.
    This is the only way to recover your wallet if the machine fails.

    \b
    Recommended backup strategy:
      1. Store in 1Password
      2. Write on paper and store in a fireproof safe
      3. Never store unencrypted on any internet-connected device
    """
    wallet_dir = ctx.obj['wallet_dir']
    testnet    = ctx.obj['testnet']

    if os.path.exists(os.path.join(wallet_dir, "keystore.json")):
        click.echo("❌  Wallet already exists at: " + wallet_dir)
        click.echo("    Delete it first if you want to create a new one.")
        sys.exit(1)

    mnemonic = None
    if import_mnemonic:
        mnemonic = click.prompt(
            "Enter your mnemonic phrase",
            hide_input=True,
            confirmation_prompt=False
        )

    passphrase = os.environ.get('AV_PASSPHRASE')
    if not passphrase:
        passphrase = click.prompt(
            "Set wallet passphrase (or set AV_PASSPHRASE env var)",
            hide_input=True,
            confirmation_prompt=True
        )
        click.echo("\n💡 Tip: Set AV_PASSPHRASE in your environment to avoid typing it.")

    try:
        click.echo(f"\n🔐 Creating wallet in: {wallet_dir}")
        if testnet:
            click.echo("🧪 Using TESTNET — no real funds involved")

        wallet, phrase = Wallet.create(
            wallet_dir=wallet_dir,
            passphrase=passphrase,
            mnemonic=mnemonic,
            testnet=testnet,
        )

        click.echo(f"\n✅ Wallet created! Fingerprint: {wallet.fingerprint}")
        click.echo(f"   Address: {wallet.address}")

        if not import_mnemonic:
            click.echo("\n" + "═" * 60)
            click.echo("🔑  YOUR MNEMONIC PHRASE")
            click.echo("═" * 60)
            words_list = phrase.split()
            for i, word in enumerate(words_list, 1):
                click.echo(f"  {i:2d}. {word}")
            click.echo("═" * 60)
            click.echo("✅ This phrase is stored encrypted in your keystore.")
            click.echo("   Retrieve it anytime with: agentvault reveal-mnemonic")
            click.echo("   Back it up to offline storage as a recovery option.")
            click.echo("   Anyone with this phrase has full access to this wallet.")
            click.echo("═" * 60)

    except Exception as e:
        click.echo(f"❌  Error creating wallet: {e}", err=True)
        sys.exit(1)


# ── balance ───────────────────────────────────────────────────────────────────

@cli.command()
@click.option('--json-output', is_flag=True, help='Output as JSON')
@click.pass_context
def balance(ctx, json_output):
    """Check BCH balance and token holdings."""
    wallet = _load_wallet(ctx)
    try:
        result = wallet.balance()
        if json_output:
            click.echo(json.dumps(result, indent=2))
        else:
            net = "TESTNET" if result['testnet'] else "MAINNET"
            click.echo(f"\n💰 AgentVault Balance ({net})")
            click.echo(f"   Address:  {result['address']}")
            click.echo(f"   BCH:      {result['bch']:.8f} BCH")
            click.echo(f"   Satoshis: {result['bch_satoshis']:,}")
            if result.get('tokens'):
                click.echo(f"   Tokens:   {len(result['tokens'])} holdings")
            else:
                click.echo("   Tokens:   None")
    except Exception as e:
        click.echo(f"❌  {e}", err=True)
        sys.exit(1)


# ── address ───────────────────────────────────────────────────────────────────

@cli.command()
@click.option('--fresh', is_flag=True,
              help='Generate a fresh unused address (privacy: never reuse)')
@click.pass_context
def address(ctx, fresh):
    """Show receiving address."""
    wallet = _load_wallet(ctx)
    if fresh:
        addr = wallet.fresh_address()
        click.echo(f"🆕 Fresh address: {addr}")
    else:
        click.echo(f"📬 Address: {wallet.address}")


# ── send ──────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument('to_address')
@click.argument('amount', type=float)
@click.argument('currency', default='bch')
@click.option('--memo', default=None, help='Internal memo (not broadcast)')
@click.option('--yes', is_flag=True, help='Skip confirmation prompt')
@click.pass_context
def send(ctx, to_address, amount, currency, memo, yes):
    """Send BCH to an address.

    \b
    Examples:
        agentvault send bitcoincash:qp... 0.001 bch
        agentvault send bitcoincash:qp... 1000 satoshi
        agentvault send bitcoincash:qp... 5.00 usd
    """
    wallet = _load_wallet(ctx)

    if not yes:
        click.echo(f"\n📤 Sending {amount} {currency.upper()} to:")
        click.echo(f"   {to_address}")
        if memo:
            click.echo(f"   Memo: {memo}")
        if not click.confirm("\nConfirm?"):
            click.echo("Cancelled.")
            return

    try:
        txid = wallet.send(to_address, amount, currency, memo=memo)
        click.echo(f"\n✅ Transaction broadcast!")
        click.echo(f"   TXID: {txid}")
        click.echo(f"   View: https://explorer.bitcoin.com/bch/tx/{txid}")
    except Exception as e:
        click.echo(f"❌  Send failed: {e}", err=True)
        sys.exit(1)


# ── mint-nft ──────────────────────────────────────────────────────────────────

@cli.command('mint-nft')
@click.option('--commitment', required=True,
              help='NFT commitment data as hex string or plain text')
@click.option('--capability', default='none',
              type=click.Choice(['none', 'mutable', 'minting']),
              help='NFT capability (none=immutable, mutable, minting)')
@click.option('--to', 'recipient', default=None,
              help='Recipient address (default: self)')
@click.option('--text', is_flag=True,
              help='Treat --commitment as plain text instead of hex')
@click.option('--yes', is_flag=True, help='Skip confirmation')
@click.pass_context
def mint_nft(ctx, commitment, capability, recipient, text, yes):
    """Mint a CashTokens NFT.

    \b
    Examples:
        # Immutable NFT with hex data
        agentvault mint-nft --commitment deadbeef

        # Mutable NFT with text commitment
        agentvault mint-nft --commitment "agent-erin-v1" --text --capability mutable

        # Minting NFT (can create more of same category)
        agentvault mint-nft --commitment 00 --capability minting
    """
    wallet = _load_wallet(ctx)

    if text:
        commitment_bytes = commitment.encode('utf-8')
    else:
        try:
            commitment_bytes = bytes.fromhex(commitment)
        except ValueError:
            click.echo("❌  Invalid hex commitment. Use --text flag for plain text.", err=True)
            sys.exit(1)

    if len(commitment_bytes) > 40:
        click.echo(f"❌  Commitment too long: {len(commitment_bytes)} bytes (max 40).", err=True)
        sys.exit(1)

    if not yes:
        click.echo(f"\n🎨 Minting NFT:")
        click.echo(f"   Commitment: {commitment_bytes.hex()} ({len(commitment_bytes)} bytes)")
        click.echo(f"   Capability: {capability}")
        if recipient:
            click.echo(f"   Recipient:  {recipient}")
        if not click.confirm("\nConfirm?"):
            click.echo("Cancelled.")
            return

    try:
        txid = wallet.mint_nft(commitment_bytes, capability, recipient=recipient)
        click.echo(f"\n✅ NFT minted!")
        click.echo(f"   TXID: {txid}")
        click.echo(f"   View: https://explorer.bitcoin.com/bch/tx/{txid}")
    except Exception as e:
        click.echo(f"❌  Mint failed: {e}", err=True)
        sys.exit(1)


# ── reveal-mnemonic ───────────────────────────────────────────────────────────

@cli.command('reveal-mnemonic')
@click.option('--passphrase', default=None, envvar='AV_PASSPHRASE',
              help='Wallet passphrase (or set AV_PASSPHRASE)')
@click.pass_context
def reveal_mnemonic(ctx, passphrase):
    """Reveal your wallet's seed phrase.

    \b
    The seed phrase is always stored encrypted in your keystore.
    Use this to back up to Electron Cash or any BIP39-compatible wallet.

    \b
    Examples:
        agentvault reveal-mnemonic
        AV_PASSPHRASE=mypass agentvault reveal-mnemonic
    """
    wallet = _load_wallet(ctx)

    if not passphrase:
        passphrase = click.prompt("Enter wallet passphrase", hide_input=True)

    try:
        mnemonic = wallet.reveal_mnemonic(passphrase)
        words_list = mnemonic.split()
        click.echo("\n" + "═" * 60)
        click.echo("🔑  SEED PHRASE")
        click.echo("═" * 60)
        for i, word in enumerate(words_list, 1):
            click.echo(f"  {i:2d}. {word}")
        click.echo("═" * 60)
        click.echo(f"   {len(words_list)} words | BIP39 | Derivation: m/44'/145'/0'")
        click.echo("   Import into Electron Cash: Wallet > New > I already have a seed")
        click.echo("═" * 60)
    except ValueError:
        click.echo("❌  Incorrect passphrase.", err=True)
        sys.exit(1)


# ── reveal-key ────────────────────────────────────────────────────────────────

@cli.command('reveal-key')
@click.option('--passphrase', default=None, envvar='AV_PASSPHRASE',
              help='Wallet passphrase (or set AV_PASSPHRASE)')
@click.option('--account', default=0, show_default=True, help='BIP44 account index')
@click.option('--change', default=0, show_default=True, help='BIP44 change index')
@click.option('--index', default=0, show_default=True, help='BIP44 address index')
@click.pass_context
def reveal_key(ctx, passphrase, account, change, index):
    """Reveal the private key (WIF) for a derivation path.

    \b
    The primary key is at account=0, change=0, index=0 (default).
    Use this to import directly into Electron Cash via private key.

    \b
    Examples:
        agentvault reveal-key
        agentvault reveal-key --index 1
    """
    wallet = _load_wallet(ctx)

    if not passphrase:
        passphrase = click.prompt("Enter wallet passphrase", hide_input=True)

    try:
        wif = wallet.reveal_private_key(passphrase, account, change, index)
        path = f"m/44'/145'/{account}'/{change}/{index}"
        click.echo("\n" + "═" * 60)
        click.echo("🔑  PRIVATE KEY (WIF)")
        click.echo("═" * 60)
        click.echo(f"   Path:    {path}")
        click.echo(f"   Address: {wallet.address}")
        click.echo(f"   WIF:     {wif}")
        click.echo("═" * 60)
        click.echo("   Import into Electron Cash: Wallet > New > Import private keys")
        click.echo("═" * 60)
    except ValueError:
        click.echo("❌  Incorrect passphrase.", err=True)
        sys.exit(1)


# ── audit ─────────────────────────────────────────────────────────────────────

@cli.group()
def audit():
    """Audit log commands."""
    pass


@audit.command('log')
@click.option('--since', default=None, help='Show entries since ISO datetime')
@click.option('--action', default=None, help='Filter by action type')
@click.option('--limit', default=20, show_default=True, help='Max entries to show')
@click.option('--json-output', is_flag=True, help='Output as JSON')
@click.pass_context
def audit_log(ctx, since, action, limit, json_output):
    """View audit log entries."""
    wallet = _load_wallet(ctx)
    entries = wallet.audit_log(since=since, action=action, limit=limit)

    if json_output:
        click.echo(json.dumps(entries, indent=2))
    else:
        click.echo(f"\n📋 Audit Log (last {limit} entries)")
        click.echo("─" * 60)
        for e in entries:
            ts = e['timestamp'][:19].replace('T', ' ')
            action_str = e['action'].replace('_', ' ').upper()
            details = e.get('details', {})
            line = f"  {ts}  {action_str}"
            if 'txid' in details:
                line += f"  txid:{details['txid'][:16]}..."
            elif 'to' in details:
                line += f"  → {details['to'][:20]}..."
            elif 'address' in details:
                line += f"  addr:{details['address'][:20]}..."
            click.echo(line)
        click.echo("─" * 60)


@audit.command('verify')
@click.pass_context
def audit_verify(ctx):
    """Verify the integrity of the audit log."""
    wallet = _load_wallet(ctx)
    valid, error = wallet.verify_audit()
    if valid:
        click.echo("✅ Audit log integrity verified — chain is intact.")
    else:
        click.echo(f"🚨 AUDIT LOG INTEGRITY FAILURE: {error}", err=True)
        sys.exit(1)


# ── info ──────────────────────────────────────────────────────────────────────

@cli.command()
@click.pass_context
def info(ctx):
    """Show wallet info."""
    wallet = _load_wallet(ctx)
    net = "TESTNET" if wallet.is_testnet else "MAINNET"
    click.echo(f"\n🔐 AgentVault Wallet")
    click.echo(f"   Network:     {net}")
    click.echo(f"   Fingerprint: {wallet.fingerprint}")
    click.echo(f"   Address:     {wallet.address}")
    click.echo(f"   Version:     0.1.0")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_wallet(ctx) -> Wallet:
    """Load wallet from context, handling errors cleanly."""
    wallet_dir = ctx.obj['wallet_dir']
    testnet    = ctx.obj['testnet']
    try:
        return Wallet.load(wallet_dir, testnet=testnet)
    except FileNotFoundError:
        click.echo(f"❌  No wallet found at: {wallet_dir}", err=True)
        click.echo("    Create one with: agentvault init", err=True)
        sys.exit(1)
    except EnvironmentError as e:
        click.echo(f"❌  {e}", err=True)
        sys.exit(1)
    except ValueError as e:
        click.echo(f"❌  {e}", err=True)
        sys.exit(1)


def main():
    cli(obj={})


if __name__ == '__main__':
    main()
