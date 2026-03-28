# Experience Layer — Спецификация
## Mnemostroma | v1.0 | 2026-03-25
> Собрано из: SESSION_BRIDGE_2026_03_09, ADR_001, config_tuner_patch_v1.4, observer_patch_v1.4

---

## 1. Суть

Experience Layer хранит паттерны успешных и провальных решений.
Memory Layer помнит ЧТО произошло. Experience Layer помнит ЧТО СРАБОТАЛО и ЧТО НЕТ.

```
Memory Layer:  "Мы использовали JWT для авторизации"    (факт)
Experience:    "JWT сработал для REST API"               (+experience)
Experience:    "JWT не сработал для WebSocket auth"      (-experience)
```

---

## 2. Два индекса

| Индекс | Содержание | Семантика |
|--------|-----------|-----------|
| **+Experience Index** | Успешные решения, подходы, паттерны | «это сработало» |
| **-Experience Index** | Провальные решения, ошибки, тупики | «это не сработало» |

Каждая запись содержит два вектора:

| Вектор | Что кодирует | Модель |
|--------|-------------|--------|
| `content_vec` | ЧТО было сделано (содержание) | EmbeddingGemma 512d |
| `process_vec` | КАК это делалось (процесс) | EmbeddingGemma 512d |

`content_vec` — для поиска похожих ситуаций.
`process_vec` — для кластеризации подходов к решению.

---

## 3. Структура записи

```python
@dataclass
class ExperienceEntry:
    exp_id:          str        # unique ID
    session_id:      str        # связь с Memory Layer
    polarity:        str        # "positive" | "negative"
    content_vec:     np.array   # float16[512] — что
    process_vec:     np.array   # float16[512] — как
    confidence:      float      # 0.0–1.0 — уверенность маркировки
    tags:            list[str]  # домен/тема
    brief:           str        # краткое описание (50 chars)
    outcome:         str        # результат ("worked" / "failed" / "partial")
    created_at:      int        # unix timestamp
    use_count:       int        # сколько раз Intuition Signal использовал
    resolution:      float      # 0.05–1.0 (Dissolver управляет)
```

### SQLite таблица

```sql
CREATE TABLE experience (
    exp_id          TEXT PRIMARY KEY,
    session_id      TEXT REFERENCES sessions(session_id),
    polarity        TEXT NOT NULL,  -- 'positive' / 'negative'
    content_vec     BLOB,           -- float16[512]
    process_vec     BLOB,           -- float16[512]
    confidence      REAL DEFAULT 0.5,
    tags            TEXT,           -- JSON array
    brief           TEXT,
    outcome         TEXT,
    created_at      INTEGER,
    use_count       INTEGER DEFAULT 0,
    resolution      REAL DEFAULT 1.0
);

CREATE INDEX idx_exp_polarity ON experience(polarity);
CREATE INDEX idx_exp_session  ON experience(session_id);
```

---

## 4. Маркировка: как определяется polarity

### Фаза A (v1.x): Маркировка через confidence score

Observer + агент определяют результат:

```python
def mark_experience(session_id: str, outcome: str, confidence: float):
    """
    outcome: "worked" | "failed" | "partial"
    confidence: 0.0–1.0 (насколько уверены в оценке)

    Правило:
      outcome == "worked" AND confidence > 0.6  → positive
      outcome == "failed" AND confidence > 0.6  → negative
      confidence ≤ 0.6                          → не записываем (недостаточно данных)
    """
```

Источники маркировки:
- Агент явно: `content.tag(block_id, status="rejected", reason="...")` → negative
- Агент явно: `content.tag(block_id, status="active")` → positive
- Implicit: сессия-потомок с conflict_flag → предок возможно negative

### Фаза B (v1.5): Маркировка + кластеризация

ExperienceCluster группирует записи по process_vec → домены компетенции.

### Фаза C (v3.0): Мини-модели

Pattern Encoder (Siamese ~8MB) + Anomaly Autoencoder (~3MB) — обучаются на накопленном опыте.

