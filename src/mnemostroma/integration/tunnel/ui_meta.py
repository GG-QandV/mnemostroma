# tunnel/ui_meta.py — UI-метаданные чатов.
# Единственный источник правды. Импортируется в tray.py и observe_handlers.py.
# Добавить новый чат: только сюда + новая запись в routes.json.

from typing import TypedDict


class ChatMeta(TypedDict):
    label:       str
    icon:        str
    hint:        str
    needs_token: bool  # True = клиент требует Bearer token (Grok)


CHAT_UI_META: dict[str, ChatMeta] = {
    "perplexity": {
        "label":       "Perplexity",
        "icon":        "🔍",
        "hint":        "Settings → AI Plugins → MCP URL",
        "needs_token": False,
    },
    "claude": {
        "label":       "Claude.ai",
        "icon":        "🤖",
        "hint":        "Settings → Integrations → Add Custom Connector",
        "needs_token": False,   # OAuth — токен не нужен пользователю
    },
    "chatgpt": {
        "label":       "ChatGPT",
        "icon":        "💬",
        "hint":        "Settings → Connectors → Add",
        "needs_token": False,   # OAuth
    },
    "grok": {
        "label":       "Grok",
        "icon":        "⚡",
        "hint":        "Settings → MCP Server URL + Bearer Token",
        "needs_token": True,    # Bearer — пользователь вставляет токен вручную
    },
    "cm": {
        "label":       "Context Memory",
        "icon":        "🧠",
        "hint":        "Settings → Custom connector → Streamable HTTP",
        "needs_token": False,
    },
}

# Fallback для неизвестных клиентов из routes.json
_GENERIC_META: ChatMeta = {
    "label":       "",   # заполняется через client.capitalize() на месте вызова
    "icon":        "🔗",
    "hint":        "Paste URL in MCP settings",
    "needs_token": False,
}


def get_meta(client: str) -> ChatMeta:
    """Возвращает метаданные клиента. Для unknown client — generic fallback."""
    if client in CHAT_UI_META:
        return CHAT_UI_META[client]
    return {**_GENERIC_META, "label": client.capitalize()}
