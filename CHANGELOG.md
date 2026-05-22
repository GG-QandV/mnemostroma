## 2.3.0 — 2026-05-20

### Added
- feat[tunnel] `mnemostroma tunnel start/stop/status` — единая команда для запуска
  Cloudflare Tunnel + MCP OAuth Adapter как фонового сервиса
- feat[tunnel] `mcp_oauth_adapter.py` — Starlette шлюз на порту 8769, поддерживает
  все 4 чата одновременно без ручной настройки
- feat[tunnel] Phase 0 Perplexity — прокси без авторизации
- feat[tunnel] Phase 1 Claude.ai — OAuth 2.0 + PKCE S256 + DCR (RFC 8414)
- feat[tunnel] Phase 2 ChatGPT — OAuth 2.0 + PKCE S256 + DCR (RFC 8414 + RFC 9728)
- feat[tunnel] Phase 3 Grok — статический Bearer token
- feat[tunnel] `tunnel/providers/cloudflare.py` — авто-загрузка платформо-специфичного
  `cloudflared` бинаря в `~/.mnemostroma/bin/` при первом запуске
- feat[tunnel] `tunnel/token.py` — изолированный `tunnel_token` (отдельный от `ssetoken`,
  права 0o600, 256 бит энтропии)
- feat[install] `mnemostroma-tunnel.service` — systemd user unit, регистрируется через
  `mnemostroma service install --component tunnel`
- feat[pyproject] `tunnel = ["mnemostroma[sse]"]` optional extras alias

### Removed
- refactor[cli] Удалена legacy логика Serveo SSH из `commands.py`
  (заменена Cloudflare Tunnel Manager)
- refactor[install] `mnemostroma-serveo.service` заменён на `mnemostroma-tunnel.service`

### Tests
- 10 новых unit-тестов: `test_tunnel_token.py`, `test_mcp_oauth_adapter.py`,
  `test_tunnel_manager.py`
- 22 интеграционных теста MCP routing + SSE auth
- Итого: 609 passed, 0 failed

---

## 2.2.7 — 2026-05-20

### Fixed
- fix[extension] Extension distribution: синхронизирован v1.0.5 (ES-модули, адаптер Grok,
  Transport-First, badge health check) в пакет демона, заменяя legacy v1.0.0
- fix[pyproject] Рекурсивный glob `extension/**/*` заменяет плоскую маску — все
  поддиректории модульного расширения корректно упакованы в wheel
- fix[extension] Создан полноценный ES-модульный адаптер `grok.js` для поддержки
  Grok (xAI)

### Added
- feat[scripts] `scripts/sync_extension.py` — автоматическая синхронизация
  `src/extension/ → src/mnemostroma/extension/` с исключением dev-артефактов
- feat[install] Вызов `python scripts/sync_extension.py` добавлен в Sync A→C
  pipeline (`GIT_RULES_v4.2.md`)
- feat[security] Git pre-commit hook `.git/hooks/pre-commit` — блокирует попадание
  приватных маркеров (`logevent`, `WATERMARK`, `INTERNAL`) в дистрибутив расширения

### Tests
- 577 passed, 0 failed (было 531 до релиза)

## [2.2.6] — 2026-05-18

### Added
- **feat(install)**: Создан полный Windows-инсталлятор `scripts/install-windows.ps1` — единый скрипт от нуля до `mnemostroma status`: автопроверка/автоустановка Python 3.12 через winget, Git-проверка, venv, pip install, PATH patch (User scope), `mnemostroma setup`, три задачи Task Scheduler (Daemon/Proxy/Watchdog), финальный статус. Не требует прав администратора.
- **feat(cli)**: install-extension: new command to deploy browser extension locally

### Fixed
- **fix(windows)**: extension: include dist/ in package_data — closes WIN-BUG-002
- **fix(setup)**: mnemostroma setup now prints extension path after install
- **fix(windows)**: status: replace `os.kill(pid, 0)` with `psutil.pid_exists()` / `_is_process_alive()`
  — PermissionError no longer triggers `_remove_pid()` on Windows
  — PID file self-healing: restored if process alive but file missing
  — Closes WIN-BUG-001: daemon shows 'stopped' despite running process
- **fix(docs)**: Переработана Windows-секция `README.md`: добавлена полная инструкция Option A (однострочник `irm`/`iex`-совместимый) и Option B (ручная), таблица Windows Troubleshooting, обновлён URL установщика в секции Task Scheduler.

## [2.1.5] — 2026-05-17

