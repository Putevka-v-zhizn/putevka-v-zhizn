---
title: "Деплой"
description: "GitHub Actions workflow, которые используются в проекте."
---

# Деплой

В репозитории используются GitHub Actions для тестов, деплоя beta-сервера, QA-сервера, AI-worker и публикации документации.

## Тесты

Workflow:

```text
.github/workflows/tests.yml
```

Workflow устанавливает Python-зависимости, запускает Django-тесты с coverage и загружает `coverage.xml` как artifact.

## Beta-сервер

Workflow:

```text
.github/workflows/deploy-beta.yml
```

Ветки, которые заканчиваются на `--beta`, деплоятся на beta-сервер. Workflow синхронизирует репозиторий по SSH и запускает стек через Docker Compose.

Нужная конфигурация:

- `BETA_DEPLOY_HOST`
- `BETA_DEPLOY_USER`
- `BETA_DEPLOY_SSH_KEY`
- `BETA_DEPLOY_PATH`
- опционально `BETA_DEPLOY_ENV_FILE`

## QA-сервер

Workflow:

```text
.github/workflows/deploy-qa.yml
```

Ветки, которые заканчиваются на `--qa`, автоматически собираются в GitHub Actions, публикуются в GHCR и деплоятся на окружение `qa`. Этот же workflow можно запустить вручную через `workflow_dispatch`:

- `action=deploy` собирает image, пушит его в GHCR и поднимает сервис на QA-сервере;
- `action=stop` останавливает QA-стек через `docker compose down --remove-orphans`.

QA использует `docker-compose.qa.yml`. В этом compose-файле нет контейнера Postgres: приложение подключается к внешней базе через `DATABASE_URL`. HTTPS и редирект с HTTP обслуживает Caddy. Запросы `/static/*` он обслуживает из собранной Django статики, остальные проксирует в Django-сервис внутри Docker-сети.

`web` выполняет `collectstatic` в `/app/staticfiles`, связанный с папкой `./staticfiles` на сервере. Та же папка подключена к Caddy как `/srv/static` только для чтения. Правило `handle_path /static/*` убирает префикс `/static` перед поиском файла. Пользовательские загрузки из `media` через это правило не публикуются.

При деплое сначала проверяется Caddyfile, затем запускается стек и перезапускается Caddy, чтобы он прочитал новую конфигурацию даже при неизменном образе. Финальная HTTPS-проверка `deploy/qa/check_http.py` проверяет `/admin/login/`, `/static/admin/css/base.css` и `/static/admin/js/core.js`: HTTP 200, правильный Content-Type и непустой ответ. Если проверка не проходит после повторных попыток, workflow завершается ошибкой.

Если нужно применить только исправление раздачи статики к уже работающему QA, синхронизируй обновлённые `docker-compose.qa.yml` и `deploy/qa/Caddyfile`, затем в каталоге QA выполни:

```bash
docker compose --env-file .env -f docker-compose.qa.yml exec -T web python manage.py collectstatic --noinput
docker compose --env-file .env -f docker-compose.qa.yml run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose --env-file .env -f docker-compose.qa.yml up -d --no-deps caddy
docker compose --env-file .env -f docker-compose.qa.yml restart caddy
```

Публичную проверку можно запустить из локального репозитория: `python deploy/qa/check_http.py https://QA_DOMAIN --attempts 1`.

Нужная конфигурация GitHub Environment `qa`:

- `QA_DEPLOY_HOST`
- `QA_DEPLOY_USER`
- `QA_DEPLOY_SSH_KEY`
- `QA_DEPLOY_PATH`
- `QA_DATABASE_URL`
- `QA_DOMAIN`
- опционально `QA_DEPLOY_ENV_FILE`

`QA_DOMAIN` должен указывать DNS A/AAAA-записью на QA-сервер. На сервере должны быть открыты входящие порты `80` и `443`, чтобы Caddy мог выпустить и продлевать Let's Encrypt сертификаты.

