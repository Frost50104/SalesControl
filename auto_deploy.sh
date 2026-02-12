#!/bin/bash
#
# SalesControl Auto Deploy - Полностью автоматическое развертывание
# Выполняется на локальной машине, делает всё автоматически
#
# Использование:
#   bash auto_deploy.sh
#

set -e

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
NC='\033[0m'

print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[✓]${NC} $1"; }
print_error() { echo -e "${RED}[✗]${NC} $1"; }
print_step() { echo -e "\n${MAGENTA}>>> $1${NC}\n"; }

# ASCII Art заголовок
clear
cat << "EOF"
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║     ███████╗ █████╗ ██╗     ███████╗███████╗             ║
║     ██╔════╝██╔══██╗██║     ██╔════╝██╔════╝             ║
║     ███████╗███████║██║     █████╗  ███████╗             ║
║     ╚════██║██╔══██║██║     ██╔══╝  ╚════██║             ║
║     ███████║██║  ██║███████╗███████╗███████║             ║
║     ╚══════╝╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝             ║
║                                                           ║
║           АВТОМАТИЧЕСКОЕ РАЗВЕРТЫВАНИЕ                    ║
║                  Raspberry Pi                             ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
EOF
echo ""

print_info "Этот скрипт полностью автоматически развернет SalesControl на Raspberry Pi"
print_info "Потребуется только ввести параметры один раз в начале"
echo ""

# Проверка необходимых утилит
print_step "Проверка зависимостей"

MISSING_DEPS=()
for cmd in ssh scp rsync curl uuidgen openssl; do
    if ! command -v $cmd &> /dev/null; then
        MISSING_DEPS+=($cmd)
    fi
done