### Added
- **feat(cli)**: Интегрированы системные действия управления туннелем Serveo через CLI (`mnemostroma tunnel start/stop/status`).
- **feat(install)**: Создан systemd-шаблон `mnemostroma-serveo.service` в `src/mnemostroma/service_templates/linux/` для автоматического управления туннелем Serveo в пользовательском пространстве systemd.
- **feat(test)**: Разработан асинхронный тестовый сьют `tests/test_watchdog.py` (6 новых тестов), проверяющий крайние случаи поведения вочдога (медленный запуск, зависание, отсутствие heartbeat, ложные срабатывания).

### Fixed
- **fix(integration)**: Устранен критический ASGI-баг Starlette (`TypeError` / `Response already started`) при вызове HTTP/SSE адаптеров. Реализован оберточный класс `ASGIAppWrapper` в `mcp_http_adapter.py` и `mcp_sse_adapter.py`, гарантирующий корректное ASGI-выполнение.
- **fix(watchdog)**: Исправлена «мертвая ветка» проверки сокета в `_check_daemon()` при зависании heartbeat.
- **fix(watchdog)**: Переработан Boot-период (`Phase 1`): вочдог больше не убивает демон Мнемостромы при медленной гидратации, если UNIX-сокет активен.
- **fix(watchdog)**: Добавлены превентивные уведомления `sd_notify` (`_notify_systemd()`) во время Boot-фазы для удержания таймера systemd WatchdogSec.
- **fix(watchdog)**: Сужен паттерн `pgrep` (`python.*-m mnemostroma run`) для исключения ложного убийства сторонних процессов и утилит grep.
- **fix(watchdog)**: Интегрирован параметр `proxy_timeout` из конфигурационного файла `config.json` взамен жестко захардкоженной константы в Phase 2.
- **fix(watchdog)**: Добавлен лог активности "watchdog alive" каждые 10 итераций в Phase 2.

## [2.0.5] — 2026-05-17

### Added
- **feat(extension)**: Release Guard предохранитель в браузере. Внедрен флаг `IS_MCP_TUNNELING_ENABLED`. При значении `false` сетевой транспорт и хуки на `fetch`/`XHR` полностью отключаются, переключая расширение в 100% стабильный локальный режим `dom_only` (наблюдатель DOM перехватывает сессии чата и передает на локальный демон).
- **feat(extension)**: Полная обратная совместимость с Claude, Perplexity, Gemini, ChatGPT, DeepSeek и Grok.

### Fixed
- **fix(extension)**: Адрес `localhost` заменен на `127.0.0.1` в сетевых запросах для устранения падения соединений по протоколу IPv6 в Chrome.
- **fix(extension)**: Логирование загрузки SPA-страниц понижено до уровня `debug`, что устранило избыточный шум и загрязнение логов в консоли браузера.
- **fix(install)**: Исправлена опечатка с импортом `LogWriter` в `conductor.py` при сборках.
- **fix(docs)**: Исправлены некорректные и устаревшие пути установки браузерного расширения (`browser_extension` -> `src/extension`) во всех файлах README и инструкциях.

## [1.11.2] - 2026-05-10

### Fixed

- fix(core): missing `LogWriter` import in `conductor.py` caused `NameError`
  and daemon crash on startup after fresh install from GitHub.
  Discovered during v1.11.1 field upgrade on Linux. Patched in venv,
  fixed in source. Introduced `scripts/update_version.py` for automated
  version management across all docs.

## [1.11.1] — 2026-05-03
### Fixed
- **fix(install)**: `_ensure_manifest()` — provisioned manifest before model download, eliminating `FileNotFoundError` on fresh installs (reported by user on curl-pipe path).
- **fix(install)**: `linux/install.sh` replaced with thin wrapper delegating to `mnemostroma service install` — eliminates `/dev/fd/linux/install.sh: No such file or directory` in curl-pipe mode.
- **fix(install)**: `install-daemon.sh` — editable install detection prevents GitHub pip from silently overwriting local source link (`R-09`).
- **fix(install)**: `systemctl enable` loop now reports per-unit failures instead of silent success (`R-05`).
- **fix(install)**: `mnemostroma-sse.service` `WorkingDirectory` uses systemd-native `%h` specifier (consistent with all other units) (`R-06`).
- **fix(install)**: `service install` failure in `install-daemon.sh` is now fatal (`exit 1`) rather than silently ignored (`R-02`).