`QA_DEPLOY_ENV_FILE` хранит остальные переменные приложения, например `SECRET_KEY`, токены интеграций, `DOZZLE_PORT` и настройки логирования. Workflow всегда дописывает в `.env` значения `DATABASE_URL`, `APP_IMAGE`, `QA_DOMAIN`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` и `BASE_URL`.

Остановка QA-сервиса не удаляет внешнюю БД, локальные media/log/static директории, Docker images и volume с сертификатами Caddy.

### Архитектура QA-контура

QA-контур состоит из нескольких независимых частей:

```text
GitHub Actions
  -> собирает Docker image
  -> публикует image в GHCR
  -> подключается к QA-серверу по SSH
  -> записывает .env
  -> запускает docker-compose.qa.yml

QA-сервер
  -> caddy принимает HTTP/HTTPS на 80/443
  -> caddy выпускает Let's Encrypt сертификат
  -> caddy проксирует запросы в web:8000
  -> web запускает Django-приложение
  -> web подключается к внешнему PostgreSQL через DATABASE_URL

PostgreSQL
  -> не входит в docker-compose.qa.yml
  -> живёт отдельно: managed DB, отдельный сервер или host-level PostgreSQL
```

В `docker-compose.qa.yml` нет сервиса `db`. Это сделано специально: QA-приложение не должно поднимать PostgreSQL-контейнер, а должно получать строку подключения через `QA_DATABASE_URL`.

### Что должно быть готово перед запуском

Перед первым деплоем проверь:

- есть QA-сервер с публичным IP;
- на сервере установлен Docker и Docker Compose plugin;
- на сервере открыты входящие порты `22`, `80`, `443`;
- домен или поддомен указывает на публичный IP QA-сервера;
- PostgreSQL создан и доступен с QA-сервера или из Docker-контейнера;
- в GitHub создан Environment `qa`;
- в Environment `qa` добавлены все обязательные secrets;
- у deploy-пользователя есть доступ к Docker на QA-сервере;
- ветка для автодеплоя заканчивается на `--qa`.

### Как поднять QA-контур

На QA-сервере должны быть установлены Docker и Docker Compose:

```bash
docker --version
docker compose version
```

Если Docker ещё не установлен на Ubuntu, установи его по официальному способу для своей ОС. После установки проверь, что команда `docker compose version` работает именно как Docker Compose plugin, а не только старый бинарник `docker-compose`.

Пользователь, под которым GitHub Actions подключается по SSH, должен иметь право запускать Docker. Обычно его добавляют в группу `docker`:

```bash
sudo usermod -aG docker USER
```

Вместо `USER` укажи значение из GitHub secret `QA_DEPLOY_USER`. Например, если `QA_DEPLOY_USER=deploy`:

```bash
sudo usermod -aG docker deploy
```

После изменения групп нужно завершить старую SSH-сессию и зайти заново. Самый надёжный вариант — перезагрузить сервер:

```bash
sudo reboot
```

После перезахода проверь Docker именно под deploy-пользователем, без `sudo`:

```bash
docker ps
docker compose version
```

Если `docker ps` падает с ошибкой доступа к `/var/run/docker.sock`, GitHub Actions тоже не сможет выполнить deploy.

Открой входящие порты:

```text
22/tcp   SSH
80/tcp   HTTP и выпуск Let's Encrypt сертификата
443/tcp  HTTPS
```

Если firewall управляется через `ufw`:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw status
```

Если на сервере уже установлен nginx, apache, другой Caddy или Traefik, проверь, что они не занимают `80` и `443`:

```bash
sudo ss -tulpn | grep -E ':80|:443'
```

Для QA compose эти порты должен занять контейнер `caddy`. Если порт занят другим сервисом, Caddy не стартует и HTTPS не поднимется.

Создай директорию деплоя:

