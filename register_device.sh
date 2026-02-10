#!/bin/bash
#
# SalesControl Device Registration Script
# Регистрация нового устройства (Raspberry Pi) на Core Server
#
# Использование:
#   bash register_device.sh
#

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
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

print_step "SalesControl - Регистрация нового устройства"

echo "Этот скрипт поможет зарегистрировать новое устройство (Raspberry Pi)"
echo "в системе SalesControl."
echo ""

# Проверка наличия необходимых утилит
if ! command -v uuidgen &> /dev/null; then
    print_error "uuidgen не найден. Установите: sudo apt install uuid-runtime"
    exit 1
fi

if ! command -v curl &> /dev/null; then
    print_error "curl не найден. Установите: sudo apt install curl"
    exit 1
fi

# Запрос параметров
print_info "Введите параметры Core Server:"
read -p "IP-адрес Core Server (например, 130.49.148.227): " CORE_IP
if [[ -z "$CORE_IP" ]]; then
    print_error "IP-адрес обязателен!"
    exit 1
fi

read -p "Логин администратора: " ADMIN_USERNAME
if [[ -z "$ADMIN_USERNAME" ]]; then
    print_error "Логин обязателен!"
    exit 1
fi

read -sp "Пароль администратора: " ADMIN_PASSWORD
echo
if [[ -z "$ADMIN_PASSWORD" ]]; then
    print_error "Пароль обязателен!"
    exit 1
fi

echo ""
print_info "Введите информацию об устройстве (или оставьте пустым для автогенерации):"
echo ""

read -p "Название точки (например, 'Магазин №1'): " POINT_NAME
POINT_NAME=${POINT_NAME:-"Новая точка"}

read -p "Название кассы (например, 'Касса 1'): " REGISTER_NAME
REGISTER_NAME=${REGISTER_NAME:-"Касса 1"}

# Генерация ID и токена
print_step "Генерация ID и токена устройства"

DEVICE_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
POINT_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
REGISTER_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
DEVICE_TOKEN=$(openssl rand -hex 32)

print_info "Сгенерированы:"
echo "  Device ID:    $DEVICE_ID"
echo "  Point ID:     $POINT_ID"
echo "  Register ID:  $REGISTER_ID"
echo "  Device Token: $DEVICE_TOKEN"

# Получение JWT токена
print_step "Аутентификация на сервере"

print_info "Получение JWT токена..."
LOGIN_RESPONSE=$(curl -s -X POST "http://$CORE_IP:8000/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$ADMIN_USERNAME\",\"password\":\"$ADMIN_PASSWORD\"}")

if echo "$LOGIN_RESPONSE" | grep -q "access_token"; then
    JWT_TOKEN=$(echo "$LOGIN_RESPONSE" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)
    print_success "Аутентификация успешна"
else
    print_error "Ошибка аутентификации:"
    echo "$LOGIN_RESPONSE"
    exit 1
fi

# Регистрация устройства
print_step "Регистрация устройства на сервере"

print_info "Отправка запроса на регистрацию..."

REGISTER_RESPONSE=$(curl -s -X POST "http://$CORE_IP:8000/api/v1/admin/devices" \
    -H "Authorization: Bearer $JWT_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
        \"device_id\": \"$DEVICE_ID\",
        \"point_id\": \"$POINT_ID\",
        \"register_id\": \"$REGISTER_ID\",
        \"token\": \"$DEVICE_TOKEN\",
        \"is_enabled\": true
    }")

if echo "$REGISTER_RESPONSE" | grep -q "device_id"; then
    print_success "Устройство успешно зарегистрировано!"
else
    print_error "Ошибка регистрации устройства:"
    echo "$REGISTER_RESPONSE"
    exit 1
fi

# Сохранение конфигурации в файл
print_step "Сохранение конфигурации"

CONFIG_FILE="device_config_$(date +%Y%m%d_%H%M%S).txt"

cat > "$CONFIG_FILE" <<EOF
# SalesControl Device Configuration
# Создано: $(date)
# Точка: $POINT_NAME
# Касса: $REGISTER_NAME

CORE_IP=$CORE_IP
DEVICE_ID=$DEVICE_ID
POINT_ID=$POINT_ID
REGISTER_ID=$REGISTER_ID
DEVICE_TOKEN=$DEVICE_TOKEN

# Для использования в setup_raspberry.sh:
# Скопируйте значения выше при запросе параметров
EOF

print_success "Конфигурация сохранена в файл: $CONFIG_FILE"

# Итоговая информация
print_step "Регистрация завершена!"

echo ""
print_success "Устройство успешно зарегистрировано в системе!"
echo ""
echo "Информация об устройстве:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Core Server IP:  $CORE_IP"
echo "Точка:           $POINT_NAME"
echo "Касса:           $REGISTER_NAME"
echo ""
echo "Device ID:       $DEVICE_ID"
echo "Point ID:        $POINT_ID"
echo "Register ID:     $REGISTER_ID"
echo "Device Token:    $DEVICE_TOKEN"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "ВАЖНО: Сохраните эти данные в надежном месте!"
echo "       Они потребуются для настройки Raspberry Pi."
echo ""
echo "Следующие шаги:"
echo "  1. Скопируйте setup_raspberry.sh на Raspberry Pi"
echo "  2. Запустите на Raspberry Pi: bash setup_raspberry.sh"
echo "  3. Введите параметры выше когда скрипт их запросит"
echo ""
echo "Конфигурация также сохранена в файл: $CONFIG_FILE"
echo ""
