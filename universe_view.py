"""Owner-only industry map and source management over the shared registry."""
import hashlib
import html
import json
import textwrap
import uuid
from datetime import datetime, timezone

import plotly.graph_objects as go
import requests
import streamlit as st

BLUE = "#3182f6"
ORANGE = "#ff9a3d"
MUTED = "#858e99"
ROLE_NAMES = {
    "company_newsroom": "Company newsroom",
    "company_ir_earnings_presentation": "Earnings and presentations",
    "official_customer_partner": "Official customer or partner",
    "official_government_procurement": "Official government or procurement",
}


def api(base, pin, path="", payload=None):
    headers = {"X-Owner-Pin": pin}
    if payload is None:
        response = requests.get(f"{base}/universe{path}", headers=headers, timeout=25)
    else:
        response = requests.post(f"{base}/universe{path}", headers=headers, json=payload, timeout=30)
    try:
        result = response.json()
    except ValueError:
        raise ValueError("The Universe service is temporarily unavailable. Try refreshing.") from None
    if response.status_code >= 400 or not result.get("ok"):
        raise ValueError(result.get("error") or "The change could not be completed.")
    return result


def config_hash(source):
    value = json.dumps([source["endpoint"], source["adapter"], source.get("config", {})], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def source_status(source, data):
    status = source.get("configuration_status", "draft")
    if status != "configured":
        return {"draft": "Draft", "paused": "Paused", "needs_adapter": "Needs setup"}.get(status, status)
    health = data.get("source_health", {}).get(source["key"], {})
    if source.get("managed_by") == "universe":
        if data.get("collection_state") != "applied":
            return "Pending activation"
        if health.get("config_hash") != config_hash(source):
            return "Awaiting first check"
    if health.get("fail_count", 0):
        return "Needs attention"
    if health.get("last_ok"):
        if overdue(health["last_ok"], source.get("cadence_minutes", 120) + 15):
            return "Overdue"
        return "Collecting"
    return "Not yet verified"


def overdue(value, minutes):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - parsed).total_seconds() > minutes * 60
    except (ValueError, TypeError):
        return True


def company_status(entity, data):
    sources = [s for s in data["registry"]["sources"] if entity["id"] in s.get("entity_ids", []) and s.get("source_role") in {"company_newsroom", "official_customer_partner"}]
    if not sources:
        return "Newsroom gap"
    states = [source_status(s, data) for s in sources]
    if "Collecting" in states:
        return "Collecting"
    return states[0]


def short_time(value):
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.strftime("%b %d, %H:%M UTC")
    except ValueError:
        return str(value)[:24]


def wrapped(value, width=24):
    return "<br>".join(html.escape(line) for line in textwrap.wrap(str(value), width))


def coverage_figure(data, industry_id=None, entities=None, selected=None, connection_kind="Sources"):
    registry = data["registry"]
    nodes, edges = [], []
    entities = entities if entities is not None else registry["entities"]
    if not industry_id and not selected:
        for n, industry in enumerate(registry["industries"]):
            count = sum(any(m["industry_id"] == industry["id"] for m in e["memberships"]) for e in registry["entities"])
            nodes.append(dict(kind="industry", id=industry["id"], x=n % 3, y=-(n // 3), color=BLUE,
                              label=wrapped(industry["name"], 25) + f"<br><span style='color:{MUTED}'>{count} names</span>"))
        height, position = 650, "bottom center"
        xrange = [-0.5, 2.5]
    elif selected:
        memberships = selected["memberships"]
        lanes = [i for i in registry["industries"] if any(m["industry_id"] == i["id"] for m in memberships)]
        sources = [s for s in registry["sources"] if selected["id"] in s.get("entity_ids", [])]
        for n, industry in enumerate(lanes):
            nodes.append(dict(kind="industry", id=industry["id"], x=0, y=n * 2, color=BLUE, label=wrapped(industry["name"], 21)))
        middle = max(len(lanes), len(sources), 1) - 1
        nodes.append(dict(kind="company", id=selected["id"], x=1.5, y=middle, color=BLUE if company_status(selected, data) == "Collecting" else ORANGE, label=wrapped(selected["name"], 22)))
        for i in range(len(lanes)):
            edges.append((nodes[i], nodes[-1]))
        company_node = nodes[-1]
        if connection_kind != "Sources":
            sources = [n for n in registry.get("knowledge_nodes", []) if selected["id"] in n["entity_ids"] and n["kind"] == connection_kind]
            sources = sources[:14]
        for n, source in enumerate(sources):
            status = source_status(source, data) if connection_kind == "Sources" else source["match_mode"] + " matching"
            node = dict(kind="source" if connection_kind == "Sources" else "knowledge", id=source["key"] if connection_kind == "Sources" else source["id"], x=3, y=n * 2, color=BLUE if status == "Collecting" else ORANGE,
                        label=wrapped(source["name"], 24) + "<br>" + html.escape(status))
            nodes.append(node)
            edges.append((company_node, node))
        height, position, xrange = max(400, min(700, 130 * max(len(lanes), len(sources), 3))), "bottom center", [-0.7, 3.7]
    else:
        industry = next(i for i in registry["industries"] if i["id"] == industry_id)
        shown = sorted(entities, key=lambda e: (e["coverage_role"] != "covered", e["name"].lower()))[:18]
        nodes.append(dict(kind="industry", id=industry_id, x=0, y=(len(shown) - 1) / 2, color=BLUE, label=wrapped(industry["name"], 21)))
        for n, entity in enumerate(shown):
            status = company_status(entity, data)
            node = dict(kind="company", id=entity["id"], x=1.5, y=n, color=BLUE if status == "Collecting" else ORANGE,
                        label=html.escape(entity["name"]) + (" · covered" if entity["coverage_role"] == "covered" else ""))
            nodes.append(node)
            edges.append((nodes[0], node))
        height, position, xrange = max(400, min(760, 38 * len(shown) + 80)), "middle right", [-0.5, 4]
    fig = go.Figure()
    if edges:
        xs, ys = [], []
        for a, b in edges:
            xs.extend([a["x"], b["x"], None]); ys.extend([a["y"], b["y"], None])
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color="#29394f", width=1.3), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(
        x=[n["x"] for n in nodes], y=[n["y"] for n in nodes], mode="markers+text",
        text=[n["label"] for n in nodes], textposition=position, textfont=dict(size=14, color="#eef1f4"),
        customdata=[[n["kind"], n["id"]] for n in nodes],
        marker=dict(size=20, color=[n["color"] for n in nodes], line=dict(width=2, color="#0c1118")),
        hovertemplate="%{text}<extra></extra>", selected=dict(marker=dict(opacity=1, size=25)),
        unselected=dict(marker=dict(opacity=0.9)), showlegend=False,
    ))
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=25, b=95), paper_bgcolor="#0c1118", plot_bgcolor="#0c1118",
                      clickmode="event+select", dragmode="pan", font=dict(color="#eef1f4"),
                      xaxis=dict(visible=False, range=xrange, fixedrange=True), yaxis=dict(visible=False, fixedrange=True))
    return fig


