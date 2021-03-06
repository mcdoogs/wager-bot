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

schedule.every().thursday.at("18:20").do(distribute_money_recurring)
schedule.every().friday.at("18:00").do(distribute_money_recurring)

# check to make sure the reactions in the DB are actually present in the guild
async def validate_emojis(required_emojis, guild_id):
    for required_emoji in required_emojis:
    # check to make sure the wagerin emoji is present
        emoji = session.query(Emoji).filter(Emoji.name == required_emoji).one_or_none()
        if not emoji: # if it's not in our database...
            emoji_id = check_existing_emoji(required_emoji, guild_id) # see if it exists on the server already and get its ID
            if not emoji_id:
                emoji_id = await add_emoji(required_emoji, guild_id) # if it's not already in the server, create it
            emoji = Emoji(emoji_id, guild_id, required_emoji)
            session.add(emoji, guild_id)
    session.commit()
            

# check to see if the emojis are present in the guild, and not just saved in the DB
def check_existing_emoji(required_emoji, guild_id):
    guild = bot.get_guild(guild_id)
    emojis = guild.emojis
    for emoji in emojis:
        if emoji.name == required_emoji:
            return emoji.id
    return None

# add our custom emojis to the guild
async def add_emoji(emoji, guild_id):
    guild = bot.get_guild(guild_id)
    with open(f"{emoji}.png", "rb") as image:
        emoji = await guild.create_custom_emoji(name=emoji, image=image.read())
        return emoji.id

# get an emoji ID by name; creates a new emoji or updates database if not present
async def find_or_create_emoji(emoji_name, guild_id):
    emoji = session.query(Emoji).filter(Emoji.name == emoji_name, Emoji.guild_id == guild_id).one_or_none()
    if not emoji:
        validate_emojis(emoji_name, guild_id)
        emoji = session.query(Emoji).filter(Emoji.name == emoji_name, Emoji.guild_id == guild_id).one_or_none()
    return emoji.id

# find a user in our wager DB using their ID; creates a new user if not found
async def find_or_create_user(user_id):
    # TODO: how to handle a user in multiple servers?
    discord_user = bot.get_user(user_id)
    wager_user = session.query(User).filter_by(id=user_id).one_or_none()
    if wager_user is None: # the user doesn't exist yet
        try:
            wager_user = User(user_id, STARTING_MONEY) # create the new user
            session.add(wager_user)
            session.commit()
            await discord_user.send(WELCOME_TEXT)
        except: #error creating user
            await discord_user.send(f"Error creating user {discord_user.mention}!")
            return
    return wager_user

# accept a wager and send/edit related messages
async def accept_wager(wager, user_id):
    # get the discord objects for the channel, user, and message; generate a link to the message
    wager_channel = bot.get_channel(wager.channel_id)
    reaction_user = bot.get_user(user_id)
    wager_creator_user = bot.get_user(wager.creator_id)
    reacted_message = await wager_channel.fetch_message(wager.message_id)
    message_url = get_wager_link(wager)

    # get the emojis we'll use
    in_emoji = bot.get_emoji(await find_or_create_emoji("wagerin", wager.guild_id))
    win_emoji = bot.get_emoji(await find_or_create_emoji("wagerwin", wager.guild_id))
    lose_emoji = bot.get_emoji(await find_or_create_emoji("wagerlose", wager.guild_id))

    try:
        # get/create the user accepting the wager from the DB
        acceptor = await find_or_create_user(user_id)
    except: # error finding user
        await wager_channel.send(f"{reaction_user.mention}: Sorry, an unknown error occurred when retrieving your user information!")
        return
    
    # can't accept your own wager
    if wager.creator_id == user_id:
        await reacted_message.remove_reaction(in_emoji, reaction_user) # remove the offending reaction
        await reaction_user.send(f"You can't accept your own wager - your :wagerin: reaction has been removed")
        return

    # make sure nerds dont try anything fishy
    if wager.amount < 1:
        await reaction_user.send(f"{wager.amount}?! Thats not a real bet!")
        return

    # make sure we can afford the wager
    if not acceptor.can_afford(wager.amount):
        await reacted_message.remove_reaction(in_emoji, reaction_user) # remove the reaction, since we can't afford
        # get our money totals to send to the user in DM
        total_money = acceptor.money
        outstanding_money = acceptor.outstanding_money()
        available_money = total_money - outstanding_money
        await reaction_user.send(f"You don't have enough moolah to take that wager! \U0001F4B8\n**Description:** {wager.description}\n**Amount:** {wager.amount}\nYou've got {total_money} doubloons and {outstanding_money} are in outstanding bets, leaving {available_money} doubloons available!")
        return

    # update the DB with the info on taker
    wager.accept(acceptor.id)

    # edit the wager creation message with new text on how to win/lose the wager
    await reacted_message.edit(content=f"{wager_creator_user.display_name} wagered {wager.amount} - condition: **{wager.description}**.\n{reaction_user.display_name} accepted - winner reply to **this** message with `:wagerwin:` ({str(win_emoji)}) and loser reply with `:wagerlose:` ({str(lose_emoji)})")

    # send DM's to creator and acceptor
    await reaction_user.send(f"You've accepted a wager from {wager_creator_user.display_name} for {wager.amount}.\nCondition: {wager.description}\n{message_url}")
    await wager_creator_user.send(f"{reaction_user.display_name} accepted your wager!\n{message_url}")

