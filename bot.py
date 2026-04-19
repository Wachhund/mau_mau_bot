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
from datetime import datetime

from telegram import BotCommand, InlineKeyboardMarkup, \
    InlineKeyboardButton, InlineQueryResultsButton, Update
from telegram.constants import ParseMode
from telegram.ext import InlineQueryHandler, ChosenInlineResultHandler, \
    CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

import card as c
import settings
import simple_commands
from actions import do_skip, do_play_card, do_draw, do_call_bluff, start_player_countdown
from config import WAITING_TIME, DEFAULT_GAMEMODE, MIN_PLAYERS
from errors import (AlreadyJoinedError, DeckEmptyError, GameAlreadyRunningError,
                    LobbyClosedError, NoGameInChatError, NotEnoughPlayersError)
from internationalization import _, __, user_locale, game_locales
from result_id import (PSEUDO_GAME_ID, decode_result_id, encode_results_list)
from result_id_resolver import (DEAD_NO_CURRENT_GAME, DEAD_NOT_A_PLAYER,
                                DEAD_UNKNOWN_GAME, resolve_result)
from results import (add_call_bluff, add_choose_color, add_draw, add_gameinfo,
                     add_no_game, add_not_started, add_other_cards, add_pass,
                     add_card, add_mode_classic, add_mode_fast, add_mode_wild, add_mode_text)
from shared_vars import gm, application
from simple_commands import help_handler
from start_bot import start_bot
from utils import display_name
from utils import send_async, answer_async, error, TIMEOUT, user_is_creator_or_admin, user_is_creator, game_is_running


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logging.getLogger('apscheduler').setLevel(logging.WARNING)


def get_thread_id(update):
    """Extract message_thread_id from an update, or None"""
    if update.message:
        return update.message.message_thread_id
    return None


def _game_in_chat(chat_id, thread_id):
    """Resolve the active game in this (chat, thread). Falls back to any game
    in the same chat when thread_id is None — this preserves previous UX where
    /kill from the General channel could close a topic-bound game."""
    game = gm.game_for_chat_topic(chat_id, thread_id)
    if game is not None:
        return game
    if thread_id is None:
        return gm._any_game_in_chat(chat_id)
    return None


def _resolve_game_id(game_id):
    """Resolver for UnoUpdateProcessor: maps game.id back to (chat_id, thread_id)."""
    game = gm.game_by_id(game_id)
    if game is None:
        return None
    return (game.chat.id, game.thread_id)


@user_locale
async def notify_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /notify_me command, pm people for next game"""
    chat_id = update.message.chat_id
    if update.message.chat.type == 'private':
        await send_async(context.bot,
                   chat_id,
                   text=_("Send this command in a group to be notified "
                          "when a new game is started there."))
    else:
        try:
            gm.remind_dict[chat_id].add(update.message.from_user.id)
        except KeyError:
            gm.remind_dict[chat_id] = {update.message.from_user.id}


@user_locale
async def new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /new command"""
    chat_id = update.message.chat_id
    thread_id = get_thread_id(update)

    if update.message.chat.type == 'private':
        await help_handler(update, context)

    else:
        # Collect reminders before locking (send after lock release)
        remind_users = None
        if update.message.chat_id in gm.remind_dict:
            remind_users = list(gm.remind_dict[update.message.chat_id])
            del gm.remind_dict[update.message.chat_id]

        try:
            game = gm.new_game(update.message.chat, thread_id=thread_id)
        except GameAlreadyRunningError:
            await send_async(context.bot, chat_id,
                       text=_("There is already a game in this chat. "
                              "End it with /kill before starting a new one."),
                       message_thread_id=thread_id)
            return
        game.starter = update.message.from_user
        game.owner.append(update.message.from_user.id)
        game.mode = DEFAULT_GAMEMODE

        if remind_users:
            for user in remind_users:
                await send_async(context.bot,
                           user,
                           text=_("A new game has been started in {title}").format(
                                title=update.message.chat.title))

        await send_async(context.bot, chat_id,
                   text=_("Created a new game! Join the game with /join "
                          "and start the game with /start"),
                   message_thread_id=thread_id)


