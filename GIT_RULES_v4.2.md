# Git Workflow — Mnemostroma Core (v4.2)

**Version**: 4.2 | **Date**: 2026-05-10
**Scope**: Repo A (Core) → Repo C (Public)
**Baseline**: v1.11.2 | 502 tests

---

## 1. Два типа коммитов

Большинство работы — **Repo A only**. Sync в Repo C делается реже, только когда изменения готовы к публикации.

| Тип | Когда | Repo C нужен? |
|-----|-------|---------------|
| `fix`, `feat`, `refactor`, `test` | Любая разработка | Нет — если не готово к релизу |
| `docs`, `chore(release)` | Релиз / версия | Да → запустить Sync |

---

## 2. Коммит в Repo A (ежедневный)

```bash
cd ~/projects/Project_mnemostroma
git add <конкретные файлы>    # никогда не git add -A без git status
git commit -m "<type>(<scope>): <описание>"
git push origin main
```

**Формат коммита:**

| Type | Scope | Пример |
|------|-------|--------|
| `feat` | storage, observer, core, integration, tools, ports, adapters | `feat(observer): Content Branch automation` |
| `fix` | (те же) | `fix(core): missing LogWriter import in conductor.py` |
| `refactor` | (те же) | `refactor(storage): hexagonal ports` |
| `test` | — | `test: regression tests for v1.11.2` |
| `docs` | — | `docs: update UPGRADE.md for v1.11.2` |
| `chore` | — | `chore: bump version to 1.11.2` |

Ограничения: один коммит — не более 3 модулей. Нет WIP, нет коммитов с failing тестами.

---

## 3. Управление версиями при релизах

Mnemostroma использует строгое разделение обязанностей при выпуске версий:
1. **Вручную (Разработчик)**: Задаёт новую актуальную версию в `pyproject.toml` в секции `[project]`:
   ```toml
   [project]
   version = "X.Y.Z" # (например, "2.1.5")
   ```
2. **Вручную (Разработчик)**: Указывает предыдущую стабильную версию в секции `[tool.mnemostroma]` в `previous_version`:
   ```toml
   [tool.mnemostroma]
   previous_version = "A.B.C" # (например, "2.0.5")
   ```
   *Примечание:* Это значение используется скриптом для автоматического поиска и предупреждения о забытых упоминаниях старой стабильной версии по всей кодовой базе при запуске.
3. **Автоматически (скрипт update_version.py)**:
   При запуске `python scripts/update_version.py` скрипт автоматически:
   - Раскатывает новую версию по всем документам (`README.md`, `UPGRADE.md`, `version.py`).
   - Добавляет суффикс `Beta` (для бета-версий) согласно регулярным выражениям.
   - Сканирует репозиторий на забытые ссылки старой версии `previous_version`.
   - Выполняет ротацию: в конце успешного запуска автоматически перезаписывает `previous_version` в `pyproject.toml` на актуальную `version` (для готовности к следующему шагу разработки).

---

## 4. Sync A → C (только при релизе)

Запускать только из `main` Repo A, только когда код готов к публикации.

```bash
REPO_A=~/projects/Project_mnemostroma
REPO_C=~/projects/mnemostroma-public

cd $REPO_A

# 1. Версия и документы
python scripts/update_version.py        # exit 0 обязателен

# 2. Стриппинг src/ + копирование публичных файлов
python scripts/strip_logs_v2.py --dir src/ $REPO_C/src/

# ⚠️ Обязательно после strip: восстановить критический импорт
# (strip_logs_v2.py удаляет любой импорт из *log_writer*)
sed -i '1i from mnemostroma.storage.log_writer import LogWriter' \
    $REPO_C/src/mnemostroma/conductor.py

cp README.md CHANGELOG.md UPGRADE.md pyproject.toml $REPO_C/
cp scripts/update_version.py $REPO_C/scripts/

# 3. Release-файлы (при релизе)
cp release/RELEASE_NOTES_vX.Y.Z.md $REPO_C/release/
cp release/QUICKSTART_vX.Y.Z.md    $REPO_C/release/
cp release/SYSTEM_ASSESSMENT_vX.Y.Z.md $REPO_C/release/

# 4. Guard (pre-commit hook дублирует, но явная проверка быстрее)
# Исключаем __pycache__, комментарии и def log_event (публичный API)
grep -rn "log_event" $REPO_C/src/ --include="*.py" \
  | grep -vE "^[^:]+:#|def log_event|log_event access|log_event instrumentation|via log_event" \
  && echo "STOP: executable log_event call found in Repo C src/" && exit 1 || true

# 4. Коммит Repo C
cd $REPO_C
git remote get-url origin               # mnemostroma.git — проверить перед push
git add -A
git commit -m "<type>: <описание>"
git push origin main
```

> `git add -A` в Repo C безопасен: pre-commit hook блокирует watermarks и `log_event`. В Repo A — только явные файлы.

---

## 5. Тег (после push Repo A)

```bash
git tag -a vX.Y.Z -m "vX.Y.Z: <одна строка>"
git push origin vX.Y.Z
```

**Инкремент**: `patch` — hotfix/docs, `minor` — новая фича, `major` — breaking change.
**Снапшот перед рефакторингом**: `git tag -a vX.Y.Z-pre-refactor -m "Snapshot. 502 tests."`

---

## 6. Ветки

```
main                     ← прямые коммиты: только hotfix и chore
fix/<slug>               ← хотфикс → squash merge в main
feat/<slug>              ← фича → rebase merge в main
refactor/phase-N-<name>  ← рефакторинг → squash merge в main
experiment/_lab/<slug>   ← никогда не мержить в main напрямую
```

```bash
# squash merge (hotfix/feat):
git checkout main && git merge --squash fix/<slug>
git commit -m "fix(<scope>): <описание>"

# rebase merge (feat с историей):
git rebase main feat/<slug>
git checkout main && git merge --ff-only feat/<slug>
```

---

## 7. Откат

```bash
systemctl --user stop mnemostroma-watchdog.service
kill -SIGUSR1 $(cat ~/.mnemostroma/daemon.pid) && sleep 10
mnemostroma off

git reset --hard $(git tag --sort=-version:refname | sed -n '2p')

~/.mnemostroma/venv/bin/pip install \
  "mnemostroma[all] @ git+https://github.com/GG-QandV/mnemostroma.git@$(git describe --tags)"

mnemostroma on
systemctl --user enable --now mnemostroma-watchdog.service
mnemostroma status
```

---

## 8. Запрещено

```
❌ push Repo A → mnemostroma.git (Repo C remote) — и наоборот
❌ git add -A в Repo A
❌ --no-verify без явного разрешения
❌ push в Repo C из ветки refactor/* или feat/*
❌ коммит с failing тестами в main
❌ .watermarks_registry.csv, dist/, logs.db, *.db в любом репо
❌ git-доступ тестерам — только ZIP
```

---

## 9. Файлы только для Repo A (никогда в C)

```
private/, instructions/, CONTRIBUTING_INTERNAL*.md
AGENTCODINGINSTRUCTIONS*.md, TASK*.md, ADR*.md, SPEC*.md, ROADMAP*.md
scripts/issue_build.py, scripts/identify_leak.py, .watermarks_registry.csv
CLAUDE.md, docs/ADR/, docs/analysis/
```

---

## 10. Язык

Код, docs, commits: **English** | Инструкции агентам: **Russian**

---

*v4.2 | 2026-05-17 | Добавлено: Раздел 3 - Управление версиями при релизах, инкрементированы последующие разделы*
