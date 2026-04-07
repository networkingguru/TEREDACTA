# Documentation & Threads Content Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare TEREDACTA for public attention — fix the case study, add site onboarding for non-technical visitors, generate visual assets for Threads, update READMEs, and update the Unobfuscator cross-reference.

**Architecture:** Five independent deliverables with two dependency gates. Phase 1 (D3, D4, D5) runs in parallel. Phase 2 (D2) requires D4 complete. Visual assets (D6) can run anytime but need DB access. The Threads post itself (D1) is not implemented here — it's user-written copy using assets and guidance from the spec.

**Tech Stack:** Jinja2 templates, Python/Pillow for image generation, SQLite for recovery data extraction, Markdown for docs.

**Spec:** `docs/superpowers/specs/2026-04-07-docs-and-threads-content-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `docs/demo-recovery-2924.md` | Fix factual errors (D5) |
| Modify | `teredacta/templates/base.html` | OG meta tags, favicon, meta description (D4) |
| Modify | `teredacta/templates/highlights.html` | Intro text, rename heading, pin featured recovery (D4) |
| Modify | `teredacta/templates/explore.html` | Orientation text (D4) |
| Modify | `teredacta/templates/recoveries/detail.html` | OG overrides (D4) |
| Modify | `teredacta/templates/recoveries/tabs/merged_text.html` | Green highlight explanation (D4) |
| Modify | `teredacta/routers/highlights.py` | Pass featured recovery to template (D4) |
| Create | `teredacta/static/img/favicon.png` | Favicon (D4) |
| Create | `teredacta/static/img/og-card.jpg` | Open Graph social card 1200x630 (D6) |
| Create | `assets/threads/quote-card.jpg` | Recovery quote card 1080x1080 (D6) |
| Create | `assets/threads/before-after.jpg` | Redacted vs recovered comparison 1080x1080 (D6) |
| Create | `assets/threads/scale-infographic.jpg` | Scale numbers graphic 1080x1080 (D6) |
| Modify | `pyproject.toml` | Add Pillow optional dependency (D6) |
| Create | `scripts/generate_thread_assets.py` | Image generation script (D6) |
| Modify | `README.md` | Key Findings + Try It sections (D2) |
| Modify | `/Users/brianhill/Scripts/Unobfuscator/README.md` | Demo site link (D3) |

---

## Task 1: Fix demo-recovery-2924.md (Deliverable 5)

**Files:**
- Modify: `docs/demo-recovery-2924.md`

- [ ] **Step 1: Fix the title**

The title says "48 Hours Before Epstein's Death" but the email is dated August 12, 2019 — two days AFTER Epstein died (August 10). The body confirms it's post-mortem ("staff who need to be interviewed by the FBI following Epstein's death").

Change line 1 from:
```markdown
# Demo Recovery: MCC Staffing Memo — 48 Hours Before Epstein's Death
```
to:
```markdown
# Demo Recovery: MCC Staff Interview List — Two Days After Epstein's Death
```

- [ ] **Step 2: Fix the "identities" claim**

Line 5 says "reveals the identities, roles, and shift assignments." The recovery contains role/shift annotations, not names. The document itself says "names still redacted" in the source table.

Change line 5 from:
```
The recovered text reveals the identities, roles, and shift assignments of BOP staff involved in Epstein's custody
```
to:
```
The recovered text reveals the roles, shift assignments, and responsibility annotations of BOP staff involved in Epstein's custody
```

- [ ] **Step 3: Fix "suicide watch" claim**

Line 61: "how a high-profile inmate on suicide watch ended up alone in his cell with no functioning camera coverage." Epstein was taken OFF suicide watch on July 29, 2019, ~12 days before his death. The DOJ stated cameras existed but footage was unusable/corrupted, not that cameras were non-functioning.

Change the "Why This Matters" intro (line 61) from:
```
The central unanswered question in the Epstein case is how a high-profile inmate on suicide watch ended up alone in his cell with no functioning camera coverage. This recovery reveals:
```
to:
```
The central unanswered question in the Epstein case is how a high-profile inmate — removed from suicide watch 12 days earlier — ended up alone in his cell with only unusable camera footage. This recovery reveals:
```

- [ ] **Step 4: Fix "minute-by-minute" claim**

Line 65: "minute-by-minute accountability chain for Epstein's final 24 hours." The data is shift-level (2-10, 8-4, etc.), not minute-level.

Change:
```
3. **Complete shift coverage was mapped.** The annotations reconstruct exactly which staff were on duty across every shift on August 9, 2019, creating a minute-by-minute accountability chain for Epstein's final 24 hours.
```
to:
```
3. **Complete shift coverage was mapped.** The annotations reconstruct exactly which staff were on duty across every shift on August 9, 2019, creating a shift-by-shift accountability chain for Epstein's final 24 hours.
```

- [ ] **Step 5: Add independent verification instructions**

Add a new section after "Technical Details" (after line 79), before the closing italic line:

```markdown
---