@user_locale
async def kill_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /kill command"""
    chat = update.message.chat
    user = update.message.from_user
    thread_id = get_thread_id(update)
    game = _game_in_chat(chat.id, thread_id)

    if update.message.chat.type == 'private':
        await help_handler(update, context)
        return

    if game is None:
        await send_async(context.bot, chat.id,
                   text=_("There is no running game in this chat."),
                   message_thread_id=thread_id)
        return

    if await user_is_creator_or_admin(user, game, context.bot, chat):
        try:
            gm.end_game(chat, user)
            await send_async(context.bot, chat.id, text=__("Game ended!", multi=game.translate),
                       message_thread_id=game.thread_id)

        except NoGameInChatError:
            await send_async(context.bot, chat.id,
                       text=_("The game is not started yet. "
                              "Join the game with /join and start the game with /start"),
                       reply_to_message_id=update.message.message_id,
                       message_thread_id=game.thread_id)

    else:
        await send_async(context.bot, chat.id,
                  text=_("Only the game creator ({name}) and admin can do that.")
                  .format(name=game.starter.first_name),
                  reply_to_message_id=update.message.message_id,
                  message_thread_id=game.thread_id)

@user_locale
async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /join command"""
    chat = update.message.chat
    thread_id = get_thread_id(update)

    if update.message.chat.type == 'private':
        await help_handler(update, context)
        return

    try:
        gm.join_game(update.message.from_user, chat, thread_id=thread_id)

    except LobbyClosedError:
        game = _game_in_chat(chat.id, thread_id)
        await send_async(context.bot, chat.id, text=_("The lobby is closed"),
                   message_thread_id=game.thread_id if game else thread_id)
        return

    except NoGameInChatError:
        await send_async(context.bot, chat.id,
                   text=_("No game is running at the moment. "
                          "Create a new game with /new"),
                   reply_to_message_id=update.message.message_id,
                   message_thread_id=thread_id)
        return

    except AlreadyJoinedError:
        game = _game_in_chat(chat.id, thread_id)
        await send_async(context.bot, chat.id,
                   text=_("You already joined the game. Start the game "
                          "with /start"),
                   reply_to_message_id=update.message.message_id,
                   message_thread_id=game.thread_id if game else thread_id)
        return

    except DeckEmptyError:
        game = _game_in_chat(chat.id, thread_id)
        await send_async(context.bot, chat.id,
                   text=_("There are not enough cards left in the deck for "
                          "new players to join."),
                   reply_to_message_id=update.message.message_id,
                   message_thread_id=game.thread_id if game else thread_id)
        return

    # Success — get the game the player just joined
    player = gm.player_for_user_in_chat(update.message.from_user, chat)
    game_thread = player.game.thread_id if player else thread_id
    await send_async(context.bot, chat.id,
               text=_("Joined the game"),
               reply_to_message_id=update.message.message_id,
               message_thread_id=game_thread)


