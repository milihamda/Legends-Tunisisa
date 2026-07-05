import asyncio
import io
import json
import math
import os
import random
import re
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import discord
from discord.abc import Messageable
from discord.ext import commands, tasks
from dotenv import load_dotenv

from welcome_card import build_welcome_card, AVATAR_SIZE, AVATAR_POSITION, FONT_SIZE
from level_up_card import build_level_up_card
from punishment_card import LABELS as PUNISHMENT_LABELS, build_punishment_card

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

TICKET_PANEL_CHANNEL_ID = 1522527871887998987
TICKET_LOG_CHANNEL_ID = 1522527871887998987
TICKET_CATEGORY_ID = 1523436013337448638
_env_ticket_cat = os.getenv("TICKET_CATEGORY_ID", "").strip()
if _env_ticket_cat and _env_ticket_cat not in ("0", "none", "false"):
    TICKET_CATEGORY_ID = int(_env_ticket_cat)

TICKET_CATEGORIES = {
    "support": {
        "label": "Support",
        "emoji": "🛡️",
        "description": "General help and questions",
        "button_style": discord.ButtonStyle.primary,
    },
    "report": {
        "label": "Report",
        "emoji": "⚠️",
        "description": "Report a user or rule break",
        "button_style": discord.ButtonStyle.danger,
    },
    "bugs": {
        "label": "Bugs",
        "emoji": "🐛",
        "description": "Report a bug or technical issue",
        "button_style": discord.ButtonStyle.secondary,
    },
}

TICKET_PANEL_TITLE = "🎫 Support Tickets"
TICKET_TOPIC_PREFIX = "legends-ticket:"

LEVEL_LOG_CHANNEL_ID = 1517921554510385242
PUNISHMENT_LOG_CHANNEL_ID = 1522676265381793876

DATA_BACKUP_CHANNEL_ID = 1518023858765168771
BOT_VOICE_CHANNEL_ID = 1518025649225470072
BOT_CHAT_CHANNEL_ID = int(os.getenv("BOT_CHAT_CHANNEL_ID", "1518023858765168771"))
BOT_CHAT_MESSAGE = os.getenv("BOT_CHAT_MESSAGE", "welcome to Bot-Chat")
BOT_BUILD_ID = "2026-07-05-tickets-only-cat"

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


def _iter_level_voice_channels(guild: discord.Guild):
    """Voice + stage channels where voice time can count."""
    excluded = {
        CREATE_CHANNEL_ID,
        SUPPORT_CHANNEL_ID,
        VERIFICATION_1_ID,
        VERIFICATION_2_ID,
        BOT_VOICE_CHANNEL_ID,
    }
    for channel in (*guild.voice_channels, *guild.stage_channels):
        if channel.id in excluded or not channel.members:
            continue
        yield channel


def _start_background_tasks():
    if not update_levels_task.is_running():
        update_levels_task.start()
    if not bot_chat_keepalive_task.is_running():
        bot_chat_keepalive_task.start()
    if not empty_temp_rooms_cleanup_task.is_running():
        empty_temp_rooms_cleanup_task.start()


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
DATA_DIR = Path("data")
DB_FILE = str(DATA_DIR / "levels_database.json")
LEGACY_DB_FILE = "levels_database.json"
bot_chat_messages = {}
ticket_counters: dict[int, int] = {}
open_tickets_by_user: dict[int, int] = {}
ticket_channels: dict[int, dict] = {}
WARNINGS_FILE = str(DATA_DIR / "warnings_database.json")
user_warnings: dict[int, int] = {}
MAX_WARNS_BEFORE_BAN = 3

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


def _list_guild_category_ids(guild: discord.Guild) -> str:
    if not guild.categories:
        return "(no categories visible to bot)"
    return ", ".join(f"{cat.name}={cat.id}" for cat in guild.categories)


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
        name=channel_name[:100],
        category=category,
        overwrites=overwrites,
        reason=f"Temp {config['kind']} room for {member}",
    )
    cat_name = getattr(category, "name", "none") if category else "none"
    print(f"Temp room created: {new_channel.name} → category {cat_name}")
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

    chat_text = (BOT_CHAT_MESSAGE or "welcome to Bot-Chat")[:2000]
    message = await channel.send(chat_text)
    bot_chat_messages[guild.id] = message.id


def _ticket_topic(user_id: int, category_key: str) -> str:
    return f"{TICKET_TOPIC_PREFIX}uid={user_id};cat={category_key}"


def _parse_ticket_topic(topic: str | None) -> dict | None:
    if not topic or not topic.startswith(TICKET_TOPIC_PREFIX):
        return None
    payload = topic[len(TICKET_TOPIC_PREFIX) :]
    data = {}
    for part in payload.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        data[key] = value
    if "uid" not in data or "cat" not in data:
        return None
    try:
        data["uid"] = int(data["uid"])
    except ValueError:
        return None
    return data


def _sanitize_ticket_slug(name: str, *, max_len: int = 18) -> str:
    cleaned = re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-"))
    return (cleaned[:max_len] or "user")


def _resolve_ticket_category(guild: discord.Guild) -> discord.CategoryChannel | None:
    """Resolve ticket category — same pattern as the reference ticket bot."""
    category_id = TICKET_CATEGORY_ID
    category = guild.get_channel(category_id)
    if isinstance(category, discord.CategoryChannel):
        return category
    category = discord.utils.get(guild.categories, id=category_id)
    if category:
        return category
    return None


def _ticket_channel_name(member: discord.Member, category_key: str) -> str:
    slug = _sanitize_ticket_slug(member.name, max_len=24)
    return f"ticket-{category_key}-{slug}"[:100]


def _find_open_ticket_channel(
    guild: discord.Guild,
    member: discord.Member,
    category: discord.CategoryChannel,
    *,
    category_key: str,
) -> discord.TextChannel | None:
    if member.id in open_tickets_by_user:
        existing = guild.get_channel(open_tickets_by_user[member.id])
        if isinstance(existing, discord.TextChannel):
            return existing

    channel_name = _ticket_channel_name(member, category_key)
    return discord.utils.get(guild.text_channels, name=channel_name, category=category)


