#!/bin/bash
#
# SalesControl Raspberry Pi Setup Script
# Автоматическая настройка recorder-agent на точке продаж
#
# Использование:
#   1. Скопируйте этот скрипт на Raspberry Pi
#   2. Запустите: bash setup_raspberry.sh
#

set -e  # Остановка при ошибках

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Функции для вывода
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_step() {
    echo ""
    echo -e "${GREEN}===================================================${NC}"
    echo -e "${GREEN}$1${NC}"
    echo -e "${GREEN}===================================================${NC}"
    echo ""
}

# Проверка, что скрипт запущен НЕ от root
if [ "$EUID" -eq 0 ]; then
    print_error "Не запускайте скрипт от root! Используйте обычного пользователя (pi)"
    print_info "Скрипт сам запросит sudo когда нужно"
    exit 1
fi

# Проверка, что это действительно Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null && ! grep -q "BCM" /proc/cpuinfo 2>/dev/null; then
    print_warning "Это не похоже на Raspberry Pi. Продолжить? (y/n)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

print_step "SalesControl - Установка Recorder Agent на Raspberry Pi"

echo "Этот скрипт установит и настроит recorder-agent для SalesControl."
echo "Убедитесь, что:"
echo "  - Core Server уже развернут и работает"
echo "  - У вас есть IP-адрес Core Server"
echo "  - Устройство зарегистрировано в системе"
echo ""
read -p "Продолжить? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

# Запрос параметров
print_step "Шаг 1/9: Сбор информации о конфигурации"

echo "Введите параметры подключения:"
echo ""

read -p "IP-адрес Core Server (например, 130.49.148.227): " CORE_IP
if [[ -z "$CORE_IP" ]]; then
    print_error "IP-адрес обязателен!"
    exit 1
fi

read -p "Device ID (UUID): " DEVICE_ID
if [[ -z "$DEVICE_ID" ]]; then
    print_error "Device ID обязателен!"
    exit 1
fi

read -p "Point ID (UUID): " POINT_ID
if [[ -z "$POINT_ID" ]]; then
    print_error "Point ID обязателен!"
    exit 1
fi

read -p "Register ID (UUID): " REGISTER_ID
if [[ -z "$REGISTER_ID" ]]; then
    print_error "Register ID обязателен!"
    exit 1
fi

read -p "Device Token (hex): " DEVICE_TOKEN
if [[ -z "$DEVICE_TOKEN" ]]; then
    print_error "Device Token обязателен!"
    exit 1
fi

echo ""
read -p "Время начала записи (HH:MM, по умолчанию 08:00): " SCHEDULE_START
SCHEDULE_START=${SCHEDULE_START:-08:00}

read -p "Время окончания записи (HH:MM, по умолчанию 22:00): " SCHEDULE_END
SCHEDULE_END=${SCHEDULE_END:-22:00}

print_info "Конфигурация:"
print_info "  Core Server: $CORE_IP"
print_info "  Device ID: $DEVICE_ID"
print_info "  Point ID: $POINT_ID"
print_info "  Register ID: $REGISTER_ID"
print_info "  Расписание: $SCHEDULE_START - $SCHEDULE_END"
echo ""
read -p "Верно? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_error "Настройка отменена"
    exit 1
fi

# Обновление системы
print_step "Шаг 2/9: Обновление системы"

print_info "Обновление списка пакетов..."
sudo apt update

print_info "Установка обновлений..."
sudo DEBIAN_FRONTEND=noninteractive apt upgrade -y

print_success "Система обновлена"

# Установка необходимых пакетов
print_step "Шаг 3/9: Установка необходимых пакетов"

print_info "Установка: python3, pip, ffmpeg, alsa-utils, git..."
sudo apt install -y \
    python3-pip \
    python3-venv \
    ffmpeg \
    alsa-utils \
    git \
    curl \
    uuidgen

print_success "Пакеты установлены"

# Проверка микрофона
print_step "Шаг 4/9: Проверка микрофона"

print_info "Поиск USB микрофонов..."
if arecord -l | grep -q "card"; then
    print_success "Микрофон обнаружен:"
    arecord -l | grep "card"
else
    print_warning "Микрофон не найден!"
    print_info "Убедитесь, что USB-микрофон подключен"
    read -p "Продолжить без микрофона? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Создание директорий
print_step "Шаг 5/9: Создание директорий"

INSTALL_DIR="/opt/recorder-agent"
SPOOL_DIR="/var/lib/recorder-agent/spool"
CONFIG_DIR="/etc/recorder-agent"

print_info "Создание $INSTALL_DIR..."
sudo mkdir -p "$INSTALL_DIR"
sudo chown $USER:$USER "$INSTALL_DIR"

print_info "Создание $SPOOL_DIR..."
sudo mkdir -p "$SPOOL_DIR"/{inbox,outbox,failed}
sudo chown -R $USER:$USER /var/lib/recorder-agent

print_info "Создание $CONFIG_DIR..."
sudo mkdir -p "$CONFIG_DIR"

print_success "Директории созданы"

# Проверка наличия кода recorder_agent
print_step "Шаг 6/9: Установка recorder-agent"