---

## 5. process_vec: как строится

Observer добавляет step на КАЖДОЕ сообщение:

```python
step_entry = {
    "msg_index":  int,           # порядковый номер
    "ts":         int,           # timestamp
    "importance": str,           # background/important/critical/principle
    "tags":       list[str],     # топ-3 тега
    "outcome":    None,          # заполняется позже
}
session_step_log[session_id].append(step_entry)
```

Flush в SQLite каждые 20 шагов или при ctx.sync().

Построение process_vec:

```python
def build_process_vec(step_log: list[dict], embedder) -> np.array:
    pattern = " ".join(e["importance"] for e in step_log)
    all_tags = [t for e in step_log for t in e.get("tags", [])]
    tag_summary = " ".join(set(all_tags[:10]))
    process_text = f"process: {pattern} topics: {tag_summary}"
    return embedder.encode(process_text)  # float16[512]
```

---

## 6. ExperienceCluster (v1.5)

### Алгоритм

```python
from sklearn.cluster import DBSCAN
import numpy as np

def cluster_experiences(experience_index: list[ExperienceEntry],
                        config: dict) -> list[ExperienceCluster]:
    vectors = np.array([e.process_vec for e in experience_index])
    clustering = DBSCAN(
        eps=0.25,           # cosine distance threshold
        min_samples=config["experience_cluster_min_samples"],  # дефолт 5
        metric="cosine"
    ).fit(vectors)

    clusters = []
    for label in set(clustering.labels_):
        if label == -1:
            continue  # noise
        members = [e for e, l in zip(experience_index, clustering.labels_) if l == label]
        clusters.append(build_cluster(members))
    return clusters
```

### ExperienceCluster структура

```python
@dataclass
class ExperienceCluster:
    cluster_id:    str
    centroid:      np.array      # float16[512] — центроид process_vec
    pos_count:     int           # количество positive
    neg_count:     int           # количество negative
    pos_neg_ratio: float         # pos / (pos + neg)
    total_hours:   float         # суммарное время работы в домене
    maturity:      str           # novice / competent / expert / master
    dominant_tags: list[str]     # топ-5 тегов кластера
    created_at:    int
    updated_at:    int
```

### Формула maturity

```python
import math

def calculate_maturity(pos_count: int, pos_neg_ratio: float) -> str:
    score = math.log(1 + pos_count) * pos_neg_ratio
    if score < 1.0:   return "novice"
    if score < 3.0:   return "competent"
    if score < 7.0:   return "expert"
    return "master"
```

Логарифмическая шкала: первые записи быстро двигают от novice к competent,
но master требует значительного объёма успешного опыта.

### Пересчёт

- Каждые 24 часа или при +10 новых записей
- Batch job, не критический путь
- Latency: ~5ms для 500 записей

---

## 7. Intuition Signal (v1.5)

### Три типа сигналов

| Сигнал | Семантика | Когда |
|--------|-----------|-------|
| `DO_THIS` | «Я видел похожий успешный паттерн» | cosine(new, +exp) > threshold |
| `AVOID_THIS` | «Я видел похожий провальный паттерн» | cosine(new, -exp) > threshold |
| `TENSION` | «Похоже и на успех, и на провал» | оба > threshold |

### Механика

```python
def evaluate_intuition(new_entity: dict, exp_index: dict,
                       config: dict) -> Optional[IntuitionSignal]:
    threshold = config["intuition_fire_threshold"]  # дефолт 0.82

    pos_score = max_cosine(new_entity["content_vec"], exp_index["positive"])
    neg_score = max_cosine(new_entity["content_vec"], exp_index["negative"])

    if pos_score > threshold and neg_score > threshold:
        return IntuitionSignal(type="TENSION",
                               pos_score=pos_score, neg_score=neg_score)
    if pos_score > threshold:
        return IntuitionSignal(type="DO_THIS",
                               confidence=pos_score, evidence_count=pos_matches)
    if neg_score > threshold:
        return IntuitionSignal(type="AVOID_THIS",
                               confidence=neg_score, evidence_count=neg_matches)
    return None  # не выстрелило
```

