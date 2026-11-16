"""Isolated importer tests: memory-only DB and no external integrations."""
import os

for name in ('TG_TOKEN_ADMIN', 'TG_TOKEN_USERS', 'TG_TOKEN_MAIL', 'GPT_TOKEN', 'YANDEX_DISK_OAUTH_TOKEN',
             'YC_EMAIL_USER', 'YC_EMAIL_PASSWORD'):
    os.environ[name] = ''
os.environ['TELEGRAM_STAFF_CHAT_IDS'] = '{}'
os.environ['BASE_URL'] = 'http://testserver'

from Putevka.settings import *  # noqa: E402,F403

if 'nto_travel' not in INSTALLED_APPS:
    os.environ['MCP_PROGRAMS'] = 'main,family_income'

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
LOGGING = {'version': 1, 'disable_existing_loggers': True, 'handlers': {'null': {'class': 'logging.NullHandler'}},
           'root': {'handlers': ['null']}}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
