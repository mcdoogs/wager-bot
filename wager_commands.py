import discord
import logging
import os
import wager_models
from dotenv import load_dotenv
from discord.ext import commands
from wager_models import Wager, User, session

# load our .env file and retrieve token, text, emoji ID's
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
WAGER_HELP_TEXT = os.getenv("WAGER_HELP_TEXT")
WAGER_FORMAT_TEXT = os.getenv("WAGER_FORMAT_TEXT")
WAGER_BRIEF_TEXT = os.getenv("WAGER_BRIEF_TEXT")
STARTING_MONEY = int(os.getenv("STARTING_MONEY"))
WAGERIN = int(os.getenv("WAGERIN"))
WAGERWIN = int(os.getenv("WAGERWIN"))
WAGERLOSE = int(os.getenv("WAGERLOSE"))
# TODO: create the emojis when joining server? maybe store in DB table

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

# create a new user in the DB, give them starting money, and send a DM with instructions
def create_user(user_id):
    # TODO: how to handle a user in multiple servers?
    new_user = User(user_id, STARTING_MONEY)
    session.add(new_user)
    session.commit()
    return new_user
    # TODO: send DM to user with details on how to use

# find a user in our wager DB using their ID; creates a new user if not found
async def find_or_create_user(user_id):
    discord_user = bot.get_user(user_id)
    wager_user = session.query(User).filter_by(id=user_id).one_or_none()
    if wager_user is None: # the user doesn't exist yet
        try:
            wager_user = create_user(user_id) # create the new user
            await discord_user.send(f"you've been created in the wager system")
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
    reacted_message = await wager_channel.fetch_message(wager.create_message_id)
    message_url = f"https://discord.com/channels/{reacted_message.guild.id}/{reacted_message.channel.id}/{reacted_message.id}"

    # get the emojis we'll use
    in_emoji = bot.get_emoji(WAGERIN)
    win_emoji = bot.get_emoji(WAGERWIN)
    lose_emoji = bot.get_emoji(WAGERLOSE)

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

# check the wager's message for completion - i.e. there is exactly one win emoji from the wager's creator/taker, and exactly one lose emoji from the other
async def check_for_winner(wager):
    # initialize our winner/lose id's
    winner_id = None
    loser_id = None

    # get the emojis we'll use
    win_emoji = bot.get_emoji(WAGERWIN)
    lose_emoji = bot.get_emoji(WAGERLOSE)

    # get a discord object for the channel/message of the wager
    wager_channel = bot.get_channel(wager.channel_id)
    wager_message = await wager_channel.fetch_message(wager.create_message_id)

    # make a list of the users involved in the wager
    wager_user_ids = [wager.creator_id, wager.taker_id]

    # get a list of all the reactions on the wager
    reactions = wager_message.reactions

    # get a list of users who have used the :wagerwin: reaction
    win_users_iter = [reaction.users() for reaction in reactions if reaction.emoji.id == WAGERWIN]
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
    lose_users_iter = [reaction.users() for reaction in reactions if reaction.emoji.id == WAGERLOSE]
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
    
async def resolve_winner(wager, winner_id):
    # edit the original message
    # get a discord object for the channel/message/users of the wager
    wager_channel = bot.get_channel(wager.channel_id)
    wager_message = await wager_channel.fetch_message(wager.create_message_id)
    wager_creator_user = bot.get_user(wager.creator_id)
    wager_taker_user = bot.get_user(wager.taker_id)
    wager_winner_user = bot.get_user(winner_id)
    message_url = f"https://discord.com/channels/{wager_message.guild.id}/{wager_message.channel.id}/{wager_message.id}"

    if wager.creator_id == winner_id:
        wager_loser_user =  wager_taker_user
        loser_id = wager.taker_id
    else:
        wager_loser_user = wager_creator_user
        loser_id = wager.creator_id

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

# Display some debug stuff when logged in, and set status
@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')
    await bot.change_presence(activity=discord.Game(name='with !wagers'))

# Watch for reactions that match our custom emoji
@bot.event
async def on_raw_reaction_add(payload):
    emoji = payload.emoji
    if emoji.id == WAGERIN:
        # find a wager whose create_message has the same ID as the emoji message, AND is not yet accepted
        wager = session.query(Wager).filter(Wager.create_message_id == payload.message_id, Wager.accepted == False).one_or_none()
        if wager is not None:
            await accept_wager(wager, payload.user_id)
    if emoji.id == WAGERWIN or emoji.id == WAGERLOSE:
        # find a wager whose create_message has the same ID as the emoji message, AND is accepted but not yet completed
        wager = session.query(Wager).filter(Wager.create_message_id == payload.message_id, Wager.accepted == True, Wager.completed == False).one_or_none()
        if wager is not None:
            winner_id = await check_for_winner(wager) # check to see if this reaction confirms a winner for the wager
            if winner_id: # if we have a winner, complete the wager!
                await resolve_winner(wager, winner_id)

# TODO: create a DM with the bot and the two users?

# !start command to create a new user and give them starting money
@bot.command(
    name="start",
    aliases = ["begin", "create"],
    help = "This will set you up for taking part in `!wagers` and give you starting money!",
    brief = "Get set up for !wagers commands"
)
async def start(ctx):
    create_user(ctx.author.id)

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
    in_emoji = bot.get_emoji(WAGERIN) # get the emoji we want to display in the message
    create_message = await ctx.send(f"{ctx.author.display_name} wagered {new_wager.amount} - condition: **{new_wager.description}**.\nReact to **this** message with `:wagerin:` ({str(in_emoji)}) to accept the wager!") 
    
    # store the id of the message we sent so we can check for reactions on it later
    new_wager.create_message_id = create_message.id

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
    help="At this point, the command just outputs some info about existing wagers."
)
async def list_wagers(ctx):
    pass # TODO - actually return the wagers


bot.run(DISCORD_TOKEN)