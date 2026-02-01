# Руководство по развёртыванию и тестированию SalesControl на реальной точке

Это пошаговая инструкция для проведения реального теста системы SalesControl на точке продаж.

---

## Оглавление

1. [Обзор инфраструктуры](#1-обзор-инфраструктуры)
2. [Требования к серверам](#2-требования-к-серверам)
3. [Аренда и настройка серверов](#3-аренда-и-настройка-серверов)
4. [Настройка Core-сервера](#4-настройка-core-сервера)
5. [Настройка ASR-сервера](#5-настройка-asr-сервера)
6. [Настройка Raspberry Pi на точке](#6-настройка-raspberry-pi-на-точке)
7. [Проверка работоспособности](#7-проверка-работоспособности)
8. [Мониторинг во время теста](#8-мониторинг-во-время-теста)
9. [Устранение неполадок](#9-устранение-неполадок)
10. [Чеклист перед тестом](#10-чеклист-перед-тестом)

---

## 1. Обзор инфраструктуры

### Архитектура системы

```
┌─────────────────────┐
│   Точка продаж      │
│  ┌───────────────┐  │
│  │ Raspberry Pi  │  │
│  │ + USB-микрофон│  │
│  └───────┬───────┘  │
└──────────┼──────────┘
           │ HTTPS (upload chunks)
           ▼
┌─────────────────────┐
│   Core Server (VPS) │
│  ┌───────────────┐  │
│  │  Ingest API   │  │
│  │  PostgreSQL   │  │
│  │  Redis        │  │
│  │  VAD Worker   │  │
│  │  Analysis     │  │
│  │  Dashboard    │  │
│  └───────┬───────┘  │
└──────────┼──────────┘
           │ Internal HTTP
           ▼
┌─────────────────────┐
│  ASR Server (VPS)   │
│  ┌───────────────┐  │
│  │  ASR Worker   │  │
│  │  (Whisper)    │  │
│  └───────────────┘  │
└─────────────────────┘
```

### Компоненты

| Компонент | Где размещён | Назначение |
|-----------|--------------|------------|
| Recorder Agent | Raspberry Pi | Запись аудио с микрофона |
| Ingest API | Core Server | Приём аудио-чанков |
| VAD Worker | Core Server | Обнаружение речи |
| ASR Worker | ASR Server | Распознавание речи (Whisper) |
| Analysis Worker | Core Server | LLM-анализ допродаж |
| Dashboard | Core Server | Веб-интерфейс |

---

## 2. Требования к серверам

### Вариант A: Минимальный (для теста 1-5 точек)

**Нужно арендовать: 2 VPS**

#### Core Server (основной)
- **CPU:** 2 vCPU
- **RAM:** 4 GB
- **Диск:** 40 GB SSD (NVMe предпочтительнее)
- **Трафик:** 1 TB/месяц
- **ОС:** Ubuntu 22.04 LTS или Debian 12
- **Примерная стоимость:** $15-25/месяц

*Примеры провайдеров:*
- Hetzner Cloud: CX21 (~€5.18/мес) или CX31 (~€9.52/мес)
- DigitalOcean: Basic Droplet $12-24/мес
- Selectel (РФ): Cloud Server от 600₽/мес
- TimeWeb (РФ): VDS от 300₽/мес

#### ASR Server (для Whisper)
- **CPU:** 4 vCPU (важно для Whisper)
- **RAM:** 8 GB (минимум для модели `small`)
- **Диск:** 20 GB SSD
- **Трафик:** 500 GB/месяц
- **ОС:** Ubuntu 22.04 LTS
- **Примерная стоимость:** $25-40/месяц

*Примеры провайдеров:*
- Hetzner Cloud: CX41 (~€17.68/мес)
- DigitalOcean: CPU-Optimized $42/мес
- Selectel (РФ): от 1200₽/мес
- TimeWeb (РФ): VDS от 800₽/мес

**Итого для минимального теста: ~$40-65/месяц (~3500-5500₽/мес)**

---

### Вариант B: Один сервер (самый экономный, только для теста)

Если бюджет ограничен, можно запустить всё на одном сервере:

- **CPU:** 4 vCPU
- **RAM:** 8 GB
- **Диск:** 50 GB SSD
- **Примерная стоимость:** $25-40/месяц

**Минусы:** ASR будет медленнее, может влиять на отзывчивость API.

---

### Вариант C: С GPU (для быстрого ASR)

Если нужна максимальная скорость распознавания:

#### ASR Server с GPU
- **GPU:** NVIDIA T4 или RTX 3060
- **CPU:** 4 vCPU
- **RAM:** 16 GB
- **Примерная стоимость:** $50-150/месяц

*Провайдеры с GPU:*
- Vast.ai: от $0.10/час
- Lambda Labs: от $0.50/час
- Hetzner: GPU servers от €150/мес

---

## 3. Аренда и настройка серверов

### Шаг 3.1: Аренда серверов

1. Зарегистрируйтесь у выбранного провайдера
2. Создайте SSH-ключ (если ещё нет):
   ```bash
   ssh-keygen -t ed25519 -C "salescontrol-server"
   cat ~/.ssh/id_ed25519.pub  # скопируйте для добавления на сервер
   ```
3. Арендуйте 2 VPS с указанными характеристиками
4. Добавьте SSH-ключ при создании серверов
5. Запишите IP-адреса серверов:
   - Core Server IP: `___.___.___.___ ` (далее CORE_IP)
   - ASR Server IP: `___.___.___.___ ` (далее ASR_IP)

### Шаг 3.2: Базовая настройка серверов

Выполните на **обоих серверах**:

```bash
# Подключение
ssh root@CORE_IP  # или ASR_IP

# Обновление системы
apt update && apt upgrade -y

# Установка необходимых пакетов
apt install -y \
    curl \
    git \
    htop \
    ufw \
    fail2ban

# Настройка firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 8000/tcp  # Ingest API (только на Core)
ufw allow 8080/tcp  # Dashboard (только на Core)
ufw --force enable

# Настройка часового пояса
timedatectl set-timezone Europe/Moscow

# Создание пользователя (опционально, но рекомендуется)
adduser deploy
usermod -aG sudo deploy
su - deploy
```

### Шаг 3.3: Установка Docker

Выполните на **обоих серверах**:

```bash
# Установка Docker
curl -fsSL https://get.docker.com | sh

# Добавление пользователя в группу docker
sudo usermod -aG docker $USER

# Перелогиниться для применения группы
exit
ssh root@CORE_IP  # переподключиться

# Проверка
docker --version
docker compose version
```

---

## 4. Настройка Core-сервера

### Шаг 4.1: Клонирование проекта

```bash
ssh root@CORE_IP

cd /opt
git clone https://github.com/YOUR_REPO/SalesControl.git
cd SalesControl
```

Или скопируйте файлы с локальной машины:
```bash
# На локальной машине
rsync -avz --exclude='venv' --exclude='__pycache__' --exclude='.git' \
    /home/petr/PycharmProjects/SalesСontrol/ \
    root@CORE_IP:/opt/SalesControl/
```

### Шаг 4.2: Настройка переменных окружения

```bash
cd /opt/SalesControl/infra
cp .env.example .env
nano .env  # или vim .env
```

Заполните `.env`:

```bash
# ============================================
# ОСНОВНЫЕ НАСТРОЙКИ
# ============================================

# Токен администратора (для Dashboard и управления устройствами)
# ВАЖНО: замените на надёжный токен!
ADMIN_TOKEN=your-secure-admin-token-here-min-32-chars

# Внутренний токен для ASR воркера
# ВАЖНО: замените на надёжный токен!
INTERNAL_TOKEN=your-secure-internal-token-here

# ============================================
# БАЗА ДАННЫХ
# ============================================
POSTGRES_USER=ingest
POSTGRES_PASSWORD=your-secure-db-password-here
POSTGRES_DB=ingest
POSTGRES_PORT=5432

# ============================================
# REDIS
# ============================================
REDIS_PORT=6379

# ============================================
# INGEST API
# ============================================
INGEST_API_PORT=8000

# ============================================
# VAD WORKER (обнаружение речи)
# ============================================
VAD_AGGRESSIVENESS=2
SILENCE_GAP_SEC=12.0
MAX_DIALOGUE_SEC=120.0
POLL_INTERVAL_SEC=5.0
BATCH_SIZE=10

# ============================================
# ANALYSIS WORKER (LLM анализ)
# ============================================
# Получите ключ на https://platform.openai.com/api-keys
OPENAI_API_KEY=sk-your-openai-api-key-here
OPENAI_MODEL=gpt-4o-mini
OPENAI_TIMEOUT_SEC=60.0

# ============================================
# DASHBOARD
# ============================================
DASHBOARD_PORT=8080
VITE_API_URL=http://CORE_IP:8000
```

### Шаг 4.3: Создание директории для аудио

```bash
mkdir -p /opt/SalesControl/infra/audio_storage
chmod 755 /opt/SalesControl/infra/audio_storage
```

### Шаг 4.4: Запуск сервисов (без ASR)

Создайте `docker-compose.override.yml` для отключения локального ASR:

```bash
cat > /opt/SalesControl/infra/docker-compose.override.yml << 'EOF'
services:
  asr-worker:
    profiles:
      - disabled
EOF
```

Запустите сервисы:

```bash
cd /opt/SalesControl/infra
docker compose up -d

# Проверка статуса
docker compose ps
docker compose logs -f  # Ctrl+C для выхода
```

### Шаг 4.5: Проверка работоспособности Core

```bash
# Health check API
curl http://localhost:8000/health

# Должен вернуть: {"status":"healthy"}

# Health check Dashboard
curl http://localhost:8080/health
```

### Шаг 4.6: Настройка HTTPS (рекомендуется)

Для production рекомендуется настроить HTTPS через Nginx + Let's Encrypt:

```bash
apt install -y nginx certbot python3-certbot-nginx

# Настройка Nginx (пример)
cat > /etc/nginx/sites-available/salescontrol << 'EOF'
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        client_max_body_size 50M;
    }
}
EOF

ln -s /etc/nginx/sites-available/salescontrol /etc/nginx/sites-enabled/
nginx -t && systemctl restart nginx

# Получение SSL сертификата
certbot --nginx -d your-domain.com
```

---

## 5. Настройка ASR-сервера

### Шаг 5.1: Подготовка

```bash
ssh root@ASR_IP

mkdir -p /opt/SalesControl/asr
cd /opt/SalesControl/asr
```

### Шаг 5.2: Создание Docker Compose для ASR

```bash
cat > docker-compose.yml << 'EOF'
services:
  asr-worker:
    build:
      context: .
      dockerfile: Dockerfile
    restart: unless-stopped
    environment:
      # Подключение к Core Server
      DATABASE_URL: postgresql+asyncpg://ingest:YOUR_DB_PASSWORD@CORE_IP:5432/ingest
      INGEST_INTERNAL_BASE_URL: http://CORE_IP:8000
      INTERNAL_TOKEN: your-secure-internal-token-here

      # Настройки Whisper
      WHISPER_MODEL_FAST: base
      WHISPER_MODEL_ACCURATE: small
      WHISPER_LANGUAGE: ru
      WHISPER_DEVICE: cpu
      WHISPER_COMPUTE_TYPE: int8
      WHISPER_CPU_THREADS: 4

      # Воркер
      POLL_INTERVAL_SEC: 5.0
      BATCH_SIZE: 5
      STUCK_TIMEOUT_SEC: 600
    volumes:
      - whisper_models:/root/.cache/huggingface
      - ./tmp:/tmp/asr_audio
    deploy:
      resources:
        limits:
          memory: 6G

volumes:
  whisper_models:
EOF
```

**ВАЖНО:** Замените в файле:
- `YOUR_DB_PASSWORD` — пароль из `.env` Core-сервера
- `CORE_IP` — IP-адрес Core-сервера
- `your-secure-internal-token-here` — токен из `.env` Core-сервера

### Шаг 5.3: Создание Dockerfile

```bash
cat > Dockerfile << 'EOF'
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "asr_worker"]
EOF
```

### Шаг 5.4: Копирование кода ASR воркера

С локальной машины:

```bash
# Копируем только asr_worker
rsync -avz \
    /home/petr/PycharmProjects/SalesСontrol/asr_worker/ \
    root@ASR_IP:/opt/SalesControl/asr/asr_worker/

# Копируем requirements
scp /home/petr/PycharmProjects/SalesСontrol/asr_worker/requirements.txt \
    root@ASR_IP:/opt/SalesControl/asr/
```

### Шаг 5.5: Открытие порта PostgreSQL на Core-сервере

На **Core-сервере**:

```bash
# Открываем порт PostgreSQL только для ASR-сервера
ufw allow from ASR_IP to any port 5432

# Настраиваем PostgreSQL для внешних подключений
# Редактируем docker-compose.yml на Core-сервере
cd /opt/SalesControl/infra
```

Добавьте в `docker-compose.override.yml`:

```yaml
services:
  postgres:
    ports:
      - "5432:5432"
```

Перезапустите:
```bash
docker compose up -d
```

### Шаг 5.6: Запуск ASR воркера

На **ASR-сервере**:

```bash
cd /opt/SalesControl/asr
docker compose up -d

# Проверка логов
docker compose logs -f
```

Первый запуск скачает модели Whisper (~150MB для base + ~500MB для small).

---

## 6. Настройка Raspberry Pi на точке

### Требования к оборудованию

- Raspberry Pi 4 Model B (2GB RAM минимум)
- USB-микрофон (рекомендуется: конденсаторный, направленный)
- MicroSD карта 16GB+ (Class 10)
- Блок питания 5V 3A (официальный)
- Стабильный интернет (Wi-Fi или Ethernet)

### Шаг 6.1: Установка Raspberry Pi OS

1. Скачайте [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Выберите: Raspberry Pi OS Lite (64-bit)
3. Нажмите шестерёнку и настройте:
   - Hostname: `salescontrol-point01`
   - Enable SSH: Yes, use password authentication
   - Username: `pi`
   - Password: `your-secure-password`
   - Configure Wi-Fi (если нужно)
   - Set locale: Europe/Moscow, ru
4. Запишите образ на SD-карту
5. Вставьте карту в Raspberry Pi и включите

### Шаг 6.2: Первоначальная настройка

```bash
# Подключитесь к Raspberry Pi
ssh pi@salescontrol-point01.local
# или по IP: ssh pi@192.168.x.x

# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка необходимых пакетов
sudo apt install -y \
    python3-pip \
    python3-venv \
    ffmpeg \
    alsa-utils \
    git

# Проверка микрофона
arecord -l
# Должен показать ваш USB-микрофон, например:
# card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]
```

### Шаг 6.3: Установка Recorder Agent

```bash
# Создание директории
sudo mkdir -p /opt/recorder-agent
sudo chown pi:pi /opt/recorder-agent
cd /opt/recorder-agent

# Копирование файлов (с вашего компьютера)
# На локальной машине выполните:
rsync -avz \
    /home/petr/PycharmProjects/SalesСontrol/recorder_agent/ \
    pi@salescontrol-point01.local:/opt/recorder-agent/

# На Raspberry Pi продолжаем:
cd /opt/recorder-agent

# Создание виртуального окружения
python3 -m venv venv
source venv/bin/activate

# Установка зависимостей
pip install --upgrade pip
pip install -r requirements.txt
```

### Шаг 6.4: Регистрация устройства на сервере

На **локальной машине или Core-сервере**:

```bash
# Генерация ID и токена устройства
DEVICE_ID=$(uuidgen)
POINT_ID=$(uuidgen)
REGISTER_ID=$(uuidgen)
DEVICE_TOKEN=$(openssl rand -hex 32)

echo "Device ID: $DEVICE_ID"
echo "Point ID: $POINT_ID"
echo "Register ID: $REGISTER_ID"
echo "Device Token: $DEVICE_TOKEN"
# СОХРАНИТЕ ЭТИ ЗНАЧЕНИЯ!

# Регистрация устройства
curl -X POST "http://CORE_IP:8000/api/v1/admin/devices" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"device_id\": \"$DEVICE_ID\",
    \"point_id\": \"$POINT_ID\",
    \"register_id\": \"$REGISTER_ID\",
    \"token\": \"$DEVICE_TOKEN\",
    \"is_enabled\": true
  }"
```

### Шаг 6.5: Настройка конфигурации

На **Raspberry Pi**:

```bash
sudo mkdir -p /etc/recorder-agent
sudo nano /etc/recorder-agent/config.yaml
```

Содержимое `config.yaml`:

```yaml
# Идентификация устройства
device_id: "YOUR_DEVICE_ID"
point_id: "YOUR_POINT_ID"
register_id: "YOUR_REGISTER_ID"

# Сервер
server:
  url: "http://CORE_IP:8000"  # или https://your-domain.com
  token: "YOUR_DEVICE_TOKEN"
  timeout_sec: 30
  retry_initial_sec: 2
  retry_max_sec: 300

# Запись
recording:
  schedule_start: "08:00"
  schedule_end: "22:00"
  chunk_duration_sec: 60
  codec: "opus"
  bitrate: "24k"
  sample_rate: 16000
  channels: 1

# Хранилище
storage:
  spool_dir: "/var/lib/recorder-agent/spool"
  max_age_days: 7
  max_size_gb: 20

# Логирование
logging:
  level: "INFO"
  format: "json"

# Health check
healthcheck:
  enabled: true
  port: 8042
```

**Замените:**
- `YOUR_DEVICE_ID` — Device ID из шага 6.4
- `YOUR_POINT_ID` — Point ID из шага 6.4
- `YOUR_REGISTER_ID` — Register ID из шага 6.4
- `YOUR_DEVICE_TOKEN` — Device Token из шага 6.4
- `CORE_IP` — IP-адрес Core-сервера

### Шаг 6.6: Создание директорий и systemd сервиса

```bash
# Создание директорий
sudo mkdir -p /var/lib/recorder-agent/spool/{inbox,outbox,failed}
sudo chown -R pi:pi /var/lib/recorder-agent

# Создание systemd сервиса
sudo nano /etc/systemd/system/recorder-agent.service
```

Содержимое сервиса:

```ini
[Unit]
Description=SalesControl Recorder Agent
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/opt/recorder-agent
Environment="PATH=/opt/recorder-agent/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/opt/recorder-agent/venv/bin/python -m recorder_agent
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Безопасность
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/lib/recorder-agent

[Install]
WantedBy=multi-user.target
```

### Шаг 6.7: Запуск сервиса

```bash
# Перезагрузка systemd
sudo systemctl daemon-reload

# Включение автозапуска
sudo systemctl enable recorder-agent

# Запуск
sudo systemctl start recorder-agent

# Проверка статуса
sudo systemctl status recorder-agent

# Просмотр логов
sudo journalctl -u recorder-agent -f
```

### Шаг 6.8: Проверка работы

```bash
# Health check
curl http://localhost:8042/health

# Проверка записи
ls -la /var/lib/recorder-agent/spool/outbox/

# Должны появиться файлы chunk_*.ogg
```

---

## 7. Проверка работоспособности

### Тест 1: Проверка связи Raspberry Pi → Core Server

На **Raspberry Pi**:

```bash
# Проверка доступности сервера
curl -I http://CORE_IP:8000/health

# Должен вернуть: HTTP/1.1 200 OK
```

### Тест 2: Проверка загрузки чанков

На **Core-сервере**:

```bash
# Проверка логов Ingest API
docker compose logs -f ingest-api

# Должны появиться записи о POST /api/v1/chunks
```

### Тест 3: Проверка обработки VAD

```bash
# На Core-сервере
docker compose logs -f vad-worker

# Должны появиться записи об обработке chunks
```

### Тест 4: Проверка ASR

```bash
# На ASR-сервере
docker compose logs -f

# Должны появиться записи о распознавании диалогов
```

### Тест 5: Проверка через Dashboard

1. Откройте в браузере: `http://CORE_IP:8080`
2. Введите Admin Token
3. Перейдите в раздел "Диалоги"
4. Должны появиться обработанные диалоги

### Тест 6: Проверка базы данных

На **Core-сервере**:

```bash
docker compose exec postgres psql -U ingest -d ingest

# В psql:
SELECT COUNT(*) FROM audio_chunks;
SELECT COUNT(*) FROM dialogues;
SELECT status, COUNT(*) FROM audio_chunks GROUP BY status;
SELECT asr_status, COUNT(*) FROM dialogues GROUP BY asr_status;
\q
```

---

## 8. Мониторинг во время теста

### Мониторинг на Core-сервере

```bash
# Все логи в реальном времени
docker compose logs -f

# Статус сервисов
docker compose ps

# Использование ресурсов
docker stats

# Дисковое пространство
df -h /opt/SalesControl/infra/audio_storage
```

### Мониторинг на ASR-сервере

```bash
# Логи ASR
docker compose logs -f

# Загрузка CPU (должна быть высокой при обработке)
htop
```

### Мониторинг на Raspberry Pi

```bash
# Логи recorder-agent
sudo journalctl -u recorder-agent -f

# Очередь на отправку
ls -la /var/lib/recorder-agent/spool/outbox/
ls -la /var/lib/recorder-agent/spool/failed/

# Использование дисков
df -h

# Температура (важно для Pi)
vcgencmd measure_temp
```

### SQL-запросы для мониторинга

```sql
-- Статус обработки чанков
SELECT
    status,
    COUNT(*) as count,
    MAX(created_at) as last_created
FROM audio_chunks
GROUP BY status;

-- Застрявшие чанки (должно быть 0)
SELECT COUNT(*)
FROM audio_chunks
WHERE status = 'PROCESSING'
  AND created_at < NOW() - INTERVAL '10 minutes';

-- Статус диалогов
SELECT
    asr_status,
    analysis_status,
    COUNT(*) as count
FROM dialogues
GROUP BY asr_status, analysis_status;

-- Последние диалоги с анализом
SELECT
    d.dialogue_id,
    dt.text,
    da.attempted,
    da.quality_score
FROM dialogues d
LEFT JOIN dialogue_transcripts dt ON d.dialogue_id = dt.dialogue_id
LEFT JOIN dialogue_upsell_analysis da ON d.dialogue_id = da.dialogue_id
ORDER BY d.created_at DESC
LIMIT 10;
```

---

## 9. Устранение неполадок

### Проблема: Recorder Agent не запускается

```bash
# Проверка логов
sudo journalctl -u recorder-agent -n 100

# Частые причины:
# 1. Микрофон не найден
arecord -l

# 2. Права доступа
ls -la /var/lib/recorder-agent/

# 3. Конфигурация
cat /etc/recorder-agent/config.yaml
```

### Проблема: Чанки не загружаются на сервер

```bash
# На Raspberry Pi
# Проверка сети
ping CORE_IP
curl -v http://CORE_IP:8000/health

# Проверка очереди
ls -la /var/lib/recorder-agent/spool/outbox/
ls -la /var/lib/recorder-agent/spool/failed/

# Проверка токена (на сервере)
docker compose exec postgres psql -U ingest -d ingest -c \
  "SELECT device_id, is_enabled FROM devices;"
```

### Проблема: ASR не обрабатывает диалоги

```bash
# На ASR-сервере
docker compose logs asr-worker

# Проверка подключения к БД
docker compose exec asr-worker python -c "
import asyncio
from db import get_engine
asyncio.run(get_engine().connect())
print('DB OK')
"

# Проверка доступа к аудио
curl -H "Authorization: Bearer INTERNAL_TOKEN" \
  http://CORE_IP:8000/api/v1/internal/chunks/test
```

### Проблема: Dashboard не показывает данные

```bash
# Проверка API
curl -H "Authorization: Bearer ADMIN_TOKEN" \
  http://CORE_IP:8000/api/v1/analytics/daily

# Проверка CORS (в браузере Dev Tools → Network)
```

### Проблема: Высокая задержка обработки

```bash
# Проверка очереди
docker compose exec postgres psql -U ingest -d ingest -c \
  "SELECT status, COUNT(*) FROM audio_chunks GROUP BY status;"

# Увеличение воркеров (в docker-compose.yml)
# Добавить replicas для vad-worker или asr-worker
```

---

## 10. Чеклист перед тестом

### Серверы

- [ ] Core-сервер арендован и настроен
- [ ] ASR-сервер арендован и настроен
- [ ] Docker установлен на обоих серверах
- [ ] Firewall настроен (порты 8000, 8080, 5432)
- [ ] `.env` файл заполнен корректно
- [ ] ADMIN_TOKEN и INTERNAL_TOKEN надёжные
- [ ] OPENAI_API_KEY установлен и рабочий
- [ ] PostgreSQL доступен для ASR-сервера
- [ ] Все сервисы запущены (`docker compose ps`)
- [ ] Health checks проходят

### Raspberry Pi

- [ ] Raspberry Pi OS установлена (64-bit Lite)
- [ ] SSH доступ работает
- [ ] USB-микрофон подключён и определяется (`arecord -l`)
- [ ] Интернет работает стабильно
- [ ] Recorder Agent установлен
- [ ] Конфигурация заполнена корректно
- [ ] Устройство зарегистрировано на сервере
- [ ] systemd сервис включён и запущен
- [ ] Health check проходит (`:8042/health`)

### Тестирование

- [ ] Чанки записываются (файлы в outbox)
- [ ] Чанки загружаются (логи ingest-api)
- [ ] VAD обрабатывает (статус DONE в БД)
- [ ] ASR распознаёт (транскрипты в БД)
- [ ] Analysis работает (анализ в БД)
- [ ] Dashboard показывает данные
- [ ] Воспроизведение аудио работает

### Контакты для экстренных случаев

- Хостинг-провайдер: _______________
- OpenAI: https://status.openai.com
- Ваши контакты: _______________

---

## Быстрые команды

```bash
# === CORE SERVER ===
cd /opt/SalesControl/infra
docker compose up -d          # Запуск
docker compose down           # Остановка
docker compose logs -f        # Логи
docker compose ps             # Статус

# === ASR SERVER ===
cd /opt/SalesControl/asr
docker compose up -d          # Запуск
docker compose logs -f        # Логи

# === RASPBERRY PI ===
sudo systemctl start recorder-agent
sudo systemctl stop recorder-agent
sudo systemctl status recorder-agent
sudo journalctl -u recorder-agent -f

# === ПРОВЕРКИ ===
curl http://CORE_IP:8000/health
curl http://localhost:8042/health
```

---

## Оценка стоимости (ежемесячно)

| Компонент | Минимум | Рекомендуемо |
|-----------|---------|--------------|
| Core Server | $15 | $25 |
| ASR Server | $25 | $40 |
| OpenAI API* | $5-10 | $10-20 |
| **Итого** | **~$45-50** | **~$75-85** |

*OpenAI API: ~$0.15 за 1M input tokens (gpt-4o-mini). При 100 диалогах/день ≈ $3-5/мес.

---

*Документ создан: 2026-02-01*
*Версия: 1.0*
