#!/bin/bash
set -e

echo "[orochi] Running migrations..."
python manage.py migrate --noinput

echo "[orochi] Collecting static files..."
python manage.py collectstatic --noinput

# Create superuser if DJANGO_SUPERUSER_PASSWORD is set and user doesn't exist
if [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='${DJANGO_SUPERUSER_USERNAME:-admin}').exists():
    User.objects.create_superuser('${DJANGO_SUPERUSER_USERNAME:-admin}', '${DJANGO_SUPERUSER_EMAIL:-admin@orochi.local}', '$DJANGO_SUPERUSER_PASSWORD')
    print('[orochi] Created superuser: ${DJANGO_SUPERUSER_USERNAME:-admin}')
else:
    print('[orochi] Superuser already exists')
"
fi

echo "[orochi] Starting Daphne ASGI server on 0.0.0.0:8559 (http-timeout 120s)..."
exec daphne -b 0.0.0.0 -p 8559 --http-timeout 120 --websocket-timeout -1 orochi.asgi:application
