# Python 3.13+ Setup Fix

## Проблема

При установке мнемостромы через `pipx` на Python 3.13.11 возможны `IndentError` из-за пустых блоков `if:` без `pass`.

Python 3.13 более строгий в валидации синтаксиса и запрещает пустые блоки.

## Решение (уже вделано в код)

1. **Обновить мнемо** до последней версии:
   ```bash
   pipx upgrade mnemostroma
   ```

2. **Если ошибка всё ещё происходит:**
   ```bash
   mnemostroma off
   rm -f ~/.mnemostroma/daemon.pid
   mnemostroma on
   ```

3. **Проверить статус:**
   ```bash
   mnemostroma status
   journalctl --user -u mnemostroma-daemon -n 30
   # или
   cat ~/.mnemostroma/daemon.log | tail -30
   ```

## Для разработчиков

Добавлен тест совместимости:
```bash
python tests/test_python313_compat.py
```

Гарантирует что все `.py` файлы компилируются без `IndentError` на Python 3.13+.

## Спасибо тестеру

Благодарность тестеру за отчёт об этой проблеме. Вы не идиот — Python 3.13 просто строже.
