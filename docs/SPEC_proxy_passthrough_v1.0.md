# Spec: Proxy Passthrough v1.0

> Status: Draft | Date: 2026-04-10
> Phase: 12.A
> Depends on: mcp_sse_adapter.py (run()), mcp_stdio_adapter.py (current_session write, Spec 12.B)

---

## 1. Overview

Claude Code нельзя направить через `http://localhost` — валидация отклоняет не-HTTPS адреса. Решение: пассивный HTTPS-прокси на `localhost:8767` с self-signed сертификатом, которому Claude Code доверяет через `NODE_EXTRA_CA_CERTS`.

Прокси прозрачно проксирует все Anthropic API запросы и параллельно отправляет текст ответа в Observer через daemon socket. Агент не знает о прокси. System prompt и тело запроса не трогаются.

---

## 2. Архитектура

```
Claude Code
  │
  ├─ ANTHROPIC_BASE_URL=https://localhost:8767 ──→ proxy_passthrough.py (TLS)
  │                                                   │ forward прозрачно
  │                                                   │ собирает SSE-чанки
  │                                                   │ читает current_session
  │                                                   └─→ ipc_call("observe") → daemon.sock
  │
  └─ mcp_stdio_adapter ─────────────────────────→ daemon.sock (читает память)
```

---

## 3. TLS — генерация при `mnemostroma setup`

### Зависимость

```toml
# pyproject.toml — добавить в [project.optional-dependencies]
sse = [
    "starlette>=0.36",
    "uvicorn>=0.27",
    "httpx>=0.27",
    "cryptography>=42.0",   # NEW — только для sse-extra
]
```

`cryptography` не попадает в core-зависимости.

### Генерация сертификата

**Файл:** `src/mnemostroma/setup/tls.py` (новый, ~50 строк)

```python
"""Generate self-signed CA + server cert for proxy_passthrough TLS."""
from __future__ import annotations
import datetime
from pathlib import Path

def generate_passthrough_tls(mnemo_dir: Path) -> tuple[Path, Path, Path]:
    """Generate CA cert + server cert/key into mnemo_dir.

    Returns (ca_cert_path, server_cert_path, server_key_path).
    Idempotent — skips if all three files already exist.
    """
    ca_cert_path   = mnemo_dir / "passthrough-ca.pem"
    cert_path      = mnemo_dir / "passthrough-cert.pem"
    key_path       = mnemo_dir / "passthrough-key.pem"

    if ca_cert_path.exists() and cert_path.exists() and key_path.exists():
        return ca_cert_path, cert_path, key_path

    from cryptography import x509
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    now = datetime.datetime.utcnow()
    expire = now + datetime.timedelta(days=3650)

    # CA key + cert
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mnemostroma Local CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name).issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now).not_valid_after(expire)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    # Server key + cert signed by CA
    srv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    srv_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    srv_cert = (
        x509.CertificateBuilder()
        .subject_name(srv_name).issuer_name(ca_name)
        .public_key(srv_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now).not_valid_after(expire)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    pem = serialization.Encoding.PEM
    ca_cert_path.write_bytes(ca_cert.public_bytes(pem))
    cert_path.write_bytes(srv_cert.public_bytes(pem))
    key_path.write_bytes(
        srv_key.private_bytes(pem, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())
    )
    key_path.chmod(0o600)

    return ca_cert_path, cert_path, key_path
```

### Интеграция в `_cmd_setup()` (**`__main__.py`**)

После существующего шага 7 (DB note):

```python
    # 8. TLS cert для proxy_passthrough (только если sse-зависимости установлены)
    try:
        from mnemostroma.setup.tls import generate_passthrough_tls
        ca, _, _ = generate_passthrough_tls(_MNEMO_DIR)
        print(f"  ✓ TLS cert:  {ca.parent}  (passthrough-ca/cert/key.pem)")
    except ImportError:
        print(f"  ~ TLS cert:  skipped  (pip install mnemostroma[sse] to enable)")
```

---

## 4. proxy_passthrough.py

**Файл:** `src/mnemostroma/integration/proxy_passthrough.py` (новый, ~70 строк)