@user_locale
async def leave_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /leave command"""
    chat = update.message.chat
    user = update.message.from_user

    player = gm.player_for_user_in_chat(user, chat)

    if player is None:
        await send_async(context.bot, chat.id, text=_("You are not playing in a game in "
                                        "this group."),
                   reply_to_message_id=update.message.message_id,
                   message_thread_id=get_thread_id(update))
        return

    game = player.game

    try:
        gm.leave_game(user, chat)

    except NoGameInChatError:
        await send_async(context.bot, chat.id, text=_("You are not playing in a game in "
                                        "this group."),
                   reply_to_message_id=update.message.message_id,
                   message_thread_id=game.thread_id)
        return

    except NotEnoughPlayersError:
        gm.end_game(chat, user)
        await send_async(context.bot, chat.id, text=__("Game ended!", multi=game.translate),
                   message_thread_id=game.thread_id)
        return

    if game.started:
        await send_async(context.bot, chat.id,
                   text=__("Okay. Next Player: {name}",
                           multi=game.translate).format(
                       name=display_name(game.current_player.user)),
                   reply_to_message_id=update.message.message_id,
                   message_thread_id=game.thread_id)
    else:
        await send_async(context.bot, chat.id,
                   text=__("{name} left the game before it started.",
                           multi=game.translate).format(
                       name=display_name(user)),
                   reply_to_message_id=update.message.message_id,
                   message_thread_id=game.thread_id)


@user_locale
async def kick_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /kick command"""

    if update.message.chat.type == 'private':
        await help_handler(update, context)
        return

    chat = update.message.chat
    user = update.message.from_user
    thread_id = get_thread_id(update)
    game = _game_in_chat(chat.id, thread_id)

    if game is None:
        await send_async(context.bot, chat.id,
               text=_("No game is running at the moment. "
                      "Create a new game with /new"),
               reply_to_message_id=update.message.message_id,
               message_thread_id=thread_id)
        return

    if not game.started:
        await send_async(context.bot, chat.id,
                   text=_("The game is not started yet. "
                          "Join the game with /join and start the game with /start"),
                   reply_to_message_id=update.message.message_id,
                   message_thread_id=game.thread_id)
        return

    if await user_is_creator_or_admin(user, game, context.bot, chat):

        if update.message.reply_to_message:
            kicked = update.message.reply_to_message.from_user

            try:
                gm.leave_game(kicked, chat)

            except NoGameInChatError:
                await send_async(context.bot, chat.id, text=_("Player {name} is not found in the current game.".format(name=display_name(kicked))),
                                reply_to_message_id=update.message.message_id,
                                message_thread_id=game.thread_id)
                return

            except NotEnoughPlayersError:
                gm.end_game(chat, user)
                await send_async(context.bot, chat.id,
                                text=_("{0} was kicked by {1}".format(display_name(kicked), display_name(user))),
                                message_thread_id=game.thread_id)
                await send_async(context.bot, chat.id, text=__("Game ended!", multi=game.translate),
                                message_thread_id=game.thread_id)
                return

            await send_async(context.bot, chat.id,
                            text=_("{0} was kicked by {1}".format(display_name(kicked), display_name(user))),
                            message_thread_id=game.thread_id)

        else:
            await send_async(context.bot, chat.id,
                text=_("Please reply to the person you want to kick and type /kick again."),
                reply_to_message_id=update.message.message_id,
                message_thread_id=game.thread_id)
            return

        await send_async(context.bot, chat.id,
                   text=__("Okay. Next Player: {name}",
                           multi=game.translate).format(
                       name=display_name(game.current_player.user)),
                   reply_to_message_id=update.message.message_id,
                   message_thread_id=game.thread_id)

    else:
        await send_async(context.bot, chat.id,
                  text=_("Only the game creator ({name}) and admin can do that.")
                  .format(name=game.starter.first_name),
                  reply_to_message_id=update.message.message_id,
                  message_thread_id=game.thread_id)


async def select_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for callback queries to select the current game"""

    try:
        chat_id = int(update.callback_query.data)
    except (ValueError, TypeError):
        return
    user_id = update.callback_query.from_user.id
    players = gm.userid_players[user_id]
    for player in players:
        if player.game.chat.id == chat_id:
            gm.userid_current[user_id] = player
            break
    else:
        await send_async(context.bot,
                   update.callback_query.message.chat_id,
                   text=_("Game not found."))
        return

    back = [[InlineKeyboardButton(text=_("Back to last group"),
                                  switch_inline_query='')]]
    await context.bot.answer_callback_query(
        update.callback_query.id,
        text=_("Please switch to the group you selected!"),
        show_alert=False)

    await context.bot.edit_message_text(
        chat_id=update.callback_query.message.chat_id,
        message_id=update.callback_query.message.message_id,
        text=_("Selected group: {group}\n"
               "<b>Make sure that you switch to the correct "
               "group!</b>").format(
            group=gm.userid_current[user_id].game.chat.title),
        reply_markup=InlineKeyboardMarkup(back),
        parse_mode=ParseMode.HTML)


@game_locales
async def status_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove player from game if user leaves the group"""
    chat = update.message.chat

    if update.message.left_chat_member:
        user = update.message.left_chat_member

        player = gm.player_for_user_in_chat(user, chat)
        if not player:
            return

        game = player.game

        try:
            gm.leave_game(user, chat)
        except NoGameInChatError:
            return
        except NotEnoughPlayersError:
            gm.end_game(chat, user)
            await send_async(context.bot, chat.id, text=__("Game ended!",
                                             multi=game.translate),
                       message_thread_id=game.thread_id)
            return

        await send_async(context.bot, chat.id, text=__("Removing {name} from the game",
                                         multi=game.translate)
                   .format(name=display_name(user)),
                   message_thread_id=game.thread_id)


