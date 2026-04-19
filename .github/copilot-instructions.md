# Copilot Code Review Instructions

## Project Overview

Telegram bot for UNO (Mau Mau) in group chats via inline queries. Python 3.11+, python-telegram-bot v22.7 (async API), Pony ORM with SQLite.

## Architecture

Flat structure — all Python source files in the project root. No packages.

| Layer | Files |
|-------|-------|
| Game domain | `game.py`, `player.py`, `card.py`, `deck.py`, `errors.py` |
| State management | `game_manager.py`, `shared_vars.py`, `uno_update_processor.py` |
| Result ID encoding | `result_id.py`, `result_id_resolver.py` |
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

### Concurrency Model (UNO-12)
Locking is **centralised** in `UnoUpdateProcessor` (subclass of `telegram.ext.BaseUpdateProcessor` in `uno_update_processor.py`). It serialises updates per `(chat_id, thread_id)` via an internal lock dict. Updates without a derivable chat context (plain `InlineQuery`, polls) run in parallel.

**Handlers must not acquire their own locks.** Do NOT add `async with chat_lock` / `async with game.lock` patterns — they were removed in UNO-12. A single game per `(chat_id, thread_id)` is guaranteed, so the update-level lock covers all handler state mutations.

Functions in `actions.py` (`do_skip`, `do_play_card`, `do_draw`, `do_call_bluff`) run inside the processor lock implicitly; no extra lock is needed.

### Singleton Games
`GameManager.chatid_games` is keyed by `(chat_id, thread_id)` and holds **at most one** active `Game` per key. `GameManager.new_game(chat, thread_id=...)` raises `GameAlreadyRunningError` when the topic already has a game with joined players. Use `gm.game_for_chat_topic(chat_id, thread_id)` or `gm.game_by_id(game_id)` for lookups — never index by `chat.id` alone.

### Inline Result IDs
Every result ID produced in `reply_to_query` is re-encoded via `encode_results_list` (in `result_id.py`) as `<game_id>:<base_id>:<anti_cheat>`. Non-game sentinels (`nogame`, `hand`, `gameinfo`, `mode_*`) get the pseudo game-id `'none'`. `process_result` decodes via `decode_result_id` and resolves game/player via `resolve_result` (`result_id_resolver.py`); dead-game cases send a user-friendly DM.

### Locale Isolation
`internationalization.py` uses `contextvars.ContextVar` for per-task locale stacks. The `@user_locale` and `@game_locales` decorators use `try/finally` to ensure cleanup. Job queue callbacks must explicitly set locales via `set_locale_stack()`.

### Message Sending
Use `send_async()` from `utils.py` for all bot messages — it handles timeouts and error logging. Always pass `message_thread_id=game.thread_id` (or `update.message.message_thread_id` when no game context) to support forum topics.

### Game.owner
`Game.owner` is an instance-level `list` initialised in `__init__`, NOT a class attribute. Do not move it to class level — mutable class attributes are shared across instances.

## Common Review Pitfalls

- Missing `from pony.orm import db_session` when adding `with db_session:` blocks
- Missing `message_thread_id` parameter on new `send_async` calls
- Re-introducing per-handler `async with chat_lock` / `async with game.lock` blocks — locking is owned by `UnoUpdateProcessor`
- Indexing `GameManager.chatid_games` by `chat.id` alone — the key is `(chat.id, thread_id)`
- Hand-rolling inline-result IDs — always go through `encode_results_list` / `decode_result_id`
- Accessing game state across `await` boundaries in ways that assume old locking guarantees (e.g. capturing before dispatch) — still wise, even though the processor serialises per topic
- Using `asyncio.get_event_loop()` (deprecated) — use `asyncio.get_running_loop()`
- Forgetting `is_bot=False` in test `User()` constructors (required in v22)

## Testing

`python -m pytest test/` — covers game logic, UpdateProcessor serialisation, GameManager singleton enforcement, result-ID encoding/decoding, resolver dead-game cases, and locale isolation. Tests do NOT import `shared_vars.py` (which requires a valid bot token for `Application.builder()`).
