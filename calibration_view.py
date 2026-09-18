"""Calibration tab: is the reviewer converging on the owner's judgment?

Reads only the aggregator's frozen calibration_* tables through /calibration/*
with the runtime Owner PIN. Writes exactly one thing: this month's audit_log
entry and next month's grading focus.
"""

import html

import plotly.graph_objects as go
import requests
import streamlit as st


STATE_ORDER = {"ignored": 0, "misapplied": 1, "dormant": 2, "working": 3, None: 4}
STATE_COLOR = {"working": "#2f855a", "ignored": "#c05621", "misapplied": "#c53030", "dormant": "#718096", None: "#4a5568"}
SERIES_BLUE = "#3987e5"     # categorical slot 1 (dark surface)
SERIES_ORANGE = "#d95926"   # categorical slot 2 (dark surface)
DIMENSIONS = ["worker", "ticker", "reason_code", "scope", "tab"]


def api(base, pin, path, payload=None):
    headers = {"X-Owner-Pin": pin}
    if payload is None:
        response = requests.get(f"{base}/calibration{path}", headers=headers, timeout=25)
    else:
        response = requests.post(f"{base}/calibration{path}", headers=headers, json=payload, timeout=25)
    try:
        result = response.json()
    except ValueError:
        raise ValueError("The calibration service is temporarily unavailable. Try refreshing.") from None
    if response.status_code == 403:
        raise ValueError("Bad PIN.")
    if response.status_code >= 400 or not result.get("ok"):
        raise ValueError(result.get("error") or "The request could not be completed.")
    return result


def pct(value) -> str:
    return "n/a" if value is None else f"{round(float(value) * 100)}%"


def delta_text(delta) -> str:
    if delta is None:
        return "no prior month to compare"
    points = round(float(delta) * 100)
    return f"{'+' if points >= 0 else ''}{points} pts vs prior month"


def render_headline(summary):
    head = summary.get("headline")
    if not head:
        st.markdown('<div class="empty-state">No calibration month has been computed yet.</div>', unsafe_allow_html=True)
        return
    month = summary.get("latest_month")
    provisional = " · provisional (month not over)" if summary.get("provisional") else ""
    st.markdown(f'<div class="rules-section">{html.escape(str(month))} · headline{html.escape(provisional)}</div>', unsafe_allow_html=True)
    a, b, c, d = st.columns(4)
    a.metric("Action agreement", pct(head.get("action_agreement")), delta_text(head.get("delta")))
    b.metric("Graded / comparable", f"{head.get('n_graded', 0)} / {head.get('n_comparable', 0)}", f"{head.get('n_late', 0)} late (excluded)")
    c.metric("Mean score gap (grader − you)", "n/a" if head.get("mean_score_gap") is None else f"{head['mean_score_gap']:+.1f}")
    d.metric("False neg / false pos", f"{pct(head.get('false_negative_rate'))} / {pct(head.get('false_positive_rate'))}")


def _line(trend, key, title, color, percent=False):
    months = [t["month"] for t in trend]
    values = [None if t.get(key) is None else (t[key] * 100 if percent else t[key]) for t in trend]
    fig = go.Figure(go.Scatter(x=months, y=values, mode="lines+markers", line={"color": color, "width": 2}, marker={"size": 8, "color": color},
                               hovertemplate="%{x}<br>" + title + ": %{y}" + ("%" if percent else "") + "<extra></extra>", connectgaps=False))
    fig.update_layout(title={"text": title, "font": {"size": 13}}, height=240, margin={"l": 40, "r": 16, "t": 40, "b": 32},
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font={"color": "#c3c2b7"}, showlegend=False,
                      xaxis={"showgrid": False, "type": "category"}, yaxis={"gridcolor": "rgba(255,255,255,.08)", "zeroline": True, "zerolinecolor": "rgba(255,255,255,.2)", "ticksuffix": "%" if percent else ""})
    return fig


def render_trend(summary):
    trend = summary.get("trend") or []
    if len(trend) < 1:
        return
    st.markdown('<div class="rules-section">Trend since inception</div>', unsafe_allow_html=True)
    left, right = st.columns(2)
    left.plotly_chart(_line(trend, "action_agreement", "Action agreement", SERIES_BLUE, percent=True), use_container_width=True)
    right.plotly_chart(_line(trend, "mean_score_gap", "Mean score gap (grader − you)", SERIES_ORANGE), use_container_width=True)
    with st.expander("Trend as a table"):
        st.table([{"month": t["month"], "agreement": pct(t.get("action_agreement")), "score gap": t.get("mean_score_gap"), "graded": t.get("n_graded"), "disagreements": t.get("n_disagreements")} for t in trend])


def dimension_rows(rows):
    return [{"dimension": r["dimension"], "value": r["dimension_value"], "graded": r.get("n_graded"), "comparable": r.get("n_comparable"),
             "disagreements": r.get("n_disagreements"), "agreement": pct(r.get("action_agreement")), "score gap": r.get("mean_score_gap")} for r in rows]


def render_worst_and_improved(summary):
    left, right = st.columns(2)
    with left:
        st.markdown('<div class="rules-section">Worst three by disagreements</div>', unsafe_allow_html=True)
        worst = summary.get("worst") or []
        st.table(dimension_rows(worst)) if worst else st.caption("No disagreements recorded.")
    with right:
        st.markdown('<div class="rules-section">Most improved vs prior month</div>', unsafe_allow_html=True)
        improved = summary.get("most_improved") or []
        if improved:
            st.table([{**row, "prior": pct(r.get("prior_action_agreement")), "delta": delta_text(r.get("delta"))} for row, r in zip(dimension_rows(improved), improved)])
        else:
            st.caption("Needs two months with three or more comparable grades in the same dimension.")


