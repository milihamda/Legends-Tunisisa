# Single file for Pydroid / phone — paste this entire file as main.py
# Put your bot token below:

TOKEN = "YOUR_BOT_TOKEN_HERE"

import io
import json
import os

import aiohttp
import discord
from discord.ext import commands, tasks
from PIL import Image, ImageDraw, ImageFont

# --- Welcome card ---
BACKGROUND_URL = "https://i.imgur.com/XIoPv4J.png"
AVATAR_SIZE = (430, 430)
AVATAR_POSITION = (88, 243)
TEXT_POSITION = (768, 418)
FONT_SIZE = 52


async def build_welcome_card(member, background_url=BACKGROUND_URL):
    headers = {"User-Agent": "Mozilla/5.0"}
    async with aiohttp.ClientSession() as session:
        async with session.get(background_url, headers=headers) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to download background: HTTP {resp.status}")
            bg_bytes = await resp.read()
        avatar_bytes = await member.display_avatar.replace(size=512, format="png").read()

    background = Image.open(io.BytesIO(bg_bytes)).convert("RGBA")
    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")

    avatar = avatar.resize(AVATAR_SIZE)
    mask = Image.new("L", AVATAR_SIZE, 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.ellipse((0, 0) + AVATAR_SIZE, fill=255)

    circular_avatar = Image.new("RGBA", AVATAR_SIZE, (0, 0, 0, 0))
    circular_avatar.paste(avatar, (0, 0), mask=mask)
    background.paste(circular_avatar, AVATAR_POSITION, circular_avatar)

    draw = ImageDraw.Draw(background)
    try:
        font = ImageFont.truetype("arial.ttf", FONT_SIZE)
    except OSError:
        font = ImageFont.load_default()

    draw.text(TEXT_POSITION, member.display_name, font=font, fill="#f3cb53", anchor="mm")

    buffer = io.BytesIO()
    background.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


# --- Bot config ---
CREATE_CHANNEL_ID = 1517870390968582155
VERIFICATION_1_ID = 1517597478378143937
VERIFICATION_2_ID = 1517666468593143940
STAFF_ROLE_ID = 1517586424306598140
NOT_VERIFIED_ROLE_ID = 1517593118399139840
WELCOME_CHANNEL_ID = 1511674200543199333
BOY_ROLE_ID = 1517606739812417647
GIRL_ROLE_ID = 1517606871064776804
LEVEL_LOG_CHANNEL_ID = 1517921554510385242
DATA_BACKUP_CHANNEL_ID = 1518023858765168771
BOT_VOICE_CHANNEL_ID = 1518025649225470072
ROLE_LVL_10 = 1518012453001232526
ROLE_LVL_20 = 1518012596824047677
ROLE_LVL_30 = 1518012596824047677

intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, status=discord.Status.dnd)
owners = {}
user_levels = {}
DB_FILE = "levels_database.json"


class DummyVoiceClient(discord.VoiceProtocol):
    def __init__(self, client, channel):
        self.client = client
        self.channel = channel
        self._connected = False

    async def connect(self, *, timeout, reconnect, self_deaf=True, self_mute=True):
        await self.channel.guild.change_voice_state(channel=self.channel, self_deaf=self_deaf, self_mute=self_mute)
        self._connected = True

    async def disconnect(self, *, force=False):
        await self.channel.guild.change_voice_state(channel=None)
        self._connected = False

    async def on_voice_state_update(self, data):
        pass

    async def on_voice_server_update(self, data):
        pass

    def is_connected(self):
        return self._connected

    def is_playing(self):
        return False

    def stop(self):
        pass


async def load_database_from_discord():
    global user_levels
    await bot.wait_until_ready()
    channel = bot.get_channel(DATA_BACKUP_CHANNEL_ID)
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                user_levels = {int(k): v for k, v in json.load(f).items()}
                return
        except Exception:
            pass
    if channel:
        try:
            async for message in channel.history(limit=5):
                if message.author == bot.user and message.content.startswith("```json"):
                    data = json.loads(message.content.strip("```json").strip("```"))
                    user_levels = {int(k): v for k, v in data.items()}
        except Exception as e:
            print(f"Error loading cloud db: {e}")


async def save_database_to_discord():
    if not user_levels:
        return
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(user_levels, f, ensure_ascii=False, indent=4)
        channel = bot.get_channel(DATA_BACKUP_CHANNEL_ID)
        if channel:
            await channel.purge(limit=10, check=lambda m: m.author == bot.user)
            await channel.send(content=f"```json\n{json.dumps(user_levels, ensure_ascii=False, indent=2)}\n```")
    except Exception as e:
        print(f"Cloud backup failed: {e}")


