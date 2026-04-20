# GIT_RULES.md
# Версия: 1.0 | Дата: 2026-04-14
# Область: Repo A (mnemostroma-core) — все правила ниже только для него.
# Repo C (public) управляется через scripts/striplogsv2.py отдельно.

## 1. Структура веток
```text
main                        ← единственный источник правды. Всегда рабочий.
                              Прямые коммиты ЗАПРЕЩЕНЫ.

refactor/phase-N-<name>     ← ветки рефакторинга. Одна фаза = одна ветка.
  refactor/phase-1-cli
  refactor/phase-2-ports
  refactor/phase-2.5-observer
  refactor/phase-3-tools

fix/<issue-id>-<slug>       ← хотфиксы. Основаны на main, мержатся в main.
  fix/bt17-scoring-ema

feat/<slug>                 ← новые фичи НЕ связанные с рефакторингом.
  feat/growth-forecast

experiment/_lab/<slug>      ← эксперименты. НИКОГДА не мержатся в main напрямую.
  experiment/_lab/hexagonal-poc
```
Правило зависимостей между ветками рефакторинга:

```text
phase-1 → merge в main → phase-2 основана на обновлённом main
                       → phase-3 основана на обновлённом main
НЕ допускается: phase-3 основана на phase-2 напрямую
```

## 2. Правила коммитов
Формат (Conventional Commits — обязателен)
```text
<type>(<scope>): <описание на русском или английском>

type:
  feat     — новая функциональность
  fix      — исправление бага
  refactor — рефакторинг без изменения поведения
  test     — только тесты
  docs     — только документация
  chore    — инфра, зависимости, скрипты
  shadow   — shadow mode код (временный, будет удалён)
  legacy   — пометка legacy-кода перед удалением

scope: модуль затронутый изменением
  storage | observer | memory | tools | integration | tuner | core | ports | adapters
```
Примеры правильных коммитов
```bash
feat(ports): добавить SessionPort Protocol и Result types
refactor(storage): вынести ConnectionPool из sqlite.py в adapters/sqlite/
shadow(storage): ShadowSessionRepo — параллельный запуск legacy + new
test(storage): тест консистентности ShadowSessionRepo за 24h
fix(observer): pipeline не создаёт asyncio.Task внутри StepChain
chore(scripts): добавить check_dependencies.py для import-linter
legacy(storage): пометить sqlite.py к удалению после Phase 2 stable
```
Запрещённые коммиты
```bash
# ❌ ЗАПРЕЩЕНО — нет scope
git commit -m "fix bug"
git commit -m "wip"
git commit -m "update"
git commit -m "."

# ❌ ЗАПРЕЩЕНО — слишком крупный коммит
# Один коммит не должен трогать больше 3 модулей одновременно
# Исключение: chore (зависимости), docs (обновление всех доков разом)

# ❌ ЗАПРЕЩЕНО — коммит с failing тестами в main
# Проверить до коммита: pytest tests/ --tb=short -q
```

## 3. Правила слияния (merge) в main
Ветка refactor/phase-N может быть смержена в main только если выполнены ВСЕ условия:

```text
□ 1. pytest tests/ → 403/403 passed (или больше если добавлены новые)
□ 2. import-linter → 0 нарушений (python scripts/check_dependencies.py)
□ 3. python scripts/gen_contracts.py --check → registry актуален
□ 4. pytest tests/test_latency_invariants.py → все бюджеты выдержаны
□ 5. Shadow mode работал минимум 24h без shadow.mismatch в логах
     (только для веток затрагивающих storage/)
□ 6. mnemostroma status → daemon запустился и прошёл health check
□ 7. CHANGELOG.md обновлён
```
Merge стратегия — только squash или rebase, НЕ merge commit:

```bash
# Правильно — squash все коммиты фазы в один чистый:
git checkout main
git merge --squash refactor/phase-2-ports
git commit -m "refactor(storage): Phase 2 — Ports + Adapters + ShadowRepo"

# ИЛИ rebase для сохранения истории:
git rebase main refactor/phase-2-ports
git checkout main
git merge --ff-only refactor/phase-2-ports
```

