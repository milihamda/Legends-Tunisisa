import asyncio
import json
import math
import os
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from welcome_card import build_welcome_card, AVATAR_SIZE, AVATAR_POSITION, FONT_SIZE
from level_up_card import build_level_up_card

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("Missing DISCORD_TOKEN. Copy .env.example to .env and add your bot token.")

CREATE_CHANNEL_ID = 1517870390968582155

SUPPORT_CHANNEL_ID = 1518020513174130769

VERIFICATION_1_ID = 1517597478378143937
VERIFICATION_2_ID = 1517666468593143940
STAFF_ROLE_ID = 1517586424306598140

NOT_VERIFIED_ROLE_ID = 1517593118399139840
WELCOME_CHANNEL_ID = 1511674200543199333

BOY_ROLE_ID = 1517606739812417647
GIRL_ROLE_ID = 1517606871064776804

# Support: user HAS any of these roles → no alert (staff/support team)
SUPPORT_NOTIFY_ROLE_IDS = [
    1511828976732209252,
    1517587986756141226,
    1518010456030183465,
    1518229368261054647,
    1518010188685246464,
    1517605837252853951,
    1517586424306598140,
]

# Support: DM sent to members who have these roles when a normal user joins
STAFF_ROLE_IDS = [
    STAFF_ROLE_ID,
    # Add more staff role IDs:
    # 1517586424306598140,
]

LEVEL_LOG_CHANNEL_ID = 1517921554510385242

DATA_BACKUP_CHANNEL_ID = 1518023858765168771
BOT_VOICE_CHANNEL_ID = 1518025649225470072
BOT_CHAT_CHANNEL_ID = int(os.getenv("BOT_CHAT_CHANNEL_ID", "1518023858765168771"))
BOT_CHAT_MESSAGE = os.getenv("BOT_CHAT_MESSAGE", "welcome to Bot-Chat")

# Server default: chat/voice-text notifications only on @mentions (not every message)
SET_DEFAULT_NOTIFICATIONS_ONLY_MENTIONS = os.getenv(
    "SET_DEFAULT_NOTIFICATIONS_ONLY_MENTIONS", "true"
).lower() in ("1", "true", "yes")

ROLE_LVL_10 = 1518012453001232526
ROLE_LVL_20 = 1518012596824047677
ROLE_LVL_30 = 1518012707553546421
ROLE_LVL_40 = 1518012815116468284
ROLE_LVL_50 = 1518012943940325406
ROLE_LVL_60 = 1518805640594850002
ROLE_LVL_70 = 1518805913530535987
ROLE_LVL_80 = 1518806076009746543
ROLE_LVL_90 = 1518806185896185936
ROLE_LVL_100 = 1518806344373637271

# Voice leveling: Lv1 = 5 min, Lv2 = +10 min (15 total), Lv3 = +15 min (30 total), ...
LEVEL_MINUTES_BASE = 5
MAX_VOICE_LEVEL = 1000


def voice_minutes_for_level(level: int) -> int:
    """Total voice minutes required to reach `level`."""
    return LEVEL_MINUTES_BASE * level * (level + 1) // 2


def level_from_voice_minutes(minutes: int) -> int:
    """Highest level reachable with `minutes` of voice time."""
    if minutes <= 0:
        return 0
    level = int((-1 + math.sqrt(1 + 8 * minutes / LEVEL_MINUTES_BASE)) // 2)
    return min(level, MAX_VOICE_LEVEL)


def minutes_for_next_level(current_level: int) -> int:
    """Minutes needed to go from `current_level` to the next level."""
    return LEVEL_MINUTES_BASE * (current_level + 1)


def _normalize_user_level_data(raw: dict) -> dict:
    if "voice_minutes" in raw:
        minutes = int(raw["voice_minutes"])
    else:
        minutes = int(raw.get("xp", 0)) // 10
    return {
        "voice_minutes": minutes,
        "level": level_from_voice_minutes(minutes),
    }


def _get_user_level_data(user_id: int) -> dict:
    return _normalize_user_level_data(user_levels.get(user_id, {}))


def _format_level_stats(user_data: dict) -> str:
    level = user_data["level"]
    minutes = user_data["voice_minutes"]
    remaining = max(0, voice_minutes_for_level(level + 1) - minutes)
    return (
        f"• **Current Level:** `Level {level}`\n"
        f"• **Voice Time:** `{minutes} min`\n"
        f"• **Next Level:** `{remaining} min` remaining"
    )


intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, status=discord.Status.dnd)

owners = {}
room_kinds = {}
owner_transfer_tasks = {}
OWNER_ABSENCE_SECONDS = 60
locked_rooms = set()
locked_room_members = {}
user_levels = {}
DB_FILE = "levels_database.json"
bot_chat_messages = {}

LOUNGE_ROOM_NAME_PREFIX = "🎙️|"
LOUNGE_ROOM_NAME_SUFFIX = " ✓"


def format_lounge_room_name(member_name: str) -> str:
    return f"{LOUNGE_ROOM_NAME_PREFIX}{member_name}{LOUNGE_ROOM_NAME_SUFFIX}"


JOIN_TO_CREATE_CHANNELS = {
    CREATE_CHANNEL_ID: {
        "name": "{member}",
        "title": "HUB CENTRAL INTERFACE",
        "kind": "lounge",
    },
    SUPPORT_CHANNEL_ID: {
        "name": "Support | {member}",
        "title": "SUPPORT ROOM",
        "kind": "support",
    },
    VERIFICATION_1_ID: {
        "name": "Verify | {member}",
        "title": "VERIFICATION ROOM",
        "kind": "verification",
    },
    VERIFICATION_2_ID: {
        "name": "Verify | {member}",
        "title": "VERIFICATION ROOM",
        "kind": "verification",
    },
}


