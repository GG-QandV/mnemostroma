# SPEC: Windows 10/11 Compatibility Patch

**Версия:** 1.0  
**Дата:** 2026-05-30  
**Статус:** Готов к имплементации  
**Затрагиваемые файлы:**

* `scripts/serveo_manager.py` + `scripts/serveo_manager.txt`

* `src/mnemostroma/integration/tunnel/providers/serveo.py`

* `src/mnemostroma/integration/mcp_oauth_adapter.py`

* `src/mnemostroma/cli/commands.py`

* `src/mnemostroma/tools/tray.py` + `traypyqt.py`

* `scripts/install-windows.ps1`

---

## Fix W-01: SSH subprocess — аргументы как list, encoding явная

**Файл:** `scripts/serveo_manager.py`, `src/.../tunnel/providers/serveo.py`  
**Проблема:** `infocmd.split()` ломает пути с пробелами на Windows; `text=True` без `encoding` использует cp1251/cp866 — URL из serveo не парсится (serveo_manager.txt)

```python
# БЫЛО:
proc = subprocess.Popen(
    info["cmd"].split(),
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1,
)

# СТАЛО:
import shlex, sys

def _build_cmd_args(cmd: str) -> list[str]:
    """На Windows используем shlex; на всех платформах — явный list."""
    return shlex.split(cmd, posix=(sys.platform != "win32"))

proc = subprocess.Popen(
    _build_cmd_args(info["cmd"]),
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8",
    errors="replace",   # не падать на cp-символы в выводе SSH
    bufsize=1,
)
```

**Тест:** `test_build_cmd_args_windows_spaces` — передаём строку с пробелами, проверяем что список корректный.

---

## Fix W-02: Все `write_text` / `read_text` с явным `encoding="utf-8"`

**Файлы:** `scripts/serveo_manager.py`, `src/.../tunnel/providers/serveo.py`, `src/.../integration/mcp_oauth_adapter.py`  
**Проблема:** Python на Windows использует системную кодировку по умолчанию. Файлы `tunnel_url`, `serveo_url`, `routes.json`, JSON-конфиги в `serveo_client_configs/` могут быть записаны в cp1252 и прочитаны с ошибкой

```python
# Паттерн — применять везде единообразно:

# БЫЛО:
url_file.write_text(url)
path.read_text()
path.write_text(updated)

# СТАЛО:
url_file.write_text(url, encoding="utf-8")
path.read_text(encoding="utf-8")
path.write_text(updated, encoding="utf-8")
```

**Scope применения** — все вхождения в:

* `ServeoTunnelManager._reader()` — `url_file.write_text(url)`

* `fill_client_configs()` — `path.read_text()` / `path.write_text()`

* `load_route_config()` в `mcp_oauth_adapter.py` — чтение `routes.json`

* `export_to_claude_config()` — чтение/запись `~/.claude.json`

* `token.py` — чтение `tunnel_token`, `sse_token`

**Тест:** `test_write_text_utf8_encoding` — создаём файл на Windows с нестандартными символами в пути, читаем обратно.

---

## Fix W-03: SSH preflight с понятным сообщением и версией

**Файл:** `scripts/serveo_manager.py`  
**Проблема:** `RuntimeError("ssh not found in PATH")` не объясняет как исправить на Windows (serveo_manager.txt)

```python
def check_ssh_available() -> Optional[str]:
    path = shutil.which("ssh")
    if path is None and sys.platform == "win32":
        raise RuntimeError(
            "OpenSSH Client не найден.\n"
            "Установите через: Settings → Apps → Optional Features → OpenSSH Client\n"
            "или выполните: winget install Microsoft.OpenSSH.Beta\n"
            "После установки перезапустите терминал."
        )
    return path


def check_ssh_version() -> Optional[str]:
    """Проверяем что версия >= 7.6 (нужен accept-new)."""
    try:
        result = subprocess.run(
            ["ssh", "-V"], capture_output=True, text=True,
            encoding="utf-8", errors="replace"
        )
        output = result.stderr or result.stdout
        m = re.search(r"OpenSSH_(\d+\.\d+)", output)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None
```

