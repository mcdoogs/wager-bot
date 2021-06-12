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
    name="wager",
    aliases = ["create_wager", "bet", "betcha"],
    help = WAGER_HELP_TEXT,
    brief = WAGER_BRIEF_TEXT
)
async def wager(ctx, wager_amount: int, *, wager_text: str):
    in_emoji = bot.get_emoji(await find_or_create_emoji("wagerin", ctx.guild.id)) # get the emoji we want to add / display in message
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
    create_message = await ctx.send(f"{ctx.author.display_name} wagered {new_wager.amount} - condition: **{new_wager.description}**.\nReact to **this** message with `:wagerin:` ({str(in_emoji)}) to accept the wager!") 
    
    # pre-fill the 'in' emoji on the wager message
    await create_message.add_reaction(in_emoji)

    # store the id of the message we sent so we can check for reactions on it later
    new_wager.message_id = create_message.id

    # persist our wager
    session.add(new_wager)
    session.commit()

# handle errors occurring during wager creation
@wager.error
async def wager_handler(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send(WAGER_FORMAT_TEXT)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(WAGER_FORMAT_TEXT)
    else:
        await ctx.send("Unknown error creating wager")

# command to list existing wagers
@bot.command(
    name="list",
    aliases=["wagers", "list_wagers"],
    brief="List existing wagers",
    help="Outputs a list of your created and accepted wagers, along with their status and direct links."
)
async def list(ctx):
    separator = '\n-----------------------------------------------------------------------------'
    user = await find_or_create_user(ctx.author.id)
    created_wagers = user.created_wagers
    accepted_wagers = user.accepted_wagers
    content = "__**Your wagers:**__" + separator
    if not created_wagers and not accepted_wagers:
        content += "\n__You haven't participated in any wagers yet!__ Type `!help wager` to get started."
        await ctx.author.send(content)
    if created_wagers:
        content += "\n__Your created wagers:__" + separator
        for wager in created_wagers:
            # Get name of user who accepted, if anyone
            if wager.taker:
                taker_user = bot.get_user(wager.taker.id)
                if taker_user:
                    taker_name = taker_user.display_name
                else:
                    taker_name = "Deleted User"
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
            await ctx.author.send(content)
            content = ""
    
    if accepted_wagers:
        content += "\n__Your accepted wagers:__" + separator
        for wager in accepted_wagers:
            # Get creator name
            creator_user = bot.get_user(wager.creator_id)
            if creator_user:
                creator_name = creator_user.display_name
            else:
                creator_name = "Deleted user"
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
            content = ""
            

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
            await cancel_wager(cancel_id, user.id)
            

bot.run(DISCORD_TOKEN)
