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


import logging

from apscheduler.jobstores.base import JobLookupError

from game import Game
from player import Player
from errors import (AlreadyJoinedError, DeckEmptyError, GameAlreadyRunningError,
                    LobbyClosedError, NoGameInChatError, NotEnoughPlayersError)


class GameManager(object):
    """Owns all running games.

    Each ``(chat_id, thread_id)`` hosts at most one game. Every lookup takes an
    explicit ``thread_id``; there is no cross-topic fallback. Concurrency is
    handled by :class:`uno_update_processor.UnoUpdateProcessor`, not here,
    and nothing in here sends messages.
    """

    def __init__(self):
        self.chatid_games = dict()        # chat_id -> {thread_id: Game}
        self.games_by_id = dict()         # game.id -> Game
        self.userid_players = dict()      # user_id -> [Player]
        self.userid_current = dict()      # user_id -> Player
        self.remind_dict = dict()         # chat_id -> {user_id}

        self.logger = logging.getLogger(__name__)

    def new_game(self, chat, thread_id=None):
        """Create a new game in this chat/topic. Singleton per (chat, topic)."""
        existing = self.game_for_chat_topic(chat.id, thread_id)
        if existing is not None and existing.players:
            raise GameAlreadyRunningError()

        if existing is not None:
            # An empty stale lobby: drop it before replacing.
            self._forget_game(existing)

        self.logger.debug("Creating new game in chat %s topic %s",
                          chat.id, thread_id)
        game = Game(chat)
        game.thread_id = thread_id

        self.chatid_games.setdefault(chat.id, dict())[thread_id] = game
        self.games_by_id[game.id] = game
        return game

    def join_game(self, user, chat, thread_id=None):
        """Add a player to the game in this ``(chat, thread_id)``."""
        self.logger.info("Joining game in chat %s topic %s", chat.id, thread_id)

        game = self.game_for_chat_topic(chat.id, thread_id)
        if game is None:
            raise NoGameInChatError()

        if not game.open:
            raise LobbyClosedError()

        if self.player_for_user_in_chat(user, chat, thread_id=thread_id):
            raise AlreadyJoinedError()

        player = Player(game, user)
        if game.started:
            try:
                player.draw_first_hand()
            except DeckEmptyError:
                player.leave()
                raise

        self.userid_players.setdefault(user.id, list()).append(player)
        self.userid_current[user.id] = player

    def leave_game(self, user, chat, thread_id=None):
        """Remove a player from the game in this ``(chat, thread_id)``.

        Raises :class:`NoGameInChatError` if the user is not playing in that
        topic and :class:`NotEnoughPlayersError` if the game could not go on
        without them (the caller decides whether to end it).
        """
        player = self.player_for_user_in_chat(user, chat, thread_id=thread_id)
        if player is None:
            raise NoGameInChatError()

        game = player.game

        if len(game.players) < 3:
            raise NotEnoughPlayersError()

        if player is game.current_player:
            game.turn()

        player.leave()
        self._drop_player(player)

    def end_game(self, game):
        """End ``game``: forget it and drop its players from the user indexes.

        Safe to call for a game that has already ended."""
        self.logger.info("Game %s in chat %s ended", game.id, game.chat.id)

        for player in game.players:
            self._drop_player(player)

        if game.job is not None:
            try:
                game.job.schedule_removal()
            except JobLookupError:
                pass  # already fired
            game.job = None

        self._forget_game(game)

    def game_for_chat_topic(self, chat_id, thread_id):
        """Return the active Game for ``(chat_id, thread_id)`` or ``None``."""
        return self.chatid_games.get(chat_id, dict()).get(thread_id)

    def games_in_chat(self, chat_id):
        """Return every active game in ``chat_id``, one per topic."""
        return list(self.chatid_games.get(chat_id, dict()).values())

    def game_by_id(self, game_id):
        """Return the active Game with the given ``game.id`` or ``None``."""
        return self.games_by_id.get(game_id)

    def player_for_user_in_chat(self, user, chat, thread_id=None):
        """Return the ``Player`` for ``user`` in the ``(chat, thread_id)`` game.

        Returns ``None`` if the user is not in that specific game, even if
        they are playing in a different topic of the same chat.
        """
        game = self.game_for_chat_topic(chat.id, thread_id)
        if game is None:
            return None
        for player in game.players:
            if player.user.id == user.id:
                return player
        return None

    # -- internal helpers -------------------------------------------------

    def _drop_player(self, player):
        """Remove ``player`` from the per-user indexes."""
        user_id = player.user.id
        players = self.userid_players.get(user_id, list())
        try:
            players.remove(player)
        except ValueError:
            pass

        if self.userid_current.get(user_id) is player:
            if players:
                self.userid_current[user_id] = players[0]
            else:
                self.userid_current.pop(user_id, None)

        if not players:
            self.userid_players.pop(user_id, None)

    def _forget_game(self, game):
        """Drop a game from the game indexes."""
        topics = self.chatid_games.get(game.chat.id)
        if topics is not None and topics.get(game.thread_id) is game:
            del topics[game.thread_id]
            if not topics:
                del self.chatid_games[game.chat.id]
        self.games_by_id.pop(game.id, None)
