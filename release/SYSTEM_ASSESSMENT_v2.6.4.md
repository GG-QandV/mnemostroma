# System Assessment — Mnemostroma v2.6.4

**Date:** 2026-09-18
**Source:** live snapshot of the running daemon at release time (local `main`) + full test run.

## Health Summary

| Indicator | Status | Notes |
|-----------|--------|-------|
| HTTP Read adapter (8762) | ✅ ok | `/health` → `{"status":"ok","adapter":"http_read","daemon":"connected"}` |
| Daemon RAM | ✅ ~91 MB | `pulse.json` `ram_mb` = 90.8, `ram_pct` = 14.4 |
| RAM index | ✅ 197 sessions | `status.json` `ram_index_count` = 197, `session_index_count` = 197 |
| Content index | ✅ 4 blocks | `content_index_count` = 4 |
| Pending writes | ✅ 0 | `pending_writes` = 0 |
| NER engine | ✅ gliner | `active_models.ner.engine` = `gliner` (после `install-models`) |
| Tests | ✅ 1811 passed, 25 skipped, 1 xfailed | full run, green |

## Database

| DB | Size | Notes |
|----|------|-------|
| `~/.mnemostroma/mnemostroma.db` | 80 MB | sessions/anchors/precision + WAL |
| `~/.mnemostroma/logs.db` | 193 MB | telemetry (30-day retention) |

## Memory (RSS, snapshot)

| Process | RSS |
|---------|-----|
| all mnemostroma processes | ~273 MB combined |

## Watch items for testers (первый выкат с новой моделью и путём чтения)

- **Латентность обсервера:** длинный текст — N проходов энкодера вместо одного обрезанного;
  NER на 512 токенах ~1.1 с вместо десятков миллисекунд. Гейт держит модель выключенной
  на большинстве наблюдений, но пик на длинных вставках заметен.
- **`ctx.metrics["chunk_cap_hits"]`:** при частых срабатываниях лимит 32 чанка мал для профиля.
- **Утечка `organization` → `location`:** известный дефект модели (ВТБ размечается как место).

## Known Issues / Deferred

- `logs.db` VACUUM deferred (DB locked while daemon runs).
- Whisper speech model not downloaded (`scripts/download_model.sh` pending) — speech-local track.
- Local venv still reports the previously installed version until `pip install -U` is run;
  the release source is v2.6.4.

## Verification commands

```bash
curl -s http://127.0.0.1:8762/health
curl -s http://127.0.0.1:8766/metrics | head
python3 -c "import json;print(json.load(open('$HOME/.mnemostroma/status.json')))"
```
