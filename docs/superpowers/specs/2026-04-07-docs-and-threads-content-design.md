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

- The cross-document redaction recovery technique is novel as automated software. Existing tools (unredact, x-ray, Edact-Ray) work on single documents only. Humans have done manual version comparison for decades — what's novel is automating it at scale across 1.4M documents.
- The specific findings from match group 2924 (MCC staffing memo, August 12, 2019) do not appear in any public reporting. The Bates numbers EFTA00066543 and EFTA00173655 are not referenced in any public analysis.
- The recovered content in group 2924 is **role/shift annotations and responsibility descriptions**, NOT names. The less-redacted version has "staff roles and shift annotations visible, names still redacted." Do not claim "identities" were recovered — that word implies names.
- The phrase "potentially in charge of no reassignment" returns zero public results.
- TEREDACTA has zero existing web presence.
- **88% of the 6,400+ recoveries are substantive** (5,662 segments). Only 12% (738) are trivial (page numbers, headers, formatting). The numbers hold up to scrutiny.

**Caveat:** The existence of the cellmate memo is publicly known from OIG Report 23-085. What's novel is recovering the role annotations describing who wrote it and who was notified.

### Precision Requirements

All content (Threads posts, README, demo site) must follow these rules:

1. Say "roles, shift assignments, and responsibility annotations" — never "identities" or "names" unless actual names were recovered in a given group.
2. Say "no other tool automates this at scale" — not "no one has done this" (manual version comparison is standard journalism practice).
3. Epstein was taken OFF suicide watch on July 29, 2019, ~12 days before his death. Never say "on suicide watch" — the scandal is that he was *removed* from it.
4. Camera footage was described as unusable/corrupted, not "no functioning cameras." Use precise language.
5. Shift-level data (2-10, 8-4, etc.) is "shift-by-shift" coverage, not "minute-by-minute."
6. The word "potentially" in "potentially in charge of no reassignment" is the OIG's hedging — do not upgrade it to a definitive finding.

---

## Candidate Recoveries for Featuring

Database analysis identified these as the most provocative recoveries. User should select which to feature in the Threads post and README.

### Tier 1: Most Explosive

| Group | Content | Why It's Strong |
|-------|---------|-----------------|
| **8022** | MCC Chief Psychologist email (8/1/2019, 10 days before death): *"We don't know if it was a ploy, if someone else did it, or he just gave himself a 'rug burn' with the sheet."* Another asks: *"Is it safe to say that he did attempt suicide?"* | Internal BOP debate about the first incident. Visceral, quotable, directly relevant to central mystery. |
| **14414** | Maxwell (gmax1@ellmax.com) drafting Vanity Fair responses in ALL CAPS: *"I MET HER WHEN SHE WAS 17 AND LIVING WITH HER FIANCE AND AVOID ALL THE OTHER STUFF."* PR advisor warns journalist "has form for story-twisting re Hillary Clinton." | Maxwell in her own words doing damage control. Instantly understandable. |
| **7726** | SDNY prosecutors: *"there is a missing person named [redacted] a teenager from Florida, who was last seen sometime around about August 1, 1997. In the flight logs, there is a..."* | Missing teenager linked to Epstein's flight records. Deeply disturbing. |
| **8848** | FBI evidence log (113 recoveries): `"girl plcs nude book 4"`, `"BID TO BURN EPSTEIN PLEA"`, seizure from safe at 9 East 71st St, UK travel records requests. | Sheer scale demonstrates the tool's power. |
| **2924** | MCC staffing memo — OIG interview list with shift annotations, including person "potentially in charge of no reassignment." | Accountability chain for Epstein's custody. Strong but requires more context to understand. |

### Tier 2: Very Compelling

| Group | Content | Why It's Strong |
|-------|---------|-----------------|
| **13493/13720** | SDNY internal: *"summary update regarding the investigation of co-conspirators"* and *"remind the Brass in a sentence or less who she is"* with reverse proffer meetings scheduled. | Shows active co-conspirator prosecution. |
| **15655** | US Marshal tip: *"a female named 'Anna' knows all JE's secrets. JE also gave his pilots apartments on STT near the airport."* | Little St. James intelligence. |
| **13487** | *"Sworn taped statements were taken from five victims and seventeen witnesses concerning massages and unlawful sexual activity"* at 358 El Brillo Way. | Palm Beach investigation scope. |
| **10124** | FBI 302: victim *"at age 14, was introduced to Jeffrey Epstein by a 17 year old girl"* — the $300 massage recruitment pipeline. | Victim testimony. |

### Selected Recoveries for Threads Post

The thread will feature **two** recoveries:

1. **Group 8022** (Post 2) — The "rug burn" quote is the lead finding. Immediately visceral, no context needed, directly relevant to the central mystery. Quotable in under 500 characters.
2. **Group 2924** (Post 4) — The MCC staffing accountability chain. Used in the "scale" post to show this isn't just one email — the tool reconstructed the entire duty roster and identified who was responsible for what. Reinforces the systematic nature of the recoveries.

The remaining Tier 1 candidates (14414, 7726, 8848) are strong choices for the README Key Findings section and for follow-up posts if the thread gains traction.

---

## Implementation Order

Deliverables have dependencies. Execute in this order:

```
D5 (fix case study) ──blocks──> D1 (Threads post)
D4 (site onboarding) ──blocks──> D2 (README with site links)
D3 (Unobfuscator README) ──no dependencies──
```

**Phase 1 (parallel):** D3, D4, D5
**Phase 2 (parallel, after Phase 1):** D2
**Phase 3 (after all above):** D1 (Threads post)

---

## Deliverable 1: Threads Post (Thread Format)

Single post with 5-6 self-replies. User will write all copy (no AI prose). The structure below defines what kind of content goes in each position and why.

**Blocking dependency:** Deliverables 4 and 5 must be complete before posting.

### Post 1: The Hook

**Purpose:** Stop the scroll. Only post most people will see.

**Content type:** Lead with the mechanism — the government released the same document 18 times with different things blacked out, and software recovered what was hidden.

**What NOT to include:** No links (suppresses reach on Threads). No tool explanation. No project name.

**Tone:** Journalist breaking a story. Short sentences. No jargon.

**Copy suggestions (user writes final version):**
- Open with the core absurdity: the government released the same email 18 times with different things blacked out. That's the hook — it's immediately understandable and enraging.
- Don't explain HOW the software works. Just state the result: "I built software that noticed, aligned all 18 versions, and recovered everything they were hiding."
- End with a teaser for post 2: what was recovered. Something like "Here's what they were hiding." or "What it found:"
- Keep it under 400 characters to leave room for whitespace/formatting.

### Post 2: The Payoff (Group 8022)

**Purpose:** Deliver the most visceral finding.

