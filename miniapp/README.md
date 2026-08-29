# Lead Radar — Mini App

Telegram Mini App поверх backend'а из `../src/webapp` (см. `../docs/miniapp-brief.md` за полным
контекстом и планом остальных экранов). Первая итерация — один экран: список источников лидов
со статусом здоровья и переключателем вкл/выкл.

## Стек

React 18 + TypeScript, Vite, `@telegram-apps/sdk-react` (мост к Telegram), `@telegram-apps/telegram-ui`
(нативные компоненты, тема подхватывается из Telegram автоматически), TanStack Query (кэш и
инвалидация запросов к API). Тесты — Vitest + Testing Library + MSW (мокает HTTP, не сам fetch).

## Разработка

Бэкенд должен быть поднят отдельно (см. `../README.md` → `MINIAPP_OWNER_TELEGRAM_ID`/`MINIAPP_PORT`
в `.env`, затем `python -m src.webapp.server` или полный `python -m src.main`):

```bash
npm install
npm run dev
```

Vite-прокси (`vite.config.ts`) перенаправляет `/api/*` на `http://127.0.0.1:8765` — порт из
`MINIAPP_PORT` по умолчанию. Открывать вне Telegram можно, но `/api/*` ответит 401 (initData
неоткуда взять) — экран корректно покажет ошибку вместо падения, это ожидаемо.

## Тесты и сборка

```bash
npm test          # vitest run
npm run lint       # oxlint
npm run build      # tsc -b && vite build -> dist/
```

`dist/` отдаётся бэкендом как статика (см. `src/webapp/server.py`), если каталог существует —
собрать фронтенд нужно один раз перед первым продовым запуском бота с Mini App.

## Подключение в Telegram

1. У @BotFather: `/newapp` (или `/setmenubutton` для кнопки в чате) → указать HTTPS-адрес, на
   котором развёрнут бэкенд (нужен туннель для локальной разработки — ngrok, Cloudflare Tunnel;
   для продакшена — обычный TLS-домен).
2. Bot Api не проксирует localhost — без публичного HTTPS-адреса Mini App не откроется из
   настоящего Telegram-клиента, только через `npm run dev` в обычном браузере (с ограничениями
   выше).
