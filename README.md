# ALONG (SeatMate)

ALONG — учебный сервис поиска попутчиков: поездки между городами, бронирование
места с четырьмя шагами подтверждения, чат, отзывы, жалобы, обращения
в поддержку и админ-панель. Пользователь может удалить аккаунт вместе
с персональными данными.
Бэкенд — Flask и SQLite, один процесс, без внешних сервисов кроме карт,
геокодера Nominatim и маршрутизатора OSRM (оба необязательны для работы
основных страниц).

## Структура проекта

```
SeatMate/
├─ app/
│  ├─ server.py            # всё приложение: маршруты, миграции, seed, права
│  ├─ mail.py              # отправка писем: SMTP или демо-режим
│  ├─ run_prod.py          # прод-запуск через waitress
│  ├─ along.db             # база SQLite (создаётся при первом запуске)
│  ├─ .secret              # секрет Flask, если не задан ALONG_SECRET_KEY
│  ├─ templates/           # Jinja2-шаблоны (base.html, admin_base.html, …)
│  └─ static/              # styles.css, site.js, home.js, logo.png,
│                          # manifest.webmanifest, icons, videos/*, images/*
├─ scripts/
│  ├─ reset_demo.py        # ротация демо-паролей и чистка мусорных аккаунтов
│  └─ refresh_demo.py      # сдвиг дат демо-поездок и рейсов на ближайшие дни
├─ tests/                  # pytest: conftest.py, test_app.py
├─ requirements.txt        # Flask, waitress
├─ requirements-dev.txt    # + pytest
├─ .env.example            # пример переменных окружения
└─ README.md
```

## Быстрый старт (разработка)

```powershell
cd SeatMate
python -m pip install -r requirements-dev.txt
cd app
python server.py            # http://127.0.0.1:5055, debug выключен
```

При первом запуске создаётся `app/along.db`, схема и демонстрационные данные.
Пароли демо-аккаунтов при создании базы генерируются случайно и один раз
печатаются в консоль (или берутся из `ALONG_ADMIN_PASSWORD` /
`ALONG_USER_PASSWORD`). Сохраните их и смените в рабочем окружении.

Если демонстрационные поездки и рейсы «состарились», их даты можно сдвинуть
на ближайшие дни. Скрипт сначала делает резервную копию базы, одну открытую
поездку оставляет в прошлом для показа завершённых поездок:

```powershell
python scripts/refresh_demo.py --dry-run   # только показать изменения
python scripts/refresh_demo.py             # сдвинуть и сохранить
```

Фоновое видео на главной — сжатая версия `hero-bg-720.mp4` (1280×720, около
3,4 МБ); исходный `hero-bg.mp4` остаётся в проекте без изменений.

## Запуск в продакшене (Windows)

```powershell
cd SeatMate
python -m pip install -r requirements.txt
cd app
$env:ALONG_ENV = "prod"
$env:ALONG_SECRET_KEY = "<длинная случайная строка>"
$env:ALONG_DB = "C:\along-data\along.db"
$env:ALONG_SECURE_COOKIES = "1"      # только если сайт работает по HTTPS
$env:ALONG_BASE_URL = "https://along.example"
python run_prod.py                   # waitress, 0.0.0.0:5055
```

Альтернатива без `run_prod.py`:

```powershell
cd app
waitress-serve --listen=0.0.0.0:5055 server:app
```

`run_prod.py` читает `ALONG_HOST`, `ALONG_PORT`, `ALONG_THREADS`. `debug`
в продакшене не включается нигде. При `ALONG_ENV=prod` cookie сессии
становятся `Secure`, добавляется `Strict-Transport-Security`. Включайте
`ALONG_SECURE_COOKIES=1` только за TLS: по HTTP браузер не передаст
secure-cookie и вход не сработает.

## Переменные окружения

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `ALONG_ENV` | `dev` или `prod` | `dev` |
| `ALONG_SECRET_KEY` | секрет Flask | `app/.secret` (создаётся) |
| `ALONG_DB` | путь к файлу SQLite | `app/along.db` |
| `ALONG_SECURE_COOKIES` | `1` — cookie только по HTTPS | `1` при `prod` |
| `ALONG_BASE_URL` | внешний адрес для ссылок в письмах | адрес запроса |
| `ALONG_ADMIN_PASSWORD` | пароль админа при первичном seed | случайный |
| `ALONG_USER_PASSWORD` | пароль демо-пользователей при seed | случайный |
| `ALONG_SMTP_HOST` | SMTP-сервер; пусто — демо-режим | — |
| `ALONG_SMTP_PORT` | порт SMTP | `587` |
| `ALONG_SMTP_USER` / `ALONG_SMTP_PASSWORD` | логин и пароль SMTP | — |
| `ALONG_SMTP_FROM` | адрес отправителя | `ALONG_SMTP_USER` |
| `ALONG_SMTP_SSL` | `1` — сразу SSL (465), иначе STARTTLS | `0` |
| `ALONG_SUPPORT_EMAIL` | адрес поддержки для формы и писем | `support@along.local` |
| `ALONG_HOST` / `ALONG_PORT` / `ALONG_THREADS` | параметры waitress | `0.0.0.0` / `5055` / `8` |

