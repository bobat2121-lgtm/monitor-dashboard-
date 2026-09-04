"""Pure helpers for dashboard time handling and pipeline health display."""

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Mapping


UTC = timezone.utc
MIN_TIME = datetime.min.replace(tzinfo=UTC)

# The longest scheduled overnight gap is twelve hours. The extra three hours
# absorb normal task/ingestion delay without showing a false alarm overnight.
HEALTHY_REVIEW_HOURS = 15
STALE_REVIEW_HOURS = 26


@dataclass(frozen=True)
class PipelineStatus:
    level: str
    text: str
    detail: str = ""


def parse_time(value: Any) -> datetime:
    """Parse ISO, RFC 2822/RSS, date-only, datetime, or epoch timestamps."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if abs(seconds) > 100_000_000_000:
            seconds /= 1000
        try:
            parsed = datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return MIN_TIME
    else:
        raw = str(value or "").strip()
        if not raw:
            return MIN_TIME

        if raw.replace(".", "", 1).isdigit():
            try:
                return parse_time(float(raw))
            except ValueError:
                pass

        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            try:
                parsed = parsedate_to_datetime(raw)
            except (TypeError, ValueError, OverflowError):
                return MIN_TIME

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def first_valid_time(item: Mapping[str, Any], *fields: str) -> datetime:
    for field in fields:
        parsed = parse_time(item.get(field))
        if parsed != MIN_TIME:
            return parsed
    return MIN_TIME


def rejected_time(item: Mapping[str, Any]) -> datetime:
    """Prefer source time, then fall back to reliable ingestion timestamps."""
    return first_valid_time(
        item,
        "ts",
        "published_at",
        "observed_at",
        "created_at",
        "at",
    )


def sort_rejected(items):
    return sorted(items or [], key=rejected_time, reverse=True)


def relative_time(value: Any, now: datetime | None = None) -> str:
    parsed = parse_time(value)
    if parsed == MIN_TIME:
        return "time unavailable"

    clock = parse_time(now or datetime.now(UTC))
    seconds = max(0, int((clock - parsed).total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _age_hours(value: Any, now: datetime) -> float | None:
    parsed = parse_time(value)
    if parsed == MIN_TIME:
        return None
    return max(0.0, (now - parsed).total_seconds() / 3600)


def _freshness_status(
    timestamp: Any,
    *,
    now: datetime,
    healthy_text: str,
    amber_text: str,
    red_text: str,
    detail: str = "",
) -> PipelineStatus:
    age = _age_hours(timestamp, now)
    when = relative_time(timestamp, now)
    if age is None:
        return PipelineStatus("red", "No successful digest review is recorded", detail)
    if age <= HEALTHY_REVIEW_HOURS:
        return PipelineStatus("green", f"{healthy_text} {when}", detail)
    if age <= STALE_REVIEW_HOURS:
        return PipelineStatus("amber", f"{amber_text} · last success {when}", detail)
    return PipelineStatus("red", f"{red_text} · last success {when}", detail)


def pipeline_status(
    health: Mapping[str, Any] | None,
    latest_post: Mapping[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> PipelineStatus:
    """Turn aggregator health into an honest green/amber/red status.

    A committed review is the liveness clock. That means a successful quiet run
    remains green even when it intentionally publishes no Streamlit edition.
    Older aggregators and an unavailable /health endpoint fall back to the
    latest published digest, but never claim verified green health.
    """
    clock = parse_time(now or datetime.now(UTC))
    latest_post_at = (latest_post or {}).get("posted_at")

    if health:
        overall_status = str(health.get("status") or "").strip().lower()
        if health.get("ok") is False or overall_status == "unhealthy":
            return PipelineStatus("red", "Aggregator reports an unhealthy pipeline")

        stale = health.get("staleness") or {}
        review_at = stale.get("lastReview")
        outcome = str(stale.get("lastOutcome") or "").strip().lower()
        item_count = stale.get("lastItemCount")
        trigger = str(stale.get("lastTriggerLabel") or "").strip()
        unread = health.get("unread")
        details = []
        if trigger:
            details.append(trigger)
        if unread is not None:
            details.append(f"{unread} awaiting review")
        detail = " · ".join(details)

        if parse_time(review_at) != MIN_TIME:
            quiet = outcome in {"reviewed_no_publish", "quiet", "no_publish"} or (
                item_count == 0 and outcome not in {"published", "committed_with_publish"}
            )
            healthy = (
                "Review completed with nothing new to publish"
                if quiet
                else "Digest review completed"
            )
            freshness = _freshness_status(
                review_at,
                now=clock,
                healthy_text=healthy,
                amber_text="Digest review is delayed",
                red_text="Digest review is stale",
                detail=detail,
            )
            # Schema-v6 can be reachable (`ok: true`) while the collector is
            # degraded or a publisher run is still in progress. Degradation is
            # an amber floor, but it must not hide a genuinely stale red review.
            if overall_status == "degraded" and freshness.level == "green":
                return PipelineStatus("amber", "Aggregator reports a degraded pipeline", detail)
            return freshness

        # Compatibility with the pre-v5 health response, where lastPost was the
        # only digest liveness timestamp.
        legacy_post_at = stale.get("lastPost") or latest_post_at
        if parse_time(legacy_post_at) != MIN_TIME:
            status = _freshness_status(
                legacy_post_at,
                now=clock,
                healthy_text="Latest digest published",
                amber_text="No committed review yet",
                red_text="Digest publishing is stale",
                detail=detail,
            )
            if status.level == "green":
                return PipelineStatus("amber", status.text, status.detail)
            return status

        return PipelineStatus("amber", "Aggregator is reachable; awaiting the first committed review", detail)

    if parse_time(latest_post_at) != MIN_TIME:
        age = _age_hours(latest_post_at, clock)
        when = relative_time(latest_post_at, clock)
        if age is not None and age > STALE_REVIEW_HOURS:
            return PipelineStatus("red", f"Health check unavailable · latest digest {when}")
        return PipelineStatus("amber", f"Health check unavailable · latest digest {when}")

    return PipelineStatus("red", "Health check unavailable and no digest history loaded")
