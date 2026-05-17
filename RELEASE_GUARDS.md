# Release Guards and Stability Shards (Mnemostroma v2.x)

Этот документ описывает активные программные предохранители (Release Guards), используемые для обеспечения стабильности публичных выпусков Mnemostroma при интеграции браузерного расширения.

---

## 🔒 1. Сетевое MCP-туннелирование (DOM-independent capture)

### Описание функционала
Фронтенд-транспорт Phase 3/4 реализует перехват сетевых запросов чата (туннелирование MCP-подключения). Этот функционал является революционным, но требует длительного тестирования.

### Релизная стратегия
*   **Стабильный публичный выпуск (v2.0.5):** Сетевой транспорт должен быть полностью **отключен / заглушен**, чтобы гарантировать бесконфликтную работу пользователей через проверенный DOM-fallback.
*   **Ветка разработки (v2.1.5):** Сетевой транспорт полностью **активен** для полевых тестов и багфиксов.

---

## 🛠️ Картография предохранителя (Release Guard Location)

Для управления активностью туннелирования используется один глобальный логический флаг:

### Файл: `src/extension/src/shared/constants.js`
```javascript
// Controls the availability of DOM-independent MCP network tunneling (Phase 3/4).
// - Development/Beta (v2.1.5): Set to true (active for field tests & debug).
// - Stable Production (v2.0.5): Must be set to false (disabled for public safety).
export const IS_MCP_TUNNELING_ENABLED = true; 
```

### Логическое поведение (`src/extension/src/content/index.js`)
При `IS_MCP_TUNNELING_ENABLED = false`:
1.  Константа `DEFAULT_CAPTURE_MODE` автоматически переключается в `dom_only`.
2.  Метод `_readCaptureMode()` принудительно возвращает `dom_only`, полностью блокируя инициализацию перехватчиков сетевых запросов и хуков `fetch`/`XHR`.

---

## 📋 Инструкция по переключению режимов

### Для перевода проекта в статус стабильного релиза v2.0.5 (при публикации в Repo C):
1.  Откройте файл: `src/extension/src/shared/constants.js`
2.  Найдите строку с объявлением `IS_MCP_TUNNELING_ENABLED`.
3.  Измените значение на `false`:
    ```javascript
    export const IS_MCP_TUNNELING_ENABLED = false;
    ```
4.  Выполните публикацию в Repo C согласно `GIT_RULES_v4.2.md`.

### Для возврата в режим активного тестирования туннелирования v2.1.5 (в Repo A):
1.  Откройте файл: `src/extension/src/shared/constants.js`
2.  Измените значение на `true`:
    ```javascript
    export const IS_MCP_TUNNELING_ENABLED = true;
    ```