def save_change(base, pin, data, operation, preview_id=None):
    payload = {"change_id": str(uuid.uuid4()), "expected_id": data["revision_id"], "operation": operation}
    if preview_id:
        payload["preview_id"] = preview_id
    try:
        api(base, pin, "/change", payload)
    except (ValueError, requests.RequestException) as error:
        st.error(str(error))
        return
    st.session_state.pop("universe_data", None)
    st.session_state.pop("universe_preview", None)
    st.session_state["universe_notice"] = "Saved. Collection status will update after the next check. The ranking brief will receive this version through the next registry sync."
    st.rerun()


def company_editor(base, pin, data, entity=None):
    registry = data["registry"]
    suffix = (entity or {}).get("id", "new") + data["revision_id"]
    name = st.text_input("Company name", value=(entity or {}).get("name", ""), key="company_name_" + suffix)
    aliases = st.text_input("Other names or aliases", value=", ".join((entity or {}).get("aliases", [])), key="company_aliases_" + suffix)
    memberships = {m["industry_id"]: m["subindustry_ids"] for m in (entity or {}).get("memberships", [])}
    industries = {i["id"]: i for i in registry["industries"]}
    selected = st.multiselect("Industries", list(industries), default=list(memberships), format_func=lambda i: industries[i]["name"], key="company_lanes_" + suffix)
    new_memberships = []
    for industry_id in selected:
        sub = {s["id"]: s["name"] for s in industries[industry_id]["subindustries"]}
        chosen = st.multiselect(industries[industry_id]["name"] + " — subindustries", list(sub), default=memberships.get(industry_id, []),
                                format_func=lambda s, names=sub: names[s], key="company_sub_" + suffix + industry_id)
        new_memberships.append({"industry_id": industry_id, "subindustry_ids": chosen})
    sec_cik = st.text_input("SEC issuer CIK (optional)", value=(entity or {}).get("sec_cik", ""), max_chars=10, key="company_cik_" + suffix, help="An official SEC issuer CIK enables the separate executive-transaction collector. Leave blank for companies without SEC reporting.")
    with st.container():
        st.caption("Verified government vendor identifiers (optional)")
        cages = st.text_input("CAGE codes (comma separated)", value=", ".join((entity or {}).get("cage_codes", [])), key="company_cage_" + suffix)
        ueis = st.text_input("UEI codes (comma separated)", value=", ".join((entity or {}).get("uei_codes", [])), key="company_uei_" + suffix)
        identity_evidence = st.text_input("Official identity evidence", value=(entity or {}).get("procurement_identity_evidence", ""), key="company_identity_" + suffix, help="Reference the SAM registration or official award that verifies these identifiers for this company.")
    notes = st.text_area("What to track", value=(entity or {}).get("tracking_notes", ""), max_chars=4000, key="company_notes_" + suffix)
    if not entity:
        st.caption("New companies join as adjacent comparables. Each company can belong to several industries.")
    if st.button("Save company", key="save_company_" + suffix, type="primary"):
        value = dict(name=name, aliases=[a.strip() for a in aliases.split(",") if a.strip()], memberships=new_memberships, tracking_notes=notes, sec_cik=sec_cik, cage_codes=[x.strip() for x in cages.split(",") if x.strip()], uei_codes=[x.strip() for x in ueis.split(",") if x.strip()], procurement_identity_evidence=identity_evidence)
        if entity:
            value["id"] = entity["id"]
        save_change(base, pin, data, {"kind": "entity_upsert", "value": value})


