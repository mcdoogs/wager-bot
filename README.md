wager-bot

## Requirements
Requires discord.py, sqlalchemy, schedule, and python-dotenv - see the requirements.txt file for details. To install automatically, run 'pip install -r requirements.txt'

## Local environment config
Create a new .env file by copying the .env.example file:
```bash
cp .env.example .env
```
Enter your discord bot's token.

Set the APP_ENV variable to either 'dev' or 'prod' to define the environment. Right now this only affects which emoji are loaded, but in the future could determine logging levels, etc