@game_locales
@user_locale
async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command"""

    if update.message.chat.type != 'private':
        chat = update.message.chat
        thread_id = get_thread_id(update)
        game = _game_in_chat(chat.id, thread_id)

        if game is None:
            await send_async(context.bot, chat.id,
                       text=_("There is no game running in this chat. Create "
                              "a new one with /new"),
                       message_thread_id=thread_id)
            return

        if game.started:
            await send_async(context.bot, chat.id, text=_("The game has already started"),
                       message_thread_id=game.thread_id)

        elif len(game.players) < MIN_PLAYERS:
            await send_async(context.bot, chat.id,
                       text=__("At least {minplayers} players must /join the game "
                              "before you can start it").format(minplayers=MIN_PLAYERS),
                       message_thread_id=game.thread_id)

        else:
            # Starting a game
            game.start()

            for player in game.players:
                player.draw_first_hand()

            choice = [[InlineKeyboardButton(text=_("Make your choice!"), switch_inline_query_current_chat='')]]
            first_message = (
                __("First player: {name}\n"
                   "Use /close to stop people from joining the game.\n"
                   "Enable multi-translations with /enable_translations",
                   multi=game.translate)
                .format(name=display_name(game.current_player.user)))

            await context.bot.send_sticker(chat.id,
                            sticker=c.STICKERS[str(game.last_card)],
                            read_timeout=TIMEOUT, write_timeout=TIMEOUT,
                            message_thread_id=game.thread_id)

            await context.bot.send_message(chat.id,
                            text=first_message,
                            reply_markup=InlineKeyboardMarkup(choice),
                            read_timeout=TIMEOUT, write_timeout=TIMEOUT,
                            message_thread_id=game.thread_id)

            start_player_countdown(context.bot, game, context.job_queue)

    elif context.args and context.args[0] == 'select':
        players = gm.userid_players[update.message.from_user.id]

        groups = list()
        for player in players:
            title = player.game.chat.title

            if player == gm.userid_current[update.message.from_user.id]:
                title = '- %s -' % player.game.chat.title

            groups.append(
                [InlineKeyboardButton(text=title,
                                      callback_data=str(player.game.chat.id))]
            )

        await send_async(context.bot, update.message.chat_id,
                   text=_('Please select the group you want to play in.'),
                   reply_markup=InlineKeyboardMarkup(groups))

    else:
        await help_handler(update, context)


@user_locale
async def close_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /close command"""
    chat = update.message.chat
    user = update.message.from_user
    thread_id = get_thread_id(update)
    game = _game_in_chat(chat.id, thread_id)

    if game is None:
        await send_async(context.bot, chat.id,
                   text=_("There is no running game in this chat."),
                   message_thread_id=thread_id)
        return

    if user.id in game.owner:
        game.open = False
        await send_async(context.bot, chat.id, text=_("Closed the lobby. "
                                        "No more players can join this game."),
                   message_thread_id=game.thread_id)
        return

    else:
        await send_async(context.bot, chat.id,
                   text=_("Only the game creator ({name}) and admin can do that.")
                   .format(name=game.starter.first_name),
                   reply_to_message_id=update.message.message_id,
                   message_thread_id=game.thread_id)
        return