def _is_ticket_text_channel(channel: discord.abc.GuildChannel) -> bool:
    if not isinstance(channel, discord.TextChannel):
        return False
    if channel.id in ticket_channels:
        return True
    if _parse_ticket_topic(channel.topic):
        return True
    if TICKET_CATEGORY_ID and channel.category_id == TICKET_CATEGORY_ID:
        return channel.name.startswith("ticket-")
    return False


def _is_ticket_staff(member: discord.Member) -> bool:
    if member.guild_permissions.manage_guild:
        return True
    staff_role = member.guild.get_role(STAFF_ROLE_ID)
    return bool(staff_role and staff_role in member.roles)


def _get_ticket_panel_channel(guild: discord.Guild):
    if TICKET_PANEL_CHANNEL_ID:
        channel = guild.get_channel(TICKET_PANEL_CHANNEL_ID)
        if channel:
            return channel
    return None


async def _log_ticket_message_to_staff(message: discord.Message):
    """Notify staff log channel when a user writes in a ticket (reference bot behavior)."""
    if not isinstance(message.channel, discord.TextChannel) or not message.guild:
        return
    if message.channel.category_id != TICKET_CATEGORY_ID:
        return
    if _is_ticket_staff(message.author):
        return

    history = [msg async for msg in message.channel.history(limit=20)]
    user_messages = [msg for msg in history if msg.author == message.author]
    if len(user_messages) == 1:
        await message.channel.send("Oki la74a taw ijik chkon ya7ki ma3ak")

    log_channel = message.guild.get_channel(TICKET_LOG_CHANNEL_ID)
    if not log_channel:
        return

    preview = message.content[:500] if message.content else "(attachment/embed)"
    try:
        await log_channel.send(
            f"🔔 <@&{STAFF_ROLE_ID}> **[Ticket - {message.author.name}]** "
            f"fil chat `{message.channel.name}`:\n> {preview}"
        )
    except discord.HTTPException as exc:
        print(f"Ticket staff log failed: {exc}")


def _get_staff_ticket_roles(guild: discord.Guild):
    role_ids = {STAFF_ROLE_ID, *SUPPORT_NOTIFY_ROLE_IDS}
    roles = []
    seen = set()
    for role_id in role_ids:
        if role_id in seen:
            continue
        seen.add(role_id)
        role = guild.get_role(role_id)
        if role:
            roles.append(role)
    return roles


def _build_ticket_panel_embed() -> discord.Embed:
    lines = "\n".join(
        f"{cat['emoji']} **{cat['label']}** — {cat['description']}"
        for cat in TICKET_CATEGORIES.values()
    )
    return discord.Embed(
        title=TICKET_PANEL_TITLE,
        description=(
            "Need help? Open a private ticket using one of the buttons below.\n"
            "Staff will respond as soon as possible.\n\n"
            f"{lines}"
        ),
        color=discord.Color.from_rgb(88, 101, 242),
    ).set_footer(text="One open ticket per member • Legends Tunisia")


def _build_ticket_welcome_embed(
    member: discord.Member,
    category_key: str,
    *,
    ticket_number: int,
) -> discord.Embed:
    category = TICKET_CATEGORIES[category_key]
    return discord.Embed(
        title=f"{category['emoji']} {category['label']} Ticket #{ticket_number:04d}",
        description=(
            f"Hello {member.mention}!\n\n"
            "Please describe your issue in as much detail as possible. "
            "A staff member will assist you shortly.\n\n"
            "When you are done, use **Close Ticket** below."
        ),
        color=discord.Color.green(),
    ).set_footer(text=f"Opened by {member} • {category['label']}")


def _register_ticket_channel(channel: discord.TextChannel, user_id: int, category_key: str):
    open_tickets_by_user[user_id] = channel.id
    ticket_channels[channel.id] = {
        "user_id": user_id,
        "category": category_key,
    }


def _unregister_ticket_channel(channel_id: int):
    info = ticket_channels.pop(channel_id, None)
    if info:
        open_tickets_by_user.pop(info["user_id"], None)


def _next_ticket_number(guild_id: int) -> int:
    ticket_counters[guild_id] = ticket_counters.get(guild_id, 0) + 1
    return ticket_counters[guild_id]


def _can_manage_ticket(member: discord.Member, ticket_owner_id: int) -> bool:
    if member.id == ticket_owner_id:
        return True
    if member.guild_permissions.manage_channels:
        return True
    return _member_has_any_role(member, [STAFF_ROLE_ID, *SUPPORT_NOTIFY_ROLE_IDS])


