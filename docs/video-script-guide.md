# Msimulizi — Demo Video Script & Curation Guide

Hard limit: **≤ 2 minutes** (120 seconds). Target 105 s to give yourself a buffer.
Language: English narration over everything. English subtitles for all Swahili speech/text.
No real player names, no real clubs, no StatsBomb branding, no copyrighted music.

---

## Shot list and timing

### [0:00 – 0:08] — Opening hook (8 s)
**Screen:** black with title card
**Text on screen:** "400 million African football fans. One AI narrator."
**Voiceover:** "Meet Msimulizi — the Swahili AI that narrates football in real time."

---

### [0:08 – 0:25] — Live match loading (17 s)
**Screen:** Browser opens to `localhost:3000` (or the deployed URL).
Show the home page briefly — score bar reads `Kisima City 0 – 0 Mto wa Nuru`, pitch visual is live.
Click **Start Replay** — the match begins at 1× speed.

**Voiceover:** "A synthetic match kicks off. The AI pipeline watches every event — goals, chances, momentum shifts — and generates a card in under 5 seconds."

*Cut as soon as the first card appears.*

---

### [0:25 – 0:45] — First overlay card — Swahili goal (20 s)
**Screen:** A goal card appears. Headline in Swahili:
> **"Gooool! Amina Kivuva anaifungia Kisima City!"**
> *(English gloss below: "Goal! Amina Kivuva scores for Kisima City!")*

Show the card for 3–4 seconds. Pan down to show the English gloss rendered beneath.
Then **zoom into the card** to show the claim badges: `minute: 58`, `score: 1-2`, `xg: 0.46`.

**Voiceover:** "Every Swahili card includes an English gloss and cites its sources — minute, score, and expected goals. Nothing is invented."

*Optional: play a 2-second clip of the Swahili TTS audio if you have it.*

---

### [0:45 – 1:00] — Personalisation panel (15 s)
**Screen:** Open the personalisation panel (right sidebar).
- Switch language to **English**
- Change club perspective to **Away (Mto wa Nuru)**
- Toggle mode to **Analyst**

A new card appears — same moment, different voice:
> **"Amina Kivuva's 0.46 xG finish gives Kisima City the lead at 1-2 — Mto wa Nuru's defensive shape was exposed."**

**Voiceover:** "One match, many perspectives. Fans choose their club, language, and depth of analysis."

---

### [1:00 – 1:15] — Architecture callout (15 s)
**Screen:** Switch to a brief architecture slide (static image or the README diagram).
Highlight the Azure services with brief labels appearing one at a time:
- AI Foundry → "GPT-4o narrates"
- AI Speech → "Swahili voices"
- Cosmos DB → "state + cache"
- Application Insights → "latency monitoring"

**Voiceover:** "Powered entirely on Azure — AI Foundry, Speech, Cosmos DB, Container Apps, and Application Insights tracking every millisecond."

*Keep this slide to exactly 15 seconds. Don't linger.*

---

### [1:15 – 1:35] — Review dashboard / quality proof (20 s)
**Screen:** Navigate to `/review` (enter the reviewer key).
Show:
1. The latency chart — p50 and p95 bars for card and audio latency
2. The groundedness score tile: **100%**
3. The native-speaker rating tile: **4.2 / 5**

**Voiceover:** "The built-in review dashboard shows live latency metrics and quality scores — groundedness checked across 50 moments, Swahili lines rated by native speakers."

---

### [1:35 – 1:50] — Resilience / fallback moment (15 s)
**Screen:** In the replay panel, drag the speed slider to **4×**.
Show cards continuing to flow — some may show the `bundle` badge.

**Voiceover:** "Push the speed to 4×. When the LLM quota is tight, the system falls back to a pre-generated bundle — the match never stops."

---

### [1:50 – 2:00] — Closing (10 s)
**Screen:** Back to the main viewer. Swahili card is on screen. Show the repo URL.
**Text on screen:** "github.com/[your-handle]/msimulizi"
**Voiceover:** "Msimulizi. Real-time football intelligence. Built for Africa, built on Azure."

*Fade to black.*

---

## Recording tips

- Use **OBS Studio** or **Screenium** to record at 1080p 30fps.
- Set browser zoom to 110% so UI text is readable after compression.
- Record audio separately with a decent mic; sync in DaVinci Resolve or CapCut.
- Use a royalty-free background score — search "football ambient loop" on **Pixabay** or **Free Music Archive** (CC0 licence only).
- Add English subtitles for every Swahili word spoken or visible on screen — mandatory per the rules.
- Export as MP4 H.264, ≤ 500 MB. YouTube accepts this directly.

## What to avoid

- No real club names (Arsenal, Barcelona, etc.)
- No real player names
- No StatsBomb logo or branding anywhere on screen
- No Microsoft internal tooling or confidential slides
- No copyrighted music — CC0 only
- Do not exceed 2:00 — the submission form may truncate or penalise over-length videos

## Upload checklist

- [ ] Upload to YouTube (unlisted is fine — just needs to be publicly viewable via link)
- [ ] Paste the YouTube URL into the Innovation Studio project page
- [ ] Confirm auto-generated captions are on OR manually upload an SRT subtitle file