@user_locale
async def open_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /open command"""
    chat = update.message.chat
    user = update.message.from_user
    thread_id = get_thread_id(update)
    game = _game_in_chat(chat.id, thread_id)

    if game is None:
        await send_async(context.bot, chat.id,
                   text=_("There is no running game in this chat."),
                   message_thread_id=thread_id)
        return

    if user.id in game.owner:
        game.open = True
        await send_async(context.bot, chat.id, text=_("Opened the lobby. "
                                        "New players may /join the game."),
                   message_thread_id=game.thread_id)
        return
    else:
        await send_async(context.bot, chat.id,
                   text=_("Only the game creator ({name}) and admin can do that.")
                   .format(name=game.starter.first_name),
                   reply_to_message_id=update.message.message_id,
                   message_thread_id=game.thread_id)
        return


@user_locale
async def enable_translations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /enable_translations command"""
    chat = update.message.chat
    user = update.message.from_user
    thread_id = get_thread_id(update)
    game = _game_in_chat(chat.id, thread_id)

    if game is None:
        await send_async(context.bot, chat.id,
                   text=_("There is no running game in this chat."),
                   message_thread_id=thread_id)
        return

    if user.id in game.owner:
        game.translate = True
        await send_async(context.bot, chat.id, text=_("Enabled multi-translations. "
                                        "Disable with /disable_translations"),
                   message_thread_id=game.thread_id)
        return

    else:
        await send_async(context.bot, chat.id,
                   text=_("Only the game creator ({name}) and admin can do that.")
                   .format(name=game.starter.first_name),
                   reply_to_message_id=update.message.message_id,
                   message_thread_id=game.thread_id)
        return


@user_locale
async def disable_translations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /disable_translations command"""
    chat = update.message.chat
    user = update.message.from_user
    thread_id = get_thread_id(update)
    game = _game_in_chat(chat.id, thread_id)

    if game is None:
        await send_async(context.bot, chat.id,
                   text=_("There is no running game in this chat."),
                   message_thread_id=thread_id)
        return

    if user.id in game.owner:
        game.translate = False
        await send_async(context.bot, chat.id, text=_("Disabled multi-translations. "
                                        "Enable them again with "
                                        "/enable_translations"),
                   message_thread_id=game.thread_id)
        return

    else:
        await send_async(context.bot, chat.id,
                   text=_("Only the game creator ({name}) and admin can do that.")
                   .format(name=game.starter.first_name),
                   reply_to_message_id=update.message.message_id,
                   message_thread_id=game.thread_id)
        return


@game_locales
@user_locale
async def skip_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /skip command"""
    chat = update.message.chat
    user = update.message.from_user

    player = gm.player_for_user_in_chat(user, chat)
    if not player:
        await send_async(context.bot, chat.id,
                   text=_("You are not playing in a game in this chat."),
                   message_thread_id=get_thread_id(update))
        return

    game = player.game
    skipped_player = game.current_player

    started = skipped_player.turn_started
    now = datetime.now()
    delta = (now - started).seconds

    # You can't skip if the current player still has time left
    # You can skip yourself even if you have time left (you'll still draw)
    if delta < skipped_player.waiting_time and player != skipped_player:
        n = skipped_player.waiting_time - delta
        await send_async(context.bot, chat.id,
                   text=_("Please wait {time} second",
                          "Please wait {time} seconds",
                          n)
                   .format(time=n),
                   reply_to_message_id=update.message.message_id,
                   message_thread_id=game.thread_id)
    else:
        await do_skip(context.bot, player)