async def _cleanup_empty_lounge_rooms(guild):
    """On startup: delete empty lounge rooms left from before a restart."""
    hub = guild.get_channel(CREATE_CHANNEL_ID)
    if not hub or not hub.category:
        return

    skip_ids = {CREATE_CHANNEL_ID, VERIFICATION_1_ID, VERIFICATION_2_ID, BOT_VOICE_CHANNEL_ID}
    lounge_prefix = "🎙️|"
    lounge_suffix = " ✓"
    legacy_lounge_suffix = "'s Lounge"

    for voice_channel in hub.category.voice_channels:
        if voice_channel.id in skip_ids:
            continue
        name = voice_channel.name
        is_lounge = (
            (name.startswith(lounge_prefix) and name.endswith(lounge_suffix))
            or name.endswith(legacy_lounge_suffix)
        )
        if not is_lounge:
            continue
        if voice_channel.members:
            owners[voice_channel.id] = _infer_lounge_owner(voice_channel)
            continue
        owners.pop(voice_channel.id, None)
        try:
            await voice_channel.delete(reason="Empty lounge cleanup after bot restart")
            print(f"Deleted empty lounge: {voice_channel.name}")
        except discord.Exception as e:
            print(f"Failed to delete {voice_channel.name}: {e}")


def _infer_lounge_owner(channel):
    for target, overwrite in channel.overwrites.items():
        if isinstance(target, discord.Member) and not target.bot and overwrite.manage_channels:
            return target.id
    humans = [m for m in channel.members if not m.bot]
    return humans[0].id if humans else None
    def __init__(self, channel):
        self.channel = channel
        options = [
            discord.SelectOption(label=m.display_name, value=str(m.id), emoji="👤")
            for m in channel.members if not m.bot
        ] or [discord.SelectOption(label="No members", value="none", disabled=True)]
        super().__init__(placeholder="Select member to kick...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message("Nobody to kick.", ephemeral=True)
        member = interaction.guild.get_member(int(self.values[0]))
        if member and member.voice and member.voice.channel.id == self.channel.id:
            await member.move_to(None)
            await interaction.response.send_message(f"Kicked **{member.display_name}**.", ephemeral=True)
        else:
            await interaction.response.send_message("User left the room.", ephemeral=True)


class KickView(discord.ui.View):
    def __init__(self, channel):
        super().__init__(timeout=60)
        self.add_item(KickUserSelect(channel))


class RenameModal(discord.ui.Modal, title="Change Room Name"):
    channel_name = discord.ui.TextInput(label="New name", max_length=30, required=True)

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction):
        await self.channel.edit(name=self.channel_name.value)
        await interaction.response.send_message(f"Renamed to **{self.channel_name.value}**.", ephemeral=True)


