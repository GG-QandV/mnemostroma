# Mnemostroma — Deployment Guide
## Развёртывание на всех платформах
## v1.7.5 | 2026-04-12

---

## Принцип: «как Ollama»

Один продукт, одна команда, работает:

```
mnemostroma install-models  → скачивает модели (~450MB)
mnemostroma daemon start    → запускает daemon
mnemostroma status          → дашборд (CLI)
mnemostroma stop            → останавливает
```

Для простого юзера: скачал → установил → кликнул иконку. Без терминала, без Python, без pip.
Для разработчика: `pip install mnemostroma` и всё.

#### Python Extras (Install options)

| Extra | Содержимое | Команды |
|---|---|---|
| *(base)* | Core daemon | `setup`, `on`, `off`, `status`, `watch`, `logs` |
| `[sse]` | SSE adapter + proxy | `sse` |
| `[tray]` | System tray (pystray) | `tray` |
| `[all]` | Всё вышеперечисленное | Все команды |

> **Linux Note:** для работы `tray` также нужны системные библиотеки:
> `sudo apt install libgirepository1.0-dev gir1.2-appindicator3-0.1`

---

## Этап 1: Основные платформы (MVP)

### Windows

| Способ | Для кого | Что нужно |
|--------|---------|-----------|
| **.msi установщик** | Простой юзер | Скачать → Next → Next → Install |
| **winget** | Продвинутый юзер | `winget install mnemostroma` |
| **pip** | Python-разработчик | `pip install mnemostroma` |
| **WSL2** | Разработчик с WSL | `pip install mnemostroma` внутри WSL (как Linux) |

#### .msi установщик (основной для Windows)

```
Содержимое .msi:
  ├── mnemostroma.exe          Embedded Python runtime (Briefcase/PyInstaller)
  ├── models/                   ONNX INT8 модели (~450MB disk)
  │   ├── multilingual-e5-small/
  │   ├── distilbert-ner/
  │   └── tinybert-l2-v2/
  ├── config.json               Дефолтная конфигурация
  └── manifest.json             SHA-256 хеши моделей

Установка:
  1. Скачать mnemostroma-1.0-windows-x64.msi (~450MB)
  2. Запустить → Next → выбрать папку → Install
  3. System tray иконка появляется автоматически
  4. Первый запуск: верификация моделей (SHA-256) → готово

Размещение данных:
  %APPDATA%\mnemostroma\
  ├── data\
  │   ├── context.db            SQLite WAL
  │   └── content_hnsw.bin      Content index
  ├── config.json
  └── logs\
      └── daemon.log
```

#### System Tray App (Windows)

```
Иконка в system tray:
  ├── ЛКМ → Status dashboard (мини-окно)
  │   ├── Sessions: 247
  │   ├── RAM: 534MB (89%)
  │   ├── Latency: 18ms
  │   └── Uptime: 4h 23m
  │
  ├── ПКМ → Context menu:
  │   ├── Start / Stop daemon
  │   ├── Open dashboard (браузер)
  │   ├── Open config
  │   ├── Search memory...
  │   ├── View logs
  │   └── Quit
  │
  └── Автозапуск при логине (опционально)
```

#### IPC на Windows

```
Named Pipe: \\.\pipe\mnemostroma
Протокол: JSON-RPC 2.0
Агенты (Cursor, VS Code, терминал) подключаются к pipe
```

#### Особенности Windows