Если SMTP не задан, регистрация работает в демо-режиме: письмо не уходит,
ссылка подтверждения показывается на странице `/verify` с пометкой
«Демо-режим почты». Когда `ALONG_SMTP_HOST` задан, письмо отправляется,
а токен в интерфейсе не показывается.

## Как создать администратора

1. Зарегистрируйте аккаунт через `/register` и подтвердите почту.
2. В базе назначьте роль:

```powershell
python -c "import sqlite3; c=sqlite3.connect(r'app/along.db'); c.execute(\"UPDATE users SET role='admin', verified=1 WHERE email=?\", ('boss@example.com',)); c.commit()"
```

Либо используйте демо-админа `admin@along.local` (пароль — из консоли
первого запуска или после `scripts/reset_demo.py`).

`scripts/reset_demo.py` идемпотентно меняет пароли `admin@along.local` и
`user@along.local`, удаляет аккаунты `name@example.com` и
`slavikmaddy@gmail.com` (если у них есть поездки — переводит в `blocked`),
чистит их сессии и связанные записи и всегда делает бэкап базы перед
изменениями. Пароли можно задать флагами:

```powershell
python scripts/reset_demo.py --admin-password "<новый>" --user-password "<новой>"
```

## Схема базы данных

13 таблиц, внешние ключи включены на каждом соединении
(`PRAGMA foreign_keys = ON`), для связей созданы индексы.

| Таблица | Назначение | Ключевые связи |
|---|---|---|
| `users` | аккаунты, профиль, роль, статус, статус водителя, кэш рейтинга и числа поездок | — |
| `trips` | опубликованные поездки | `driver_id → users.id` |
| `bookings` | заявки и брони, шаги подтверждения | `trip_id → trips.id`, `passenger_id → users.id` |
| `schedules` | справочник рейсов (автобус/самолёт/поезд), пересадки | — |
| `reviews` | отзывы: один источник истины `target_id` + `text` | `trip_id → trips.id`, `author_id → users.id`, `target_id → users.id` |
| `messages` | личный чат, в том числе по поездке | `sender_id`, `receiver_id → users.id`, `trip_id → trips.id` |
| `complaints` | жалобы пользователей и ответ администратора | `author_id → users.id`, `trip_id → trips.id` |
| `custom_offers` | предложения цены, если рейсов нет | `passenger_id → users.id` |
| `saved_routes` | сохранённые маршруты | `user_id → users.id` |
| `driver_resignations` | заявки водителей на отказ от статуса | `user_id → users.id` |
| `sessions` | серверные сессии (хранится SHA-256 токена) | `user_id → users.id` |
| `login_attempts` | антибрутфорс, чистка старше 24 часов | — |
| `admin_log` | журнал действий администратора | `admin_id → users.id` |

Индексы: `trips(driver_id)`, `trips(status)`, `trips(depart_at)`,
`bookings(trip_id)`, `bookings(passenger_id)`, `messages(sender_id)`,
`messages(receiver_id)`, `messages(trip_id)`, `reviews(target_id)`,
`complaints(status)`, `sessions(user_id)`, `admin_log(created_at)`.

### Обоснование денормализации

`users.rating`, `users.trips_count`, `trips.seats_taken` — кэширующие поля,
нужные для быстрых списков без агрегатных подзапросов. Источник истины:
отзывы, таблица `trips`, строки `bookings` со статусом `confirmed`.
Кэш пересчитывается функцией `refresh_user_stats()` при добавлении и
удалении отзыва, а `seats_taken` меняется в той же транзакции, что и статус
брони (`BEGIN IMMEDIATE` при подтверждении и отмене).

## Матрица ролей

| Действие | Гость | Пользователь | Водитель (approved) | Админ |
|---|---|---|---|---|
| Смотреть главную, поиск, расписание, профили | да | да | да | да |
| Регистрация, вход, подтверждение почты | да | — | — | — |
| Бронировать место, чат, жалоба, отзыв после поездки | — | да | да | да |
| Публиковать поездку | — | — | да | да |
| Заявка на статус водителя, отказ от статуса | — | да | да | да |
| Панель `/admin` и разделы | нет (302 → `/login`) | нет (403) | нет (403) | да |
| Поездки: скрыть/вернуть/правка/экспорт CSV | — | — | — | да |
| Расписание: создать/править/удалить | — | — | — | да |
| Отзывы: поиск, фильтр, удаление | — | — | — | да |
| Пользователи: роль, блокировка, заявки водителей | — | — | — | да |
| Жалобы, журнал действий | — | — | — | да |

Проверки прав выполняются на сервере декораторами `@require_admin`,
`@require_user(verified=True)` и проверками владения записью; скрытие
кнопок в шаблонах — только удобство.

## Защиты

- **SQL-инъекции:** только параметризованные запросы (`?`), динамические
  фрагменты — из фиксированных белых списков.
- **XSS:** автоэкранирование Jinja2, без `|safe` для пользовательских данных,
  в JS используется `textContent`.
