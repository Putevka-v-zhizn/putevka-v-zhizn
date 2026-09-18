# Django Admin

DJANGO_SUPERUSER_USERNAME= # Django superuser login
DJANGO_SUPERUSER_EMAIL=    # Django superuser email
DJANGO_SUPERUSER_PASSWORD= # Django superuser password


# PostgreSQL

POSTGRES_DB=       # Database name
POSTGRES_USER=     # Database user
POSTGRES_PASSWORD= # Database password


# Telegram Bots

TG_TOKEN_ADMIN= # Telegram bot token for staff
TG_TOKEN_USERS= # Telegram bot token for users
TELEGRAM_STAFF_CHAT_IDS='{"developer": 000000000}' # JSON with staff chat ids
TELEGRAM_LOG_CHAT_ID= # Telegram chat id for logs
TG_BOT_USERS_USERNAME= # Telegram username for the users bot
TELEGRAM_SERVICE_TOKEN= # Общий секрет для внутреннего Telegram API Django
TELEGRAM_DJANGO_BASE_URL= # Для telegram-service, например http://web:8000 или https://example.com
TELEGRAM_WORKER_ID=telegram-worker-local-1
TELEGRAM_WORKER_POLLING_INTERVAL=5
TELEGRAM_WORKER_LEASE_SECONDS=120


# Common Settings

DEBUG=false # На сервере обязательно false; для локальной разработки явно задайте DEBUG=true
ALLOWED_HOSTS=localhost,127.0.0.1 # На сервере укажите домен приложения

BASE_URL= # Base app URL, for example https://example.com
CONTACT_EMAIL=talents@putevka-v-zhizn.ru # Shared address for participant questions
APPLICATION_SUBMISSIONS_OPEN=true # Set to false to close final questionnaire submission


# GPT

GPT_TOKEN= # Deprecated for web: OpenAI token should live in the AI worker env. Kept as fallback.
OPENAI_PROXY= # Deprecated.
AI_SERVICE_TOKEN= # Shared secret for Django internal AI API. Must match .env.ai.local.
AI_FILE_TOKEN_MAX_AGE=3600


# ZVONOK

PUBLIC_KEY_CALL=         # Public API key
CAMPAIGN_ID=             # Campaign id
ZVONOK_API_INITIATE_URL= # Call initiation URL
ZVONOK_API_POLLING_URL=  # Call status URL


# Yandex Disk for video business cards

YANDEX_DISK_OAUTH_TOKEN=               # OAuth token for Yandex Disk
YANDEX_DISK_VIDEO_FOLDER=              # Base folder, for example Putevka/VideoBusinessCards
YANDEX_DISK_DOCUMENTS_FOLDER=Админка/документы # Base folder for documents
YANDEX_DISK_TIMEOUT_SECONDS=60         # API metadata timeout
YANDEX_DISK_UPLOAD_TIMEOUT_SECONDS=900 # Large upload timeout
