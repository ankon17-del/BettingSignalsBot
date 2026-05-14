# Betting Signals Bot MVP

Telegram-бот для аналитических betting-сигналов, ведения банкролла и статистики. MVP не делает автоматические ставки, не логинится в букмекерские аккаунты, не обходит капчи или антибот-защиту. Пользователь всегда принимает решение вручную.

## Возможности MVP

- Telegram-бот на `aiogram 3.x`.
- PostgreSQL через `SQLAlchemy async` и `asyncpg`.
- Alembic-миграция для таблиц `users`, `signals`, `news_items`, `signal_news_links`, `bankroll_history`.
- Команды `/start`, `/help`, `/bankroll`, `/set_bankroll`, `/set_unit`, `/risk_profile`, `/signals`, `/stats`.
- Админ-команда `/add_test_signal`, которая создает демо VALUE-сигнал.
- Inline-кнопки закрытия сигнала: `Зашло`, `Не зашло`, `Возврат`.
- Автоматический пересчет P/L, bankroll, ROI, winrate и max drawdown.
- Заготовки модулей для odds/stats/news collectors, Poisson-модели, value detector, risk adjuster и backtest.

## Структура

```text
app/
  bot/
  collectors/
  engine/
  db/
  services/
  config.py
  main.py
alembic/
.env.example
requirements.txt
Procfile
railway.json
```

## Переменные окружения

```env
BOT_TOKEN=
DATABASE_URL=
ADMIN_USER_ID=
DEFAULT_BANKROLL=10000
DEFAULT_RISK_PROFILE=normal
DEFAULT_UNIT_PERCENT=1.0
OLIMP_ENABLED=false
OLIMP_PUBLIC_LINE_URL=
OLIMP_TIMEOUT_SECONDS=10
OLIMP_SPORT=football
```

`DATABASE_URL` можно указывать в формате Railway/Postgres `postgresql://...`; приложение автоматически преобразует его в async URL для `asyncpg`.

## OLIMP integration prep

В проект уже заложен отдельный конфиг под открытые коэффициенты БК ОЛИМП:

```env
OLIMP_ENABLED=false
OLIMP_PUBLIC_LINE_URL=
OLIMP_TIMEOUT_SECONDS=10
OLIMP_SPORT=football
```

Это подготовка именно под открытые данные линии: без логина, без аккаунта БК и без любых автоматических ставок. Следующий этап для OLIMP:

- зафиксировать стабильный публичный endpoint линии;
- описать схему ответа;
- нормализовать рынки OLIMP в общий формат бота;
- передать коэффициенты в value engine.

## Локальный запуск

1. Создайте виртуальное окружение:

```bash
python -m venv .venv
```

2. Активируйте его и установите зависимости:

```bash
pip install -r requirements.txt
```

3. Скопируйте `.env.example` в `.env` и заполните значения.

4. Примените миграции:

```bash
alembic upgrade head
```

5. Запустите worker:

```bash
python -m app.main
```

## Как создать Telegram-бота

1. Откройте Telegram и найдите `@BotFather`.
2. Выполните команду `/newbot`.
3. Укажите имя и username бота.
4. BotFather выдаст token. Запишите его в переменную `BOT_TOKEN`.
5. Узнайте свой Telegram user id через `@userinfobot` или аналогичный бот и запишите в `ADMIN_USER_ID`.

Админские команды, например `/add_test_signal`, будут доступны только этому пользователю.

## Деплой GitHub -> Railway -> PostgreSQL -> Telegram

1. Создайте репозиторий на GitHub.
2. Добавьте проект и отправьте код:

```bash
git init
git add .
git commit -m "Initial Betting Signals Bot MVP"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```

3. В Railway создайте новый проект и выберите `Deploy from GitHub repo`.
4. Подключите репозиторий.
5. Добавьте PostgreSQL через `New -> Database -> PostgreSQL`.
6. В сервисе worker добавьте переменные:
   - `BOT_TOKEN`
   - `DATABASE_URL` из Railway PostgreSQL
   - `ADMIN_USER_ID`
   - `DEFAULT_BANKROLL`
   - `DEFAULT_RISK_PROFILE`
   - `DEFAULT_UNIT_PERCENT`
7. Railway запустит worker командой из `railway.json`:

```bash
python -m app.main
```

8. Выполните миграции в Railway shell:

```bash
alembic upgrade head
```

9. Откройте Telegram-бота и проверьте:
   - `/start`
   - `/set_bankroll 100000`
   - `/add_test_signal`
   - закрытие сигнала кнопками
   - `/stats`

## Команды

- `/start` - приветствие и главное меню.
- `/help` - справка и предупреждение о рисках.
- `/bankroll` - текущий bankroll, unit, risk profile и P/L.
- `/set_bankroll 100000` - установить текущий bankroll.
- `/set_unit 1` - установить базовый размер unit в процентах.
- `/risk_profile` - выбрать `conservative`, `normal`, `aggressive`.
- `/signals` - последние активные сигналы.
- `/stats` - статистика.
- `/stats league=Premier League risk=medium month=2026-05` - пример фильтров.
- `/add_test_signal` - создать демо-сигнал, только для `ADMIN_USER_ID`.

## Логика ставок и статистики

Бот рекомендует размер ставки как процент от текущего bankroll:

```text
recommended_stake = current_bankroll * stake_percent / 100
```

Профили риска:

```text
conservative: weak 0.25%, normal 0.5%, strong 1%
normal:       weak 0.5%,  normal 1%,   strong 1.5%
aggressive:  weak 1%,    normal 2%,   strong 3%
```

Если `risk_level = high`, ставка ограничивается максимумом `0.5%`, а в сигнале показывается предупреждение: лучше пропустить или снизить размер.

После фиксации исхода:

```text
won:  profit = recommended_stake * (odds - 1)
lost: profit = -recommended_stake
void: profit = 0
```

ROI считается так:

```text
ROI = total_profit / total_staked * 100
```

Value:

```text
bookmaker_probability = 1 / odds
value_percent = (model_probability - bookmaker_probability) * 100
```

Сигнал считается VALUE, если `value_percent >= 5`, `model_probability > bookmaker_probability`, `odds >= 1.40`, `risk_level != high`.

## Следующий этап

Poisson-модель пока заглушка. Следующий этап:

- загрузка статистики матчей;
- расчет `attack_strength`;
- расчет `defense_strength`;
- expected goals;
- вероятности счета;
- вероятность ТБ/ТМ 2.5;
- сравнение с коэффициентами;
- генерация VALUE-сигнала.

Инфополе также заложено архитектурно через `news_items` и `signal_news_links`, но реальные парсеры пока не подключены.

## Ограничения

Проект предназначен только для аналитики. Он не ставит автоматически, не подключается к аккаунтам букмекеров, не обходит ограничения сайтов и не гарантирует прибыль. Ставки связаны с финансовым риском.
