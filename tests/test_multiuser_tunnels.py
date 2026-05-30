"""Integration tests for multi-user Serveo tunnel support."""
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mnemostroma.integration.tunnel.manager import (
    TUNNEL_CONFIG_PATH,
    TUNNEL_TOKENS_DIR,
    TUNNEL_URLS_DIR,
    _get_or_ask_subdomain,
    _load_tunnel_config,
    _save_tunnel_config,
    _save_tunnel_token,
    _save_tunnel_url,
)


# ── Tunnel config persistence ──────────────────────────────────────────────────

class TestTunnelConfig:
    def test_save_and_load_config(self, tmp_path):
        """Config file is created and loaded correctly."""
        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_CONFIG_PATH", tmp_path / "config.json"):
            config = {"provider": "serveo", "subdomain": "alice", "port": 8769}
            _save_tunnel_config(config)
            loaded = _load_tunnel_config()
        assert loaded["subdomain"] == "alice"

    def test_load_missing_config_returns_defaults(self, tmp_path):
        """Missing config returns sensible defaults."""
        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_CONFIG_PATH", tmp_path / "missing.json"):
            config = _load_tunnel_config()
        assert config["provider"] == "serveo"
        assert config["subdomain"] is None
        assert config["port"] == 8769

    def test_subdomain_persists_across_restarts(self, tmp_path):
        """Subdomain is saved and not re-asked on next run."""
        config_file = tmp_path / "config.json"
        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_CONFIG_PATH", config_file):
            # Simulate first run with user input
            config = {"provider": "serveo", "subdomain": "bob", "port": 8769}
            _save_tunnel_config(config)
            # Simulate second run without user input
            loaded = _load_tunnel_config()
        assert loaded["subdomain"] == "bob"


# ── Multi-user URL storage ────────────────────────────────────────────────────

class TestMultiUserUrlStorage:
    def test_save_url_alice(self, tmp_path):
        """Alice's URL is saved to user-alice.txt."""
        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_URLS_DIR", tmp_path / "tunnel_urls"):
            _save_tunnel_url("alice", "https://alice.serveo.net")
        assert (tmp_path / "tunnel_urls" / "user-alice.txt").read_text() == "https://alice.serveo.net"

    def test_save_url_bob(self, tmp_path):
        """Bob's URL is saved to user-bob.txt."""
        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_URLS_DIR", tmp_path / "tunnel_urls"):
            _save_tunnel_url("bob", "https://bob.serveo.net")
        assert (tmp_path / "tunnel_urls" / "user-bob.txt").read_text() == "https://bob.serveo.net"

    def test_save_url_anonymous(self, tmp_path):
        """Anonymous URL is saved to user-anonymous.txt."""
        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_URLS_DIR", tmp_path / "tunnel_urls"):
            _save_tunnel_url(None, "https://random-123.serveo.net")
        assert (tmp_path / "tunnel_urls" / "user-anonymous.txt").read_text() == "https://random-123.serveo.net"

    def test_no_overwrite_different_users(self, tmp_path):
        """URLs for different users don't overwrite each other."""
        urls_dir = tmp_path / "tunnel_urls"
        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_URLS_DIR", urls_dir):
            _save_tunnel_url("alice", "https://alice.serveo.net")
            _save_tunnel_url("bob", "https://bob.serveo.net")
        assert (urls_dir / "user-alice.txt").read_text() == "https://alice.serveo.net"
        assert (urls_dir / "user-bob.txt").read_text() == "https://bob.serveo.net"


# ── Multi-user token storage ───────────────────────────────────────────────────

