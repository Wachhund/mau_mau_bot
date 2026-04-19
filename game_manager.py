#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Telegram bot to play UNO in group chats
# Copyright (c) 2016 Jannes Höke <uno@jhoeke.de>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.


import asyncio
import logging

from game import Game
from player import Player
from errors import (AlreadyJoinedError, GameAlreadyRunningError,
                    LobbyClosedError, NoGameInChatError, NotEnoughPlayersError)
from promotions import send_promotion


class GameManager(object):
    """Owns all running games — keyed by ``(chat_id, thread_id)``.

    Each ``(chat_id, thread_id)`` may host **at most one** active game.
    Concurrency is handled by :class:`uno_update_processor.UnoUpdateProcessor`,
    not in this manager. ``update_processor`` is set from ``shared_vars`` after
    construction so that ``end_game`` can release the matching lock.
    """

    def __init__(self):
        self.chatid_games = dict()        # (chat_id, thread_id) -> Game
        self.games_by_id = dict()         # game.id -> Game
        self.userid_players = dict()
        self.userid_current = dict()
        self.remind_dict = dict()
        self.update_processor = None      # set by shared_vars after wiring

        self.logger = logging.getLogger(__name__)

    def new_game(self, chat, thread_id=None):
        """Create a new game in this chat/topic. Singleton per (chat, topic)."""
        chat_id = chat.id
        key = (chat_id, thread_id)

        existing = self.chatid_games.get(key)
        if existing is not None and existing.players:
            raise GameAlreadyRunningError()

        if existing is not None:
            # An empty stale lobby — drop it before replacing.
            self._forget_game(existing)

        self.logger.debug("Creating new game in chat %s topic %s",
                          chat_id, thread_id)
        game = Game(chat)
        game.thread_id = thread_id

        self.chatid_games[key] = game
        self.games_by_id[game.id] = game
        return game

    def join_game(self, user, chat, thread_id=None):
        """Create a player from the Telegram user and add it to the game."""
        self.logger.info("Joining game with chat id " + str(chat.id))

        game = self.game_for_chat_topic(chat.id, thread_id)
        if game is None:
            # Backwards-friendly: if no exact (chat, topic) game exists but the
            # caller did not specify a thread, fall back to any game in the chat.
            if thread_id is None:
                game = self._any_game_in_chat(chat.id)
            if game is None:
                raise NoGameInChatError()

        if not game.open:
            raise LobbyClosedError()

        if user.id not in self.userid_players:
            self.userid_players[user.id] = list()

        players = self.userid_players[user.id]

        # Don't re-add a player and remove the player from previous games in
        # this chat, if he is in one of them
        for player in players:
            if player in game.players:
                raise AlreadyJoinedError()

        try:
            self.leave_game(user, chat)
        except NoGameInChatError:
            pass
        except NotEnoughPlayersError:
            self.end_game(chat, user)

            if user.id not in self.userid_players:
                self.userid_players[user.id] = list()

            players = self.userid_players[user.id]

        player = Player(game, user)
        if game.started:
            player.draw_first_hand()

        players.append(player)
        self.userid_current[user.id] = player

    def leave_game(self, user, chat):
        """Remove a player from its current game."""

        player = self.player_for_user_in_chat(user, chat)
        players = self.userid_players.get(user.id, list())

        if not player:
            for game in self._games_in_chat(chat.id):
                for p in game.players:
                    if p.user.id == user.id:
                        if p == game.current_player:
                            game.turn()
                        p.leave()
                        return

            raise NoGameInChatError

        game = player.game

        if len(game.players) < 3:
            raise NotEnoughPlayersError()

        if player is game.current_player:
            game.turn()

        player.leave()
        players.remove(player)

        # If this is the selected game, switch to another
        if self.userid_current.get(user.id, None) is player:
            if players:
                self.userid_current[user.id] = players[0]
            else:
                del self.userid_current[user.id]
                del self.userid_players[user.id]

    def end_game(self, chat, user):
        """End a game."""

        self.logger.info("Game in chat " + str(chat.id) + " ended")

        player = self.player_for_user_in_chat(user, chat)
        if not player:
            raise NoGameInChatError

        game = player.game

        try:
            asyncio.get_running_loop().create_task(
                send_promotion(chat, chance=0.15, message_thread_id=game.thread_id))
        except RuntimeError:
            pass

        # Clear all players from the userid maps
        for player_in_game in game.players:
            this_users_players = \
                self.userid_players.get(player_in_game.user.id, list())

            try:
                this_users_players.remove(player_in_game)
            except ValueError:
                pass

            if this_users_players:
                self.userid_current[player_in_game.user.id] = this_users_players[0]
            else:
                self.userid_players.pop(player_in_game.user.id, None)
                self.userid_current.pop(player_in_game.user.id, None)

        self._forget_game(game)

    def game_for_chat_topic(self, chat_id, thread_id):
        """Return the active Game for ``(chat_id, thread_id)`` or ``None``."""
        return self.chatid_games.get((chat_id, thread_id))

    def game_by_id(self, game_id):
        """Return the active Game with the given ``game.id`` or ``None``."""
        return self.games_by_id.get(game_id)

    def player_for_user_in_chat(self, user, chat):
        players = self.userid_players.get(user.id, list())
        for player in players:
            if player.game.chat.id == chat.id:
                return player
        return None

    # -- internal helpers -------------------------------------------------

    def _games_in_chat(self, chat_id):
        """Yield every active game whose chat matches ``chat_id``."""
        for (cid, _tid), game in self.chatid_games.items():
            if cid == chat_id:
                yield game

    def _any_game_in_chat(self, chat_id):
        for game in self._games_in_chat(chat_id):
            return game
        return None

    def _forget_game(self, game):
        """Drop a game from all in-memory indexes and release its lock."""
        key = (game.chat.id, game.thread_id)
        self.chatid_games.pop(key, None)
        self.games_by_id.pop(game.id, None)

        processor = self.update_processor
        if processor is not None:
            try:
                processor.release_key(key)
            except Exception:  # pragma: no cover - defensive
                self.logger.exception("Failed to release processor lock for %s", key)
