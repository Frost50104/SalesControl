# SalesControl Audio System

Система непрерывной записи и обработки аудио для точек продаж.

## Компоненты

| Компонент | Описание | Документация |
|-----------|----------|--------------|
| **recorder-agent** | Сервис записи на Raspberry Pi | [README ниже](#recorder-agent) |
| **ingest-api** | API приёма аудио-чанков | [ingest_api/README.md](ingest_api/README.md) |
| **vad-worker** | VAD и построение диалогов | [vad_worker/](vad_worker/) |
| **asr-worker** | Распознавание речи (Whisper) | [asr_worker/README.md](asr_worker/README.md) |
| **analysis-worker** | LLM-анализ допродаж | [analysis_worker/](analysis_worker/) |
| **dashboard-web** | Web UI для аналитики | [dashboard_web/README.md](dashboard_web/README.md) |
| **infra** | Docker Compose для деплоя | [infra/](#инфраструктура) |

## Архитектура системы

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Raspberry Pi                                   │
│  ┌─────────────┐     ┌──────────────┐     ┌──────────────┐                 │
│  │ USB Mic     │────>│ recorder-    │────>│   outbox/    │                 │
│  │ (ALSA)      │     │ agent        │     │  .ogg files  │                 │
│  └─────────────┘     │ (ffmpeg)     │     └──────┬───────┘                 │
│                      └──────────────┘            │                          │
│                                                  │ HTTP POST                │
└──────────────────────────────────────────────────┼──────────────────────────┘
                                                   │
                                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Core Server                                       │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐                │
│  │ ingest-api   │────>│  PostgreSQL  │<────│  vad-worker  │                │
│  │ (FastAPI)    │     │  (metadata)  │     │  (webrtcvad) │                │
│  └──────┬───────┘     └──────┬───────┘     └──────────────┘                │
│         │                    │                                              │
│         ▼                    │                                              │
│  ┌──────────────┐            │  Tables: audio_chunks, dialogues,           │
│  │ File Storage │            │          speech_segments, dialogue_segments, │
│  │ (audio files)│            │          dialogue_transcripts               │
│  └──────────────┘            │                                              │
└──────────────────────────────┼──────────────────────────────────────────────┘
                               │
                               │ PostgreSQL + HTTP (internal endpoint)
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ASR Server (отдельный VPS)                        │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                        asr-worker                                     │  │
│  │  ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐   │  │
│  │  │ fetch ogg  │──>│ assemble   │──>│ transcribe │──>│   save     │   │  │
│  │  │ via HTTP   │   │ audio      │   │ (whisper)  │   │ transcript │   │  │
│  │  └────────────┘   └────────────┘   └────────────┘   └────────────┘   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Быстрый старт

### 1. Развернуть сервер (ingest-api)

```bash
cd infra
cp .env.example .env
# Отредактировать .env (особенно ADMIN_TOKEN!)

docker compose up -d
```

### 2. Зарегистрировать устройство

```bash
# Сгенерировать идентификаторы
POINT_ID=$(uuidgen)
REGISTER_ID=$(uuidgen)
DEVICE_ID=$(uuidgen)
DEVICE_TOKEN="$(openssl rand -hex 24)"

# Создать устройство через Admin API
curl -X POST http://your-server:8000/api/v1/admin/devices \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"point_id\": \"$POINT_ID\",
    \"register_id\": \"$REGISTER_ID\",
    \"device_id\": \"$DEVICE_ID\",
    \"token_plain\": \"$DEVICE_TOKEN\"
  }"

echo "Device Token: $DEVICE_TOKEN"
```

### 3. Настроить Raspberry Pi (recorder-agent)

```bash
# На Raspberry Pi
sudo apt install -y python3-venv ffmpeg alsa-utils

cd /opt
sudo mkdir -p recorder-agent && sudo chown $USER: recorder-agent
# Скопировать файлы проекта...

cd /opt/recorder-agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .

# Конфигурация
sudo mkdir -p /etc/recorder-agent
sudo nano /etc/recorder-agent/config.yaml
```

```yaml
# /etc/recorder-agent/config.yaml
identifiers:
  point_id: "<POINT_ID из шага 2>"
  register_id: "<REGISTER_ID из шага 2>"
  device_id: "<DEVICE_ID из шага 2>"

ingest:
  ingest_base_url: "http://your-server:8000"
  ingest_token: "<DEVICE_TOKEN из шага 2>"
```

```bash
# Запуск
sudo systemctl enable --now recorder-agent
```

---

## Инфраструктура

### Docker Compose (infra/)

```bash
cd infra
cp .env.example .env
docker compose up -d
```

Сервисы:
- **ingest-api** — FastAPI на порту 8000
- **postgres** — PostgreSQL 16
- **redis** — Redis 7 (для очереди обработки)
- **migrations** — one-shot контейнер для Alembic
- **vad-worker** — VAD и построение диалогов
- **asr-worker** — распознавание речи (может запускаться на отдельном VPS)
- **analysis-worker** — LLM-анализ допродаж (требует OPENAI_API_KEY)
- **dashboard-web** — Web UI на порту 8080

### Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `ADMIN_TOKEN` | `changeme-admin-token` | Токен для Admin API |
| `INTERNAL_TOKEN` | *(пусто)* | Токен для internal API (asr-worker) |
| `POSTGRES_USER` | `ingest` | Пользователь БД |
| `POSTGRES_PASSWORD` | `ingest` | Пароль БД |
| `AUDIO_STORAGE_PATH` | `./audio_storage` | Путь хранения аудио |
| `OPENAI_API_KEY` | *(пусто)* | API ключ OpenAI для analysis-worker |
| `DASHBOARD_PORT` | `8080` | Порт для dashboard-web |

### Dashboard Web (UI аналитики)

Dashboard — web-интерфейс для просмотра аналитики допродаж.

**Быстрый старт:**

```bash
cd infra
docker compose up -d dashboard-web
```

**Открыть UI:** http://localhost:8080

**Авторизация:**
1. Откройте http://localhost:8080
2. Введите URL API (по умолчанию `http://localhost:8000`)
3. Введите ADMIN_TOKEN из вашего .env файла
4. Нажмите "Войти"

Токен хранится только в sessionStorage браузера и не включён в сборку.

**Возможности Dashboard:**
- **Обзор** — сводные показатели за день: количество диалогов, попытки допродаж, среднее качество
- **Графики** — динамика по часам, топ категорий предложений, распределение качества
- **Диалоги** — список с фильтрацией по дате, точке, попытке допродажи, качеству
- **Детали** — полный текст диалога, анализ LLM, подсветка цитат-доказательств

**Таймзона:** Europe/Belgrade (отображается в UI локальное время)

### Развертывание ASR Worker на отдельном VPS

1. На core сервере включите INTERNAL_TOKEN:
```bash
# infra/.env
INTERNAL_TOKEN=your-secret-internal-token
docker compose up -d ingest-api
```

2. На ASR VPS создайте compose файл:
```yaml
version: "3.9"
services:
  asr-worker:
    image: asr-worker:latest
    environment:
      - DATABASE_URL=postgresql+asyncpg://ingest:ingest@core-host:5432/ingest
      - INGEST_INTERNAL_BASE_URL=http://core-host:8000
      - INTERNAL_TOKEN=your-secret-internal-token
    volumes:
      - models:/models
volumes:
  models:
```

3. Проверьте результат:
```sql
SELECT dialogue_id, asr_status, asr_pass FROM dialogues WHERE asr_status = 'DONE';
SELECT dt.text FROM dialogue_transcripts dt LIMIT 5;
```

---

# recorder-agent

Сервис непрерывной записи аудио с USB-микрофона для Raspberry Pi.
Записывает по расписанию, кодирует в OGG/Opus, нарезает чанками и отправляет на Ingest API по HTTPS.

## Возможности

- Запись по расписанию (по умолчанию 08:00 — 22:00, настраивается)
- Непрерывная запись с нарезкой на чанки (по умолчанию 60 сек)
- Кодирование OGG/Opus mono, битрейт 24/32 kbps (настраивается)
- Offline-first: чанки сохраняются локально и отправляются с экспоненциальным backoff
- Ротация хранилища по возрасту (дни) и объёму (ГБ), удаление по FIFO
- Автодетект USB-микрофона, переподключение при отключении
- systemd-сервис с автозапуском и автоперезапуском
- HTTP healthcheck на localhost
- Структурированные JSON-логи (совместимы с journalctl)

## Системные требования

- Raspberry Pi OS (Debian Bookworm+) или любой Linux с ALSA
- Python 3.11+
- ffmpeg с поддержкой libopus
- USB-микрофон

## Структура проекта

```
recorder_agent/
    __init__.py          — пакет, версия
    __main__.py          — точка входа: python -m recorder_agent
    config.py            — загрузка конфигурации (YAML + env)
    audio_device.py      — детект ALSA-устройств, валидация USB-микрофона
    recorder.py          — запись через ffmpeg segment muxer
    uploader.py          — отправка чанков на Ingest API с retry
    spool.py             — очистка хранилища по возрасту и размеру
    scheduler.py         — расписание записи (HH:MM)
    healthcheck.py       — HTTP /health endpoint
    logging_setup.py     — JSON-логирование на stderr
    main.py              — оркестратор сервиса

tests/
    test_config.py       — 7 тестов конфигурации
    test_scheduler.py    — 10 тестов расписания
    test_spool.py        — 6 тестов ротации хранилища
    test_uploader.py     — 11 тестов очереди загрузки

ingest_api/              — сервер приёма чанков (FastAPI)
infra/                   — Docker Compose для деплоя сервера
```

## Установка

### 1. Системные зависимости

```bash
sudo apt update
sudo apt install -y python3-venv ffmpeg alsa-utils
```

### 2. Проверить, что микрофон виден

```bash
arecord -l
```

Вывод должен содержать строку вроде:
```
card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]
```

### 3. Развернуть проект

```bash
cd /opt
sudo mkdir -p recorder-agent && sudo chown $USER: recorder-agent
cp -r /path/to/project/* /opt/recorder-agent/

cd /opt/recorder-agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

### 4. Создать конфигурацию

```bash
sudo mkdir -p /etc/recorder-agent
sudo cp config.yaml.example /etc/recorder-agent/config.yaml
sudo nano /etc/recorder-agent/config.yaml
```

В конфиге обязательно указать:
- `point_id`, `register_id`, `device_id` — валидные UUID
- `ingest_base_url` — адрес сервера (например `https://audio.example.com`)
- `ingest_token` — Bearer-токен для авторизации
- `audio_device` — ALSA-устройство (например `hw:1,0`), или оставить пустым для автодетекта

### 5. Создать каталоги и пользователя

```bash
sudo mkdir -p /var/lib/recorder-agent/spool
sudo useradd -r -s /usr/sbin/nologin recorder-agent || true
sudo usermod -aG audio recorder-agent
sudo chown -R recorder-agent: /var/lib/recorder-agent
```

## Запуск вручную (для отладки)

```bash
source /opt/recorder-agent/venv/bin/activate

# С конфиг-файлом
python -m recorder_agent -c /etc/recorder-agent/config.yaml

# Через переменные окружения
export RA_POINT_ID="00000000-0000-0000-0000-000000000001"
export RA_REGISTER_ID="00000000-0000-0000-0000-000000000002"
export RA_DEVICE_ID="00000000-0000-0000-0000-000000000003"
export RA_INGEST_BASE_URL="https://audio.example.com"
export RA_INGEST_TOKEN="your-token"
python -m recorder_agent

# С отладочным логированием
python -m recorder_agent -c /etc/recorder-agent/config.yaml --log-level DEBUG
```

## Запуск как systemd-сервис

```bash
sudo cp recorder-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable recorder-agent
sudo systemctl start recorder-agent
```

Просмотр логов:
```bash
sudo systemctl status recorder-agent
sudo journalctl -u recorder-agent -f
```

## Healthcheck

```bash
curl -s http://127.0.0.1:8042/health | python3 -m json.tool
```

Пример ответа:

```json
{
  "status": "ok",
  "recording": true,
  "in_schedule": true,
  "queue_size": 2,
  "uploaded_total": 147,
  "upload_errors_total": 3,
  "last_upload_ts": 1705312345.6,
  "spool_files": 42,
  "spool_bytes": 8372224,
  "point_id": "00000000-0000-0000-0000-000000000001"
}
```

## Проверка работоспособности

```bash
# 1. Микрофон определяется
arecord -l

# 2. Ручная тестовая запись (5 сек)
arecord -D hw:1,0 -f S16_LE -r 48000 -c 1 -d 5 /tmp/test.wav
aplay /tmp/test.wav

# 3. Тест кодирования через ffmpeg
ffmpeg -f alsa -i hw:1,0 -ac 1 -ar 48000 -c:a libopus -b:a 24k -t 5 /tmp/test.ogg

# 4. Запустить сервис и наблюдать логи
sudo systemctl start recorder-agent
sudo journalctl -u recorder-agent -f

# 5. Следить за появлением чанков в outbox
watch ls -la /var/lib/recorder-agent/spool/outbox/

# 6. Проверить healthcheck
curl -s http://127.0.0.1:8042/health | python3 -m json.tool

# 7. Убедиться, что очередь разгружается (queue_size уменьшается)
watch 'curl -s http://127.0.0.1:8042/health | python3 -m json.tool'
```

## Запуск тестов

```bash
source /opt/recorder-agent/venv/bin/activate
pip install -e ".[dev]"
pytest -v
```

## Справочник конфигурации

| Ключ | Переменная окружения | По умолчанию | Описание |
|------|----------------------|--------------|----------|
| `point_id` | `RA_POINT_ID` | *обязательно* | UUID точки продаж |
| `register_id` | `RA_REGISTER_ID` | *обязательно* | UUID кассы |
| `device_id` | `RA_DEVICE_ID` | *обязательно* | UUID устройства |
| `ingest_base_url` | `RA_INGEST_BASE_URL` | *обязательно* | Базовый URL Ingest API |
| `ingest_token` | `RA_INGEST_TOKEN` | *обязательно* | Bearer-токен авторизации |
| `schedule_start` | `RA_SCHEDULE_START` | `08:00` | Время начала записи (HH:MM) |
| `schedule_end` | `RA_SCHEDULE_END` | `22:00` | Время окончания записи (HH:MM) |
| `chunk_seconds` | `RA_CHUNK_SECONDS` | `60` | Длительность чанка (секунды) |
| `opus_bitrate_kbps` | `RA_OPUS_BITRATE_KBPS` | `24` | Битрейт Opus (kbps) |
| `audio_device` | `RA_AUDIO_DEVICE` | *(автодетект)* | ALSA-устройство (напр. `hw:1,0`) |
| `sample_rate` | `RA_SAMPLE_RATE` | `48000` | Частота дискретизации (Гц) |
| `spool_dir` | `RA_SPOOL_DIR` | `/var/lib/recorder-agent/spool` | Корневой каталог хранилища |
| `max_spool_days` | `RA_MAX_SPOOL_DAYS` | `7` | Хранить не дольше N дней |
| `max_spool_gb` | `RA_MAX_SPOOL_GB` | `20` | Максимальный размер хранилища (ГБ) |
| `retry_min_s` | `RA_RETRY_MIN_S` | `2` | Минимальная задержка retry (сек) |
| `retry_max_s` | `RA_RETRY_MAX_S` | `300` | Максимальная задержка retry (сек) |
| `health_port` | `RA_HEALTH_PORT` | `8042` | Порт HTTP healthcheck |

## Протокол загрузки

```
POST {ingest_base_url}/api/v1/chunks
Authorization: Bearer <token>
Content-Type: multipart/form-data

Поля: point_id, register_id, device_id, start_ts, end_ts, codec, sample_rate, channels
Файл: chunk_file (audio/ogg)

Ответ 200: {"status": "ok", "chunk_id": "...", "stored_path": "...", "queued": true}
```

## Потоки (threads)

| Поток | Назначение |
|-------|------------|
| **main** | Оркестратор, schedule loop: каждые 5 с проверяет расписание, запускает/останавливает recorder |
| **recorder** | Управляет процессом ffmpeg, переименовывает завершённые `.part` → `.ogg`, переподключает микрофон |
| **uploader** | Сканирует outbox, отправляет чанки, backoff при ошибках |
| **spool-janitor** | Каждые 5 мин удаляет файлы старше `max_spool_days` и сверх `max_spool_gb` |
| **health** | HTTP-сервер на `127.0.0.1:health_port` |

## Обработка сбоев

| Ситуация | Поведение |
|----------|-----------|
| Микрофон отключён | ffmpeg завершается, recorder пытается переподключиться с backoff 2 → 4 → 8 → ... → 60 сек |
| Микрофон вернулся | Автоматический перезапуск записи, backoff сбрасывается |
| Сеть недоступна | Чанки копятся в outbox, uploader ретраит с backoff 2 → 300 сек + jitter |
| Сеть вернулась | Backoff сбрасывается при первом успешном upload |
| Диск заполнен | SpoolJanitor удаляет самые старые файлы, пока `total < max_spool_gb` |
| SIGTERM / SIGINT | Корректная остановка: ffmpeg получает SIGINT, текущий чанк финализируется, потоки завершаются |