**В `build_ssh_cmd()` — fallback для старого SSH:**

```python
def build_ssh_cmd(port: int = DEFAULT_MCP_PORT,
                  subdomain: Optional[str] = None) -> str:
    version = check_ssh_version()
    # accept-new появился в OpenSSH 7.6
    try:
        major, minor = (float(x) for x in (version or "0.0").split(".", 1))
        strict = "accept-new" if (major, minor) >= (7.6, 0) else "yes"
    except ValueError:
        strict = "accept-new"

    remote = f"{subdomain}:80:localhost:{port}" if subdomain else f"80:localhost:{port}"
    return (
        f"ssh -o ServerAliveInterval=60 "
        f"-o StrictHostKeyChecking={strict} "
        f"-R {remote} {SERVEO_HOST}"
    )
```

**Тест:** `test_ssh_version_fallback_old_openssh` — мокируем версию 7.1, проверяем что strict=`yes`.

---

## Fix W-04: `proc.terminate()` → graceful на Windows

**Файл:** `scripts/serveo_manager.py`, `src/.../tunnel/providers/serveo.py`  
**Проблема:** `terminate()` на Windows = `TerminateProcess()` — убивает SSH мгновенно без уведомления serveo, субдомен занят 15-60 сек (serveo_manager.txt)

```python
def stop(self) -> None:
    self._stop_event.set()
    if self._proc and self._proc.poll() is None:
        if sys.platform == "win32":
            # Посылаем CTRL_C_EVENT в группу процессов SSH
            import signal
            try:
                self._proc.send_signal(signal.CTRL_C_EVENT)
                self._proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self._proc.kill()
        else:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
    self._proc = None
    self._url = None
    # Очищаем ОБА файла состояния
    for name in ("serveo_url", "tunnel_url"):
        f = Path.home() / ".mnemostroma" / name
        f.unlink(missing_ok=True)
```

> **Примечание:** `CTRL_C_EVENT` работает только если процесс запущен с `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP`. Добавить в `Popen`:
> 
> python
> 
> `kwargs = {} if sys.platform == "win32":     kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP proc = subprocess.Popen(_build_cmd_args(info["cmd"]), ..., **kwargs)`

**Тест:** `test_stop_sends_ctrl_c_on_windows` — мокируем платформу, проверяем `send_signal(CTRL_C_EVENT)`.

---

## Fix W-05: `RouteFileWatcher` — валидация backend на Windows

**Файл:** `src/.../integration/mcp_oauth_adapter.py`  
**Проблема:** `"backend": "inotify"` в `routes.json` бросает `RuntimeError` при старте на Windows

```python
def _make_watch_backend_from_config(cfg: WatcherConfig) -> WatchBackend:
    if cfg.backend == "inotify":
        if sys.platform == "win32":
            logger.warning(
                "InotifyBackend недоступен на Windows — "
                "используется PollingBackend. "
                "Установите 'backend': 'polling' в routes.json."
            )
            return PollingBackend()
        return InotifyBackend()   # поднимет RuntimeError если нет watchfiles
    elif cfg.backend == "polling":
        return PollingBackend()
    else:  # "auto"
        if sys.platform == "win32":
            return PollingBackend()
        try:
            return InotifyBackend()
        except RuntimeError:
            return PollingBackend()
```

**Тест:** `test_inotify_fallback_on_windows` — мокируем `sys.platform = "win32"`, `backend="inotify"`, проверяем что возвращается `PollingBackend` без исключения.

---

## Fix W-06: OAuth Consent Screen — `--no-browser` флаг для Task Scheduler

**Файл:** `src/.../integration/mcp_oauth_adapter.py`, `src/.../cli/commands.py`  
**Проблема:** `webbrowser.open()` падает или открывает невидимое окно в Session 0 (Task Scheduler)

```python
# В mcp_oauth_adapter.py — handler GET /authorize:

NO_BROWSER = os.environ.get("MNEMOSTROMA_NO_BROWSER", "").lower() in ("1", "true", "yes")

@app.route("/authorize")
async def authorize(request: Request):
    # ... генерация HTML consent page ...
    consent_url = f"http://localhost:{PORT}/authorize?{request.query_string.decode()}"

    if not NO_BROWSER:
        try:
            import webbrowser
            webbrowser.open(consent_url)
        except Exception as e:
            logger.warning("Не удалось открыть браузер: %s", e)

    # Возвращаем 200 с HTML-формой согласия (не 302!)
    return HTMLResponse(content=render_consent_html(request.query_params))
```

