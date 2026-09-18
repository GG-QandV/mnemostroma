# Release Notes — Mnemostroma v2.5.4

> **Дата:** 2026-09-18

v2.5.4 — release по корректности моделей и учёту памяти: NER-разметка больше не может
тихо сдвинуться, веса моделей больше не считаются вытесняемой памятью, а модельный NER
получил детерминированный гейт.

## What's new

### NER correctness

- **`id2label` читается из `config.json` модели**, а не из захардкоженной карты на 9 меток.
  Модель с другим числом меток (WikiANN — 7, без DATE) сдвигала бы каждый id: PER читался бы
  как DATE, ORG как PER — без единой ошибки в логе. На первом прогоне число меток сверяется
  с размерностью логитов, при несовпадении — `ValueError`.
- **Понятная ошибка на не-BIO метках** вместо молчаливой порчи разметки.
- **Гейт модельного NER** — `needs_model_ner()` в `observer/filter.py`. Модель — самый дорогой
  шаг конвейера и запускалась на 100% наблюдений при цели `observer.ner_call_rate_target` = 0.3.
  Гейт открывают детерминированные сигналы: заглавная буква в середине предложения, дата,
  precision-items, длинный текст. Решение детерминированное намеренно — невоспроизводимую
  память нечем отлаживать. Регексная половина `HybridNER` работает всегда.

### Model engine

- **Режимы pooling `mean|cls`** в `ONNXEmbeddingEngine` — нужны для эмбеддеров с CLS-пулингом
  (granite-embedding-r2). Неизвестный режим — `ValueError`, без молчаливого отката на mean.
- **`ModelDefinition.model_key`** — идентификатор эмбеддера для инвалидации индекса. Проверка
  по размерности не ловит смену модели 384 → 384: векторы читаются, но несравнимы.
- **`graph_optimization_level` и `disable_prepacking`** — настройки ORT-сессии на модель.
  `ORT_ENABLE_ALL` сливает Gather+LayerNorm и разворачивает низкобитные таблицы эмбеддингов
  в fp32 (замерено: +486 MB на INT4-энкодере). Дефолт сохраняет прежнее поведение.
- **`models/footprint.py`** — процесс-уровневый учёт памяти ONNX-сессий: каждая сессия пишет
  свой прирост RSS при загрузке и снимает его при освобождении.

### Memory accounting

- **`onnx_baseline_mb` больше не одноразовый снимок RSS.** Модели грузятся лениво, поэтому их
  вес попадал на «вытесняемую» сторону `evictable_mb = rss - baseline` — и сессии вытеснялись,
  чтобы освободить память под веса моделей, которую вытеснение освободить не может. Теперь
  baseline хранит только процессную часть, а вес моделей учитывается динамически; Dissolver
  читает `ctx.onnx_baseline_total_mb`.
- **При сбое эмбеддера сессия не индексируется случайным вектором.** Случайный единичный вектор
  в 384 измерениях не нейтрален — он оказывается на среднем косинусе ко всему и всплывает в
  выдаче как шум. Сессия сохраняется с `embedding = NULL`, растёт счётчик `embed_failures`,
  вектор восстанавливается переэмбеддингом.
- **`DatabaseManager.check_embedding_model()`** — инвалидация индекса по `model_key` поверх
  `embedding_model_registry`. Вайп запрещён, пока тексты сессий целы: пишется ERROR
  `reembed_required` и флаг `embedding_migration_pending`.

### CLI & deps

- **`mnemostroma --help` / `-h`** завершались кодом 2 (парсер с `add_help=False`). Теперь печатают
  справку.
- **`mcp>=1.0,<2`** — mcp 2.x лишил низкоуровневый `Server` декораторов `list_tools`/`call_tool`,
  свежая установка падала на импорте `integration/mcp_server.py`.
- В dev-extras добавлен `pytest-mock` (без него не собирались тесты с фикстурой `mocker`).
- Ключ дедупликации `EnginePool` учитывает pooling и query-префикс.

### Tests

- Полный прогон приведён в зелёное: **1729 passed, 52 skipped**. `tests/test_behavioral.py`
  переписан под живой код; тесты, которым нужны веса моделей или установленный демон,
  пропускаются с причиной, а не падают.

## Upgrade notes

No breaking changes. Обновление:

```bash
pip install -U "mnemostroma @ git+https://github.com/GG-QandV/mnemostroma.git@v2.5.4"
systemctl --user restart mnemostroma-daemon
```

Конфиг менять не нужно; новые поля (`model_key`, `graph_optimization_level`,
`disable_prepacking`) опциональны и по умолчанию сохраняют прежнее поведение.

## Stats

| Metric | Value |
| ------ | ----- |
| Tests | 1729 passed, 52 skipped |
| Breaking changes | 0 |
| Daemon RSS (baseline) | ~200 MB |
| RAM index | 200 sessions |

**v2.5.4** | Model Correctness & Memory Accounting Release
