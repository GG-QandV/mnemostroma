# Инструкция по оформлению релиза на GitHub — v1.11.0

Этот документ описывает пошаговый процесс публикации новой версии Mnemostroma на GitHub.

## Этап 1: Предварительная проверка (Repo A)

1. Убедитесь, что все тесты пройдены: `pytest tests/`.
2. Проверьте, что версия в `src/mnemostroma/version.py` и `pyproject.toml` установлена как `1.11.0`.
3. Убедитесь, что файлы `README.md` и `UPGRADE.md` в корне синхронизированы с версией `1.11.0`.

## Этап 2: Синхронизация с публичным репозиторием (Repo C)

1. Скопируйте обновленный исходный код в Repo C.
2. Запустите скрипт очистки логов: `python3 scripts/strip_logs_v2.py /path/to/repo_c/src`.
3. Проведите аудит: `grep -rn "log_event" src/` должен вернуть **0 результатов**.
4. Закоммитьте и запушьте изменения в Repo C: `git commit -m "chore: release v1.11.0 stable"`.

## Этап 3: Создание релиза на GitHub

1. Перейдите на страницу **https://github.com/GG-QandV/mnemostroma/releases**.
2. Нажмите **"Draft a new release"**.
3. Создайте новый тег: **`v1.11.0`**.
4. Установите заголовок релиза (Release Title): **`v1.11.0 — Content Branch & Temporal Precision`**.
5. Скопируйте содержимое файла `release/RELEASE_NOTES_v1.11.0.md` в поле описания.
6. **Загрузите ассеты (Assets)** из папки `release/`:
   - `QUICKSTART_v1.11.0.md`
   - `SYSTEM_ASSESSMENT_v1.11.0.md`
7. Убедитесь, что галочка "Set as latest release" включена.
8. Нажмите **"Publish release"**.

## Этап 4: Финальная проверка

1. Откройте публичный репозиторий на GitHub и проверьте отображение текста релиза.
2. Скачайте ассеты и убедитесь, что они открываются корректно.
3. Проверьте команду установки: `pip install "git+https://github.com/GG-QandV/mnemostroma.git"`.