if [ ! -f "$INSTALL_DIR/recorder_agent/__init__.py" ]; then
    print_warning "Код recorder_agent не найден в $INSTALL_DIR"
    print_info "Скопируйте код с помощью rsync:"
    print_info "  На локальной машине выполните:"
    print_info "  rsync -avz /home/petr/PycharmProjects/SalesСontrol/recorder_agent/ pi@<raspberry-pi-ip>:/opt/recorder-agent/"
    echo ""
    read -p "Код уже скопирован? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_error "Сначала скопируйте код recorder_agent"
        exit 1
    fi
fi

# Проверка requirements.txt
if [ ! -f "$INSTALL_DIR/requirements.txt" ]; then
    print_error "Файл requirements.txt не найден!"
    print_info "Убедитесь, что вы скопировали весь код recorder_agent"
    exit 1
fi

# Создание виртуального окружения
print_info "Создание виртуального окружения..."
cd "$INSTALL_DIR"
python3 -m venv venv

print_info "Активация виртуального окружения..."
source venv/bin/activate

print_info "Установка зависимостей..."
pip install --upgrade pip
pip install -r requirements.txt

print_success "Recorder-agent установлен"

# Создание конфигурационного файла
print_step "Шаг 7/9: Создание конфигурации"

CONFIG_FILE="$CONFIG_DIR/config.yaml"

print_info "Создание $CONFIG_FILE..."
sudo tee "$CONFIG_FILE" > /dev/null <<EOF
# SalesControl Recorder Agent Configuration
# Generated: $(date)

# Идентификация устройства
device_id: "$DEVICE_ID"
point_id: "$POINT_ID"
register_id: "$REGISTER_ID"

# Сервер
server:
  url: "http://$CORE_IP:8000"
  token: "$DEVICE_TOKEN"
  timeout_sec: 30
  retry_initial_sec: 2
  retry_max_sec: 300

# Запись
recording:
  schedule_start: "$SCHEDULE_START"
  schedule_end: "$SCHEDULE_END"
  chunk_duration_sec: 60
  codec: "opus"
  bitrate: "24k"
  sample_rate: 16000
  channels: 1

# Хранилище
storage:
  spool_dir: "$SPOOL_DIR"
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
EOF

sudo chmod 644 "$CONFIG_FILE"

print_success "Конфигурация создана: $CONFIG_FILE"

# Создание systemd сервиса
print_step "Шаг 8/9: Создание systemd сервиса"

SERVICE_FILE="/etc/systemd/system/recorder-agent.service"

print_info "Создание $SERVICE_FILE..."
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=SalesControl Recorder Agent
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$INSTALL_DIR/venv/bin/python -m recorder_agent
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
EOF

print_info "Перезагрузка systemd..."
sudo systemctl daemon-reload

print_info "Включение автозапуска..."
sudo systemctl enable recorder-agent

print_success "Systemd сервис создан"

# Запуск сервиса
print_step "Шаг 9/9: Запуск recorder-agent"

print_info "Запуск сервиса..."
sudo systemctl start recorder-agent

sleep 2

print_info "Проверка статуса..."
if sudo systemctl is-active --quiet recorder-agent; then
    print_success "Сервис запущен успешно!"
else
    print_error "Сервис не запустился. Проверьте логи:"
    print_info "  sudo journalctl -u recorder-agent -n 50"
    exit 1
fi

# Проверка работы
print_step "Проверка работоспособности"

echo ""
print_info "1. Проверка health check..."
sleep 2
if curl -s http://localhost:8042/health > /dev/null 2>&1; then
    print_success "Health check работает"
else
    print_warning "Health check не отвечает (может быть еще не запустился)"
fi

echo ""
print_info "2. Проверка подключения к серверу..."
if curl -s -I "http://$CORE_IP:8000/health" | grep -q "200 OK"; then
    print_success "Core Server доступен"
else
    print_warning "Core Server недоступен. Проверьте сеть и IP-адрес"
fi

echo ""
print_info "3. Просмотр последних логов..."
sudo journalctl -u recorder-agent -n 20 --no-pager

# Итоговая информация
print_step "Установка завершена!"

echo ""
print_success "Recorder Agent успешно установлен и запущен!"
echo ""
echo "Конфигурация:"
echo "  - Установлен в: $INSTALL_DIR"
echo "  - Конфигурация: $CONFIG_FILE"
echo "  - Директория spool: $SPOOL_DIR"
echo "  - Systemd сервис: recorder-agent.service"
echo ""
echo "Полезные команды:"
echo "  Статус сервиса:    sudo systemctl status recorder-agent"
echo "  Просмотр логов:    sudo journalctl -u recorder-agent -f"
echo "  Перезапуск:        sudo systemctl restart recorder-agent"
echo "  Остановка:         sudo systemctl stop recorder-agent"
echo "  Health check:      curl http://localhost:8042/health"
echo "  Проверка файлов:   ls -lh $SPOOL_DIR/outbox/"
echo ""
echo "Проверьте Dashboard по адресу: http://$CORE_IP:8080"
echo "Через несколько минут должны начать появляться диалоги."
echo ""

print_info "Показать логи в реальном времени? (y/n)"
read -p "" -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo journalctl -u recorder-agent -f
fi
