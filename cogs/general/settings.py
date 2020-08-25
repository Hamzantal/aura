import logging
from collections import Mapping

from discord import Embed
from discord.ext import commands
from discord.ext.commands import guild_only

from core.decorator import has_required_role
from util.config import config, write_config, descriptions
from util.constants import embed_color, hidden_config
from util.embedutil import add_filler_fields

log = logging.getLogger(__name__)


class SettingsManager(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    # edit config defined in config.yaml, return messages if incorrect args are provided.
    # no checks on non existing configuration
    @guild_only()
    @has_required_role(command_name='config')
    @commands.command(brief='configuration menu or configuration modification',
                      usage='{}config\n{}config [keys] [new_value]\n{}config help [keys]'
                      .format(config['prefix'], config['prefix'], config['prefix']))
    async def config(self, ctx, *, params: str = ""):
        args = params.split()
        if len(args) >= 2 and args[0] == 'karma' and args[1] == 'keywords':
            keywords = params.replace('karma keywords', '')
            args[2] = keywords.strip()
            args = args[:3]

        if len(args) > 3:
            await ctx.channel.send('You provided too many arguments to the config command.')
            return

        if len(args) == 0:
            embed = self.build_config_embed()
            await ctx.channel.send(embed=embed)
            return

        if args[0] == 'help':
            embed = self.build_config_help_embed(args)
            await ctx.channel.send(embed=embed)
            return

        if args[0] in hidden_config:
            return

        if args[0] not in config.keys():
            await ctx.channel.send('Configuration key does not exist.')
            return

        if len(args) == 3:
            if args[1] not in config[args[0]].keys():
                await ctx.channel.send('Configuration key does not exist.')
                return

            config[args[0]][args[1]] = args[2]
            write_config()
            await ctx.channel.send('Configuration parameter {} {} has been changed to {}'
                                   .format(args[0], args[1], args[2]))
            return

        config[args[0]] = args[1]
        write_config()
        await ctx.channel.send('Configuration parameter {} has been changed to {}'.format(args[0], args[1]))

    def build_config_embed(self) -> Embed:
        """
        Building the config embed with all keys that are changeable current values.
        :return: discord.Embed
        """
        config_embed: Embed = Embed(title='Aura Configuration Menu',
                                    description='Shows all changeable configuration keys '
                                                + 'and their current values ',
                                    colour=embed_color)
        for key in config.keys():
            if key not in hidden_config:
                if isinstance(config[key], Mapping):
                    config_embed.add_field(name=f'**{key}**', value=config[key])
                    continue
                for other_key in config[key].keys():
                    config_embed.add_field(name=f'**{key} {other_key}**', value=config[key][other_key])

        config_embed = add_filler_fields(config_embed, config_embed.fields)
        config_embed.set_footer(
            text='token, owner, prefix, database, logging level only only changeable before runtime')
        return config_embed

    def build_config_help_embed(self, args) -> Embed:
        """
        Building the configuration help embed to provide more context on configuration value.
        :param args: configuration keys
        :return: discord.Embed
        """
        config_help_embed: Embed = Embed(colour=embed_color)
        # args[0] == help
        if len(args) == 2:
            config_help_embed.title = args[1]
            config_description = descriptions[args[1]]
        else:
            config_help_embed.title = args[1] + ' ' + args[2]
            config_description = descriptions[args[1]][args[2]]

        config_help_embed.description = config_description.description
        config_help_embed.add_field(name='Possible Values', value=self.build_possible_values(config_description.values))
        return config_help_embed

    def build_possible_values(self, values) -> str:
        """
        Using the ConfigDescriptions in config.py build a possible value list for the config help embed.
        :param values: list of values
        :return: result containing the values to show in the config help embed
        """
        if len(values) == 1:
            return values[0]
        result = ''
        for value in values:
            result += value + ", "
        return result[:-2]
