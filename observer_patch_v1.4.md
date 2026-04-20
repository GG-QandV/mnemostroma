# Observer — Патч v1.4
## Добавлено: GLiNER dual-mode, tech labels, process_vec per-message
## Дата: 2026-03-24

---

## Патч 1: GLiNER Dual-Mode (NEW-01 resolution)

**Decision:** Both models available, selected via config or runtime flag. Default = `small`.

**Rationale:** Test both, keep small if precision sufficient, switch to medium for tech-heavy projects.

```python
GLINER_MODES = {
    "small":  {"model": "urchade/gliner_small-v2.1",  "ram_mb": 42,  "latency_ms": 8},
    "medium": {"model": "urchade/gliner_medium-v2.1", "ram_mb": 95,  "latency_ms": 18},
}

# config.json
{
  "gliner_mode": "small",  # "small" | "medium" | "auto"
}
# "auto": start with small, switch to medium if ner_precision < 0.7 after 50 sessions
```

### Runtime Switching (no restart required)

```python
async def switch_gliner_mode(new_mode: str, conductor) -> dict:
    """Unload current GLiNER, load new one. Observer pauses for ~2-3 seconds."""
    await conductor.pause_observer()
    conductor.gliner_session = load_onnx_model(GLINER_MODES[new_mode]["model"])
    conductor.config["gliner_mode"] = new_mode
    await conductor.resume_observer()
    return {"mode": new_mode, "ram_mb": GLINER_MODES[new_mode]["ram_mb"]}
```

> **config_tuner:** Add `gliner_mode` parameter with values `small` / `medium` / `auto`.

---

## Патч 2: Extended Tech-Domain NER Labels (WP-15)

**Current labels:** `["решение","запрет","артефакт","технология","концепция","вопрос","человек","продукт"]`

Add `TECH_LABELS` for `session_type == "content"` or `"context"` with tech signals:

```python
TECH_LABELS_EXTENDED = [
    # базовые (всегда)
    "решение", "запрет", "артефакт", "технология", "концепция", "вопрос", "человек", "продукт",
    # tech-domain (добавляются при session_type in ["content", "context"])
    "function_name", "module_name", "library", "api_endpoint",
    "sql_query", "constant", "config_key", "error_code",
    "version", "url", "constraint", "database_table",
]

def get_ner_labels(session_type: str) -> list[str]:
    if session_type in ("content", "context"):
        return TECH_LABELS_EXTENDED
    return TECH_LABELS_EXTENDED[:8]  # базовые только
```

> **Note:** Medium GLiNER benefits more from extended labels (better zero-shot coverage).

---

## Патч 3: process_vec Incremental — Every Message (NEW-06 resolution)

**Decision:** Observer adds a step to Experience Layer on EVERY message (not just important ones).

**Rationale:** Experience accumulates from all interactions, filtering happens at cluster level.

```python
async def observer_process(agent_output: str, session_id: str, msg_index: int):
    # ... existing pipeline steps 1-6 ...

    # NEW v1.4: step_log для Experience Layer
    step_entry = {
        "msg_index":  msg_index,           # порядковый номер в сессии
        "ts":         int(time.time()),
        "importance": filter_result["importance"],
        "tags":       entity["tags"][:3],  # только топ-3 тега
        "outcome":    None,                # заполняется агентом через content.tag()
    }
    session_step_log[session_id].append(step_entry)

    # Flush step_log в SQLite при конце сессии (или каждые 20 шагов)
    if msg_index % 20 == 0:
        asyncio.create_task(flush_step_log(session_id, step_log, db_conn))
```

### New SQLite Table

```sql
CREATE TABLE IF NOT EXISTS session_steps (
    session_id   TEXT,
    msg_index    INTEGER,
    ts           INTEGER,
    importance   TEXT,
    tags         TEXT,   -- JSON array, max 3
    outcome      TEXT,   -- NULL until agent marks it
    PRIMARY KEY (session_id, msg_index)
);
```

### process_vec (Experience Layer vectorization)

```python
def build_process_vec(step_log: list[dict], embedder) -> list[float]:
    """
    Encodes the HOW (process pattern) of a session, not WHAT.
    Used by Experience Layer to cluster similar problem-solving approaches.
    Input: step_log entries for one session
    Output: 512d float16 vector
    """
    # Encode sequence of importance levels as text pattern
    pattern = " ".join(e["importance"] for e in step_log)
    # Append dominant tags
    all_tags = [t for e in step_log for t in e.get("tags", [])]
    tag_summary = " ".join(set(all_tags[:10]))
    process_text = f"process: {pattern} topics: {tag_summary}"
    return embedder.encode(process_text)
```

---

*Observer Patch v1.4 | 2026-03-24 | Дополняет observer_specification_v1.3.md*
