# SPDX-License-Identifier: FSL-1.1-MIT
import os
import stat
from pathlib import Path
import pytest
from mnemostroma.integration.tunnel import token


@pytest.fixture(autouse=True)
def mock_token_path(monkeypatch, tmp_path):
    # Изолируем путь к токену для всех тестов
    fake_token_path = tmp_path / "tunnel_token"
    monkeypatch.setattr(token, "TUNNEL_TOKEN_PATH", fake_token_path)
    return fake_token_path


def test_token_none_initially():
    # 1. get_tunnel_token() -> None если файл не существует
    assert token.get_tunnel_token() is None


def test_token_created_on_demand(mock_token_path):
    # 2. get_or_create создаёт файл при отсутствии
    assert not mock_token_path.exists()
    tok = token.get_or_create_tunnel_token()
    assert len(tok) > 0
    assert mock_token_path.exists()


def test_token_length():
    # 3. Токен минимум 32 символа
    tok = token.get_or_create_tunnel_token()
    assert len(tok) >= 32


@pytest.mark.skipif(os.name == "nt", reason="chmod 0o600 is unix-specific")
def test_token_permissions_unix(mock_token_path):
    # 4. Права файла 0o600 на Unix
    token.get_or_create_tunnel_token()
    mode = mock_token_path.stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_token_idempotency():
    # 5. get_or_create возвращает тот же токен при повторном вызове (идемпотентность)
    tok1 = token.get_or_create_tunnel_token()
    tok2 = token.get_or_create_tunnel_token()
    assert tok1 == tok2


def test_get_tunnel_token_returns_value():
    # 6. get_tunnel_token() -> строка если файл существует
    tok1 = token.get_or_create_tunnel_token()
    tok2 = token.get_tunnel_token()
    assert tok1 == tok2


def test_tunnel_token_isolated_from_ssetoken():
    # 7. tunnel_token != ssetoken (разные пути)
    # Наш реальный ssetoken лежит в ~/.mnemostroma/ssetoken
    ssetoken_path = Path.home() / ".mnemostroma" / "ssetoken"
    # Путь по умолчанию к tunnel_token должен быть другим
    # Восстановим оригинальный путь для проверки изоляции путей
    from importlib import reload
    reload(token)
    assert token.TUNNEL_TOKEN_PATH != ssetoken_path
    assert token.TUNNEL_TOKEN_PATH.name == "tunnel_token"
