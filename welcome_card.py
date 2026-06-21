import io
import aiohttp
from PIL import Image, ImageDraw, ImageFont

BACKGROUND_URL = "https://i.imgur.com/XIoPv4J.png"

# Edit ONLY these values, then restart bot: python bot.py
AVATAR_SIZE = (430, 430)
AVATAR_POSITION = (88, 243)
TEXT_POSITION = (898, 500)
FONT_SIZE = 120


def _load_font(size: int):
    for path in (
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/ARIAL.TTF",
        "C:/Windows/Fonts/calibri.ttf",
        "arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


async def build_welcome_card(member, background_url: str = BACKGROUND_URL) -> io.BytesIO:
    print(
        f"[welcome] size={AVATAR_SIZE} pos={AVATAR_POSITION} "
        f"text={TEXT_POSITION} font={FONT_SIZE} user={member.display_name}"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
    }

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
    font = _load_font(FONT_SIZE)

    draw.text(TEXT_POSITION, member.display_name, font=font, fill="#f3cb53", anchor="mm")

    buffer = io.BytesIO()
    background.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