## How to Verify This Recovery

Anyone can independently confirm these results using the original government documents:

1. **Download the source documents** from [justice.gov/epstein](https://www.justice.gov/epstein). Search for these Bates numbers across the available data sets:
   - EFTA00066543 (heavily redacted version)
   - EFTA00173655 (less-redacted version)

2. **Compare the two versions manually.** Open both PDFs side by side. The heavily-redacted version has entries 3–12 replaced with `[Redacted]`. The less-redacted version shows role and shift annotations for those same entries.

3. **Verify the anchor context.** Each recovered passage is bounded by 29–40 characters of identical text on both sides — the surrounding context that proves the alignment is correct.

### Limitations

- **Names were NOT recovered.** The less-redacted version shows roles and shift annotations, not actual staff names. All versions redact the names themselves.
- **"High" confidence** means each recovered segment has 29+ characters of verified matching context on both sides. No segment was inferred or interpolated — each is a direct text extraction from a less-redacted copy.
- **The recovery is deterministic.** Running the same 18 documents through the merger produces identical output every time.
```

- [ ] **Step 6: Commit**

```bash
git add docs/demo-recovery-2924.md
git commit -m "docs: fix factual errors in demo recovery case study

- Title: '48 Hours Before' → 'Two Days After' (email is post-mortem)
- 'identities' → 'roles, shift assignments, and responsibility annotations'
- 'on suicide watch' → 'removed from suicide watch 12 days earlier'
- 'no functioning camera coverage' → 'only unusable camera footage'
- 'minute-by-minute' → 'shift-by-shift'
- Add independent verification instructions and limitations section"
```

---

## Task 2: Add Open Graph meta tags, favicon, and meta description (Deliverable 4, part 1)

**Files:**
- Modify: `teredacta/templates/base.html`
- Modify: `teredacta/templates/recoveries/detail.html`

- [ ] **Step 1: Update base.html head section**

Replace the current `<head>` block (lines 3-9) with:

```html
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}TEREDACTA{% endblock %}</title>
    <meta name="description" content="{% block meta_description %}Browse 5,600+ recovered redactions from 1.4 million government documents in the Congressional Epstein/Maxwell releases.{% endblock %}">
    <meta name="csrf-token" content="{{ csrf_token }}">
    <!-- Open Graph -->
    <meta property="og:title" content="{% block og_title %}TEREDACTA — Recovered Government Redactions{% endblock %}">
    <meta property="og:description" content="{% block og_description %}5,600+ redacted passages recovered from 1.4 million Congressional Epstein/Maxwell documents by cross-referencing inconsistent redaction patterns.{% endblock %}">
    <meta property="og:image" content="{% block og_image %}https://teredacta.counting-to-infinity.com/static/img/og-card.jpg{% endblock %}">
    <meta property="og:type" content="website">
    <meta property="og:url" content="https://teredacta.counting-to-infinity.com{{ request.url.path }}">
    <!-- Twitter/X Card (falls back to OG tags for title/description/image) -->
    <meta name="twitter:card" content="summary_large_image">
    <!-- Favicon -->
    <link rel="icon" type="image/png" href="/static/img/favicon.png">
    <link rel="stylesheet" href="/static/css/app.css">
    <script src="/static/js/htmx.min.js"></script>
