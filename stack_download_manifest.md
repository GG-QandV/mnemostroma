# Mnemostroma — Stack Download Manifest

## Все компоненты для скачивания: модели, библиотеки, БД

## v1.0 | 2026-03-25

---

## 1. ONNX Модели (342MB суммарно)

### EmbeddingGemma-300M (сессионный эмбеддер)

| Параметр     | Значение                           |
| ------------ | ---------------------------------- |
| Роль         | Векторизация сессий, 512d MRL      |
| RAM          | ~52MB                              |
| Лицензия     | Gemma License (Google)             |
| Quantization | Q8 (quantized), FP32 (unquantized) |

| Вариант                             | URL                                                                | Примечание                                 |
| ----------------------------------- | ------------------------------------------------------------------ | ------------------------------------------ |
| **ONNX official (рекомендуемый)**   | https://huggingface.co/onnx-community/embeddinggemma-300m-ONNX     | FP32 + Q8 + Q4 варианты, subfolder `onnx/` |
| ONNX uint8 (community)              | https://huggingface.co/electroglyph/embeddinggemma-300m-ONNX-uint8 | uint8 output для vector DBs                |
| Оригинал (PyTorch, для конвертации) | https://huggingface.co/google/embeddinggemma-300m                  | Gemma license, нужен accept agreement      |

**Скачать:**

```python
from huggingface_hub import hf_hub_download
# Q8 quantized (рекомендуемый)
hf_hub_download("onnx-community/embeddinggemma-300m-ONNX", 
                subfolder="onnx", filename="model_quantized.onnx")
hf_hub_download("onnx-community/embeddinggemma-300m-ONNX", 
                subfolder="onnx", filename="model_quantized.onnx_data")
```

**Важно:** EmbeddingGemma НЕ поддерживает float16 activations. Использовать FP32 или INT8/Q8.

---

### BGE-M3 (контентный эмбеддер)

| Параметр     | Значение                               |
| ------------ | -------------------------------------- |
| Роль         | Векторизация контента, dense + ColBERT |
| RAM          | ~145MB (INT8) / ~540MB (FP32)          |
| Лицензия     | MIT                                    |
| Quantization | INT8 доступен                          |

| Вариант                       | URL                                                | Примечание                               |
| ----------------------------- | -------------------------------------------------- | ---------------------------------------- |
| **ONNX INT8 (рекомендуемый)** | https://huggingface.co/gpahal/bge-m3-onnx-int8     | INT8, dense+sparse+ColBERT               |
| ONNX INT8 (Teradata)          | https://huggingface.co/Teradata/bge-m3             | INT8, tested с Teradata                  |
| ONNX FP32 (full features)     | https://huggingface.co/aapot/bge-m3-onnx           | FP32, dense+sparse+ColBERT, O2 optimized |
| ONNX (yuniko, multi-language) | https://huggingface.co/yuniko-software/bge-m3-onnx | C#/Java/Python examples                  |
| Оригинал (PyTorch)            | https://huggingface.co/BAAI/bge-m3                 | 567M params                              |

**Скачать:**

```python
from optimum.onnxruntime import ORTModelForCustomTasks
model = ORTModelForCustomTasks.from_pretrained("gpahal/bge-m3-onnx-int8")
```

---

### GLiNER-small-v2.1 (NER)

| Параметр | Значение                            |
| -------- | ----------------------------------- |
| Роль     | Zero-shot NER, извлечение сущностей |
| RAM      | ~42MB (small) / ~95MB (medium)      |
| Лицензия | Apache 2.0                          |

| Вариант                        | URL                                                     | Примечание                       |
| ------------------------------ | ------------------------------------------------------- | -------------------------------- |
| **ONNX small (рекомендуемый)** | https://huggingface.co/onnx-community/gliner_small-v2.1 | ONNX weights в subfolder `onnx/` |
| ONNX medium                    | https://huggingface.co/onnx-community/gliner_multi-v2.1 | Multilingual, больше но точнее   |
| ONNX large                     | https://huggingface.co/onnx-community/gliner_large-v2.1 | Enterprise tier                  |
| Оригинал small (PyTorch)       | https://huggingface.co/urchade/gliner_small-v2.1        | Apache 2.0                       |
| Оригинал medium (PyTorch)      | https://huggingface.co/urchade/gliner_medium-v2.1       | Apache 2.0                       |
| Оригинал large (PyTorch)       | https://huggingface.co/urchade/gliner_large-v2.1        | Apache 2.0                       |

**Скачать:**

