# tunnel/state.py — единственный читатель URL и token для всего UI слоя.
# Не пишет ничего. Только читает.
# Latency: <1ms (disk read).

import logging
from pathlib import Path

logger = logging.getLogger("mnemostroma.tunnel.state")

_MNEMO_DIR         = Path.home() / ".mnemostroma"
_TUNNEL_URL_FILE   = _MNEMO_DIR / "tunnel_url"


def get_tunnel_url() -> str | None:
    """
    Читает URL активного туннеля из flat-файла.
    Возвращает None если туннель не запущен или файл отсутствует.
    """
    try:
        url = _TUNNEL_URL_FILE.read_text(encoding="utf-8").strip()
        return url if url else None
    except FileNotFoundError:
        return None
    except OSError as e:
        logger.warning("tunnel_url read error: %s", e)
        return None


def get_tunnel_token() -> str | None:
    """
    Читает Bearer token туннеля через официальный API.
    Единственный источник правды — tunnel/token.py пишет этот файл.
    """
    try:
        from mnemostroma.integration.tunnel.token import get_tunnel_token as _get
        return _get()
    except Exception as e:
        logger.warning("tunnel_token read error: %s", e)
        return None
