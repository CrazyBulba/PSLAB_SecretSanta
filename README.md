# Secret Santa Telegram Bot

**Версия:** 1.9.0

Конверсационные команды: бот спрашивает текст, следующее сообщение пользователя принимается как ответ.

## Как работает

- `/create` — бот спросит вступительное. Отправьте текст или «пропустить».
- `/setintro` — спрашивает вступительный текст.
- `/setwish` — спрашивает пожелания.
- `/import_previous` — спрашивает список пар.

Можно по-прежнему передать аргумент сразу: `/setintro Текст здесь`.

## Основные команды

- `/create` — создать игру
- `/setintro` — вступительное
- `/join CODE` — вступить
- `/mygames` — список игр
- `/setwish` — пожелания
- `/participants` — участники
- `/draw` — розыгрыш
- `/export` — экспорт пар
- `/close [all]` — закрыть
- `/avoid on|off`
- `/import_previous`
- `/import_from OLDCODE`
- `/myresult`
- `/info`

## Persistence

`games.json` в `/data` (Railway Volume).