@game_locales
@user_locale
async def reply_to_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for inline queries.
    Builds the result list for inline queries and answers to the client.
    """
    results = list()
    switch = None

    has_game = False
    try:
        user = update.inline_query.from_user
        user_id = user.id
        players = gm.userid_players[user_id]
        player = gm.userid_current[user_id]
        game = player.game
        has_game = True
    except KeyError:
        players = []
        player = None
        game = None
        add_no_game(results)

    if has_game:

        # The game has not started.
        # The creator may change the game mode, other users just get a "game has not started" message.
        if not game.started:
            if user_is_creator(user, game):
                add_mode_classic(results)
                add_mode_fast(results)
                add_mode_wild(results)
                add_mode_text(results)
            else:
                add_not_started(results)


        elif user_id == game.current_player.user.id:
            if game.choosing_color:
                add_choose_color(results, game)
                add_other_cards(player, results, game)
            else:
                if not player.drew:
                    add_draw(player, results)

                else:
                    add_pass(results, game)

                if game.last_card.special == c.DRAW_FOUR and game.draw_counter:
                    add_call_bluff(results, game)

                playable = player.playable_cards()
                added_ids = list()  # Duplicates are not allowed

                for card in sorted(player.cards):
                    add_card(game, card, results,
                             can_play=(card in playable and
                                            str(card) not in added_ids))
                    added_ids.append(str(card))

                add_gameinfo(game, results)

        elif user_id != game.current_player.user.id:
            # Not the current player — show cards as not playable.
            # Defensive: if draw_counter > 0 and this player is next,
            # the turn may still be transitioning — show draw option.
            if game.draw_counter and game.current_player.next.user.id == user_id:
                add_draw(player, results)
            for card in sorted(player.cards):
                add_card(game, card, results, can_play=False)

        else:
            add_gameinfo(game, results)

        if players and game and len(players) > 1:
            switch = _('Current game: {game}').format(game=game.chat.title)

    # Re-encode every result_id as <game_id>:<base_id>:<anti_cheat> so the
    # UpdateProcessor can route ChosenInlineResult updates to the right game
    # lock and process_result can resolve the game directly. Non-game results
    # (no_game sentinel) are tagged with the pseudo game-id 'none' so the
    # decode contract stays uniform.
    if has_game:
        encode_results_list(results, game_id=game.id,
                            anti_cheat=player.anti_cheat)
    else:
        encode_results_list(results, game_id=PSEUDO_GAME_ID, anti_cheat=0)

    button = None
    if switch:
        button = InlineQueryResultsButton(text=switch, start_parameter='select')
    await answer_async(context.bot, update.inline_query.id, results, cache_time=0,
                 button=button)


@game_locales
@user_locale
async def process_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for chosen inline results.
    Checks the players actions and acts accordingly.

    Per-game serialization is owned by :class:`UnoUpdateProcessor`; this
    handler runs inside the (chat, thread) lock and must not acquire its own.
    """
    try:
        user = update.chosen_inline_result.from_user
        raw_result_id = update.chosen_inline_result.result_id
    except AttributeError:
        return

    logger.debug("Selected result: " + raw_result_id)

    decoded = decode_result_id(raw_result_id)
    if decoded is None:
        # Old-format ID (bot was restarted mid-game) or unknown sentinel.
        return

    base_id = decoded.base_id
    anti_cheat = decoded.anti_cheat

    if base_id in ('hand', 'gameinfo', 'nogame'):
        return

    resolved = resolve_result(gm, decoded, user_id=user.id)
    if resolved.dead_reason is not None:
        # AC-8: the game has ended (or the user was kicked) between
        # answer_inline_query and chosen_inline_result. Telegram does not give
        # us the chat the user was typing in, so the only feedback channel is
        # a direct message — send_async swallows "bot can't initiate chat"
        # errors for users who never started a DM with the bot.
        if resolved.dead_reason == DEAD_UNKNOWN_GAME:
            hint = _("This game has already ended.")
        elif resolved.dead_reason == DEAD_NOT_A_PLAYER:
            hint = _("You are no longer in this game.")
        else:  # DEAD_NO_CURRENT_GAME
            hint = _("You are not in a game right now. "
                     "Use /new to start one or /join to join an existing game.")
        await send_async(context.bot, user.id, text=hint)
        return

    game = resolved.game
    player = resolved.player
    chat = game.chat

    if base_id.startswith('mode_'):
        mode = base_id[5:]
        if mode not in ('classic', 'fast', 'wild', 'text'):
            return
        game.set_mode(mode)
        logger.info("Gamemode changed to {mode}".format(mode=mode))
        await send_async(context.bot, chat.id,
                         text=__("Gamemode changed to {mode}".format(mode=mode)),
                         message_thread_id=game.thread_id)
        return
    if len(base_id) == 36:  # UUID-only result (legacy "other cards" placeholder)
        return

    if anti_cheat != player.anti_cheat:
        await send_async(context.bot, chat.id,
                         text=__("Cheat attempt by {name}", multi=game.translate)
                         .format(name=display_name(player.user)),
                         message_thread_id=game.thread_id)
        return

    player.anti_cheat += 1

    if base_id == 'call_bluff':
        reset_waiting_time(context.bot, player)
        await do_call_bluff(context.bot, player)
    elif base_id == 'draw':
        reset_waiting_time(context.bot, player)
        await do_draw(context.bot, player)
    elif base_id == 'pass':
        game.turn()
    elif base_id in c.COLORS:
        game.choose_color(base_id)
    else:
        reset_waiting_time(context.bot, player)
        await do_play_card(context.bot, player, base_id)

    if game_is_running(game):
        nextplayer_message = (
            __("Next player: {name}", multi=game.translate)
            .format(name=display_name(game.current_player.user)))
        choice = [[InlineKeyboardButton(text=_("Make your choice!"), switch_inline_query_current_chat='')]]
        await send_async(context.bot, chat.id,
                        text=nextplayer_message,
                        reply_markup=InlineKeyboardMarkup(choice),
                        message_thread_id=game.thread_id)
        start_player_countdown(context.bot, game, context.job_queue)