### Ключевое свойство: интуиция ошибается

Это **намеренно**. `polarity_confidence` и `evidence_count` всегда передаются
агенту вместе с сигналом. Агент решает сам — следовать интуиции или нет.

```python
@dataclass
class IntuitionSignal:
    type:            str    # DO_THIS / AVOID_THIS / TENSION
    confidence:      float  # 0.0–1.0
    evidence_count:  int    # на скольких записях основан
    cluster_maturity: str   # novice/competent/expert/master (если есть кластер)
```

### Адаптивный threshold по maturity

| Maturity кластера | Threshold | Логика |
|-------------------|-----------|--------|
| novice | 0.90 | Мало данных — осторожнее |
| competent | 0.85 | Средний порог |
| expert | 0.80 | Достаточно данных — доверяем |
| master | 0.75 | Много данных — порог ниже |

### Cooldown

- Максимум 3 сигнала за сессию (`max_intuition_per_session`)
- Cooldown 5 минут между сигналами одного типа
- Предотвращает спам при работе в одном домене

---

## 8. Negative Experience Decay

Провальный опыт **медленно угасает** — технологии меняются, контекст другой.

```
negative_exp_lambda = 0.10
negative_exp_resolution_floor = 0.05

Полураспад: t½ = ln(2) / 0.10 ≈ 7 лет

Со временем:
  t=0:      полная запись провала со всеми деталями
  t=3 года: ослабленная запись, детали тускнеют
  t=7 лет:  половина начального веса
  t→∞:      embedding с весом ~0.05 — «здесь был провал» без подробностей
```

`resolution_floor = 0.05` — суть провала остаётся навсегда (только embedding).
Параметр 🔒 — не рекомендуется менять.

---

## 9. Условия активации

| Компонент | Когда включается | Условие |
|-----------|-----------------|---------|
| Маркировка (+/-) | v1.x MVP | `experience_layer_enabled = true` |
| process_vec | v1.x MVP | `process_vec_enabled = true` |
| ExperienceCluster | v1.5 | ≥200 записей в experience |
| Intuition Signal | v1.5 | ≥200 записей + кластеры сформированы |
| Pattern Encoder | v3.0 | ≥500 записей (300+ pos, 100+ neg) |
| Anomaly Autoencoder | v3.0 | ≥500 pos + кластеры стабильны 30 дней |

---

## 10. RAM и Latency

| Компонент | RAM | Latency | Версия |
|-----------|-----|---------|--------|
| Experience entries (500) | ~1MB | — | v1.x |
| ExperienceCluster | ~0.5MB | ~5ms batch/24h | v1.5 |
| Intuition evaluation | 0MB доп. | ~0.5ms (cosine) | v1.5 |
| Pattern Encoder ONNX | ~8MB | ~3ms | v3.0 |
| Anomaly Autoencoder ONNX | ~3MB | ~1ms | v3.0 |

---

## 11. Конфигурация (из config_tuner_patch_v1.4)

| Параметр | Дефолт | Шкала | Тип |
|----------|--------|-------|-----|
| `experience_layer_enabled` | false | true/false | 🔧 |
| `process_vec_enabled` | true | true/false | 🔧 |
| `process_vec_step_flush_every_n` | 20 | 5–100 | 🔧 |
| `negative_exp_lambda` | 0.10 | 0.0–0.3 | 🔧 🧠 |
| `negative_exp_resolution_floor` | 0.05 | 0.01–0.2 | 🔒 |
| `experience_cluster_min_samples` | 5 | 3–20 | 🔧 |
| `intuition_fire_threshold` | 0.82 | 0.6–0.95 | 🔧 🧠 |

---

*Mnemostroma | Experience Layer Specification | v1.0 | 2026-03-25*
*Собрано из 4 файлов: SESSION_BRIDGE, ADR_001, config_tuner_patch, observer_patch*
