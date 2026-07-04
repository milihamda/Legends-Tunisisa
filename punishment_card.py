import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PUNISHMENT_DIR = Path(__file__).parent / "punshmentimg"

TEMPLATES = {
    "ban": PUNISHMENT_DIR / "BANNED.jpg",
    "timeout": PUNISHMENT_DIR / "TIMEOUT.jpg",
    "chatmute": PUNISHMENT_DIR / "CHATMUTE.jpg",
    "voicemute": PUNISHMENT_DIR / "VOICEMUTE.jpg",
    "warn": PUNISHMENT_DIR / "warning.jpg",
}

LABELS = {
    "ban": "BAN",
    "timeout": "TIMEOUT",
    "chatmute": "CHAT MUTE",
    "voicemute": "VOICE MUTE",
    "warn": "WARN",
}

# Positions as fractions of template width/height (tweak if text is misaligned)
TEXT_X_RATIO = 0.26
USERNAME_Y_RATIO = 0.335
PUNISHER_Y_RATIO = 0.420
REASON_Y_RATIO = 0.505
FONT_SIZE_RATIO = 0.042
TEXT_COLOR = "#d4a574"
MAX_FIELD_LEN = 48


def _load_font(size: int):
    for path in (
        "C:/Windows/Fonts/timesbd.ttf",
        "C:/Windows/Fonts/times.ttf",
        "C:/Windows/Fonts/georgiab.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _truncate(text: str, max_len: int = MAX_FIELD_LEN) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _display_name(member) -> str:
    return member.display_name or member.name


async def build_punishment_card(
    member,
    punisher,
    reason: str,
    punishment_type: str,
) -> io.BytesIO:
    template_path = TEMPLATES.get(punishment_type)
    if not template_path or not template_path.is_file():
        raise FileNotFoundError(
            f"Missing template for {punishment_type!r}: {template_path}"
        )

    canvas = Image.open(template_path).convert("RGBA")
    width, height = canvas.size
    draw = ImageDraw.Draw(canvas)
    font = _load_font(max(14, int(height * FONT_SIZE_RATIO)))

    text_x = int(width * TEXT_X_RATIO)
    lines = (
        (int(height * USERNAME_Y_RATIO), _truncate(_display_name(member))),
        (int(height * PUNISHER_Y_RATIO), _truncate(_display_name(punisher))),
        (int(height * REASON_Y_RATIO), _truncate(reason or "No reason provided")),
    )

    for y, text in lines:
        draw.text((text_x, y), text, font=font, fill=TEXT_COLOR, anchor="ls")

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