def source_editor(base, pin, data, source=None):
    registry = data["registry"]
    entity_names = {e["id"]: e["name"] for e in registry["entities"]}
    source = source or {}
    protected = source.get("protected_roster_entry", False)
    suffix = source.get("key", "new") + data["revision_id"]
    if protected:
        st.info("Original source. Its endpoint, polling frequency, and phone delivery are protected. You can update company links and tracking notes.")
    with st.form("source_form_" + suffix):
        ids = st.multiselect("Linked companies", list(entity_names), default=source.get("entity_ids", []), format_func=lambda e: entity_names[e])
        lane_names = {i["id"]: i["name"] for i in registry["industries"]}
        knowledge_names = {n["id"]: n["name"] for n in registry.get("knowledge_nodes", [])}
        lanes = st.multiselect("Source industries (optional)", list(lane_names), default=source.get("industry_ids", []), format_func=lambda x: lane_names[x])
        knowledge = st.multiselect("Source relationships (optional)", list(knowledge_names), default=source.get("knowledge_ids", []), format_func=lambda x: knowledge_names[x])
        name = st.text_input("Source name", value=source.get("name", ""), disabled=protected)
        endpoint = st.text_input("Newsroom or feed URL", value=source.get("endpoint", ""), disabled=protected, placeholder="https://company.com/news/")
        cols = st.columns(2)
        with cols[0]:
            methods = ["auto", "rss", "html", "wp_json", "json"]
            current_method = source.get("adapter", "auto")
            if current_method not in methods:
                methods.append(current_method)
            method = st.selectbox("Collection method", methods, index=methods.index(current_method), disabled=protected,
                                  format_func=lambda x: {"auto": "Detect automatically", "rss": "RSS / Atom", "html": "Newsroom links", "wp_json": "WordPress articles", "json": "Structured articles (JSON)"}.get(x, x))
            prefix = st.text_input("Article path, if needed", value=source.get("config", {}).get("path_prefix", ""), disabled=protected, placeholder="/news/")
        with cols[1]:
            statuses = ["public", "private", "noncompany"]
            company_state = source.get("companyStatus") if source.get("companyStatus") in statuses else "private"
            company_state = st.selectbox("Company status", statuses, index=statuses.index(company_state), disabled=protected)
            cadence = st.number_input("Check every (minutes)", min_value=8, max_value=120, value=int(source.get("cadence_minutes", 60)), step=1, disabled=protected)
        roles = list(ROLE_NAMES)
        current_role = source.get("source_role", "company_newsroom")
        if current_role not in roles:
            roles.append(current_role)
        role = st.selectbox("Source role", roles, index=roles.index(current_role), format_func=lambda x: ROLE_NAMES.get(x, x.replace("_", " ")), disabled=protected)
        state_options = ["draft", "configured", "paused", "needs_adapter"]
        state = st.selectbox("Collection", state_options, index=state_options.index(source.get("configuration_status", "draft")), disabled=protected,
                             format_func=lambda x: {"draft": "Save as draft", "configured": "Activate collection", "paused": "Pause collection", "needs_adapter": "Needs a custom adapter"}[x])
        include_terms = st.text_area("Topic filter (optional, one phrase per line)", value="\n".join(source.get("config", {}).get("include_terms", [])), disabled=protected, help="Use for broad customer or partner newsrooms. A release must mention at least one phrase. Leave empty to collect all company updates.")
        exclude_paths = st.text_area("Exclude sections (optional, one path per line)", value="\n".join(source.get("config", {}).get("exclude_paths", [])), disabled=protected, placeholder="/in-the-news/")
        include_categories = st.text_area("Allowed release categories (optional, one per line)", value="\n".join(source.get("config", {}).get("include_categories", [])), disabled=protected, help="Exact categories from the company’s page or feed, such as Press Release. Other categories are excluded.")
        card_fields = {}
        with st.expander("Advanced page extraction", expanded=False):
            st.caption("Advanced page extraction — use when releases share a page with media coverage. Preview before saving.")
            for field, label in [("item_selector", "Article card selector"), ("title_selector", "Headline selector"), ("link_selector", "Article link selector"), ("category_selector", "Category selector"), ("date_selector", "Publication date selector")]:
                card_fields[field] = st.text_input(label, value=source.get("config", {}).get(field, ""), disabled=protected, placeholder=".release-card" if field == "item_selector" else "", key=field + suffix).strip()
            allow_pdf = st.checkbox("Include company-hosted PDF releases", value=source.get("config", {}).get("allow_pdf", False), disabled=protected, help="Collect PDF headlines and links from the selected release cards. Document downloads are handled only when reviewing a selected story.")
        json_fields = {}
        with st.expander("Advanced structured feed extraction", expanded=False):
            st.caption("Use the JSON method for a company article API or embedded article data. Preview to verify titles and company-only categories.")
            for field, label in [("json_script_id", "Embedded JSON element ID (optional)"), ("json_items_path", "Article array path"), ("json_title_field", "JSON headline field"), ("json_url_field", "JSON URL field"), ("json_url_prefix", "Article URL directory (optional)"), ("json_date_field", "JSON date field"), ("json_category_field", "JSON category field"), ("json_external_field", "JSON external media flag"), ("json_excerpt_field", "JSON excerpt field")]:
                json_fields[field] = st.text_input(label, value=source.get("config", {}).get(field, ""), disabled=protected, key=field + suffix).strip()
        st.caption("Company-issued releases and official updates only. External media coverage and ‘in the news’ roundups are excluded.")
        notes = st.text_area("Source notes", value=source.get("tracking_notes", ""), max_chars=2000)
        st.caption("New sources feed the digest. First checks establish a baseline. Public companies: at most 60 minutes; private companies: at most 120; covered companies: 8 minutes.")
        left, right = st.columns(2)
        preview_clicked = left.form_submit_button("Preview releases", disabled=protected)
        save_clicked = right.form_submit_button("Save source", type="primary")
    inputs = {"endpoint": endpoint.strip(), "adapter": method, "path_prefix": prefix.strip(), "include_terms": [x.strip() for x in include_terms.splitlines() if x.strip()], "exclude_paths": [x.strip() for x in exclude_paths.splitlines() if x.strip()]}
    inputs.update(card_fields)
    inputs.update(json_fields)
    inputs["allow_pdf"] = allow_pdf
    inputs["include_categories"] = [x.strip() for x in include_categories.splitlines() if x.strip()]
    if preview_clicked:
        with st.spinner("Checking the source and its releases…"):
            try:
                result = api(base, pin, "/preview", inputs)
                st.session_state["universe_preview"] = {"inputs": inputs, "result": result, "suffix": suffix}
            except (ValueError, requests.RequestException) as error:
                st.session_state.pop("universe_preview", None)
                st.error(str(error))
    preview = st.session_state.get("universe_preview")
    matching = preview and preview.get("inputs") == inputs and preview.get("suffix") == suffix
    if matching:
        result = preview["result"]
        st.success(f"Found {result['total_found']} releases. Detected {result['source']['adapter']} collection.")
        st.caption("Collection URL: " + result["source"]["endpoint"])
        if result.get("excluded"):
            st.caption("Excluded by source scope: " + ", ".join(f"{key.replace('_', ' ')}: {count}" for key, count in result["excluded"].items()))
        st.dataframe([{"Release": i["title"], "Published": short_time(i.get("published")), "URL": i["url"]} for i in result["items"]],
                     hide_index=True, use_container_width=True, column_config={"URL": st.column_config.LinkColumn("URL")})
        if result.get("undated_count"):
            st.caption("Some releases have no publication date. Their observation time will be recorded separately.")
    if save_clicked:
        value = {"entity_ids": ids, "tracking_notes": notes, "industry_ids": lanes, "knowledge_ids": knowledge}
        if source:
            value["key"] = source["key"]
        proof = None
        if not protected:
            chosen = preview["result"]["source"] if matching else {"endpoint": inputs["endpoint"], "adapter": method, "config": {"path_prefix": prefix.strip()}}
            value.update(name=name, endpoint=chosen["endpoint"], adapter=chosen["adapter"], path_prefix=chosen["config"].get("path_prefix", ""),
                         companyStatus=company_state, cadence_minutes=int(cadence), source_role=role, configuration_status=state, include_terms=inputs["include_terms"], exclude_paths=inputs["exclude_paths"])
            value.update(json_fields)
            value.update(card_fields, include_categories=inputs["include_categories"], allow_pdf=inputs["allow_pdf"])
            if matching:
                proof = preview["result"]["preview_id"]
        save_change(base, pin, data, {"kind": "source_upsert", "value": value}, proof)


