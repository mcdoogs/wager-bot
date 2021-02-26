import discord
import logging
import os
from dotenv import load_dotenv
from discord.ext import commands

# load our .env file and retrieve token
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# set up logging to output to a file with formatted lines
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

bot = commands.Bot(command_prefix='!')

# a class representing a single wager
class Wager:
    def __init__(self, creator, amount, description):
        # details of the wager
        self.creator = creator
        self.amount = amount
        self.description = description

        # status of the wager
        self.accepted = False
        self.completed = False
        self.confirmed = False

@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')
    await bot.change_presence(activity=discord.Game(name='with !wagers'))

# command to create a new wager
@bot.command(
    name="create_wager",
    aliases = ["wager", "bet", "betcha"],
    help = '''Create a new wager with an amount that you are betting and a description.

- wager_amount must be a whole number written in numerical digits! e.g. 10 - entering 'ten' will confuse the robots.
- The `!wager` command, the amount, and the text describing your bet must be separated from each other by spaces.

Example:
!wager 25 that I can hit this shot''',
    brief = 'Create a new wager'
)
async def create_wager(ctx, wager_amount: int, *, wager_text: str):
    await ctx.message.add_reaction('\U0001F44D')
    wager_author = ctx.author
    new_wager = Wager(wager_author, wager_amount, wager_text)
    await ctx.send(f"{new_wager.creator} wagered {new_wager.amount} - condition: {new_wager.description}")

# handle errors occurring during wager creation
@create_wager.error
async def wager_handler(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send(
'''Sorry, I didn't understand your wager! Correct format for wagers is: 
> !wager **amount** *condition*
Example:
> !wager **25** *that I can hit this shot*
- **amount** must be a whole number written in numerical digits! e.g. 10 - entering 'ten' will confuse the robots.
- The `!wager` command, the amount, and the text describing your bet must be separated from each other by spaces.''')

# command to list existing wagers
@bot.command(
    name="list_wagers",
    aliases=["wagers", "list"],
    brief="List existing wagers",
    help="At this point, the command just outputs some info about existing wagers."
)
async def list_wagers(ctx):
    pass # todo - actually return the wagers

bot.run(DISCORD_TOKEN)