```python
from gliner import GLiNER
model = GLiNER.from_pretrained("onnx-community/gliner_small-v2.1", 
                                load_onnx_model=True, load_tokenizer=True)
```

**Конвертация в ONNX (если нужно):**

```bash
python convert_to_onnx.py --model_path urchade/gliner_small-v2.1 \
                           --save_path ./gliner-small-onnx \
                           --quantize True
```

---

### TinyBERT-L2-v2 (реранкер)

| Параметр | Значение                               |
| -------- | -------------------------------------- |
| Роль     | Cross-encoder reranking top-20 → top-5 |
| RAM      | ~8MB                                   |
| Лицензия | Apache 2.0                             |

| Вариант                       | URL                                                          | Примечание                               |
| ----------------------------- | ------------------------------------------------------------ | ---------------------------------------- |
| **Оригинал (содержит ONNX)**  | https://huggingface.co/cross-encoder/ms-marco-TinyBERT-L2-v2 | Subfolder `onnx/`, включая INT8          |
| ONNX (Xenova/Transformers.js) | https://huggingface.co/Xenova/ms-marco-TinyBERT-L-2-v2       | ONNX weights для JS, работает и в Python |

**Скачать:**

```python
from huggingface_hub import hf_hub_download
# INT8 quantized
hf_hub_download("cross-encoder/ms-marco-TinyBERT-L2-v2",
                subfolder="onnx", filename="model_qint8_avx512_vnni.onnx")
# или FP32
hf_hub_download("cross-encoder/ms-marco-TinyBERT-L2-v2",
                subfolder="onnx", filename="model.onnx")
```

---

## 2. Python библиотеки (pip)

### Обязательные (core)

```
onnxruntime>=1.17        # ONNX inference runtime
tokenizers>=0.15         # Rust tokenizers (HuggingFace)
numpy>=1.24              # Массивы, матричные операции
hnswlib>=0.8             # HNSWlib ANN search
lz4>=4.0                 # LZ4 compression для content branch
```

### Рекомендуемые (для полного стека)

```
gliner>=0.2              # GLiNER Python wrapper (загрузка + ONNX inference)
huggingface-hub>=0.20    # Скачивание моделей с HuggingFace
optimum>=1.16            # ONNX Runtime integration с HuggingFace
psutil>=5.9              # Мониторинг RAM (adaptive session window)
```

### Полный requirements.txt с хешами (security)

```
# Генерировать при финальной сборке:
pip install pip-tools
pip-compile --generate-hashes requirements.in > requirements.txt
pip install --require-hashes -r requirements.txt
```

---

## 3. Системные зависимости

| Компонент    | Что            | Нужен для           | Установка                                                              |
| ------------ | -------------- | ------------------- | ---------------------------------------------------------------------- |
| Python 3.10+ | Runtime        | Всё                 | python.org или pyenv                                                   |
| SQLite 3.35+ | БД (WAL mode)  | Storage             | Встроен в Python stdlib                                                |
| C compiler   | Сборка hnswlib | HNSWlib pip install | `build-essential` (Linux), Xcode CLI (macOS), VS Build Tools (Windows) |

### SQLite — уже встроен

SQLite поставляется с Python. Отдельная установка НЕ нужна. Проверить версию:

```python
import sqlite3
print(sqlite3.sqlite_version)  # нужно >= 3.35 для WAL mode
```

Python 3.10+ всегда включает SQLite >= 3.35.

---

## 4. Что НЕ нужно скачивать

| Компонент                  | Почему не нужен                            |
| -------------------------- | ------------------------------------------ |
| PyTorch / torch            | ONNX Runtime заменяет                      |
| transformers (HuggingFace) | Только tokenizers, не full transformers    |
| LangChain                  | Не используется                            |
| Docker                     | Не обязателен (опционально для deployment) |
| Redis / PostgreSQL         | SQLite встроен                             |
| CUDA / GPU drivers         | CPU-only inference                         |

---

## 5. Сводная таблица скачиваемых компонентов

### Модели

| Модель                 | Рекомендуемый URL                         | Размер     | Лицензия   |
| ---------------------- | ----------------------------------------- | ---------- | ---------- |
| EmbeddingGemma-300M Q8 | `onnx-community/embeddinggemma-300m-ONNX` | ~52MB      | Gemma      |
| BGE-M3 INT8            | `gpahal/bge-m3-onnx-int8`                 | ~145MB     | MIT        |
| GLiNER-small-v2.1 ONNX | `onnx-community/gliner_small-v2.1`        | ~42MB      | Apache 2.0 |
| TinyBERT-L2-v2 ONNX    | `cross-encoder/ms-marco-TinyBERT-L2-v2`   | ~8MB       | Apache 2.0 |
| **Итого модели**       |                                           | **~247MB** |            |

