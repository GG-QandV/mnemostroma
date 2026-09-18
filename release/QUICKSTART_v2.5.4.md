# Quick Start — Mnemostroma v2.5.4

## Model Correctness & Memory Accounting Release

v2.5.4 делает разметку NER неподделываемо-корректной, перестаёт считать веса моделей
вытесняемой памятью и добавляет детерминированный гейт модельного NER.

### What's new in v2.5.4

- **NER**: `id2label` берётся из `config.json` модели + сверка числа меток с размерностью
  логитов — сдвиг разметки (PER↔DATE) больше невозможен.
- **NER gate**: `needs_model_ner()` — модель запускается по детерминированным сигналам, а не
  на 100% наблюдений (цель `ner_call_rate_target` = 0.3). Регексы работают всегда.
- **Embedders**: режимы pooling `mean|cls`, инвалидация индекса по `model_key`,
  per-model настройки ORT-сессии (`graph_optimization_level`, `disable_prepacking`).
- **Memory**: динамический baseline весов моделей (`models/footprint.py`) — сессии больше не
  вытесняются под вес моделей.
- **CLI**: `mnemostroma --help` / `-h` работают (были exit 2).

### Install / Upgrade

```bash
pip install -U "mnemostroma @ git+https://github.com/GG-QandV/mnemostroma.git@v2.5.4"
# или из локального клона:
# pip install -e ".[dev]"
```

Перезапустить демон, чтобы подхватить новую версию:

```bash
systemctl --user restart mnemostroma-daemon
```

Конфиг менять не нужно — новые поля опциональны.

### Verify

```bash
# 1. Версия
mnemostroma --version        # 2.5.4
python3 ~/.mnemostroma/venv/bin/pip show mnemostroma | grep Version

# 2. Демон жив и отвечает
curl -s http://127.0.0.1:8762/health

# 3. RAM / индекс
python3 -c "import json; d=json.load(open('$HOME/.mnemostroma/pulse.json')); print(d['ram_mb'],'MB /',d['sessions'],'sessions')"
```