</head>
```

- [ ] **Step 2: Add OG overrides to recovery detail template**

In `teredacta/templates/recoveries/detail.html`, add these blocks after line 3 (`{% block nav_recoveries %}active{% endblock %}`):

```html
{% block meta_description %}Recovery #{{ group_id }} — {{ recovery.recovered_count }} redacted passages recovered by cross-referencing multiple government releases of the same document.{% endblock %}
{% block og_title %}Recovery #{{ group_id }} — {{ recovery.recovered_count }} Redactions Recovered | TEREDACTA{% endblock %}
{% block og_description %}{{ recovery.recovered_count }} redacted passages recovered from government Epstein/Maxwell documents by cross-referencing inconsistent redaction patterns across multiple releases.{% endblock %}
```

- [ ] **Step 3: Create a favicon**

Generate a simple 32x32 PNG favicon from the existing logo. Run:

```bash
cd /Users/brianhill/Scripts/TEREDACTA
python3 -c "
from PIL import Image
img = Image.open('teredacta/static/img/logo.png')
img.thumbnail((32, 32), Image.LANCZOS)
img.save('teredacta/static/img/favicon.png')
print(f'Created favicon.png ({img.size[0]}x{img.size[1]})')
"
```

If Pillow is not installed, install it first: `pip install Pillow`

- [ ] **Step 4: Verify the changes render correctly**

```bash
cd /Users/brianhill/Scripts/TEREDACTA
source .venv/bin/activate
python -c "
from teredacta.app import create_app
from httpx import ASGITransport, AsyncClient
import asyncio

async def check():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        r = await c.get('/highlights')
        assert 'og:title' in r.text, 'Missing og:title'
        assert 'og:image' in r.text, 'Missing og:image'
        assert 'og:description' in r.text, 'Missing og:description'
        assert 'twitter:card' in r.text, 'Missing twitter:card'
        assert 'favicon.png' in r.text, 'Missing favicon'
        assert 'meta name=\"description\"' in r.text, 'Missing meta description'
        print('All meta tags present on /highlights')

        r = await c.get('/recoveries/2924')
        assert 'Recovery #2924' in r.text or r.status_code == 200
        print('Recovery detail page loads OK')

asyncio.run(check())
"
```

Expected: Both checks pass.

- [ ] **Step 5: Commit**

```bash
git add teredacta/templates/base.html teredacta/templates/recoveries/detail.html teredacta/static/img/favicon.png
git commit -m "feat: add Open Graph meta tags, Twitter cards, favicon, and meta description

Enables rich link previews when sharing TEREDACTA URLs on social media.
Recovery detail pages get per-page OG overrides with recovery-specific titles."
```

---

## Task 3: Add site onboarding text (Deliverable 4, part 2)

**Files:**
- Modify: `teredacta/templates/highlights.html`
- Modify: `teredacta/templates/recoveries/tabs/merged_text.html`
- Modify: `teredacta/templates/explore.html`

- [ ] **Step 1: Add intro text to Highlights page**

In `highlights.html`, after line 5 (`<h1>Highlights</h1>`) add:

```html
<p style="color:var(--text-secondary);margin-bottom:1.5rem;max-width:720px;line-height:1.6;">
    TEREDACTA automatically cross-references 1.4 million government documents from the Congressional Epstein/Maxwell releases.
    When the same document was released multiple times with different redaction patterns, the software recovered the hidden text.
    <span style="color:var(--accent-green);">Green highlighted text</span> on recovery pages marks passages that were redacted by the government but recovered through this process.
</p>
```

- [ ] **Step 2: Rename "Common Unredactions" heading**

In `highlights.html`, change line 53 from:

```html
    <h2 style="font-size:1.1rem;margin-bottom:0.75rem;">Common Unredactions</h2>
```

to:

```html
    <h2 style="font-size:1.1rem;margin-bottom:0.75rem;">Frequently Recovered Text</h2>
```

Also update the empty-state message on line 64 from:

```html
    <p style="color:var(--text-secondary);">No common unredactions found yet.</p>
```

to:

```html
    <p style="color:var(--text-secondary);">No frequently recovered text found yet.</p>
```

- [ ] **Step 3: Add green highlight explanation to recovery detail merged text**

In `teredacta/templates/recoveries/tabs/merged_text.html`, after line 1 (`<h3>Merged Text</h3>`) and before line 2 (`{% if recovery.merged_text_html %}`), add:

```html
<p style="color:var(--text-secondary);font-size:0.85rem;margin-bottom:0.75rem;max-width:720px;">
    <span style="color:var(--accent-green);">Green highlighted text</span> was redacted by the government but recovered by cross-referencing multiple releases of this document.