class ControlPanelView(discord.ui.View):
    def __init__(self, channel):
        super().__init__(timeout=None)
        self.channel = channel

    @discord.ui.button(label="Lock", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="lock_room")
    async def lock_button(self, interaction, button):
        if interaction.user.id != owners.get(self.channel.id):
            return await interaction.response.send_message("Only room owner.", ephemeral=True)
        for role_id in (BOY_ROLE_ID, GIRL_ROLE_ID):
            role = interaction.guild.get_role(role_id)
            if role:
                await self.channel.set_permissions(role, connect=False)
        await interaction.response.send_message("Locked.", ephemeral=True)

    @discord.ui.button(label="Unlock", style=discord.ButtonStyle.success, emoji="🔓", custom_id="unlock_room")
    async def unlock_button(self, interaction, button):
        if interaction.user.id != owners.get(self.channel.id):
            return await interaction.response.send_message("Only room owner.", ephemeral=True)
        for role_id in (BOY_ROLE_ID, GIRL_ROLE_ID):
            role = interaction.guild.get_role(role_id)
            if role:
                await self.channel.set_permissions(role, connect=True, view_channel=True, speak=True)
        await interaction.response.send_message("Unlocked.", ephemeral=True)

    @discord.ui.button(label="Rename", style=discord.ButtonStyle.primary, emoji="📝", custom_id="rename_room")
    async def rename_button(self, interaction, button):
        if interaction.user.id != owners.get(self.channel.id):
            return await interaction.response.send_message("Only room owner.", ephemeral=True)
        await interaction.response.send_modal(RenameModal(self.channel))

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.secondary, emoji="👞", custom_id="kick_member")
    async def kick_button(self, interaction, button):
        if interaction.user.id != owners.get(self.channel.id):
            return await interaction.response.send_message("Only room owner.", ephemeral=True)
        await interaction.response.send_message("Select member:", view=KickView(self.channel), ephemeral=True)

    @discord.ui.button(label="Level", style=discord.ButtonStyle.primary, emoji="📊", custom_id="check_my_level")
    async def check_level_button(self, interaction, button):
        data = user_levels.get(interaction.user.id, {"xp": 0, "level": 0})
        embed = discord.Embed(
            title="YOUR STATS",
            description=f"Level `{data['level']}` — XP `{data['xp']}`",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await load_database_from_discord()
    for guild in bot.guilds:
        await _cleanup_empty_lounge_rooms(guild)
    voice_channel = bot.get_channel(BOT_VOICE_CHANNEL_ID)
    if voice_channel:
        try:
            await voice_channel.connect(cls=DummyVoiceClient)
        except Exception as e:
            print(f"Voice join failed: {e}")
    update_levels_task.start()
    await bot.change_presence(status=discord.Status.dnd)


@bot.event
async def on_resumed():
    await bot.change_presence(status=discord.Status.dnd)


@tasks.loop(minutes=1.0)
async def update_levels_task():
    changed = False
    for guild in bot.guilds:
        log_channel = guild.get_channel(LEVEL_LOG_CHANNEL_ID)
        for vc in guild.voice_channels:
            if vc.id in [CREATE_CHANNEL_ID, VERIFICATION_1_ID, VERIFICATION_2_ID, BOT_VOICE_CHANNEL_ID]:
                continue
            if not vc.members:
                continue
            for member in vc.members:
                if member.bot or member.voice.self_deaf:
                    continue
                uid = member.id
                user_levels.setdefault(uid, {"xp": 0, "level": 0})
                user_levels[uid]["xp"] += 10
                new_lvl = min(user_levels[uid]["xp"] // 150, 1000)
                changed = True
                if new_lvl > user_levels[uid]["level"]:
                    user_levels[uid]["level"] = new_lvl
                    if log_channel:
                        await log_channel.send(f"{member.mention} reached Level {new_lvl}!")
    if changed:
        await save_database_to_discord()


@bot.command(name="level")
async def level_cmd(ctx, member: discord.Member = None):
    target = member or ctx.author
    data = user_levels.get(target.id, {"xp": 0, "level": 0})
    await ctx.send(f"{target.mention} — Level `{data['level']}` — XP `{data['xp']}`")


@bot.event
async def on_member_join(member):
    guild = member.guild
    role = guild.get_role(NOT_VERIFIED_ROLE_ID)
    if role:
        try:
            await member.add_roles(role)
        except Exception as e:
            print(f"Role error: {e}")

    welcome_channel = guild.get_channel(WELCOME_CHANNEL_ID)
    if not welcome_channel:
        return

    try:
        buffer = await build_welcome_card(member)
        file = discord.File(buffer, filename="welcome_card.png")
        embed = discord.Embed(
            title="GLORIOUS ARRIVAL!",
            description=f"Welcome {member.mention} to **{guild.name}**!",
            color=discord.Color.red(),
        )
        embed.set_image(url="attachment://welcome_card.png")
        await welcome_channel.send(content=f"Welcome {member.mention}!", file=file, embed=embed)
    except Exception as e:
        print(f"Welcome error: {e}")
        await welcome_channel.send(f"Welcome {member.mention}!")


@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild
    if after.channel and after.channel.id in [VERIFICATION_1_ID, VERIFICATION_2_ID]:
        if (before.channel is None or before.channel.id != after.channel.id) and any(r.id == NOT_VERIFIED_ROLE_ID for r in member.roles):
            staff = guild.get_role(STAFF_ROLE_ID)
            if staff:
                for s in staff.members:
                    if not s.bot:
                        try:
                            await s.send(f"Unverified user {member.mention} in {after.channel.name}")
                        except discord.Forbidden:
                            pass

    if after.channel and after.channel.id == CREATE_CHANNEL_ID:
        cat = after.channel.category
        ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False)}
        for rid in (BOY_ROLE_ID, GIRL_ROLE_ID):
            r = guild.get_role(rid)
            if r:
                ow[r] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
        ow[member] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True, manage_channels=True)
        new_vc = await guild.create_voice_channel(
            name=f"🎙️|{member.name} ✓", category=cat, overwrites=ow
        )
        owners[new_vc.id] = member.id
        await member.move_to(new_vc)
        await new_vc.send(embed=discord.Embed(title="Your lounge", description=f"Welcome {member.mention}!"), view=ControlPanelView(new_vc))

    if before.channel and before.channel.id in owners and not before.channel.members:
        owners.pop(before.channel.id, None)
        try:
            await before.channel.delete(reason="Empty lounge cleanup")
        except discord.HTTPException:
            pass


if TOKEN == "YOUR_BOT_TOKEN_HERE":
    raise SystemExit("Set TOKEN at the top of this file.")

bot.run(TOKEN)
