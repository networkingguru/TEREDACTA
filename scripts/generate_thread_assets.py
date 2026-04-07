"""Generate visual assets for the Threads post and OG social card.

Usage:
    python scripts/generate_thread_assets.py

Requires: Pillow (pip install Pillow or pip install -e .[assets])
Reads: Unobfuscator database for recovery text
Writes: assets/threads/*.jpg, teredacta/static/img/og-card.jpg
"""

import json
import os
import re
import sqlite3
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --- Config ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _find_db_path() -> str:
    """Resolve DB path from env, config, or default."""
    if os.environ.get("UNOBFUSCATOR_DB"):
        return os.environ["UNOBFUSCATOR_DB"]
    # Try teredacta.yaml
    import yaml
    for cfg in [PROJECT_ROOT / "teredacta.yaml", Path.home() / ".teredacta" / "config.yaml"]:
        if cfg.exists():
            with open(cfg) as f:
                data = yaml.safe_load(f) or {}
            if data.get("db_path"):
                return data["db_path"]
    raise FileNotFoundError(
        "Cannot find Unobfuscator DB. Set UNOBFUSCATOR_DB env var or ensure teredacta.yaml exists."
    )


DB_PATH = _find_db_path()
ASSETS_DIR = PROJECT_ROOT / "assets" / "threads"
STATIC_DIR = PROJECT_ROOT / "teredacta" / "static" / "img"
SITE_URL = "teredacta.counting-to-infinity.com"

# Colors (matching TEREDACTA dark theme)
BG_DARK = (18, 24, 38)
TEXT_WHITE = (224, 224, 224)
TEXT_GRAY = (153, 153, 153)
GREEN_HIGHLIGHT = (46, 125, 50)
GREEN_TEXT = (165, 214, 167)
ACCENT_GREEN = (102, 187, 106)
REDACT_BLACK = (0, 0, 0)

# Uniform redaction bar width (does NOT vary with hidden text length)
REDACT_BAR_WIDTH = 320


def strip_html(text: str) -> str:
    """Remove HTML tags from text, including broken/partial tags."""
    # Remove well-formed tags
    text = re.sub(r"<[^>]+>", "", text)
    # Remove orphaned closing/opening tag fragments (e.g. "u>" at start)
    text = re.sub(r"^\w+>", "", text)
    text = re.sub(r"<\w+$", "", text)
    return text


def get_system_font(size: int):
    """Try to load a clean sans-serif font, fall back to default."""
    candidates = [
        # macOS
        ("/System/Library/Fonts/SFNS.ttf", None),
        ("/System/Library/Fonts/Helvetica.ttc", 0),  # index 0 = Regular
        # Linux
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", None),
    ]
    for path, index in candidates:
        if os.path.exists(path):
            try:
                if index is not None:
                    return ImageFont.truetype(path, size, index=index)
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default(size=size)


def get_system_font_bold(size: int):
    """Try to load a bold sans-serif font."""
    candidates = [
        # macOS
        ("/System/Library/Fonts/Helvetica.ttc", 1),  # index 1 = Bold
        ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", None),
        # Linux
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", None),
    ]
    for path, index in candidates:
        if os.path.exists(path):
            try:
                if index is not None:
                    return ImageFont.truetype(path, size, index=index)
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return get_system_font(size)


def fetch_recovery(group_id: int) -> dict:
    """Fetch recovery data from the Unobfuscator database."""
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA query_only = ON")
    row = db.execute(
        "SELECT recovered_segments, merged_text, recovered_count "
        "FROM merge_results WHERE group_id = ?",
        (group_id,),
    ).fetchone()
    db.close()
    if not row:
        raise ValueError(f"Group {group_id} not found")
    segments = json.loads(row[0]) if row[0] else []
    return {
        "segments": segments,
        "merged_text": row[1] or "",
        "recovered_count": row[2],
    }


def extract_quote(full_text: str, keyword: str) -> str:
    """Extract the sentence containing a keyword from a longer text.

    Splits on sentence boundaries and returns the sentence (plus the
    following sentence for context) that contains the keyword.
    """
    clean = strip_html(full_text)
    # Split on sentence-ending punctuation followed by space or newline
    sentences = re.split(r'(?<=[.!?"])\s+', clean)
    for i, sent in enumerate(sentences):
        if keyword.lower() in sent.lower():
            # Clean up leading email artifacts like timestamps, > » markers
            result = re.sub(r'^[\d/]+\s+[\d:]+\s*[>»\s]*', '', sent).strip()
            if result and result[0].islower():
                # If stripping removed too much, use original
                result = sent.strip()
            # Also grab next sentence for context
            if i + 1 < len(sentences):
                next_sent = sentences[i + 1].strip()
                result += " " + next_sent
            return result
    return clean[:300]  # fallback: first 300 chars