</p>
```

- [ ] **Step 4: Add orientation text to Explore page**

In `explore.html`, after line 13 (`{% if entity_index_ready %}`) and before line 14 (`<div class="explore-container">`), add:

```html
<p style="color:var(--text-secondary);font-size:0.85rem;margin:0 0 1rem 0;max-width:720px;">
    Browse people, organizations, and locations found in recovered redactions. Select an entity on the left to see its connections across documents.
</p>
```

- [ ] **Step 5: Verify the changes render correctly**

```bash
cd /Users/brianhill/Scripts/TEREDACTA
source .venv/bin/activate
python -c "
from teredacta.app import create_app
from httpx import ASGITransport, AsyncClient
import asyncio

async def check():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        r = await c.get('/highlights')
        assert 'cross-references 1.4 million' in r.text, 'Missing highlights intro'
        assert 'Frequently Recovered Text' in r.text, 'Heading not renamed'
        assert 'Common Unredactions' not in r.text, 'Old heading still present'
        print('Highlights page: intro text present, heading renamed')

        r = await c.get('/')
        assert 'Browse people, organizations' in r.text or 'Entity index has not been built' in r.text
        print('Explore page: orientation text present (or index not built)')

asyncio.run(check())
"
```

Expected: All assertions pass.

- [ ] **Step 6: Commit**

```bash
git add teredacta/templates/highlights.html teredacta/templates/recoveries/tabs/merged_text.html teredacta/templates/explore.html
git commit -m "feat: add onboarding text for non-technical visitors

- Highlights page: intro paragraph explaining what TEREDACTA does
- Recovery detail: green highlight explanation banner
- Explore page: orientation text for entity graph
- Rename 'Common Unredactions' to 'Frequently Recovered Text'"
```

---

## Task 4: Pin featured recovery on Highlights page (Deliverable 4, part 3)

**Files:**
- Modify: `teredacta/routers/highlights.py`
- Modify: `teredacta/templates/highlights.html`

- [ ] **Step 1: Pass featured recovery data to template**

In `teredacta/routers/highlights.py`, modify the route function to fetch the featured recovery (group 8022, the "rug burn" email) separately and pass it to the template. After line 42 (`pass`) and before line 44 (`# Top entities`), add:

```python
    # Featured recovery (pinned at top of highlights)
    featured = None
    try:
        featured_detail = unob.get_recovery_detail(8022)
        if featured_detail:
            featured = {
                "group_id": 8022,
                "recovered_count": featured_detail["recovered_count"],
                "headline": _get_headline(featured_detail.get("recovered_segments", [])),
            }
    except Exception:
        pass
```

Then add `"featured": featured,` to the template context dict (after line 63, inside the dict on line 58-63):

```python
    return templates.TemplateResponse(request, "highlights.html", {
        "is_admin": getattr(request.state, "is_admin", False),
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "top_recoveries": top_recoveries,
        "top_entities": top_entities,
        "common": common,
        "featured": featured,
    })
```

- [ ] **Step 2: Add featured recovery card to highlights template**

In `highlights.html`, after the intro paragraph (added in Task 3, Step 1) and before the "Top Recoveries" section (line 7), add:

```html
{% if featured %}
<section style="margin-bottom:2rem;">
    <h2 style="font-size:1.1rem;margin-bottom:0.75rem;">Featured Recovery</h2>
    <a href="/recoveries/{{ featured.group_id }}" style="text-decoration:none;color:inherit;">
        <div class="stat-card" style="text-align:left;cursor:pointer;border-left:3px solid var(--accent-green);">
            <p style="font-size:0.85rem;margin-bottom:0.5rem;color:var(--text-primary);">{{ featured.headline or "Recovery #" ~ featured.group_id }}</p>
            <span class="entity-type-badge" style="background:rgba(102,187,106,0.2);color:#66bb6a;">{{ featured.recovered_count }} passage{{ 's' if featured.recovered_count != 1 else '' }} recovered</span>
        </div>
    </a>
</section>
{% endif %}
```

- [ ] **Step 3: Verify featured recovery appears**

