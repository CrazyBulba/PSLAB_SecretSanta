# Secret Santa Telegram Bot

**Версия:** 1.13.0

## Структура

- `secret_santa_bot.py` — точка входа
- `messages.py` — все тексты сообщений и подсказок
- `storage.py` — хранение игр (GameManager)
- `handlers.py` — команды и кнопки
- `utils.py` — вспомогательные функции

Тексты уведомлений правятся в `messages.py`.

## Команды

- `/create` — создать игру
- `/mygames` — мои игры
- `/join CODE` — вступить
- `/draw` — розыгрыш
- `/close [all]` — удалить

## Persistence

`games.json` в `/data` (Railway Volume).
