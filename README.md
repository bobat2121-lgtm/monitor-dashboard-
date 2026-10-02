# monitor-dashboard

A minimal editorial news platform for physical AI, built in Streamlit with an
obsidian black base, electric blue navigation and restrained copper-orange accents.

- Compact typographic masthead and a single, uninterrupted digest feed.
- Search and owner tools are available from compact navigation controls.
- In Owner, enable **Load grading controls** to grade one item at a time
  below each digest and on the Rejected tab: pick the item, score it 0-100
  (90+ lead, 70-89 digest, 40-69 borderline, <40 reject), optionally override
  the action, name a reason code, choose item or rule scope, and add a note.
  The grader's own score and reason for each item are shown so you grade
  against them. Both tabs post the same row to the aggregator's `/grades`
  endpoint with the runtime PIN; nothing is stored in this repo. An
  edition's trial items are graded in the same form as **T1–T3** (70+ = it
  belonged in the main digest, below 40 = noise): those grades teach the
  grader but stay out of the monthly calibration scoreboard and the trends.
- Keyboard-accessible article disclosures and direct source links.
- Existing Feed and Rejected navigation, owner feedback, API endpoints and
  automatic refresh behavior are preserved.
- The visual system is isolated in `feed.css`; the native widget theme lives in
  `.streamlit/config.toml`. No extra runtime dependencies or remote fonts.

- **Feed** — high-signal editions from the five daily review slots (7am, 9am,
  noon, 5pm, and 7pm ET), newest first. An edition may end with a collapsed
  **Trial** panel (at most 3 items, T1–T3): stories from discovery sources
  on a 21-day Radar trial, and stories the Radar Scout found the collection
  missed. Trial items never count toward the edition's items and are not
  prior coverage, so the same story can still appear in a later edition's
  main items. A search leaves the panel out.
- **Rejected** — the audit and feedback lane for reviewed candidates that were
  not selected for an edition.
- **Rules** (Owner PIN) — one tab, four sections: **Drafts and rules**
  (**Write a rule** in your own words, optionally about an event id; the
  scheduled ChatGPT reviewer proposes a universal rewrite after its next
  edition, shown beside your words with its signature, score bounds and any
  rule it overlaps or would replace; approve it, edit it, send it back with
  a note, or reject it. Rule-scoped grades take the same path. Active rules
  show their calibration state and score bounds; ask ChatGPT to revise a
  rule or write the missing signatures; supersede, set score bounds,
  deactivate, set signature, fold into a brief version), **Calibration** (the monthly scoreboard: headline and delta,
  trend, worst three, most improved, rules by state, drill-down),
  **Monthly audit** (the 20-minute checklist with the audit and focus form)
  and **How to grade** (the grading principles). The two guide pages are
  served by the aggregator from its runbook files, so they never drift.
- **Radar** (Owner PIN) — every change to what the Universe collects, signed
  off here. **New request** in your own words (track a company or
  relationship, or a story we missed: its link is required, and Claude
  checks whether we collected it and why it was missed, from no source, a
  filter, a broken source or a low ranking); the scheduled Claude
  Radar Scout drafts a card at its next run (1:30 PM and 8:30 PM ET) and adds
  its own from deal news and newsroom gaps. Each card shows its lane
  (**Relationship source**, **Company newsroom** for a company's own
  newsroom, or **Discovery lane**) and action, why, and the evidence (a live
  probe of the newsroom, with when it ran, and a backtest of the names
  against past items, with the matches that also name a guard word and
  samples); approve it, edit its source, record or company fields in
  Details (which also show, read-only, whether the source will be collected,
  its company status and the release stored as evidence), send it back with
  a note, or discard it. Approval
  re-checks the newsroom and saves a new registry revision; anything decided
  in the last 24 hours can be undone. A **Trial result** card (at day 21, or
  early after 3 trial grades of 70+ or 3 below 40) shows the trial's
  scorecard and is answered with **Promote** (a regular source, or the
  relationship source the card names), **Extend 21 days** or **Retire**
  (paused); Claude's pick is highlighted. To change the pick, send it back
  with a note; it has no Discard, and no Withdraw while it is with Claude,
  so the verdict stays due until you pick one. A **Start trial** card also
  lists the evidence the Worker verified (misses in the last 30 days, unique
  catches, and per story when it was first seen elsewhere, whether and how
  late a source collected it, and whether you reported or graded it). A
  **Missed story** card answers your missed-story request when we collected
  the story but the Grader ranked it low: it says in plain words when it was
  collected, as which event, and what the Grader did (with the event's link
  when it was matched by title). **Send to Rules** files a Rules draft
  about that event (your optional words, else your request's, plus the
  event and the Grader's call; it shows on the Rules tab as "from Radar
  (missed story)"); **Discard** drops it. Undoing a Send to Rules within 24
  hours withdraws the Rules draft while it is still pending; once it was
  decided on the Rules tab, undo it there. An **Identity backfill** card
  (up to 25 companies' SEC CIK, CAGE or UEI codes, procurement evidence or
  coverage review) lists each change in a compact table with its evidence
  link (SEC, USAspending or SAM; http(s) only): approve it as written, or
  send it back with a note to change rows, as it has no per-row editing. A
  card whose probe carries a failure class (a failed probe, or the failing
  channel's class, which the Scout copies there) shows it as a chip (**Blocked by the site**, **Needs JavaScript**, **No article list**,
  **Page not found**, **Page too large**, **Temporary error**, **Invalid
  URL**). **With Claude** lists what is waiting
  for the next run, with Withdraw, and **Lane health** lists Radar's sources
  with their collection status and, when the Worker reports them, the posts
  each kept and filtered out in the last 7 days (a new source's first-poll
  archive not counted), then a **Trial sources** table (trial day, items
  shown in the panel, average grade, grades of 70+ and below 40, unique
  catches, duplicates, posts collected), then **Recall by industry (30
  days)**: for each industry, the last evening recall audit (the 8:30 PM run
  audits a third of the industries each night), the stories it found, how
  many we captured (late catches included), how many late, and the recall
  percentage, then **Coverage by company**: how many companies have each
  grade (A newsroom or IR site, B distributor page, C regulatory filings, D
  procurement records, E trade press, F mentions only) and, behind a toggle
  that is off by default, the companies below C or with a failing channel
  (Company, Grade, Best channel, Failing, Review); an older aggregator sends
  no coverage and the section stays hidden. Radar replaces the Universe
  tab: the map and
  the manual editors left the dashboard, and those changes are now asked for
  in words.

Data comes from a public read-only JSON endpoint (`/digests`) served by a
Cloudflare Worker. Ranking and editorial summaries are produced by the
scheduled ChatGPT task; upstream monitors provide source facts rather than
editorial prose. No secrets are stored in this repo — the read endpoints are
public by design, while owner feedback requires a PIN supplied at runtime.

## Run locally

```
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy (Streamlit Community Cloud)

New app → this repo → branch `main` → main file `streamlit_app.py`.