def render_rules(summary):
    rules = summary.get("rules") or []
    added = set(summary.get("rules_added_last_month") or [])
    st.markdown(f'<div class="rules-section">Rules · {summary.get("latest_month")} · sorted ignored → misapplied → dormant → working</div>', unsafe_allow_html=True)
    only_added = st.checkbox("Only rules added last month", key="cal_only_added")
    shown = [r for r in rules if not only_added or r["rule_id"] in added]
    if not shown:
        st.caption("No rules to show." if not only_added else "No rules were added last month.")
        return
    rows = "".join(
        '<div class="rule-row">'
        f'<div class="rule-head"><span class="rule-id">{html.escape(str(r["rule_id"]))}</span>'
        f'<span class="rule-badge" style="background:{STATE_COLOR.get(r.get("state"), STATE_COLOR[None])}">{html.escape(r.get("state") or "no data yet")}</span>'
        + ('<span class="rule-meta">added last month</span>' if r["rule_id"] in added else "")
        + "</div>"
        f'<div class="rule-meta">cited {r.get("cited", 0)} · applicable {r.get("applicable", 0)} · agreement when cited {pct(r.get("agreement_when_cited"))} · '
        f'when applicable but not cited {pct(r.get("agreement_when_applicable_not_cited"))}</div>'
        "</div>"
        for r in shown
    )
    st.markdown('<div class="rules-list">' + rows + "</div>", unsafe_allow_html=True)
    if all(r.get("state") is None for r in rules):
        st.caption("States appear from the first month in which the reviewer cites rules (decisions v2). Until then only applicability is counted.")


def render_drilldown(base, pin, summary):
    month = summary.get("latest_month")
    if not month:
        return
    st.markdown('<div class="rules-section">Drill down</div>', unsafe_allow_html=True)
    months = summary.get("months") or [month]
    a, b, c = st.columns(3)
    sel_month = a.selectbox("Month", months, index=len(months) - 1, key="cal_dd_month")
    dimension = b.selectbox("Dimension", DIMENSIONS, key="cal_dd_dimension")
    try:
        rows = api(base, pin, f"/month?month={sel_month}")["dimensions"]
    except ValueError as exc:
        st.error(str(exc))
        return
    values = [r["dimension_value"] for r in rows if r["dimension"] == dimension]
    if not values:
        c.caption("No rows for that dimension.")
        return
    value = c.selectbox("Value", values, key="cal_dd_value")
    try:
        grades = api(base, pin, f"/drilldown?month={sel_month}&dimension={dimension}&value={requests.utils.quote(str(value), safe='')}")["grades"]
    except ValueError as exc:
        st.error(str(exc))
        return
    if not grades:
        st.caption("No grades.")
        return
    st.table([
        {"id": g["id"], "event": g.get("event_id"), "title": (g.get("title") or "")[:80], "your score": g.get("target_score"), "your action": g.get("owner_action"),
         "your reason": g.get("reason_code"), "grader score": g.get("grader_score"), "grader action": g.get("grader_action"), "grader reason": g.get("grader_reason_code"),
         "agree": "" if g.get("agree") is None else ("yes" if g["agree"] else "no"), "late": "late" if g.get("late") else "", "note": (g.get("note") or "")[:120]}
        for g in grades
    ])


def render_audit(base, pin, summary):
    prior = summary.get("prior_audit")
    latest_audit = summary.get("latest_audit")
    month = summary.get("latest_month")
    if prior:
        st.markdown(f'<div class="rules-section">Prior month audit · {html.escape(str(summary.get("prior_month")))}</div>'
                    f'<div class="rule-row"><div class="rule-text">{html.escape(prior.get("summary") or "")}</div>'
                    f'<div class="rule-meta">Focus: {html.escape(prior.get("focus") or "none")}</div></div>', unsafe_allow_html=True)
    if latest_audit:
        st.markdown(f'<div class="rules-section">This month\'s audit · {html.escape(str(month))}</div>'
                    f'<div class="rule-row"><div class="rule-text">{html.escape(latest_audit.get("summary") or "")}</div>'
                    f'<div class="rule-meta">Focus: {html.escape(latest_audit.get("focus") or "none")}</div></div>', unsafe_allow_html=True)
    if not month:
        return
    with st.form("audit_form", border=True):
        st.markdown(f'<div class="rules-section">Write the {html.escape(str(month))} audit</div>', unsafe_allow_html=True)
        summary_text = st.text_area("Conclusions", key="audit_summary", height=110, placeholder="What the disagreements were about: rule ignored, rule missing, or your own inconsistency.")
        focus = st.text_area("Next month's grading focus (becomes a standing instruction for the reviewer)", key="audit_focus", height=70)
        if st.form_submit_button("Save audit", type="primary"):
            if len(summary_text.strip()) < 10:
                st.info("Write at least a sentence of conclusions.")
            else:
                try:
                    result = api(base, pin, "/audit", {"month": month, "summary": summary_text.strip(), "focus": focus.strip()})
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    extra = f" · standing instruction #{result['standing_instruction_id']}" if result.get("standing_instruction_id") else ""
                    st.success(f"Audit #{result.get('id')} saved for {month}{extra}")


def render_calibration_view(base):
    pin = str(st.session_state.get("grader_pin", "")).strip()
    if not pin:
        st.markdown('<div class="empty-state">Open Owner mode and enter the grader PIN to see calibration.</div>', unsafe_allow_html=True)
        return
    try:
        summary = api(base, pin, "/summary")
    except ValueError as exc:
        st.error(str(exc))
        return
    render_headline(summary)
    render_trend(summary)
    render_worst_and_improved(summary)
    render_rules(summary)
    render_drilldown(base, pin, summary)
    render_audit(base, pin, summary)
