"""
One-command daily intake: scrape enabled sources, score all opportunities, and
build a notification digest. Scraping reuses the same per-source helper the
`scrape-enabled-sources` CLI command uses; scoring reuses the rules-based
scorer. Factored so it can be tested offline by skipping the scrape step.
"""

from datetime import UTC, datetime

from sqlmodel import select

from app.models import Opportunity, SourceConfig
from app.services.notifications import build_digest
from app.services.scorer import apply_scored_review_status, score_opportunity_text


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _scrape_enabled_sources(session) -> dict:
    """Scrape all enabled sources, reusing the CLI's run_scrape_for_source.

    Imported lazily to avoid a circular import (cli imports services).
    Per-source failures are recorded and do not abort the run; run_scrape_for_source
    already persists the failed ScrapeRun before re-raising.
    """
    from app.cli import run_scrape_for_source

    sources = list(
        session.exec(select(SourceConfig).where(SourceConfig.enabled == True)).all()
    )
    summary = {
        "sources_scraped": 0,
        "created": 0,
        "updated": 0,
        "skipped_duplicates": 0,
        "errors": [],
        "per_source": [],
    }
    for source in sources:
        try:
            result = run_scrape_for_source(source)
        except Exception as exc:  # noqa: BLE001 - keep going on per-source failure
            summary["errors"].append(f"{source.name}: {exc}")
            summary["per_source"].append(
                {"source": source.name, "status": "failed", "error": str(exc)}
            )
            continue
        summary["sources_scraped"] += 1
        summary["created"] += result.get("created_count", 0)
        summary["updated"] += result.get("updated_count", 0)
        summary["skipped_duplicates"] += result.get("skipped_duplicates", 0)
        if result.get("errors"):
            summary["errors"].extend(
                f"{source.name}: {err}" for err in result["errors"]
            )
        summary["per_source"].append(
            {
                "source": source.name,
                "status": "completed",
                "created": result.get("created_count", 0),
                "updated": result.get("updated_count", 0),
            }
        )
    return summary


def _score_all(session) -> int:
    opportunities = list(session.exec(select(Opportunity)).all())
    for opportunity in opportunities:
        scoring_result = score_opportunity_text(opportunity)
        opportunity.bid_score = scoring_result["score"]
        opportunity.bid_decision = scoring_result["decision"]
        opportunity.bid_reason = scoring_result["reason"]
        apply_scored_review_status(opportunity, scoring_result["suggested_review_status"])
        opportunity.updated_at = _utc_now()
        session.add(opportunity)
    session.commit()
    return len(opportunities)


def daily_run(session, do_scrape: bool = True, days: int = 7) -> dict:
    """Run the daily intake pipeline and return a structured summary."""
    scrape_summary: dict = {"skipped": True}
    if do_scrape:
        scrape_summary = _scrape_enabled_sources(session)

    scored = _score_all(session)
    digest = build_digest(session, days=days)

    return {
        "scrape": scrape_summary,
        "scored": scored,
        "digest": digest,
    }
