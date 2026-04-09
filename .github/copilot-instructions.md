# Copilot Code Review Instructions

## Project Overview

Telegram bot for UNO (Mau Mau) in group chats via inline queries. Python 3.11+, python-telegram-bot v22.7 (async API), Pony ORM with SQLite.

## Architecture

Flat structure — all Python source files in the project root. No packages.

| Layer | Files |
|-------|-------|
| Game domain | `game.py`, `player.py`, `card.py`, `deck.py`, `errors.py` |
| State management | `game_manager.py`, `shared_vars.py` |
| Bot integration | `bot.py`, `actions.py`, `results.py`, `settings.py`, `simple_commands.py` |
| Cross-cutting | `internationalization.py`, `utils.py`, `config.py`, `database.py`, `user_setting.py`, `promotions.py` |

## Critical Patterns to Enforce

### Async Handlers
All handler functions must be `async def`. All bot API calls must use `await`.

### Pony ORM + async
`@db_session` decorator must NOT be used on async functions. Use `with db_session:` blocks instead. Sessions must NOT span `await` calls — read data into local variables before awaiting.

```python
# CORRECT
with db_session:
    us = UserSetting.get(id=user.id)
    lang = us.lang if us else 'en'
await send_async(bot, chat_id, text=msg)

# WRONG — db_session spanning await
with db_session:
    us = UserSetting.get(id=user.id)
    await send_async(bot, chat_id, text=us.lang)  # BAD: await inside session
```

### Concurrency Model
`concurrent_updates=True` is enabled. Two locking levels protect shared state:

- **`game.lock`** (`asyncio.Lock` per Game instance) — must be held for all game state mutations in `process_result`, `skip_player`, `skip_job`
- **`gm.get_chat_lock(chat_id)`** (`asyncio.Lock` per chat) — must be held for GameManager operations (`new_game`, `join_game`, `leave_game`, `end_game`, `kick`)

Lock ordering: always chat lock first, then game lock. Never reversed.

Functions in `actions.py` (`do_skip`, `do_play_card`, `do_draw`, `do_call_bluff`) expect the caller to already hold `game.lock`.

### Locale Isolation
`internationalization.py` uses `contextvars.ContextVar` for per-task locale stacks. The `@user_locale` and `@game_locales` decorators use `try/finally` to ensure cleanup. Job queue callbacks must explicitly set locales via `set_locale_stack()`.

### Message Sending
Use `send_async()` from `utils.py` for all bot messages — it handles timeouts and error logging. Always pass `message_thread_id=game.thread_id` (or `update.message.message_thread_id` when no game context) to support forum topics.

### Game.owner
`Game.owner` is an instance-level `list` initialized in `__init__`, NOT a class attribute. Do not move it to class level — mutable class attributes are shared across instances.

## Common Review Pitfalls

- Missing `from pony.orm import db_session` when adding `with db_session:` blocks
- Missing `message_thread_id` parameter on new `send_async` calls
- Using `game.lock` without `async with` (must be `async with game.lock:`)
- Accessing game state after releasing the lock (capture values inside the lock)
- Using `asyncio.get_event_loop()` (deprecated) — use `asyncio.get_running_loop()`
- Forgetting `is_bot=False` in test `User()` constructors (required in v22)

## Testing

`python -m pytest test/` — 24 tests covering game logic, concurrency locks, and locale isolation. Tests do NOT import `shared_vars.py` (which requires a valid bot token for `Application.builder()`).
