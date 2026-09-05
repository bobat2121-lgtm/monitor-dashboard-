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
    sources = [s for s in data["registry"]["sources"] if entity["id"] in s.get("entity_ids", []) and s.get("source_role") == "company_newsroom"]
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


def coverage_figure(data, industry_id=None, entities=None, selected=None):
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
        for n, source in enumerate(sources):
            status = source_status(source, data)
            node = dict(kind="source", id=source["key"], x=3, y=n * 2, color=BLUE if status == "Collecting" else ORANGE,
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
    notes = st.text_area("What to track", value=(entity or {}).get("tracking_notes", ""), max_chars=4000, key="company_notes_" + suffix)
    if not entity:
        st.caption("New companies join as adjacent comparables. Each company can belong to several industries.")
    if st.button("Save company", key="save_company_" + suffix, type="primary"):
        value = dict(name=name, aliases=[a.strip() for a in aliases.split(",") if a.strip()], memberships=new_memberships, tracking_notes=notes)
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
        name = st.text_input("Source name", value=source.get("name", ""), disabled=protected)
        endpoint = st.text_input("Newsroom or feed URL", value=source.get("endpoint", ""), disabled=protected, placeholder="https://company.com/news/")
        cols = st.columns(2)
        with cols[0]:
            methods = ["auto", "rss", "html", "wp_json"]
            current_method = source.get("adapter", "auto")
            if current_method not in methods:
                methods.append(current_method)
            method = st.selectbox("Collection method", methods, index=methods.index(current_method), disabled=protected,
                                  format_func=lambda x: {"auto": "Detect automatically", "rss": "RSS / Atom", "html": "Newsroom links", "wp_json": "WordPress articles"}.get(x, x))
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
        notes = st.text_area("Source notes", value=source.get("tracking_notes", ""), max_chars=2000)
        st.caption("New sources feed the digest. First checks establish a baseline. Public companies: at most 60 minutes; private companies: at most 120; covered companies: 8 minutes.")
        left, right = st.columns(2)
        preview_clicked = left.form_submit_button("Preview releases", disabled=protected)
        save_clicked = right.form_submit_button("Save source", type="primary")
    inputs = {"endpoint": endpoint.strip(), "adapter": method, "path_prefix": prefix.strip()}
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
        st.dataframe([{"Release": i["title"], "Published": short_time(i.get("published")), "URL": i["url"]} for i in result["items"]],
                     hide_index=True, use_container_width=True, column_config={"URL": st.column_config.LinkColumn("URL")})
        if result.get("undated_count"):
            st.caption("Some releases have no publication date. Their observation time will be recorded separately.")
    if save_clicked:
        value = {"entity_ids": ids, "tracking_notes": notes}
        if source:
            value["key"] = source["key"]
        proof = None
        if not protected:
            chosen = preview["result"]["source"] if matching else {"endpoint": inputs["endpoint"], "adapter": method, "config": {"path_prefix": prefix.strip()}}
            value.update(name=name, endpoint=chosen["endpoint"], adapter=chosen["adapter"], path_prefix=chosen["config"].get("path_prefix", ""),
                         companyStatus=company_state, cadence_minutes=int(cadence), source_role=role, configuration_status=state)
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
    managed_active = any(s.get("managed_by") == "universe" and s.get("configuration_status") == "configured" for s in registry["sources"])
    if managed_active and (not collector.get("last_tick") or overdue(collector["last_tick"], 5) or collector.get("last_error")):
        st.warning("The supplemental collector has not reported a healthy recent check. Saved sources are retained; refresh to check recovery.")
    if collector.get("oldest_due_minutes", 0) > 15:
        st.warning("Some supplemental sources are overdue. Collection capacity needs attention; original source schedules remain independent.")
    next_mode = st.session_state.pop("universe_next_mode", None)
    if next_mode:
        st.session_state["universe_mode"] = next_mode
    mode = st.radio("Universe view", ["Map", "Sources", "History"], horizontal=True, key="universe_mode", label_visibility="collapsed")
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
        entities = [e for e in entities if query in " ".join([e["name"], *e["aliases"]]).lower()]
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
    chart_key = "coverage_map_" + str(industry_id) + str(selected_id) + query + role + str(st.session_state.get("universe_map_nonce", 0))
    event = st.plotly_chart(coverage_figure(data, industry_id, entities, selected), use_container_width=True, key=chart_key,
                           on_select="rerun", selection_mode="points", config={"displayModeBar": False, "scrollZoom": False})
    points = (event.get("selection") or {}).get("points", [])
    if points and points[0].get("customdata"):
        kind, ident = points[0]["customdata"]
        token = (chart_key, kind, ident)
        if st.session_state.get("universe_last_click") != token:
            st.session_state["universe_last_click"] = token
            st.session_state["universe_map_nonce"] = st.session_state.get("universe_map_nonce", 0) + 1
            st.session_state["universe_next_" + kind] = ident
            if kind == "source":
                st.session_state["universe_next_mode"] = "Sources"
            st.rerun()
    st.caption("Select a node to explore. On company and source nodes, cobalt means collecting; orange means coverage needs review.")
    if industry_id and not selected:
        st.caption(f"{len(entities)} matching names. The map shows up to 18 at a time; use search or the company selector to reach every name.")
    if selected:
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
