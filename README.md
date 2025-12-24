# MAX → Telegram bridge (PyMax + __oneme_auth)

Минимальный сервис, который забирает сообщения из выбранных чатов MAX через WebSocket (PyMax) и пересылает их в Telegram пользователям, подписанным через бота.

## Что есть
- Авторизация через `__oneme_auth` (env `MAX_TOKEN`) в PyMax с `device_type=WEB`.
- Каталог MAX-групп из `config/groups.yaml`, подписки через меню бота.
- Отправка текста (HTML) с пометкой группы и временем, попытка подтянуть имя отправителя.
- Фото / файлы / видео через скачивание и отправку в Telegram.
- Хранение оффсета по каждому чату в `data/state.json`.
- Стартовая подгрузка последних `STARTUP_HISTORY` сообщений, если оффсета нет.
- Dockerfile + docker-compose для быстрого запуска.

## Конфигурация
1) Скопируйте `.env.example` → `.env` и заполните:
```
MAX_TOKEN=значение token из __oneme_auth
MAX_PHONE=+7XXXXXXXXXX   # номер аккаунта, нужен PyMax
TG_TOKEN=токен бота от @BotFather
MAX_APP_VERSION=25.12.13  # можно оставить дефолт
CONFIG_PATH=config/groups.yaml
STATE_PATH=data/state.json
MAX_WORK_DIR=.max_session
LOG_LEVEL=INFO
STARTUP_HISTORY=3
ADMIN_CHAT_ID=449962608
SUBSCRIBERS_PATH=data/subscribers.json
CATALOG_PATH=data/catalog.json
```
2) Создайте `config/groups.yaml` (или скопируйте шаблон `config.example/groups.yaml`) и заполните:
```yaml
routes:
  - max_chat_id: -123456789   # id чата в MAX
```
   При первом запуске контейнера, если файла нет, он будет создан с шаблоном; заполните и перезапустите.

Пользователи подписываются на группы через бота `/start`, админ получает уведомления о подписках и управляет каталогом через меню.

## Запуск
```bash
docker compose up --build
```

Состояние (`data/state.json`) и сессия PyMax (`max_session/`) сохраняются на хосте, чтобы не терять оффсеты/логин.

## Примечания
- PyMax требует телефон в формате `+7...`; он не используется для вызова, но нужен для инициализации клиента.
- Если `MAX_TOKEN` перестанет работать, PyMax можно залогинить по номеру/QR (пока не реализовано).
- Загрузка файлов/видео идёт по URL, если MAX отдаёт приватные ссылки, может потребоваться добавить заголовки авторизации в `fetch_bytes`.