async def _create_text_ticket(interaction: discord.Interaction, category_key: str):
    if category_key not in TICKET_CATEGORIES:
        return await interaction.response.send_message("Unknown ticket category.", ephemeral=True)

    if not interaction.guild:
        return await interaction.response.send_message("Tickets only work inside a server.", ephemeral=True)

    member = interaction.user
    if member.id in open_tickets_by_user:
        existing = interaction.guild.get_channel(open_tickets_by_user[member.id])
        if existing:
            return await interaction.response.send_message(
                f"You already have an open ticket: {existing.mention}",
                ephemeral=True,
            )
        open_tickets_by_user.pop(member.id, None)

    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild
    category = _resolve_ticket_category(guild)
    if not category:
        return await interaction.followup.send(
            "❌ Ticket category not found. Check `TICKET_CATEGORY_ID` in bot.py.",
            ephemeral=True,
        )

    existing_channel = _find_open_ticket_channel(guild, member, category, category_key=category_key)
    if existing_channel:
        return await interaction.followup.send(
            f"⚠️ 3andek ticket ma7loul men 9bal hna: {existing_channel.mention}",
            ephemeral=True,
        )

    ticket_number = _next_ticket_number(guild.id)
    category_meta = TICKET_CATEGORIES[category_key]
    channel_name = _ticket_channel_name(member, category_key)

    staff_role = guild.get_role(STAFF_ROLE_ID)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False, read_messages=False),
        member: discord.PermissionOverwrite(
            view_channel=True,
            read_messages=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
        ),
    }
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(
            view_channel=True,
            read_messages=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
            manage_messages=True,
        )
    if guild.me:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
        )

    try:
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=_ticket_topic(member.id, category_key),
            reason=f"Ticket opened by {member} ({category_key})",
        )
    except discord.Forbidden:
        return await interaction.followup.send(
            "❌ El Bot ma 3andouch permission `Manage Channels`!",
            ephemeral=True,
        )
    except discord.HTTPException as exc:
        return await interaction.followup.send(
            f"Could not create your ticket right now. ({exc.text})",
            ephemeral=True,
        )

    _register_ticket_channel(ticket_channel, member.id, category_key)

    close_view = TicketCloseView(ticket_channel.id)
    bot.add_view(close_view)

    staff_role = guild.get_role(STAFF_ROLE_ID)
    ping_parts = [member.mention]
    if staff_role:
        ping_parts.append(staff_role.mention)
    await ticket_channel.send(
        " ".join(ping_parts),
        embed=_build_ticket_welcome_embed(member, category_key, ticket_number=ticket_number),
        view=close_view,
    )

    log_channel = guild.get_channel(TICKET_LOG_CHANNEL_ID)
    if log_channel:
        try:
            await log_channel.send(
                f"🔔 <@&{STAFF_ROLE_ID}> **Ticket jdid** — {member.mention} "
                f"({category_meta['label']}) → {ticket_channel.mention}"
            )
        except discord.HTTPException as exc:
            print(f"Ticket open log failed: {exc}")

    alert = discord.Embed(
        title=f"NEW {category_meta['label'].upper()} TICKET",
        description=(
            f"**User:** {member.mention} (`{member.name}`)\n"
            f"**Category:** {category_meta['emoji']} {category_meta['label']}\n"
            f"**Channel:** {ticket_channel.mention}"
        ),
        color=discord.Color.orange(),
    )
    await _notify_roles_members(guild, STAFF_ROLE_IDS, alert)

    await interaction.followup.send(
        f"✅ T7al ticket jdid hna: {ticket_channel.mention}",
        ephemeral=True,
    )


async def _close_text_ticket(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    *,
    reason: str = "Closed",
):
    info = ticket_channels.get(channel.id) or _parse_ticket_topic(channel.topic)
    if isinstance(info, dict) and "user_id" in info:
        owner_id = info["user_id"]
    elif isinstance(info, dict) and "uid" in info:
        owner_id = info["uid"]
    else:
        owner_id = None

    if owner_id is None:
        return await interaction.response.send_message("This is not an active ticket channel.", ephemeral=True)

    if not _can_manage_ticket(interaction.user, owner_id):
        return await interaction.response.send_message(
            "Only the ticket owner or staff can close this ticket.",
            ephemeral=True,
        )

    await interaction.response.defer(ephemeral=True)
    _unregister_ticket_channel(channel.id)

    closer = interaction.user.display_name
    try:
        await channel.send(
            embed=discord.Embed(
                title="Ticket Closed",
                description=f"Closed by {interaction.user.mention}\n**Reason:** {reason}",
                color=discord.Color.red(),
            )
        )
        await channel.delete(reason=f"Ticket closed by {closer}: {reason}")
    except discord.Forbidden:
        return await interaction.followup.send(
            "I cannot delete this ticket channel.",
            ephemeral=True,
        )
    except discord.HTTPException as exc:
        return await interaction.followup.send(
            f"Could not close the ticket. ({exc.text})",
            ephemeral=True,
        )

    await interaction.followup.send("Ticket closed.", ephemeral=True)


async def _log_ticket_setup(guild: discord.Guild):
    category = _resolve_ticket_category(guild)
    if category:
        print(f"TICKETS ready: category **{category.name}** ({category.id})")
    else:
        print(
            f"TICKETS MISCONFIGURED: category {TICKET_CATEGORY_ID} not found. "
            f"Visible categories: {_list_guild_category_ids(guild)}"
        )


async def _ensure_ticket_panel(guild: discord.Guild):
    channel = _get_ticket_panel_channel(guild)
    if not channel:
        return

    try:
        async for message in channel.history(limit=25):
            if message.author.id != bot.user.id:
                continue
            if not message.embeds:
                continue
            title = message.embeds[0].title or ""
            if title in (TICKET_PANEL_TITLE, "🎟️ Support Ticket"):
                return
    except discord.Forbidden:
        return

    embed = discord.Embed(
        title="🎟️ Support Ticket",
        description=(
            "Choose a category below to open a private ticket.\n"
            "Staff will respond as soon as possible."
        ),
        color=discord.Color.from_rgb(43, 45, 49),
    )
    embed.set_image(url="https://i.imgur.com/07cNK6S.png")
    await channel.send(embed=embed, view=TicketPanelView())


async def _register_existing_ticket_channels(guild: discord.Guild):
    max_number = ticket_counters.get(guild.id, 0)
    for channel in guild.text_channels:
        info = _parse_ticket_topic(channel.topic)
        if not info:
            continue

        ticket_channels[channel.id] = {
            "user_id": info["uid"],
            "category": info["cat"],
        }
        open_tickets_by_user[info["uid"]] = channel.id
        bot.add_view(TicketCloseView(channel.id))

        match = re.search(r"-(\d{4})$", channel.name)
        if match:
            max_number = max(max_number, int(match.group(1)))

    if max_number:
        ticket_counters[guild.id] = max(ticket_counters.get(guild.id, 0), max_number)


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


async def _purge_empty_temp_rooms(guild, *, reason: str = "Empty temp voice room cleanup"):
    """Delete empty bot-managed temp voice rooms."""
    skip_ids = _JOIN_TO_CREATE_HUB_IDS | {BOT_VOICE_CHANNEL_ID}
    deleted_ids = set()

    for channel_id in set(owners) | set(room_kinds):
        if channel_id in skip_ids:
            continue
        channel = guild.get_channel(channel_id)
        if channel is None:
            _clear_temp_room_tracking(channel_id)
            continue
        if len(channel.members) == 0:
            await _delete_temp_voice_channel(channel, reason=reason)
            deleted_ids.add(channel_id)
            print(f"Deleted empty tracked temp room: {channel.name}")

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
            if voice_channel.id in skip_ids or voice_channel.id in deleted_ids:
                continue

            kind = _temp_room_kind_from_name(voice_channel.name)
            if kind is None:
                continue

            if len(voice_channel.members) == 0:
                await _delete_temp_voice_channel(voice_channel, reason=reason)
                print(f"Deleted empty temp room: {voice_channel.name}")