```bash
sudo mkdir -p /opt/putevka-qa
sudo chown -R $USER:$USER /opt/putevka-qa
```

Значение `/opt/putevka-qa` используется в GitHub secret `QA_DEPLOY_PATH`.

Workflow сам создаст внутри этой директории:

```text
.env
docker-compose.qa.yml
deploy/qa/Caddyfile
media/
staticfiles/
logs/
```

`media`, `staticfiles` и `logs` сохраняются между деплоями и не удаляются при `action=stop`.

### Как поднять PostgreSQL для QA

База QA не поднимается в `docker-compose.qa.yml`. Используй managed PostgreSQL или отдельный PostgreSQL на сервере/отдельной машине.

Рекомендуемые варианты:

- managed PostgreSQL у облачного провайдера: проще для бэкапов, TLS и доступов;
- PostgreSQL на отдельном сервере: удобно, если уже есть инфраструктура;
- PostgreSQL на том же QA-сервере как системный сервис: нормально для небольшого QA-контура;
- PostgreSQL в отдельном compose/контейнере вне `docker-compose.qa.yml`: допустимо, но это уже отдельный контур БД, а не часть app deploy.

Пример установки PostgreSQL на Ubuntu-сервере:

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
```

Создай пользователя и базу:

```bash
sudo -u postgres psql
```

Внутри `psql`:

```sql
CREATE USER putevka_qa WITH PASSWORD 'ЗАМЕНИ_НА_СЛОЖНЫЙ_ПАРОЛЬ';
CREATE DATABASE putevka_qa OWNER putevka_qa;
GRANT ALL PRIVILEGES ON DATABASE putevka_qa TO putevka_qa;
\q
```

Проверь локальное подключение на сервере PostgreSQL:

```bash
psql "postgresql://putevka_qa:ПАРОЛЬ@127.0.0.1:5432/putevka_qa?sslmode=disable"
```

Если PostgreSQL стоит на отдельном сервере или должен принимать подключения не только с `localhost`, настрой `listen_addresses`:

```bash
sudo nano /etc/postgresql/*/main/postgresql.conf
```

Пример:

```conf
listen_addresses = '127.0.0.1,PRIVATE_SERVER_IP'
```

Где `PRIVATE_SERVER_IP` — приватный IP сервера PostgreSQL, если QA-сервер подключается к нему по приватной сети.

И разреши доступ в `pg_hba.conf` только с нужного адреса QA-сервера:

```bash
sudo nano /etc/postgresql/*/main/pg_hba.conf
```

Пример:

```conf
host    putevka_qa    putevka_qa    QA_SERVER_PRIVATE_IP/32    scram-sha-256
```

Если PostgreSQL и Docker находятся на одном сервере, а приложение подключается из контейнера через bridge-сеть, есть два рабочих подхода.

Первый подход — разрешить Docker subnet:

```conf
host    putevka_qa    putevka_qa    172.16.0.0/12    scram-sha-256
```

Второй подход — подключаться к PostgreSQL по IP docker bridge gateway. Его можно посмотреть так:

```bash
ip addr show docker0
```

Обычно это `172.17.0.1`. Тогда `QA_DATABASE_URL` может выглядеть так:

```text
postgresql://putevka_qa:ПАРОЛЬ@172.17.0.1:5432/putevka_qa?sslmode=disable
```

В этом случае PostgreSQL должен слушать этот адрес или все нужные адреса, а `pg_hba.conf` должен разрешать подключение из Docker subnet.

Перезапусти PostgreSQL:

```bash
sudo systemctl restart postgresql
sudo systemctl status postgresql
```

Проверь подключение с того места, откуда будет подключаться приложение. Если проверяешь с QA-сервера:

```bash
psql "postgresql://putevka_qa:ПАРОЛЬ@DB_HOST:5432/putevka_qa?sslmode=disable"
```

Если контейнеры уже запущены, можно проверить из контейнера приложения:

```bash
cd /opt/putevka-qa
docker compose --env-file .env -f docker-compose.qa.yml exec web python manage.py dbshell
```

Итоговое значение `QA_DATABASE_URL`:

```text
postgresql://putevka_qa:ПАРОЛЬ@DB_HOST:5432/putevka_qa?sslmode=disable
```

Если используется managed PostgreSQL с TLS:

```text
postgresql://putevka_qa:ПАРОЛЬ@DB_HOST:5432/putevka_qa?sslmode=require
```

Для QA не используй production-базу. Заведи отдельную базу, отдельного пользователя и отдельный пароль.

### DNS для QA

Для домена вида `qa.example.com` добавь DNS-запись:

```text
Type: A
Name: qa
Value: PUBLIC_IP_QA_SERVER
TTL: 300 или Auto
```

`A` запись указывает домен на IPv4. Если у сервера есть только IPv4, достаточно только этой записи.

Если у сервера есть IPv6, добавь:

```text
Type: AAAA
Name: qa
Value: IPv6_QA_SERVER
TTL: 300 или Auto
```

`AAAA` запись указывает домен на IPv6. Добавляй её только если сервер реально принимает трафик по IPv6 и firewall для IPv6 тоже настроен.

Проверь, что домен указывает на QA-сервер:

```bash
nslookup qa.example.com
```

Дополнительно можно проверить с сервера:

```bash
curl -I http://qa.example.com
```

До первого успешного деплоя ответ может быть ошибкой подключения. Главное, чтобы DNS уже резолвился в IP QA-сервера.

Значение `qa.example.com` нужно записать в GitHub secret `QA_DOMAIN`.

Для Caddy и Let's Encrypt важно:

- `QA_DOMAIN` должен быть публично доступным доменом;
- DNS должен указывать на QA-сервер;
- порты `80` и `443` должны быть открыты снаружи;
- на этих портах не должен слушать другой сервис;
- если домен проксируется через Cloudflare, на первом запуске лучше использовать режим DNS only или корректный TLS mode.

### SSH-ключ для GitHub Actions

Создай ключ:

```bash
ssh-keygen -t ed25519 -C "github-actions-qa-deploy" -f qa_deploy_key
```

Команда создаст два файла:

```text
qa_deploy_key      приватный ключ
qa_deploy_key.pub  публичный ключ
```

Публичный ключ `qa_deploy_key.pub` добавь на QA-сервер в:

```text
~/.ssh/authorized_keys
```

Проверь вход:

```bash
ssh -i qa_deploy_key USER@QA_SERVER_IP
```

Если сервер просит пароль или не пускает, проверь права:

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

Приватный ключ `qa_deploy_key` добавь в GitHub secret `QA_DEPLOY_SSH_KEY`.

Не добавляй публичный ключ в GitHub secret. В GitHub нужен именно приватный ключ, а публичный ключ должен лежать на сервере.

### Secrets для GitHub Environment `qa`

Создай environment `qa` в GitHub:

```text
Repository -> Settings -> Environments -> New environment -> qa
```

Добавь secrets:

```text
QA_DEPLOY_HOST      = IP или hostname QA-сервера
QA_DEPLOY_USER      = SSH user
QA_DEPLOY_SSH_KEY   = приватный ключ qa_deploy_key
QA_DEPLOY_PATH      = /opt/putevka-qa
QA_DATABASE_URL     = postgresql://putevka_qa:ПАРОЛЬ@DB_HOST:5432/putevka_qa?sslmode=disable
QA_DOMAIN           = qa.example.com
```

Назначение secrets:

```text
QA_DEPLOY_HOST      куда GitHub Actions подключается по SSH
QA_DEPLOY_USER      пользователь на QA-сервере
QA_DEPLOY_SSH_KEY   приватный SSH-ключ для этого пользователя
QA_DEPLOY_PATH      директория, где лежит compose и .env
QA_DATABASE_URL     строка подключения к отдельной QA PostgreSQL базе
QA_DOMAIN           публичный домен QA-контура
```

Опциональный secret `QA_DEPLOY_ENV_FILE` хранит остальные переменные приложения:

```env
SECRET_KEY=сложный-django-secret
DEBUG=false
RUN_BACKGROUND_WORKERS=false

