import discord
from discord.ext import commands
import json
import sqlite3
import sys
from datetime import datetime
import re

# -------------------------
# Load config
# -------------------------

with open("token.json", "r") as f:
    config = json.load(f)

bots = config["bots"]

# -------------------------
# Choose bot
# -------------------------

print("Available bots:")

for name in bots:
    print(f" - {name}")

choice = input("Choose bot: ").strip()

if choice not in bots:
    print("Invalid bot name")
    sys.exit(1)

TOKEN = bots[choice]["token"]
PREFIX = bots[choice].get("prefix", "!")
DB = bots[choice].get("db",)

print(f"Starting bot: {choice}")

# -------------------------
# SQLite setup
# -------------------------

db = sqlite3.connect(DB)
cursor = db.cursor()

# example table (you can modify later)
# cursor.execute("""
# CREATE TABLE "user" (
# 	"userid"	INTEGER,
# 	"joined"	TEXT,
# 	"warns"	INTEGER,
# 	"warns_info"	TEXT
# );
# """)

# db.commit()

# -------------------------
# Discord setup
# -------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)


# -------------------------
# things using
# -------------------------

OWNER_ID = 1449033057779843217

def register_in_table(userid, joindate):
    cursor.execute(
        "INSERT INTO user (userid, joined) VALUES (?, ?)",
        (userid, joindate)
    )
    db.commit()

def is_whitelisted(user_id: int) -> bool:
    cursor.execute(
        "SELECT 1 FROM whitelist WHERE userid = ?",
        (user_id,)
    )
    return cursor.fetchone() is not None


import discord

def resolve_user(guild, input_str):
    input_str = input_str.strip()

    # --- Mention ---
    if input_str.startswith("<@") and input_str.endswith(">"):
        user_id = input_str.replace("<@", "").replace("<@!", "").replace(">", "")
        if user_id.isdigit():
            return int(user_id)

    # --- Raw user ID ---
    if input_str.isdigit():
        return int(input_str)

    input_lower = input_str.lower()

    # --- Exact match (username, display name, nickname) ---
    for member in guild.members:
        if (
            member.name.lower() == input_lower or
            member.display_name.lower() == input_lower
        ):
            return member.id

    # --- Partial match (contains text) ---
    for member in guild.members:
        if (
            input_lower in member.name.lower() or
            input_lower in member.display_name.lower()
        ):
            return member.id

    return None

def resolve_user_object(guild, user_id: int):
    member = guild.get_member(user_id)

    if member:
        return member  # full Member object

    return None  # not in server

async def resolve_channel(guild: discord.Guild, argument: str):
    argument = argument.strip()

    # 1️⃣ Check mention format <#1234567890>
    match = re.match(r"<#(\d+)>", argument)
    if match:
        channel_id = int(match.group(1))
        channel = guild.get_channel(channel_id)
        if channel:
            return channel
        try:
            return await guild.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden):
            return None

    # 2️⃣ Check if raw ID
    if argument.isdigit():
        channel_id = int(argument)
        channel = guild.get_channel(channel_id)
        if channel:
            return channel
        try:
            return await guild.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden):
            return None

    # 3️⃣ Check by name (remove # if included)
    if argument.startswith("#"):
        argument = argument[1:]
    channel = discord.utils.get(guild.channels, name=argument)
    return channel

# -------------------------
# Events
# -------------------------


@bot.event
async def on_member_join(member):
    joined_id = member.id
    datenow = datetime.now().isoformat()

    register_in_table(joined_id,datenow)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    print("------")

# -------------------------
# Example command
# -------------------------


@bot.command(help="Checks latency")
async def ping(ctx):
    latency = round(bot.latency * 1000)
    await ctx.send(f"Pong! {latency} ms")

@bot.command(help="shows this message")
async def help(ctx):
    embed = discord.Embed(title="Help", color=discord.Color.blue())

    for command in bot.commands:
        embed.add_field(
            name=f".{command.name}",
            value=command.help or "No description",
            inline=False
        )

    await ctx.send(embed=embed)

