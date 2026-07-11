import asyncio
import io
import json
import math
import os
import random
import re
import sys
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import discord
from discord import app_commands
from discord.abc import Messageable
from discord.ext import commands, tasks
from dotenv import load_dotenv

from welcome_card import build_welcome_card, AVATAR_SIZE, AVATAR_POSITION, FONT_SIZE
from punishment_card import LABELS as PUNISHMENT_LABELS, build_punishment_card
from level_up_card import build_level_up_card

load_dotenv()


def _env_channel_id(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw or raw.lower() in ("0", "none", "false"):
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"Invalid {name}={raw!r} — must be a numeric Discord channel ID.") from exc


TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("Missing DISCORD_TOKEN. Copy .env.example to .env and add your bot token.")

CREATE_CHANNEL_ID = _env_channel_id("CREATE_CHANNEL_ID", 1517870390968582155)

SUPPORT_CHANNEL_ID = _env_channel_id("SUPPORT_CHANNEL_ID", 1518020513174130769)

VERIFICATION_1_ID = _env_channel_id("VERIFICATION_1_ID", 1517597478378143937)
VERIFICATION_2_ID = _env_channel_id("VERIFICATION_2_ID", 1517666468593143940)
STAFF_ROLE_ID = 1517586424306598140

NOT_VERIFIED_ROLE_ID = 1517593118399139840
WELCOME_CHANNEL_ID = 1511674200543199333

# Roles auto-assigned when a member joins the server
NEW_MEMBER_ROLE_IDS = [
    1523437275768291400,
    1523437226330030270,
    1523437146739052604,
    1523441776331853844,
    1523441832095252564,
]
JOIN_AUTO_ROLE_IDS = [NOT_VERIFIED_ROLE_ID, *NEW_MEMBER_ROLE_IDS]

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

GIVEAWAY_CHANNEL_ID = 1518721917312434197
GIVEAWAY_ADMIN_ROLE_ID = 1511828976732209252
BAN_TIMEOUT_IMMUNE_ROLE_IDS = [GIVEAWAY_ADMIN_ROLE_ID]

TICKET_PANEL_CHANNEL_ID = 1522527871887998987
TICKET_LOG_CHANNEL_ID = 1522527871887998987
TICKET_CATEGORY_ID = 1523436013337448638
_env_ticket_cat = os.getenv("TICKET_CATEGORY_ID", "").strip()
if _env_ticket_cat and _env_ticket_cat not in ("0", "none", "false"):
    TICKET_CATEGORY_ID = int(_env_ticket_cat)

TICKET_EMOJI_SUPPORT = discord.PartialEmoji(name="51395", id=1523430687493984417)
TICKET_EMOJI_REPORT = discord.PartialEmoji(name="51795", id=1523430684150988894)
TICKET_EMOJI_BUGS = discord.PartialEmoji(name="51796", id=1523430685740630026)

TICKET_CATEGORIES = {
    "support": {
        "label": "Support",
        "emoji": TICKET_EMOJI_SUPPORT,
        "description": "General help and questions",
        "button_style": discord.ButtonStyle.primary,
    },
    "report": {
        "label": "Report",
        "emoji": TICKET_EMOJI_REPORT,
        "description": "Report a user or rule break",
        "button_style": discord.ButtonStyle.danger,
    },
    "bugs": {
        "label": "Bugs",
        "emoji": TICKET_EMOJI_BUGS,
        "description": "Report a bug or technical issue",
        "button_style": discord.ButtonStyle.secondary,
    },
}

TICKET_PANEL_TITLE = "🎫 Support Tickets"
TICKET_TOPIC_PREFIX = "legends-ticket:"

PUNISHMENT_LOG_CHANNEL_ID = 1522676265381793876

BOT_VOICE_CHANNEL_ID = 1518025649225470072

VOICE_LEVEL_SKIP_CHANNEL_IDS = frozenset({
    CREATE_CHANNEL_ID,
    SUPPORT_CHANNEL_ID,
    VERIFICATION_1_ID,
    VERIFICATION_2_ID,
    BOT_VOICE_CHANNEL_ID,
})
BOT_CHAT_CHANNEL_ID = int(os.getenv("BOT_CHAT_CHANNEL_ID", "1518023858765168771"))
BOT_BUILD_ID = "2026-07-08-rate-limit-safe"

LEVEL_LOG_CHANNEL_ID = 1517921554510385242
LEVEL_MINUTES_BASE = 5
MAX_VOICE_LEVEL = 1000
LEVELS_BACKUP_CHANNEL_ID = _env_channel_id(
    "LEVELS_BACKUP_CHANNEL_ID", LEVEL_LOG_CHANNEL_ID
)
LEVELS_BACKUP_HOURS = max(1.0, float(os.getenv("LEVELS_BACKUP_HOURS", "1")))
LEVELS_BACKUP_MARKER = "LEGENDS_LEVELS_BACKUP"
LEVELS_BACKUP_FILENAME = "levels_database.json"
LEVELS_BACKUP_KEEP = max(1, int(os.getenv("LEVELS_BACKUP_KEEP", "5")))

BOT_CHAT_KEEPALIVE_MINUTES = max(5.0, float(os.getenv("BOT_CHAT_KEEPALIVE_MINUTES", "30")))
EMPTY_ROOM_CLEANUP_MINUTES = max(5.0, float(os.getenv("EMPTY_ROOM_CLEANUP_MINUTES", "10")))
PUNISHMENT_POST_CAP = max(1, int(os.getenv("PUNISHMENT_POST_CAP", "5")))
WELCOME_POST_CAP = max(1, int(os.getenv("WELCOME_POST_CAP", "5")))
SYNCROLES_MEMBER_DELAY = max(0.0, float(os.getenv("SYNCROLES_MEMBER_DELAY", "0.35")))
GUILD_INIT_STEP_DELAY = max(0.0, float(os.getenv("GUILD_INIT_STEP_DELAY", "0.4")))

# Server default: chat/voice-text notifications only on @mentions (not every message)
SET_DEFAULT_NOTIFICATIONS_ONLY_MENTIONS = os.getenv(
    "SET_DEFAULT_NOTIFICATIONS_ONLY_MENTIONS", "true"
).lower() in ("1", "true", "yes")

def _start_background_tasks():
    if not bot_chat_keepalive_task.is_running():
        bot_chat_keepalive_task.start()
    if not empty_temp_rooms_cleanup_task.is_running():
        empty_temp_rooms_cleanup_task.start()
    if not update_voice_levels_task.is_running():
        update_voice_levels_task.start()
    if not levels_backup_task.is_running():
        levels_backup_task.start()


intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.message_content = True
intents.members = True

COMMAND_PREFIX = "?"
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, status=discord.Status.dnd)
_startup_done = False
_punishment_post_count = 0
_punishment_post_bucket = 0
_welcome_post_count = 0
_welcome_post_bucket = 0


async def _await_rate_limit(exc: discord.HTTPException, *, label: str) -> None:
    wait = float(getattr(exc, "retry_after", 5) or 5) + 0.5
    print(f"{label}: rate limited, waiting {wait:.1f}s")
    await asyncio.sleep(wait)


