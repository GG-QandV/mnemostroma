# Cloud Sync — Спецификация
## Mnemostroma | Phase 2 | 2026-03-25

---

## 1. Суть

Синхронизация **холодных** слоёв памяти между устройствами одного юзера.
Горячая память (RAM Hot/Warm) никогда не покидает машину.

```
Ноутбук                          Десктоп
┌──────────────────┐              ┌──────────────────┐
│ RAM Hot/Warm     │              │ RAM Hot/Warm     │
│ (НИКОГДА не sync)│              │ (НИКОГДА не sync)│
├──────────────────┤              ├──────────────────┤
│ SQLite Archive   │◄────────────►│ SQLite Archive   │
│ SQLite Eternal   │  encrypted   │ SQLite Eternal   │
└──────────────────┘              └──────────────────┘
         │                                 │
         └──────────┐      ┌───────────────┘
                    ▼      ▼
              ┌──────────────────┐
              │   Sync Server    │
              │ (видит только    │
              │  ciphertext)     │
              └──────────────────┘
```

---

## 2. Что синхронизируется

| Данные | Sync? | Почему |
|--------|-------|--------|
| RAM Hot сессии | ❌ | Рабочие данные, локальные по определению |
| RAM Warm сессии | ❌ | То же |
| SQLite Archive (resolution 0.1-0.3) | ✅ | Долгосрочная память |
| SQLite Eternal (resolution ≤0.05) | ✅ | Вечная память |
| HNSWlib embeddings | ✅ | Нужны для semantic search на другом устройстве |
| Anchors (stale/expired) | ✅ | Историческая ценность |
| Precision Log (archived) | ✅ | Ссылки, формулы, данные |
| Content versions (archived) | ✅ | Код, документы |
| Experience Layer записи | ✅ | Накопленный опыт юзера |
| config.json | ✅ | Единая конфигурация на всех устройствах |
| Subconscious models (v3.0) | ✅ | Персонализированные модели |

**Правило:** sync = только данные с resolution < 0.5 (уже в SQLite, не в RAM).

---

## 3. E2E Encryption

### Модель угрозы

Sync-сервер — **untrusted**. Он хранит и передаёт ciphertext, но никогда не видит plaintext. Даже при полной компрометации сервера — данные юзера защищены.

### Схема

```
Device:
  master_key = PBKDF2(user_password, device_salt, 100000 iterations)
  data_key = random 256-bit AES key (генерируется один раз)
  encrypted_data_key = AES-256-GCM(master_key, data_key)

  Для каждого blob:
    ciphertext = AES-256-GCM(data_key, plaintext)
    → upload ciphertext + encrypted_data_key

Server:
  хранит: ciphertext + encrypted_data_key
  не имеет: master_key, data_key, plaintext
```

### Key rotation

```
При смене пароля:
  new_master_key = PBKDF2(new_password, new_salt, 100000)
  re-encrypt data_key: AES-256-GCM(new_master_key, data_key)
  upload новый encrypted_data_key
  Данные НЕ перешифровываются (data_key не меняется)
```

### Многоустройственный доступ

```
Device A генерирует data_key
  → шифрует master_key_A → encrypted_data_key_A

Device B подключается:
  → юзер вводит пароль → master_key_B = PBKDF2(password, ...)
  → Device A передаёт data_key зашифрованный master_key_B
  → оба устройства имеют data_key
```

---

## 4. Conflict Resolution

### Проблема

Два устройства одновременно изменили одну сессию (редко, но возможно).

### Стратегия: Last-Write-Wins + Merge для аддитивных данных

| Тип данных | Стратегия | Обоснование |
|-----------|-----------|-------------|
| sessions (brief, tags, importance) | Last-Write-Wins по updated_at | Мутация одной записи |
| anchors | Merge (union) | Аддитивные — добавление не конфликтует |
| precision_log | Merge (union, dedup by hash) | Аддитивные |
| content_versions | Append-only (новая версия = новая запись) | Версионирование по определению |
| experience | Merge (union) | Аддитивные |
| HNSWlib vectors | Rebuild на принимающей стороне | Индекс перестраивается из данных |

### Вектор версионирования

```python
@dataclass
class SyncEntry:
    entity_id:    str
    entity_type:  str        # "session" | "anchor" | "precision" | "content" | "experience"
    updated_at:   int        # unix timestamp
    device_id:    str        # UUID устройства
    data:         bytes      # encrypted blob
    tombstone:    bool       # True = удалено
```

### Алгоритм sync

```
1. Device → Server: "дай всё с updated_at > last_sync_ts"
2. Server → Device: list[SyncEntry]
3. Device применяет:
   - Для каждого entry:
     - если entity_id не существует локально → INSERT
     - если существует и remote.updated_at > local.updated_at → UPDATE (LWW)
     - если существует и remote.updated_at ≤ local.updated_at → skip
     - anchors/precision/experience: MERGE (union)
4. Device → Server: свои изменения с updated_at > last_sync_ts
5. Обновить last_sync_ts
```

---

## 5. Sync Protocol

### Транспорт

HTTPS + JSON. Без WebSocket, без gRPC. Простота > производительность для sync каждые 5 минут.

### Endpoints

```
POST /sync/push     — отправить изменения
POST /sync/pull     — получить изменения
POST /sync/register — зарегистрировать устройство
POST /sync/keys     — обменяться encrypted_data_key
GET  /sync/status   — статус синхронизации
```

### Конфигурация

```json
{
  "cloud_sync": {
    "enabled": true,
    "endpoint": "https://sync.mnemostroma.dev",
    "interval_sec": 300,
    "layers": ["SQLite_Archive", "SQLite_Eternal"],
    "encrypted": true,
    "device_id": "uuid-auto-generated"
  }
}
```

---

## 6. Bandwidth

| Данных | Размер (зашифрованный) | Частота |
|--------|----------------------|---------|
| Новая сессия (archive) | ~2KB | По мере растворения |
| Embedding | ~1KB | При каждой новой сессии |
| Content version | ~5-50KB | При content.save() |
| Experience entry | ~1.5KB | При маркировке |
| **Типичный sync (5 мин)** | **~5-20KB** | Каждые 300s |

При 10 сессиях/день, sync каждые 5 минут: **~50-100KB/день upload**. Пренебрежимо.

---

## 7. Offline-first

Sync — опциональный. Система работает полностью автономно без подключения.

```
Онлайн:   sync каждые 300s → server → другие устройства
Офлайн:   всё работает локально, изменения копятся
Возврат:   при подключении → bulk sync → разрешение конфликтов → ready
```

Нет деградации функционала в офлайне. Sync = удобство, не требование.

---

## 8. Открытые вопросы

| Вопрос | Статус |
|--------|--------|
| Hosted sync server или self-hosted? | Оба варианта (hosted для Pro, self-hosted для Enterprise) |
| Лимит storage на сервере | Pro: 1GB, Team: 10GB, Enterprise: unlimited |
| Selective sync (только определённые проекты) | Желательно, спека не готова |
| Mobile thin client (только чтение + sync) | Phase 3, отдельная спека |

---

*Mnemostroma | Cloud Sync Specification | Phase 2 | 2026-03-25*
