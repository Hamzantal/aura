import logging
from collections import defaultdict

import discord
from discord.ext import commands
from discord.ext.commands import guild_only

from core import datasource
from core.model.member import KarmaMember, Member
from core.service.mongo_service import KarmaMemberService, BlockerService
from core.service.validation_service import validate_message
from core.timer import KarmaSingleActionTimer
from util.config import config, karma, reaction_emoji
from util.constants import revoke_message
from util.util import clear_reaction

log = logging.getLogger(__name__)


class KarmaProducer(commands.Cog):
    # Class that gives positive karma and negative karma on message deletion (take back last action)

    def __init__(self, bot, karma_service=KarmaMemberService(datasource.karma),
                 blocker_service=BlockerService(datasource.blacklist)):
        self.bot = bot
        self.karma_service = karma_service
        self.blocker_service = blocker_service
        # this creates a dictionary where each value is a dictionary whose values are a list
        # with lambda this automatically creates an empty list on non existing keys
        self._members_on_cooldown = defaultdict(lambda: defaultdict(list))
        self._running_timers = defaultdict(lambda: defaultdict(lambda: defaultdict()))

    @guild_only()
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        message listener, calls methods to validate valid karma gain and filter out blacklisted members.
        :param message: discord.Message
        :return: None
        """
        guild_id: int = message.guild.id
        if message.author.bot:
            return

        if not await validate_message(message):
            return

        # check if member is blacklisted
        if self.blocker_service.find_member(Member(str(guild_id), message.author.id)) is not None:
            if str(config['blacklist']['dm']).lower() == 'true':
                log.info(f'Sending Blacklist dm to {message.author.id} in guild {guild_id}')
                await message.author.send(f'You have been blacklisted from giving out karma, if you believe this ' +
                                          f'to be an error, contact {config["blacklist"]["contact"]}')
            if str(config['blacklist']['emote']).lower() == 'true':
                await message.add_reaction(reaction_emoji()['karma_blacklist'])
            return

        await self.give_karma(message, message.guild)

    @guild_only()
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        """
        Will remove and add karma according to the state of the message before and afterwards.
        :param before: discord message before the edit
        :param after: discord message after the edit
        :return: None
        """

        if str(karma()['edit']).lower() != 'true':
            return

        before_valid = await validate_message(before)
        after_valid = await validate_message(after)
        if before_valid and after_valid:
            print()  # TODO implement search on message id to find all members thanked
            return

        if before_valid and not after_valid:
            # remove karma given out through karma message.
            log.info(f'Removing karma because message {after.id} not valid after edit')
            await after.clear_reactions()
            await self.remove_karma(before, after.guild, 'message edit')
            return

        if after_valid and not before_valid:
            # all new karma to give out
            log.info(f'Adding karma because message: {after.id} is valid after edit')
            await self.give_karma(after, after.guild)

    @guild_only()
    @commands.Cog.listener()
    async def on_message_delete(self, message) -> None:
        """
        message deletion listener, remove karma associated with that message, if it is a karma message.
        :param message: message which was deleted
        :return: None
        """
        if self.karma_service.find_message(str(message.id)) is not None:
            await self.remove_karma(message, message.guild, 'message delete')

    @guild_only()
    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction: discord.Reaction, user: discord.User) -> None:
        """
        If the thumps up reaction is removed then, remove the karma gained through the karma message.
        :param reaction: the reaction that was removed
        :param user: user who added the reaction first
        :return: None
        """
        # if aura made this reaction then it was very clearly a karma message
        if user.id != self.bot.user.id and reaction.emoji != reaction_emoji()['karma_gain']:
            return

        message = reaction.message
        if self.karma_service.find_message(str(message.id)) is not None:
            await self.remove_karma(message, message.guild, 'reaction remove')

    @guild_only()
    @commands.Cog.listener()
    async def on_reaction_clear(self, message, reactions) -> None:
        """
        If all reactions are cleared and one of those reactions is a karma gain emoji and was made by Aura
        then remove all karma associated.
        :param message:
        :param reactions:
        :return:
        """
        for reaction in reactions:
            if reaction.emoji != reaction_emoji()['karma_gain']:
                continue

            # reaction me is very much the same as checking the user id
            # was the reaction made by aura
            if not reaction.me:
                continue

            if self.karma_service.find_message(str(message.id)) is not None:
                await self.remove_karma(message, message.guild, 'reaction clear')

    @guild_only()
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User) -> None:
        """
        If the karma deletion is set, will remove all karma gained through the message,
        if the message author clicks it and then remove all reactions on the message
        :param reaction: reaction which was clicked
        :param user: user who added the reaction
        :return: None
        """
        if self.karma_service.find_message(str(reaction.message.id)) is None or \
                reaction.message.author.id != user.id or \
                not reaction.me:
            return

        if reaction.emoji == reaction_emoji()['karma_delete']:
            if str(karma()['self_delete']).lower() != 'true':
                return

            log.info('Removing karma because the karma_delete emoji was clicked by author')
            for other_reaction in reaction.message.reactions:
                await clear_reaction(other_reaction)

            await self.remove_karma(reaction.message, reaction.message.guild, 'self emoji clear')
            return

        log.info('Removing aura emojis because gain was clicked by author')
        for other_reaction in reaction.message.reactions:
            if reaction is not other_reaction:
                await clear_reaction(other_reaction)

    async def give_karma(self, message: discord.Message, guild: discord.Guild) -> None:
        """
        give karma to all the users in the message except the author, other bots or aura itself
        :param message: message containing the mentions
        :param guild: guild of the karma message
        :return: None
        """
        # walk through the mention list which contains discord: Members
        for member in set(message.mentions):
            # filter out message author, aura and other bots
            a_id = message.author.id
            m_id = member.id
            if m_id == a_id or m_id == self.bot.user.id or self.bot.get_user(member).bot:
                continue

            # check if giver-receiver combo on cooldown
            if m_id in self._members_on_cooldown[guild.id][a_id]:
                log.info(f'Sending configured cooldown response to {a_id} in guild {guild.id}')
                if str(config['karma']['time-emote']).lower() == "true":
                    await message.add_reaction(reaction_emoji()['karma_cooldown'])

                if str(config['karma']['time-message']).lower() == "true":
                    await self.bot.get_channel(message.channel.id) \
                        .send(f'Sorry {message.author.mention}, your karma for {member.name} needs time to recharge')
                continue

            karma_member = KarmaMember(guild.id, member.id, message.channel.id, message.id)
            self.karma_service.upsert_karma_member(karma_member)
            await self.cooldown_user(guild.id, message.author.id, member.id)
            await self.notify_member_gain(message, member)
            log.info(f'{a_id} gave karma to {m_id} in guild {guild.id}')

    async def remove_karma(self, message: discord.Message, guild: discord.Guild, reason: str) -> None:
        """
        remove karma from everyone that is in the set of mentions of the message,
        providing a reason for the deletion.
        :param message: message to remove karma from
        :param guild: guild of the message
        :param reason: reason for deleting the karma (event_type)
        :return: None
        """
        # walk through the mention list which contains discord: Members
        for mention in set(message.mentions):
            member = mention
            karma_member = KarmaMember(guild.id, member.id, message.channel.id, message.id, 1)
            deletion_result = self.karma_service.delete_single_karma(karma_member)
            await self.log_karma_removal(message, member, reason)
            if deletion_result.deleted_count == 1:
                continue

            single_action_timer: KarmaSingleActionTimer \
                = self._running_timers[guild.id][message.author.id][member.id]
            if single_action_timer is None or not single_action_timer.is_started:
                continue

            await single_action_timer.stop()
            del self._running_timers[guild.id][message.author.id][member.id]
            self._members_on_cooldown[guild.id][message.author.id].remove(member.id)

    async def notify_member_gain(self, message: discord.Message, member: discord.Member) -> None:
        """
        notify the member that he gained karma, configureable through configuration.
        :param message: the discord message, used to link to the message.
        :param member: the member to notify, if applicable.
        :return: None
        """
        if str(karma()['log']).lower() == 'true':
            log_message = '{}{} earned karma in {}. {}'.format(
                member.name + '#' + member.discriminator,
                f' ({member.nick})' if member.Nick is not None else '',
                message.channel.mention,
                message.jump_url)

            log_channel = self.bot.get_channel(int(config['channel']['log']))
            log_channel.send(log_message)

        if str(karma()['message']).lower() == 'true':
            result = f'Congratulations {member.mention}, you have earned karma from {member.author.mention}. '

            if str(karma()['self_delete']).lower() == 'true':
                result += revoke_message.format(message.author.mention)

            message_channel = self.bot.get_channel(message.channel.id)
            await message_channel.send(result)

        if str(karma()['emote']).lower() == 'true':
            await message.add_reaction(reaction_emoji()['karma_gain'])
            if str(karma()['self_delete']).lower() == 'true':
                await message.add_reaction(reaction_emoji()['karma_delete'])

    async def log_karma_removal(self, message: discord.Message, member: discord.Member,
                                event_type: str) -> None:  # TODO change event_type to enum
        """
        log the karma removal of a user in a channel.
        :param message: the discord message which triggered the removal, can be None.
        :param member: the discord member whose removal is to be logged.
        :param event_type: the reason for the deletion
        :return: None
        """
        if not karma()['log']:
            return

        result = f'karma for {member.name + "#" + member.discriminator} was removed through event: ' + \
                 f'{event_type} "" in {message.channel.mention}'
        if event_type == 'message delete':
            await self.bot.get_channel(int(config['channel']['log'])).send(result)
            return

        result += f" :: {message.jump_url}"
        await self.bot.get_channel(int(config['channel']['log'])).send(result)

    async def cooldown_user(self, guild_id: int, giver_id: int, receiver_id: int) -> None:
        """
        Put giver-receiver pairs on a cooldown and start a SingleActionTimer which removes them from the cooldown dict.
        :param guild_id: id of the guild the cooldown is applied to.
        :param giver_id: id of the giver who thanked the receiver.
        :param receiver_id: id of the receiver who was thanked by the receiver.
        :return: None
        """
        self._members_on_cooldown[guild_id][giver_id].append(receiver_id)
        single_action_timer = KarmaSingleActionTimer(self.remove_from_cooldown, int(config['cooldown']),
                                                     guild_id, giver_id, receiver_id)
        self._running_timers[guild_id][giver_id][receiver_id] = single_action_timer
        await single_action_timer.start()

    async def remove_from_cooldown(self, guild_id: int, giver_id: int, receiver_id: int) -> None:
        """
        Method that is used in the SingleAction timer to remove the giver-receiver pair from the cooldown dict.
        :param guild_id: id of the guild
        :param giver_id:  id of the giver who thanked the receiver.
        :param receiver_id: id of the receiver who was thanked by the receiver
        :return:
        """
        self._members_on_cooldown[guild_id][giver_id].remove(receiver_id)
        del self._running_timers[guild_id][giver_id][receiver_id]