## [1.11.0] — 2026-04-28
### Added
- **feat(storage)**: `Exact Time` search — exact time window queries capability for high-precision temporal routing.
- **feat(observer)**: `Content Branch` automation — mechanism #12 automatically intercepts, classifies, and saves `content` sessions to `ContentManager`.
### Changed
- **refactor(api)**: Disabled explicit `save_content`, `content_get`, `ctx_expire`, and `ctx_urgent` MCP routes to enforce API minimization and "Agent does not write memory" invariant.

## [1.9.1] — 2026-04-27
### Added
- **feat(autobridge)**: `AutoBridgeWorker` — autonomous background context bridge generation for seamless AI agent handoffs (L5).
- **feat(windows)**: Full Windows feature-parity installer with Proxy and Watchdog via Task Scheduler (closes GAP-11, GAP-12).
- **feat(macos)**: Full macOS feature-parity with native `launchctl bootstrap` and multi-agent Proxy/Watchdog `.plist` injection (closes GAP-8, 9, 10).
- **feat(installer)**: All platforms now auto-download ONNX models during `setup` or service installation (closes GAP-5).
### Fixed
- **fix(linux)**: `mnemostroma-sse` is now correctly enabled by `install.sh` (closes GAP-1).
- **fix(linux)**: Improved Python detector fallback for pyenv/conda and fixed `clean-zombies` invocation edge cases (closes GAP-2, GAP-3, GAP-4).
- **fix(cli)**: `update.sh` and `mnemo-health.sh` now correctly track and reset `mnemostroma-ui` and `mnemostroma-sse` (closes GAP-14, 15).

## [1.8.5] — 2026-04-25
### Added
- **feat(observer)**: `anchor_replay.py` — A/B Testing tool for anchor logic evaluation.
- **feat(ner)**: Outcome entity extraction ("успешным", "провалено").
### Fixed
- **fix(ner)**: Decision/prohibition priority over technology [BUG-001].
- **fix(observer)**: Dynamic `SourceType` detection in pipeline [BUG-002].
- **fix(pipeline)**: Explicit entity attachment to `SessionBrief` for downstream tool consistency.
### Results
- Reached 33% decision coverage on real-world session data (baseline was 0%).

## [1.8.4] — 2026-04-23
### Fixed
- **Urgency Bug**: Expired sessions now correctly persist `urgency_active=False` to SQLite. Resolved 51 "frozen" sessions.
- **Dissolver Loop**: Implemented Rule 2 (RSS-based eviction) in `dissolver.py`. Eviction now considers actual RAM usage via `psutil`.
- **Memory Scaling**: Increased `session_window_size` to 400 (from 200) to better utilize the 650MB RAM budget.
### Added
- **Critical Guard**: Important and critical sessions are now protected from eviction unless RAM usage exceeds 90% of the hard limit.
- **Anchor Stoplist**: Observer now filters parasitic phrases using a configurable stop-list to prevent noisy anchor creation.
- **Regressions**: Added `tests/test_v184_regressions.py` covering memory and persistence invariants.

## [1.8.3] — 2026-04-20

### Fixed

- **Watchdog & UI Stabilization**: Finalized 2-phase watchdog and UI systemd integration for reliable background operation.
- **Daemon Detachment**: Fixed CLI stdin redirection to allow proper daemon detachment without terminal tethering.
- **Log Stripping**: Improved regex in `strip_logs_v2.py` for more reliable removal of sensitive diagnostic markers.

## [1.8.2] — 2026-04-20

### Added

- **Emergency RAM Reset**: Added "Hard RAM Reset (Emergency)" option to tray menu and `clean-zombies.py` script for aggressive process hunting.
- **Installation Pipeline**: Overhauled daemon installation logic for Linux (systemd), macOS (launchd), and Windows (Task Scheduler).

## [1.8.1] — 2026-04-17

### Fixed

- **Proxy Lifecycle**: Resolved runtime errors in the passthrough proxy lifecycle and unified versioning.

## [1.8.0] — 2026-04-14

### Changed

- **Hexagonal Architecture**: Completed full transition to Ports & Adapters; decoupled toolset from direct SQLite dependencies.
- **API Minimization**: Streamlined MCP API to 12 core tools (8 Recollection / 4 Navigation).
- **Tool Removal**: Formally removed legacy tools (`ctx_active`, `ctx_urgent`, `ctx_expire`, `save_content`).

### Tests

- 100% test pass rate with updated architecture (435/435 tests).

## [1.7.5] — 2026-04-10

### Added

