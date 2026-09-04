# monitor-dashboard

Black, X-style Streamlit feed for a Cloudflare-based news monitoring pipeline.

- **Feed** — high-signal editions from the five daily review slots (7am, 9am,
  noon, 5pm, and 7pm ET), newest first.
- **Rejected** — the audit and feedback lane for reviewed candidates that were
  not selected for an edition.
- **Pipeline status** — `/health`-based green/amber/red freshness. A successful
  quiet review stays healthy even when it intentionally publishes no edition.

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