**В `install-windows.ps1`** — при регистрации Task Scheduler добавить переменную:

```powershell
# При создании задачи для tunnel/oauth adapter:
$action = New-ScheduledTaskAction `
    -Execute "python" `
    -Argument "-m mnemostroma tunnel start" `
    -WorkingDirectory $InstallDir

# Установить переменную окружения для задачи:
$env_settings = New-ScheduledTaskSettingsSet
# Добавляем MNEMOSTROMA_NO_BROWSER=1 в env задачи
```

**Альтернатива** — вместо env переменной: при старте проверять `os.environ.get("SESSIONNAME")` — в Task Scheduler без рабочего стола `SESSIONNAME` равен `""` или отсутствует:

```python
def _is_headless() -> bool:
    if sys.platform == "win32":
        return os.environ.get("SESSIONNAME", "") == ""
    return os.environ.get("DISPLAY", "") == ""  # Linux headless
```

**Тест:** `test_no_browser_in_headless_mode` — мокируем `SESSIONNAME=""`, проверяем что `webbrowser.open` не вызывается.

---

## Fix W-07: Unix socket IPC — fallback на TCP

**Файл:** `src/.../integration/mcp_oauth_adapter.py` (`safe_ipc_call`)  
**Проблема:** Unix domain sockets отсутствуют на Windows 10 до Build 17063 и на LTSC 2016

```python
def safe_ipc_call(method: str, params: dict) -> dict:
    """IPC к daemon: Unix socket (Linux/macOS/Win 1809+) или TCP fallback."""
    sock_path = Path.home() / ".mnemostroma" / "daemon.sock"

    # Windows LTSC / старые билды — fallback на TCP порт
    use_tcp = sys.platform == "win32" and not _unix_socket_available()

    if use_tcp:
        return _ipc_via_tcp(method, params, port=_IPC_TCP_PORT)
    else:
        return _ipc_via_unix(method, params, sock_path)


def _unix_socket_available() -> bool:
    """AF_UNIX доступен начиная с Windows 10 Build 17063."""
    if sys.platform != "win32":
        return True
    try:
        import socket
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.close()
        return True
    except (AttributeError, OSError):
        return False
```

**Тест:** `test_ipc_fallback_to_tcp_on_old_windows` — мокируем `_unix_socket_available() = False`, проверяем вызов `_ipc_via_tcp`.

---

## Сводная таблица патчей

| Fix  | Файл                                                         | Строк | Приоритет  | Тест                                      |
| ---- | ------------------------------------------------------------ | ----- | ---------- | ----------------------------------------- |
| W-01 | `serveo_manager.py`, `serveo.py`                             | ~10   | 🔴 Крит.   | `test_build_cmd_args_windows_spaces`      |
| W-02 | Все файлы с `read/write_text`                                | ~20   | 🔴 Крит.   | `test_write_text_utf8_encoding`           |
| W-03 | `serveo_manager.py`                                          | ~20   | 🔴 Крит.   | `test_ssh_version_fallback_old_openssh`   |
| W-04 | `serveo_manager.py`, `serveo.py`                             | ~15   | 🟡 Высокий | `test_stop_sends_ctrl_c_on_windows`       |
| W-05 | `mcp_oauth_adapter.py`                                       | ~10   | 🟡 Высокий | `test_inotify_fallback_on_windows`        |
| W-06 | `mcp_oauth_adapter.py`, `commands.py`, `install-windows.ps1` | ~25   | 🟡 Высокий | `test_no_browser_in_headless_mode`        |
| W-07 | `mcp_oauth_adapter.py`                                       | ~30   | 🟡 Средний | `test_ipc_fallback_to_tcp_on_old_windows` |

**Итого:** ~130 строк изменений, 7 новых тестов, все изменения обратно совместимы с Linux/macOS.
