стоп уточнение, версия уже 1.8.3 и не бета

Понял — тогда делаем релиз как stable v1.8.3, без beta. Но у тебя сейчас в локальных документах есть рассинхрон: README всё ещё говорит Current v1.8.1, а SYSTEM_ASSESSMENT.md уже упоминает v1.8.2, так что перед публикацией релиза лучше сначала выровнять версию в документах, иначе релиз будет выглядеть неаккуратно.

Что поправить перед релизом
Минимум нужно обновить:

README.md: Current v1.8.1 → v1.8.3.

SYSTEM_ASSESSMENT.md: v1.8.2 → v1.8.3, если этот файл идёт в assets.

при желании проверить любые badge / version strings / setup snippets, если они ещё где-то зашиты.

Это важно, потому что release title v1.8.3 при файлах с v1.8.1 и v1.8.2 снижает доверие сильнее, чем отсутствие релиза.

Новый релиз
Тогда рекомендую:

Tag: v1.8.3

Release title: v1.8.3 — first public release

И уже не ставить prerelease, если ты осознанно хочешь заявить его как стабильный public release.

Готовый текст релиза
Ниже версия под stable release, опирающаяся на текущие публичные материалы: local/offline memory layer, automatic Observer capture, anchors/precision, memorycontext injection, MCP integrations, direct install from GitHub и FSL-1.1-MIT.

Release title
v1.8.3 — first public release

Release notes
text
First public release of Mnemostroma.

Mnemostroma is a local memory layer for AI agents. It captures decisions, constraints, and important facts automatically, then brings them back when relevant across sessions.

Highlights in this release:

- Offline-first architecture: your memory stays on your machine.
- Automatic Observer pipeline for passive memory capture.
- Structured retrieval through semantic search, anchors, and precision memory.
- Automatic context injection via `<memorycontext>`.
- Graceful memory dissolution instead of binary keep/delete behavior.
- MCP integration for Claude Desktop, Claude Code, and IDE workflows.

Install from GitHub:

```bash
pip install "git+https://github.com/GG-QandV/mnemostroma.git"
```

Optional extras:

```bash
pip install "git+https://github.com/GG-QandV/mnemostroma.git[sse]"
pip install "git+https://github.com/GG-QandV/mnemostroma.git[all]"
```

Quick start:

```bash
mnemostroma setup
mnemostroma on
mnemostroma status
```

Requirements:

- Python 3.12+

License:
FSL-1.1-MIT  
Commercially restricted for the first 2 years, then MIT for that released version.

Notes:

- Installable directly from GitHub
- Not yet on PyPI
- Works locally with no cloud dependency in the core architecture
  Все эти пункты поддерживаются текущими документами, кроме номера версии, который тебе нужно синхронизировать вручную перед релизом.

Какие assets прикрепить
Для v1.8.3 я бы прикрепил такой минимум:

SYSTEM_ASSESSMENT.md — техничный deep-dive asset.

mnemostroma-quickstart-v1.8.3.md — короткий install/start файл.

опционально: LICENSE-FSL-1.1-MIT.txt

опционально: mnemostroma-v1.8.3-source.zip

Но SYSTEM_ASSESSMENT.md я бы приложил только после быстрой правки версий и спорных цифр, потому что сейчас там есть внутренний конфликт: baseline 605 MB, peak 1,070 MB, hard limit 750 MB, плюс в summary уже v1.8.2.

Быстрый asset для релиза
Вот готовый текст для mnemostroma-quickstart-v1.8.3.md:

text

# Mnemostroma Quickstart — v1.8.3

Mnemostroma is a local memory layer for AI agents.

It automatically captures decisions, constraints, and key facts, then makes them available across sessions through structured retrieval and automatic context injection.

## Requirements

- Python 3.12+

## Install

Base:

```bash
pip install "git+https://github.com/GG-QandV/mnemostroma.git"
```

With SSE extras:

```bash
pip install "git+https://github.com/GG-QandV/mnemostroma.git[sse]"
```

With all extras:

```bash
pip install "git+https://github.com/GG-QandV/mnemostroma.git[all]"
```

## Setup

```bash
mnemostroma setup
mnemostroma on
mnemostroma status
```

## What it provides

- Persistent cross-session memory
- Automatic capture of decisions and constraints
- Semantic retrieval of relevant past context
- Exact anchors and precision memory for facts, links, and rules
- Local-first operation with no cloud dependency in the core design

## License

