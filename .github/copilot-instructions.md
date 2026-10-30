# Notes for code review

Telegram UNO bot on python-telegram-bot 22 (async) with Pony ORM on SQLite.
Flat module layout, no package. Run the tests with `uv run pytest`.

## Concurrency

- `UnoUpdateProcessor` (`uno_update_processor.py`) serialises updates per
  `(chat_id, thread_id)`. Handlers hold no locks of their own. Code that runs
  outside an update but touches a game (the skip timer in `actions.skip_job`,
  the departure handler `bot.status_update`) takes the same lock with
  `async with update_processor.serialized(key)`.
- One game per `(chat_id, thread_id)`. Every `GameManager` lookup takes a
  `thread_id`; there is no cross-topic fallback. `GameManager` never sends
  messages.
- Inline queries run unlocked. `process_result` therefore checks every chosen
  result with `is_action_allowed` before acting, and the action functions in
  `actions.py` change the game state synchronously and return the messages to
  send. Keep it that way: no `await` between a state change and the end of
  the move.
- `message_thread_id` names a forum topic only when `is_topic_message` is set;
  replies in ordinary supergroups carry it too. Use `topic_id(message)`.
- Inline result ids are `<game_id>:<base_id>:<anti_cheat>` (`result_id.py`).
- Background sends go through `utils.fire_and_forget`. Awaited bot calls that
  must not raise go through `safe_call` or `send_async`.

## Pony ORM

Use `with db_session:` blocks that never span an `await`. Copy what you need
out of the session before awaiting.

## Locales

`internationalization.py` keeps the locale stack in a ContextVar. Enter
locales with the `locale_stack(...)` context manager; `game_locale_stack(game)`
gives a game's languages. New user-facing strings must be added to
`locales/unobot.pot` by running `genpot.sh`.
