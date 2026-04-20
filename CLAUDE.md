# Claude Code — Project Instructions

## Language
Always respond in Russian unless the user writes in another language.

## Репозитории — порядок приватности (ОБЯЗАТЕЛЬНО к соблюдению)

| Репо | Тип | Remote | Локальный путь |
|------|-----|--------|----------------|
| **A** | Приватный (source of truth) | `https://github.com/GG-QandV/mnemostroma-core.git` | `/home/gg/projects/Project_mnemostroma` |
| **B** | ZIP-артефакт (не git) | — | `dist/mnemostroma-alpha-<tester-id>.zip` |
| **C** | Публичный | `https://github.com/GG-QandV/mnemostroma.git` | `/home/gg/projects/mnemostroma-public` |

**Правила — никогда не нарушать:**
- Весь код разрабатывается и коммитится ТОЛЬКО в Repo A (`mnemostroma-core`)
- В Repo C (`mnemostroma`) попадает только то что прошло strip_logs и ревью
- Перед любым `git push` — проверить remote: `git remote get-url origin`
- Если remote указывает на `mnemostroma-core` — это Repo A (приватный), всё корректно
- Если нужно пушить в Repo C — переключиться явно на `/home/gg/projects/mnemostroma-public`
- Watermark anchors (`_SESS_DIAG_KEY_`, `_LOGS_ID_DB_`, `_CONS_BUILD_TAG_`) — не удалять, это система трекинга тестеров
- `scripts/issue_build.py` и `scripts/identify_leak.py` — только Repo A, никогда не идут в C

## Синк в Repo C — обязательный порядок

Каждый новый/изменённый файл в Repo A перед попаданием в Repo C проходит классификацию:

| Категория | Признаки | Куда идёт |
|-----------|----------|-----------|
| **Founder-personal** | бизнес, стратегия, бренд, переписка | только Repo A |
| **Dev-only** | ADR, specs, roadmap, scripts/, watermark tools, internal ТЗ | только Repo A |
| **Tester (Repo B)** | src/ без dev-docs + ALPHA_TESTING.md + watermark | ZIP через `issue_build.py` |
| **Public (Repo C)** | README, src/, tests/, CHANGELOG, setup guides | `mnemostroma-public/` |

**Процедура синка в Repo C (выполнять строго по порядку):**

1. Убедиться что файл закоммичен в Repo A
2. Определить категорию по таблице выше
3. Если Public → скопировать в `/home/gg/projects/mnemostroma-public/`
   - файлы из `docs/` Repo A → в корень `mnemostroma-public/` (у него `docs/` в .gitignore)
4. Запустить проверку логирования: `grep -rn "log_event" <скопированные файлы>`
   - если найдено → СТОП, удалить вызовы log_event, затем продолжить
   - strip_logs_v2.py находится в `scripts/strip_logs_v2.py`
5. Перейти в `/home/gg/projects/mnemostroma-public`, проверить `git remote get-url origin` → должен быть `mnemostroma.git`
6. Коммит + push

**Бекапы и архивы (не git):**

| Папка | Что хранится |
|-------|-------------|
| `/home/gg/projects/backups/mnemostroma/MAIN-Faunder` | Founder-personal: стратегия, бизнес, бренд, переписка, всё личное фаундера |
| `/home/gg/projects/backups/mnemostroma/other-old` | Устаревшие файлы из Repo A: старые спеки, черновики, заархивированные версии |

Правило: перед удалением любого файла из Repo A — сначала скопировать в соответствующую папку бекапа. Бекап-папки не находятся под git.

**Repo B (ZIP тестерам):**
Запускать отдельно: `python scripts/issue_build.py <tester-id>` (ветка `main`).
Watermark инжектируется автоматически в `_SESS_DIAG_KEY_`, `_LOGS_ID_DB_`, `_CONS_BUILD_TAG_`.

## CM RAG — жёсткое правило
При любой работе с CM RAG инструментами (cm_save_br, cm_save_im, cm_save_fl, cm_query, cm_search, cm_cross):
- **НЕ выводить** сохраняемый или читаемый контент в терминал
- Вызывать инструмент напрямую, без предварительного или последующего текста с содержимым
- Никаких "сохраняю следующее:", никаких резюме того что было сохранено
- Исключение: только если пользователь явно просит показать содержимое

## Стиль
- Краткие ответы, без лишних слов
- Не подтверждать выполненное действие развёрнутым текстом если результат очевиден
