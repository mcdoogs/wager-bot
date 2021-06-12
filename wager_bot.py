import discord
import logging
import os
import wager_models
import asyncio
import schedule
from dotenv import load_dotenv
from discord.ext import commands
from wager_models import Wager, User, Emoji, session

# load our .env file and retrieve token, text, emoji ID's
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
WAGER_HELP_TEXT = os.getenv("WAGER_HELP_TEXT")
WAGER_FORMAT_TEXT = os.getenv("WAGER_FORMAT_TEXT")
WAGER_BRIEF_TEXT = os.getenv("WAGER_BRIEF_TEXT")
WELCOME_TEXT = os.getenv("WELCOME_TEXT")
APP_ENV = os.getenv("APP_ENV")

STARTING_MONEY = int(os.getenv("STARTING_MONEY"))
WEEKLY_MONEY = int(os.getenv("WEEKLY_MONEY"))

# set up logging to output to a file with formatted lines
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

# bot config
bot_intents = discord.Intents(
    guilds=True, 
    members=True, 
    emojis=True, 
    messages=True, 
    guild_messages=True, 
    dm_messages=True, 
    reactions=True, 
    dm_reactions=True)

bot = commands.Bot(intents=bot_intents, command_prefix='!')

# TODO: randomize phrase for money each time it's mentioned

# add the weekly money allotment to each user's balance
def distribute_money_recurring():
    for user in session.query(User).all():
        user.add_money(WEEKLY_MONEY)
        session.add(user)
    session.commit()

schedule.every().friday.at("18:00").do(distribute_money_recurring)