# check the wager's message for completion - i.e. there is exactly one win emoji from the wager's creator/taker, and exactly one lose emoji from the other. returns winner_id if valid
async def check_for_winner(wager):
    # initialize our winner/lose id's
    winner_id = None
    loser_id = None

    # get the emojis we'll use
    win_emoji = bot.get_emoji(await find_or_create_emoji("wagerwin", wager.guild_id))
    lose_emoji = bot.get_emoji(await find_or_create_emoji("wagerlose", wager.guild_id))

    # get a discord object for the channel/message of the wager
    wager_channel = bot.get_channel(wager.channel_id)
    wager_message = await wager_channel.fetch_message(wager.message_id)

    # make a list of the users involved in the wager
    wager_user_ids = [wager.creator_id, wager.taker_id]

    # get a list of all the reactions on the wager
    reactions = wager_message.reactions

    # get a list of users who have used the :wagerwin: reaction
    win_users_iter = [reaction.users() for reaction in reactions if reaction.custom_emoji and reaction.emoji.id == await find_or_create_emoji("wagerwin", wager.guild_id)]
    if win_users_iter:
        win_users_list = await win_users_iter[0].flatten()

        # filter that list down to only the ID's of the users we care about (creator/taker)
        proposed_winner_ids = [user.id for user in win_users_list if user.id in wager_user_ids]

        # if more than one of our bettors has reacted with :wagerwin:, clear both and ignore; if exactly one has reacted, mark them winner
        if len(proposed_winner_ids) > 1:
            await wager_message.clear_reaction(win_emoji)
            return
        elif len(proposed_winner_ids) == 1:
            winner_id = proposed_winner_ids[0]

    # get a list of users who have used the :wagerlose: reaction
    lose_users_iter = [reaction.users() for reaction in reactions if reaction.custom_emoji and reaction.emoji.id == await find_or_create_emoji("wagerlose", wager.guild_id)]
    if lose_users_iter:
        lose_users_list = await lose_users_iter[0].flatten()

        # filter that list down to only the ID's of the users we care about (creator / taker)
        proposed_loser_ids = [user.id for user in lose_users_list if user.id in wager_user_ids]

        # if more than one of our bettors has reacted with :wagerlose:, clear both and ignore; if exactly one has reacted, mark them loser
        if len(proposed_loser_ids) > 1:
            await wager_message.clear_reaction(lose_emoji)
            return
        elif len(proposed_loser_ids) == 1:
            loser_id = proposed_loser_ids[0]

    if winner_id and loser_id:
        if winner_id == loser_id: # you can't win and lose the same bet
            await wager_message.remove_reaction(win_emoji, bot.get_user(winner_id))
            await wager_message.remove_reaction(lose_emoji, bot.get_user(loser_id))
            return
        # bet is complete!
        return winner_id

# handle winning a bet (messaging, money transfer, DB update)
async def resolve_winner(wager, winner_id):
    # edit the original message
    # get a discord object for the channel/message/users of the wager
    wager_channel = bot.get_channel(wager.channel_id)
    wager_message = await wager_channel.fetch_message(wager.message_id)
    wager_creator_user = bot.get_user(wager.creator_id)
    wager_taker_user = bot.get_user(wager.taker_id)
    wager_winner_user = bot.get_user(winner_id)
    message_url = f"https://discord.com/channels/{wager_message.guild.id}/{wager_message.channel.id}/{wager_message.id}"

    # set the winner and loser based off the winner ID we got passed
    if wager.creator_id == winner_id:
        wager_loser_user =  wager_taker_user
        loser_id = wager.taker_id
    else:
        wager_loser_user = wager_creator_user
        loser_id = wager.creator_id

    # edit the original message to reflect winner
    await wager_message.edit(content=f"{wager_creator_user.display_name} wagered {wager.amount} - condition: **{wager.description}**.\n{wager_winner_user.display_name} won the wager against {wager_loser_user.display_name}!")

    # send a DM to the participants
    await wager_winner_user.send(f"You won your wager against {wager_loser_user.display_name}! You have received {wager.amount}.\n{message_url}")
    await wager_loser_user.send(f"You lost your wager against {wager_winner_user.display_name}! You have lost {wager.amount}.\n{message_url}")

    # update in database (record winner, transfer money)
    wager.winner_id = winner_id
    wager.loser_id = loser_id
    wager.winner.add_money(wager.amount)
    wager.loser.remove_money(wager.amount)
    wager.completed = True
    session.add(wager)
    session.commit()

