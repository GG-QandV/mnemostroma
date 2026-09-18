# Quick Start — Mnemostroma v2.6.4

## NER Replacement & Multichunk Release

v2.6.4 меняет NER-модель (`distilbert-ner` → `gliner_small-v2.5` INT8) и вводит
мультивекторный чанкинг: длинные тексты больше не обрезаются на 512 токенах —
каждый чанк получает свой вектор в индексе.

### What's new in v2.6.4

- **NER**: `gliner_small-v2.5` — на ru/uk находит в 2–2.7× больше сущностей; 6 типов
  (`person`, `organization`, `location`, `date`, `technology`, `product`); выбор
  движка из манифеста (`engine: "gliner"`, откат — одна строка).
- **Chunking**: длинные тексты режутся по чанкам ~384 токена (overlap 48), каждый
  чанк индексируется; лимит 32 чанка на сессию (`ctx.metrics["chunk_cap_hits"]`).
- **Известный дефект**: `organization` частично размечается как `location`.

### Install / Upgrade

```bash
pip install -U "mnemostroma @ git+https://github.com/GG-QandV/mnemostroma.git@v2.6.4"
mnemostroma install-models   # докачает бандл gliner_small-v2.5 (~196 MB, всего ~336 MB)
# или из локального клона:
# pip install -e ".[dev]"
```

Перезапустить демон, чтобы подхватить новую версию:

```bash
systemctl --user restart mnemostroma-daemon
```

Конфиг менять не нужно.

### Verify

```bash
# 1. Версия
mnemostroma --version        # 2.6.4
python3 ~/.mnemostroma/venv/bin/pip show mnemostroma | grep Version

# 2. Демон жив и отвечает
curl -s http://127.0.0.1:8762/health

# 3. Активный NER-движок — gliner
python3 -c "import json;print(json.load(open('$HOME/.mnemostroma/models_manifest.json'))['active_models']['ner']['engine'])"

# 4. RAM / индекс
python3 -c "import json; d=json.load(open('$HOME/.mnemostroma/pulse.json')); print(d['ram_mb'],'MB /',d['sessions'],'sessions')"
```