**Content type:** The "rug burn" quote from the MCC Chief Psychologist (8/1/2019, 10 days before Epstein's death).

**Copy suggestions:**
- Quote the recovered text directly — it speaks for itself: *"We don't know if it was a ploy, if someone else did it, or he just gave himself a 'rug burn' with the sheet to call attention to his situation."*
- Brief context: this is an internal BOP email from 10 days before Epstein died, where the prison's own psychologists are debating whether his first incident was real.
- The follow-up question from another staffer — *"Is it safe to say that he did attempt suicide?"* — is the kicker. They didn't know. They were guessing.
- Don't editorialize. The quote does the work. Just frame it: who said it, when, and what it means.
- Stay under 500 characters.

**Attachment:** Image asset — see Visual Assets section below.

### Post 3: The Evidence

**Purpose:** Visual proof. Show, don't tell.

**Content type:** Before/after image showing redacted vs. recovered text from group 8022. Brief caption.

**Copy suggestions:**
- Caption should be minimal — one sentence explaining what the image shows: "Left: what the government released. Right: what we recovered."
- If the image is self-explanatory (labeled before/after), the caption can be even shorter.

**Attachment:** Image asset — see Visual Assets section below.

### Post 4: The Scale + Group 2924

**Purpose:** Expand from "one find" to "systematic," using the MCC staffing accountability chain as the second example.

**Content type:**
- Transition: the rug-burn email is one of 5,600+ substantive recoveries across 3,000+ document groups from 1.4 million documents
- Introduce group 2924 as the second example: an OIG interview list that maps every shift at MCC on August 9 — who was on duty, who wrote the cellmate memo, who was notified, and who was "potentially in charge of no reassignment"
- Frame the combination: internal debate about whether the first incident was real + a complete map of who was supposed to be watching = a picture the government was actively hiding

**Copy suggestions:**
- Lead with the number: "That email is one of over 5,600 passages recovered from 1.4 million government documents."
- Then the 2924 finding: "Another recovery maps every staff member on duty at MCC the night Epstein died — including the person the OIG flagged as responsible for the decision to leave him without a cellmate."
- The word "flagged" is important — it's accurate to the OIG's hedging without overstating.
- Stay under 500 characters. This is tight — may need to split across two sentences.

### Post 5: The How + CTA

**Purpose:** Explain the tool, link to demo site.

**Content type:**
- Brief non-technical explanation of the technique
- Name the tool (TEREDACTA)
- Link to teredacta.counting-to-infinity.com/highlights

**Copy suggestions:**
- One sentence on how: "I built software that compares every version of every document the government released under the Epstein Files Transparency Act. When the same passage is redacted in one version but visible in another, it fills in the blank."
- One sentence on novelty: "Every other redaction tool works on single documents. This one cross-references 1.4 million."
- CTA: "The entire database is public. Browse it yourself:" + link
- Don't oversell. The findings already did the selling.

### Post 6: The Call to Action

**Purpose:** Convert attention into relationships and engagement.

**Copy suggestions:**
- Direct and specific: "If you're a journalist working the EFTA documents, DM me — I can run targeted searches against the full corpus."
- Secondary: "If you're a developer, the code is open source." + GitHub link
- Don't ask open-ended questions ("what do you think?"). They attract low-quality speculation and signal uncertainty.

### Visual Assets (Generated)

The following image assets will be generated as part of implementation. All assets must be phone-legible at 320px width (Threads feed resolution).

**Asset 1: Recovery Quote Card (Post 2 attachment)**
- Clean, high-contrast card showing the recovered "rug burn" quote from group 8022
- White or dark background, large readable font (minimum 16pt equivalent at display size)
- Attribution line: "Internal BOP email, August 1, 2019 — 10 days before Epstein's death"
- Format: 1080x1080px (square, optimal for Threads) or 1080x1350px (portrait)
- Subtle branding: demo site URL in small text at bottom
- Output: JPG/PNG

**Asset 2: Before/After Comparison (Post 3 attachment)**
- Side-by-side or stacked layout showing redacted text vs. recovered text from group 8022
- Left/top: the redacted version (black bars or [Redacted] text)
- Right/bottom: the same passage with recovered text highlighted in green
- Clear labels: "RELEASED BY THE GOVERNMENT" / "WHAT THE SOFTWARE RECOVERED"
- Tightly cropped — 3-4 lines of text maximum
- Demo site URL visible as watermark or footer text
- Format: 1080x1080px or 1080x1350px
- Output: JPG/PNG

**Asset 3: Scale Infographic (Post 4 attachment, optional)**
- Simple visual showing the key numbers: 1.4M documents → 15,220 match groups → 5,600+ substantive recoveries
- Clean, minimal design — not a busy infographic
- Format: 1080x1080px
- Output: JPG/PNG

**Asset 4: Open Graph Social Card (Deliverable 4)**
- Purpose-built card for link previews when sharing the demo site
- 1200x630px (standard OG image dimensions)
- Should include: TEREDACTA name/logo, one-line description, key stat (e.g., "5,600+ recovered redactions from 1.4M government documents")
- Used as default `og:image` across the site
- Output: JPG/PNG

**Asset generation approach:** Generate using Python (Pillow/PIL or reportlab for PDF, then convert) or HTML-to-image rendering. Source data comes from the Unobfuscator database. The actual redacted vs. recovered text for group 8022 must be extracted from the database to create authentic before/after comparisons.

### Thread-Level Guidance

- Screenshots are critical — green-highlighted recovered text is the money shot
- Don't explain tech before post 5
- Don't link before post 5 (but embed URL visibly in post 3 screenshot)
- Tag journalists/researchers in a reply to the thread, not in the thread itself
- **Hashtags:** Drop #EFTA (nobody searches it). Use #Epstein cautiously (conspiracy magnet). Add #transparency #investigativejournalism #FOIA. Place hashtags in post 4 or later, not in post 1.
- **Profile bio:** Put teredacta.counting-to-infinity.com in your Threads bio before posting.
- **Cross-posting:** Adapt the same thread for X and Bluesky. For Hacker News, use "Show HN:" format, lead with the open-source tool and technique (not findings), link to live demo, and write a substantive first comment. HN is hostile to self-promotion — frame as the general technique applicable to any FOIA corpus, with Epstein as the example dataset.
- **Timing:** Post Tuesday-Thursday, 9-11am ET. Space self-replies 3-5 minutes apart.
- **If the thread doesn't gain traction within 24 hours:** Don't delete it. Try posting Post 1 as a standalone (non-thread) post — single posts sometimes outperform threads on Threads. Try a different hook angle.

---

## Deliverable 2: TEREDACTA README Update

**Blocking dependency:** Deliverable 4 must be complete first (README links to demo site pages that need onboarding text).

Add a new section **above** "What It Does", serving as a project landing page for non-technical visitors.

### New Section: Key Findings

- 3-5 bullet points of the most significant recoveries in plain language (selected from Candidate Recoveries above)
- Written to provoke curiosity, not to be exhaustive
- Each bullet links to the specific recovery page on the demo site (e.g., teredacta.counting-to-infinity.com/recoveries/2924)
- **Precision:** Follow all precision requirements above

### New Section: Try It

- Prominent link to teredacta.counting-to-infinity.com/highlights
- One sentence: "Browse 5,600+ recovered redactions from the Congressional Epstein/Maxwell releases."

### Existing Content

All existing README content remains unchanged. The new sections go above it.

**Do NOT add a separate "How It Works (plain English)" section** — the existing opening paragraph already explains this.

---

## Deliverable 3: Unobfuscator README Update

**No dependencies.** Can be done in parallel with anything.

**Minimal change only.** Add one line to the existing TEREDACTA cross-reference section: "Browse recoveries from the Epstein archive at teredacta.counting-to-infinity.com"

Do NOT add findings or bullet points.

---

## Deliverable 4: Demo Site Onboarding

**No dependencies.** Should be completed before Deliverables 1 and 2.

This is the most critical deliverable for the Threads funnel. The site currently drops visitors into the entity explorer (root URL) with zero context.

### Required Changes

1. **Pin recovery 2924 (or whichever recovery is featured in the Threads post) at the top of the Highlights page.** Visitors from the thread need to immediately see the specific finding they came for. If the featured recovery isn't prominent on /highlights, visitors will feel baited.

2. **Add intro text to the Highlights page.** A brief orientation (2-3 sentences max) covering: what TEREDACTA is, what "recovered redactions" means, and the dataset scale. Must include: what the tool does (in non-technical language), that green text = recovered, and the number of documents analyzed. Tone: factual, not promotional.

3. **Add a one-liner to recovery detail pages explaining green highlights.** Place as a persistent banner above the merged text content (not a tooltip — invisible on mobile). Something like: "Green highlighted text was redacted by the government but recovered by cross-referencing multiple releases of this document."

4. **Add orientation text to the Explore page.** One sentence explaining what the entity graph is and how to use it, so visitors who navigate there from Highlights aren't lost.

5. **Add Open Graph meta tags to `base.html`.**
   - Default: `og:title` = "TEREDACTA", `og:description` = one-sentence summary, `og:image` = a purpose-built 1200x630px social card (the before/after screenshot from Post 3, or a branded card showing the key stat — NOT the 128px logo)
   - Per-page overrides for recovery detail pages: `og:title` = "Recovery #N — X redactions recovered", `og:description` = first ~150 chars of recovered text
   - Per-page OG images are out of scope — use the same static social card everywhere
   - Also add `<meta name="description">` for search engine indexing
   - Also add `twitter:card` / `twitter:title` / `twitter:description` / `twitter:image` for X cross-posting

6. **Add a favicon.** Use a cropped version of the TEREDACTA logo or a simple icon. One-line change, but missing favicons make sites look unfinished.

7. **Add UTM parameters to all campaign links.** Thread links should use `?utm_source=threads&utm_medium=social`. README links should use `?utm_source=github&utm_medium=readme`. This enables basic traffic source analysis from server access logs even without dedicated analytics.

8. **Verify mobile rendering** of the Highlights page and recovery detail pages. The Threads audience is overwhelmingly mobile. Test at 375px width (iPhone SE/Mini).

9. **Rename "Common Unredactions" heading** on the Highlights page to something non-jargon: "Frequently Recovered Text" or similar.

---

## Deliverable 5: Fix demo-recovery-2924.md

**No dependencies.** Must be completed before Deliverable 1.

The case study document has factual and framing issues that must be fixed before any public-facing content references it.

1. **Fix the title.** "48 Hours Before Epstein's Death" is wrong. The email is dated August 12, 2019 — two days AFTER Epstein died (August 10). The body confirms this: "staff who need to be interviewed by the FBI following Epstein's death." Change the title to accurately reflect that this is a post-mortem document (e.g., "Post-Mortem MCC Staffing Memo" or "MCC Staff Interview List — Two Days After Epstein's Death").

2. **Fix the "identities" claim.** Replace "reveals the identities, roles, and shift assignments" with "reveals the roles, shift assignments, and responsibility annotations" throughout.

3. **Fix "suicide watch" claim.** Line 61 says "a high-profile inmate on suicide watch" — Epstein was taken OFF suicide watch on July 29. The scandal is that he was removed from it. Fix to reflect this accurately.

4. **Fix "no functioning camera" claim.** Line 61 says "no functioning camera coverage." The DOJ stated cameras existed but footage was unusable/corrupted. Use precise language.

5. **Fix "minute-by-minute" claim.** Line 65 says "minute-by-minute accountability chain." The data is shift-level (2-10, 8-4, etc.). Change to "shift-by-shift."

6. **Add independent verification instructions.** Bates numbers (already present), where to download the originals from justice.gov, step-by-step manual confirmation process.

7. **Acknowledge limitations.** Define what "High" confidence means (anchor match lengths, context verification). Note any known limitations of the anchor matching approach.

---

## Out of Scope

- Rewriting existing technical documentation
- Major UI redesign of the demo site
- Creating a separate landing page or marketing site
- Writing the actual Threads copy (user will write all prose; spec provides suggestions/examples only)
- CONTRIBUTING.md or issue templates (valuable but separate effort)
- Dynamic per-page OG images (use static social card)
- Dedicated analytics platform (UTM params + server logs are sufficient)