## 4. Правила для трёх репо (специфика Mnemostroma)
```text
Repo A (mnemostroma-core)     ← основная разработка, все правила выше
Repo B (tester ZIP)           ← генерируется автоматически, git не ведётся вручную
Repo C (mnemostroma-public)   ← синхронизируется через striplogsv2.py
```
Синхронизация A → C (public)
```bash
# Делать ТОЛЬКО из main ветки Repo A, ТОЛЬКО после merge фазы:
git checkout main
git pull

# 1. Убедиться что remote правильный:
git remote get-url origin
# Если origin = mnemostroma-core (Repo A) — правильно

# 2. Запустить stripping:
cd ~/projects/mnemostroma-public
python ~/projects/mnemostroma-core/scripts/striplogsv2.py

# 3. Проверить watermarks:
python scripts/identifyleak.py

# 4. Только после этого push в Repo C
git push

# ❌ ЗАПРЕЩЕНО: push в Repo C из ветки refactor/*
# ❌ ЗАПРЕЩЕНО: push в Repo C если тесты не прошли
# ❌ ЗАПРЕЩЕНО: push в Repo C с незачищенными watermarks
```
Что НИКОГДА не попадает в Repo C
```text
logs.db
mnemostroma.db
*.db.bak*
private/
.rollbackpoint.txt
instructions/   (все инструкции для агентов)
AGENTCODINGINSTRUCTIONS*.md
MNEMOSTROMAINVENTORY*.md
CONTRIBUTINGINTERNAL*.md
TASK*.md
scripts/identifyleak.py
scripts/issuebuild.py
.watermarksregistry.csv
```

## 5. Теги и версии
```bash
# Тег ставится ТОЛЬКО на main ПОСЛЕ успешного merge фазы:
git tag -a v1.8.0-phase1 -m "Phase 1: core/bootstrap.py, CLI refactor"
git tag -a v1.8.0-phase2 -m "Phase 2: Ports + Adapters + ShadowSessionRepo"

# Формат: v<major>.<minor>.<patch>-<phase-slug>
# Во время рефакторинга minor не меняется до завершения всех фаз
# После завершения всех фаз рефакторинга: тег v2.0.0

# Snapshot перед началом рефакторинга (сделать сейчас):
git tag -a v1.7.5-pre-refactor -m "Snapshot before hexagonal refactor. 403 tests passing."
git push origin v1.7.5-pre-refactor
```

## 6. Откат (Emergency Rollback)
```bash
# Ситуация: смержили Phase 2 в main, что-то сломалось в production

# Шаг 1 — daemon flush (не терять RAM):
kill -SIGUSR1 $(cat ~/.mnemostroma/daemon.pid)
sleep 3

# Шаг 2 — вернуть main на pre-refactor snapshot:
git checkout main
git revert HEAD --no-edit
# ИЛИ жёсткий откат если revert недостаточен:
git reset --hard v1.7.5-pre-refactor

# Шаг 3 — переустановить пакет:
pip install -e .

# Шаг 4 — перезапустить daemon:
mnemostroma off && mnemostroma on

# Шаг 5 — проверить:
mnemostroma status
pytest tests/ -q --tb=short

# Правило: откат должен занимать < 5 минут.
# Если занимает больше — структура фазы была слишком крупной.
```

## 7. Защита критических файлов
Добавить в .git/hooks/pre-commit:

```bash
#!/bin/bash
# Запрещает случайный коммит критических файлов в Repo C

FORBIDDEN=(
  "logs.db"
  "mnemostroma.db"
  ".watermarksregistry.csv"
  "private/"
  "AGENTCODINGINSTRUCTIONS"
)

for pattern in "${FORBIDDEN[@]}"; do
  if git diff --cached --name-only | grep -q "$pattern"; then
    echo "❌ BLOCKED: попытка закоммитить запрещённый файл: $pattern"
    exit 1
  fi
done

# Проверить что тесты не broken (быстрый smoke-test):
python -m pytest tests/test_basic.py -q --tb=short 2>/dev/null
if [ $? -ne 0 ]; then
  echo "❌ BLOCKED: smoke-тест не прошёл. Запусти pytest tests/ перед коммитом."
  exit 1
fi

exit 0
```
```bash
# Установить hook:
chmod +x .git/hooks/pre-commit
```

## 8. Правило одного коммита для legacy-удаления
Когда старый файл готов к удалению (Shadow Mode завершён, фаза стабильна):

```bash
# Один отдельный коммит ТОЛЬКО для удаления:
git rm src/mnemostroma/storage/sqlite_legacy.py
git commit -m "legacy(storage): удалить sqlite.py — заменён adapters/sqlite/session_repo.py (Phase 2 stable 7d)"

# Правило: коммит legacy-removal не содержит НИЧЕГО кроме git rm
# Причина: легко найти в истории и легко отменить если нужно
```
