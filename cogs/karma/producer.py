import re
from collections import defaultdict

import discord
from discord.ext import commands

from core import datasource
from core.model.member import KarmaMember, Member
from core.service.karma_service import KarmaService, BlockerService
from core.timer import KarmaCooldownTimer

from util.config import config, thanks_list


# Class that gives positive karma and negative karma on message deletion (take back last action)
class KarmaProducer(commands.Cog):

    def __init__(self, bot, karma_service=KarmaService(datasource.karma),
                 blocker_service=BlockerService(datasource.blacklist)):
        self.bot = bot
        self.karma_service = karma_service
        self.blocker_service = blocker_service
        self._members_on_cooldown = defaultdict(list)

    # give karma if message has thanks and correct mentions
    @commands.Cog.listener()
    async def on_message(self, message):
        guild_id: int = message.guild.id
        guild = self.bot.get_guild(guild_id)
        if await self.validate_message(message):
            if self.blocker_service.find_member(Member(str(guild_id), message.author.id)) is None:
                if message.author.id not in self._members_on_cooldown[guild.id]:
                    await self.give_karma(message, guild, True)
                else:
                    await message.add_reaction('🕒')
            else:
                await message.author.send('You have been blacklisted from giving out Karma, '
                                          'if you believe this to be an error contact {}.'
                                          .format(config['blacklist']))

    # remove karma on deleted message of said karma message
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        guild_id: int = message.guild.id
        guild = self.bot.get_guild(guild_id)
        await self.give_karma(message, guild, False)

    # check if message is a valid message for karma
    async def validate_message(self, message) -> bool:
        # check if message has any variation of thanks
        if self.has_thanks(message) and len(message.mentions) > 0:
            return True
        else:
            return False

    # check if message has thanks by using regex
    def has_thanks(self, message) -> bool:
        pattern = r'\b{}\b'
        for thanks in thanks_list():
            if re.search(re.compile(pattern.format(thanks), re.IGNORECASE), message.content) is not None:
                return True
        return False

    # give karma to all users in a message except author, other bots or aura itself.
    # logged to a configured channel with member name & discriminator, optionally with nickname
    # cooldown author after successfully giving karma
    async def give_karma(self, message: discord.Message, guild: discord.Guild, inc: bool):
        karma_given = 0
        for mention in message.mentions:
            member = mention
            if member.id != message.author.id and member.id != self.bot.user.id and not \
                    self.bot.get_user(member.id).bot:
                karma_member = KarmaMember(guild.id, member.id, message.channel.id, message.id)
                self.karma_service.upsert_karma_member(karma_member, inc)
                karma_given += 1
                if inc:
                    await self.notify_member(message, member)
        if karma_given > 0:
            await self.cooldown_user(guild.id, message.author.id)

    # notify user about successful karma gain
    async def notify_member(self, message, member):
        if str(config['karma']['log']).lower() == 'true':
            if member.nick is None:
                await self.bot.get_channel(int(config['channel']['log'])).send(
                    '{} earned karma in {}'
                        .format(member.name + '#'
                                + member.discriminator,
                                message.channel.mention))
            else:
                await self.bot.get_channel(int(config['channel']['log'])).send(
                    '{} ({}) earned karma in {}'.format(member.name + '#'
                                                        + member.discriminator,
                                                        member.nick,
                                                        message.channel.mention))
        if str(config['karma']['message']).lower() == 'true':
            await self.bot.get_channel(message.channel.id).send('Congratulations {}, you have earned a karma.'
                                                                .format(member.mention))
        if str(config['karma']['emote']).lower() == 'true':
            await message.add_reaction('👍')

    # create new timer and add the user to it
    async def cooldown_user(self, guild_id: int, member_id: int) -> None:
        self._members_on_cooldown[guild_id].append(member_id)
        await KarmaCooldownTimer(self.remove_from_cooldown, int(config['cooldown']),
                                 guild_id, member_id).start()

    # remove user from cooldown after time runs out
    async def remove_from_cooldown(self, guild_id: int, member_id: int) -> None:
        self._members_on_cooldown[guild_id].remove(member_id)