| Нюанс | Решение |
|-------|---------|
| Нет Unix Socket | Named Pipe (уже в спеке Conductor) |
| Антивирус может блокировать | Подписать .msi сертификатом (code signing) |
| Windows Defender SmartScreen | Code signing обязательно, иначе «Unknown publisher» |
| Пути с пробелами (`C:\Program Files\`) | Использовать `%APPDATA%` для данных |
| Автозапуск | Ключ реестра `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` |
| ONNX Runtime на Windows | ✅ Полная поддержка x64, ARM64 через onnxruntime |

---

### macOS

| Способ | Для кого | Что нужно |
|--------|---------|-----------|
| **.dmg установщик** | Простой юзер | Скачать → перетащить в Applications |
| **Homebrew** | Продвинутый юзер / разработчик | `brew install mnemostroma` |
| **pip** | Python-разработчик | `pip install mnemostroma` |

#### .dmg установщик (основной для macOS)

```
Содержимое .dmg:
  Mnemostroma.app/
  ├── Contents/
  │   ├── MacOS/
  │   │   └── mnemostroma          Native binary (Briefcase)
  │   ├── Resources/
  │   │   ├── models/              ONNX INT8 (~342MB)
  │   │   ├── config.json
  │   │   └── manifest.json
  │   └── Info.plist

Установка:
  1. Скачать mnemostroma-1.0-macos-universal.dmg (~450MB)
  2. Перетащить Mnemostroma.app в Applications
  3. Первый запуск: macOS Gatekeeper → "Open Anyway"
     (или notarize app через Apple — убирает предупреждение)
  4. Menu bar иконка появляется

Размещение данных:
  ~/Library/Application Support/mnemostroma/
  ├── data/
  │   ├── context.db
  │   └── content_hnsw.bin
  ├── config.json
  └── logs/
```

#### Menu Bar App (macOS)

```
Иконка в menu bar (как Ollama, Docker Desktop):
  ├── Клик → Dropdown:
  │   ├── Status: Running ● (зелёная точка)
  │   ├── Sessions: 247 | RAM: 534MB | 18ms
  │   ├── ──────────
  │   ├── Search memory...    (⌘⇧M hotkey)
  │   ├── Open dashboard
  │   ├── ──────────
  │   ├── Start at login ☑
  │   ├── Preferences...
  │   ├── View logs
  │   └── Quit
```

#### Homebrew

```bash
# Tap + install
brew tap mnemostroma/tap
brew install mnemostroma

# Запуск как brew service (автозапуск)
brew services start mnemostroma

# Или вручную
mnemostroma daemon start
```

#### Особенности macOS

| Нюанс | Решение |
|-------|---------|
| Gatekeeper блокирует неподписанные | Apple Developer certificate + notarization |
| Universal binary (Intel + ARM) | Собрать через Briefcase для обоих архитектур |
| Apple Silicon (M1-M4) | ONNX Runtime поддерживает ARM64 нативно |
| IPC | Unix Socket: `/tmp/mnemostroma.sock` |
| Автозапуск | LaunchAgent plist в `~/Library/LaunchAgents/` |
| Sandbox (App Store) | НЕ через App Store — нужен полный доступ к filesystem |

---

### Linux

| Способ | Для кого | Что нужно |
|--------|---------|-----------|
| **AppImage** | Простой юзер (любой дистрибутив) | Скачать → chmod +x → запустить |
| **pip** | Разработчик | `pip install mnemostroma` |
| **deb** | Ubuntu/Debian | `sudo dpkg -i mnemostroma.deb` |
| **rpm** | Fedora/RHEL | `sudo rpm -i mnemostroma.rpm` |
| **snap** | Ubuntu | `snap install mnemostroma` |
| **AUR** | Arch | `yay -S mnemostroma` |

#### AppImage (основной для Linux, универсальный)

```
Один файл: mnemostroma-1.0-x86_64.AppImage (~450MB)
  Содержит: Python runtime + все зависимости + модели

Установка:
  1. wget https://github.com/mnemostroma/releases/mnemostroma-1.0-x86_64.AppImage
  2. chmod +x mnemostroma-1.0-x86_64.AppImage
  3. ./mnemostroma-1.0-x86_64.AppImage daemon start

Или с desktop integration:
  ./mnemostroma-1.0-x86_64.AppImage --install
  → .desktop файл в ~/.local/share/applications/
  → иконка в system tray (если DE поддерживает)

Размещение данных:
  ~/.local/share/mnemostroma/
  ├── data/
  │   ├── context.db
  │   └── content_hnsw.bin
  ├── config.json
  └── logs/
```

#### Systemd service (автозапуск на Linux)

```ini
# ~/.config/systemd/user/mnemostroma.service
[Unit]
Description=Mnemostroma Memory Daemon
After=network.target

[Service]
ExecStart=/path/to/mnemostroma daemon start --foreground
ExecStop=/path/to/mnemostroma daemon stop
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable mnemostroma
systemctl --user start mnemostroma
```

#### Особенности Linux

| Нюанс | Решение |
|-------|---------|
| Сотни дистрибутивов | AppImage = работает на всех. Пакеты (deb/rpm) для основных |
| IPC | Unix Socket: `/run/user/$UID/mnemostroma.sock` или `/tmp/mnemostroma.sock` |
| Автозапуск | systemd user service |
| System tray | Зависит от DE: GNOME extension, KDE tray, XFCE panel. Не все DE поддерживают — CLI fallback |
| ARM64 (Raspberry Pi) | Отдельная сборка AppImage для aarch64 |
| Headless server | Daemon-only, без GUI. CLI + JSON-RPC для удалённого доступа |

---

## Этап 2: Дополнительные платформы (после MVP)

### Docker

```bash
# Одной командой
docker run -d \
  --name mnemostroma \
  -v ~/.mnemostroma:/data \
  -p 47821:47821 \
  mnemostroma/mnemostroma:latest

# docker-compose.yml
version: "3"
services:
  mnemostroma:
    image: mnemostroma/mnemostroma:latest
    volumes:
      - ./data:/data
    ports:
      - "47821:47821"
    restart: unless-stopped
```

- Для тех кто не хочет ставить Python
- Для NAS (Synology/QNAP) с Docker support
- Для Cloud VPS

| Параметр | Значение |
|----------|----------|
| Image size | ~500MB |
| RAM runtime | ~600MB |
| Persist | Volume mount `/data` |
| Port | 47821 (JSON-RPC) |

---

### Android (Thin Client)

```
НЕ full stack. Только чтение через Cloud Sync API.

Android App:
  ├── Memory Dashboard (сессии, decisions, principles)
  ├── Semantic Search (через API к daemon на десктопе/VPS)
  ├── Push notifications (дедлайны, конфликты)
  └── Shared Experience Feed (Team tier)

Размер: ~5MB APK
Требования: Android 8+, интернет
Зависимости: Cloud Sync Pro tier или Remote Daemon в LAN
```

---

### iOS (Thin Client)

```
Аналогично Android — только чтение.

iOS App (Swift):
  ├── Memory Dashboard
  ├── Semantic Search
  ├── Widgets (дедлайны на домашнем экране)
  └── Shared Experience Feed

Размер: ~10MB
Требования: iOS 16+
App Store: возможна публикация (нет Python runtime)
```

---

### Raspberry Pi 5 (Full Stack)

```bash
# Pi 5 с 8GB RAM — полный стек
wget mnemostroma-1.0-aarch64.AppImage
chmod +x mnemostroma-1.0-aarch64.AppImage
./mnemostroma-1.0-aarch64.AppImage daemon start

# Как personal memory server:
# - Подключён к домашней сети 24/7
# - Все устройства подключаются через Remote Daemon
# - ~$60 hardware, 0 подписок
```

| Параметр | Значение |
|----------|----------|
| RAM usage | ~600MB из 8GB |
| Latency ctx.semantic() | ~50-80ms (ARM64, медленнее x86) |
| Storage | microSD или USB SSD |

---

### NAS (Synology/QNAP)

```
Docker container на NAS:
  → Mnemostroma daemon 24/7
  → Все устройства в LAN подключаются
  → Данные на RAID — надёжнее чем ноутбук
  → Не нужен Cloud Sync — NAS = домашнее облако
```

---

### Cloud VPS

```bash
# $5/мес Hetzner/DigitalOcean, 2GB RAM
ssh user@vps
pip install mnemostroma
mnemostroma daemon start --bind 0.0.0.0 --token "your-secret-token"

# С любого устройства:
mnemostroma remote connect vps.example.com --token "your-secret-token"
```

**Обязательно:** E2E encryption + auth token для remote connections.

---

### ChromeOS

```
Два варианта:
  1. Linux container (Crostini) → pip install → как обычный Linux
  2. Android thin client из Play Store
```

---

## Сборка бинарников

| Инструмент | Платформы | Что делает | Рекомендация |
|-----------|-----------|-----------|-------------|
| **Briefcase (BeeWare)** | Windows .msi, macOS .app, Linux AppImage | Python → нативное приложение с GUI/tray | ✅ Основной — единый build pipeline |
| **PyInstaller** | Windows .exe, macOS, Linux | Python → standalone бинарник | 🟡 Backup — если Briefcase не справится |
| **Nuitka** | Все платформы | Python → compiled C → бинарник | 🟡 Для максимальной производительности |
| **Docker** | Все с Docker | Контейнер | ✅ Для серверного deployment |

**Рекомендация:** Briefcase как основной инструмент. Из одного Python проекта генерирует .msi, .dmg, AppImage. Один CI/CD pipeline → три платформы.

---

## Модели: скачивание и верификация

### Два варианта доставки моделей

| Вариант | Размер пакета | Первый запуск | Offline install |
|---------|-------------|---------------|-----------------|
| **Модели внутри пакета** | ~450MB | Мгновенный старт | ✅ Полный offline |
| **Модели скачиваются отдельно** | ~100MB пакет + ~342MB download | Первый запуск +2-5 мин на скачку | ❌ Нужен интернет один раз |

**Рекомендация:** два варианта скачивания:
- `mnemostroma-1.0-full.msi` (~450MB) — всё внутри, полный offline
- `mnemostroma-1.0-lite.msi` (~100MB) — скачает модели при первом запуске

### Верификация при каждом запуске

```
Bootstrap:
  [0] Проверить SHA-256 каждой модели по manifest.json
  [1] Если хеш не совпал → НЕ ЗАПУСКАТЬ, предупреждение
  [2] Если модели нет → предложить скачать
  [3] Всё OK → продолжить bootstrap
```

---

## Remote Daemon (новый deployment pattern)

Daemon работает на одной машине, агенты подключаются с других:

```
                    LAN / Internet
                         │
    ┌────────────────────┼────────────────────┐
    │                    │                    │
    ▼                    ▼                    ▼
 Ноутбук            Десктоп              Телефон
 (agent +            (agent +            (thin
  mnemostroma         mnemostroma         client)
  remote client)      remote client)
    │                    │                    │
    └────────────────────┼────────────────────┘
                         │ JSON-RPC + auth token + E2E
                         ▼
                  ┌──────────────┐
                  │  NAS / VPS   │
                  │  / Pi 5      │
                  │              │
                  │ mnemostroma  │
                  │ daemon       │
                  │ (full stack) │
                  └──────────────┘
```

**Требования для Remote Daemon:**
- Auth token (Bearer) в каждом JSON-RPC запросе
- TLS для шифрования транспорта (или E2E поверх)
- Bind address: `--bind 0.0.0.0` (не только localhost)
- Firewall: открыть порт 47821

**Конфигурация:**

```json
{
  "daemon": {
    "bind_address": "0.0.0.0",
    "port": 47821,
    "auth_token": "generated-secret-token",
    "tls_enabled": true,
    "tls_cert": "/path/to/cert.pem",
    "tls_key": "/path/to/key.pem"
  }
}
```

---

## Сводная таблица

| Платформа | Этап | Способ для простого юзера | Способ для разработчика | GUI |
|-----------|------|--------------------------|------------------------|-----|
| **Windows** | 1 (MVP) | .msi installer | pip / winget / WSL2 | System tray |
| **macOS** | 1 (MVP) | .dmg → Applications | brew / pip | Menu bar |
| **Linux** | 1 (MVP) | AppImage | pip / deb / rpm / snap / AUR | System tray (если DE поддерживает) |
| Docker | 2 | `docker run` | docker-compose | CLI |
| Android | 2 | Thin client (Play Store) | — | Native app |
| iOS | 2 | Thin client (App Store) | — | Native app |
| Raspberry Pi 5 | 2 | AppImage aarch64 | pip | CLI / headless |
| NAS | 2 | Docker | Docker | Web dashboard |
| Cloud VPS | 2 | pip + daemon | pip + daemon | CLI / remote |
| ChromeOS | 2 | Linux container или Android thin | pip в Crostini | Depends |

---

*Mnemostroma | Deployment Guide | v1.0 | 2026-03-25*