TG_TOKEN_ADMIN=
TG_TOKEN_USERS=
TELEGRAM_STAFF_CHAT_IDS={}
TELEGRAM_LOG_CHAT_ID=
TG_BOT_USERS_USERNAME=

YC_EMAIL_USER=
YC_EMAIL_PASSWORD=
DEFAULT_FROM_EMAIL=
CONTACT_EMAIL=talents@putevka-v-zhizn.ru

YANDEX_DISK_OAUTH_TOKEN=
DOZZLE_PORT=8080

DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_EMAIL=admin@example.com
DJANGO_SUPERUSER_PASSWORD=сложный-пароль
```

Не добавляй в `QA_DEPLOY_ENV_FILE` эти значения, workflow запишет их сам:

```env
DATABASE_URL=
APP_IMAGE=
QA_DOMAIN=
ALLOWED_HOSTS=
CSRF_TRUSTED_ORIGINS=
BASE_URL=
```

Если какая-то переменная указана и в `QA_DEPLOY_ENV_FILE`, и дописывается workflow ниже по файлу, итоговое значение будет тем, которое workflow записал последним. Поэтому `DATABASE_URL`, `APP_IMAGE`, `QA_DOMAIN`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` и `BASE_URL` лучше не дублировать.

### GHCR и Docker image