if [ ${#MISSING_DEPS[@]} -ne 0 ]; then
    print_error "Отсутствуют утилиты: ${MISSING_DEPS[*]}"
    print_info "Установите: sudo apt install openssh-client rsync curl uuid-runtime openssl"
    exit 1
fi

print_success "Все зависимости установлены"

# Проверка наличия кода recorder_agent
if [ ! -d "recorder_agent" ]; then
    print_error "Директория recorder_agent не найдена!"
    print_info "Запустите скрипт из корневой директории проекта SalesControl"
    exit 1
fi

print_success "Код recorder_agent найден"

# Сбор параметров
print_step "Настройка параметров"

echo "CORE SERVER:"
read -p "  IP-адрес Core Server (например, 130.49.148.227): " CORE_IP
read -p "  Логин администратора (например, Frost50104): " ADMIN_USERNAME
read -sp "  Пароль администратора: " ADMIN_PASSWORD
echo ""

echo ""
echo "RASPBERRY PI:"
read -p "  IP-адрес Raspberry Pi (например, 192.168.1.100): " RPI_IP
read -p "  Пользователь на Raspberry Pi (обычно 'pi'): " RPI_USER
RPI_USER=${RPI_USER:-pi}
read -sp "  Пароль пользователя $RPI_USER на Raspberry Pi: " RPI_PASSWORD
echo ""

echo ""
echo "ТОЧКА ПРОДАЖ:"
read -p "  Название точки (например, 'Магазин №1'): " POINT_NAME
POINT_NAME=${POINT_NAME:-"Новая точка"}
read -p "  Название кассы (например, 'Касса 1'): " REGISTER_NAME
REGISTER_NAME=${REGISTER_NAME:-"Касса 1"}

echo ""
echo "РАСПИСАНИЕ ЗАПИСИ:"
read -p "  Время начала записи (HH:MM, по умолчанию 08:00): " SCHEDULE_START
SCHEDULE_START=${SCHEDULE_START:-08:00}
read -p "  Время окончания записи (HH:MM, по умолчанию 22:00): " SCHEDULE_END
SCHEDULE_END=${SCHEDULE_END:-22:00}

# Проверка SSH доступа к Raspberry Pi
print_step "Проверка доступа к Raspberry Pi"

print_info "Проверка SSH соединения с $RPI_USER@$RPI_IP..."
if sshpass -p "$RPI_PASSWORD" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 $RPI_USER@$RPI_IP "echo 'OK'" &>/dev/null; then
    print_success "SSH соединение установлено"
else
    print_error "Не удается подключиться к Raspberry Pi"
    print_info "Проверьте IP-адрес, имя пользователя и пароль"
    print_info "Возможно нужно установить sshpass: sudo apt install sshpass"
    exit 1
fi

# Генерация ID и токена
print_step "Регистрация устройства на Core Server"

DEVICE_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
POINT_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
REGISTER_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
DEVICE_TOKEN=$(openssl rand -hex 32)

print_info "Device ID:    $DEVICE_ID"
print_info "Point ID:     $POINT_ID"
print_info "Register ID:  $REGISTER_ID"

# Получение JWT токена
print_info "Аутентификация на Core Server..."
LOGIN_RESPONSE=$(curl -s -X POST "http://$CORE_IP:8000/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$ADMIN_USERNAME\",\"password\":\"$ADMIN_PASSWORD\"}")

if echo "$LOGIN_RESPONSE" | grep -q "access_token"; then
    JWT_TOKEN=$(echo "$LOGIN_RESPONSE" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)
    print_success "Аутентификация успешна"
else
    print_error "Ошибка аутентификации на Core Server:"
    echo "$LOGIN_RESPONSE"
    exit 1
fi

# Регистрация устройства
print_info "Регистрация устройства..."
REGISTER_RESPONSE=$(curl -s -X POST "http://$CORE_IP:8000/api/v1/admin/devices" \
    -H "Authorization: Bearer $JWT_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
        \"device_id\": \"$DEVICE_ID\",
        \"point_id\": \"$POINT_ID\",
        \"register_id\": \"$REGISTER_ID\",
        \"token_plain\": \"$DEVICE_TOKEN\",
        \"is_enabled\": true
    }")

if echo "$REGISTER_RESPONSE" | grep -q "device_id"; then
    print_success "Устройство зарегистрировано: $POINT_NAME - $REGISTER_NAME"
else
    print_error "Ошибка регистрации устройства:"
    echo "$REGISTER_RESPONSE"
    exit 1
fi

# Создание конфигурационного файла
print_step "Создание конфигурации"

CONFIG_FILE=".rpi_deploy_config"
cat > "$CONFIG_FILE" <<EOF
CORE_IP=$CORE_IP
DEVICE_ID=$DEVICE_ID
POINT_ID=$POINT_ID
REGISTER_ID=$REGISTER_ID
DEVICE_TOKEN=$DEVICE_TOKEN
SCHEDULE_START=$SCHEDULE_START
SCHEDULE_END=$SCHEDULE_END
EOF

print_success "Конфигурация создана"

# Копирование файлов на Raspberry Pi
print_step "Копирование файлов на Raspberry Pi"

print_info "Копирование recorder_agent..."
sshpass -p "$RPI_PASSWORD" rsync -az --info=progress2 \
    recorder_agent/ \
    $RPI_USER@$RPI_IP:/tmp/recorder-agent/

print_info "Копирование конфигурации..."
sshpass -p "$RPI_PASSWORD" scp -o StrictHostKeyChecking=no \
    "$CONFIG_FILE" \
    $RPI_USER@$RPI_IP:/tmp/.rpi_deploy_config

print_info "Копирование setup скрипта..."
sshpass -p "$RPI_PASSWORD" scp -o StrictHostKeyChecking=no \
    setup_raspberry.sh \
    $RPI_USER@$RPI_IP:/tmp/setup_raspberry.sh

print_success "Все файлы скопированы"

# Запуск установки на Raspberry Pi
print_step "Запуск автоматической установки на Raspberry Pi"

print_info "Подключение к Raspberry Pi и запуск установки..."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

sshpass -p "$RPI_PASSWORD" ssh -o StrictHostKeyChecking=no -tt $RPI_USER@$RPI_IP << 'ENDSSH'
# Установка на Raspberry Pi
set -e

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() { echo -e "${BLUE}[RPI]${NC} $1"; }
print_success() { echo -e "${GREEN}[RPI ✓]${NC} $1"; }
print_error() { echo -e "${RED}[RPI ✗]${NC} $1"; }

print_info "Начало установки на Raspberry Pi..."

# Загрузка конфигурации
if [ -f /tmp/.rpi_deploy_config ]; then
    source /tmp/.rpi_deploy_config
    print_success "Конфигурация загружена"
else
    print_error "Конфигурация не найдена!"
    exit 1
fi

# Обновление системы
print_info "Обновление системы..."
sudo apt update -qq

print_info "Установка пакетов..."
sudo DEBIAN_FRONTEND=noninteractive apt install -y -qq \
    python3-pip python3-venv ffmpeg alsa-utils git curl \
    > /dev/null 2>&1

# Создание директорий
print_info "Создание директорий..."
sudo mkdir -p /opt/recorder-agent
sudo chown $USER:$USER /opt/recorder-agent
sudo mkdir -p /var/lib/recorder-agent/spool/{inbox,outbox,failed}
sudo chown -R $USER:$USER /var/lib/recorder-agent
sudo mkdir -p /etc/recorder-agent

# Копирование кода
print_info "Установка recorder-agent..."
cp -r /tmp/recorder-agent/* /opt/recorder-agent/
cd /opt/recorder-agent

# Создание правильной структуры (файлы должны быть в подпапке recorder_agent/)
mkdir -p recorder_agent
for f in *.py; do
    [ -f "$f" ] && mv "$f" recorder_agent/
done
[ -d "__pycache__" ] && mv __pycache__ recorder_agent/
# requirements.txt остается в корне
[ -f "recorder_agent/requirements.txt" ] && cp recorder_agent/requirements.txt .

# Python окружение
print_info "Настройка Python окружения..."
python3 -m venv venv > /dev/null 2>&1
source venv/bin/activate
pip install --quiet --upgrade pip > /dev/null 2>&1
pip install --quiet -r requirements.txt > /dev/null 2>&1

# Создание конфигурации
print_info "Создание конфигурации..."
sudo tee /etc/recorder-agent/config.yaml > /dev/null <<EOFCONFIG
# Идентификаторы
point_id: "$POINT_ID"
register_id: "$REGISTER_ID"
device_id: "$DEVICE_ID"

# Ingest сервер
ingest_base_url: "http://$CORE_IP:8000"
ingest_token: "$DEVICE_TOKEN"

# Расписание
schedule_start: "$SCHEDULE_START"
schedule_end: "$SCHEDULE_END"

# Параметры записи
chunk_seconds: 60
opus_bitrate_kbps: 24
sample_rate: 48000
audio_device: ""

# Хранилище
spool_dir: "/var/lib/recorder-agent/spool"
max_spool_days: 7
max_spool_gb: 20.0

# Retry
retry_min_s: 2.0
retry_max_s: 300.0

# Health check
health_port: 8042
EOFCONFIG

# Создание systemd сервиса
print_info "Настройка systemd сервиса..."
sudo tee /etc/systemd/system/recorder-agent.service > /dev/null <<EOFSERVICE
[Unit]
Description=SalesControl Recorder Agent
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=/opt/recorder-agent
Environment="PATH=/opt/recorder-agent/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/opt/recorder-agent/venv/bin/python -m recorder_agent
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/lib/recorder-agent

[Install]
WantedBy=multi-user.target
EOFSERVICE

# Запуск сервиса
print_info "Запуск сервиса..."
sudo systemctl daemon-reload
sudo systemctl enable recorder-agent > /dev/null 2>&1
sudo systemctl start recorder-agent

sleep 2

# Проверка
if sudo systemctl is-active --quiet recorder-agent; then
    print_success "Recorder Agent запущен и работает!"
else
    print_error "Сервис не запустился"
    sudo journalctl -u recorder-agent -n 20 --no-pager
    exit 1
fi

# Очистка временных файлов
rm -rf /tmp/recorder-agent /tmp/.rpi_deploy_config /tmp/setup_raspberry.sh

print_success "Установка на Raspberry Pi завершена!"

ENDSSH

SSH_EXIT_CODE=$?

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ $SSH_EXIT_CODE -eq 0 ]; then
    print_success "Установка на Raspberry Pi завершена успешно!"
else
    print_error "Ошибка при установке на Raspberry Pi"
    exit 1
fi

# Сохранение информации о развертывании
print_step "Сохранение информации"

DEPLOY_LOG="deployment_$(date +%Y%m%d_%H%M%S).log"
cat > "$DEPLOY_LOG" <<EOF
# SalesControl Deployment Log
# Дата: $(date)

## Точка продаж
Название: $POINT_NAME
Касса: $REGISTER_NAME

## Core Server
IP: $CORE_IP
Dashboard: http://$CORE_IP:8080

## Raspberry Pi
IP: $RPI_IP
Пользователь: $RPI_USER

## Устройство
Device ID: $DEVICE_ID
Point ID: $POINT_ID
Register ID: $REGISTER_ID
Device Token: $DEVICE_TOKEN

## Расписание
Начало записи: $SCHEDULE_START
Окончание записи: $SCHEDULE_END

## SSH команды для управления
ssh $RPI_USER@$RPI_IP
sudo systemctl status recorder-agent
sudo journalctl -u recorder-agent -f

EOF

print_success "Лог сохранен в файл: $DEPLOY_LOG"

# Очистка временных файлов
rm -f "$CONFIG_FILE"

# Финальная информация
print_step "✨ РАЗВЕРТЫВАНИЕ ЗАВЕРШЕНО! ✨"

cat << EOF

╔════════════════════════════════════════════════════════════╗
║                 УСТАНОВКА ЗАВЕРШЕНА                        ║
╚════════════════════════════════════════════════════════════╝

📍 Точка: $POINT_NAME - $REGISTER_NAME
🖥️  Raspberry Pi: $RPI_USER@$RPI_IP
🌐 Core Server: $CORE_IP

✅ Что сделано:
   • Устройство зарегистрировано на Core Server
   • Код установлен на Raspberry Pi
   • Сервис настроен и запущен
   • Автозапуск включен

📊 Dashboard: http://$CORE_IP:8080
   Логин: $ADMIN_USERNAME
   Через 2-3 минуты начнут появляться диалоги

🔧 Управление (на Raspberry Pi):
   ssh $RPI_USER@$RPI_IP
   sudo systemctl status recorder-agent
   sudo journalctl -u recorder-agent -f

📝 Информация о развертывании: $DEPLOY_LOG

EOF

print_info "Хотите посмотреть логи Raspberry Pi в реальном времени? (y/n)"
read -p "" -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    print_info "Подключение к логам Raspberry Pi (Ctrl+C для выхода)..."
    sleep 1
    sshpass -p "$RPI_PASSWORD" ssh -o StrictHostKeyChecking=no $RPI_USER@$RPI_IP \
        "sudo journalctl -u recorder-agent -f"
fi

print_success "Готово! 🎉"