# generate a direct link to a wager message
def get_wager_link(wager):
    return f"https://discord.com/channels/{wager.guild_id}/{wager.channel_id}/{wager.message_id}"

# Display some debug stuff when logged in, and set status
@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')

    # change bot's presence info
    await bot.change_presence(activity=discord.Game(name='with !wagers'))

    # check for emojis
    guilds = bot.guilds
    for guild in guilds:
        await validate_emojis(["wagerin", "wagerwin", "wagerlose"], guild.id)

    # run schedule and check for jobs every second
    while True:
        # run_pending
        schedule.run_pending()
        await asyncio.sleep(1)

# Watch for reactions that match our custom emoji
@bot.event
async def on_raw_reaction_add(payload):
    emoji = payload.emoji
    if not emoji.is_custom_emoji: # if this isn't a custom emoji...
        return
    if emoji.id == await find_or_create_emoji("wagerin", payload.guild_id):
        # find a wager whose create_message has the same ID as the emoji message, AND is not yet accepted
        wager = session.query(Wager).filter(Wager.message_id == payload.message_id, Wager.accepted == False).one_or_none()
        if wager is not None:
            await accept_wager(wager, payload.user_id)
    if emoji.id == await find_or_create_emoji("wagerwin", payload.guild_id) or emoji.id == await find_or_create_emoji("wagerlose", payload.guild_id):
        # find a wager whose create_message has the same ID as the emoji message, AND is accepted but not yet completed
        wager = session.query(Wager).filter(Wager.message_id == payload.message_id, Wager.accepted == True, Wager.completed == False).one_or_none()
        if wager is not None:
            winner_id = await check_for_winner(wager) # check to see if this reaction confirms a winner for the wager
            if winner_id: # if we have a winner, complete the wager!
                await resolve_winner(wager, winner_id)

# !start command to create a new user and give them starting money
@bot.command(
    name="start",
    aliases = ["begin", "create"],
    help = "This will set you up for taking part in `!wagers` and give you starting money!",
    brief = "Get set up for !wagers commands"
)
async def start(ctx):
    await find_or_create_user(ctx.author.id)

# !wager / !bet command to create a new wager
@bot.command(
    name="create_wager",
    aliases = ["wager", "bet", "betcha"],
    help = WAGER_HELP_TEXT,
    brief = WAGER_BRIEF_TEXT
)
async def create_wager(ctx, wager_amount: int, *, wager_text: str):
    # check to see if wager was created in a DM
    if ctx.channel.type is discord.ChannelType.private:
        await ctx.send("Can't create a wager in a direct message, sorry")
        return
    
    # get the wager's creator and create in DB if necessary
    try:
        # get/create the user who is creating the wager
        wager_creator = await find_or_create_user(ctx.author.id)
    except: # error finding user
        await ctx.send(f"{ctx.author.mention}: Sorry, an unknown error occurred when retrieving your user information!")
        return

    # make sure nerds dont try to do negative wagers
    if wager_amount < 1:
        await ctx.author.send(f"You think that {wager_amount} is a real bet?!")
        await ctx.message.add_reaction('\U0001F44E')
        return

    # check to see if the creator can afford this wager
    if not wager_creator.can_afford(wager_amount): # if we can't afford this wager...
        # get our money totals to print out to the user
        total_money = wager_creator.money
        outstanding_money = wager_creator.outstanding_money()
        available_money = total_money - outstanding_money
        await ctx.author.send(f"You don't got the dough \U0001F4B8\nYou've got {total_money} doubloons and {outstanding_money} are in outstanding bets, leaving {available_money} doubloons available!") # send current money and amount of outstanding wagers
        await ctx.message.add_reaction('\U0001F4B8')
        return

    # like the original comment if everything's good (helpful for debug!)
    await ctx.message.add_reaction('\U0001F44D')

    # create wager
    new_wager = Wager(ctx.guild.id, ctx.channel.id, wager_creator.id, wager_amount, wager_text)
    
    # send confirmation message
    in_emoji = bot.get_emoji(await find_or_create_emoji("wagerin", ctx.guild.id)) # get the emoji we want to display in the message
    create_message = await ctx.send(f"{ctx.author.display_name} wagered {new_wager.amount} - condition: **{new_wager.description}**.\nReact to **this** message with `:wagerin:` ({str(in_emoji)}) to accept the wager!") 
    
    # store the id of the message we sent so we can check for reactions on it later
    new_wager.message_id = create_message.id

    # persist our wager
    session.add(new_wager)
    session.commit()

