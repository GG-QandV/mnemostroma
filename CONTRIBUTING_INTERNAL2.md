# Mnemostroma Internal Development Workflow

## Tri-Repo Split

*Last updated: 2026-04-13*

---

## 1. Repository Architecture

| Repo | Type                   | Audience       | Local path                             |
| ---- | ---------------------- | -------------- | -------------------------------------- |
| A    | Private git            | Founder / devs | ~/projects/Project_mnemostroma         |
| B    | ZIP artifact (not git) | Alpha testers  | dist/mnemostroma-alpha-<tester-id>.zip |
| C    | Public git             | End users      | ~/projects/mnemostroma-public          |

Before any `git push`, always verify remote:

```bash
git remote get-url origin
# Repo A must show: mnemostroma-core.git
# Repo C must show: mnemostroma.git
```

---

## 2. File Classification

| Category         | Examples                                                                               | Repo A | Repo B | Repo C |
| ---------------- | -------------------------------------------------------------------------------------- |:------:|:------:|:------:|
| Public           | README, CHANGELOG, src/, tests/, pyproject.toml, setup guides                          | ✓      | ✓      | ✓      |
| Tester-only      | ALPHATESTING.md                                                                        | ✓      | ✓      | —      |
| Dev-only         | SPEC.md, ADR.md, ROADMAP.md, MASTER_ROADMAP.md, CHECKLIST.md, CONTRIBUTING_INTERNAL.md | ✓      | —      | —      |
| Founder-personal | Business strategy, brand, correspondence                                               | ✓      | —      | —      |
| Watermark tools  | scripts/issue_build.py, scripts/identify_leak.py, .watermarks_registry.csv             | ✓      | —      | —      |

> `docs/` from Repo A → copy to **root** of Repo C.
> Repo C has `docs/` in `.gitignore`.

### Публичные файлы — актуальный список (src/)

| Файл                                        | Добавлен   | Примечание                              |
| ------------------------------------------- | ---------- | --------------------------------------- |
| `src/mnemostroma/memory/growth_forecast.py` | 2026-04-13 | GrowthForecast, два режима (linear/exp) |
| `src/mnemostroma/memory/consolidation.py`   | 2026-04-13 | db_snapshots tick, snapshot_db_sizes    |
| `src/mnemostroma/storage/log_writer.py`     | 2026-04-13 | метод snapshot_db_sizes                 |
| `src/mnemostroma/storage/sqlite.py`         | 2026-04-13 | таблица db_snapshots + индекс           |
| `src/mnemostroma/tools/admin.py`            | 2026-04-13 | интеграция GrowthForecast в ctx_growth  |
| `src/mnemostroma/__main__.py`               | 2026-04-13 | вывод прогноза в CLI                    |
| `tests/test_growth.py`                      | 2026-04-13 | 10 юнит-тестов GrowthForecast           |

---

## 3. Syncing Repo A → Repo C

**When to sync**: after any commit to Repo A that touches Public-category files and is ready for users.

### Procedure (strict order)

**Step 1** — Verify Repo A is committed:

```bash
git status           # must be clean
git log --oneline -3
```

**Step 2** — Copy public files to Repo C:

```bash
PUBLIC=~/projects/mnemostroma-public

# src — copy changed files only
cp src/mnemostroma/memory/growth_forecast.py  $PUBLIC/src/mnemostroma/memory/
cp src/mnemostroma/memory/consolidation.py    $PUBLIC/src/mnemostroma/memory/
cp src/mnemostroma/storage/log_writer.py      $PUBLIC/src/mnemostroma/storage/
cp src/mnemostroma/storage/sqlite.py          $PUBLIC/src/mnemostroma/storage/
cp src/mnemostroma/tools/admin.py             $PUBLIC/src/mnemostroma/tools/
cp src/mnemostroma/__main__.py                $PUBLIC/src/mnemostroma/
cp tests/test_growth.py                       $PUBLIC/tests/

# Root docs (not docs/ — it's gitignored in Repo C)
cp README.md CHANGELOG.md pyproject.toml     $PUBLIC/
cp docs/CLAUDE_AI_SETUP.md                   $PUBLIC/
cp docs/MCP_TOOLS_MAP.md                     $PUBLIC/
```

