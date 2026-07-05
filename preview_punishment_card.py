"""Generate a local punishment card preview without running the Discord bot.

Usage:
    python preview_punishment_card.py
    python preview_punishment_card.py ban
    python preview_punishment_card.py warn --avatar https://cdn.discordapp.com/embed/avatars/3.png
"""

import argparse
import asyncio
import io
from pathlib import Path

import aiohttp
from PIL import Image

from punishment_card import LABELS, build_punishment_card

DEFAULT_AVATAR = "https://cdn.discordapp.com/embed/avatars/3.png"
OUTPUT_DIR = Path(__file__).parent / "preview_output"


class _FakeAvatar:
    def __init__(self, url: str):
        self.url = url

    def replace(self, **kwargs):
        return self

    async def read(self) -> bytes:
        headers = {"User-Agent": "LegendsTunisiaPreview/1.0"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(self.url) as resp:
                resp.raise_for_status()
                return await resp.read()


class _FakeUser:
    def __init__(self, user_id: int, name: str, avatar_url: str):
        self.id = user_id
        self.name = name
        self.display_name = name
        self.display_avatar = _FakeAvatar(avatar_url)


async def _generate(punishment_type: str, avatar_url: str, output: Path) -> Path:
    member = _FakeUser(1, "LOST", avatar_url)
    punisher = _FakeUser(2, "hamda", DEFAULT_AVATAR)
    buffer = await build_punishment_card(member, punisher, "Test punishment", punishment_type)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(buffer.getvalue())
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview punishment cards locally.")
    parser.add_argument(
        "type",
        nargs="?",
        default="ban",
        choices=sorted(LABELS.keys()),
        help="Punishment type to preview (default: ban)",
    )
    parser.add_argument(
        "--avatar",
        default=DEFAULT_AVATAR,
        help="Avatar URL for the punished member",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output PNG path (default: preview_output/<type>.png)",
    )
    args = parser.parse_args()
    output = args.output or OUTPUT_DIR / f"{args.type}.png"

    path = asyncio.run(_generate(args.type, args.avatar, output))
    print(f"Preview saved: {path.resolve()}")


if __name__ == "__main__":
    main()
