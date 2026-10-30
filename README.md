# UNO Bot

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](./LICENSE)

Telegram Bot that allows you to play the popular card game UNO via inline queries. The bot currently runs as [@unobot](http://telegram.me/unobot).

To run the bot yourself, you will need:
- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/), which installs the dependencies ([python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) and [Pony ORM](https://ponyorm.com/))

## Setup
- Get a bot token from [@BotFather](http://telegram.me/BotFather) and change configurations in `config.json`.
- Convert all language files from `.po` files to `.mo` by executing the bash script `compile.sh` located in the `locales` folder.
  Another option is: `find . -maxdepth 2 -type d -name 'LC_MESSAGES' -exec bash -c 'msgfmt {}/unobot.po -o {}/unobot.mo' \;`.
- Use `/setinline` and `/setinlinefeedback` with BotFather for your bot.
- The bot registers its command list with Telegram on every start, so `/setcommands` is not needed. `commandlist.txt` holds the same list for reference.
- Install the dependencies: `uv sync`

You can change some gameplay parameters like turn times, minimum amount of players and default gamemode in `config.json`.
Current gamemodes available: classic, fast, wild and text. Check the details with the `/modes` command.

A chat (or forum topic) holds one game at a time. `/new` over a lobby that has not started replaces it. `/new` over a running game is refused, unless nobody has made a move for `stale_game_timeout` seconds (default 600, 0 disables this) or the caller is the game's creator or a chat admin.

Then run the bot with `uv run bot.py`.

To run the tests: `uv run pytest`.

Code documentation is minimal but there.
