import discord
import yaml
from discord.ext import commands

# Class to return karma of a single user or the top of the particular karma type
from core.model.karma_member import KarmaMember
from core.service.karma_service import KarmaService


class Leaderboard(commands.Cog):

    def __init__(self, bot):
        self._bot = bot
        self._karma_service = KarmaService()
        with open("config.yaml", 'r') as stream:
            self._config = yaml.safe_load(stream)
        self._limit = self._config['leaderboard']['limit']

    @commands.command()
    async def karma(self, ctx, karma_type):
        if len(ctx.message.mentions) == 1:
            guild_id: int = int(self._config['guild'])
            guild = self._bot.get_guild(guild_id)
            message = ctx.message
            member = message.mentions[0]
            if not self._bot.get_user(self._bot.user.id).mentioned_in(message):
                if guild.get_member(member.id).mentioned_in(message):
                    karma_member = KarmaMember(guild_id, member.id, karma_type)
                    karma = self._karma_service.get_karma_from_karma_member(karma_member)
                    await ctx.channel.send('{} has earned a total of {} {} karma'
                                           .format(member.name, karma, karma_type))

    @commands.command()
    async def leaderboard(self, ctx, karma_type):
        guild_id: str = self._config['guild']
        print(guild_id)
        embed = discord.Embed(title="{}".format(karma_type).capitalize(),
                              description="Top {} Members with {} karma".format(self._limit, karma_type),
                              color=0x00ff00)
        leaderboard = self._karma_service.get_top_karma_members(guild_id, self._limit, karma_type)
        if leaderboard.collection.count_documents(dict(guild_id=guild_id)) > 0:
            for document in leaderboard:
                guild = self._bot.get_guild(int(guild_id))
                member = guild.get_member(int(document['member_id']))
                karma = document['karma']
                embed.add_field(name=member.name+'#'+member.discriminator, value=karma, inline=False)
            await ctx.channel.send(embed=embed)
        else:
            await ctx.channel.send('At present there is not a single user with {} karma'.format(karma_type))