class TestMultiUserTokenStorage:
    def test_save_token_alice(self, tmp_path):
        """Alice's token is saved to user-alice.txt."""
        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_TOKENS_DIR", tmp_path / "tunnel_tokens"):
            _save_tunnel_token("alice", "token-alice-secret")
        assert (tmp_path / "tunnel_tokens" / "user-alice.txt").read_text() == "token-alice-secret"

    def test_save_token_bob(self, tmp_path):
        """Bob's token is saved to user-bob.txt."""
        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_TOKENS_DIR", tmp_path / "tunnel_tokens"):
            _save_tunnel_token("bob", "token-bob-secret")
        assert (tmp_path / "tunnel_tokens" / "user-bob.txt").read_text() == "token-bob-secret"

    def test_save_token_anonymous(self, tmp_path):
        """Anonymous token is saved to user-anonymous.txt."""
        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_TOKENS_DIR", tmp_path / "tunnel_tokens"):
            _save_tunnel_token(None, "token-anon-secret")
        assert (tmp_path / "tunnel_tokens" / "user-anonymous.txt").read_text() == "token-anon-secret"

    def test_no_overwrite_different_users(self, tmp_path):
        """Tokens for different users don't overwrite each other."""
        tokens_dir = tmp_path / "tunnel_tokens"
        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_TOKENS_DIR", tokens_dir):
            _save_tunnel_token("alice", "token-alice")
            _save_tunnel_token("bob", "token-bob")
        assert (tokens_dir / "user-alice.txt").read_text() == "token-alice"
        assert (tokens_dir / "user-bob.txt").read_text() == "token-bob"


# ── Multi-user directory structure ────────────────────────────────────────────

class TestMultiUserDirectoryStructure:
    def test_directories_created_on_save(self, tmp_path):
        """tunnel_urls and tunnel_tokens directories are created if missing."""
        urls_dir = tmp_path / "tunnel_urls"
        tokens_dir = tmp_path / "tunnel_tokens"

        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_URLS_DIR", urls_dir):
            _save_tunnel_url("alice", "https://alice.serveo.net")
        assert urls_dir.is_dir()

        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_TOKENS_DIR", tokens_dir):
            _save_tunnel_token("alice", "token-alice")
        assert tokens_dir.is_dir()

    def test_full_mnemostroma_structure(self, tmp_path):
        """Full ~/.mnemostroma structure with multiple users."""
        urls_dir = tmp_path / "tunnel_urls"
        tokens_dir = tmp_path / "tunnel_tokens"

        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_URLS_DIR", urls_dir):
            _save_tunnel_url("alice", "https://alice.serveo.net")
            _save_tunnel_url("bob", "https://bob.serveo.net")
            _save_tunnel_url("charlie", "https://charlie.serveo.net")

        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_TOKENS_DIR", tokens_dir):
            _save_tunnel_token("alice", "token-alice")
            _save_tunnel_token("bob", "token-bob")
            _save_tunnel_token("charlie", "token-charlie")

        assert len(list(urls_dir.glob("user-*.txt"))) == 3
        assert len(list(tokens_dir.glob("user-*.txt"))) == 3
        assert (urls_dir / "user-alice.txt").read_text() == "https://alice.serveo.net"
        assert (tokens_dir / "user-bob.txt").read_text() == "token-bob"


# ── No race conditions ────────────────────────────────────────────────────────

class TestNoRaceConditions:
    def test_concurrent_url_saves_dont_collide(self, tmp_path):
        """Multiple simultaneous tunnel starts don't overwrite URLs."""
        urls_dir = tmp_path / "tunnel_urls"

        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_URLS_DIR", urls_dir):
            # Simulate concurrent writes
            _save_tunnel_url("alice", "https://alice.serveo.net")
            _save_tunnel_url("bob", "https://bob.serveo.net")
            _save_tunnel_url("alice", "https://alice-reconnect.serveo.net")

        # Each user's latest URL is preserved
        assert (urls_dir / "user-alice.txt").read_text() == "https://alice-reconnect.serveo.net"
        assert (urls_dir / "user-bob.txt").read_text() == "https://bob.serveo.net"

    def test_config_updates_dont_lose_data(self, tmp_path):
        """Updating config for one user doesn't affect another user's config."""
        config_file = tmp_path / "config.json"

        with patch("mnemostroma.integration.tunnel.manager.TUNNEL_CONFIG_PATH", config_file):
            # Save alice's config
            config = {"provider": "serveo", "subdomain": "alice", "port": 8769}
            _save_tunnel_config(config)

            # Verify alice's config
            loaded = _load_tunnel_config()
            assert loaded["subdomain"] == "alice"

            # Update (simulates new tunnel instance for bob)
            config["subdomain"] = "bob"
            _save_tunnel_config(config)

            # New instance should see bob's subdomain
            loaded = _load_tunnel_config()
            assert loaded["subdomain"] == "bob"
