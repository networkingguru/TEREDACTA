# Documentation & Threads Content Strategy

**Date:** 2026-04-07
**Status:** Draft

---

## Goal

Improve documentation for TEREDACTA and Unobfuscator to serve non-technical visitors, and define the structure for a Threads post designed to go viral and funnel people to the demo site (teredacta.counting-to-infinity.com).

## Audience

1. **Primary:** Investigative journalists and FOIA researchers
2. **Secondary (equal):** Tech-savvy general public interested in government transparency; developers/open-source community

## Verified Claims

Web research (April 2026) confirmed:

- The cross-document redaction recovery technique is novel as automated software. Existing tools (unredact, x-ray, Edact-Ray) work on single documents only.
- The specific findings from match group 2924 (MCC staffing memo, August 12, 2019) do not appear in any public reporting. The Bates numbers EFTA00066543 and EFTA00173655 are not referenced in any public analysis.
- The recovered role/shift annotations (entries 3-12) have not been publicly identified. Only Tova Noel and Michael Thomas are named in public reporting from that staff list. Ghitto Bonhomme and Michael Kearins were identified in separate March 2026 reporting.
- The phrase "potentially in charge of no reassignment" returns zero public results.
- TEREDACTA has zero existing web presence.

**Caveat:** The existence of the cellmate memo is publicly known from OIG Report 23-085. What's novel is recovering who wrote it and who was notified.

---

## Deliverable 1: Threads Post (Thread Format)

Single post with 5-6 self-replies. User will write all copy (no AI prose). The structure below defines what kind of content goes in each position and why.

### Post 1: The Hook

**Purpose:** Stop the scroll. Only post most people will see.

**Content type:** The single most shocking specific finding. Lead with the person "potentially in charge of no reassignment" — the person the OIG identified as responsible for Epstein not having a cellmate. State plainly that this has never been publicly reported.

**What NOT to include:** No links (suppresses reach on Threads). No tool explanation. No project name. No context about how it was found.

**Tone:** Journalist breaking a story. Short sentences. No jargon.

### Post 2: The Context

**Purpose:** Explain significance for people who don't follow the case closely.

**Content type:**
- Quick Epstein custody context (high-profile inmate, alone, no cameras)
- The government redacted staff identities but released the same document 18 times with inconsistent redactions
- Reveal 2-3 more recovered entries: the cellmate memo author, the person notified, the overnight shift supervisor
- Frame as an accountability chain

### Post 3: The Evidence

**Purpose:** Visual proof. Show, don't tell.

**Content type:** Screenshot from the demo site showing green-highlighted recovered text next to the blacked-out original. Brief caption explaining what the reader is looking at.

**Requirements:** Screenshot must be legible at phone resolution on Threads. Good contrast, readable font size.

### Post 4: The Scale

**Purpose:** Expand from "one cool find" to "systematic problem."

**Content type:**
- Numbers: 1.4 million documents, 6,400+ recoveries, 15,220 match groups
- The MCC staffing memo is one example among thousands
- Frame as systematic government redaction failure, not a one-off

### Post 5: The How + CTA

**Purpose:** Explain the tool, link to demo site.

**Content type:**
- Brief non-technical explanation: software that automatically compares every version of every document and fills in gaps where redactions are inconsistent
- No other tool does this — existing tools work on single documents
- Name the tool (TEREDACTA)
- Link to teredacta.counting-to-infinity.com
- Frame as: the entire database of recoveries is publicly browsable right now

### Post 6 (optional): The Open Question

**Purpose:** Drive engagement through replies.

**Content type:** A genuine open question the findings raise. Examples: What else is hidden? Why were redactions inconsistent — incompetence or intent? What should journalists look at next?

### Thread-Level Guidance

- Screenshots are critical — green-highlighted recovered text vs. blacked-out original is the money shot
- Don't explain tech before post 5
- Don't link before post 5
- Tag journalists/researchers in a reply to the thread, not in the thread itself
- Hashtags: sparingly. #Epstein #EFTA #FOIA at most
- Opportunistically reply to existing Epstein/FOIA/transparency threads with the most compelling finding + link (user will handle this organically)

---

## Deliverable 2: TEREDACTA README Update

Add a new section **above** "What It Does", serving as a project landing page for non-technical visitors.

### New Section: Key Findings

- 3-5 bullet points of the most significant recoveries in plain language
- Written to provoke curiosity, not to be exhaustive
- Each bullet links to the specific recovery page on the demo site

### New Section: Try It

- Prominent link to teredacta.counting-to-infinity.com
- One sentence: "Browse all 6,400+ recovered redactions from the Congressional Epstein/Maxwell releases."

### New Section: How It Works (plain English)

- 2-3 sentences explaining the core insight: same documents released multiple times, different redaction patterns, software cross-references and fills gaps
- No mention of SQLite, FastAPI, HTMX, or any implementation detail
- Link to Unobfuscator repo for the technically curious

### Existing Content

All existing README content (What It Does, Tech Stack, Installation, Config, Architecture, Health, Stress Testing, Troubleshooting) remains unchanged. The new sections go above it.

---

## Deliverable 3: Unobfuscator README Update

### New Section: Plain English Summary (top of file)

- One paragraph, no jargon: "When the government releases the same document multiple times with different redactions, this software notices and fills in the gaps."
- Link to TEREDACTA and the demo site: "See the results at teredacta.counting-to-infinity.com"

### New Section: Key Results

- Same bullet points as TEREDACTA README, or link to the TEREDACTA highlights page
- Establishes that this tool has produced real, novel findings

### Existing Content

All existing Unobfuscator documentation remains unchanged.

---

## Deliverable 4: Demo Site Onboarding (if needed)

Assess whether the demo site needs any first-visitor context. If the highlights or landing page has no explanation of what recovered redactions are, add a brief intro banner or paragraph. This should be minimal — one or two sentences max — not a tutorial.

---

## Out of Scope

- Rewriting existing technical documentation
- Changing the demo site's UI or features
- Creating a separate landing page or marketing site
- Writing the actual Threads copy (user will write all prose)
