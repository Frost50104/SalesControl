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

config.yaml.example      — пример конфигурации
.env.example              — пример переменных окружения
recorder-agent.service    — systemd unit file
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

Ответ 200: {"status": "ok", "chunk_id": "..."}
```

## Архитектура

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Scheduler   │────>│   Recorder   │────>│   outbox/    │
│ (main loop)  │     │   (ffmpeg)   │     │  .ogg files  │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                 │
                     ┌──────────────┐            │
                     │   Uploader   │<───────────┘
                     │  (HTTP POST) │──────> Ingest API
                     └──────┬───────┘
                            │ при успехе
                     ┌──────▼───────┐
                     │  uploaded/   │
                     │  .ogg files  │
                     └──────┬───────┘
                            │
                     ┌──────▼───────┐
                     │ SpoolJanitor │──> удаление старых / лишних
                     └──────────────┘
```

### Потоки (threads)

| Поток | Назначение |
|-------|------------|
| **main** | Оркестратор, schedule loop: каждые 5 с проверяет расписание, запускает/останавливает recorder |
| **recorder** | Управляет процессом ffmpeg, переименовывает завершённые `.part` → `.ogg`, переподключает микрофон |
| **uploader** | Сканирует outbox, отправляет чанки, backoff при ошибках |
| **spool-janitor** | Каждые 5 мин удаляет файлы старше `max_spool_days` и сверх `max_spool_gb` |
| **health** | HTTP-сервер на `127.0.0.1:health_port` |

### Обработка сбоев

| Ситуация | Поведение |
|----------|-----------|
| Микрофон отключён | ffmpeg завершается, recorder пытается переподключиться с backoff 2 → 4 → 8 → ... → 60 сек |
| Микрофон вернулся | Автоматический перезапуск записи, backoff сбрасывается |
| Сеть недоступна | Чанки копятся в outbox, uploader ретраит с backoff 2 → 300 сек + jitter |
| Сеть вернулась | Backoff сбрасывается при первом успешном upload |
| Диск заполнен | SpoolJanitor удаляет самые старые файлы, пока `total < max_spool_gb` |
| SIGTERM / SIGINT | Корректная остановка: ffmpeg получает SIGINT, текущий чанк финализируется, потоки завершаются |
