# monitor-dashboard

Black, X-style Streamlit feed for a Cloudflare-based news monitoring pipeline.

- **⚡ Daily tab** — one post per digest run (7am / 9am / 5pm ET), ten ranked
  items each: one-sentence summary, value badge where applicable, source link.
- **🗞 Weekly tab** — Friday 8am ET synthesis of the week's top items.

Data comes from a public read-only JSON endpoint (`/digests`) served by a
Cloudflare Worker; the ranking and synthesis are done by Claude on a schedule.
No secrets in this repo — the endpoint is public by design.

## Run locally

```
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy (Streamlit Community Cloud)

New app → this repo → branch `main` → main file `streamlit_app.py`.