```bash
cd /Users/brianhill/Scripts/TEREDACTA
source .venv/bin/activate
python -c "
from teredacta.app import create_app
from httpx import ASGITransport, AsyncClient
import asyncio

async def check():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        r = await c.get('/highlights')
        assert 'Featured Recovery' in r.text, 'Featured section missing'
        assert '/recoveries/8022' in r.text, 'Featured recovery link missing'
        print('Featured recovery pinned on highlights page')

asyncio.run(check())
"
```

Expected: Featured recovery card visible linking to /recoveries/8022.

- [ ] **Step 4: Commit**

```bash
git add teredacta/routers/highlights.py teredacta/templates/highlights.html
git commit -m "feat: pin featured recovery (group 8022) on highlights page

The 'rug burn' MCC psychologist email is pinned at the top of Highlights
with a green accent border, so Threads visitors see it immediately."
```

---

## Task 5: Add UTM parameter support (Deliverable 4, part 4)

This is documentation-only — UTM parameters are appended to URLs in the README and Threads post, not parsed by the server. No code changes needed. The server access logs already capture the full URL including query strings.

- [ ] **Step 1: Verify access logs capture query strings**

```bash
# Check a sample log line from the running server (if available)
# UTM params like ?utm_source=threads will appear in the request path in access logs
# No server-side code changes needed — Uvicorn logs the full URL by default
echo "UTM parameters are URL-appended and captured in server access logs. No implementation needed."
```

- [ ] **Step 2: Document the UTM convention**

This is handled in Task 8 (README update) where URLs include `?utm_source=github&utm_medium=readme` and in the spec which specifies `?utm_source=threads&utm_medium=social` for the Threads post.

No commit needed for this task.

---

## Task 6: Verify mobile rendering (Deliverable 4, part 5)

- [ ] **Step 1: Check CSS for responsive breakpoints**

```bash
cd /Users/brianhill/Scripts/TEREDACTA
grep -n '@media' teredacta/static/css/app.css
```

Review the output to check if highlights and recovery detail pages have mobile breakpoints. The key pages are:
- `/highlights` — stat-card grid should stack on narrow screens
- `/recoveries/N` — tabs and merged text should be readable on 375px width

- [ ] **Step 2: Test at mobile width using a browser**

Open the demo site in a browser, use DevTools responsive mode at 375px width (iPhone SE), and check:
- Highlights page: cards stack vertically, intro text is readable
- Recovery detail: tabs are tappable, merged text scrolls, green highlights visible
- Explore page: three-column layout likely needs work (document in spec as known limitation)

This is a manual verification step. If issues are found, file them as GitHub issues for follow-up.

- [ ] **Step 3: Commit any mobile fixes if needed**

Only if CSS changes are required. Otherwise skip.

---

## Task 7: Generate visual assets (Deliverable 6)

**Files:**
- Create: `scripts/generate_thread_assets.py`
- Create: `assets/threads/quote-card.jpg`
- Create: `assets/threads/before-after.jpg`
- Create: `assets/threads/scale-infographic.jpg`
- Create: `teredacta/static/img/og-card.jpg`

- [ ] **Step 1: Add Pillow as optional dependency and install**

In `pyproject.toml`, add an `assets` optional dependency group after the `stress` group (after line 32):

```toml
assets = [
    "Pillow>=10.0.0",
]
```

Then install:

```bash
cd /Users/brianhill/Scripts/TEREDACTA
source .venv/bin/activate
pip install -e ".[assets]"
```

- [ ] **Step 2: Extract recovery data from database**

Query the Unobfuscator database for group 8022's recovered text to use in the visual assets:

```bash
cd /Users/brianhill/Scripts/TEREDACTA
source .venv/bin/activate
python3 -c "
import sqlite3, json
db = sqlite3.connect('/Users/brianhill/Scripts/Unobfuscator/data/unobfuscator.db')
db.execute('PRAGMA query_only = ON')
row = db.execute('SELECT recovered_segments, merged_text, recovered_count FROM merge_results WHERE group_id = 8022').fetchone()
if row:
    segs = json.loads(row[0]) if row[0] else []
    print(f'Group 8022: {row[2]} recoveries')
    print(f'Segments: {len(segs)}')
    for i, seg in enumerate(segs):
        text = seg.get(\"text\", \"\") if isinstance(seg, dict) else str(seg)
        if text.strip():
            print(f'  [{i}] {text[:200]}')
    print()
    print('--- MERGED TEXT (first 2000 chars) ---')
    print((row[1] or '')[:2000])
db.close()
"
```