@bot.command(help="Warn a user")
async def warn(ctx, user_input, *, reason="No reason provided"):

    if not is_whitelisted(ctx.author.id):
        await ctx.send("You are not whitelisted.")
        return

    member = resolve_user_object(ctx.guild, resolve_user(ctx.guild, user_input))

    if member is None:
        await ctx.send("User not found.")
        return

    if member.bot:
        await ctx.send("Cannot warn bots.")
        return

    if member.id == ctx.author.id:
        await ctx.send("You cannot warn yourself.")
        return

    # insert warn
    cursor.execute(
        "INSERT INTO warns (offender_id, moderator_id, reason, date) VALUES (?, ?, ?, ?)",
        (
            member.id,
            ctx.author.id,  # still saved, but hidden
            reason,
            datetime.now().isoformat()
        )
    )

    warn_id = cursor.lastrowid  # get warn ID
    db.commit()

    # PUBLIC EMBED (no moderator shown)
    public_embed = discord.Embed(
        title="⚠️ User Warned",
        description=f"{member.mention} has been warned.",
        color=discord.Color.red(),
        timestamp=datetime.now()
    )

    public_embed.add_field(name="Warn ID", value=str(warn_id), inline=False)
    public_embed.add_field(name="Reason", value=reason, inline=False)

    public_embed.set_thumbnail(url=member.display_avatar.url)

    await ctx.send(embed=public_embed)

    # DM EMBED (also hides moderator)
    dm_embed = discord.Embed(
        title="⚠️ You were warned",
        description=f"You were warned in **{ctx.guild.name}**",
        color=discord.Color.red(),
        timestamp=datetime.now()
    )

    dm_embed.add_field(name="Warn ID", value=str(warn_id), inline=False)
    dm_embed.add_field(name="Reason", value=reason, inline=False)

    dm_embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)

    try:
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        await ctx.send("Could not DM the user (DMs closed).")


@bot.command(help="View moderation logs for a user")
async def modlogs(ctx, user_input):

    if not is_whitelisted(ctx.author.id):
        await ctx.send("You are not whitelisted.")
        return

    user_id = resolve_user(ctx.guild, user_input)

    if user_id is None:
        await ctx.send("User not found.")
        return

    cursor.execute(
        "SELECT warn_id, moderator_id, reason, date FROM warns WHERE offender_id = ? ORDER BY warn_id DESC",
        (user_id,)
    )

    results = cursor.fetchall()

    if not results:
        await ctx.send("No modlogs found.")
        return

    member = ctx.guild.get_member(user_id)

    if member:
        title_name = f"{member.name} ({member.id})"
        avatar = member.display_avatar.url
    else:
        title_name = f"User ID: {user_id}"
        avatar = None

    embed = discord.Embed(
        title="Moderation Logs",
        description=f"Showing warns for {title_name}",
        color=discord.Color.red()
    )

    if avatar:
        embed.set_thumbnail(url=avatar)

    for warn_id, mod_id, reason, date in results:
        embed.add_field(
            name=f"Warn ID: {warn_id}",
            value=(
                f"Moderator: <@{mod_id}>\n"
                f"Reason: {reason}\n"
                f"Date: {date}"
            ),
            inline=False
        )

    embed.set_footer(text=f"Total warns: {len(results)}")

    await ctx.send(embed=embed)

@bot.command(help="Deletes a warn by warn ID")
async def delwarn(ctx, warn_id: int):

    if not is_whitelisted(ctx.author.id):
        return await ctx.send("No permission.")

    cursor.execute(
        "SELECT offender_id, reason FROM warns WHERE warn_id = ?",
        (warn_id,)
    )

    warn = cursor.fetchone()

    if not warn:
        return await ctx.send("Warn not found.")

    cursor.execute(
        "DELETE FROM warns WHERE warn_id = ?",
        (warn_id,)
    )

    db.commit()

    embed = discord.Embed(
        title="Warn Removed",
        description=f"Warn ID `{warn_id}` deleted",
        color=discord.Color.green()
    )

    await ctx.send(embed=embed)