async def _create_join_to_create_room(member, trigger_channel):
    """Create a private sub-room when a member joins a join-to-create voice channel."""
    config = JOIN_TO_CREATE_CHANNELS.get(trigger_channel.id)
    if not config:
        return

    guild = member.guild
    category = trigger_channel.category
    everyone_role = guild.default_role
    staff_role = guild.get_role(STAFF_ROLE_ID)
    boy_role = guild.get_role(BOY_ROLE_ID)
    girl_role = guild.get_role(GIRL_ROLE_ID)

    overwrites = {
        everyone_role: discord.PermissionOverwrite(view_channel=False, connect=False, send_messages=False),
    }

    if config["kind"] == "lounge":
        if boy_role:
            overwrites[boy_role] = discord.PermissionOverwrite(
                view_channel=True, connect=True, speak=True, send_messages=True
            )
        if girl_role:
            overwrites[girl_role] = discord.PermissionOverwrite(
                view_channel=True, connect=True, speak=True, send_messages=True
            )
    elif config["kind"] in ("support", "verification") and staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            send_messages=True,
            move_members=True,
        )

    overwrites[member] = discord.PermissionOverwrite(
        view_channel=True,
        connect=True,
        speak=True,
        send_messages=True,
        manage_channels=True,
    )

    me = guild.me
    if me:
        overwrites[me] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            send_messages=True,
            manage_channels=True,
            read_message_history=True,
        )

    if config["kind"] == "lounge":
        channel_name = format_lounge_room_name(member.name)
    else:
        channel_name = config["name"].format(member=member.name)
    new_channel = await guild.create_voice_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
    )
    owners[new_channel.id] = member.id
    room_kinds[new_channel.id] = config["kind"]
    await member.move_to(new_channel)

    await _send_room_control_panel(new_channel, member, kind=config["kind"])


async def _set_room_locked(channel, *, locked: bool):
    """Lock = whitelist current members + block everyone else from joining."""
    if locked:
        allowed = {m.id for m in channel.members if not m.bot}
        locked_room_members[channel.id] = allowed
        await channel.edit(user_limit=max(len(allowed), 1))
        locked_rooms.add(channel.id)
    else:
        locked_room_members.pop(channel.id, None)
        await channel.edit(user_limit=0)
        locked_rooms.discard(channel.id)
        await _restore_room_join_permissions(channel, channel.guild)


def _lounge_access_roles(guild):
    return [r for rid in (BOY_ROLE_ID, GIRL_ROLE_ID) if (r := guild.get_role(rid))]


async def _restore_room_join_permissions(channel, guild):
    """Fix Boy/Girl perms after old permission-based lock hid the room."""
    for role in _lounge_access_roles(guild):
        await channel.set_permissions(
            role,
            view_channel=True,
            connect=True,
            speak=True,
            send_messages=True,
        )


PANEL_EMOJI_LOCK = discord.PartialEmoji(name="50376", id=1518983212066668675)
PANEL_EMOJI_UNLOCK = discord.PartialEmoji(name="50375", id=1518983208224559214)
PANEL_EMOJI_RENAME = discord.PartialEmoji(name="50377", id=1518983214511820850)
PANEL_EMOJI_KICK = discord.PartialEmoji(name="50378", id=1518983216575414292)
PANEL_EMOJI_LEVEL = discord.PartialEmoji(name="50379", id=1518983219372884038)
PANEL_EMOJI_CROWN = discord.PartialEmoji(name="50399", id=1519035786002038915)

PANEL_EMOJI_FALLBACKS = {
    "lock": "🔒",
    "unlock": "🔓",
    "rename": "📝",
    "kick": "👞",
    "level": "📊",
    "transfer": "👑",
}


PANEL_EMOJI_CUSTOM = {
    "lock": PANEL_EMOJI_LOCK,
    "unlock": PANEL_EMOJI_UNLOCK,
    "rename": PANEL_EMOJI_RENAME,
    "kick": PANEL_EMOJI_KICK,
    "level": PANEL_EMOJI_LEVEL,
    "transfer": PANEL_EMOJI_CROWN,
}


def _get_panel_emojis(_guild=None):
    """Always use server custom emoji IDs; fallback only if Discord rejects the send."""
    return dict(PANEL_EMOJI_CUSTOM)