def _should_post_punishment() -> bool:
    global _punishment_post_count, _punishment_post_bucket
    bucket = int(time.time() // 60)
    if bucket != _punishment_post_bucket:
        _punishment_post_bucket = bucket
        _punishment_post_count = 0
    if _punishment_post_count >= PUNISHMENT_POST_CAP:
        return False
    _punishment_post_count += 1
    return True


def _should_post_welcome() -> bool:
    global _welcome_post_count, _welcome_post_bucket
    bucket = int(time.time() // 60)
    if bucket != _welcome_post_bucket:
        _welcome_post_bucket = bucket
        _welcome_post_count = 0
    if _welcome_post_count >= WELCOME_POST_CAP:
        return False
    _welcome_post_count += 1
    return True


async def _api_call_with_retry(coro_factory, *, label: str, attempts: int = 3):
    last_exc = None
    for attempt in range(attempts):
        try:
            return await coro_factory()
        except discord.HTTPException as exc:
            last_exc = exc
            if exc.status == 429 and attempt < attempts - 1:
                await _await_rate_limit(exc, label=label)
                continue
            raise
    if last_exc:
        raise last_exc

owners = {}
room_kinds = {}
room_nsfw_enabled: dict[int, bool] = {}
room_nsfw_pending: dict[int, tuple[str, bool]] = {}
room_nsfw_retry_tasks: dict[int, asyncio.Task] = {}
owner_transfer_tasks = {}
OWNER_ABSENCE_SECONDS = 60
locked_rooms = set()
_join_create_in_progress: set[int] = set()

DATA_DIR = Path("data")
LEVELS_DB_FILE = DATA_DIR / "levels_database.json"
LEGACY_LEVELS_DB_FILE = Path("levels_database.json")
bot_chat_messages = {}
ticket_counters: dict[int, int] = {}
open_tickets_by_user: dict[int, int] = {}
ticket_channels: dict[int, dict] = {}
WARNINGS_FILE = str(DATA_DIR / "warnings_database.json")
user_warnings: dict[int, int] = {}
user_levels: dict[int, dict] = {}
MAX_WARNS_BEFORE_BAN = 3

WARN_1_ROLE_ID = 1523000242491097208
WARN_2_ROLE_ID = 1523000417758347274
CHAT_MUTE_ROLE_ID = 1523473905237495839
VOICE_MUTE_ROLE_ID = 1523000899692138668
WARN_3_ROLE_IDS = (CHAT_MUTE_ROLE_ID, VOICE_MUTE_ROLE_ID)
WARN_EARLY_ROLE_IDS = (WARN_1_ROLE_ID, WARN_2_ROLE_ID)
WARN_3_MUTE_DURATION = timedelta(days=1)

active_giveaways: dict[int, asyncio.Event] = {}
chat_mute_expiry_tasks: dict[int, asyncio.Task] = {}
current_giveaway_view = None

LOUNGE_ROOM_NAME_PREFIX = "🎙️|"
LOUNGE_ROOM_NAME_SUFFIX = " ✓"
NSFW_ROOM_NAME_PREFIX = "🔞"


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


def _log_join_to_create_startup(guild: discord.Guild) -> None:
    labels = {
        CREATE_CHANNEL_ID: "Create Lounge",
        SUPPORT_CHANNEL_ID: "Support",
        VERIFICATION_1_ID: "Verification 1",
        VERIFICATION_2_ID: "Verification 2",
    }
    for hub_id, label in labels.items():
        channel = guild.get_channel(hub_id)
        if isinstance(channel, discord.VoiceChannel):
            cat = channel.category.name if channel.category else "NO CATEGORY"
            print(f"Join-to-create hub OK: {label} → {channel.name} ({hub_id}) category={cat}")
        elif channel is None:
            print(
                f"WARNING: Join-to-create hub MISSING: {label} channel id {hub_id} "
                f"not found in {guild.name}. Set CREATE_CHANNEL_ID (etc.) in env if the channel was recreated."
            )
        else:
            print(f"WARNING: Join-to-create hub {label} ({hub_id}) is not a voice channel.")


async def _notify_join_create_failure(member: discord.Member, message: str) -> None:
    try:
        await member.send(
            embed=discord.Embed(
                title="Could not create your voice room",
                description=message,
                color=discord.Color.red(),
            )
        )
    except discord.Forbidden:
        pass


async def _create_join_to_create_room(member, trigger_channel):
    """Create a private sub-room when a member joins a join-to-create voice channel."""
    if member.bot or member.id in _join_create_in_progress:
        return

    config = JOIN_TO_CREATE_CHANNELS.get(trigger_channel.id)
    if not config:
        return

    guild = member.guild
    me = guild.me
    if me is None:
        print(f"Join-to-create skipped for {member}: bot member not cached in guild.")
        return

    missing_perms = [
        name
        for name, allowed in (
            ("Manage Channels", me.guild_permissions.manage_channels),
            ("Move Members", me.guild_permissions.move_members),
            ("Connect", me.guild_permissions.connect),
        )
        if not allowed
    ]
    if missing_perms:
        msg = (
            f"I need **{'**, **'.join(missing_perms)}** on this server to create your room.\n"
            "Ask staff to fix the bot role permissions and try again."
        )
        print(f"Join-to-create blocked for {member} in {trigger_channel.name}: missing {missing_perms}")
        await _notify_join_create_failure(member, msg)
        return

    _join_create_in_progress.add(member.id)
    try:
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
        print(
            f"Temp room created: {new_channel.name} ({new_channel.id}) "
            f"for {member} via hub {trigger_channel.name} ({trigger_channel.id}) → category {cat_name}"
        )
        owners[new_channel.id] = member.id
        room_kinds[new_channel.id] = config["kind"]
        room_nsfw_enabled[new_channel.id] = False

        try:
            await member.move_to(new_channel)
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"Join-to-create move failed for {member} → {new_channel.name}: {exc}")
            await _notify_join_create_failure(
                member,
                (
                    f"Your room **{new_channel.name}** was created, but I could not move you into it.\n"
                    "Please join it manually from the voice channel list."
                ),
            )

        await _send_room_control_panel(new_channel, member, kind=config["kind"])
    except discord.Forbidden as exc:
        print(f"Join-to-create forbidden for {member} in {trigger_channel.name}: {exc}")
        await _notify_join_create_failure(
            member,
            (
                "I do not have permission to create your room in this category.\n"
                "Move the **bot role above** member roles and grant **Manage Channels** + **Move Members**."
            ),
        )
    except discord.HTTPException as exc:
        print(f"Join-to-create HTTP error for {member} in {trigger_channel.name}: {exc.status} {exc.text}")
        await _notify_join_create_failure(
            member,
            f"Discord rejected the room creation (`HTTP {exc.status}`). Try again in a moment.",
        )
    except Exception as exc:
        print(f"Join-to-create unexpected error for {member} in {trigger_channel.name}: {exc}")
        await _notify_join_create_failure(
            member,
            "Something went wrong while creating your room. Staff have been notified in the bot logs.",
        )
    finally:
        _join_create_in_progress.discard(member.id)


async def _set_room_locked(channel, *, locked: bool):
    """Lock = @everyone + Boy/Girl cannot connect; Staff + room owner can."""
    guild = channel.guild

    if locked:
        everyone = guild.default_role
        everyone_ow = channel.overwrites_for(everyone)
        everyone_ow.connect = False
        await channel.set_permissions(everyone, overwrite=everyone_ow)

        for role in _lounge_access_roles(guild):
            role_ow = channel.overwrites_for(role)
            role_ow.connect = False
            await channel.set_permissions(role, overwrite=role_ow)

        staff_role = guild.get_role(STAFF_ROLE_ID)
        if staff_role:
            await channel.set_permissions(
                staff_role,
                view_channel=True,
                connect=True,
                speak=True,
            )

        owner_id = owners.get(channel.id)
        if owner_id:
            owner = guild.get_member(owner_id)
            if owner:
                await channel.set_permissions(
                    owner,
                    view_channel=True,
                    connect=True,
                    speak=True,
                    send_messages=True,
                    manage_channels=True,
                )

        locked_rooms.add(channel.id)
    else:
        locked_rooms.discard(channel.id)
        await _restore_room_join_permissions(channel, guild)


def _lounge_access_roles(guild):
    return [r for rid in (BOY_ROLE_ID, GIRL_ROLE_ID) if (r := guild.get_role(rid))]


async def _restore_room_join_permissions(channel, guild):
    """Restore default lounge join perms after unlock."""
    kind = room_kinds.get(channel.id, "lounge")
    if kind != "lounge":
        return

    everyone = guild.default_role
    await channel.set_permissions(
        everyone,
        view_channel=False,
        connect=False,
        send_messages=False,
    )
    for role in _lounge_access_roles(guild):
        await channel.set_permissions(
            role,
            view_channel=True,
            connect=True,
            speak=True,
            send_messages=True,
        )


def _strip_nsfw_room_prefix(channel_name: str) -> str:
    if channel_name.startswith(NSFW_ROOM_NAME_PREFIX):
        return channel_name[len(NSFW_ROOM_NAME_PREFIX) :]
    return channel_name


def _channel_has_nsfw_label(channel_name: str) -> bool:
    return channel_name.startswith(NSFW_ROOM_NAME_PREFIX)


async def _apply_nsfw_room_mark(
    channel: discord.VoiceChannel,
    *,
    new_name: str,
    enabled: bool,
    reason: str,
) -> None:
    await channel.edit(name=new_name, reason=reason)
    room_nsfw_enabled[channel.id] = enabled


async def _schedule_nsfw_room_retry(
    guild_id: int,
    channel_id: int,
    new_name: str,
    enabled: bool,
    delay: float,
) -> None:
    existing = room_nsfw_retry_tasks.pop(channel_id, None)
    if existing and not existing.done():
        existing.cancel()

    room_nsfw_pending[channel_id] = (new_name, enabled)

    async def _retry() -> None:
        try:
            await asyncio.sleep(max(delay, 1))
            pending = room_nsfw_pending.get(channel_id)
            if pending != (new_name, enabled):
                return
            guild = bot.get_guild(guild_id)
            if guild is None:
                return
            fresh = await guild.fetch_channel(channel_id)
            if not isinstance(fresh, discord.VoiceChannel):
                return
            await _apply_nsfw_room_mark(
                fresh,
                new_name=new_name,
                enabled=enabled,
                reason="Room 18+ label retry",
            )
            room_nsfw_pending.pop(channel_id, None)
            print(f"NSFW label retry ok for channel {channel_id}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"NSFW label retry failed for {channel_id}: {exc}")
        finally:
            room_nsfw_retry_tasks.pop(channel_id, None)

    room_nsfw_retry_tasks[channel_id] = asyncio.create_task(_retry())


async def _toggle_room_nsfw_mark(channel: discord.VoiceChannel) -> tuple[bool, str, float | None]:
    """Toggle 🔞 prefix on the voice channel name.

    Returns (enabled, display_name, retry_after_seconds if rate-limited else None).
    """
    fresh = await channel.guild.fetch_channel(channel.id)
    if not isinstance(fresh, discord.VoiceChannel):
        raise TypeError("Channel is not a voice channel")

    has_label = _channel_has_nsfw_label(fresh.name)
    enabled = not has_label
    base_name = _strip_nsfw_room_prefix(fresh.name)
    new_name = f"{NSFW_ROOM_NAME_PREFIX}{base_name}"[:100] if enabled else base_name[:100]

    pending = room_nsfw_pending.pop(fresh.id, None)
    if pending:
        retry_task = room_nsfw_retry_tasks.pop(fresh.id, None)
        if retry_task and not retry_task.done():
            retry_task.cancel()

    if fresh.name == new_name:
        room_nsfw_enabled[fresh.id] = enabled
        return enabled, new_name, None

    try:
        await _apply_nsfw_room_mark(
            fresh,
            new_name=new_name,
            enabled=enabled,
            reason="Room owner toggled 18+ label",
        )
        return enabled, new_name, None
    except discord.HTTPException as exc:
        if exc.status != 429:
            raise
        retry_after = float(getattr(exc, "retry_after", 0) or 600)
        await _schedule_nsfw_room_retry(
            channel.guild.id,
            fresh.id,
            new_name,
            enabled,
            retry_after + 1,
        )
        return enabled, new_name, retry_after


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
                        f"Then use `{COMMAND_PREFIX}panel` inside the room chat to repost it."
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


def _get_giveaway_guild():
    channel = bot.get_channel(GIVEAWAY_CHANNEL_ID)
    return channel.guild if channel else None


def _is_giveaway_admin(member):
    return _member_has_any_role(member, [GIVEAWAY_ADMIN_ROLE_ID])


async def _assign_join_roles(member: discord.Member) -> None:
    roles_to_add = []
    for role_id in JOIN_AUTO_ROLE_IDS:
        role = member.guild.get_role(role_id)
        if role and role not in member.roles:
            roles_to_add.append(role)
    if not roles_to_add:
        return
    try:
        await member.add_roles(*roles_to_add, reason="New member auto-role")
        names = ", ".join(role.name for role in roles_to_add)
        print(f"Given join roles to {member.name}: {names}")
    except Exception as e:
        print(f"Failed to give join roles to {member.name}: {e}")


async def _assign_missing_roles(member: discord.Member, roles: list[discord.Role], *, reason: str) -> int:
    roles_to_add = [role for role in roles if role not in member.roles]
    if not roles_to_add:
        return 0
    await member.add_roles(*roles_to_add, reason=reason)
    return len(roles_to_add)


def _get_guild_roles_by_ids(guild: discord.Guild, role_ids: list[int]) -> list[discord.Role]:
    return [role for role_id in role_ids if (role := guild.get_role(role_id))]


def _bot_role_assignment_issue(guild: discord.Guild, roles: list[discord.Role]) -> str | None:
    me = guild.me
    if not me or not me.guild_permissions.manage_roles:
        return "El bot ma 3andhouch **Manage Roles**."
    blocked = [role for role in roles if role.position >= me.top_role.position]
    if blocked:
        names = ", ".join(role.name for role in blocked)
        return (
            f"Role mta3 el bot (**{me.top_role.name}**) ta7t: **{names}**.\n"
            "Sa7eh el hierarchy: role el bot lezem ykon **fo9** el roles hedhouma."
        )
    return None


async def _fetch_human_members(guild: discord.Guild) -> list[discord.Member]:
    members = []
    async for member in guild.fetch_members(limit=None):
        if not member.bot:
            members.append(member)
    return members


def _get_bot_chat_channel(guild):
    if BOT_CHAT_CHANNEL_ID:
        channel = guild.get_channel(BOT_CHAT_CHANNEL_ID)
        if channel:
            return channel
    return discord.utils.get(guild.text_channels, name="bot-chat")


async def _apply_guild_notification_settings(guild, *, force=False):
    """Set guild default notifications to @mentions only (Manage Server required)."""
    if not SET_DEFAULT_NOTIFICATIONS_ONLY_MENTIONS and not force:
        return False, f"Auto setup is off. Use `{COMMAND_PREFIX}setnotifications` or enable `SET_DEFAULT_NOTIFICATIONS_ONLY_MENTIONS`."

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
            await _api_call_with_retry(
                lambda: channel.fetch_message(message_id),
                label="Bot chat fetch",
            )
            return
        except discord.NotFound:
            bot_chat_messages.pop(guild.id, None)
        except discord.Forbidden:
            return
        except discord.HTTPException as exc:
            if exc.status == 429:
                print("Bot chat keepalive skipped (rate limited).")
            return

    chat_text = (BOT_CHAT_MESSAGE or "welcome to Bot-Chat")[:2000]
    try:
        message = await _api_call_with_retry(
            lambda: channel.send(chat_text),
            label="Bot chat send",
        )
        bot_chat_messages[guild.id] = message.id
    except discord.HTTPException as exc:
        if exc.status == 429:
            print("Bot chat welcome send skipped (rate limited).")


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


def _ticket_emoji_display(emoji) -> str:
    if isinstance(emoji, discord.PartialEmoji):
        return str(emoji)
    return str(emoji) if emoji else ""


def _build_ticket_panel_embed() -> discord.Embed:
    lines = "\n".join(
        f"{_ticket_emoji_display(cat['emoji'])} **{cat['label']}** — {cat['description']}"
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
        title=f"{_ticket_emoji_display(category['emoji'])} {category['label']} Ticket #{ticket_number:04d}",
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

        nsfw_btn = discord.ui.Button(
            label="18+",
            style=discord.ButtonStyle.secondary,
            emoji="🔞",
            custom_id=f"legends:nsfw:{channel_id}",
            row=2,
        )
        nsfw_btn.callback = self.nsfw_button
        self.add_item(nsfw_btn)

    def _get_channel(self, interaction: discord.Interaction):
        return interaction.guild.get_channel(self.channel_id)

    async def lock_button(self, interaction: discord.Interaction):
        channel = self._get_channel(interaction)
        if not channel:
            return await interaction.response.send_message("Room no longer exists.", ephemeral=True)
        if interaction.user.id != owners.get(self.channel_id):
            return await interaction.response.send_message("Only the room creator can use these controls.", ephemeral=True)

        await _set_room_locked(channel, locked=True)
        await interaction.response.send_message(
            "Room locked — **@everyone** cannot join. Only **Staff** and the room owner can connect.",
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
        embed = _format_level_embed(interaction.user)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def nsfw_button(self, interaction: discord.Interaction):
        channel = self._get_channel(interaction)
        if not channel:
            return await interaction.response.send_message("Room no longer exists.", ephemeral=True)
        if interaction.user.id != owners.get(self.channel_id):
            return await interaction.response.send_message("Only the room creator can use these controls.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        try:
            enabled, new_name, retry_after = await _toggle_room_nsfw_mark(channel)
        except discord.Forbidden:
            return await interaction.followup.send(
                "I cannot rename this room (check **Manage Channels**).",
                ephemeral=True,
            )
        except discord.HTTPException as exc:
            return await interaction.followup.send(f"Could not update room: {exc.text}", ephemeral=True)
        except Exception as exc:
            print(f"NSFW toggle failed for {self.channel_id}: {exc}")
            return await interaction.followup.send(f"Could not update room: {exc}", ephemeral=True)

        if retry_after is not None:
            mins = max(1, int((retry_after + 59) // 60))
            action = "ytetzad" if enabled else "yetsala7"
            return await interaction.followup.send(
                f"⏳ Discord y7eb limit esm el room (2 marrat / 10 min).\n"
                f"🔞 Label **{action}** automatiquement ba3d ~**{mins} min**. Ma tclickich kter.",
                ephemeral=True,
            )

        if enabled:
            msg = f"🔞 **18+** label added — room is now **{new_name}**"
        else:
            msg = f"🔞 **18+** label removed — room is now **{new_name}**"
        await interaction.followup.send(msg, ephemeral=True)




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


class GiveawayView(discord.ui.View):
    def __init__(self, timeout=None):
        super().__init__(timeout=timeout)
        self.participants = set()
        self.kicked_users = set()

    @discord.ui.button(label="🎉 Join Giveaway", style=discord.ButtonStyle.primary, custom_id="giveaway_join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.kicked_users:
            await interaction.response.send_message(
                "❌ Ma tnajemch tcharrek fi hal giveaway, rak tna7it menha!",
                ephemeral=True,
            )
            return

        if interaction.user.id in self.participants:
            await interaction.response.send_message("Enti m9ayed deja fi hal giveaway!", ephemeral=True)
        else:
            self.participants.add(interaction.user.id)
            await interaction.response.send_message(
                "✅ Rak 9ayedt m3ana fil giveaway! Bonne chance! 🎉",
                ephemeral=True,
            )

    @discord.ui.button(label="👀 Chkoun Charek", style=discord.ButtonStyle.secondary, custom_id="giveaway_list")
    async def list_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.participants) == 0:
            await interaction.response.send_message("😢 Mezel 7ad ma charek fi hal giveaway!", ephemeral=True)
        else:
            participants_list = ", ".join(f"<@{p}>" for p in self.participants)
            await interaction.response.send_message(
                f"👥 **Eli charkou lkol ({len(self.participants)}):**\n{participants_list}",
                ephemeral=True,
            )


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


_JOIN_TO_CREATE_HUB_IDS = frozenset(JOIN_TO_CREATE_CHANNELS.keys())


def _temp_room_kind_from_name(channel_name: str) -> str | None:
    name = _strip_nsfw_room_prefix(channel_name)
    if name.startswith(LOUNGE_ROOM_NAME_PREFIX) and name.endswith(LOUNGE_ROOM_NAME_SUFFIX):
        return "lounge"
    if name.endswith("'s Lounge"):
        return "lounge"
    if name.startswith("Support | "):
        return "support"
    if name.startswith("Verify | "):
        return "verification"
    return None


def _is_tracked_temp_room(channel_id: int) -> bool:
    return channel_id in owners or channel_id in room_kinds


def _clear_temp_room_tracking(channel_id: int):
    _cancel_owner_transfer(channel_id)
    owners.pop(channel_id, None)
    room_kinds.pop(channel_id, None)
    room_nsfw_enabled.pop(channel_id, None)
    room_nsfw_pending.pop(channel_id, None)
    retry_task = room_nsfw_retry_tasks.pop(channel_id, None)
    if retry_task and not retry_task.done():
        retry_task.cancel()
    locked_rooms.discard(channel_id)


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
            room_nsfw_enabled[voice_channel.id] = voice_channel.name.startswith(NSFW_ROOM_NAME_PREFIX)
            print(
                f"Re-registered temp room: {voice_channel.name} "
                f"(kind={kind}, owner={owner.display_name if owner else 'unknown'})"
            )


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


def _voice_minutes_for_level(level: int) -> int:
    return LEVEL_MINUTES_BASE * level * (level + 1) // 2


def _level_from_voice_minutes(minutes: int) -> int:
    if minutes <= 0:
        return 0
    level = int((-1 + math.sqrt(1 + 8 * minutes / LEVEL_MINUTES_BASE)) // 2)
    return min(level, MAX_VOICE_LEVEL)


def _normalize_user_level_data(raw: dict) -> dict:
    if "voice_minutes" in raw:
        minutes = int(raw["voice_minutes"])
    else:
        minutes = int(raw.get("xp", 0)) // 10
    return {
        "voice_minutes": minutes,
        "level": _level_from_voice_minutes(minutes),
    }


def _get_user_level_data(user_id: int) -> dict:
    data = user_levels.get(user_id)
    if not data:
        return {"voice_minutes": 0, "level": 0}
    return _normalize_user_level_data(data)


def _minutes_until_next_level(minutes: int, level: int) -> int | None:
    if level >= MAX_VOICE_LEVEL:
        return None
    return max(0, _voice_minutes_for_level(level + 1) - minutes)


def _apply_levels_raw(raw: dict) -> int:
    global user_levels
    user_levels = {int(k): _normalize_user_level_data(v) for k, v in raw.items()}
    return len(user_levels)


def _load_levels_database() -> None:
    global user_levels
    if LEGACY_LEVELS_DB_FILE.is_file() and not LEVELS_DB_FILE.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LEGACY_LEVELS_DB_FILE.replace(LEVELS_DB_FILE)

    if not LEVELS_DB_FILE.is_file():
        user_levels = {}
        return

    try:
        with open(LEVELS_DB_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        count = _apply_levels_raw(raw)
        print(f"Loaded {count} voice level records from local file.")
    except Exception as exc:
        print(f"Could not load levels database: {exc}")
        user_levels = {}


def _save_levels_database() -> bool:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(LEVELS_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {str(k): _normalize_user_level_data(v) for k, v in user_levels.items()},
                f,
                ensure_ascii=False,
                indent=2,
            )
        return True
    except Exception as exc:
        print(f"Levels save failed: {exc}")
        return False


def _levels_payload_bytes() -> bytes:
    payload = {
        str(k): _normalize_user_level_data(v) for k, v in user_levels.items()
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _get_levels_backup_channel():
    channel = bot.get_channel(LEVELS_BACKUP_CHANNEL_ID)
    if channel is not None:
        return channel
    for guild in bot.guilds:
        channel = guild.get_channel(LEVELS_BACKUP_CHANNEL_ID)
        if channel is not None:
            return channel
    return None


async def _prune_old_levels_backups(channel, *, keep: int = LEVELS_BACKUP_KEEP) -> None:
    backups = []
    try:
        async for message in channel.history(limit=40):
            if message.author.id != bot.user.id:
                continue
            if LEVELS_BACKUP_MARKER not in (message.content or ""):
                continue
            backups.append(message)
    except discord.HTTPException as exc:
        print(f"Levels backup prune scan failed: {exc}")
        return

    for old in backups[keep:]:
        try:
            await old.delete()
        except discord.HTTPException:
            pass


async def _post_levels_backup(*, reason: str = "hourly") -> bool:
    channel = _get_levels_backup_channel()
    if channel is None:
        print(f"Levels backup skipped: channel {LEVELS_BACKUP_CHANNEL_ID} not found.")
        return False

    _save_levels_database()
    data = _levels_payload_bytes()
    file = discord.File(io.BytesIO(data), filename=LEVELS_BACKUP_FILENAME)
    try:
        await channel.send(
            content=(
                f"{LEVELS_BACKUP_MARKER} | records={len(user_levels)} | "
                f"reason={reason} | <t:{int(time.time())}:f>"
            ),
            file=file,
        )
    except discord.HTTPException as exc:
        print(f"Levels backup post failed: {exc}")
        return False

    await _prune_old_levels_backups(channel)
    print(f"Levels backup posted ({reason}): {len(user_levels)} records.")
    return True


async def _restore_levels_from_discord() -> bool:
    """Load newest levels JSON backup from the backup channel (Render-safe)."""
    channel = _get_levels_backup_channel()
    if channel is None:
        print(f"No levels backup channel ({LEVELS_BACKUP_CHANNEL_ID}).")
        return False

    try:
        async for message in channel.history(limit=50):
            if message.author.id != bot.user.id:
                continue
            if LEVELS_BACKUP_MARKER not in (message.content or ""):
                continue
            for attachment in message.attachments:
                name = (attachment.filename or "").lower()
                if name != LEVELS_BACKUP_FILENAME and not name.endswith(".json"):
                    continue
                try:
                    raw_bytes = await attachment.read()
                    raw = json.loads(raw_bytes.decode("utf-8"))
                    if not isinstance(raw, dict):
                        continue
                    count = _apply_levels_raw(raw)
                    _save_levels_database()
                    print(
                        f"Restored {count} voice level records from Discord backup "
                        f"(message {message.id})."
                    )
                    return True
                except Exception as exc:
                    print(f"Failed reading levels backup attachment: {exc}")
                    continue
    except discord.HTTPException as exc:
        print(f"Levels backup restore failed: {exc}")
        return False

    print("No Discord levels backup found.")
    return False


def _format_level_embed(target: discord.Member) -> discord.Embed:
    data = _get_user_level_data(target.id)
    minutes = data["voice_minutes"]
    level = data["level"]
    remaining = _minutes_until_next_level(minutes, level)
    if remaining is None:
        progress = "Max level reached."
    else:
        progress = f"**{remaining}** min until level **{level + 1}**."

    hours = minutes // 60
    mins = minutes % 60
    time_text = f"{hours}h {mins}m" if hours else f"{mins}m"

    return discord.Embed(
        title=f"Voice Level — {target.display_name}",
        description=(
            f"**Level:** `{level}`\n"
            f"**Voice time:** `{time_text}` (`{minutes}` min)\n"
            f"{progress}"
        ),
        color=discord.Color.gold(),
    )


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


async def _safe_add_roles(member: discord.Member, role_ids, *, reason: str) -> None:
    roles = [role for role_id in role_ids if (role := member.guild.get_role(role_id))]
    roles = [role for role in roles if role not in member.roles]
    if not roles:
        return
    await member.add_roles(*roles, reason=reason)


async def _safe_remove_roles(member: discord.Member, role_ids, *, reason: str) -> None:
    roles = [role for role_id in role_ids if (role := member.guild.get_role(role_id))]
    roles = [role for role in roles if role in member.roles]
    if not roles:
        return
    await member.remove_roles(*roles, reason=reason)


def _is_chat_muted(member: discord.Member) -> bool:
    chat_mute_role = member.guild.get_role(CHAT_MUTE_ROLE_ID)
    if chat_mute_role and chat_mute_role in member.roles:
        return True
    if member.timed_out_until and member.timed_out_until > discord.utils.utcnow():
        return True
    return False


def _cancel_chat_mute_expiry(user_id: int) -> None:
    task = chat_mute_expiry_tasks.pop(user_id, None)
    if task and not task.done():
        task.cancel()


async def _schedule_chat_mute_expiry(member: discord.Member, duration: timedelta) -> None:
    guild = member.guild
    user_id = member.id
    seconds = max(int(duration.total_seconds()), 1)

    async def _expire():
        await asyncio.sleep(seconds)
        chat_mute_expiry_tasks.pop(user_id, None)
        target = guild.get_member(user_id)
        if target is None:
            try:
                target = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.HTTPException):
                return
        try:
            await _safe_remove_roles(target, [CHAT_MUTE_ROLE_ID], reason="Chat mute expired")
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"Chat mute role removal failed for {user_id}: {exc}")

    _cancel_chat_mute_expiry(user_id)
    chat_mute_expiry_tasks[user_id] = asyncio.create_task(_expire())


async def _apply_chat_mute(
    member: discord.Member,
    duration: timedelta,
    moderator: discord.Member,
    reason: str,
) -> None:
    mute_reason = f"{moderator}: {reason}"
    await _safe_add_roles(member, [CHAT_MUTE_ROLE_ID], reason=mute_reason)
    until = discord.utils.utcnow() + duration
    try:
        await member.timeout(until, reason=mute_reason)
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(f"Chat mute timeout failed for {member.id}: {exc}")
    await _schedule_chat_mute_expiry(member, duration)


async def _remove_chat_mute(
    member: discord.Member,
    moderator: discord.Member,
    *,
    reason: str = "Chat mute removed",
) -> None:
    remove_reason = f"{moderator}: {reason}"
    _cancel_chat_mute_expiry(member.id)
    await _safe_remove_roles(member, [CHAT_MUTE_ROLE_ID], reason=remove_reason)
    try:
        await member.timeout(None, reason=remove_reason)
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(f"Remove chat mute timeout failed for {member.id}: {exc}")


def _is_voice_muted(member: discord.Member) -> bool:
    return _has_voice_mute_role(member) or (
        member.voice is not None and member.voice.channel is not None and member.voice.mute
    )


def _has_voice_mute_role(member: discord.Member) -> bool:
    voice_mute_role = member.guild.get_role(VOICE_MUTE_ROLE_ID)
    return bool(voice_mute_role and voice_mute_role in member.roles)


async def _enforce_voice_mute_state(member: discord.Member, *, reason: str = "Voice mute active") -> None:
    if member.bot or not _has_voice_mute_role(member):
        return
    if not member.voice or not member.voice.channel or member.voice.mute:
        return
    try:
        await member.edit(mute=True, reason=reason)
    except (discord.Forbidden, discord.HTTPException) as exc:
        print(f"Voice mute enforce failed for {member.id}: {exc}")


async def _remove_voice_mute(
    member: discord.Member,
    moderator: discord.Member,
    *,
    reason: str = "Voice mute removed",
) -> None:
    remove_reason = f"{moderator}: {reason}"
    await _safe_remove_roles(member, [VOICE_MUTE_ROLE_ID], reason=remove_reason)
    if member.voice and member.voice.channel:
        try:
            await member.edit(mute=False, reason=remove_reason)
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"Remove voice mute failed for {member.id}: {exc}")


async def _enforce_chat_mute(message: discord.Message) -> bool:
    if not message.guild or message.author.bot:
        return False
    if not isinstance(message.author, discord.Member):
        return False
    if not _is_chat_muted(message.author):
        return False
    if not message.guild.me.guild_permissions.manage_messages:
        return True
    try:
        await message.delete()
    except discord.Forbidden:
        print(f"Cannot delete chat-muted message in {message.channel.id} (missing Manage Messages)")
    except discord.HTTPException as exc:
        print(f"Failed to delete chat-muted message: {exc.text}")
    return True


async def _apply_warn_3_mutes(member: discord.Member, moderator: discord.Member, reason: str) -> None:
    mute_reason = f"{moderator}: Warn 3 — {reason}"
    await _apply_chat_mute(member, WARN_3_MUTE_DURATION, moderator, f"Warn 3 — {reason}")
    await _enforce_voice_mute_state(member, reason=mute_reason)


async def _apply_warn_consequences(
    member: discord.Member,
    count: int,
    moderator: discord.Member,
    reason: str,
) -> None:
    sync_reason = f"Warn {count} by {moderator}: {reason}"
    try:
        if count == 1:
            await _safe_add_roles(member, [WARN_1_ROLE_ID], reason=sync_reason)
        elif count == 2:
            await _safe_add_roles(member, [WARN_2_ROLE_ID], reason=sync_reason)
        elif count == 3:
            await _safe_remove_roles(member, WARN_EARLY_ROLE_IDS, reason=sync_reason)
            await _apply_warn_3_mutes(member, moderator, reason)
            await _safe_add_roles(member, [VOICE_MUTE_ROLE_ID], reason=sync_reason)
    except discord.Forbidden:
        print(f"Warn {count} role action failed for {member.id}: missing Manage Roles or hierarchy issue")
    except discord.HTTPException as exc:
        print(f"Warn {count} role action failed for {member.id}: {exc.text}")


async def _sync_warn_roles_after_count(
    member: discord.Member,
    count: int,
    moderator: discord.Member,
    *,
    reason: str = "Warnings cleared",
) -> None:
    """Remove warn roles/mutes that no longer match the warning count."""
    sync_reason = f"{moderator}: {reason}"
    try:
        if count < 2:
            await _safe_remove_roles(member, [WARN_2_ROLE_ID], reason=sync_reason)
        if count < 1:
            await _safe_remove_roles(member, [WARN_1_ROLE_ID], reason=sync_reason)
            await _remove_chat_mute(member, moderator, reason=sync_reason)
            await _remove_voice_mute(member, moderator, reason=sync_reason)
    except discord.Forbidden:
        print(f"Warn role sync failed for {member.id}: missing Manage Roles or hierarchy issue")
    except discord.HTTPException as exc:
        print(f"Warn role sync failed for {member.id}: {exc.text}")


@bot.event
async def on_ready():
    global _startup_done
    if os.environ.pop("DISCORD_LOGIN_ATTEMPT", None):
        print("Discord login succeeded after rate-limit backoff.")
    print(f"Logged in as {bot.user} (build {BOT_BUILD_ID})")
    print(
        f"Commands: prefix={COMMAND_PREFIX!r} | "
        f"message_content intent={intents.message_content} | "
        f"members intent={intents.members}"
    )
    if not intents.message_content:
        print("WARNING: message_content intent is OFF — ?commands will not work.")
    else:
        print(
            "If ?commands do not work, enable **Message Content Intent** in "
            "Discord Developer Portal → Bot → Privileged Gateway Intents → Save."
        )

    if _startup_done:
        print("Reconnect — skipping heavy startup (avoids Discord rate limits).")
        await bot.change_presence(status=discord.Status.dnd)
        return

    _startup_done = True

    _load_warnings()
    _load_levels_database()
    if await _restore_levels_from_discord():
        print("Using Discord levels backup as source of truth.")
    else:
        print("Using local levels file (no Discord backup yet).")
    await _post_levels_backup(reason="startup")
    print(
        f"Rate-limit settings: bot-chat keepalive {BOT_CHAT_KEEPALIVE_MINUTES}m, "
        f"punishment cap {PUNISHMENT_POST_CAP}/min, welcome cap {WELCOME_POST_CAP}/min"
    )

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
    for guild in bot.guilds:
        try:
            await _cleanup_and_register_temp_rooms(guild)
            _log_join_to_create_startup(guild)
        except Exception as e:
            print(f"Temp room startup cleanup failed for {guild.name}: {e}")

    bot.add_view(GameRolePickerView())
    bot.add_view(TicketPanelView())

    for guild in bot.guilds:
        try:
            await _register_existing_ticket_channels(guild)
            if GUILD_INIT_STEP_DELAY:
                await asyncio.sleep(GUILD_INIT_STEP_DELAY)
            success, message = await _apply_guild_notification_settings(guild)
            if success and "updated" in message.lower():
                print(message)
            elif not success and SET_DEFAULT_NOTIFICATIONS_ONLY_MENTIONS:
                print(f"{guild.name}: {message}")
            if GUILD_INIT_STEP_DELAY:
                await asyncio.sleep(GUILD_INIT_STEP_DELAY)
            await _refresh_bot_chat_welcome_message(guild)
            if GUILD_INIT_STEP_DELAY:
                await asyncio.sleep(GUILD_INIT_STEP_DELAY)
            await _ensure_ticket_panel(guild)
            await _log_ticket_setup(guild)
        except Exception as e:
            print(f"Guild init failed for {guild.name}: {e}")
        if GUILD_INIT_STEP_DELAY:
            await asyncio.sleep(GUILD_INIT_STEP_DELAY)

    await bot.change_presence(status=discord.Status.dnd)
    try:
        synced = await bot.tree.sync()
        print(f"Slash commands synced: {len(synced)} (/ping, /level, …)")
    except discord.HTTPException as exc:
        print(f"Slash command sync failed: {exc.text}")
    print("System online.")


@bot.event
async def on_resumed():
    await bot.change_presence(status=discord.Status.dnd)


@tasks.loop(minutes=BOT_CHAT_KEEPALIVE_MINUTES)
async def bot_chat_keepalive_task():
    for guild in bot.guilds:
        try:
            await _refresh_bot_chat_welcome_message(guild)
        except Exception as e:
            print(f"Bot chat keepalive failed for {guild.name}: {e}")


@tasks.loop(minutes=EMPTY_ROOM_CLEANUP_MINUTES)
async def empty_temp_rooms_cleanup_task():
    for guild in bot.guilds:
        try:
            await _purge_empty_temp_rooms(
                guild,
                reason="Empty temp voice room periodic cleanup",
            )
        except Exception as e:
            print(f"Empty temp room cleanup failed for {guild.name}: {e}")


@tasks.loop(minutes=1.0)
async def update_voice_levels_task():
    changed = False
    level_ups: list[tuple[discord.Guild, discord.Member, int, int]] = []
    skip_ids = _JOIN_TO_CREATE_HUB_IDS | {BOT_VOICE_CHANNEL_ID}

    for guild in bot.guilds:
        for vc in guild.voice_channels:
            if vc.id in skip_ids or not vc.members:
                continue
            for member in vc.members:
                if member.bot or not member.voice or member.voice.self_deaf:
                    continue
                entry = _normalize_user_level_data(user_levels.get(member.id, {}))
                old_level = entry["level"]
                entry["voice_minutes"] += 1
                entry["level"] = _level_from_voice_minutes(entry["voice_minutes"])
                user_levels[member.id] = entry
                changed = True
                if entry["level"] > old_level:
                    level_ups.append((guild, member, old_level, entry["level"]))

    if changed:
        _save_levels_database()

    for guild, member, old_level, new_level in level_ups:
        log_channel = guild.get_channel(LEVEL_LOG_CHANNEL_ID)
        if not log_channel:
            continue
        try:
            await log_channel.send(
                f"🎉 {member.mention} reached **Level {new_level}**! (was {old_level})"
            )
        except discord.HTTPException as exc:
            print(f"Level-up announce failed for {member.id}: {exc.text}")


@bot_chat_keepalive_task.before_loop
async def before_bot_chat_keepalive_task():
    await bot.wait_until_ready()


@empty_temp_rooms_cleanup_task.before_loop
async def before_empty_temp_rooms_cleanup_task():
    await bot.wait_until_ready()


@tasks.loop(minutes=1.0)
async def update_voice_levels_task():
    changed = False
    level_ups: list[tuple[discord.Guild, discord.Member, int, int]] = []
    skip_ids = VOICE_LEVEL_SKIP_CHANNEL_IDS

    for guild in bot.guilds:
        for vc in guild.voice_channels:
            if vc.id in skip_ids or not vc.members:
                continue
            for member in vc.members:
                if member.bot or not member.voice or member.voice.self_deaf:
                    continue
                entry = _normalize_user_level_data(user_levels.get(member.id, {}))
                old_level = entry["level"]
                entry["voice_minutes"] += 1
                entry["level"] = _level_from_voice_minutes(entry["voice_minutes"])
                user_levels[member.id] = entry
                changed = True
                if entry["level"] > old_level:
                    level_ups.append((guild, member, old_level, entry["level"]))

    if changed:
        _save_levels_database()

    for guild, member, old_level, new_level in level_ups:
        log_channel = guild.get_channel(LEVEL_LOG_CHANNEL_ID)
        if not log_channel:
            continue
        content_msg = f"🎉 {member.mention} reached **Level {new_level}**! (was {old_level})"
        try:
            buffer = await build_level_up_card(member, old_level, new_level)
            await log_channel.send(
                content=content_msg,
                file=discord.File(buffer, filename="level_up.png"),
            )
        except Exception as exc:
            print(f"Level-up card failed for {member.id}: {exc}")
            try:
                await log_channel.send(content_msg)
            except discord.HTTPException as send_exc:
                print(f"Level-up announce failed for {member.id}: {send_exc.text}")


@bot_chat_keepalive_task.before_loop
async def before_bot_chat_keepalive_task():
    await bot.wait_until_ready()


@update_voice_levels_task.before_loop
async def before_update_voice_levels_task():
    await bot.wait_until_ready()


@tasks.loop(hours=LEVELS_BACKUP_HOURS)
async def levels_backup_task():
    if not user_levels:
        return
    await _post_levels_backup(reason="hourly")


@levels_backup_task.before_loop
async def before_levels_backup_task():
    await bot.wait_until_ready()
    # Wait one full interval before first hourly post (startup restore already loaded data).
    await asyncio.sleep(LEVELS_BACKUP_HOURS * 3600)


@bot.tree.command(name="ping", description="Vérifie si le bot est en ligne")
async def slash_ping(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"Pong — `{round(bot.latency * 1000)}ms` • build `{BOT_BUILD_ID}`",
        ephemeral=True,
    )


@bot.tree.command(name="level", description="Affiche le level vocal")
@app_commands.describe(member="Membre (optionnel)")
async def slash_level(interaction: discord.Interaction, member: discord.Member | None = None):
    target = member or interaction.user
    if target.bot:
        return await interaction.response.send_message("Les bots n'ont pas de level vocal.", ephemeral=True)
    embed = _format_level_embed(target)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.command(name="ping")
async def ping_cmd(ctx):
    """Check if the bot is online and responding."""
    await ctx.send(
        f"Pong — `{round(bot.latency * 1000)}ms` • build `{BOT_BUILD_ID}`",
        delete_after=10,
    )


@bot.command(name="level", aliases=["lvl", "niveau"])
async def level_cmd(ctx, member: discord.Member = None):
    """Show voice level stats. Usage: ?level or ?level @user"""
    target = member or ctx.author
    if target.bot:
        return await ctx.send("Bots do not have voice levels.", delete_after=8)
    embed = _format_level_embed(target)
    await ctx.send(embed=embed, delete_after=45)


@bot.command(name="checkbot")
@commands.has_permissions(manage_guild=True)
async def check_bot_cmd(ctx):
    """Diagnose why prefix commands may not work in this channel."""
    me = ctx.guild.me
    if me is None:
        return await ctx.send("Bot member not found in this guild.", delete_after=12)

    perms = ctx.channel.permissions_for(me)
    muted = isinstance(ctx.author, discord.Member) and _is_chat_muted(ctx.author)
    lines = [
        f"**Prefix:** `{COMMAND_PREFIX}`",
        f"**Build:** `{BOT_BUILD_ID}`",
        f"**Message Content Intent (code):** `{intents.message_content}`",
        f"**Read this channel:** `{'yes' if perms.read_messages else 'NO'}`",
        f"**Send in this channel:** `{'yes' if perms.send_messages else 'NO'}`",
        f"**Embed links:** `{'yes' if perms.embed_links else 'NO'}`",
        f"**You are chat-muted:** `{'yes' if muted else 'no'}`",
        "",
        f"Test prefix: `{COMMAND_PREFIX}ping`",
        "Test slash: `/ping` (works even without Message Content Intent)",
    ]
    if not perms.send_messages:
        lines.append("\n❌ I **cannot send messages** in this channel.")
    if not intents.message_content:
        lines.append("\n❌ `message_content` intent is disabled in code.")

    embed = discord.Embed(title="Bot diagnostics", description="\n".join(lines), color=discord.Color.blue())
    await ctx.send(embed=embed, delete_after=60)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="checkjoincreate")
@commands.has_permissions(manage_guild=True)
async def check_join_create_cmd(ctx):
    """Verify join-to-create hub channels, bot permissions, and category setup."""
    guild = ctx.guild
    me = guild.me
    lines = [f"**Build:** `{BOT_BUILD_ID}`"]

    if me is None:
        lines.append("**Bot member:** NOT FOUND in this guild.")
    else:
        perm_bits = (
            ("Manage Channels", me.guild_permissions.manage_channels),
            ("Move Members", me.guild_permissions.move_members),
            ("Connect", me.guild_permissions.connect),
            ("Send Messages", me.guild_permissions.send_messages),
        )
        perm_status = ", ".join(
            f"{'✅' if ok else '❌'} {label}" for label, ok in perm_bits
        )
        lines.append(f"**Bot permissions:** {perm_status}")
        if me.top_role:
            lines.append(f"**Bot top role:** {me.top_role.name} (position {me.top_role.position})")

    hub_labels = {
        CREATE_CHANNEL_ID: "Create Lounge",
        SUPPORT_CHANNEL_ID: "Support",
        VERIFICATION_1_ID: "Verification 1",
        VERIFICATION_2_ID: "Verification 2",
    }
    lines.append("**Configured hubs:**")
    for hub_id, label in hub_labels.items():
        channel = guild.get_channel(hub_id)
        if isinstance(channel, discord.VoiceChannel):
            cat = channel.category
            cat_text = f"{cat.name} (`{cat.id}`)" if cat else "⚠️ **no category**"
            lines.append(f"✅ **{label}** — {channel.mention} (`{channel.id}`) → {cat_text}")
        elif channel is None:
            lines.append(f"❌ **{label}** — channel `{hub_id}` **not found** (wrong ID or bot cannot see it)")
        else:
            lines.append(f"❌ **{label}** — `{hub_id}` exists but is **not a voice channel** ({type(channel).__name__})")

    voice_hubs = [
        ch for ch in guild.voice_channels
        if ch.id not in _JOIN_TO_CREATE_HUB_IDS
        and ch.category
        and "create" in ch.name.lower()
    ]
    if voice_hubs:
        hints = ", ".join(f"**{ch.name}** (`{ch.id}`)" for ch in voice_hubs[:5])
        lines.append(
            f"**Hint:** voice channels with “create” in the name that are **not** configured: {hints}"
        )
        lines.append(
            "If users join one of those, update the ID in Render env / `.env` "
            f"(`CREATE_CHANNEL_ID=...`) or run `{COMMAND_PREFIX}checkjoincreate` after fixing."
        )

    embed = discord.Embed(
        title="Join-to-Create Check",
        description="\n".join(lines),
        color=discord.Color.green(),
    )
    await ctx.send(embed=embed, delete_after=60)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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


@bot.command(name="testlevel", aliases=["testlvl", "testlevelup"])
async def test_level_cmd(
    ctx,
    member: discord.Member = None,
    old_level: int = 4,
    new_level: int = 5,
):
    """Preview level-up card. Usage: ?testlevel [@user] [old] [new]"""
    target = member or ctx.author
    if target.bot:
        return await ctx.send("Bots do not have voice levels.", delete_after=8)
    if old_level < 0 or new_level < 0:
        return await ctx.send("Levels must be >= 0.", delete_after=8)
    if new_level <= old_level:
        new_level = old_level + 1

    content_msg = f"🎉 {target.mention} reached **Level {new_level}**! (was {old_level}) *(test)*"
    try:
        buffer = await build_level_up_card(target, old_level, new_level)
        await ctx.send(
            content=content_msg,
            file=discord.File(buffer, filename="level_up.png"),
        )
    except Exception as e:
        await ctx.send(f"Level card test failed: {e}")


@bot.command(name="backuplevels", aliases=["levelbackup"])
@commands.has_permissions(manage_guild=True)
async def backup_levels_cmd(ctx):
    """Force-post levels JSON backup to the backup channel."""
    ok = await _post_levels_backup(reason=f"manual:{ctx.author.id}")
    if ok:
        await ctx.send("✅ Levels backup t7at fil channel.", delete_after=10)
    else:
        await ctx.send("❌ Backup fashal — chouf logs / channel ID.", delete_after=12)


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


@bot.command(name="syncroles", aliases=["syncjoinroles"])
@commands.has_permissions(manage_guild=True)
async def sync_roles_cmd(ctx, member: discord.Member = None):
    """Give the 5 default member roles to all members who are missing them (admin)."""
    guild = ctx.guild
    status = await ctx.send("⏳ Jari nesta3mlou el roles...")

    roles = _get_guild_roles_by_ids(guild, NEW_MEMBER_ROLE_IDS)
    if not roles:
        return await status.edit(content="❌ Ma l9inahomch el roles fi serveur. Chouf el IDs fi bot.py.")

    issue = _bot_role_assignment_issue(guild, roles)
    if issue:
        return await status.edit(content=f"❌ {issue}")

    reason = f"Role sync by {ctx.author}"
    role_names = ", ".join(role.name for role in roles)

    if member is not None:
        try:
            added = await _assign_missing_roles(member, roles, reason=reason)
            if added:
                return await status.edit(
                    content=f"✅ **{member.display_name}** ta7 el {added} role(s): {role_names}"
                )
            return await status.edit(content=f"ℹ️ **{member.display_name}** 3andou deja kol el roles.")
        except discord.Forbidden:
            return await status.edit(
                content=f"❌ Ma najamtech na3ti roles le **{member.display_name}**. Chouf hierarchy mta3 el bot."
            )
        except discord.HTTPException as exc:
            return await status.edit(content=f"❌ Error: {exc.text}")

    await status.edit(content="⏳ Jari nejibou liste el membres...")

    try:
        members = await asyncio.wait_for(_fetch_human_members(guild), timeout=120.0)
    except asyncio.TimeoutError:
        return await status.edit(
            content=(
                "❌ Timeout fi jib el membres (barcha 3bed).\n"
                f"Jarreb: `{COMMAND_PREFIX}syncroles @user` 3la wa7ed wa7ed."
            )
        )
    except discord.Forbidden:
        return await status.edit(
            content=(
                "❌ El bot ma 3andhouch access lel membres.\n"
                "Chouf **Server Members Intent** fi Discord Developer Portal."
            )
        )
    except Exception as e:
        print(f"syncroles fetch failed: {e}")
        return await status.edit(content=f"❌ Error fi jib el membres: `{e}`")

    total = len(members)
    if total == 0:
        return await status.edit(
            content="❌ Ma l9inahch membres. Chouf **Server Members Intent** fi Developer Portal."
        )

    updated = 0
    skipped = 0
    failed = 0
    first_error = None

    for index, target in enumerate(members, start=1):
        try:
            added = await _assign_missing_roles(target, roles, reason=reason)
            if added:
                updated += 1
            else:
                skipped += 1
        except discord.Forbidden:
            failed += 1
            if first_error is None:
                first_error = f"{target.display_name}: bot role ta7t role el membre"
        except discord.HTTPException as exc:
            failed += 1
            if first_error is None:
                first_error = f"{target.display_name}: {exc.text}"
            if exc.status == 429:
                await _await_rate_limit(exc, label="syncroles")

        if index < total and SYNCROLES_MEMBER_DELAY:
            await asyncio.sleep(SYNCROLES_MEMBER_DELAY)

        if index % 15 == 0 or index == total:
            try:
                await status.edit(
                    content=(
                        f"⏳ Jari... **{index}/{total}**\n"
                        f"• Updated: **{updated}** | Skipped: **{skipped}** | Failed: **{failed}**"
                    )
                )
            except discord.HTTPException:
                pass

    lines = [
        "✅ **Sync roles kemmel!**",
        f"• **Roles:** {role_names}",
        f"• **Updated:** {updated}",
        f"• **Deja 3andhomhom:** {skipped}",
        f"• **Failed:** {failed}",
    ]
    if failed and first_error:
        lines.append(f"• **Awel error:** {first_error}")
    if updated == 0 and failed == 0:
        lines.insert(0, "ℹ️ Kol el membres 3andhom deja el roles.")

    await status.edit(content="\n".join(lines))


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
    """Repost your message as the bot (deletes your command). Usage: ?post Hello everyone"""
    content = (message or "").strip()
    attachments = list(ctx.message.attachments)

    if not content and not attachments:
        return await ctx.send(f"Usage: `{COMMAND_PREFIX}post your message here`", delete_after=8)

    files = [await attachment.to_file() for attachment in attachments]

    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass

    await ctx.send(content or None, files=files or None)


def _parse_giveaway_hours(raw: str) -> float:
    """Accept `1`, `1.5` (hours) or duration tokens like `30m`, `1h`, `2d`."""
    text = (raw or "").strip().lower()
    if not text:
        raise ValueError("empty duration")

    duration = _parse_duration(text)
    if duration is not None:
        hours = duration.total_seconds() / 3600.0
    else:
        hours = float(text)

    if hours <= 0:
        raise ValueError("non-positive duration")
    return hours


@bot.command(name="giveaway")
async def giveaway_cmd(ctx):
    global current_giveaway_view
    guild = _get_giveaway_guild()
    if guild is None:
        return await ctx.send("❌ Giveaway channel ma l9inech. Chouf el config mta3 el bot.", delete_after=10)

    member = guild.get_member(ctx.author.id)
    if not member:
        try:
            member = await guild.fetch_member(ctx.author.id)
        except discord.NotFound:
            return await ctx.author.send("❌ أنت لست عضواً في السيرفر المخصص لهذا البوت!")

    if not _is_giveaway_admin(member):
        return await ctx.author.send("❌ Ma 3andekch el permission kan t7ab bara a7ki ma3 @mobo33.3 !")

    try:
        await ctx.author.send("👋 Ahla bik! Haya n7athrou el giveaway m3a ba3dhna. Jawebni 3ala hal as2la:")
        if ctx.guild:
            await ctx.send(
                f"✅ <@{ctx.author.id}>, b3athtlek message privé (DM) bech n7athrou el giveaway!"
            )
    except discord.Forbidden:
        await ctx.send("❌ Ma najamtech nab3athlek message! Lazmek t7el les messages privés (DMs) mta3ek.")
        return

    def check(m):
        return m.author == ctx.author and m.channel == ctx.author.dm_channel

    try:
        await ctx.author.send("🎁 **1. Chnouwa el jeyza?**")
        msg_prize = await bot.wait_for("message", timeout=60.0, check=check)
        prize = msg_prize.content

        await ctx.author.send(
            "⏳ **2. 9adeh bech yo93od el giveaway?**\n"
            "👉 Mathalan: `1` (se3a), `1h`, `30m`, `2d`"
        )
        msg_time = await bot.wait_for("message", timeout=60.0, check=check)
        hours = _parse_giveaway_hours(msg_time.content)

        await ctx.author.send("🏆 **3. 9adeh min we7ed bech yarba7?**")
        msg_winners = await bot.wait_for("message", timeout=60.0, check=check)
        winners_count = int(msg_winners.content)

        await ctx.author.send(
            "🎲 **4. T7eb chkoun yarba7 yt7aded zhar?**\n"
            "👉 Ekteb `random` ken t7ebha zhar.\n"
            "👉 Walla a3tini el **ID** mta3 cha5s mo3ayen ken t7ebou yarba7 bessaif."
        )
        msg_mode = await bot.wait_for("message", timeout=60.0, check=check)
        mode = msg_mode.content.strip().lower()

    except asyncio.TimeoutError:
        return await ctx.author.send(f"❌ Btit barcha ma jawebtnech! 3awed ekteb `{COMMAND_PREFIX}giveaway` min jdid.")
    except ValueError:
        return await ctx.author.send(
            "❌ Ghalta fil wa9t walla ar9am!\n"
            f"👉 Wa9t: `1`, `1h`, `30m`, `2d` — 3awed `{COMMAND_PREFIX}giveaway`."
        )

    await ctx.author.send(
        f"✅ Sayé, el giveaway hebet tawa fil serveur! (Tnajem tekteb `{COMMAND_PREFIX}stop` houni ken t7eb twa9afha wa9t ma t7eb)."
    )

    end_time = int(time.time() + (hours * 3600))
    embed = discord.Embed(
        title=f"🎉 GIVEAWAY: {prize} 🎉",
        description=(
            f"**Enzel 3al 9ars louta bach tqayed m3ana!**\n\n"
            f"⏳ Toufa: <t:{end_time}:R>\n"
            f"🏆 9adeh min we7ed bech yarba7: **{winners_count}**\n"
            f"🎁 El Jeyza: **{prize}**"
        ),
        color=discord.Color.blue(),
    )
    embed.set_footer(text=f"Hosted by: {ctx.author.display_name} | Famma 9ars bach tchouf chkoun charek")

    view = GiveawayView(timeout=hours * 3600)
    current_giveaway_view = view

    channel = bot.get_channel(GIVEAWAY_CHANNEL_ID)
    if not channel:
        channel = ctx.channel

    msg = await channel.send(embed=embed, view=view)

    stop_event = asyncio.Event()
    active_giveaways[ctx.author.id] = stop_event

    try:
        await asyncio.wait_for(stop_event.wait(), timeout=hours * 3600)
    except asyncio.TimeoutError:
        pass

    is_manually_stopped = stop_event.is_set()

    if ctx.author.id in active_giveaways:
        del active_giveaways[ctx.author.id]

    for child in view.children:
        child.disabled = True
    await msg.edit(view=view)

    current_giveaway_view = None

    if is_manually_stopped:
        await channel.send("desole fama 7aja 8alta taw ba3ad nchofo kifah")
        return

    if len(view.participants) == 0:
        await channel.send(f"Giveaway 3ala **{prize}** wfet, ama 7ad ma 9ayed! 😢")
        return

    actual_winners_count = min(winners_count, len(view.participants))

    if mode == "random":
        winners = random.sample(list(view.participants), actual_winners_count)
    else:
        rigged_id = int(mode) if mode.isdigit() else None
        if rigged_id and rigged_id in view.participants:
            winners = [rigged_id]
            if actual_winners_count > 1:
                remaining = list(view.participants)
                remaining.remove(rigged_id)
                winners += random.sample(remaining, actual_winners_count - 1)
        else:
            winners = random.sample(list(view.participants), actual_winners_count)

    winners_mentions = ", ".join(f"<@{w}>" for w in winners)
    count_participants = len(view.participants)

    public_msg = (
        f"🎉 **WFET EL GIVEAWAY!** 🎉\n\n"
        f"🎁 **El Jeyza:** {prize}\n"
        f"👑 **Eli rba7:** {winners_mentions} (Mabrouk!)\n"
        f"👥 **9adeh charkou:** {count_participants} min nes\n\n"
        f"🔗 **Link mta3 giveaway:** {msg.jump_url}"
    )
    await channel.send(public_msg)

    for winner_id in winners:
        try:
            winner_user = await bot.fetch_user(winner_id)
            await winner_user.send(
                f"🎉 **MABROUK!** 🎉\n"
                f"Rak rba7t **{prize}** fil giveaway mta3 serveur!\n"
                f"🔗 Tnajem tchouf el resulta houni: {msg.jump_url}"
            )
        except discord.Forbidden:
            pass
        except Exception as e:
            print(f"Erreur DM lel reba7: {e}")


@bot.command(name="stop")
async def stop_giveaway_cmd(ctx):
    guild = _get_giveaway_guild()
    if guild is None:
        return await ctx.send("❌ Giveaway channel ma l9inech.", delete_after=10)

    try:
        member = await guild.fetch_member(ctx.author.id)
    except discord.NotFound:
        return await ctx.send("❌ Enti mch fil serveur mta3 el giveaway!")

    if not _is_giveaway_admin(member):
        return await ctx.send("❌ Ma 3andekch el permission bech twa9af el giveaway!")

    if ctx.author.id in active_giveaways:
        active_giveaways[ctx.author.id].set()
        await ctx.send("🛑 **Sayé, 3tit amr bech nwa9af el giveaway tawa!**")
    else:
        await ctx.send("❌ Ma fammech giveaway te5dem bil ID hetha.")


@bot.command(name="kickuser")
async def kickuser_giveaway_cmd(ctx, user: discord.User):
    global current_giveaway_view

    guild = _get_giveaway_guild()
    if guild is None:
        return await ctx.send("❌ Giveaway channel ma l9inech.", delete_after=10)

    try:
        member = await guild.fetch_member(ctx.author.id)
    except discord.NotFound:
        return await ctx.send("❌ Error")

    if not _is_giveaway_admin(member) and ctx.author.id != guild.owner_id:
        return await ctx.send("❌ Ma 3andekch permission bech testa3mel hal command!")

    if current_giveaway_view is None:
        return await ctx.send("❌ Ma famma 7atta giveaway te5dem tawa باش تنحي منها شكون!")

    if user.id in current_giveaway_view.participants:
        current_giveaway_view.participants.remove(user.id)
        current_giveaway_view.kicked_users.add(user.id)
        await ctx.send(f"✅ **{user.name}** tna7a men hal giveaway w m9ادش ينجم يدخل فيها!")
    else:
        current_giveaway_view.kicked_users.add(user.id)
        await ctx.send(
            f"🚫 **{user.name}** mch m9ayed, ama t7at fi block mta3 hal giveaway (ميقدرش يدخلها)!"
        )


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


def _is_ban_timeout_immune(member: discord.Member) -> bool:
    return _member_has_any_role(member, BAN_TIMEOUT_IMMUNE_ROLE_IDS)


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
    punisher: discord.abc.User | None = None,
    finish_command: bool = True,
):
    moderator = punisher or ctx.author
    try:
        buffer = await build_punishment_card(target, moderator, reason, punishment_type)
    except Exception as exc:
        print(f"Punishment card build failed ({punishment_type}): {exc}")
        await ctx.send(f"Punishment card failed: {exc}", delete_after=12)
        return False

    card_bytes = buffer.getvalue()
    image_file = discord.File(io.BytesIO(card_bytes), filename="punishment.png")
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

    if not preview and not _should_post_punishment():
        print(f"Punishment log post skipped (cap {PUNISHMENT_POST_CAP}/min).")
        await ctx.send(
            "Punishment applied but log card delayed (rate limit protection).",
            delete_after=12,
        )
        if finish_command:
            await _finish_staff_command(ctx, True, log_channel)
        return True

    try:
        await _api_call_with_retry(
            lambda: _send_to_punishment_log(
                log_channel,
                content,
                discord.File(io.BytesIO(card_bytes), filename="punishment.png"),
            ),
            label="Punishment log post",
        )
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

    dm_recipient = ctx.author if preview else target
    if dm_recipient and not dm_recipient.bot:
        dm_lines = [
            f"⚠️ **Punishment — {label}**",
            f"**Server:** {ctx.guild.name}",
            f"**Reason:** {reason}",
        ]
        if preview:
            dm_lines.insert(0, "*(Preview — hedha ma howach punishment 7a9i9i)*")
        if duration:
            dm_lines.append(f"**Duration:** {_format_duration(duration)}")
        if extra_note:
            dm_lines.append(extra_note)
        dm_file = discord.File(io.BytesIO(card_bytes), filename="punishment.png")
        try:
            await dm_recipient.send("\n".join(dm_lines), file=dm_file)
        except discord.Forbidden:
            who = "command author" if preview else f"target {target.id}"
            print(f"Punishment DM blocked for {who} (DMs closed)")
        except discord.HTTPException as exc:
            print(f"Punishment DM failed for {dm_recipient.id}: {exc.text}")
        except Exception as exc:
            print(f"Punishment DM unexpected error for {dm_recipient.id}: {exc}")

    if finish_command:
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
    if _is_ban_timeout_immune(member):
        return await ctx.send("❌ Ma tnajemch tbani had el membre (role protégé).", delete_after=8)

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
    """Timeout a member. Example: ?timeout @user 1h spam"""
    if not ctx.author.guild_permissions.moderate_members:
        return await ctx.send("You need **Moderate Members** permission.", delete_after=8)
    if not _can_punish_target(ctx.author, member):
        return await ctx.send("You cannot punish this member.", delete_after=8)
    if _is_ban_timeout_immune(member):
        return await ctx.send("❌ Ma tnajemch ttimeouti had el membre (role protégé).", delete_after=8)

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
    """Chat mute (timeout). Example: ?chatmute @user 30m toxic"""
    if not ctx.author.guild_permissions.moderate_members:
        return await ctx.send("You need **Moderate Members** permission.", delete_after=8)
    if not _can_punish_target(ctx.author, member):
        return await ctx.send("You cannot punish this member.", delete_after=8)

    delta = _parse_duration(duration)
    if not delta or delta > MAX_TIMEOUT:
        return await ctx.send("Invalid duration. Example: `30m`, `2h`, `1d` (max 28 days).", delete_after=10)

    try:
        await _apply_chat_mute(member, delta, ctx.author, reason)
    except discord.Forbidden:
        return await ctx.send("I cannot mute this member (check **Manage Roles** / hierarchy).", delete_after=8)
    except discord.HTTPException as exc:
        return await ctx.send(f"Chat mute failed: {exc.text}", delete_after=8)

    await _post_punishment_card(ctx, "chatmute", member, reason, duration=delta)


@bot.command(name="voicemute", aliases=["vmute"])
@_punishment_staff_check()
@commands.bot_has_permissions(moderate_members=True)
async def voicemute_cmd(ctx, member: discord.Member, duration: str, *, reason: str = "No reason provided"):
    """Voice mute. Example: ?voicemute @user 1h mic spam"""
    if not ctx.author.guild_permissions.moderate_members:
        return await ctx.send("You need **Moderate Members** permission.", delete_after=8)
    if not _can_punish_target(ctx.author, member):
        return await ctx.send("You cannot punish this member.", delete_after=8)

    delta = _parse_duration(duration)
    if not delta or delta > MAX_TIMEOUT:
        return await ctx.send("Invalid duration. Example: `30m`, `2h`, `1d` (max 28 days).", delete_after=10)

    mute_reason = f"{ctx.author}: {reason}"
    try:
        await _safe_add_roles(member, [VOICE_MUTE_ROLE_ID], reason=mute_reason)
        await _enforce_voice_mute_state(member, reason=mute_reason)
    except discord.Forbidden:
        return await ctx.send("I cannot voice-mute this member (check **Manage Roles** / hierarchy).", delete_after=8)
    except discord.HTTPException as exc:
        return await ctx.send(f"Voice mute failed: {exc.text}", delete_after=8)

    await _post_punishment_card(ctx, "voicemute", member, reason, duration=delta)


@bot.command(name="untimeout", aliases=["unchatmute", "unmutechat"])
@_punishment_staff_check()
@commands.bot_has_permissions(moderate_members=True)
async def untimeout_cmd(ctx, member: discord.Member, *, reason: str = "Chat mute removed"):
    """Remove chat mute (timeout + chat mute role). Example: ?untimeout @user"""
    if not ctx.author.guild_permissions.moderate_members:
        return await ctx.send("You need **Moderate Members** permission.", delete_after=8)
    if not _can_punish_target(ctx.author, member):
        return await ctx.send("You cannot punish this member.", delete_after=8)

    if not _is_chat_muted(member):
        return await ctx.send(f"{member.mention} is not chat-muted.", delete_after=8)

    try:
        await _remove_chat_mute(member, ctx.author, reason=reason)
    except discord.Forbidden:
        return await ctx.send("I cannot remove chat mute (check **Manage Roles** / hierarchy).", delete_after=8)
    except discord.HTTPException as exc:
        return await ctx.send(f"Untimeout failed: {exc.text}", delete_after=8)

    await ctx.send(f"✅ Chat mute removed for {member.mention}.", delete_after=10)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="unmute", aliases=["unvmute", "unvoicemute"])
@_punishment_staff_check()
@commands.bot_has_permissions(moderate_members=True)
async def unmute_cmd(ctx, member: discord.Member, *, reason: str = "Voice mute removed"):
    """Remove voice mute (server mute + voice mute role). Example: ?unmute @user"""
    if not ctx.author.guild_permissions.moderate_members:
        return await ctx.send("You need **Moderate Members** permission.", delete_after=8)
    if not _can_punish_target(ctx.author, member):
        return await ctx.send("You cannot punish this member.", delete_after=8)

    if not _is_voice_muted(member):
        return await ctx.send(f"{member.mention} is not voice-muted.", delete_after=8)

    try:
        await _remove_voice_mute(member, ctx.author, reason=reason)
    except discord.Forbidden:
        return await ctx.send("I cannot remove voice mute (check **Manage Roles** / hierarchy).", delete_after=8)
    except discord.HTTPException as exc:
        return await ctx.send(f"Unmute failed: {exc.text}", delete_after=8)

    await ctx.send(f"✅ Voice mute removed for {member.mention}.", delete_after=10)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="warn", aliases=["warning"])
@_punishment_staff_check()
async def warn_cmd(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    """Warn a member. Example: ?warn @user toxic behavior"""
    if not _can_punish_target(ctx.author, member):
        return await ctx.send("You cannot punish this member.", delete_after=8)

    count = _add_warning(member.id)
    await _apply_warn_consequences(member, count, ctx.author, reason)

    card_note = f"**({count}/{MAX_WARNS_BEFORE_BAN})**"
    is_warn_3 = count >= MAX_WARNS_BEFORE_BAN
    if is_warn_3:
        _clear_warnings(member.id)
        card_note = f"**({MAX_WARNS_BEFORE_BAN}/{MAX_WARNS_BEFORE_BAN})**"

    await _post_punishment_card(
        ctx,
        "warn",
        member,
        reason,
        extra_note=card_note,
        finish_command=not is_warn_3,
    )

    if is_warn_3:
        bot_member = ctx.guild.me
        warn3_reason = "3 warn"
        await _post_punishment_card(
            ctx,
            "chatmute",
            member,
            warn3_reason,
            duration=WARN_3_MUTE_DURATION,
            punisher=bot_member,
            finish_command=False,
        )
        await _post_punishment_card(
            ctx,
            "voicemute",
            member,
            warn3_reason,
            duration=WARN_3_MUTE_DURATION,
            punisher=bot_member,
            finish_command=True,
        )


@bot.command(name="warnings", aliases=["warns", "getwarns"])
@_punishment_staff_check()
async def warnings_cmd(ctx, member: discord.Member = None):
    """Check how many warnings a member has. Example: ?warnings @user"""
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
    Remove warning(s) from a member and sync warn roles/mutes.
    ?clearwarn @user       → remove all warnings
    ?clearwarn @user 1     → remove one warning
    """
    if member.bot:
        return await ctx.send("Bots cannot have warnings.", delete_after=8)

    current = _get_warning_count(member.id)
    if current == 0:
        return await ctx.send(f"{member.mention} has no warnings.", delete_after=8)

    token = (amount or "all").strip().lower()
    if token == "all":
        _clear_warnings(member.id)
        remaining = 0
        msg = f"All warnings cleared for {member.mention} (was **{current}/{MAX_WARNS_BEFORE_BAN}**)."
    else:
        try:
            remove_count = int(token)
        except ValueError:
            return await ctx.send(f"Usage: `{COMMAND_PREFIX}clearwarn @user` or `{COMMAND_PREFIX}clearwarn @user 1`", delete_after=10)
        if remove_count <= 0:
            return await ctx.send("Amount must be at least 1.", delete_after=8)
        for _ in range(min(remove_count, current)):
            _remove_warning(member.id)
        remaining = _get_warning_count(member.id)
        msg = (
            f"Removed **{min(remove_count, current)}** warning(s) from {member.mention}. "
            f"Now **{remaining}/{MAX_WARNS_BEFORE_BAN}**."
        )

    try:
        await _sync_warn_roles_after_count(member, remaining, ctx.author, reason="Warnings cleared")
    except Exception as exc:
        print(f"clearwarn role sync failed for {member.id}: {exc}")
        msg += "\n⚠️ Counter updated, but some roles/mutes could not be removed."

    await ctx.send(msg, delete_after=12)
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

    # Commands first — chat mute must not block ?ping / ?level before processing.
    await bot.process_commands(message)

    if await _enforce_chat_mute(message):
        return

    try:
        await _log_ticket_message_to_staff(message)
    except Exception as exc:
        print(f"Ticket message handler failed: {exc}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        content = (ctx.message.content or "").strip()
        if content.startswith(COMMAND_PREFIX):
            return await ctx.send(
                f"Commande inconnue. Essaie `{COMMAND_PREFIX}ping` ou tape `/ping` (slash).",
                delete_after=12,
            )
        return

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

    await _assign_join_roles(member)

    if not welcome_channel:
        return

    if not _should_post_welcome():
        print(f"Welcome card skipped for {member.id} (cap {WELCOME_POST_CAP}/min).")
        try:
            await welcome_channel.send(
                content=f"Welcome {member.mention}! The glamorous combatant has landed in **{guild.name}**!"
            )
        except discord.HTTPException as exc:
            if exc.status == 429:
                print("Welcome fallback message skipped (rate limited).")
        return

    try:
        buffer = await build_welcome_card(member)
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
        card_data = buffer.getvalue()
        await _api_call_with_retry(
            lambda: welcome_channel.send(
                content=content_msg,
                file=discord.File(io.BytesIO(card_data), filename="welcome_card.png"),
                embed=embed_welcome,
            ),
            label="Welcome card post",
        )

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
async def on_member_update(before, after):
    if before.roles == after.roles:
        return

    had_voice_mute = any(role.id == VOICE_MUTE_ROLE_ID for role in before.roles)
    has_voice_mute = _has_voice_mute_role(after)

    if not had_voice_mute and has_voice_mute:
        await _enforce_voice_mute_state(after, reason="Voice mute role assigned")
    elif had_voice_mute and not has_voice_mute and after.voice and after.voice.channel:
        try:
            await after.edit(mute=False, reason="Voice mute role removed")
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"Voice unmute on role removal failed for {after.id}: {exc}")


@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild

    if not member.bot and after.channel:
        await _enforce_voice_mute_state(member)

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

    if (
        after.channel
        and after.channel.id in JOIN_TO_CREATE_CHANNELS
        and not member.bot
        and (before.channel is None or before.channel.id != after.channel.id)
    ):
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


async def _close_with_save():
    if user_warnings:
        if _save_warnings():
            print("Warnings saved locally before shutdown.")
    if user_levels:
        _save_levels_database()
        try:
            await _post_levels_backup(reason="shutdown")
        except Exception as exc:
            print(f"Levels backup on shutdown failed: {exc}")
    await _original_bot_close()


bot.close = _close_with_save


def _validate_token() -> None:
    token = (TOKEN or "").strip()
    if not token or token in ("your_bot_token_here", "your_main_bot_token_here"):
        raise SystemExit(
            "Invalid DISCORD_TOKEN. Set a real bot token in Render env vars or .env — "
            "not the placeholder from .env.example."
        )


def _handle_login_rate_limit(exc: discord.HTTPException) -> None:
    """Wait out Discord login 429s instead of exiting immediately (Render restart storm)."""
    attempt = int(os.environ.get("DISCORD_LOGIN_ATTEMPT", "1"))
    max_attempts = max(1, int(os.getenv("DISCORD_LOGIN_MAX_ATTEMPTS", "6")))
    retry_after = float(getattr(exc, "retry_after", 0) or 0)
    wait = min(max(retry_after, 60), 600) if retry_after else 90

    if attempt >= max_attempts:
        raise SystemExit(
            "Discord login still rate-limited (429) after "
            f"{max_attempts} attempts. Stop every other instance using this token "
            "(local PC, second Render service, bot_all_in_one.py), wait 30 minutes, "
            "then redeploy once."
        )

    print(
        f"Discord login rate-limited (429). Attempt {attempt}/{max_attempts}. "
        f"Health check stays up; waiting {wait:.0f}s before a fresh login retry..."
    )
    time.sleep(wait)
    os.environ["DISCORD_LOGIN_ATTEMPT"] = str(attempt + 1)
    os.execv(sys.executable, [sys.executable, *sys.argv])


if __name__ == "__main__":
    _validate_token()

    if os.environ.get("PORT"):
        threading.Thread(target=_start_health_server, daemon=True).start()

    login_delay = max(0.0, float(os.getenv("DISCORD_LOGIN_DELAY_SECONDS", "0")))
    if login_delay:
        print(f"Startup login delay: {login_delay:.0f}s")
        time.sleep(login_delay)

    # bot.run() must be called only once per process — on 429 we sleep then execv for a fresh Client.
    try:
        bot.run(TOKEN)
    except discord.LoginFailure:
        raise SystemExit(
            "Login failed: DISCORD_TOKEN is invalid or revoked. "
            "Reset the token in Discord Developer Portal, update Render, then redeploy."
        ) from None
    except discord.HTTPException as exc:
        if exc.status == 429:
            _handle_login_rate_limit(exc)
        raise