def draw_wrapped_text(draw, text, x, y, max_width, font, fill, line_spacing=8):
    """Draw word-wrapped text, return the y position after the last line."""
    # Use "M" width for more conservative line-length estimation
    avg_char_width = font.getlength("M") * 0.6
    chars_per_line = max(1, int(max_width / avg_char_width))
    lines = textwrap.wrap(text, width=chars_per_line)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = font.getbbox(line)
        y += (bbox[3] - bbox[1]) + line_spacing
    return y


def generate_quote_card(recovery: dict):
    """Asset 1: Recovery quote card (1080x1080) for Post 2."""
    w, h = 1080, 1080
    img = Image.new("RGB", (w, h), BG_DARK)
    draw = ImageDraw.Draw(img)
    pad = 80

    # Extract just the "rug burn" sentence from the full email segment
    quote_text = ""
    for seg in recovery["segments"]:
        text = seg.get("text", "") if isinstance(seg, dict) else str(seg)
        if "rug burn" in text.lower() or "ploy" in text.lower():
            quote_text = extract_quote(text, "rug burn")
            break

    if not quote_text:
        raise ValueError("Could not find 'rug burn' quote in group 8022 segments")

    font_quote = get_system_font(36)
    font_attr = get_system_font(22)
    font_url = get_system_font(18)

    # "RECOVERED FROM GOVERNMENT DOCUMENTS" label at top
    font_label = get_system_font(16)
    draw.text(
        (pad, pad - 5),
        "RECOVERED FROM GOVERNMENT DOCUMENTS",
        font=font_label,
        fill=ACCENT_GREEN,
    )

    # Green accent bar on the left
    draw.rectangle([(pad - 20, pad + 25), (pad - 12, h - pad - 40)], fill=ACCENT_GREEN)

    # Quote text
    y = pad + 40
    y = draw_wrapped_text(
        draw, f'"{quote_text}"', pad + 20, y, w - pad * 2 - 20, font_quote, GREEN_TEXT
    )

    # Attribution
    y += 30
    draw.text(
        (pad + 20, y),
        "Internal BOP email, August 1, 2019",
        font=font_attr,
        fill=TEXT_GRAY,
    )
    y += 35
    draw.text(
        (pad + 20, y),
        "10 days before Epstein's death",
        font=font_attr,
        fill=TEXT_GRAY,
    )

    # URL at bottom (offset by 25px to avoid descender clipping)
    draw.text((pad, h - pad - 25), SITE_URL, font=font_url, fill=TEXT_GRAY)

    path = ASSETS_DIR / "quote-card.jpg"
    img.save(path, "JPEG", quality=95)
    print(f"Created {path}")


def generate_before_after(recovery: dict):
    """Asset 2: Before/after comparison (1080x1080) for Post 3.

    Uses a stacked (top/bottom) layout for better readability at phone width.
    Top half: redacted version with uniform black bars.
    Bottom half: same passages with recovered text in green.
    """
    w, h = 1080, 1080
    img = Image.new("RGB", (w, h), BG_DARK)
    draw = ImageDraw.Draw(img)
    pad = 60
    mid_y = h // 2

    font_label = get_system_font_bold(22)
    font_body = get_system_font(26)
    font_redacted = get_system_font(16)
    font_url = get_system_font(18)

    # Extract the key quote, then split it into display-friendly chunks
    quote_text = ""
    for seg in recovery["segments"]:
        raw = seg.get("text", "") if isinstance(seg, dict) else str(seg)
        if "rug burn" in raw.lower() or "ploy" in raw.lower():
            quote_text = extract_quote(raw, "rug burn")
            break

    if not quote_text:
        quote_text = "We don't know if it was a ploy, if someone else did it, or he just gave himself a \"rug burn\" with the sheet to call attention to his situation"

    # Split the quote into 2-3 visual snippets for the before/after display
    # Break at natural pause points
    parts = re.split(r',\s*', quote_text, maxsplit=2)
    snippets = [p.strip() for p in parts if len(p.strip()) > 10]
    if not snippets:
        snippets = [quote_text]

    # Top half label
    draw.text((pad, pad), "RELEASED BY THE GOVERNMENT", font=font_label, fill=TEXT_GRAY)

    # Top half: uniform redaction bars
    y = pad + 50
    for _ in snippets:
        draw.rectangle([(pad, y), (pad + REDACT_BAR_WIDTH, y + 28)], fill=REDACT_BLACK)
        draw.text((pad + 10, y + 4), "[Redacted]", font=font_redacted, fill=(80, 80, 80))
        y += 50

    # Divider line
    draw.line([(pad, mid_y), (w - pad, mid_y)], fill=TEXT_GRAY, width=1)

    # Bottom half label
    draw.text((pad, mid_y + 20), "WHAT THE SOFTWARE RECOVERED", font=font_label, fill=ACCENT_GREEN)

    # Bottom half: recovered text with green highlights
    y = mid_y + 60
    for snippet in snippets:
        y = draw_wrapped_text(
            draw, snippet, pad, y, w - pad * 2, font_body, GREEN_TEXT, line_spacing=6
        )
        y += 20

    # URL at bottom
    draw.text((pad, h - pad - 25), SITE_URL, font=font_url, fill=TEXT_GRAY)

    path = ASSETS_DIR / "before-after.jpg"
    img.save(path, "JPEG", quality=95)
    print(f"Created {path}")