# handle errors occurring during wager creation
@create_wager.error
async def wager_handler(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send(WAGER_FORMAT_TEXT)
    else:
        await ctx.send("Unknown error creating wager")

# command to list existing wagers
@bot.command(
    name="list_wagers",
    aliases=["wagers", "list"],
    brief="List existing wagers",
    help="Outputs a list of your created and accepted wagers, along with their status and direct links."
)
async def list_wagers(ctx):
    separator = '\n-----------------------------------------------------------------------------'
    user = await find_or_create_user(ctx.author.id)
    created_wagers = user.created_wagers
    accepted_wagers = user.accepted_wagers
    content = "__**Your wagers:**__" + separator
    if not created_wagers and not accepted_wagers:
        content += "\n__You haven't participated in any wagers yet!__ Type `!help wager` to get started."
    if created_wagers:
        content += "\n__Your created wagers:__" + separator
        for wager in created_wagers:
            # Get name of user who accepted, if anyone
            if wager.taker:
                taker_name = bot.get_user(wager.taker.id).display_name
            else:
                taker_name = "Nobody"
            
            # Get status
            if wager.completed:
                status = "Complete"
                if wager.winner_id == ctx.author.id:
                    winner_name = "You"
                else:
                    winner_name = taker_name
                winner_text = f"**Winner:** {winner_name}"
            elif wager.accepted:
                status = "Accepted"
                winner_text = ""
            else:
                status = "Created"
                winner_text = ""

            # build the message content for this wager
            content += f"\n**Amount:** {wager.amount} **Accepted by:** {taker_name} **Status:** {status} {winner_text}"
            content += f"\n**Description:** {wager.description}"
            content += f"\n**Link:** {get_wager_link(wager)}"
            content += separator
    
    if accepted_wagers:
        content += "\n__Your accepted wagers:__" + separator
        for wager in accepted_wagers:
            # Get creator name
            creator_name = bot.get_user(wager.creator_id).display_name
            # Get status
            if wager.completed:
                status = "Complete"
                if wager.winner_id == ctx.author.id:
                    winner_name = "You"
                else:
                    winner_name = creator_name
                winner_text = f"**Winner:** {winner_name}"
            else:
                status = "Accepted"
                winner_text = ""

            # build the message content for this wager
            content += f"\n**Amount:** {wager.amount} **Created by:** {creator_name} **Status:** {status} {winner_text}"
            content += f"\n**Description:** {wager.description}"
            content += f"\n**Link:** {get_wager_link(wager)}"
            content += separator
    
    await ctx.author.send(content)
            

@bot.command(
    name="money",
    brief="Show information about your imaginary money",
    help="Lists your total money, as well as what money you have currently tied up in bets."
)
async def money(ctx):
    user = await find_or_create_user(ctx.author.id)
    await ctx.author.send(f"You have {user.money} doubloons, {user.outstanding_money()} of which are tied up in outstanding bets. This leaves you {user.money - user.outstanding_money()} available.")

# TODO: maybe remove the bet 'taker' from DB if they remove the 'in' emoji?

@bot.command(
    name="cancel",
    brief="Cancel one of your oustanding bets",
    help="Without any arguments, this command will list your outstanding bets and a unique ID for each - to cancel a bet, use that ID in the cancel command e.g. '!cancel 13'. You can cancel multiple bets by separating the IDs with spaces."
)
async def cancel(ctx, *cancel_ids: int):
    user = await find_or_create_user(ctx.author.id)
    if not cancel_ids:
        separator = '\n-----------------------------------------------------------------------------'
        wagers = [created_wager for created_wager in user.created_wagers if created_wager.completed == False]
        content = "__**Your Outstanding Wagers**__  (Cancel with !cancel `id`)" + separator
        for wager in wagers:
            content += f"\n**ID:** {wager.id} **Amount:** {wager.amount}\n**Description:** {wager.description}\n**Link:** {get_wager_link(wager)}" + separator
        await bot.get_user(user.id).send(content)
    else:
        for cancel_id in cancel_ids:
            wager = session.query(Wager).filter(Wager.id == cancel_id, Wager.completed == False, Wager.creator_id == ctx.author.id).one_or_none()
            if wager is None:
                await bot.get_user(user.id).send(f"No outstanding wager with an ID of {cancel_id} found")
            else:
                # get a discord object for the channel/message of the wager
                wager_channel = bot.get_channel(wager.channel_id)
                wager_message = await wager_channel.fetch_message(wager.message_id)
                # cross that message out
                new_content = f"~~{wager_message.content}~~"
                await wager_message.edit(content=new_content)
                # delete from DB
                session.delete(wager)
                await bot.get_user(user.id).send(f"Canceled bet with ID {cancel_id}")
        session.commit()
            

bot.run(DISCORD_TOKEN)