- **Passthrough HTTPS proxy** (`:8767`) — captures Claude Code ↔ Anthropic API traffic to Observer without modifying requests; self-signed TLS cert generated by `mnemostroma setup`
- `src/mnemostroma/integration/proxy_passthrough.py` — Starlette ASGI app, SSE-aware streaming, fire-and-forget `observe()` calls, in-process metrics
- `src/mnemostroma/setup/tls.py` — idempotent TLS cert generation (CA + server cert, 10-year, localhost SAN)
- `mcp_sse_adapter.py`: starts proxy server conditionally when cert files exist
- `mcp_stdio_adapter.py`: writes `~/.mnemostroma/current_session` on startup for proxy session binding
- `py.typed` — PEP 561 marker; `pyproject.toml` metadata (authors, keywords, OS classifiers, `[sse]`/`[all]` extras, `[project.urls]`)
- README: platform-specific install (pip/pipx), service table, Claude Desktop/Claude Code/IDE/proxy configs for Linux/macOS/Windows

### Removed

- `ctx_expire` and `save_content` removed from MCP public interface (stdio adapter + SSE adapter). Observer-internal `tools/write.py` unchanged.

### Fixed

- `mcp_stdio_adapter._ipc_call`: removed TOCTOU socket existence check; added `asyncio.wait_for(reader.readline(), timeout=10s)` to prevent hang on unresponsive daemon
- `proxy_passthrough.py`: `httpx.AsyncClient` lifecycle — manual close in SSE generator's `finally` block (not `async with`) to prevent connection closure before streaming starts

### Tests

- 23 new integration tests: `tests/test_integration/test_proxy_passthrough.py` (Layers A–F + tail invariants)
- Total: 403 tests

## [1.7.1] — 2026-04-07

### Added

- `PersistenceLayer` — формальный интерфейс между WorkingMemory и SQLite (Phase 9.2)
- CLI user mode: `mnemostroma setup / on / off / status`
- `config_default.json` — копируется при `setup` в `~/.mnemostroma/`
- `pyproject.toml`: package-data для config_default.json + models_manifest.json

### Fixed

- `pipeline.py`, `consolidation.py`, `dreamer.py`: `create_task(save_anchor/upsert_experience)` → `await ctx.persistence.*` — устранён fire-and-forget на священных записях
- `bridge.py`: ctx_sync делегирует в `PersistenceLayer.sync()` — WAL логика централизована
- `content_manager.py`, `daemon_metrics.py`, `dissolver.py`, `admin.py`, `__main__.py`: все db_manager → persistence

### Architecture

- `SystemContext.db_manager` → `SystemContext.persistence: Optional[PersistenceLayer]`
- `conductor.py`: `PersistenceLayer(db_manager)` + `persistence.wire_ctx(ctx)`
- Два явных пути записи зафиксированы: enqueue_session (5-sec batch) vs save_anchor/save_experience (immediate, never lost)

### Tests

- 303 passed (было 303 до 9.2, все сохранены + переписан test_bridge.py)
- `test_bridge.py`: переписан с `_make_persistence_mock()`
- `test_dissolver.py`, `test_anchor_decay.py`, `test_daemon_infra.py`: переведены на использование ctx.persistence

## [1.7.0] — 2026-04-04

### Added

- **Numpy MatrixSearch**: Replaced `hnswlib` with pure numpy implementation for semantic search (ADR-002).
- **Core Memory Features**: Implemented `marker()`, `Entity`, `Emotion`, `Atmosphere`, and `TemporalRelations`.
- **Subconscious Layers**: Added `Anchor Decay` engine and `Dreamer` background re-evaluation.
- **Persistence**: `t_rel` (temporal relations) persistence in SQLite with `check_anchor_schema` migration.
- **Experience Layer**: Added Emotional Patterns (`ATTRACT`/`REPEL`/`AMBIVALENT`) to `ExperienceCluster`.
- **Daemon Infra**: Added `PulseWriter`, `StatusWriter`, `flush()` mechanics, and signal handling (`SIGUSR1/2`).
- **CLI Tools**: Added `mnemostroma install-models` and `dump`/`growth` commands.
- **Reranker E2E**: Fully integrated `TinyBERT-L2-v2` with `multilingual-e5-small` (dim=384) embeddings.

### Changed

- **MCP API**: Streamlined tools from 22 to 16, removing daemon-only tools and clarifying urgency policy.
- **Eviction Strategy**: Implemented Eviction Formula v2 for smarter RAM management.
- **Logging**: Added Safe/Debug logging mode to protect sensitive data.

### Planned

- **B.2: Continuation Detection**: implementation of scoring logic (HNSW + tags + recency).
- **B.3: Mention Type**: classifier for focus vs passing entities.
- **Safe Logging**: mode to disable diagnostic logs in `config.json`.
- **CLI**: `mnemostroma install-models` for automated environment setup.
- **Decay Engine**: background memory resolution reduction (Stage C).