- **CSRF:** токен в сессии и в каждом POST (`check_csrf()`), сравнение через
  `hmac.compare_digest`; POST без токена — 400.
- **Пароли:** PBKDF2-HMAC-SHA256, 200 000 итераций, случайная соль,
  сравнение `hmac.compare_digest`.
- **Сессии:** случайный токен, в БД хранится только SHA-256; cookie
  `HttpOnly`, `SameSite=Lax`, опционально `Secure`; срок 8 часов.
- **Брутфорс:** не более 5 неудачных попыток за 10 минут по почте; записи
  старше суток удаляются при входе.
- **Роли:** 12+ маршрутов под `@require_admin`, запрет блокировки себя и
  снятия последнего администратора.
- **Заголовки:** CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options:
  DENY`, `Referrer-Policy`, `Permissions-Policy`, HSTS за TLS.
- **Open redirect:** `safe_next()` пропускает только локальные пути.
- **Ошибки:** кастомные страницы 400/404/500 без трассировок.
- **Файлы:** загружаемых файлов нет; статика отдаётся только из `static/`
  (включая `static/images`). Источники и лицензии фотографий —
  `app/static/images/CREDITS.md` (CC0 / Public Domain).

## Резервное копирование и восстановление

Перед миграциями и скриптами создаётся копия
`app/along.db.bak-YYYYMMDD-HHMMSS`. Вручную:

```powershell
Copy-Item app\along.db "app\along.db.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
```

Восстановление:

```powershell
# остановить приложение
Copy-Item app\along.db.bak-20260101-120000 app\along.db -Force
# удалить остатки WAL, если есть
Remove-Item app\along.db-wal, app\along.db-shm -ErrorAction SilentlyContinue
# запустить приложение: миграции идемпотентны и доведут схему до текущей
python app\run_prod.py
```

Миграции выполняются при старте (`init_db`), проверяют наличие колонок через
`PRAGMA table_info`, поэтому повторный запуск безопасен. Откат схемы —
только восстановлением файла базы из бэкапа.

## Тесты

```powershell
cd SeatMate
python -m pytest -q
```

Тесты работают на временной копии схемы (`tmp_path`), выставляют
`ALONG_DB` до импорта `server.py` и не открывают `app/along.db`. Покрыты:
публичные страницы, security-заголовки, регистрация/вход/выход, доступ в
админку (302 для гостя, 403 для пользователя, 200 для админа), CSRF,
SQLi-пробы, экранирование XSS, публикация поездки только approved-водителем,
полный цикл брони, CRUD расписания и валидация, модерация отзывов, журнал,
канонические колонки `reviews`, индексы и чистка `login_attempts`.

## Протокол ручного тестирования

| Сценарий | Шаги | Ожидаемый результат | Факт |
|---|---|---|---|
| Главная | Открыть `/` | 200, видео и логотип на месте, карта работает | 200 |
| Поиск | `/trips?from=Москва&to=Минск` | 200, найдены рейсы или пустой результат без ошибки | 200 |
| Расписание | `/schedule?mode=bus` | 200, календарь дней и рейсы | 200 |
| Регистрация | `/register` → форма | 302 на `/verify`, в демо-режиме видна ссылка | 302 |
| Подтверждение | Перейти по ссылке `/verify/<token>` | 302, сообщение об успехе | 302 |
| Вход | `/login`, верные данные | 302, в шапке имя, cookie `along_sid` | 302 |
| Выход | Кнопка «Выйти» (POST) | 302, `/me` снова требует вход | 302 |
| Бронь | Открыть поездку → «Отправить заявку» | Статус `clarify`, шаг «Уточнение» | ок |
| Подтверждение брони | Уточнение → согласие водителя → план обеих сторон → «Подтвердить» | Статус `confirmed`, `seats_taken` +1 | ок |
| Публикация поездки | `/trips/new` без статуса водителя | Ошибка «статус водителя не подтвержден» | ок |
| Гость в админке | `/admin` без входа | 302 на `/login?next=/admin` | 302 |
| Пользователь в админке | `/admin` под обычным аккаунтом | 403 | 403 |
| Админ-обзор | `/admin` под админом | 200, график и счётчики | 200 |
| Расписание в админке | `/admin/schedules/new` → создать/править/удалить | 302 и изменения в списке | ок |
| Отзывы | `/admin/reviews` → удалить отзыв | 302, отзыв исчез из `/u/<id>` | ок |
| Журнал | `/admin/log` | 200, записи о действиях | 200 |
| CSRF | POST `/login` без поля `csrf` | 400 | 400 |
| SQLi | `/trips?seats=1' OR '1'='1` | 200, запрос не ломается | 200 |
| XSS | Жалоба с `<script>alert(1)</script>` | В админке текст экранирован | ок |
| Заголовки | `curl -I /` | CSP, nosniff, DENY, Referrer-Policy, Permissions-Policy | ок |
| Статика | `/static/videos/hero-bg.mp4`, `/static/logo.png` | 200; `/static/media/road.mp4` — 404 | ок |

## Лицензия и назначение

Учебный проект. Данные демонстрационные, реальные платежи и перевозки
не выполняются.
