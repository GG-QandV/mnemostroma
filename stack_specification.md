# Стек компонентов — Детальная спецификация
## RAM-First Context System v1.7.1
> Обновлён: 2026-04-07 | Предыдущая версия: 2026-04-04

---

## 1. Итоговый стек

### 1.1 Все компоненты

| Роль | Компонент | FP32 | INT8 | HuggingFace / источник |
|---|---|---|---|---|
| 🔵 **Embedder** | multilingual-e5-small ONNX INT8 | 138MB | 420MB* | `intfloat/multilingual-e5-small` |
| 🏆 **Reranker** | TinyBERT-L2-v2 ONNX INT8 | 28MB | 8MB | `cross-encoder/ms-marco-TinyBERT-L2-v2` |
| 🔍 **NER Observer** | HybridNER (DistilBERT int8 + Regex) | 260MB | 178MB | `Xenova/distilbert-base-uncased-finetuned-conll03-english` |
| 🛡️ **Persistence** | PersistenceLayer (informal split) | 0MB | 0MB | Phase 9.2 v1.7.1 |
| 📦 **ANN индекс** | numpy MatrixSearch (cosine) | 0MB | 0MB | stdlib / numpy |
| 🗜️ **Компрессор** | float16 compression | 0MB | 0MB | `numpy` (stdlib) |
| 💾 **Сжатие контента** | lz4 | 0MB | 0MB | `lz4` (PyPI) |
| 💾 **Cold Storage** | SQLite WAL mode | 0MB | 0MB | `sqlite3` (stdlib) |
| ⚙️ **Inference Engine** | ONNX Runtime 1.18+ | 45MB | 45MB | `onnxruntime` (PyPI) |
| 🐍 **Interpreter** | Python 3.11 slim | 35MB | 35MB | base |
| 📝 **Tokenizer** | HuggingFace tokenizers Rust | 15MB | 15MB | `tokenizers` (PyPI) |

**Итого INT8 RSS: ~631MB**

> *Примечание: EmbeddingGemma и BGE-M3 были заменены на E5-small. RAM для E5 включает tokenizer (270MB) + ONNX (138MB).

### 1.2 Зависимости — только это

```
onnxruntime>=1.18.0
tokenizers>=0.20.0
numpy>=1.26.0
lz4>=4.3.0
aiosqlite>=0.20.0
```

Без torch, без transformers, без langchain, без docker.

---

## 2. Детали каждого компонента

### 2.1 EmbeddingGemma-300M ONNX INT8

- **Назначение:** векторизация сессий и смысловых сущностей (NOT ACTIVE — replaced by E5-small)
- **Особенности:** Matryoshka (MRL) — гибкая размерность 768→512→256→128
- **Размерность:** 384d (unified in v1.7)

```python
from onnxruntime import InferenceSession
from tokenizers import Tokenizer

class EmbeddingGemmaEncoder:
    def __init__(self, model_path: str, tokenizer_path: str):
        self.session = InferenceSession(model_path)
        self.tokenizer = Tokenizer.from_file(tokenizer_path)
        self.dim = 384

    def encode(self, text: str) -> list[float]:
        tokens = self.tokenizer.encode(text)
        inputs = {
            "input_ids": [tokens.ids],
            "attention_mask": [tokens.attention_mask]
        }
        output = self.session.run(None, inputs)[0][0]
        # MRL: берём первые 384 измерения
        vec = output[:self.dim]
        # L2 нормализация
        norm = sum(x*x for x in vec) ** 0.5
        return [x / norm for x in vec]
```

### 2.2 BGE-M3 ONNX INT8

- **Назначение:** векторизация контентных блоков (NOT ACTIVE — replaced by E5-small)
- **Особенности:** dense + sparse + ColBERT одновременно
- **Размерность:** 384d (unified in v1.7)

**Режим ColBERT** для различения версий:
```python
# ColBERT score = MaxSim между токен-матрицами двух версий
# Это ловит точные изменения даже при высокой общей схожести
score = max_sim(tokens_v1, tokens_v2)
```

### 2.3 TinyBERT-L-2-v2 ONNX INT8 (Реранкер)

- **Назначение:** cross-encoder реранкинг top-K результатов HNSWlib
- **Архитектура:** cross-encoder — видит [запрос + документ] вместе
- **Почему не bi-encoder:** bi-encoder логику уже даёт EmbeddingGemma; нужен принципиально другой уровень
- **MRR@10:** 32.56
- **Latency (CPU):** ~6ms на пару

```python
def rerank(query: str, candidates: list[str]) -> list[tuple[str, float]]:
    scores = []
    for doc in candidates:
        pair = f"[CLS] {query} [SEP] {doc} [SEP]"
        tokens = tokenizer.encode(pair)
        score = session.run(None, {"input_ids": [tokens.ids]})[0][0][1]
        scores.append((doc, float(score)))
    return sorted(scores, key=lambda x: -x[1])
```

### 2.4 GLiNER-small-v2.1 ONNX INT8 (Observer NER)

- **Назначение:** zero-shot NER для извлечения сущностей Observer-ом
- **Особенности:** любые типы сущностей без дообучения
- **INT8:** корректно работает (в отличие от medium-версии)
- **Latency:** ~8ms
- **Примеры entity_types:**

```python
entity_types = [
    "решение", "запрет", "артефакт", "концепция",
    "человек", "организация", "продукт", "технология",
    "дата", "число", "адрес", "ссылка"
]
```