## [1.6.2] - 2026-03-30

### Fixed

- **Regex Patterns**: Changed `DECISION` and `PROHIBITION` patterns from matching trailing character to positive lookahead `(?=[.,;!\n]|$)`. This enables catching entities at the end of the line and prevents delimiter consumption in the entity value.

## [1.6.1] - 2026-03-30

### Added

- **Hybrid NER**: Introduced `HybridNER` which combines DistilBERT token classification with regex patterns to improve extraction of technology-specific entities, decisions (RU/EN/UA), and prohibitions.

### Changed

- **NER Pipeline**: Migrated `NERObserver` from `BertNER` to `HybridNER`. Full compliance with Rule 2 for CPU-bound offloading via `run_in_executor`.

## [1.6.0] - 2026-03-29

### Added

- **Config-Driven Model Manifest**: Introduced `models_manifest.json` to decouple model paths and parameters from the code.
- **Shared Model Architecture**: Transitioned to a single `gte-multilingual-base` (ONNX INT8) model shared between session and content embedding.
- **ONNX Memory Optimization**: Implemented the `enable_cpu_mem_arena = False` hack in `ModelRegistry` to keep RAM usage within limits.

### Changed

- **Embedding Dimension**: Unified embedding dimension to **768d** (removing MRL truncation).
- **RAM Limits**: Increased resource limits to **650MB (soft)** and **750MB (hard)** to accommodate the new model requirements.
- **Model Registry**: Refactored `ModelRegistry` to use the manifest and provide pre-initialized shared sessions.

### Fixed

- **Content lazy-loading**: Unified the loading logic for all embedding operations.

## [1.5.1] - 2026-03-26

### Added

- **Configuration Centralization**: All implicit feedback weights, EMA alpha, and SQLite resource Pragmas moved to `config.json`.
- **Modular Pipeline**: Extracted `compress_text` and scoring helpers to `observer/utils.py` and `memory/scoring.py`.

### Fixed

- **EMA Calculation**: Corrected formula in `implicit.py` to ensure baseline scaling (neutral signals no longer drift to 0.9).
- **Shutdown Reliability**: Fixed race condition in `DatabaseManager.stop()` ensuring full queue flush before worker exit.
- **Index Consistency**: Unified HNSW labeling logic in `SystemContext.get_hnsw_label()` to resolve `sid_to_id` mapping errors.
- **SQLite Performance**: Pragmas (cache/mmap) are now dynamically loaded from config.

## [1.5.0] - 2026-03-26

### Added

- **Phase 7 Implementation**: 
  - `ModelRegistry` ONNX lazy-loading wrappers (`session_embedder`, `content_embedder`, `ner_observer`, `reranker`).
  - `ConductorProxy` integration layer for XML-based context injection into LLM prompts.
  - `tools/admin.py` with `ctx.status()`, `ctx.sync()`, and `ctx.dump()`.
- **Conflict Detector (Phase 3)**: Semantic dissonance detection using HNSW cosine similarity and Levenshtein distance.
- **Feedback Loop (v1.5)**: `ImplicitFeedbackTracker` for automated USE/IGNORE signal processing.
- **Persistence Layer**: Log instrumentation (18 points) and `logs.db` storage.

### Fixed

- **Architectural Compliance**: 
  - Added missing `deep_use_count` and `last_use_ts` to `sessions` table.
  - Enabled feedback field persistence in `DatabaseManager` flush logic.
  - Refactored `ContentManager` to use unified async queue for non-blocking writes.
  - Resolved `Dissolver` operational gap by enabling background RAM eviction loop.
  - Normalized Content branch embeddings to `float16` for system-wide consistency.
- **EMA Scoring**: Corrected formula in `ImplicitFeedbackTracker` for neutral/negative signals.
- **HNSW Content Index**: Corrected initialization with high-precision parameters (M=32, ef=400).
- **SystemContext (T04)**: Migrated from `Optional[Any]` to strict typing and unified infrastructure access.
- **HNSW Safety**: Added checks for empty indices in `knn_query` to prevent runtime crashes.
- **NER Mock**: Fixed TypeError in `observer_pipeline` regarding empty metadata.

### Security

- **Fail-fast Core**: Added `__post_init__` to `ModelRegistry` to ensure local model storage directory existence.

## [1.0.0] - 2026-03-24

- Initial project bootstrap: Conductor, Observer, RAM Index.
