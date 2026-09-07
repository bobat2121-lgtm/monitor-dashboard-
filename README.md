# monitor-dashboard

A minimal editorial news platform for physical AI, built in Streamlit with an
obsidian black base, electric blue navigation and restrained copper-orange accents.

- Compact typographic masthead and a single, uninterrupted digest feed.
- Search and owner tools are available from compact navigation controls.
- In Owner, enable **Load grading controls** to show article votes, an optional
  note, and **Submit grades** below each digest inside its panel. Each digest
  submits independently, including earlier editions loaded through pagination.
- Keyboard-accessible article disclosures and direct source links.
- Existing Feed, Rejected and Universe navigation, owner feedback, API endpoints
  and automatic refresh behavior are preserved.
- The visual system is isolated in `feed.css`; the native widget theme lives in
  `.streamlit/config.toml`. No extra runtime dependencies or remote fonts.

- **Feed** — high-signal editions from the five daily review slots (7am, 9am,
  noon, 5pm, and 7pm ET), newest first.
- **Rejected** — the audit and feedback lane for reviewed candidates that were
  not selected for an edition.

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