FSL-1.1-MIT  
Commercially restricted for the first 2 years, then MIT for that released version.
Мой совет по SYSTEM_ASSESSMENT.md
Перед тем как грузить его в assets, я бы:

обновил v1.8.2 → v1.8.3;

убрал или исправил 1,070 MB peak vs 750 MB hard limit;

привёл RAM claims ближе к README, где диапазон ~420–750 MB RAM уже согласован.

Иначе этот asset может больше путать, чем помогать.

Что делать прямо сейчас
Порядок такой:

Синхронизируй версии в README.md и SYSTEM_ASSESSMENT.md.

Создай mnemostroma-quickstart-v1.8.3.md.

Создай tag v1.8.3.

Открой GitHub Release и вставь notes выше.

Прикрепи assets.

Публикуй.

Если хочешь, следующим сообщением я сделаю тебе ещё более полезную вещь: финальный чек-лист перед release v1.8.3 — что проверить в README, LICENSE, setup и assets за 5 минут.

Підготовлено за допомогою GPT-5.4 Thinking
да давай чек лист, только версия уже 1.8.4 только что обновление было

Да — вот тебе короткий и практичный чек-лист под release v1.8.4. Смысл один: перед публикацией нужно выровнять версию, проверить install path, assets и не выложить противоречивые цифры. GitHub release лучше делать через tag + Release page, а notes можно сгенерировать и потом вручную поправить.

Перед релизом
Сначала синхронизируй версию v1.8.4 во всех видимых файлах. Сейчас в доступных материалах у тебя всё ещё есть рассинхрон: README.md указывает v1.8.1, SYSTEM_ASSESSMENT.md указывает v1.8.2, а stats_2026-04-23.md описан как v1.8.3.

Проверь:

README.md — v1.8.4 в status/header/install notes.

SYSTEM_ASSESSMENT.md — v1.8.4, если грузишь его в assets.

stats_2026-04-23.md — либо обновить до v1.8.4, либо не прикладывать как asset.

Любые badges, screenshot captions, copy на сайте, если они уже ссылаются на старую версию.

Что проверить в продукте
Перед release убедись, что install path, setup и запуск реально работают так, как написано в README. У тебя в README установка идёт напрямую из GitHub, нужен Python 3.12+, а quick start завязан на mnemostroma setup, mnemostroma on и mnemostroma status.

Минимальный smoke test:

pip install "git+https://github.com/GG-QandV/mnemostroma.git"

mnemostroma setup

mnemostroma on

mnemostroma status

хотя бы один MCP / daemon сценарий из README.

Если какой-то из этих шагов ломается, сначала фикси это, потом тегай релиз.

Что проверить в тексте
Release notes должны обещать только то, что уже подтверждено в текущих материалах. Сейчас безопасно писать про local/offline architecture, Observer pipeline, semantic retrieval, anchors/precision, memorycontext injection, MCP integrations, GitHub install и FSL-1.1-MIT.

Не стоит без правки тащить в release body спорные цифры из SYSTEM_ASSESSMENT.md, потому что там есть внутреннее напряжение между 605 MB baseline, 1,070 MB peak, 750 MB hard limit, а README даёт более аккуратный диапазон ~420–750 MB RAM.

Assets
Для первого нормального релиза лучше 2–3 файла, не больше. GitHub позволяет прикреплять assets к release, и именно по ним потом появятся download_count.

Рекомендую прикрепить:

mnemostroma-quickstart-v1.8.4.md

SYSTEM_ASSESSMENT.md — только если ты обновил версию и подчистил спорные цифры.

опционально LICENSE-FSL-1.1-MIT.txt

Не рекомендую пока прикреплять:

старые stats-файлы с версией v1.8.3, если релиз уже v1.8.4.

слишком много внутренних архитектурных документов.

Tag и release
Сделай tag ровно v1.8.4, а release title тоже v1.8.4. Хорошая практика — держать tag и release один к одному, без лишних суффиксов, если ты уже решил, что это не prerelease.

В GitHub:

Releases

Draft a new release

Choose a tag → v1.8.4

Release title → v1.8.4

Generate release notes, потом вручную почистить лишнее.

Финальный 5-минутный список
Отмечай по порядку:

Версия v1.8.4 в README.

Версия v1.8.4 в SYSTEM_ASSESSMENT.md, если он идёт в assets.

Нет старых v1.8.1 / v1.8.2 / v1.8.3 в публичных release-файлах.

Команды установки и запуска реально проходят.