def render_universe(base):
    pin = str(st.session_state.get("grader_pin", "")).strip()
    if not pin:
        st.info("Enter your Grader PIN in Owner mode to open the Universe map and source manager.")
        return
    cache_key = hashlib.sha256((base + pin).encode()).hexdigest()
    cached = st.session_state.get("universe_data")
    if not cached or cached["auth"] != cache_key:
        try:
            with st.spinner("Loading your Universe…"):
                data = api(base, pin)
            st.session_state["universe_data"] = {"auth": cache_key, "data": data}
        except (ValueError, requests.RequestException) as error:
            st.error(str(error))
            return
    data = st.session_state["universe_data"]["data"]
    registry = data["registry"]
    if notice := st.session_state.pop("universe_notice", None):
        st.success(notice)
    status_col, refresh_col = st.columns([4, 1])
    with status_col:
        st.caption("Worker matching: " + ("current" if data.get("matching_revision") == data.get("revision_id") else "update pending"))
        st.caption("Ranking brief: " + ("current" if data.get("ranking_published") else "update pending — syncs about every 15 minutes"))
        if data.get("collection_state") != "applied":
            st.caption("Collector configuration is pending; activation will retry automatically.")
    with refresh_col:
        if st.button("Refresh", key="universe_refresh"):
            st.session_state.pop("universe_data", None)
            st.rerun()
    metrics = st.columns(3)
    metrics[0].metric("Industries", len(registry["industries"]))
    metrics[1].metric("Tracked names", len(registry["entities"]))
    metrics[2].metric("Configured sources", sum(s["configuration_status"] == "configured" for s in registry["sources"]))
    collector = data.get("collector") or {}
    active_sources = [s for s in data["registry"]["sources"] if s.get("managed_by") == "universe" and s.get("configuration_status") == "configured"]
    requested_per_hour = sum(60 / max(8, s.get("cadence_minutes", 120)) for s in active_sources)
    capacity_per_hour = 60 * collector.get("batch_limit", 6)
    st.caption(f"Supplemental collection: {len(active_sources)} active sources · {requested_per_hour:.0f} planned checks/hour · capacity {capacity_per_hour}/hour. One source can serve several companies and industries.")
    if requested_per_hour > capacity_per_hour * .7:
        st.warning("Collection is approaching capacity. Add another collector partition before expanding much further; all saved names and sources are retained.")
    managed_active = any(s.get("managed_by") == "universe" and s.get("configuration_status") == "configured" for s in registry["sources"])
    if managed_active and (not collector.get("last_tick") or overdue(collector["last_tick"], 5) or collector.get("last_error")):
        st.warning("The supplemental collector has not reported a healthy recent check. Saved sources are retained; refresh to check recovery.")
    if collector.get("oldest_due_minutes", 0) > 15:
        st.warning("Some supplemental sources are overdue. Collection capacity needs attention; original source schedules remain independent.")
    next_mode = st.session_state.pop("universe_next_mode", None)
    if next_mode:
        st.session_state["universe_mode"] = next_mode
    mode = st.radio("Universe view", ["Map", "Sources", "Relationships", "Government", "History"], horizontal=True, key="universe_mode", label_visibility="collapsed")
    if mode == "Relationships":
        render_relationships(base, pin, data)
        return
    if mode == "Government":
        render_government(base, pin, data)
        return
    if mode == "History":
        try:
            history = api(base, pin, "/history")["revisions"]
        except (ValueError, requests.RequestException) as error:
            st.error(str(error)); return
        st.dataframe([{"Change": r["label"], "Saved": short_time(r["created_at"]), "Collection": r["collection_state"], "Ranking published": bool(r.get("published_commit"))} for r in history], hide_index=True, use_container_width=True)
        prior = [r for r in history if r["id"] != data["revision_id"]]
        if prior:
            chosen = st.selectbox("Restore a saved configuration", prior, format_func=lambda r: short_time(r["created_at"]) + " · " + r["label"])
            st.caption("Restoring saves another version. Collected articles and the original roster are retained.")
            if st.button("Restore this configuration"):
                save_change(base, pin, data, {"kind": "restore", "revision_id": chosen["id"]})
        return
    if mode == "Sources":
        filter_col, query_col = st.columns([1, 2])
        with filter_col:
            state_filter = st.selectbox("Status", ["All sources", "Collecting", "Overdue", "Pending activation", "Newsroom gaps", "Needs attention", "Draft", "Paused", "Needs setup", "Awaiting first check", "Not yet verified"])
        with query_col:
            query = st.text_input("Find a source or company", key="source_search").lower().strip()
        names = {e["id"]: e["name"] for e in registry["entities"]}
        sources = [s for s in registry["sources"] if not query or query in (s["name"] + " " + " ".join(names.get(e, e) for e in s.get("entity_ids", []))).lower()]
        if state_filter == "Newsroom gaps":
            gaps = [e for e in registry["entities"] if company_status(e, data) == "Newsroom gap"]
            st.dataframe([{"Company": e["name"], "Candidate newsroom": (e.get("source_candidates") or [{}])[0].get("url", "")} for e in gaps], hide_index=True, use_container_width=True,
                         column_config={"Candidate newsroom": st.column_config.LinkColumn("Candidate newsroom")})
        elif state_filter != "All sources":
            sources = [s for s in sources if source_status(s, data) == state_filter]
        rows = []
        for s in sources:
            h = data.get("source_health", {}).get(s["key"], {})
            rows.append({"Source": s["name"], "Companies": ", ".join(names.get(i, i) for i in s.get("entity_ids", [])), "Status": source_status(s, data),
                         "Minutes": s.get("cadence_minutes"), "Last successful check": short_time(h.get("last_ok")), "Last article": short_time(h.get("last_article")), "Original": bool(s.get("protected_roster_entry"))})
        st.dataframe(rows, hide_index=True, use_container_width=True)
        st.caption("A quiet newsroom can be healthy. Last successful check and last article are separate measures.")
        all_sources = {s["key"]: s for s in registry["sources"]}
        options = [None] + list(all_sources)
        jump = st.session_state.pop("universe_next_source", None)
        if jump in all_sources:
            st.session_state["universe_source"] = jump
        if st.session_state.get("universe_source") not in options:
            st.session_state["universe_source"] = None
        selected = st.selectbox("Edit or add a source", options, format_func=lambda k: "＋ Add a source" if k is None else all_sources[k]["name"], key="universe_source")
        source_editor(base, pin, data, all_sources.get(selected))
        return

    industries = {i["id"]: i for i in registry["industries"]}
    jump = st.session_state.pop("universe_next_industry", None)
    if jump in industries:
        st.session_state["universe_industry"] = jump
    industry_id = st.selectbox("Industry", [None] + list(industries), format_func=lambda i: "All industries" if i is None else industries[i]["name"], key="universe_industry")
    search_col, role_col = st.columns([2, 1])
    with search_col:
        query = st.text_input("Find a company", key="universe_company_search").lower().strip()
    with role_col:
        role = st.selectbox("Coverage", ["All names", "Covered companies", "Adjacent comparables", "Newsroom gaps"])
    entities = registry["entities"]
    if industry_id:
        entities = [e for e in entities if any(m["industry_id"] == industry_id for m in e["memberships"])]
        subs = {s["id"]: s["name"] for s in industries[industry_id]["subindustries"]}
        sub = st.selectbox("Subindustry", [None] + list(subs), format_func=lambda s: "All subindustries" if s is None else subs[s], key="map_sub_" + industry_id)
        if sub:
            entities = [e for e in entities if any(m["industry_id"] == industry_id and sub in m["subindustry_ids"] for m in e["memberships"])]
    if query:
        related = {eid for n in registry.get("knowledge_nodes", []) if query in " ".join([n["name"], *n["aliases"]]).lower() for eid in n["entity_ids"]}
        entities = [e for e in entities if e["id"] in related or query in " ".join([e["name"], *e["aliases"]]).lower()]
    if role in ["Covered companies", "Adjacent comparables"]:
        entities = [e for e in entities if e["coverage_role"] == ("covered" if role == "Covered companies" else "adjacent_comparable")]
    if role == "Newsroom gaps":
        entities = [e for e in entities if company_status(e, data) == "Newsroom gap"]
    entity_map = {e["id"]: e for e in entities}
    jump = st.session_state.pop("universe_next_company", None)
    if jump in entity_map:
        st.session_state["universe_company"] = jump
    if st.session_state.get("universe_company") not in entity_map:
        st.session_state["universe_company"] = None
    selected_id = st.selectbox("Company", [None] + list(entity_map), format_func=lambda e: "Choose a company" if e is None else entity_map[e]["name"], key="universe_company")
    selected = entity_map.get(selected_id)
    connection_kind = st.selectbox("Company connections", ["Sources", "subsidiary", "product", "agency", "program", "regulation"]) if selected else "Sources"
    chart_key = connection_kind + "coverage_map_" + str(industry_id) + str(selected_id) + query + role + str(st.session_state.get("universe_map_nonce", 0))
    event = st.plotly_chart(coverage_figure(data, industry_id, entities, selected, connection_kind), use_container_width=True, key=chart_key,
                           on_select="rerun", selection_mode="points", config={"displayModeBar": False, "scrollZoom": False})
    points = (event.get("selection") or {}).get("points", [])
    if points and points[0].get("customdata"):
        kind, ident = points[0]["customdata"]
        token = (chart_key, kind, ident)
        if st.session_state.get("universe_last_click") != token:
            st.session_state["universe_last_click"] = token
            st.session_state["universe_map_nonce"] = st.session_state.get("universe_map_nonce", 0) + 1
            st.session_state["universe_next_" + kind] = ident
            if kind == "knowledge":
                st.session_state["universe_next_mode"] = "Relationships"
            if kind == "source":
                st.session_state["universe_next_mode"] = "Sources"
            st.rerun()
    st.caption("Select a node to explore. Company connections show up to 14 records; Relationships provides the complete searchable list. Government connections describe research exposure.")
    if industry_id and not selected:
        st.caption(f"{len(entities)} matching names. The map shows up to 18 at a time; use search or the company selector to reach every name.")
    if selected:
        verification = selected.get("newsroom_discovery") or {}
        if verification:
            st.caption("Newsroom check: " + verification.get("status", "not checked").replace("_", " ") + " · " + short_time(verification.get("checked_at")))
            if verification.get("note"):
                st.info(verification["note"])
        candidates = selected.get("source_candidates", [])
        if candidates:
            with st.expander("Candidate newsrooms"):
                for candidate in candidates:
                    st.markdown(f"[{candidate.get('label', 'Company newsroom')}]({candidate['url']})")
                st.caption("Candidate pages still require a preview and activation in Sources.")
        with st.expander("Company details and tracking", expanded=False):
            company_editor(base, pin, data, selected)
    with st.expander("Add a company"):
        company_editor(base, pin, data)