**Примечание:** 247MB < 342MB из спек. Разница = tokenizer files + runtime overhead. 342MB = total RAM при загрузке (модель + буферы ONNX Runtime).

### Библиотеки

| Пакет           | Размер (pip) |
| --------------- | ------------ |
| onnxruntime     | ~30MB        |
| tokenizers      | ~6MB         |
| numpy           | ~20MB        |
| hnswlib         | ~2MB         |
| lz4             | ~1MB         |
| gliner          | ~5MB         |
| huggingface-hub | ~3MB         |
| optimum         | ~10MB        |
| psutil          | ~1MB         |
| **Итого pip**   | **~78MB**    |

### Общий размер установки

| Компонент                               | Размер на диске |
| --------------------------------------- | --------------- |
| Модели ONNX                             | ~247MB          |
| Python пакеты                           | ~78MB           |
| Python runtime (если embedded в binary) | ~30-50MB        |
| SQLite DB (пустая)                      | ~0MB            |
| Config + manifest                       | <1MB            |
| **Итого при установке**                 | **~360-380MB**  |
| **+ runtime RAM при работе**            | **~600MB**      |

---

## 6. Скрипт автоскачивания моделей

```python
#!/usr/bin/env python3
"""mnemostroma model downloader — скачивает все ONNX модели при первом запуске"""

import os
import hashlib
import json
from pathlib import Path

MODELS_DIR = Path.home() / ".mnemostroma" / "models"
MANIFEST_URL = "manifest.json"

MODELS = {
    "embeddinggemma-300m": {
        "repo": "onnx-community/embeddinggemma-300m-ONNX",
        "files": ["onnx/model_quantized.onnx", "onnx/model_quantized.onnx_data"],
        "description": "Session embedder (512d MRL)",
    },
    "bge-m3-int8": {
        "repo": "gpahal/bge-m3-onnx-int8",
        "files": ["model.onnx"],  # или clone full repo
        "description": "Content embedder (dense + ColBERT)",
    },
    "gliner-small-v2.1": {
        "repo": "onnx-community/gliner_small-v2.1",
        "files": ["onnx/model.onnx"],
        "description": "Zero-shot NER",
    },
    "tinybert-l2-v2": {
        "repo": "cross-encoder/ms-marco-TinyBERT-L2-v2",
        "files": ["onnx/model.onnx"],
        "description": "Cross-encoder reranker",
    },
}

def download_model(name: str, config: dict):
    from huggingface_hub import hf_hub_download
    target_dir = MODELS_DIR / name
    target_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {name}: {config['description']}...")
    for file in config["files"]:
        subfolder = str(Path(file).parent) if "/" in file else None
        filename = Path(file).name
        hf_hub_download(
            repo_id=config["repo"],
            subfolder=subfolder,
            filename=filename,
            local_dir=str(target_dir),
        )
    print(f"  ✅ {name} downloaded")

def download_all():
    print(f"Mnemostroma: downloading models to {MODELS_DIR}")
    print(f"Total: ~247MB\n")
    for name, config in MODELS.items():
        if (MODELS_DIR / name).exists():
            print(f"  ⏭ {name} already exists, skipping")
            continue
        download_model(name, config)
    print(f"\n✅ All models ready")

if __name__ == "__main__":
    download_all()
```

---

## 7. Enterprise — расширенные модели

| Модель                | Free | Enterprise | URL                                                                  |
| --------------------- | ---- | ---------- | -------------------------------------------------------------------- |
| EmbeddingGemma FP16   | —    | ~120MB     | Конвертировать из `google/embeddinggemma-300m`                       |
| BGE-M3 FP16           | —    | ~300MB     | `hotchpotch/vespa-onnx-BAAI-bge-m3-only-dense` (FP16 вариант)        |
| GLiNER medium         | —    | ~95MB      | `onnx-community/gliner_multi-v2.1`                                   |
| GLiNER large          | —    | ~200MB     | `onnx-community/gliner_large-v2.1`                                   |
| DeBERTa cross-encoder | —    | ~100MB     | Конвертировать из `cross-encoder/ms-marco-MiniLM-L6-v2` или `L12-v2` |

---

*Mnemostroma | Stack Download Manifest | v1.0 | 2026-03-25*
*4 модели ~247MB | 9 pip пакетов ~78MB | 0 системных зависимостей кроме Python 3.10+*
