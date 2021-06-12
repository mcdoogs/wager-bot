# check to make sure the reactions are present in the DB *and* those ID's are present in the guild; add if necessary
async def validate_emojis(required_emojis, guild_id):
    for required_emoji in required_emojis:
        # find this emoji in the DB
        emoji = session.query(Emoji).filter(Emoji.name == required_emoji).one_or_none()
        if not emoji: # if it's not in our database, look for it in list of emojis and add to DB, or create a new one
            emoji_id = check_existing_emoji(required_emoji, guild_id) # see if it exists on the server already and get its ID
            if not emoji_id:
                emoji_id = await add_emoji(required_emoji, guild_id) # if it's not already in the server, create it
            emoji = Emoji(emoji_id, guild_id, required_emoji)
            session.add(emoji, guild_id)
        else: # if it is in our database, check to make sure it actually exists in the guild
            emoji_id = check_existing_emoji(required_emoji, guild_id)
            if not emoji_id: # if the emoji doesn't exist on the server, create a new one
                session.delete(emoji) # remove the incorrect entry in the DB
                emoji_id = await add_emoji(required_emoji, guild_id) # create a new one
                emoji = Emoji(emoji_id, guild_id, required_emoji)
                session.add(emoji, guild_id)
            elif not emoji_id == emoji.id: # if the emoji in the DB doesn't have the same ID as the emoji on the server, update the DB with server info
                session.delete(emoji) # remove the incorrect entry in the DB
                emoji = Emoji(emoji_id, guild_id, required_emoji) # add the existing emoji to the DB
                session.add(emoji, guild_id)
    session.commit()
            

# check the indicated guild for a required emoji; if found, return its ID
def check_existing_emoji(required_emoji, guild_id):
    guild = bot.get_guild(guild_id)
    emojis = guild.emojis
    for emoji in emojis:
        if emoji.name == required_emoji:
            return emoji.id
    return None

# add our custom emojis to the guild (use dev emoji if dev environment)
async def add_emoji(emoji, guild_id):
    if APP_ENV == "dev":
        path = "dev_emoji/"
    else:
        path = ""
    guild = bot.get_guild(guild_id)
    with open(f"{path}{emoji}.png", "rb") as image:
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
    accepting_user = bot.get_user(user_id)
    if accepting_user.bot: # we're a bot; ignore
        return
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
        await wager_channel.send(f"{accepting_user.mention}: Sorry, an unknown error occurred when retrieving your user information!")
        return
    
    # can't accept your own wager
    if wager.creator_id == user_id:
        await reacted_message.remove_reaction(in_emoji, accepting_user) # remove the offending reaction
        await accepting_user.send(f"You can't accept your own wager - your :wagerin: reaction has been removed")
        return

    # make sure nerds dont try anything fishy
    if wager.amount < 1:
        await accepting_user.send(f"{wager.amount}?! Thats not a real bet!")
        return

    # make sure we can afford the wager
    if not acceptor.can_afford(wager.amount):
        await reacted_message.remove_reaction(in_emoji, accepting_user) # remove the reaction, since we can't afford
        # get our money totals to send to the user in DM
        total_money = acceptor.money
        outstanding_money = acceptor.outstanding_money()
        available_money = total_money - outstanding_money
        await accepting_user.send(f"You don't have enough moolah to take that wager! \U0001F4B8\n**Description:** {wager.description}\n**Amount:** {wager.amount}\nYou've got {total_money} doubloons and {outstanding_money} are in outstanding bets, leaving {available_money} doubloons available!")
        return

    # update the DB with the info on taker
    wager.accept(acceptor.id)

    # edit the wager creation message with new text on how to win/lose the wager
    await reacted_message.edit(content=f"{wager_creator_user.display_name} wagered {wager.amount} - condition: **{wager.description}**.\n{accepting_user.display_name} accepted - winner react to **this** message with `:wagerwin:` ({str(win_emoji)}) and loser react with `:wagerlose:` ({str(lose_emoji)})")

    # pre-populate the emoji's that users can respond with
    await reacted_message.add_reaction(win_emoji)
    await reacted_message.add_reaction(lose_emoji)

    # send DM's to creator and acceptor
    await accepting_user.send(f"You've accepted a wager from {wager_creator_user.display_name} for {wager.amount}.\nCondition: {wager.description}\n{message_url}")
    await wager_creator_user.send(f"{accepting_user.display_name} accepted your wager!\n{message_url}")

async def cancel_wager(wager_id, user_id):
    wager = session.query(Wager).filter(Wager.id == wager_id, Wager.completed == False, Wager.creator_id == user_id).one_or_none()
    user = bot.get_user(user_id)
    if wager is None and user:
        await user.send(f"No outstanding wager with an ID of {wager_id} found")
    else:
        # get a discord object for the channel/message/guild of the wager
        wager_guild = bot.get_guild(wager.guild_id)
        wager_channel = bot.get_channel(wager.channel_id)
        wager_message = await wager_channel.fetch_message(wager.message_id)
        # cross that message out
        new_content = f"~~{wager_message.content}~~"
        await wager_message.edit(content=new_content)
        # delete from DB
        session.delete(wager)
        if user and wager_guild.get_member(user_id): # check to make sure they're still a member before messaging
            await user.send(f"Canceled bet with ID {wager_id}")
        session.commit()

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