def reset_waiting_time(bot, player):
    """Resets waiting time for a player"""
    if player.waiting_time < WAITING_TIME:
        player.waiting_time = WAITING_TIME


# Add all handlers to the application and run the bot
application.add_handler(InlineQueryHandler(reply_to_query))
application.add_handler(ChosenInlineResultHandler(process_result))
application.add_handler(CallbackQueryHandler(select_game))
application.add_handler(CommandHandler('start', start_game))
application.add_handler(CommandHandler('new', new_game))
application.add_handler(CommandHandler('kill', kill_game))
application.add_handler(CommandHandler('join', join_game))
application.add_handler(CommandHandler('leave', leave_game))
application.add_handler(CommandHandler('kick', kick_player))
application.add_handler(CommandHandler('open', open_game))
application.add_handler(CommandHandler('close', close_game))
application.add_handler(CommandHandler('enable_translations',
                                      enable_translations))
application.add_handler(CommandHandler('disable_translations',
                                      disable_translations))
application.add_handler(CommandHandler('skip', skip_player))
application.add_handler(CommandHandler('notify_me', notify_me))
simple_commands.register()
settings.register()
application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, status_update))
application.add_error_handler(error)


async def post_init(application):
    """Set bot commands and validate configuration on startup"""
    me = await application.bot.get_me()
    if not me.supports_inline_queries:
        logger.warning("Inline mode is NOT enabled for @%s. "
                       "Players will not be able to select cards. "
                       "Enable it via @BotFather /setinline.", me.username)

    await application.bot.set_my_commands([
        BotCommand('new', 'Start a new game'),
        BotCommand('join', 'Join the current game'),
        BotCommand('start', 'Start the game'),
        BotCommand('leave', 'Leave the game you\'re in'),
        BotCommand('close', 'Close the game lobby'),
        BotCommand('open', 'Open the game lobby'),
        BotCommand('kill', 'Terminate the game'),
        BotCommand('kick', 'Kick players out of the game'),
        BotCommand('skip', 'Skip the current player'),
        BotCommand('notify_me', 'Get notified about new games'),
        BotCommand('help', 'How to use this bot?'),
        BotCommand('modes', 'Explanation of game modes'),
        BotCommand('settings', 'Language and other settings'),
        BotCommand('stats', 'Show statistics'),
        BotCommand('source', 'See source information'),
        BotCommand('news', 'All news about this bot'),
    ])

application.post_init = post_init

start_bot(application)