@bot.command(help="Register into whitelist")
async def whitelist(ctx, input_member):

    userid = resolve_user(ctx.guild, input_member)

    if userid is None:
        await ctx.send("User not found.")
        return

    cursor.execute("""
        INSERT INTO whitelist (userid) VALUES (?)
    """, (userid,))
    db.commit()

    member = ctx.guild.get_member(userid)

    if member:
        display_name = member.display_name

        payload = discord.Embed(
            title="Whitelist added",
            description=f"*{display_name}* added to whitelist",
            color=discord.Color.blue()
        )

        await ctx.send(embed=payload)

    else:
        await ctx.send(f"User ID `{userid}` added to whitelist.")
@bot.command(help="Removes from whitelist")
async def dewhitelist(ctx, input_member):
    userid = resolve_user(ctx.guild, input_member)

    if userid is None:
        await ctx.send("User not found")
        return

    cursor.execute("DELETE FROM whitelist WHERE userid = ?", (userid,))
    db.commit()

    if cursor.rowcount == 0:
        await ctx.send("User was not in whitelist.")
    else:
        await ctx.send("User removed from whitelist.")


@bot.command(help="Run raw SQL (OWNER ONLY)")
async def sqlrun(ctx, *, query):

    # owner lock
    if ctx.author.id != OWNER_ID:
        await ctx.send("You are not allowed to use this command.")
        return

    try:
        cursor.execute(query)

        # SELECT queries return results
        if query.strip().lower().startswith("select"):
            results = cursor.fetchall()

            if not results:
                await ctx.send("Query executed. No results.")
                return

            output = "\n".join(str(row) for row in results)

            if len(output) > 1900:
                output = output[:1900] + "\n... (truncated)"

            embed = discord.Embed(
                title="SQL Result",
                description=f"```sql\n{output}```",
                color=discord.Color.green()
            )

            await ctx.send(embed=embed)

        else:
            db.commit()

            embed = discord.Embed(
                title="SQL Executed",
                description="Query executed successfully.",
                color=discord.Color.blue()
            )

            await ctx.send(embed=embed)

    except Exception as e:

        embed = discord.Embed(
            title="SQL Error",
            description=f"```{e}```",
            color=discord.Color.red()
        )

        await ctx.send(embed=embed)

@bot.command(help="Kicks member")
async def kick(ctx,user_input,*,reason):
    userid = resolve_user(ctx.guild,user_input)
    pass


@bot.command()
async def join_vc(ctx, channel_arg: str = None):
    if channel_arg is None:
        # Default: join the author's VC
        if ctx.author.voice is None:
            await ctx.send("You're not in a voice channel.")
            return
        channel = ctx.author.voice.channel
    else:
        # Resolve by mention, ID, or name
        channel = await resolve_channel(ctx.guild, channel_arg)
        if channel is None or not isinstance(channel, discord.VoiceChannel):
            await ctx.send("Could not find that voice channel or it's not a voice channel.")
            return

    vc = ctx.voice_client
    if vc is None:
        print(f"Joined {channel.name}")
        await channel.connect()
    else:
        await vc.move_to(channel)

    await ctx.send(f"Joined *{channel.mention}*!")

@bot.command()
async def leave(ctx):
    vc = ctx.voice_client  # get the bot's current VC connection in this guild

    if vc is None:
        await ctx.send("I'm not in a voice channel!")
        return

    await vc.disconnect()  # leave the VC
    await ctx.send("Left the voice channel.")

# -------------------------
# Example SQLite usage
# -------------------------




# @bot.command()
# async def register(ctx):
#     user_id = ctx.author.id

#     cursor.execute(
#         "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
#         (user_id,)
#     )

#     db.commit()

#     await ctx.send("Registered in database.")

# -------------------------
# Run bot
# -------------------------

bot.run(TOKEN)