QA workflow собирает image в GitHub Actions и публикует его в GitHub Container Registry:

```text
ghcr.io/<owner>/<repo>:qa-<commit-sha>
ghcr.io/<owner>/<repo>:qa-latest
```

На сервер деплоится SHA-tag:

```text
qa-<commit-sha>
```

Это важно: сервер запускает конкретную сборку, а не случайное состояние ветки.

Workflow логинится в GHCR на QA-сервере перед `docker compose pull`. Для этого используется `GITHUB_TOKEN` текущего workflow. Если package в GHCR приватный и pull не проходит, проверь:

- у workflow есть permission `packages: write`;
- image публикуется в тот же GitHub owner/repo;
- package в GHCR доступен репозиторию;
- в логах нет ошибки `denied`, `unauthorized` или `permission_denied`.

### Запуск и остановка QA

Создай и запушь ветку, которая заканчивается на `--qa`:

```bash
git switch -c feature-something--qa
git push origin feature-something--qa
```

Workflow `Deploy QA` соберёт image, запушит его в GHCR, подключится к серверу по SSH, создаст `.env`, поднимет `web`, `caddy` и `dozzle`. После успешного деплоя сайт должен открыться по HTTPS:

```text
https://qa.example.com
```

HTTP должен редиректиться на HTTPS:

```text
http://qa.example.com -> https://qa.example.com
```

Также deploy можно запустить вручную:

```text
Actions -> Deploy QA -> Run workflow -> action: deploy
```

Чтобы остановить QA:

```text
Actions -> Deploy QA -> Run workflow -> action: stop
```

Остановка выполняет:

```bash
docker compose --env-file .env -f docker-compose.qa.yml down --remove-orphans
```

Она не удаляет volume с сертификатами Caddy, локальные директории `media/`, `staticfiles/`, `logs/`, Docker images и внешнюю PostgreSQL базу.

Проверки на сервере:

```bash
cd /opt/putevka-qa
docker compose --env-file .env -f docker-compose.qa.yml ps
docker compose --env-file .env -f docker-compose.qa.yml logs -f web
docker compose --env-file .env -f docker-compose.qa.yml logs -f caddy
```

Проверка Django:

```bash
docker compose --env-file .env -f docker-compose.qa.yml exec web python manage.py check
```

Проверка HTTPS:

```bash
curl -I http://qa.example.com
curl -I https://qa.example.com
```

Ожидаемо:

- HTTP отвечает редиректом на HTTPS;
- HTTPS открывает приложение;
- в логах `web` нет `DisallowedHost`;
- формы в приложении не падают с CSRF ошибкой;
- в логах `caddy` нет ошибок выпуска сертификата.

### Troubleshooting QA

Если workflow падает на SSH:

- проверь `QA_DEPLOY_HOST`, `QA_DEPLOY_USER`, `QA_DEPLOY_SSH_KEY`;
- проверь, что публичный ключ добавлен в `~/.ssh/authorized_keys`;
- проверь, что сервер доступен по `22/tcp`;
- проверь, что `QA_DEPLOY_USER` может выполнить `docker ps`.

Если workflow падает с ошибкой Docker socket:

```text
permission denied while trying to connect to the Docker daemon socket
```

Это значит, что SSH-пользователь из `QA_DEPLOY_USER` не имеет прав на Docker. Добавь его в группу `docker`:

```bash
sudo usermod -aG docker QA_DEPLOY_USER
sudo reboot
```

После перезагрузки зайди на сервер под этим же пользователем и проверь:

```bash
docker ps
docker compose version
```

Команды должны работать без `sudo`. После этого перезапусти workflow `Deploy QA`.

Если workflow падает на `docker compose pull`:

- проверь, что image появился в GHCR;
- проверь права package в GitHub;
- проверь, что workflow имеет `packages: write`;
- посмотри ошибку авторизации GHCR в логах Actions.

Если Caddy не получает сертификат:

- проверь DNS `QA_DOMAIN`;
- проверь открытость портов `80` и `443`;
- проверь, что другой nginx/apache не занимает эти порты;
- посмотри `docker compose --env-file .env -f docker-compose.qa.yml logs -f caddy`;
- подожди обновления DNS, если запись была создана только что.

Если сайт открывается, но Django возвращает `DisallowedHost`:

- проверь, что `QA_DOMAIN` равен домену без `https://`;
- проверь, что workflow перезаписал `.env`;
- проверь внутри `.env` на сервере значение `ALLOWED_HOSTS`.

Если формы падают с CSRF:

- проверь, что `CSRF_TRUSTED_ORIGINS=https://qa.example.com`;
- проверь, что сайт открывается именно по HTTPS;
- проверь, что браузер не использует старый домен или IP.

Если приложение не подключается к PostgreSQL:

- проверь `QA_DATABASE_URL`;
- проверь доступность `DB_HOST:5432` с QA-сервера;
- проверь `listen_addresses` в PostgreSQL;
- проверь `pg_hba.conf`;
- проверь firewall между QA-сервером и PostgreSQL;
- проверь, что база и пользователь созданы именно для QA.

Если контейнер `web` постоянно рестартится:

- смотри логи `web`;
- проверь обязательные env-переменные в `QA_DEPLOY_ENV_FILE`;
- проверь доступность PostgreSQL;
- проверь, что миграции не падают;
- проверь, что `SECRET_KEY` задан и `DEBUG=false`.

Если `action=stop` не освобождает порты:

- проверь, что остановлен именно workflow `Deploy QA`;
- на сервере выполни `docker ps`;
- если остались старые контейнеры от другого compose project, останови их вручную после проверки.

## AI-worker

Workflow:

```text
.github/workflows/deploy-ai-service.yml
```

Этот workflow запускается вручную и деплоит AI-worker через `docker-compose.ai.yml`.

## Документация

Workflow:

```text
.github/workflows/deploy-docs.yml
```

Workflow документации собирает сайт на Material for MkDocs из `docs/` и публикует результат в GitHub Pages. Поиск строится во время сборки и работает в браузере без внешнего сервиса.

Локальный preview:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-docs.txt
.\.venv\Scripts\python.exe -m mkdocs serve
```