def render_relationships(base, pin, data):
    registry = data["registry"]
    records = registry.get("knowledge_nodes", [])
    names = {e["id"]: e["name"] for e in registry["entities"]}
    industries = {i["id"]: i["name"] for i in registry["industries"]}
    st.caption("Shared records feed the map, ranking brief, and supported worker matchers. Agency and program links provide research context; they do not imply a company award.")
    cols = st.columns(2)
    kind_filter = cols[0].selectbox("Record type", ["All", "subsidiary", "product", "agency", "program", "regulation"])
    query = cols[1].text_input("Find a relationship", key="knowledge_search").lower().strip()
    visible = [n for n in records if (kind_filter == "All" or n["kind"] == kind_filter) and (not query or query in " ".join([n["name"], *n["aliases"], *[names.get(i, i) for i in n["entity_ids"]]]).lower())]
    st.dataframe([{"Record": n["name"], "Type": n["kind"], "Companies": ", ".join(names[i] for i in n["entity_ids"]), "Aliases": ", ".join(n["aliases"]), "Matching": n["match_mode"]} for n in visible], hide_index=True, use_container_width=True)
    lookup = {n["id"]: n for n in records}
    jump = st.session_state.pop("universe_next_knowledge", None)
    if jump in lookup:
        st.session_state["knowledge_selected"] = jump
    ident = st.selectbox("Edit or add a relationship", [None] + list(lookup), format_func=lambda x: "＋ Add a relationship" if x is None else lookup[x]["kind"] + " · " + lookup[x]["name"], key="knowledge_selected")
    n = lookup.get(ident, {})
    suffix = str(ident) + data["revision_id"]
    with st.form("knowledge_form_" + suffix):
        kinds = ["subsidiary", "product", "agency", "program", "regulation"]
        kind = st.selectbox("Relationship type", kinds, index=kinds.index(n.get("kind", "product")))
        name = st.text_input("Record name", value=n.get("name", ""), max_chars=180)
        aliases = st.text_area("Matchable names (one per line)", value="\n".join(n.get("aliases", [])))
        ids = st.multiselect("Related companies", list(names), default=n.get("entity_ids", []), format_func=lambda x: names[x])
        lane_ids = st.multiselect("Related industries", list(industries), default=n.get("industry_ids", []), format_func=lambda x: industries[x])
        modes = ["direct", "context", "disabled"]
        mode = st.selectbox("Matching behavior", modes, index=modes.index(n.get("match_mode", "context")), format_func=lambda x: {"direct": "Company/product identity", "context": "Research context", "disabled": "Reference only"}[x])
        context = st.text_area("Require one of these context phrases (optional)", value="\n".join(n.get("context_terms", [])))
        note = st.text_area("Relationship evidence and tracking notes", value=n.get("evidence_note", ""), max_chars=4000)
        evidence = st.text_input("Evidence URL or source", value=n.get("evidence_source", ""))
        date = st.text_input("Evidence date", value=n.get("evidence_as_of", ""), placeholder="YYYY-MM-DD")
        st.caption("Use specific product or legal-entity names. Ambiguous short names require sector context. Agencies, programs and regulations must use Research context or Reference only.")
        save = st.form_submit_button("Save relationship", type="primary")
    if save:
        value = dict(kind=kind, name=name, aliases=aliases.splitlines(), entity_ids=ids, industry_ids=lane_ids, match_mode=mode, context_terms=context.splitlines(), evidence_note=note, evidence_source=evidence, evidence_as_of=date)
        if ident:
            value["id"] = ident
        save_change(base, pin, data, {"kind": "knowledge_upsert", "value": value})