def _build_room_panel_embed(member, channel, kind="lounge"):
    description = (
        f"👑 • **Owner:** {member.mention}\n"
        f"🔊 • **Channel:** {channel.mention}\n\n"
        f"📋 • **Status:** Fully functional. Use the buttons below to manage your channel."
    )
    if kind == "support":
        description += "\n\n🛡️ • **Staff:** Staff members can join this room to help you."
    elif kind == "verification":
        description += "\n\n🛡️ • **Staff:** Please wait — a staff member will join to verify you."

    embed = discord.Embed(
        title="➕ Temporary Voice Control Panel",
        description=description,
        color=discord.Color.red(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"ID: {member.id} • Temp Voice System")
    return embed


def _cancel_owner_transfer(channel_id: int):
    task = owner_transfer_tasks.pop(channel_id, None)
    if task and not task.done():
        task.cancel()


async def _apply_owner_permissions(channel, old_owner_id: int, new_owner: discord.Member):
    guild = channel.guild
    member_overwrite = discord.PermissionOverwrite(
        view_channel=True,
        connect=True,
        speak=True,
        send_messages=True,
    )
    owner_overwrite = discord.PermissionOverwrite(
        view_channel=True,
        connect=True,
        speak=True,
        send_messages=True,
        manage_channels=True,
    )
    old_member = guild.get_member(old_owner_id)
    if old_member:
        await channel.set_permissions(old_member, overwrite=member_overwrite)
    await channel.set_permissions(new_owner, overwrite=owner_overwrite)


async def _transfer_room_ownership(
    channel: discord.VoiceChannel,
    new_owner: discord.Member,
    *,
    former_owner_id: int | None = None,
    transfer_reason: str = "auto",
):
    former_owner_id = former_owner_id or owners.get(channel.id)
    _cancel_owner_transfer(channel.id)
    owners[channel.id] = new_owner.id
    if former_owner_id:
        await _apply_owner_permissions(channel, former_owner_id, new_owner)
    kind = room_kinds.get(channel.id, "lounge")
    await _send_room_control_panel(channel, new_owner, kind=kind)
    if transfer_reason == "manual":
        notice = f"👑 {new_owner.mention} is now the room owner (transferred by the previous owner)."
    else:
        notice = (
            f"👑 {new_owner.mention} is now the room owner "
            f"(previous owner did not return within {OWNER_ABSENCE_SECONDS}s)."
        )
    try:
        await channel.send(notice)
    except discord.HTTPException:
        pass


async def _owner_absence_countdown(guild_id: int, channel_id: int, former_owner_id: int):
    try:
        await asyncio.sleep(OWNER_ABSENCE_SECONDS)
    except asyncio.CancelledError:
        return

    owner_transfer_tasks.pop(channel_id, None)
    guild = bot.get_guild(guild_id)
    if not guild:
        return
    channel = guild.get_channel(channel_id)
    if not channel or channel_id not in owners:
        return
    if owners.get(channel_id) != former_owner_id:
        return

    former = guild.get_member(former_owner_id)
    if former and former.voice and former.voice.channel and former.voice.channel.id == channel_id:
        return

    candidates = [m for m in channel.members if not m.bot and m.id != former_owner_id]
    if not candidates:
        return

    new_owner = random.choice(candidates)
    await _transfer_room_ownership(channel, new_owner, former_owner_id=former_owner_id)


def _schedule_owner_transfer(channel: discord.VoiceChannel, former_owner_id: int):
    if room_kinds.get(channel.id) != "lounge":
        return
    _cancel_owner_transfer(channel.id)
    task = asyncio.create_task(
        _owner_absence_countdown(channel.guild.id, channel.id, former_owner_id)
    )
    owner_transfer_tasks[channel.id] = task


async def _send_room_control_panel(channel, owner, embed=None, *, kind="lounge"):
    """Post control panel embed + buttons in the voice channel text chat."""
    if embed is None:
        embed = _build_room_panel_embed(owner, channel, kind)

    guild = channel.guild
    view = ControlPanelView(channel.id, emojis=_get_panel_emojis(guild))
    bot.add_view(view)

    try:
        await channel.send(
            content=f"{owner.mention} — open **chat** here to use the panel below.",
            embed=embed,
            view=view,
        )
    except discord.Forbidden:
        print(f"Cannot send control panel in {channel.name}: missing Send Messages permission")
        try:
            await owner.send(
                embed=discord.Embed(
                    title="Room created",
                    description=(
                        f"Your room **{channel.name}** is ready, but I could not post the control panel.\n"
                        "Move my bot role **above** other roles and give **Send Messages** in voice channels.\n"
                        "Then use `!panel` inside the room chat to repost it."
                    ),
                    color=discord.Color.orange(),
                )
            )
        except discord.Forbidden:
            pass
    except discord.HTTPException as exc:
        print(f"Control panel send failed in {channel.name}: {exc.text}")
        fallback_view = ControlPanelView(channel.id, emojis=PANEL_EMOJI_FALLBACKS)
        bot.add_view(fallback_view)
        try:
            await channel.send(
                content=f"{owner.mention} — open **chat** here to use the panel below.",
                embed=embed,
                view=fallback_view,
            )
        except discord.HTTPException as retry_exc:
            print(f"Control panel fallback send failed in {channel.name}: {retry_exc.text}")


async def _notify_roles_members(guild, role_ids, embed):
    notified = set()
    for role_id in role_ids:
        role = guild.get_role(role_id)
        if not role:
            continue
        for role_member in role.members:
            if role_member.bot or role_member.id in notified:
                continue
            notified.add(role_member.id)
            try:
                await role_member.send(embed=embed)
            except discord.Forbidden:
                pass


def _member_has_any_role(member, role_ids):
    member_role_ids = {r.id for r in member.roles}
    return any(rid in member_role_ids for rid in role_ids)


def _get_bot_chat_channel(guild):
    if BOT_CHAT_CHANNEL_ID:
        channel = guild.get_channel(BOT_CHAT_CHANNEL_ID)
        if channel:
            return channel
    return discord.utils.get(guild.text_channels, name="bot-chat")


async def _apply_guild_notification_settings(guild, *, force=False):
    """Set guild default notifications to @mentions only (Manage Server required)."""
    if not SET_DEFAULT_NOTIFICATIONS_ONLY_MENTIONS and not force:
        return False, "Auto setup is off. Use `!setnotifications` or enable `SET_DEFAULT_NOTIFICATIONS_ONLY_MENTIONS`."

    if guild.default_notifications == discord.NotificationLevel.only_mentions:
        return True, "Server notifications are already set to **@mentions only**."

    if not guild.me.guild_permissions.manage_guild:
        return False, "I need **Manage Server** permission to change this setting."

    try:
        await guild.edit(
            default_notifications=discord.NotificationLevel.only_mentions,
            reason="Legends bot: default chat notifications to @mentions only",
        )
        print(f"Set {guild.name} default notifications to @mentions only")
        return True, "Server default notifications updated to **@mentions only**."
    except discord.Forbidden:
        return False, "I cannot edit server settings (missing permission)."
    except discord.HTTPException as exc:
        return False, f"Discord API error: {exc.text}"


async def _refresh_bot_chat_welcome_message(guild):
    channel = _get_bot_chat_channel(guild)
    if not channel:
        return

    message_id = bot_chat_messages.get(guild.id)
    if message_id:
        try:
            await channel.fetch_message(message_id)
            return
        except discord.NotFound:
            bot_chat_messages.pop(guild.id, None)
        except discord.Forbidden:
            return

    message = await channel.send(BOT_CHAT_MESSAGE, suppress=True)
    bot_chat_messages[guild.id] = message.id


_JOIN_TO_CREATE_HUB_IDS = frozenset(JOIN_TO_CREATE_CHANNELS.keys())


def _temp_room_kind_from_name(channel_name: str) -> str | None:
    if channel_name.startswith(LOUNGE_ROOM_NAME_PREFIX) and channel_name.endswith(LOUNGE_ROOM_NAME_SUFFIX):
        return "lounge"
    if channel_name.endswith("'s Lounge"):
        return "lounge"
    if channel_name.startswith("Support | "):
        return "support"
    if channel_name.startswith("Verify | "):
        return "verification"
    return None


def _is_tracked_temp_room(channel_id: int) -> bool:
    return channel_id in owners or channel_id in room_kinds


def _clear_temp_room_tracking(channel_id: int):
    _cancel_owner_transfer(channel_id)
    owners.pop(channel_id, None)
    room_kinds.pop(channel_id, None)
    locked_rooms.discard(channel_id)
    locked_room_members.pop(channel_id, None)


def _infer_room_owner(channel: discord.VoiceChannel) -> discord.Member | None:
    for target, overwrite in channel.overwrites.items():
        if isinstance(target, discord.Member) and not target.bot and overwrite.manage_channels:
            return target
    humans = [m for m in channel.members if not m.bot]
    return humans[0] if humans else None


async def _delete_temp_voice_channel(channel: discord.VoiceChannel, *, reason: str):
    channel_id = channel.id
    _clear_temp_room_tracking(channel_id)
    try:
        await channel.delete(reason=reason)
    except discord.HTTPException as exc:
        print(f"Failed to delete temp room {channel.name}: {exc.text}")


async def _cleanup_and_register_temp_rooms(guild):
    """On startup: delete empty temp voice rooms; re-track occupied ones."""
    skip_ids = _JOIN_TO_CREATE_HUB_IDS | {BOT_VOICE_CHANNEL_ID}
    scanned_categories = set()

    for hub_id in _JOIN_TO_CREATE_HUB_IDS:
        hub = guild.get_channel(hub_id)
        if not hub or not hub.category:
            continue
        category = hub.category
        if category.id in scanned_categories:
            continue
        scanned_categories.add(category.id)

        for voice_channel in category.voice_channels:
            if voice_channel.id in skip_ids:
                continue

            kind = _temp_room_kind_from_name(voice_channel.name)
            if kind is None:
                continue

            if len(voice_channel.members) == 0:
                await _delete_temp_voice_channel(
                    voice_channel,
                    reason="Empty temp voice room cleanup after bot restart",
                )
                print(f"Deleted empty temp room: {voice_channel.name}")
                continue

            owner = _infer_room_owner(voice_channel)
            if owner:
                owners[voice_channel.id] = owner.id
            room_kinds[voice_channel.id] = kind
            print(
                f"Re-registered temp room: {voice_channel.name} "
                f"(kind={kind}, owner={owner.display_name if owner else 'unknown'})"
            )


# Game roles — replace role_id with real Discord role IDs (Developer mode → copy ID)
# Set role_id to 0 to skip a game until you add the ID.
GAME_ROLES = [
    {"label": "Free Fire", "role_id": 1518285374068232273, "emoji": "🔥", "description": "Click to select Free Fire"},
    {"label": "Rust", "role_id": 1518285498903166986, "emoji": "🛠️", "description": "Click to select Rust"},
    {"label": "Call of duty", "role_id": 1518285558089121842, "emoji": "🎯", "description": "Click to select Call of duty"},
    {"label": "GTA V", "role_id": 1518285631657082932, "emoji": "🚗", "description": "Click to select GTA V"},
    {"label": "Brawlhalla", "role_id": 1518286791382274211, "emoji": "⚔️", "description": "Click to select Brawlhalla"},
    {"label": "CS GO", "role_id": 1518286667360763914, "emoji": "💣", "description": "Click to select CS GO"},
    {"label": "Fortnite", "role_id": 1518286698277240912, "emoji": "🏝️", "description": "Click to select Fortnite"},
    {"label": "Valorant", "role_id": 1518270987882201168, "emoji": "🎮", "description": "Click to select Valorant"},
    {"label": "League of Legends", "role_id": 1518285800201257031, "emoji": "🧙", "description": "Click to select League of Legends"},
    {"label": "Minecraft", "role_id": 1518285836532056286, "emoji": "⛏️", "description": "Click to select Minecraft"},
]


def _active_game_roles():
    return [g for g in GAME_ROLES if g.get("role_id", 0)]


class GameRoleSelect(discord.ui.Select):
    def __init__(self):
        active = _active_game_roles()
        if not active:
            options = [
                discord.SelectOption(
                    label="No roles configured",
                    value="none",
                    description="Admin: set role_id in GAME_ROLES",
                    emoji="⚠️",
                )
            ]
            super().__init__(
                placeholder="Select your roles",
                min_values=0,
                max_values=1,
                options=options,
                custom_id="legends_game_role_picker",
                disabled=True,
            )
            return

        options = [
            discord.SelectOption(
                label=g["label"],
                value=str(g["role_id"]),
                description=g.get("description", f"Get the {g['label']} role"),
                emoji=g.get("emoji"),
            )
            for g in active[:25]
        ]
        super().__init__(
            placeholder="Select your roles",
            min_values=0,
            max_values=len(options),
            options=options,
            custom_id="legends_game_role_picker",
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values == ["none"]:
            return await interaction.response.send_message("Roles not configured yet.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        member = interaction.user
        guild = interaction.guild
        all_game_ids = {g["role_id"] for g in _active_game_roles()}
        selected_ids = {int(v) for v in self.values}

        game_roles = {
            role for rid in all_game_ids if (role := guild.get_role(rid)) is not None
        }
        new_roles = [role for role in member.roles if role not in game_roles]
        for rid in selected_ids:
            role = guild.get_role(rid)
            if role:
                new_roles.append(role)

        try:
            await member.edit(roles=new_roles, reason="Game role picker")
        except discord.Forbidden:
            return await interaction.followup.send(
                "I cannot assign these roles. Move my bot role **above** the game roles.",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            return await interaction.followup.send(
                f"Could not update roles right now. Try again in a moment. ({exc.text})",
                ephemeral=True,
            )

        if selected_ids:
            names = ", ".join(f"**{guild.get_role(rid).name}**" for rid in selected_ids if guild.get_role(rid))
            msg = f"Roles updated: {names}"
        else:
            msg = "All game roles removed."

        await interaction.followup.send(msg, ephemeral=True)


class GameRolePickerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GameRoleSelect())


class DummyVoiceClient(discord.VoiceProtocol):
    def __init__(self, client, channel):
        self.client = client
        self.channel = channel
        self._connected = False

    async def connect(self, *, timeout: float, reconnect: bool, self_deaf: bool = True, self_mute: bool = True) -> None:
        await self.channel.guild.change_voice_state(channel=self.channel, self_deaf=self_deaf, self_mute=self_mute)
        self._connected = True

    async def disconnect(self, *, force: bool = False) -> None:
        await self.channel.guild.change_voice_state(channel=None)
        self._connected = False
        try:
            key_id, _ = self.channel._get_voice_client_key()
            self.client._connection._remove_voice_client(key_id)
        except Exception:
            pass

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
                data = json.load(f)
                user_levels = {
                    int(k): _normalize_user_level_data(v) for k, v in data.items()
                }
                print("Loaded from local JSON file.")
                return
        except Exception:
            pass

    if channel:
        try:
            async for message in channel.history(limit=5):
                if message.author == bot.user and message.content.startswith("```json"):
                    clean_content = message.content.strip("```json").strip("```")
                    data = json.loads(clean_content)
                    user_levels = {
                        int(k): _normalize_user_level_data(v) for k, v in data.items()
                    }
                    print("Restored levels from Discord backup channel.")
                    with open(DB_FILE, "w", encoding="utf-8") as f:
                        json.dump(user_levels, f, ensure_ascii=False, indent=4)
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
            try:
                await channel.purge(limit=10, check=lambda m: m.author == bot.user)
            except Exception:
                pass

            formatted_data = {str(k): v for k, v in user_levels.items()}
            json_string = json.dumps(formatted_data, ensure_ascii=False, indent=2)

            await channel.send(
                content=f"```json\n{json_string}\n```",
                embed=discord.Embed(
                    title="AUTOMATIC DATA BACKUP SECURED",
                    description="Automated backup for server voice levels.\n**DO NOT DELETE THIS MESSAGE.**",
                    color=discord.Color.green(),
                ),
            )
    except Exception as e:
        print(f"Cloud backup failed: {e}")


class KickUserSelect(discord.ui.Select):
    def __init__(self, channel):
        self.channel = channel
        options = [
            discord.SelectOption(label=member.display_name, value=str(member.id), emoji="👤")
            for member in channel.members
            if not member.bot
        ]
        if not options:
            options = [discord.SelectOption(label="No other members inside the room", value="none", disabled=True)]

        super().__init__(placeholder="Select a member to kick out...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message("There is no one here to kick!", ephemeral=True)

        member_id = int(self.values[0])
        member = interaction.guild.get_member(member_id)

        if member and member.voice and member.voice.channel.id == self.channel.id:
            await member.move_to(None)
            await interaction.response.send_message(f"**{member.display_name}** has been kicked.", ephemeral=True)
        else:
            await interaction.response.send_message("User is no longer in your room.", ephemeral=True)


class KickView(discord.ui.View):
    def __init__(self, channel):
        super().__init__(timeout=60)
        self.add_item(KickUserSelect(channel))


class TransferOwnerSelect(discord.ui.Select):
    def __init__(self, channel, owner_id: int):
        self.channel = channel
        self.owner_id = owner_id
        options = [
            discord.SelectOption(label=member.display_name, value=str(member.id), emoji=PANEL_EMOJI_CROWN)
            for member in channel.members
            if not member.bot and member.id != owner_id
        ]
        if not options:
            options = [
                discord.SelectOption(label="No other members in the room", value="none", disabled=True)
            ]

        super().__init__(
            placeholder="Select the new room owner...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message(
                "There is no one else in the room to transfer ownership to.",
                ephemeral=True,
            )

        if interaction.user.id != owners.get(self.channel.id):
            return await interaction.response.send_message(
                "Only the room owner can transfer ownership.",
                ephemeral=True,
            )

        member_id = int(self.values[0])
        new_owner = interaction.guild.get_member(member_id)
        if not new_owner or not new_owner.voice or new_owner.voice.channel.id != self.channel.id:
            return await interaction.response.send_message(
                "That user is no longer in your room.",
                ephemeral=True,
            )

        await _transfer_room_ownership(
            self.channel,
            new_owner,
            former_owner_id=interaction.user.id,
            transfer_reason="manual",
        )
        await interaction.response.send_message(
            f"Ownership transferred to **{new_owner.display_name}**.",
            ephemeral=True,
        )


class TransferOwnerView(discord.ui.View):
    def __init__(self, channel, owner_id: int):
        super().__init__(timeout=60)
        self.add_item(TransferOwnerSelect(channel, owner_id))


class RenameModal(discord.ui.Modal, title="Change Room Name"):
    channel_name = discord.ui.TextInput(label="New Room Name", placeholder="Enter channel name...", max_length=30, required=True)

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        await self.channel.edit(name=self.channel_name.value)
        await interaction.response.send_message(f"Room name updated to: **{self.channel_name.value}**", ephemeral=True)


class ControlPanelView(discord.ui.View):
    def __init__(self, channel_id: int, emojis=None):
        super().__init__(timeout=None)
        self.channel_id = channel_id
        emojis = emojis or PANEL_EMOJI_FALLBACKS

        lock_btn = discord.ui.Button(
            label="Lock",
            style=discord.ButtonStyle.secondary,
            emoji=emojis["lock"],
            custom_id=f"legends:lock:{channel_id}",
            row=0,
        )
        lock_btn.callback = self.lock_button
        self.add_item(lock_btn)

        unlock_btn = discord.ui.Button(
            label="Unlock",
            style=discord.ButtonStyle.secondary,
            emoji=emojis["unlock"],
            custom_id=f"legends:unlock:{channel_id}",
            row=0,
        )
        unlock_btn.callback = self.unlock_button
        self.add_item(unlock_btn)

        rename_btn = discord.ui.Button(
            label="Rename",
            style=discord.ButtonStyle.secondary,
            emoji=emojis["rename"],
            custom_id=f"legends:rename:{channel_id}",
            row=0,
        )
        rename_btn.callback = self.rename_button
        self.add_item(rename_btn)

        kick_btn = discord.ui.Button(
            label="Kick",
            style=discord.ButtonStyle.secondary,
            emoji=emojis["kick"],
            custom_id=f"legends:kick:{channel_id}",
            row=1,
        )
        kick_btn.callback = self.kick_button
        self.add_item(kick_btn)

        transfer_btn = discord.ui.Button(
            label="Transfer",
            style=discord.ButtonStyle.secondary,
            emoji=PANEL_EMOJI_CROWN,
            custom_id=f"legends:transfer:{channel_id}",
            row=1,
        )
        transfer_btn.callback = self.transfer_button
        self.add_item(transfer_btn)

        level_btn = discord.ui.Button(
            label="Check Level",
            style=discord.ButtonStyle.secondary,
            emoji=emojis["level"],
            custom_id=f"legends:level:{channel_id}",
            row=2,
        )
        level_btn.callback = self.check_level_button
        self.add_item(level_btn)

    def _get_channel(self, interaction: discord.Interaction):
        return interaction.guild.get_channel(self.channel_id)

    async def lock_button(self, interaction: discord.Interaction):
        channel = self._get_channel(interaction)
        if not channel:
            return await interaction.response.send_message("Room no longer exists.", ephemeral=True)
        if interaction.user.id != owners.get(self.channel_id):
            return await interaction.response.send_message("Only the room creator can use these controls.", ephemeral=True)

        await _set_room_locked(channel, locked=True)
        count = len(locked_room_members.get(channel.id, set()))
        await interaction.response.send_message(
            f"Room locked — only the **{count}** people here can stay. "
            "If someone leaves, no one can take their place until you unlock.",
            ephemeral=True,
        )

    async def unlock_button(self, interaction: discord.Interaction):
        channel = self._get_channel(interaction)
        if not channel:
            return await interaction.response.send_message("Room no longer exists.", ephemeral=True)
        if interaction.user.id != owners.get(self.channel_id):
            return await interaction.response.send_message("Only the room creator can use these controls.", ephemeral=True)

        await _set_room_locked(channel, locked=False)
        await interaction.response.send_message("Room unlocked — others can join again.", ephemeral=True)

    async def rename_button(self, interaction: discord.Interaction):
        channel = self._get_channel(interaction)
        if not channel:
            return await interaction.response.send_message("Room no longer exists.", ephemeral=True)
        if interaction.user.id != owners.get(self.channel_id):
            return await interaction.response.send_message("Only the room creator can use these controls.", ephemeral=True)
        await interaction.response.send_modal(RenameModal(channel))

    async def kick_button(self, interaction: discord.Interaction):
        channel = self._get_channel(interaction)
        if not channel:
            return await interaction.response.send_message("Room no longer exists.", ephemeral=True)
        if interaction.user.id != owners.get(self.channel_id):
            return await interaction.response.send_message("Only the room creator can use these controls.", ephemeral=True)
        await interaction.response.send_message("Choose who to disconnect:", view=KickView(channel), ephemeral=True)

    async def transfer_button(self, interaction: discord.Interaction):
        channel = self._get_channel(interaction)
        if not channel:
            return await interaction.response.send_message("Room no longer exists.", ephemeral=True)
        if interaction.user.id != owners.get(self.channel_id):
            return await interaction.response.send_message(
                "Only the room owner can use these controls.",
                ephemeral=True,
            )

        others = [m for m in channel.members if not m.bot and m.id != interaction.user.id]
        if not others:
            return await interaction.response.send_message(
                "There is no one else in the room to transfer ownership to.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            "Choose who gets ownership:",
            view=TransferOwnerView(channel, interaction.user.id),
            ephemeral=True,
        )

    async def check_level_button(self, interaction: discord.Interaction):
        user_data = _get_user_level_data(interaction.user.id)
        embed_stats = discord.Embed(
            title="YOUR LIVE STATS",
            description=f"Hello {interaction.user.mention}!\n\n{_format_level_stats(user_data)}",
            color=discord.Color.blue(),
        )
        embed_stats.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed_stats, ephemeral=True)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    await load_database_from_discord()

    voice_channel = bot.get_channel(BOT_VOICE_CHANNEL_ID)
    if voice_channel:
        try:
            await voice_channel.connect(cls=DummyVoiceClient)
            print(f"Bot connected to voice lounge: {voice_channel.name}")
        except Exception as e:
            print(f"Failed to join static channel: {e}")

    update_levels_task.start()
    bot_chat_keepalive_task.start()
    bot.add_view(GameRolePickerView())

    for guild in bot.guilds:
        try:
            await guild.chunk()
            await _cleanup_and_register_temp_rooms(guild)
            for channel_id in list(room_kinds.keys()):
                ch = guild.get_channel(channel_id)
                emojis = _get_panel_emojis(guild) if ch else PANEL_EMOJI_FALLBACKS
                bot.add_view(ControlPanelView(channel_id, emojis=emojis))
            success, message = await _apply_guild_notification_settings(guild)
            if success and "updated" in message.lower():
                print(message)
            elif not success and SET_DEFAULT_NOTIFICATIONS_ONLY_MENTIONS:
                print(f"{guild.name}: {message}")
            await _refresh_bot_chat_welcome_message(guild)
        except Exception as e:
            print(f"Guild init failed for {guild.name}: {e}")

    await bot.change_presence(status=discord.Status.dnd)
    print("System online.")


@bot.event
async def on_resumed():
    await bot.change_presence(status=discord.Status.dnd)


@tasks.loop(minutes=1.0)
async def bot_chat_keepalive_task():
    for guild in bot.guilds:
        try:
            await _refresh_bot_chat_welcome_message(guild)
        except Exception as e:
            print(f"Bot chat keepalive failed for {guild.name}: {e}")


@bot_chat_keepalive_task.before_loop
async def before_bot_chat_keepalive_task():
    await bot.wait_until_ready()


@tasks.loop(minutes=1.0)
async def update_levels_task():
    data_changed = False
    for guild in bot.guilds:
        log_channel = guild.get_channel(LEVEL_LOG_CHANNEL_ID)
        for voice_channel in guild.voice_channels:
            if voice_channel.id in [
                CREATE_CHANNEL_ID,
                SUPPORT_CHANNEL_ID,
                VERIFICATION_1_ID,
                VERIFICATION_2_ID,
                BOT_VOICE_CHANNEL_ID,
            ] or len(voice_channel.members) == 0:
                continue

            for member in voice_channel.members:
                if member.bot or member.voice.self_deaf:
                    continue

                user_id = member.id
                user_data = _get_user_level_data(user_id)
                old_lvl = user_data["level"]
                user_data["voice_minutes"] += 1
                new_calculated_level = level_from_voice_minutes(user_data["voice_minutes"])
                user_data["level"] = new_calculated_level
                user_levels[user_id] = user_data

                data_changed = True

                if new_calculated_level > old_lvl:
                    current_lvl = new_calculated_level

                    if log_channel:
                        try:
                            buffer = await build_level_up_card(member, old_lvl, current_lvl)
                            image_file = discord.File(buffer, filename="level_up.png")
                            embed_lvl = discord.Embed(
                                title="LEVEL UP!",
                                description=(
                                    f"{member.mention} reached **Level {current_lvl}**.\n"
                                    f"*Voice Time: {user_data['voice_minutes']} min*"
                                ),
                                color=discord.Color.from_rgb(231, 76, 60),
                            )
                            embed_lvl.set_image(url="attachment://level_up.png")
                            await log_channel.send(file=image_file, embed=embed_lvl)
                        except Exception as e:
                            print(f"Level up card failed: {e}")
                            embed_lvl = discord.Embed(
                                title="LEVEL UP!",
                                description=(
                                    f"{member.mention} reached **Level {current_lvl}**.\n"
                                    f"*Voice Time: {user_data['voice_minutes']} min*"
                                ),
                                color=discord.Color.gold(),
                            )
                            embed_lvl.set_thumbnail(url=member.display_avatar.url)
                            await log_channel.send(embed=embed_lvl)

                    if current_lvl >= 10 and current_lvl < 20:
                        role = guild.get_role(ROLE_LVL_10)
                        if role and role not in member.roles:
                            await member.add_roles(role)
                    elif current_lvl >= 20 and current_lvl < 30:
                        role = guild.get_role(ROLE_LVL_20)
                        if role and role not in member.roles:
                            await member.add_roles(role)
                    elif current_lvl >= 30:
                        role = guild.get_role(ROLE_LVL_30)
                        if role and role not in member.roles:
                            await member.add_roles(role)

    if data_changed:
        await save_database_to_discord()


@bot.command(name="level")
async def check_user_level_cmd(ctx, member: discord.Member = None):
    target_member = member or ctx.author
    if target_member.bot:
        return await ctx.send("Bots do not have voice leveling profiles.")

    user_data = _get_user_level_data(target_member.id)

    embed_cmd = discord.Embed(
        title="ARENA LEVEL REGISTRY",
        description=f"Stats for: {target_member.mention}\n\n{_format_level_stats(user_data)}",
        color=discord.Color.from_rgb(46, 204, 113),
    )
    embed_cmd.set_thumbnail(url=target_member.display_avatar.url)
    embed_cmd.set_footer(text=f"Requested by {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed_cmd)


@bot.command(name="testlevelup")
async def test_levelup_cmd(ctx, member: discord.Member = None, old: int = None, new: int = None):
    """Preview level-up card (admin). Example: !testlevelup @user 2 3"""
    target = member or ctx.author
    user_data = _get_user_level_data(target.id)
    old_lvl = old if old is not None else max(0, user_data["level"] - 1)
    new_lvl = new if new is not None else user_data["level"]

    try:
        buffer = await build_level_up_card(target, old_lvl, new_lvl)
        image_file = discord.File(buffer, filename="level_up.png")
        embed = discord.Embed(
            title="LEVEL UP! (TEST)",
            description=f"Preview: **{old_lvl} → {new_lvl}** for {target.mention}",
            color=discord.Color.from_rgb(231, 76, 60),
        )
        embed.set_image(url="attachment://level_up.png")
        await ctx.send(file=image_file, embed=embed)
    except Exception as e:
        await ctx.send(f"Level up preview failed: {e}")


@bot.command(name="testwelcome")
async def test_welcome_cmd(ctx, member: discord.Member = None):
    """Preview welcome card without a new member joining."""
    target = member or ctx.author
    welcome_channel = ctx.guild.get_channel(WELCOME_CHANNEL_ID)
    if not welcome_channel:
        return await ctx.send("Welcome channel not found.")

    try:
        buffer = await build_welcome_card(target)
        image_file = discord.File(buffer, filename="welcome_card.png")
        embed = discord.Embed(
            title="GLORIOUS ARRIVAL! (TEST)",
            description=(
                f"Preview for {target.mention}\n\n"
                f"Config: size={AVATAR_SIZE[0]} pos={AVATAR_POSITION} font={FONT_SIZE}"
            ),
            color=discord.Color.from_rgb(231, 76, 60),
        )
        embed.set_image(url="attachment://welcome_card.png")
        await welcome_channel.send(content=f"Welcome test for {target.mention}", file=image_file, embed=embed)
        await ctx.send("Welcome preview sent.", delete_after=5)
    except Exception as e:
        await ctx.send(f"Welcome test failed: {e}")


@bot.command(name="panel", aliases=["controlpanel", "roompanel"])
async def repost_panel_cmd(ctx):
    """Repost room control panel in your current voice room."""
    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.send("Join your voice room first, then run `!panel` in its chat.", delete_after=10)

    channel = ctx.author.voice.channel
    is_bot_room = channel.id in owners or channel.id in room_kinds
    if not is_bot_room:
        return await ctx.send("This voice channel is not a bot-managed room.", delete_after=10)

    owner_id = owners.get(channel.id, ctx.author.id)
    if ctx.author.id != owner_id:
        return await ctx.send("Only the room owner can repost the control panel.", delete_after=10)

    owners.setdefault(channel.id, ctx.author.id)

    config_kind = room_kinds.get(channel.id, "lounge")
    await _send_room_control_panel(channel, ctx.author, kind=config_kind)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


def _is_bot_managed_voice_room(channel):
    return isinstance(channel, discord.VoiceChannel) and (
        channel.id in owners or channel.id in room_kinds
    )


async def _purge_channel_messages(channel):
    """Delete as many messages as Discord allows (bulk purge: last 14 days)."""
    total = 0
    while True:
        deleted = await channel.purge(limit=100)
        total += len(deleted)
        if len(deleted) < 100:
            break
    return total


@bot.command(name="clear", aliases=["clearchat", "purgechat", "purge"])
async def clear_chat_cmd(ctx):
    """Clear all messages in this chat (room owner or Manage Messages)."""
    channel = ctx.channel
    if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.Thread)):
        return await ctx.send("Use this in a text or voice chat.", delete_after=8)

    if _is_bot_managed_voice_room(channel):
        owner_id = owners.get(channel.id, ctx.author.id)
        if ctx.author.id != owner_id and not ctx.author.guild_permissions.manage_messages:
            return await ctx.send("Only the room owner can clear this chat.", delete_after=8)
    elif not ctx.author.guild_permissions.manage_messages:
        return await ctx.send("You need **Manage Messages** to clear this channel.", delete_after=8)

    if not ctx.guild.me.guild_permissions.manage_messages:
        return await ctx.send("I need **Manage Messages** to clear chat.", delete_after=8)

    try:
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass

        removed = await _purge_channel_messages(channel)
        msg = f"Chat cleared by **{ctx.author.display_name}** ({removed} message(s) removed)."
        if _is_bot_managed_voice_room(channel):
            msg += "\nUse `!panel` to repost the control panel."
        await channel.send(msg, delete_after=5)
    except discord.Forbidden:
        await channel.send("I cannot delete messages here.", delete_after=8)
    except discord.HTTPException as exc:
        await channel.send(f"Could not clear chat: {exc.text}", delete_after=8)


@bot.command(name="setnotifications", aliases=["mentionsonly", "notifmentions"])
@commands.has_permissions(manage_guild=True)
async def set_notifications_cmd(ctx):
    """Set server default notifications to @mentions only (admin)."""
    success, message = await _apply_guild_notification_settings(ctx.guild, force=True)
    color = discord.Color.green() if success else discord.Color.red()
    embed = discord.Embed(title="Notification Settings", description=message, color=color)
    embed.add_field(
        name="Important",
        value=(
            "Server default = **new members only**.\n"
            "**You** must set manually on your Discord:\n"
            "• Server icon → **Notification Settings** → **Only @mentions**\n"
            "• Right-click lounge category → **Notification Settings** → **Only @mentions**"
        ),
        inline=False,
    )
    await ctx.send(embed=embed)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="postroles")
@commands.has_permissions(manage_guild=True)
async def post_roles_cmd(ctx):
    """Post the game role picker menu (admin only)."""
    active = _active_game_roles()
    if not active:
        return await ctx.send(
            "No game roles configured. Edit **GAME_ROLES** in `bot.py` and set real `role_id` values."
        )

    lines = "\n".join(f"{g.get('emoji', '🎮')} @{g['label']}" for g in active)
    embed = discord.Embed(
        title="Select your roles",
        description=(
            "Choose your games below. The bot will assign the matching roles automatically.\n\n"
            f"{lines}\n\n"
            "You can select **multiple** games at once."
        ),
        color=discord.Color.purple(),
    )
    await ctx.send(embed=embed, view=GameRolePickerView())
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.event
async def on_member_join(member):
    guild = member.guild
    welcome_channel = guild.get_channel(WELCOME_CHANNEL_ID)

    not_verified_role = guild.get_role(NOT_VERIFIED_ROLE_ID)
    if not_verified_role:
        try:
            await member.add_roles(not_verified_role)
            print(f"Given Not Verified role to {member.name}")
        except Exception as e:
            print(f"Failed to give role: {e}")

    if not welcome_channel:
        return

    try:
        buffer = await build_welcome_card(member)
        image_file = discord.File(buffer, filename="welcome_card.png")

        embed_welcome = discord.Embed(
            title="GLORIOUS ARRIVAL!",
            description=(
                f"Welcome {member.mention} to **{guild.name}**!\n"
                f"Enjoy your stay here!\n\n"
                f"• **Member Name:** {member.name}\n"
                f"• **Registry Account:** #{guild.member_count}\n\n"
                f"Please head over to the verification rooms to confirm your account."
            ),
            color=discord.Color.from_rgb(231, 76, 60),
        )
        embed_welcome.set_image(url="attachment://welcome_card.png")

        content_msg = f"Welcome {member.mention}! The glamorous combatant has landed in **{guild.name}**!"
        await welcome_channel.send(content=content_msg, file=image_file, embed=embed_welcome)

    except Exception as e:
        print(f"Error generating welcome image: {e}")
        embed_fallback = discord.Embed(
            title="GLORIOUS ARRIVAL!",
            description=(
                f"Welcome {member.mention} to **{guild.name}**!\n\n"
                f"• **Member Name:** {member.name}\n"
                f"• **Registry Account:** #{guild.member_count}"
            ),
            color=discord.Color.from_rgb(231, 76, 60),
        )
        await welcome_channel.send(content=f"Welcome {member.mention}!", embed=embed_fallback)


@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild

    if after.channel and after.channel.id in locked_rooms and not member.bot:
        allowed = locked_room_members.get(after.channel.id, set())
        if member.id not in allowed:
            try:
                await member.move_to(None)
            except discord.HTTPException:
                pass
            return

    verification_hubs = {VERIFICATION_1_ID, VERIFICATION_2_ID}

    if after.channel and after.channel.id == SUPPORT_CHANNEL_ID:
        if before.channel is None or before.channel.id != after.channel.id:
            if not _member_has_any_role(member, SUPPORT_NOTIFY_ROLE_IDS):
                embed_alert = discord.Embed(
                    title="SUPPORT — NEW USER WAITING",
                    description=(
                        f"**User:** {member.mention} (`{member.name}`)\n"
                        f"**Room:** {after.channel.name}\n\n"
                        "A member joined Support. Please check their sub-room."
                    ),
                    color=discord.Color.orange(),
                )
                await _notify_roles_members(guild, STAFF_ROLE_IDS, embed_alert)

    if after.channel and after.channel.id in verification_hubs:
        if before.channel is None or before.channel.id != after.channel.id:
            has_not_verified_role = any(role.id == NOT_VERIFIED_ROLE_ID for role in member.roles)
            if has_not_verified_role:
                staff_role = guild.get_role(STAFF_ROLE_ID)
                if staff_role:
                    embed_alert = discord.Embed(
                        title="UNVERIFIED USER DETECTED IN VOICE",
                        description=f"**User:** {member.mention}\n**Room:** {after.channel.name}",
                        color=discord.Color.red(),
                    )
                    for staff_member in staff_role.members:
                        if not staff_member.bot:
                            try:
                                await staff_member.send(embed=embed_alert)
                            except discord.Forbidden:
                                pass

    if after.channel and after.channel.id in JOIN_TO_CREATE_CHANNELS:
        await _create_join_to_create_room(member, after.channel)

    if after.channel and after.channel.id in owners and member.id == owners[after.channel.id]:
        _cancel_owner_transfer(after.channel.id)

    if (
        before.channel
        and before.channel.id in owners
        and member.id == owners.get(before.channel.id)
        and len(before.channel.members) > 0
    ):
        _schedule_owner_transfer(before.channel, member.id)

    if before.channel and before.channel.id in locked_rooms:
        allowed = locked_room_members.get(before.channel.id)
        if allowed is not None:
            allowed.discard(member.id)
        try:
            await before.channel.edit(user_limit=max(len(before.channel.members), 1))
        except discord.HTTPException:
            pass

    if (
        before.channel
        and _is_tracked_temp_room(before.channel.id)
        and len(before.channel.members) == 0
    ):
        await _delete_temp_voice_channel(
            before.channel,
            reason="Empty temp voice room cleanup",
        )


class _HealthHandler(BaseHTTPRequestHandler):
    def _send_ok(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        self._send_ok()
        self.wfile.write(b"Legends Tunisia bot is running")

    def do_HEAD(self):
        self._send_ok()

    def log_message(self, format, *args):
        pass


def _start_health_server() -> None:
    port = int(os.environ.get("PORT", "8080"))
    HTTPServer(("0.0.0.0", port), _HealthHandler).serve_forever()


if __name__ == "__main__":
    if os.environ.get("PORT"):
        threading.Thread(target=_start_health_server, daemon=True).start()
    bot.run(TOKEN)