**Step 3** — Verify watermark anchors are empty:

```bash
grep -rn "LOGSIDDB\|SESSDIAGKEY\|CONSBUILDTAG" $PUBLIC/src --include="*.py"
# Must return nothing (or lines with empty values "")
```

> **Note**: Logging code (`logevent`, `LogWriter`, `log_writer`) does **NOT** need to be stripped.
> It is safe to ship. Default config has `logging.enabled: false` — logs write nothing without
> user opt-in. The pre-commit hook in Repo C guards only watermark anchor values, not logging.

**Step 4** — Commit and push Repo C:

```bash
cd $PUBLIC
git remote get-url origin   # must be mnemostroma.git
git add -A
git commit -m "feat/fix/docs: ..."
git push
# Pre-commit hook runs automatically and blocks if any anchor has a non-empty value
```

---

## 4. Pre-commit Hook (Repo C)

Located at `~/projects/mnemostroma-public/.git/hooks/pre-commit`.

- Blocks `LOGSIDDB`, `SESSDIAGKEY`, `CONSBUILDTAG` with any value other than `""`
- Allows all logging code: `logevent`, `LogWriter`, `log_writer`
- **Rationale**: watermarks are the only thing that must not reach Repo C with real values.
  Logging infrastructure is public and safe.

---

## 5. Repo B — Tester ZIPs

Repo B is **not a git repository**. It is a per-tester installable ZIP with injected watermarks.

```bash
python scripts/issue_build.py <tester-id> --branch alpha
# Output: dist/mnemostroma-alpha-<tester-id>.zip
# Send directly to the tester — never publish via GitHub or any public URL
```

ZIP contains: full source + logging + common docs + ALPHATESTING.md + unique watermark.
ZIP does NOT contain: dev/founder docs, `issue_build.py`, `identify_leak.py`, `.watermarks_registry.csv`.

### Watermark anchors (injected per-tester)

| Anchor         | File                                      |
| -------------- | ----------------------------------------- |
| `LOGSIDDB`     | `src/mnemostroma/storage/sqlite.py`       |
| `SESSDIAGKEY`  | `src/mnemostroma/conductor.py`            |
| `CONSBUILDTAG` | `src/mnemostroma/memory/consolidation.py` |

Leak identification:

```bash
python scripts/identify_leak.py path/to/leaked_file.py
# Registry: scripts/.watermarks_registry.csv — NEVER commit to any repo
```

> **Repo B status**: sleeping. Next ZIP build only when explicitly needed.

---

## 6. Repo A Commit Rules

- All work goes to `main` in Repo A
- Merge `main` → `alpha` before building Repo B ZIPs:
  
  ```bash
  git checkout alpha
  git merge main --no-edit
  git push origin alpha
  git checkout main
  ```
- Commit messages: English, conventional commits (`feat/fix/refactor/docs/chore`)
- Never use `--no-verify` unless explicitly authorized

---

## 7. Safety Rules — Never Break

- **NEVER** push Repo A to `mnemostroma.git` (Repo C remote)
- **NEVER** push Repo C to `mnemostroma-core.git` (Repo A remote)
- **NEVER** commit `.watermarks_registry.csv` or `dist/` to any git repo
- **NEVER** give testers git access — ZIP only
- **NEVER** put `SPEC.md`, `ADR.md`, `ROADMAP.md`, or founder docs in Repo C
- **NEVER** bypass the pre-commit hook in Repo C (`--no-verify`)
- **ALWAYS** run `git remote get-url origin` before pushing

---

## 8. Backups (non-git)

| Path                                          | Contents                                                    |
| --------------------------------------------- | ----------------------------------------------------------- |
| `~/projects/backups/mnemostroma/MAIN-Faunder` | Founder-personal: strategy, business, brand, correspondence |
| `~/projects/backups/mnemostroma/other-old`    | Archived files from Repo A: old specs, drafts               |

> Before deleting any file from Repo A — copy to backup first.

---

## 9. Language Policy

- Code, docs, specs, commit messages: **English**
- CLAUDE.md responses: **Russian** (per project instructions)
- User data processed by the system: any language, by design