def render_government(base, pin, data):
    registry = data["registry"]
    sources = registry.get("external_sources", [])
    industries = {i["id"]: i["name"] for i in registry["industries"]}
    records = {n["id"]: n for n in registry.get("knowledge_nodes", [])}
    health = data.get("government_health", [])
    def last_run(worker):
        return max([h.get("at", "") for h in health if h.get("trigger_kind", "").startswith(worker)], default="")
    st.caption("Government collectors use the shared company, subsidiary and program registry. Procurement queries rotate under fixed daily request limits. A catalog entry is not proof of a successful source check.")
    st.dataframe([{"Source": s["name"], "Worker": s["worker"], "Configuration": s["configuration_status"].replace("_", " "), "Last recorded run": short_time(last_run(s["worker"])), "URL": s["endpoint"]} for s in sources], hide_index=True, use_container_width=True, column_config={"URL": st.column_config.LinkColumn("URL")})
    with st.expander("Collection capacity and recovery", expanded=True):
        for h in sorted(health, key=lambda row: row.get("at", ""), reverse=True):
            try:
                note = json.loads(h.get("note") or "{}")
            except (ValueError, TypeError):
                continue
            worker = h.get("trigger_kind", "")
            if worker == "contracts-watcher:grouped":
                cols = st.columns(3)
                cols[0].metric("Procurement companies", note.get("entity_count", 0))
                cols[1].metric("Provider query groups", note.get("query_groups", 0))
                cols[2].metric("Pages in latest run", note.get("pages_completed", 0))
                st.caption("Procurement checked " + short_time(h.get("at")) + "; oldest search window: " + str(note.get("oldest_window_start") or "unknown"))
                st.write("Daily request ceilings", note.get("provider_limits", {}))
                if note.get("sam_awards") == "missing_credential":
                    st.info("SAM Contract Awards API needs a SAM_API_KEY in contracts-watcher. SAM opportunity CSV collection runs independently.")
                if note.get("errors"):
                    st.warning("Provider retries are waiting; affected page checkpoints remain unchanged.")
                    st.json(note["errors"], expanded=False)
                if note.get("empty_query_entities"):
                    st.warning("Add verified legal names or identifiers for: " + ", ".join(note["empty_query_entities"]))
            elif worker == "sam-bulk-discovery":
                st.write("SAM opportunity snapshot", f"{note.get('next_offset', 0):,} / {note.get('total', 0):,} records processed")
                st.caption("Last batch " + short_time(h.get("at")) + ". Each saved snapshot resumes automatically; old notices baseline and irrelevant procurement subjects are filtered.")
            elif worker == "budget-document-discovery":
                st.write("Official budget documents", f"{note.get('source_count', 0)} indexes · {note.get('new_or_changed_pending', 0)} pending research · {note.get('documents_awaiting_first_fetch', 0)} queued downloads")
                st.caption("Document discovery " + short_time(h.get("at")) + ". The existing worldwide Work budget watch verifies spending and lifecycle changes.")
                failed = [{"Source": key, "Last error": value.get("last_error")} for key, value in note.get("sources", {}).items() if value.get("last_error")]
                if failed:
                    st.dataframe(failed, hide_index=True, use_container_width=True)
        revisions = []
        for h in health:
            try:
                note = json.loads(h.get("note") or "{}")
            except (ValueError, TypeError):
                continue
            revision = note.get("universe_revision")
            if revision:
                registry_status = "Current" if revision == data["revision_id"] else "Git registry snapshot " + revision[:8] if len(revision) == 40 else "Earlier revision; refreshes on next check"
                revisions.append({"Collector": h["trigger_kind"], "Last check": short_time(h.get("at")), "Registry": registry_status})
        if revisions:
            st.dataframe(revisions, hide_index=True, use_container_width=True)
    insider = data.get("insider_health") or {}
    with st.expander("Executive share transactions", expanded=True):
        cols = st.columns(3)
        cols[0].metric("SEC issuers", insider.get("issuer_count", 0))
        cols[1].metric("Filings awaiting parsing", insider.get("pending_count", 0))
        cols[2].metric("Candidates in latest check", insider.get("emitted", 0))
        st.caption("Last check: " + short_time(insider.get("last_tick")))
        if insider.get("last_error"):
            st.warning(insider["last_error"])
        elif not insider.get("last_tick") or overdue(insider["last_tick"], 15):
            st.info("The insider collector is awaiting a recent successful check.")
        st.caption("Forms 4 and 4/A are parsed for executed executive purchases and sales. Grants, withholding, transfers and director-only trades are retained for audit. ChatGPT assesses trade size using disclosed value, holdings and context; there is no fixed automatic cutoff. First checks establish a baseline.")
    if not sources:
        return
    lookup = {s["id"]: s for s in sources}
    selected = st.selectbox("Government source routing", list(lookup), format_func=lambda x: lookup[x]["name"])
    source = lookup[selected]
    supports_extra = selected in ["federal_register", "oira", "agenda", "congress", "govinfo"]
    with st.form("government_source_" + selected + data["revision_id"]):
        lanes = st.multiselect("Industries served", list(industries), default=source["industry_ids"], format_func=lambda x: industries[x])
        linked = st.multiselect("Agency and program records", list(records), default=source.get("knowledge_ids", []), format_func=lambda x: records[x]["name"])
        include = st.text_area("Additional relevance phrases (one per line)", value="\n".join(source["include_terms"]), disabled=not supports_extra)
        if selected == "federal_register":
            st.caption("Federal Register accepts up to 12 additional search phrases within its existing agency scope.")
        exclude = st.text_area("Exclude from additional matching (one per line)", value="\n".join(source["exclude_terms"]), disabled=not supports_extra)
        enabled = st.checkbox("Enable additional relevance matching", value=source.get("matching_enabled", True), disabled=not supports_extra)
        if not supports_extra:
            st.caption("Vendor queries follow shared company/subsidiary names. Other cataloged sources retain their existing collector settings.")
        st.caption("These phrases supplement supported worker matching. Existing legal-status gates, protected source filters, credentials and delivery schedules remain controlled by their collectors.")
        save = st.form_submit_button("Save government routing", type="primary")
    if save:
        save_change(base, pin, data, {"kind": "government_source_update", "value": dict(id=selected, industry_ids=lanes, knowledge_ids=linked, include_terms=include.splitlines(), exclude_terms=exclude.splitlines(), matching_enabled=enabled)})