```python
# SPDX-License-Identifier: FSL-1.1-MIT
"""Passthrough HTTPS proxy for Claude Code → Anthropic API.

Forwards all requests transparently. For POST /v1/messages:
collects response text (streaming or JSON) and fires observe() to daemon.

Entry: make_passthrough_app() → called from mcp_sse_adapter.run().
"""
import asyncio
import json
import logging
from datetime import date
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from .mcp_stdio_adapter import _ipc_call

logger = logging.getLogger("mnemostroma.passthrough")

_MNEMO_DIR    = Path.home() / ".mnemostroma"
_SESSION_FILE = _MNEMO_DIR / "current_session"
_UPSTREAM     = "https://api.anthropic.com"


def _current_session() -> str:
    try:
        sid = _SESSION_FILE.read_text(encoding="utf-8").strip()
        if sid:
            return sid
    except OSError:
        pass
    sid = f"passthrough-{date.today().isoformat()}"
    logger.warning("current_session missing — using fallback: %s", sid)
    return sid


async def _observe(text: str) -> None:
    if not text.strip():
        return
    try:
        await _ipc_call("observe", {"session_id": _current_session(), "text": text})
    except Exception as exc:
        logger.debug("observe failed: %s", exc)


async def handle_request(request: Request) -> Response:
    body = await request.body()
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "accept-encoding")
    }
    headers["accept-encoding"] = "identity"

    url = _UPSTREAM + request.url.path
    if request.url.query:
        url += "?" + request.url.query

    is_messages = request.method == "POST" and "/v1/messages" in request.url.path

    async with httpx.AsyncClient(timeout=300) as client:
        upstream = await client.send(
            client.build_request(request.method, url, headers=headers, content=body),
            stream=True,
        )

        content_type = upstream.headers.get("content-type", "")

        if "text/event-stream" in content_type:
            chunks: list[str] = []

            async def stream_chunks():
                async for chunk in upstream.aiter_text():
                    yield chunk
                    if is_messages:
                        # extract delta.text from SSE data lines
                        for line in chunk.splitlines():
                            if line.startswith("data:"):
                                try:
                                    ev = json.loads(line[5:].strip())
                                    chunks.append(ev.get("delta", {}).get("text", ""))
                                except (json.JSONDecodeError, AttributeError):
                                    pass
                if is_messages:
                    asyncio.create_task(_observe("".join(chunks)))

            return StreamingResponse(
                stream_chunks(),
                status_code=upstream.status_code,
                headers=dict(upstream.headers),
                media_type=content_type,
            )

        else:
            raw = await upstream.aread()
            if is_messages:
                try:
                    text = json.loads(raw).get("content", [{}])[0].get("text", "")
                    asyncio.create_task(_observe(text))
                except Exception:
                    pass
            return Response(
                content=raw,
                status_code=upstream.status_code,
                headers=dict(upstream.headers),
                media_type=content_type,
            )


def make_passthrough_app() -> Starlette:
    return Starlette(routes=[Route("/{path:path}", endpoint=handle_request, methods=["GET", "POST", "PUT", "DELETE", "PATCH"])])
```

---

## 5. Интеграция в `mcp_sse_adapter.run()`

**Файл:** `src/mnemostroma/integration/mcp_sse_adapter.py`

```python
# Добавить импорт:
from .proxy_passthrough import make_passthrough_app

# В run() — добавить 2 строки:
async def run():
    logging.basicConfig(level=logging.INFO)
    ca_cert  = _MNEMO_DIR / "passthrough-ca.pem"
    srv_cert = _MNEMO_DIR / "passthrough-cert.pem"
    srv_key  = _MNEMO_DIR / "passthrough-key.pem"

    mcp_config  = uvicorn.Config(make_mcp_app(),         host="0.0.0.0",   port=8765, log_level="info")
    obs_config  = uvicorn.Config(make_observe_app(),     host="127.0.0.1", port=8766, log_level="info")
    pass_config = uvicorn.Config(                                                          # NEW
        make_passthrough_app(), host="127.0.0.1", port=8767, log_level="warning",          # NEW
        ssl_certfile=str(srv_cert), ssl_keyfile=str(srv_key),                              # NEW
    )                                                                                       # NEW

    await asyncio.gather(
        uvicorn.Server(mcp_config).serve(),
        uvicorn.Server(obs_config).serve(),
        uvicorn.Server(pass_config).serve(),   # NEW
    )
```

Если cert-файлы отсутствуют (sse не установлен) — `pass_config` не создаётся, `gather` без третьего сервера.

Рекомендуемая проверка перед созданием `pass_config`:

```python
    if srv_cert.exists() and srv_key.exists():
        pass_config = uvicorn.Config(...)
        servers.append(uvicorn.Server(pass_config))
```

---

## 6. Конфигурация Claude Code

```bash
# ~/.profile или ~/.bashrc — добавить два экспорта:
export ANTHROPIC_BASE_URL=https://localhost:8767
export NODE_EXTRA_CA_CERTS=~/.mnemostroma/passthrough-ca.pem
```

Альтернатива без env — через `~/.claude.json`:

```json
{ "apiBaseUrl": "https://localhost:8767" }
```

`NODE_EXTRA_CA_CERTS` всё равно нужен — без него Node.js отклонит self-signed cert.

Проверка:

```bash
curl --cacert ~/.mnemostroma/passthrough-ca.pem https://localhost:8767/v1/models \
  -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01"
# → 200 OK с данными от api.anthropic.com
```

---

## 7. `config.json` — новое поле

```json
"passthrough": {
    "upstream": "https://api.anthropic.com",
    "port": 8767
}
```

`proxy_passthrough.py` читает `upstream` из конфига (fallback: константа `_UPSTREAM`).

---

## 8. Метрики в `observer_metrics`

```python
passthrough_requests   int   # всего запросов через :8767
passthrough_observed   int   # успешно отправлено в observe()
passthrough_skipped    int   # non-messages endpoints
passthrough_errors     int   # ошибки upstream или ipc
```

---

## 9. Known Issues

| Issue | Severity | Resolution |
|---|---|---|
| `NODE_EXTRA_CA_CERTS` нужно прокинуть в среду Claude Code | Medium | Добавить в shell profile до запуска Claude Code |
| Cert истекает через 10 лет | Low | `mnemostroma setup` перегенерирует если файл отсутствует |
| Upstream timeout при больших ответах | Low | `httpx.AsyncClient(timeout=300)` — достаточно |
| Дублирование observe при retry Claude Code | Low | Observer дедуплицирует по content hash |

---

## 10. Тесты

- `test_passthrough_forwards_get()` — GET /v1/models → 200 от upstream
- `test_passthrough_observe_on_messages()` — POST /v1/messages → observe() вызван
- `test_passthrough_skips_observe_non_messages()` — GET /v1/models → observe() не вызван
- `test_passthrough_sse_chunks_collected()` — стриминг → полный текст в observe()
- `test_passthrough_missing_session_fallback()` — нет current_session → fallback sid, observe не падает
- `test_tls_generation_idempotent()` — повторный вызов не перегенерирует файлы