Save the output — you'll need the exact recovered text for the image assets.

- [ ] **Step 3: Create the asset generation script**

Create `scripts/generate_thread_assets.py`:

```python
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
DB_PATH = "/Users/brianhill/Scripts/Unobfuscator/data/unobfuscator.db"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
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
    """Remove HTML tags from text."""
    return re.sub(r"<[^>]+>", "", text)


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
            # Return this sentence + next one for context
            result = sent.strip()
            if i + 1 < len(sentences):
                result += " " + sentences[i + 1].strip()
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

    # Extract meaningful text snippets (strip HTML, split into sentences)
    snippets = []
    for seg in recovery["segments"]:
        raw = seg.get("text", "") if isinstance(seg, dict) else str(seg)
        clean = strip_html(raw).strip()
        if len(clean) < 20:
            continue
        # Split into sentences and take interesting ones
        sentences = re.split(r'(?<=[.!?"])\s+', clean)
        for sent in sentences:
            sent = sent.strip()
            if len(sent) > 30 and not sent.startswith(("From:", "Date:", "Subject:", "To:")):
                snippets.append(sent[:120])
            if len(snippets) >= 3:
                break
        if len(snippets) >= 3:
            break

    if not snippets:
        snippets = ["[No displayable text found]"]

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
```

- [ ] **Step 4: Create output directories and run the script**

```bash
cd /Users/brianhill/Scripts/TEREDACTA
source .venv/bin/activate
mkdir -p assets/threads
python scripts/generate_thread_assets.py
```

Expected output:
```
Fetching recovery data for group 8022...
  1 segments found
Generating assets...
Created assets/threads/quote-card.jpg
Created assets/threads/before-after.jpg
Created assets/threads/scale-infographic.jpg
Created teredacta/static/img/og-card.jpg
Done. Review the generated images and adjust as needed.
```

- [ ] **Step 5: Review the generated images**

Open each image and verify:
- `assets/threads/quote-card.jpg` — Quote text is readable, attribution visible, URL at bottom
- `assets/threads/before-after.jpg` — Left side shows black redaction bars, right side shows green-highlighted recovered text
- `assets/threads/scale-infographic.jpg` — Numbers are large and legible, clean layout
- `teredacta/static/img/og-card.jpg` — 1200x630, title + stat visible, looks good as a link preview

If any image needs adjustment, edit the script and re-run. Font sizes, padding, and colors are all configurable at the top of each function.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml scripts/generate_thread_assets.py assets/threads/ teredacta/static/img/og-card.jpg
git commit -m "feat: add Threads visual assets and OG social card

Generated via scripts/generate_thread_assets.py from live DB data:
- Quote card (1080x1080): group 8022 'rug burn' recovery
- Before/after comparison (1080x1080): redacted vs recovered
- Scale infographic (1080x1080): 1.4M docs, 5,600+ recoveries
- OG social card (1200x630): site-wide link preview image"
```

---

## Task 8: Update TEREDACTA README (Deliverable 2)

**Blocking dependency:** Tasks 2-4 (Deliverable 4) must be complete — README links to demo site pages that need onboarding text.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Key Findings and Try It sections**

In `README.md`, after line 9 (`---`) and before line 11 (`## What It Does`), insert:

```markdown

## Key Findings

TEREDACTA has recovered thousands of redacted passages from the Congressional Epstein/Maxwell document releases. Among them:

- **MCC psychologist email (10 days before Epstein's death):** Internal BOP debate over whether Epstein's first incident was *"a ploy, if someone else did it, or he just gave himself a 'rug burn' with the sheet."* ([Recovery #8022](https://teredacta.counting-to-infinity.com/recoveries/8022?utm_source=github&utm_medium=readme))
- **MCC staff interview list (2 days after Epstein's death):** OIG email mapping staff roles across every shift at MCC on August 9 — which positions covered each shift, which role authored the cellmate memo, which role was notified, and the person flagged as *"potentially in charge of no reassignment."* ([Recovery #2924](https://teredacta.counting-to-infinity.com/recoveries/2924?utm_source=github&utm_medium=readme))
- **FBI evidence log (113 recovered passages):** Extensive case records from the child sex trafficking investigation, including evidence items and seizure inventory from Epstein's safe at 9 East 71st Street. ([Recovery #8848](https://teredacta.counting-to-infinity.com/recoveries/8848?utm_source=github&utm_medium=readme))
- **Maxwell's Vanity Fair damage control:** Ghislaine Maxwell drafting PR responses to a journalist, in her own words: *"I MET HER WHEN SHE WAS 17 AND LIVING WITH HER FIANCE AND AVOID ALL THE OTHER STUFF."* ([Recovery #14414](https://teredacta.counting-to-infinity.com/recoveries/14414?utm_source=github&utm_medium=readme))
- **Missing teenager in flight logs:** SDNY prosecutors discussing a missing Florida teenager in connection with Epstein's flight records. ([Recovery #7726](https://teredacta.counting-to-infinity.com/recoveries/7726?utm_source=github&utm_medium=readme))

### Try It

**[Browse all 5,600+ recovered redactions](https://teredacta.counting-to-infinity.com/highlights?utm_source=github&utm_medium=readme)** from the Congressional Epstein/Maxwell releases.

---

```

- [ ] **Step 2: Update the recovery count in the existing description**

On line 15 (now shifted down), change:

```markdown
**Currently deployed against 1.4 million documents from the Congressional Epstein/Maxwell releases** (DOJ volumes, House Oversight releases), with 6,400+ recovered redactions across 15,220 document match groups.
```

to:

```markdown
**Currently deployed against 1.4 million documents from the Congressional Epstein/Maxwell releases** (DOJ volumes, House Oversight releases), with 5,600+ substantive recovered redactions across 15,220 document match groups.
```

- [ ] **Step 3: Verify README renders correctly**

Open the README in a Markdown previewer or check on GitHub after pushing. Verify:
- Key Findings section appears above "What It Does"
- All recovery links are formatted correctly
- "Try It" link points to /highlights with UTM params

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add Key Findings and Try It sections to README

Five highlighted recoveries with direct links to the demo site.
Prominent 'Try It' link to the highlights page for non-technical visitors."
```

---

## Task 9: Update Unobfuscator README (Deliverable 3)

**Files:**
- Modify: `/Users/brianhill/Scripts/Unobfuscator/README.md`

- [ ] **Step 1: Add demo site link to TEREDACTA section**

In `/Users/brianhill/Scripts/Unobfuscator/README.md`, the TEREDACTA section is at lines 208-212:

```markdown
## TEREDACTA

[TEREDACTA](https://github.com/networkingguru/TEREDACTA) is a companion web UI
for browsing and searching Unobfuscator results. It provides a document viewer,
entity browser, and recovery timeline.
```

Add one line after line 212:

```markdown

Browse recoveries from the Epstein archive at [teredacta.counting-to-infinity.com](https://teredacta.counting-to-infinity.com/highlights?utm_source=github&utm_medium=readme).
```

- [ ] **Step 2: Commit**

```bash
cd /Users/brianhill/Scripts/Unobfuscator
git add README.md
git commit -m "docs: add demo site link to TEREDACTA section"
```

Then return to TEREDACTA directory:

```bash
cd /Users/brianhill/Scripts/TEREDACTA
```

---

## Task Summary

| Task | Deliverable | Dependencies | Estimated Steps |
|------|-------------|--------------|-----------------|
| 1 | D5: Fix case study | None | 6 |
| 2 | D4: OG tags + favicon | None | 5 |
| 3 | D4: Onboarding text | None | 6 |
| 4 | D4: Pin featured recovery | Task 3 | 4 |
| 5 | D4: UTM support | None | 2 (docs only) |
| 6 | D4: Mobile verification | Tasks 2-4 | 3 |
| 7 | D6: Visual assets | None (needs Pillow) | 6 |
| 8 | D2: README update | Tasks 2-4 | 4 |
| 9 | D3: Unobfuscator README | None | 2 |

**Parallel execution:** Tasks 1, 2, 3, 7, 9 can all run in parallel. Task 4 depends on 3. Task 6 depends on 2-4. Task 8 depends on 2-4.
