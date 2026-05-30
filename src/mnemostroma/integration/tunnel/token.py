# tunnel/token.py — управление tunnel_token (изолирован от ssetoken)
import os
import secrets
from pathlib import Path

TUNNEL_TOKEN_PATH = Path.home() / ".mnemostroma" / "tunnel_token"


def get_or_create_tunnel_token() -> str:
    if TUNNEL_TOKEN_PATH.exists():
        return TUNNEL_TOKEN_PATH.read_text(encoding="utf-8").strip()
    token = secrets.token_urlsafe(32)
    TUNNEL_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TUNNEL_TOKEN_PATH.write_text(token, encoding="utf-8")
    TUNNEL_TOKEN_PATH.chmod(0o600)
    return token


def get_tunnel_token() -> str | None:
    if TUNNEL_TOKEN_PATH.exists():
        return TUNNEL_TOKEN_PATH.read_text(encoding="utf-8").strip()
    return None