### 2.5 MatrixSearch — два независимых индекса
```python
# Индекс для сессионного контекста (numpy, cosine)
session_index = MatrixSearch(dim=384)
# Индекс для контента (numpy, cosine, персистентный)
content_index = MatrixSearch(dim=384)
```

### 2.6 numpy-based MatrixSearch MultiTenant
- **Назначение:** in-RAM векторный поиск с поддержкой namespace
- **Зависимости:** только numpy
- **Использование:** быстрые операции внутри одного namespace (tenant = project_id)
```python
# Сессионная ветка — один tenant
session_db = MatrixSearch(384)
# Контентная — по проекту
content_db = MatrixSearch(384)
```

### 2.7 SQLite WAL + lz4

```python
import sqlite3
import lz4.frame

conn = sqlite3.connect("context.db")
conn.execute("PRAGMA journal_mode=WAL")      # параллельные reads
conn.execute("PRAGMA synchronous=NORMAL")    # баланс скорость/надёжность
conn.execute("PRAGMA cache_size=-64000")     # 64MB page cache
conn.execute("PRAGMA mmap_size=268435456")   # 256MB memory-mapped

# Контент пишем через lz4
compressed = lz4.frame.compress(content_text.encode('utf-8'))
```

---

## 3. RAM-бюджет по масштабам

### Компоненты (фиксированные)

| Компонент | RAM |
|---|---|
| ONNX Runtime + Python + tokenizers | 95MB |
| EmbeddingGemma INT8 | 52MB |
| TinyBERT INT8 | 8MB |
| GLiNER INT8 | 42MB |
| BGE-M3 INT8 | 145MB |
| **Базовый стек** | **342MB** |

### Данные (динамические, float16)

| Масштаб | Session Index | Content Index | Precision Log | TOTAL |
|---|---|---|---|---|
| 50 сессий / 100 блоков | 50MB | 0.4MB | 15MB | **407MB** |
| 200 сессий / 200 блоков | 200MB | 0.8MB | 60MB | **603MB** |
| 200 сессий / 50 блоков* | 200MB | 0.2MB | 60MB | **602MB** |

*Рекомендуемый рабочий режим: 200 сессий скользящее окно + текущий активный проект (~50 блоков)

**Рабочий RAM: ~600MB — вся система на ноутбуке без GPU.**

---

## 4. Latency пайплайн

### Чтение (поиск и ответ агенту)

```
ctx.active()                    <0.01ms   RAM dict
ctx.search(["#JWT", "#auth"])   <0.1ms    RAM dict filter
ctx.semantic("авторизация")
  → Tokenizer                   0.5ms
  → e5-small INT8               10ms
  → MatrixSearch top-20         0.5ms
  → TinyBERT реранкинг          6ms
  → RAM dict brief×5            0.01ms
  ИТОГО:                        ~17ms

ctx.full(session_id)            <0.5ms    SQLite by PK
ctx.precision("link")           <0.1ms    RAM dict
```

### Запись (Observer async)

```
Детерминированный фильтр        0.1ms
GLiNER NER (если нужен)         8ms
EmbeddingGemma encode           12ms
RAM dict update                 0.01ms
MatrixSearch add_item           0.1ms
ИТОГО Observer (async):         ~18ms    (не блокирует агента)

async flush → SQLite            <5ms     (background)
```

---

## 5. Конфигурация системы

```python
CONFIG = {
    # RAM лимиты
    "session_window_size": 200,       # макс сессий в RAM
    "content_max_blocks": 500,        # макс контент-блоков в RAM
    "ram_eviction_threshold": 0.80,   # % RAM при котором evict

    # Score формула
    "score_weights": {
        "relevance": 0.5,
        "temporal": 0.3,
        "importance": 0.2,
    },
    "temporal_decay_lambda": 0.05,

    # Важность
    "importance_levels": {
        "critical":   1.0,
        "important":  0.5,
        "background": 0.1,
    },

    # Brief лимиты
    "brief_max_chars": 50,
    "active_variables_max": 9,        # 7±2 Миллера

    # Возраст сессий
    "age_thresholds_days": {
        "fresh":   1,
        "actual":  7,
        "stale":   30,
        "archive": 90,
    },

    # Тегирование
    "tag_verification_threshold": 0.65,  # cosine для подтверждения тега

    # MatrixSearch
    "session_index": {
        "dim": 384, "space": "cosine",
    },
    "content_index": {
        "dim": 384, "space": "cosine",
    },

    # SQLite
    "sqlite_path": "context.db",
    "sqlite_cache_mb": 64,
    "sqlite_mmap_mb": 256,
}
```

---

## 6. Сравнение с существующими решениями

| Критерий | Mem0 | Letta | AgentCore | **Наша система** |
|---|---|---|---|---|
| RAM | 500MB+ (Docker) | 1GB+ | Cloud | **~600MB** |
| Зависимости | Docker+Qdrant+Postgres | LangChain+Server | AWS SDK | **onnxruntime+numpy** |
| Latency p95 | 1440ms | нестабильно | ~500ms | **~20ms** |
| Два потока | ❌ | ❌ | ❌ | **✅** |
| Якорный слой | ❌ | ❌ | частично | **✅** |
| Прецизионный слой | ❌ | ❌ | ❌ | **✅** |
| Офлайн | ❌ | частично | ❌ | **✅** |
| Контентная ветка | ❌ | ❌ | ❌ | **✅** |
| Академическое обоснование | — | — | — | **LightMem (ICLR 2026)** |
