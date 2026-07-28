# Аудит конфігурації Mnemostroma Daemon

## 1. Знайдені файли `config.json` зі значеннями RAM‑лімітів

| Шлях до файлу                                       | `ram_soft_limit_mb` | `ram_hard_limit_mb` | Дата модифікації    |
| --------------------------------------------------- | ------------------- | ------------------- | ------------------- |
| `/home/gg/projects/Project_mnemostroma/config.json` | 520                 | 600                 | 2026-07-11 00:39:07 |
| `/home/gg/.mnemostroma/config.json`                 | 700                 | 750                 | 2026-07-19 00:23:58 |

*Усі інші знайдені `config.json` (в директоріях моделей) не містять полів `ram_*_limit_mb` і не використовуються демоном для налаштування ресурсів.*

## 2. Файл, який реально використовує запущений процес демона

- **PID демона**: 3885677 (за даними `systemctl --user status mnemostroma-daemon`)
- **Поточна робоча директорія (cwd)**: `/home/gg/.mnemostroma`
- **Відкриті дескриптори файлів**: немає відкритих `config.json` у `/proc/<PID>/fd` (демон читає файл при старті та тримає його в пам’яті).
- **Висновок**: демон читає конфігураційний файл  
  **`/home/gg/.mnemostroma/config.json`**  
  (це шлях, жорстко закодований у CLI: `$HOME/.mnemostroma/config.json`).

## 3. Як у коді визначається шлях до конфігу

У файле **`/home/gg/projects/Project_mnemostroma/src/mnemostroma/cli/commands.py`** визначено:

```python
_MNEMO_DIR = Path.home() / ".mnemostroma"
_CONFIG_PATH = _MNEMO_DIR / "config.json"
```

Функція `_run_daemon` викликає `bootstrap(config_path, db_path, model_dir)`, де `config_path` за замовчуванням дорівнює `"config.json"` (відносно поточної робочої директорії).  
При старті демона через `mnemostroma on` або `systemd` процесу задається `cwd = $HOME/.mnemostroma`, тому відносна шлях `"config.json"` розв’язується точно до `/home/gg/.mnemostroma/config.json`.

Тобто, resolving chain:

1. `Path.home() → /home/gg`
2. `._mnemostroma/ → /home/gg/.mnemostroma`
3. `config.json → /home/gg/.mnemostroma/config.json`

## 4. Орфанні / легарі конфігураційні файли

- `/home/gg/projects/Project_mnemostroma/config.json` – це **шаблон/заготовка** з репозиторію, використовується лише під час первинної інсталяції (`mnemostroma setup` копіює його у `$HOME/.mnemostroma/config.json`). Поточний демон **не читає** цей файл.
- Усі `config.json` всередині директорій моделей (наприклад, `.../models/multilingual-e5-small/config.json`) – це конфігурації саме моделей (ONNX, токенізатори тощо) і не стосуються ресурсних лімітів демона.

**Висновок**: для внесення змін у ліміти пам’яті демона треба правити **один єдиний файл** – `/home/gg/.mnemostroma/config.json` та після цього перезапустити демон:

```bash
systemctl --user restart mnemostroma-daemon
```

---

*Zвіт підготовлено автоматично агентом Hermes на основі аудиту файлових систем та процесу.*