async def _cleanup_and_register_temp_rooms(guild):
    """On startup: delete empty temp voice rooms; re-track occupied ones."""
    await _purge_empty_temp_rooms(
        guild,
        reason="Empty temp voice room cleanup after bot restart",
    )

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


class TicketOpenButton(discord.ui.Button):
    def __init__(self, category_key: str, category: dict):
        super().__init__(
            label=category["label"],
            emoji=category.get("emoji"),
            style=category.get("button_style", discord.ButtonStyle.secondary),
            custom_id=f"legends_ticket_open:{category_key}",
        )
        self.category_key = category_key

    async def callback(self, interaction: discord.Interaction):
        await _create_text_ticket(interaction, self.category_key)


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for key, category in TICKET_CATEGORIES.items():
            self.add_item(TicketOpenButton(key, category))


class TicketCloseView(discord.ui.View):
    def __init__(self, channel_id: int):
        super().__init__(timeout=None)
        self.channel_id = channel_id
        close_btn = discord.ui.Button(
            label="Close Ticket",
            emoji="🔒",
            style=discord.ButtonStyle.danger,
            custom_id=f"legends_ticket_close:{channel_id}",
        )
        close_btn.callback = self.close_button
        self.add_item(close_btn)

    async def close_button(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(self.channel_id) if interaction.guild else None
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message(
                "This ticket channel no longer exists.",
                ephemeral=True,
            )
        await _close_text_ticket(interaction, channel, reason="Closed from panel")


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


def _levels_data_score(data: dict) -> int:
    return sum(entry.get("voice_minutes", 0) for entry in data.values())


def _normalize_levels_payload(raw: dict) -> dict:
    return {int(k): _normalize_user_level_data(v) for k, v in raw.items()}


def _read_levels_file(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _normalize_levels_payload(json.load(f))
    except Exception as e:
        print(f"Could not read {path}: {e}")
        return {}


def _migrate_legacy_db_if_needed():
    legacy = Path(LEGACY_DB_FILE)
    target = Path(DB_FILE)
    if legacy.is_file() and not target.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        legacy.replace(target)
        print(f"Migrated {LEGACY_DB_FILE} -> {DB_FILE}")


def _save_local_database_sync() -> bool:
    if not user_levels:
        return False
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        formatted_data = {str(k): v for k, v in user_levels.items()}
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(formatted_data, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"Local level save failed: {e}")
        return False


def _pick_best_levels_data(*datasets: dict) -> dict:
    best: dict = {}
    best_score = -1
    for data in datasets:
        if not data:
            continue
        score = _levels_data_score(data)
        if score > best_score:
            best = data
            best_score = score
    return best


async def _read_levels_from_discord_backup() -> dict:
    channel = bot.get_channel(DATA_BACKUP_CHANNEL_ID)
    if not channel:
        return {}

    try:
        async for message in channel.history(limit=10):
            if message.author != bot.user:
                continue

            for attachment in message.attachments:
                if not attachment.filename.lower().endswith(".json"):
                    continue
                try:
                    payload = await attachment.read()
                    return _normalize_levels_payload(json.loads(payload.decode("utf-8")))
                except Exception as e:
                    print(f"Error reading backup attachment {attachment.filename}: {e}")

            if message.content.startswith("```json"):
                clean_content = message.content.strip("```json").strip("```")
                return _normalize_levels_payload(json.loads(clean_content))
    except Exception as e:
        print(f"Error loading cloud db: {e}")
    return {}


async def load_database_from_discord():
    global user_levels
    await bot.wait_until_ready()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_db_if_needed()

    local_data = _read_levels_file(DB_FILE)
    discord_data = await _read_levels_from_discord_backup()
    user_levels = _pick_best_levels_data(local_data, discord_data)

    if user_levels:
        _save_local_database_sync()
        source = "local file" if _levels_data_score(local_data) >= _levels_data_score(discord_data) else "Discord backup"
        print(f"Loaded {len(user_levels)} user levels from {source}.")
    else:
        print("No level data found — starting fresh.")


async def save_database_to_discord():
    if not user_levels:
        return
    if not _save_local_database_sync():
        return

    channel = bot.get_channel(DATA_BACKUP_CHANNEL_ID)
    if not channel:
        return

    try:
        formatted_data = {str(k): v for k, v in user_levels.items()}
        json_bytes = json.dumps(formatted_data, ensure_ascii=False, indent=2).encode("utf-8")
        buffer = io.BytesIO(json_bytes)
        buffer.seek(0)
        backup_file = discord.File(buffer, filename="levels_database.json")
        backup_embed = discord.Embed(
            title="AUTOMATIC DATA BACKUP SECURED",
            description=(
                "Automated backup for server voice levels.\n"
                "**DO NOT DELETE THIS MESSAGE.**\n"
                "Attachment: `levels_database.json`"
            ),
            color=discord.Color.green(),
        )
        backup_message = await channel.send(embed=backup_embed, file=backup_file)
        try:
            await channel.purge(
                limit=10,
                check=lambda m: m.author == bot.user and m.id != backup_message.id,
            )
        except Exception:
            pass
    except Exception as e:
        print(f"Cloud backup failed: {e}")


def _load_warnings() -> None:
    global user_warnings
    if not os.path.exists(WARNINGS_FILE):
        user_warnings = {}
        return
    try:
        with open(WARNINGS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        user_warnings = {int(k): int(v) for k, v in raw.items()}
        print(f"Loaded {len(user_warnings)} warning records.")
    except Exception as e:
        print(f"Could not load warnings database: {e}")
        user_warnings = {}


def _save_warnings() -> bool:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(WARNINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in user_warnings.items()}, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Warnings save failed: {e}")
        return False


def _get_warning_count(user_id: int) -> int:
    return user_warnings.get(user_id, 0)


def _add_warning(user_id: int) -> int:
    count = user_warnings.get(user_id, 0) + 1
    user_warnings[user_id] = count
    _save_warnings()
    return count


def _clear_warnings(user_id: int) -> None:
    if user_id in user_warnings:
        del user_warnings[user_id]
        _save_warnings()


def _remove_warning(user_id: int) -> int:
    count = user_warnings.get(user_id, 0)
    if count <= 1:
        user_warnings.pop(user_id, None)
    else:
        user_warnings[user_id] = count - 1
    _save_warnings()
    return user_warnings.get(user_id, 0)


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
    print(f"Logged in as {bot.user} (build {BOT_BUILD_ID})")

    await load_database_from_discord()
    _load_warnings()

    log_channel = await _get_punishment_log_channel()
    if log_channel is None:
        print(f"WARNING: punishment log channel {PUNISHMENT_LOG_CHANNEL_ID} is not accessible.")
    else:
        print(
            f"Punishment log channel ready: {log_channel.name} "
            f"({log_channel.id}, {type(log_channel).__name__})"
        )

    voice_channel = bot.get_channel(BOT_VOICE_CHANNEL_ID)
    if voice_channel:
        try:
            await voice_channel.connect(cls=DummyVoiceClient)
            print(f"Bot connected to voice lounge: {voice_channel.name}")
        except Exception as e:
            print(f"Failed to join static channel: {e}")

    _start_background_tasks()
    bot.add_view(GameRolePickerView())
    bot.add_view(TicketPanelView())

    for guild in bot.guilds:
        try:
            await guild.chunk()
            await _cleanup_and_register_temp_rooms(guild)
            await _register_existing_ticket_channels(guild)
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
            await _ensure_ticket_panel(guild)
            await _log_ticket_setup(guild)
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


@tasks.loop(minutes=5.0)
async def empty_temp_rooms_cleanup_task():
    for guild in bot.guilds:
        try:
            await _purge_empty_temp_rooms(
                guild,
                reason="Empty temp voice room periodic cleanup",
            )
        except Exception as e:
            print(f"Empty temp room cleanup failed for {guild.name}: {e}")


@bot_chat_keepalive_task.before_loop
async def before_bot_chat_keepalive_task():
    await bot.wait_until_ready()


@empty_temp_rooms_cleanup_task.before_loop
async def before_empty_temp_rooms_cleanup_task():
    await bot.wait_until_ready()


@tasks.loop(minutes=1.0)
async def update_levels_task():
    data_changed = False
    for guild in bot.guilds:
        log_channel = guild.get_channel(LEVEL_LOG_CHANNEL_ID)
        for voice_channel in _iter_level_voice_channels(guild):
            for member in voice_channel.members:
                if member.bot:
                    continue
                voice = member.voice
                if voice is None or voice.self_deaf:
                    continue

                try:
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
                except Exception as e:
                    print(f"Level update failed for {member.id}: {e}")

    if data_changed:
        await save_database_to_discord()


@update_levels_task.before_loop
async def before_update_levels_task():
    await bot.wait_until_ready()


@update_levels_task.error
async def update_levels_task_error(error):
    print(f"update_levels_task crashed: {error}")


@bot.command(name="ping")
async def ping_cmd(ctx):
    """Check if the bot is online and responding."""
    await ctx.send(
        f"Pong — `{round(bot.latency * 1000)}ms` • build `{BOT_BUILD_ID}`",
        delete_after=10,
    )


@bot.command(name="checkticketcategory")
@commands.has_permissions(manage_guild=True)
async def check_ticket_category_cmd(ctx):
    """Show ticket category configuration (admin)."""
    guild = ctx.guild
    lines = [f"**Build:** `{BOT_BUILD_ID}`", f"**Ticket category ID:** `{TICKET_CATEGORY_ID}`"]

    category = _resolve_ticket_category(guild)
    if category:
        lines.append(f"**Status:** OK — **{category.name}** (`{category.id}`)")
    else:
        lines.append("**Status:** INVALID — category not found.")
        lines.append(f"**Visible categories:** {_list_guild_category_ids(guild)}")

    hub = guild.get_channel(CREATE_CHANNEL_ID)
    if isinstance(hub, discord.VoiceChannel) and hub.category:
        lines.append(
            f"**Voice rooms (join-to-create):** same category as hub → "
            f"**{hub.category.name}** (`{hub.category.id}`)"
        )

    embed = discord.Embed(
        title="Ticket Category Check",
        description="\n".join(lines),
        color=discord.Color.green() if category else discord.Color.red(),
    )
    await ctx.send(embed=embed, delete_after=45)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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


@bot.command(name="ticketpanel", aliases=["go"])
@commands.has_permissions(manage_guild=True)
async def ticket_panel_cmd(ctx):
    """Post the text ticket panel (admin only). Alias: !go"""
    target = ctx.channel
    if TICKET_PANEL_CHANNEL_ID:
        panel_channel = ctx.guild.get_channel(TICKET_PANEL_CHANNEL_ID)
        if panel_channel:
            target = panel_channel

    embed = discord.Embed(
        title="🎟️ Support Ticket",
        description=(
            "Choose a category below to open a private ticket.\n"
            "Staff will respond as soon as possible."
        ),
        color=discord.Color.from_rgb(43, 45, 49),
    )
    embed.set_image(url="https://i.imgur.com/07cNK6S.png")
    await target.send(embed=embed, view=TicketPanelView())
    if target.id != ctx.channel.id:
        await ctx.send(f"Ticket panel posted in {target.mention}.", delete_after=8)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="closeticket", aliases=["cv"])
async def close_ticket_cmd(ctx, *, reason: str = "Closed by staff"):
    """Close the current ticket channel. Staff alias: !cv"""
    if not isinstance(ctx.channel, discord.TextChannel):
        return await ctx.send("Run this command inside a ticket channel.", delete_after=8)

    if ctx.channel.category_id != TICKET_CATEGORY_ID and not _is_ticket_text_channel(ctx.channel):
        return await ctx.send("El command ha4i testa3malha ken de5el ticket chat!", delete_after=8)

    info = ticket_channels.get(ctx.channel.id) or _parse_ticket_topic(ctx.channel.topic)
    owner_id = None
    if info:
        owner_id = info.get("user_id") or info.get("uid")

    if owner_id is not None and not _can_manage_ticket(ctx.author, owner_id):
        return await ctx.send("Only the ticket owner or staff can close this ticket.", delete_after=8)
    if owner_id is None and not _is_ticket_staff(ctx.author) and ctx.author.id != ctx.guild.owner_id:
        return await ctx.send("❌ El command ha4i yesta3mlha ken el Staff!", delete_after=8)

    _unregister_ticket_channel(ctx.channel.id)
    try:
        await ctx.send("Jari fsa5 el ticket... ⚙️", delete_after=3)
        await asyncio.sleep(1)
        await ctx.channel.delete(reason=f"Ticket closed by {ctx.author}: {reason}")
    except discord.Forbidden:
        await ctx.send("I cannot delete this ticket channel.", delete_after=8)
    except discord.HTTPException as exc:
        await ctx.send(f"Could not close the ticket. ({exc.text})", delete_after=8)


@bot.command(name="post", aliases=["say", "echo"])
@commands.has_permissions(manage_messages=True)
async def post_cmd(ctx, *, message: str = None):
    """Repost your message as the bot (deletes your command). Usage: !post Hello everyone"""
    content = (message or "").strip()
    attachments = list(ctx.message.attachments)

    if not content and not attachments:
        return await ctx.send("Usage: `!post your message here`", delete_after=8)

    files = [await attachment.to_file() for attachment in attachments]

    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass

    await ctx.send(content or None, files=files or None)


_DURATION_RE = re.compile(r"^(\d+)([smhdw])$", re.IGNORECASE)
MAX_TIMEOUT = timedelta(days=28)


def _parse_duration(token: str) -> timedelta | None:
    match = _DURATION_RE.match((token or "").strip().lower())
    if not match:
        return None
    amount = int(match.group(1))
    if amount <= 0:
        return None
    unit = match.group(2)
    if unit == "s":
        return timedelta(seconds=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    if unit == "w":
        return timedelta(weeks=amount)
    return None


def _format_duration(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}s"
    if total_seconds < 3600:
        return f"{total_seconds // 60}m"
    if total_seconds < 86400:
        return f"{total_seconds // 3600}h"
    return f"{total_seconds // 86400}d"


def _is_punishment_staff(member: discord.Member) -> bool:
    if member.guild_permissions.manage_guild:
        return True
    if member.guild_permissions.moderate_members:
        return True
    if member.guild_permissions.ban_members:
        return True
    staff_role = member.guild.get_role(STAFF_ROLE_ID)
    return bool(staff_role and staff_role in member.roles)


def _can_punish_target(moderator: discord.Member, target: discord.Member) -> bool:
    if target.bot:
        return False
    if target.id == moderator.id:
        return False
    if target.id == moderator.guild.owner_id:
        return False
    if moderator.id != moderator.guild.owner_id and target.top_role >= moderator.top_role:
        return False
    if target.top_role >= moderator.guild.me.top_role:
        return False
    return True


def _is_valid_punishment_log_channel(channel) -> bool:
    if channel is None:
        return False
    if isinstance(channel, discord.CategoryChannel):
        return False
    if isinstance(channel, discord.ForumChannel):
        return True
    return isinstance(channel, Messageable)


async def _get_punishment_log_channel(guild: discord.Guild | None = None):
    channel = bot.get_channel(PUNISHMENT_LOG_CHANNEL_ID)
    if channel is None and guild is not None:
        channel = guild.get_channel(PUNISHMENT_LOG_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(PUNISHMENT_LOG_CHANNEL_ID)
        except discord.NotFound:
            print(f"Punishment log channel {PUNISHMENT_LOG_CHANNEL_ID} does not exist.")
            return None
        except discord.Forbidden:
            print(f"Bot cannot access punishment log channel {PUNISHMENT_LOG_CHANNEL_ID}.")
            return None
        except discord.HTTPException as exc:
            print(f"Could not fetch punishment log channel {PUNISHMENT_LOG_CHANNEL_ID}: {exc}")
            return None

    if not _is_valid_punishment_log_channel(channel):
        print(
            f"Punishment log target {PUNISHMENT_LOG_CHANNEL_ID} is a "
            f"{type(channel).__name__} — use a text/voice/forum channel ID, not a category."
        )
        return None
    return channel


async def _send_to_punishment_log(channel, content: str, image_file: discord.File):
    if isinstance(channel, discord.ForumChannel):
        title = content.replace("New Punishment: ", "Punishment: ", 1)
        title = title[:100] if len(title) <= 100 else title[:97] + "..."
        return await channel.create_thread(name=title, content=content, files=[image_file])

    return await channel.send(content=content, files=[image_file])


async def _finish_staff_command(ctx, posted: bool, log_channel=None):
    """Give staff feedback and only delete their command when the log post succeeded."""
    if posted:
        try:
            await ctx.message.add_reaction("✅")
        except discord.HTTPException:
            pass
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
        return

    try:
        if log_channel is not None:
            await ctx.send(
                f"Could not post in {log_channel.mention}. Check bot permissions there.",
                delete_after=12,
            )
        else:
            await ctx.send(
                f"Punishment log channel not found (`{PUNISHMENT_LOG_CHANNEL_ID}`).",
                delete_after=12,
            )
    except discord.HTTPException:
        pass


async def _post_punishment_card(
    ctx,
    punishment_type: str,
    target: discord.Member,
    reason: str,
    *,
    duration: timedelta | None = None,
    extra_note: str | None = None,
    preview: bool = False,
):
    try:
        buffer = await build_punishment_card(target, ctx.author, reason, punishment_type)
    except Exception as exc:
        print(f"Punishment card build failed ({punishment_type}): {exc}")
        await ctx.send(f"Punishment card failed: {exc}", delete_after=12)
        return False

    image_file = discord.File(buffer, filename="punishment.png")
    label = PUNISHMENT_LABELS[punishment_type]
    content = f"New Punishment: **{label}** -> {target.mention}"
    if preview:
        content += " *(preview)*"
    if duration:
        content += f" ({_format_duration(duration)})"
    if extra_note:
        content += f" {extra_note}"

    log_channel = await _get_punishment_log_channel(ctx.guild)
    if log_channel is None:
        await _finish_staff_command(ctx, False)
        return False

    try:
        await _send_to_punishment_log(log_channel, content, image_file)
    except discord.Forbidden:
        print(f"Forbidden posting punishment to {log_channel.id} ({type(log_channel).__name__})")
        await _finish_staff_command(ctx, False, log_channel)
        return False
    except discord.HTTPException as exc:
        print(f"Punishment post failed in {log_channel.id}: {exc.text}")
        await _finish_staff_command(ctx, False, log_channel)
        return False
    except Exception as exc:
        print(f"Punishment post unexpected error in {log_channel.id}: {exc}")
        await ctx.send(f"Punishment post failed: {exc}", delete_after=12)
        return False

    await _finish_staff_command(ctx, True, log_channel)
    return True


def _punishment_staff_check():
    async def predicate(ctx):
        if _is_punishment_staff(ctx.author):
            return True
        await ctx.send("You need staff permissions to use punishment commands.", delete_after=8)
        return False

    return commands.check(predicate)


@bot.command(name="ban")
@_punishment_staff_check()
@commands.bot_has_permissions(ban_members=True)
async def ban_cmd(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    """Ban a member and post a punishment card."""
    if not ctx.author.guild_permissions.ban_members:
        return await ctx.send("You need **Ban Members** permission.", delete_after=8)
    if not _can_punish_target(ctx.author, member):
        return await ctx.send("You cannot punish this member.", delete_after=8)

    try:
        await member.ban(reason=f"{ctx.author}: {reason}", delete_message_seconds=0)
    except discord.Forbidden:
        return await ctx.send("I cannot ban this member.", delete_after=8)
    except discord.HTTPException as exc:
        return await ctx.send(f"Ban failed: {exc.text}", delete_after=8)

    await _post_punishment_card(ctx, "ban", member, reason)


@bot.command(name="timeout", aliases=["to"])
@_punishment_staff_check()
@commands.bot_has_permissions(moderate_members=True)
async def timeout_cmd(ctx, member: discord.Member, duration: str, *, reason: str = "No reason provided"):
    """Timeout a member. Example: !timeout @user 1h spam"""
    if not ctx.author.guild_permissions.moderate_members:
        return await ctx.send("You need **Moderate Members** permission.", delete_after=8)
    if not _can_punish_target(ctx.author, member):
        return await ctx.send("You cannot punish this member.", delete_after=8)

    delta = _parse_duration(duration)
    if not delta or delta > MAX_TIMEOUT:
        return await ctx.send("Invalid duration. Example: `30m`, `2h`, `1d` (max 28 days).", delete_after=10)

    until = discord.utils.utcnow() + delta
    try:
        await member.timeout(until, reason=f"{ctx.author}: {reason}")
    except discord.Forbidden:
        return await ctx.send("I cannot timeout this member.", delete_after=8)
    except discord.HTTPException as exc:
        return await ctx.send(f"Timeout failed: {exc.text}", delete_after=8)

    await _post_punishment_card(ctx, "timeout", member, reason, duration=delta)


@bot.command(name="chatmute", aliases=["cmute"])
@_punishment_staff_check()
@commands.bot_has_permissions(moderate_members=True)
async def chatmute_cmd(ctx, member: discord.Member, duration: str, *, reason: str = "No reason provided"):
    """Chat mute (timeout). Example: !chatmute @user 30m toxic"""
    if not ctx.author.guild_permissions.moderate_members:
        return await ctx.send("You need **Moderate Members** permission.", delete_after=8)
    if not _can_punish_target(ctx.author, member):
        return await ctx.send("You cannot punish this member.", delete_after=8)

    delta = _parse_duration(duration)
    if not delta or delta > MAX_TIMEOUT:
        return await ctx.send("Invalid duration. Example: `30m`, `2h`, `1d` (max 28 days).", delete_after=10)

    until = discord.utils.utcnow() + delta
    try:
        await member.timeout(until, reason=f"{ctx.author}: {reason}")
    except discord.Forbidden:
        return await ctx.send("I cannot mute this member.", delete_after=8)
    except discord.HTTPException as exc:
        return await ctx.send(f"Chat mute failed: {exc.text}", delete_after=8)

    await _post_punishment_card(ctx, "chatmute", member, reason, duration=delta)


@bot.command(name="voicemute", aliases=["vmute"])
@_punishment_staff_check()
@commands.bot_has_permissions(moderate_members=True)
async def voicemute_cmd(ctx, member: discord.Member, duration: str, *, reason: str = "No reason provided"):
    """Voice mute. Example: !voicemute @user 1h mic spam"""
    if not ctx.author.guild_permissions.moderate_members:
        return await ctx.send("You need **Moderate Members** permission.", delete_after=8)
    if not _can_punish_target(ctx.author, member):
        return await ctx.send("You cannot punish this member.", delete_after=8)

    delta = _parse_duration(duration)
    if not delta or delta > MAX_TIMEOUT:
        return await ctx.send("Invalid duration. Example: `30m`, `2h`, `1d` (max 28 days).", delete_after=10)

    applied_voice_mute = False
    if member.voice and member.voice.channel:
        try:
            await member.edit(mute=True, reason=f"{ctx.author}: {reason}")
            applied_voice_mute = True
        except discord.Forbidden:
            pass

    if not applied_voice_mute:
        until = discord.utils.utcnow() + delta
        try:
            await member.timeout(until, reason=f"{ctx.author}: {reason}")
        except discord.Forbidden:
            return await ctx.send("I cannot voice-mute this member.", delete_after=8)
        except discord.HTTPException as exc:
            return await ctx.send(f"Voice mute failed: {exc.text}", delete_after=8)

    await _post_punishment_card(ctx, "voicemute", member, reason, duration=delta)


@bot.command(name="warn", aliases=["warning"])
@_punishment_staff_check()
async def warn_cmd(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    """Warn a member. After 3 warnings → automatic ban. Example: !warn @user toxic behavior"""
    if not _can_punish_target(ctx.author, member):
        return await ctx.send("You cannot punish this member.", delete_after=8)

    count = _add_warning(member.id)
    await _post_punishment_card(
        ctx,
        "warn",
        member,
        reason,
        extra_note=f"**({count}/{MAX_WARNS_BEFORE_BAN})**",
    )

    if count >= MAX_WARNS_BEFORE_BAN:
        ban_reason = f"Automatic ban — {MAX_WARNS_BEFORE_BAN} warnings reached. Last: {reason}"
        try:
            await member.ban(reason=f"{ctx.author}: {ban_reason}", delete_message_seconds=0)
        except discord.Forbidden:
            log_channel = await _get_punishment_log_channel(ctx.guild)
            if log_channel:
                await log_channel.send(
                    f"⚠️ {member.mention} reached **{MAX_WARNS_BEFORE_BAN} warnings** "
                    f"but I cannot ban them (missing **Ban Members** permission)."
                )
        except discord.HTTPException as exc:
            log_channel = await _get_punishment_log_channel(ctx.guild)
            if log_channel:
                await log_channel.send(f"Auto-ban failed for {member.mention}: {exc.text}")
        except Exception as exc:
            await ctx.send(f"Auto-ban failed: {exc}", delete_after=12)
            print(f"Auto-ban unexpected error: {exc}")
        else:
            await _post_punishment_card(ctx, "ban", member, ban_reason)
            _clear_warnings(member.id)


@bot.command(name="warnings", aliases=["warns", "getwarns"])
@_punishment_staff_check()
async def warnings_cmd(ctx, member: discord.Member = None):
    """Check how many warnings a member has. Example: !warnings @user"""
    target = member or ctx.author
    count = _get_warning_count(target.id)
    await ctx.send(
        f"{target.mention} has **{count}/{MAX_WARNS_BEFORE_BAN}** warning(s).",
        delete_after=10,
    )
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="clearwarn", aliases=["removewarn", "unwarn", "clearwarnings"])
@_punishment_staff_check()
async def clearwarn_cmd(ctx, member: discord.Member, amount: str = "all"):
    """
    Remove warning(s) from a member.
    !clearwarn @user       → remove all warnings
    !clearwarn @user 1     → remove one warning
    """
    if member.bot:
        return await ctx.send("Bots cannot have warnings.", delete_after=8)

    current = _get_warning_count(member.id)
    if current == 0:
        return await ctx.send(f"{member.mention} has no warnings.", delete_after=8)

    token = (amount or "all").strip().lower()
    if token == "all":
        _clear_warnings(member.id)
        msg = f"All warnings cleared for {member.mention} (was **{current}/{MAX_WARNS_BEFORE_BAN}**)."
    else:
        try:
            remove_count = int(token)
        except ValueError:
            return await ctx.send("Usage: `!clearwarn @user` or `!clearwarn @user 1`", delete_after=10)
        if remove_count <= 0:
            return await ctx.send("Amount must be at least 1.", delete_after=8)
        for _ in range(min(remove_count, current)):
            remaining = _remove_warning(member.id)
        msg = (
            f"Removed **{min(remove_count, current)}** warning(s) from {member.mention}. "
            f"Now **{remaining}/{MAX_WARNS_BEFORE_BAN}**."
        )

    await ctx.send(msg, delete_after=10)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="testpunishment", aliases=["testpunish"])
@_punishment_staff_check()
async def test_punishment_cmd(
    ctx,
    punishment_type: str,
    member: discord.Member = None,
    *,
    reason: str = "Test punishment",
):
    """Preview a punishment card in the punishment log channel."""
    target = member or ctx.author
    punishment_type = punishment_type.lower()
    if punishment_type not in PUNISHMENT_LABELS:
        types_list = ", ".join(PUNISHMENT_LABELS)
        return await ctx.send(f"Unknown type. Use one of: `{types_list}`", delete_after=10)

    await _post_punishment_card(ctx, punishment_type, target, reason, preview=True)


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    try:
        await _log_ticket_message_to_staff(message)
    except Exception as exc:
        print(f"Ticket message handler failed: {exc}")

    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandInvokeError):
        error = error.original

    if isinstance(error, commands.BotMissingPermissions):
        missing = ", ".join(f"**{p.replace('_', ' ').title()}**" for p in error.missing_permissions)
        return await ctx.send(f"I need these permissions: {missing}", delete_after=12)

    if isinstance(error, commands.MissingPermissions):
        missing = ", ".join(f"**{p.replace('_', ' ').title()}**" for p in error.missing_permissions)
        return await ctx.send(f"You need: {missing}", delete_after=12)

    if isinstance(error, commands.CheckFailure):
        return

    if isinstance(error, commands.MissingRequiredArgument):
        usage = ctx.command.signature if ctx.command else "?"
        return await ctx.send(f"Missing argument. Usage: `{ctx.prefix}{ctx.command.name} {usage}`", delete_after=10)

    if isinstance(error, commands.MemberNotFound):
        return await ctx.send("Member not found. Mention a valid user.", delete_after=8)

    if isinstance(error, commands.BadArgument):
        return await ctx.send("Invalid command usage.", delete_after=8)

    print(f"Command error in {getattr(ctx.command, 'name', '?')}: {type(error).__name__}: {error}")
    try:
        await ctx.send(f"Command failed: `{type(error).__name__}: {error}`", delete_after=15)
    except discord.HTTPException:
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


_original_bot_close = bot.close


async def _close_with_level_save():
    if user_levels:
        if _save_local_database_sync():
            print("Levels saved locally before shutdown.")
    if user_warnings:
        if _save_warnings():
            print("Warnings saved locally before shutdown.")
    await _original_bot_close()


bot.close = _close_with_level_save

if __name__ == "__main__":
    if os.environ.get("PORT"):
        threading.Thread(target=_start_health_server, daemon=True).start()
    bot.run(TOKEN)