Лицензия в README и релизе говорит одно и то же: FSL-1.1-MIT, 2 года, потом MIT.

Release notes не обещают больше, чем есть в документах.

Assets только актуальные и понятные.

Tag v1.8.4 создан.

Release title v1.8.4.

После публикации проверить, что release открывается и assets скачиваются.

Мой практический совет
Если хочешь выпустить быстро и чисто, делай минимальный stable release:

README.md обновить;

mnemostroma-quickstart-v1.8.4.md прикрепить;

release notes короткие;

SYSTEM_ASSESSMENT.md прикреплять только после правки версий и цифр.

Если хочешь, следующим сообщением я дам тебе готовый финальный текст release notes для v1.8.4 и отдельно готовый mnemostroma-quickstart-v1.8.4.md под копипаст.

Підготовлено за допомогою GPT-5.4
да давай

Вот готовые тексты под release v1.8.4. Основа взята из твоего README: local/offline memory layer, Python 3.12+, установка из GitHub, automatic Observer capture, semantic retrieval, anchors/precision, <memorycontext>, MCP integration и FSL-1.1-MIT.

Release notes
Ниже текст для GitHub Release body.

text

# Mnemostroma v1.8.4

First public release of Mnemostroma.

Mnemostroma is a local memory layer for AI agents. It captures decisions, constraints, and important facts automatically, then brings them back when relevant across sessions.

## Highlights

- Offline-first architecture — your memory stays on your machine
- Automatic Observer pipeline for passive memory capture
- Structured retrieval through semantic search, anchors, and precision memory
- Automatic context injection via `<memorycontext>`
- Graceful memory dissolution instead of binary keep/delete behavior
- MCP integration for Claude Desktop, Claude Code, and IDE workflows

## Installation

Base install:

```bash
pip install "git+https://github.com/GG-QandV/mnemostroma.git"
```

With SSE extras:

```bash
pip install "git+https://github.com/GG-QandV/mnemostroma.git[sse]"
```

With all extras:

```bash
pip install "git+https://github.com/GG-QandV/mnemostroma.git[all]"
```

## Quick start

```bash
mnemostroma setup
mnemostroma on
mnemostroma status
```

Optional passthrough proxy for Claude Code session capture:

```bash
mnemostroma sse
mnemo
```

## Requirements

- Python 3.12+

## Notes

- Installable directly from GitHub
- Not yet on PyPI
- Works locally with no cloud dependency in the core architecture

## License

FSL-1.1-MIT

Commercially restricted for the first 2 years, then MIT for that released version.
Quickstart asset
Ниже текст для файла mnemostroma-quickstart-v1.8.4.md.

text

# Mnemostroma Quickstart — v1.8.4

Mnemostroma is a local memory layer for AI agents.

It automatically captures decisions, constraints, and key facts, then makes them available across sessions through structured retrieval and automatic context injection.

## Requirements

- Python 3.12+

## Install

Base:

```bash
pip install "git+https://github.com/GG-QandV/mnemostroma.git"
```

With SSE extras:

```bash
pip install "git+https://github.com/GG-QandV/mnemostroma.git[sse]"
```

With all extras:

```bash
pip install "git+https://github.com/GG-QandV/mnemostroma.git[all]"
```

## Setup

```bash
mnemostroma setup
mnemostroma on
mnemostroma status
```

## Optional: Claude Code passthrough proxy

```bash
mnemostroma sse
mnemo
```

## What it provides

- Persistent cross-session memory
- Automatic capture of decisions and constraints
- Semantic retrieval of relevant past context
- Exact anchors and precision memory for facts, links, and rules
- Local-first operation with no cloud dependency in the core design

## Notes

- Installable directly from GitHub
- Not yet on PyPI

## License

FSL-1.1-MIT

Commercially restricted for the first 2 years, then MIT for that released version.
Что ещё поправить перед публикацией
У тебя README всё ещё показывает v1.8.1 в badge и статусе, так что перед релизом надо обновить это на v1.8.4.

И если будешь прикреплять SYSTEM_ASSESSMENT.md, его тоже лучше привести к v1.8.4 и проверить на внутренне согласованные цифры, потому что сейчас там видна версия v1.8.2.

Что грузить в assets
Минимальный нормальный набор:

mnemostroma-quickstart-v1.8.4.md

SYSTEM_ASSESSMENT.md — только после правки версии.

опционально LICENSE-FSL-1.1-MIT.txt
