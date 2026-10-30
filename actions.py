import logging

import card as c

from telegram.ext import ContextTypes
from apscheduler.jobstores.base import JobLookupError

from config import TIME_REMOVAL_AFTER_SKIP, MIN_FAST_TURN_TIME
from pony.orm import db_session
from errors import DeckEmptyError, NotEnoughPlayersError
from internationalization import __, locale_stack
from shared_vars import gm
from user_setting import UserSetting
from utils import send_async, display_name, game_is_running

logger = logging.getLogger(__name__)


class Countdown(object):
    player = None
    job_queue = None
    locales = None

    def __init__(self, player, job_queue, locales=None):
        self.player = player
        self.job_queue = job_queue
        self.locales = locales or []


# Game actions change the game state synchronously and return the messages
# to send, so no inline query can observe a half-applied move. Callers run
# under the game's lock (UnoUpdateProcessor) and send the messages afterwards.


def is_action_allowed(game, player, action):
    """Whether ``action`` (the base id of an inline result) is a legal move
    for ``player`` right now.

    Mirrors the options ``reply_to_query`` offers, so a stale result list
    (cached by the client, or fetched while a move was in flight) cannot act
    out of turn or repeat a move.
    """
    if not game.started or player is not game.current_player:
        return False
    if action in c.COLORS:
        return game.choosing_color
    if game.choosing_color:
        return False
    if action == 'draw':
        return not player.drew
    if action == 'pass':
        return player.drew
    if action == 'call_bluff':
        return game.last_card.special == c.DRAW_FOUR and game.draw_counter > 0
    try:
        card = c.from_str(action)
    except ValueError:
        return False
    return card in player.playable_cards()


def do_skip(player):
    """Skip the current player of ``player``'s game. Returns the messages."""
    game = player.game
    skipped_player = game.current_player

    if skipped_player.waiting_time > 0:
        skipped_player.anti_cheat += 1
        skipped_player.waiting_time -= TIME_REMOVAL_AFTER_SKIP
        if skipped_player.waiting_time < 0:
            skipped_player.waiting_time = 0

        try:
            skipped_player.draw()
        except DeckEmptyError:
            pass

        game.turn()
        logger.info("%s was skipped!", display_name(skipped_player.user))
        return [__("Waiting time to skip this player has "
                   "been reduced to {time} seconds.\n"
                   "Next player: {name}", multi=game.translate)
                .format(time=skipped_player.waiting_time,
                        name=display_name(game.current_player.user))]

    try:
        gm.leave_game(skipped_player.user, game.chat, thread_id=game.thread_id)
    except NotEnoughPlayersError:
        gm.end_game(game)
        logger.info("%s ran out of time, game ended",
                    display_name(skipped_player.user))
        return [__("{name} ran out of time "
                   "and has been removed from the game!\n"
                   "The game ended.", multi=game.translate)
                .format(name=display_name(skipped_player.user))]

    logger.info("%s ran out of time and was removed",
                display_name(skipped_player.user))
    return [__("{name1} ran out of time "
               "and has been removed from the game!\n"
               "Next player: {name2}", multi=game.translate)
            .format(name1=display_name(skipped_player.user),
                    name2=display_name(game.current_player.user))]


def do_play_card(player, card_id):
    """Play the selected card. Returns the messages to send."""
    card = c.from_str(card_id)
    player.play(card)
    game = player.game
    user = player.user
    messages = []

    with db_session:
        us = UserSetting.get(id=user.id)
        if not us:
            us = UserSetting(id=user.id)

        if us.stats:
            us.cards_played += 1

    if game.choosing_color:
        messages.append(__("Please choose a color", multi=game.translate))

    if len(player.cards) == 1:
        messages.append("UNO!")

    if len(player.cards) == 0:
        messages.append(__("{name} won!", multi=game.translate)
                        .format(name=user.first_name))

        with db_session:
            us = UserSetting.get(id=user.id)
            if us and us.stats:
                us.games_played += 1

                if game.players_won == 0:
                    us.first_places += 1

        game.players_won += 1

        try:
            gm.leave_game(user, game.chat, thread_id=game.thread_id)
        except NotEnoughPlayersError:
            messages.append(__("Game ended!", multi=game.translate))

            with db_session:
                us2 = UserSetting.get(id=game.current_player.user.id)
                if us2 and us2.stats:
                    us2.games_played += 1

            gm.end_game(game)

    return messages


def do_draw(player):
    """Draw for the player. Returns the messages to send."""
    game = player.game
    draw_counter_before = game.draw_counter
    messages = []

    try:
        player.draw()
    except DeckEmptyError:
        messages.append(__("There are no more cards in the deck.",
                           multi=game.translate))

    if (game.last_card.value == c.DRAW_TWO or
        game.last_card.special == c.DRAW_FOUR) and \
            draw_counter_before > 0:
        game.turn()

    return messages


def do_call_bluff(player):
    """Resolve a bluff call against the previous player. Returns the messages."""
    game = player.game
    messages = []

    if player.prev.bluffing:
        messages.append(__("Bluff called! Giving 4 cards to {name}",
                           multi=game.translate)
                        .format(name=player.prev.user.first_name))

        try:
            player.prev.draw()
        except DeckEmptyError:
            messages.append(__("There are no more cards in the deck.",
                               multi=game.translate))

    else:
        game.draw_counter += 2
        messages.append(__("{name1} didn't bluff! Giving 6 cards to {name2}",
                           multi=game.translate)
                        .format(name1=player.prev.user.first_name,
                                name2=player.user.first_name))
        try:
            player.draw()
        except DeckEmptyError:
            messages.append(__("There are no more cards in the deck.",
                               multi=game.translate))

    game.turn()
    return messages


def start_player_countdown(game, job_queue):
    player = game.current_player
    time = player.waiting_time

    if time < MIN_FAST_TURN_TIME:
        time = MIN_FAST_TURN_TIME

    if game.mode == 'fast':
        if game.job:
            try:
                game.job.schedule_removal()
            except JobLookupError:
                pass

        from internationalization import _locale_stack
        locales = _locale_stack.get([])

        job = job_queue.run_once(
            skip_job,
            time,
            data=Countdown(player, job_queue, locales)
        )

        logger.info("Started countdown for player: {player}. {time} seconds."
                    .format(player=display_name(player.user), time=time))
        player.game.job = job


async def skip_job(context: ContextTypes.DEFAULT_TYPE):
    """Job-queue callback fired when a player's turn timer elapses.

    Runs outside the update flow, so it takes the game's lock itself.
    """
    player = context.job.data.player
    game = player.game
    job_queue = context.job.data.job_queue

    # Late import to avoid an import cycle at module load.
    from shared_vars import update_processor
    async with update_processor.serialized((game.chat.id, game.thread_id)):
        if not game_is_running(game):
            return
        with locale_stack(context.job.data.locales):
            messages = do_skip(player)
            if game_is_running(game):
                start_player_countdown(game, job_queue)
            for text in messages:
                await send_async(context.bot, game.chat.id, text=text,
                                 message_thread_id=game.thread_id)