def generate_scale_infographic():
    """Asset 3: Scale numbers graphic (1080x1080) for Post 4."""
    w, h = 1080, 1080
    img = Image.new("RGB", (w, h), BG_DARK)
    draw = ImageDraw.Draw(img)
    pad = 80

    font_big = get_system_font_bold(72)
    font_label = get_system_font(28)
    font_url = get_system_font(18)

    stats = [
        ("1.4M", "government documents scanned"),
        ("15,220", "document match groups found"),
        ("5,600+", "redacted passages recovered"),
    ]

    y = pad + 60
    for number, label in stats:
        draw.text((pad, y), number, font=font_big, fill=ACCENT_GREEN)
        bbox = font_big.getbbox(number)
        y += (bbox[3] - bbox[1]) + 10
        draw.text((pad, y), label, font=font_label, fill=TEXT_GRAY)
        y += 80

    # Tagline
    font_tag = get_system_font(22)
    draw.text(
        (pad, y + 20),
        "Same documents. Different redactions.",
        font=font_tag,
        fill=TEXT_WHITE,
    )
    draw.text(
        (pad, y + 55),
        "Software filled in the gaps.",
        font=font_tag,
        fill=TEXT_WHITE,
    )

    # URL at bottom
    draw.text((pad, h - pad - 25), SITE_URL, font=font_url, fill=TEXT_GRAY)

    path = ASSETS_DIR / "scale-infographic.jpg"
    img.save(path, "JPEG", quality=95)
    print(f"Created {path}")


def generate_og_card():
    """Asset 4: Open Graph social card (1200x630) for link previews."""
    w, h = 1200, 630
    img = Image.new("RGB", (w, h), BG_DARK)
    draw = ImageDraw.Draw(img)
    pad = 60

    font_title = get_system_font_bold(48)
    font_sub = get_system_font(28)
    font_stat = get_system_font_bold(36)

    # Title
    draw.text((pad, pad), "TEREDACTA", font=font_title, fill=TEXT_WHITE)

    # Subtitle
    y = pad + 70
    y = draw_wrapped_text(
        draw,
        "Recovered government redactions from the Congressional Epstein/Maxwell releases",
        pad, y, w - pad * 2, font_sub, TEXT_GRAY,
    )

    # Key stat
    y += 40
    draw.text((pad, y), "5,600+", font=font_stat, fill=ACCENT_GREEN)
    bbox = font_stat.getbbox("5,600+")
    stat_w = bbox[2] - bbox[0]
    draw.text(
        (pad + stat_w + 15, y + 8),
        "redacted passages recovered from 1.4M documents",
        font=font_sub,
        fill=TEXT_GRAY,
    )

    # Green accent line at bottom
    draw.rectangle([(0, h - 6), (w, h)], fill=ACCENT_GREEN)

    # URL
    font_url = get_system_font(20)
    draw.text((pad, h - 45), SITE_URL, font=font_url, fill=TEXT_GRAY)

    path = STATIC_DIR / "og-card.jpg"
    img.save(path, "JPEG", quality=95)
    print(f"Created {path}")


def main():
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching recovery data for group 8022...")
    recovery = fetch_recovery(8022)
    print(f"  {recovery['recovered_count']} segments found")

    print("\nGenerating assets...")
    generate_quote_card(recovery)
    generate_before_after(recovery)
    generate_scale_infographic()
    generate_og_card()
    print("\nDone. Review the generated images and adjust as needed.")


if __name__ == "__main__":
    main()
