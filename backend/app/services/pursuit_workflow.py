"""
Pursuit workflow: run the next-step preparation actions for an opportunity
that a human has decided to move forward (Pursue / Watchlist).

This is deliberately user-triggered. It never runs automatically across all
scraped opportunities, and the batch entry point requires an explicit review
status and a bounded limit so public sites are not hammered.

Steps are run in order; each step's errors are captured and the workflow
continues where it safely can. The local AI being unavailable is recorded as
a clean per-step error and does not fail the whole run.
"""

from datetime import UTC, datetime

from sqlmodel import select

from app.models import Document, Opportunity
from app.services.ai_evaluator import (
    LOCAL_AI_UNAVAILABLE,
    evaluate_opportunity_with_local_ai,
)
from app.services.downloader import download_documents_for_opportunity
from app.services.logistics_extractor import apply_logistics_to_opportunity
from app.services.logistics_qa import run_logistics_qa
from app.services.parser import parse_documents_for_opportunity
from app.services.portal_document_downloader import (
    download_portal_documents_headed,
    portal_document_download_available,
)
from app.services.requirement_extractor import extract_requirements_with_local_ai
from app.services.scraper import discover_documents_for_opportunity

STEP_DISCOVER = "discover_documents"
STEP_DOWNLOAD = "download_documents"
STEP_PORTAL_DOWNLOAD = "download_portal_documents"
STEP_PARSE = "parse_documents"
STEP_AI = "ai_evaluate"
STEP_REQUIREMENTS = "extract_requirements"
STEP_LOGISTICS = "extract_logistics"
STEP_LOGISTICS_QA = "logistics_qa"

DEFAULT_STEPS = [
    STEP_DISCOVER,
    STEP_DOWNLOAD,
    STEP_PORTAL_DOWNLOAD,
    STEP_PARSE,
    STEP_AI,
    STEP_REQUIREMENTS,
    STEP_LOGISTICS,
    STEP_LOGISTICS_QA,
]
VALID_STEPS = set(DEFAULT_STEPS)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def run_pursuit_prep(opportunity_id: int, session, steps: list[str] | None = None) -> dict:
    requested = list(steps) if steps else list(DEFAULT_STEPS)
    summary = {
        "opportunity_id": opportunity_id,
        "title": None,
        "steps_requested": requested,
        "step_results": [],
        "final_status": "ok",
        "next_action": None,
        "errors": [],
    }

    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        summary["final_status"] = "error"
        summary["errors"].append("Opportunity not found")
        return summary
    summary["title"] = opportunity.title

    metrics = {
        "documents_discovered": 0,
        "documents_downloaded": 0,
        "documents_parsed": 0,
        "requirements_extracted": 0,
        "ai_evaluated": False,
        "logistics_extracted": False,
        "logistics_qa_ran": False,
    }

    for step in requested:
        if step not in VALID_STEPS:
            summary["step_results"].append(
                {"step": step, "status": "skipped", "summary": "Unknown step", "errors": []}
            )
            summary["errors"].append(f"Unknown step: {step}")
            continue
        result = _run_step(step, opportunity_id, session, metrics)
        summary["step_results"].append(result)
        if result["status"] == "error":
            summary["errors"].extend(result["errors"])

    downloaded_total, pending_total = _document_counts(session, opportunity_id)
    next_action = _decide_next_action(metrics, downloaded_total, pending_total)

    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is not None:
        opportunity.next_action = next_action
        opportunity.updated_at = _utc_now()
        session.add(opportunity)
        session.commit()

    summary["next_action"] = next_action
    summary["metrics"] = metrics
    if summary["errors"] and summary["final_status"] != "error":
        summary["final_status"] = "completed_with_errors"
    return summary


def run_pursuit_prep_for_status(
    status: str, session, steps: list[str] | None = None, limit: int = 10
) -> dict:
    limit = max(1, int(limit))
    matching = list(
        session.exec(
            select(Opportunity)
            .where(Opportunity.review_status == status)
            .order_by(Opportunity.id)
        ).all()
    )
    matched_count = len(matching)
    selected = matching[:limit]
    truncated = matched_count > limit

    batch = {
        "status": status,
        "limit": limit,
        "matched_count": matched_count,
        "processed_count": len(selected),
        "truncated": truncated,
        "warning": None,
        "results": [],
    }
    if truncated:
        batch["warning"] = (
            f"{matched_count} opportunities match status '{status}'; "
            f"only the first {limit} were processed. Re-run with a higher "
            f"--limit to process more."
        )

    for opportunity in selected:
        batch["results"].append(run_pursuit_prep(opportunity.id, session, steps))
    return batch


def _run_step(step: str, opportunity_id: int, session, metrics: dict) -> dict:
    try:
        if step == STEP_DISCOVER:
            result = discover_documents_for_opportunity(opportunity_id, session)
            metrics["documents_discovered"] += result.get("documents_discovered", 0)
            errors = result.get("errors", [])
            return _step_result(
                step,
                "ok" if not errors else "error",
                f"{result.get('documents_discovered', 0)} new links, "
                f"{result.get('documents_skipped', 0)} already known",
                errors,
            )

        if step == STEP_DOWNLOAD:
            result = download_documents_for_opportunity(opportunity_id, session)
            metrics["documents_downloaded"] += result.get("downloaded_count", 0)
            errors = result.get("errors", [])
            return _step_result(
                step,
                "ok" if not errors else "error",
                f"{result.get('downloaded_count', 0)} downloaded, "
                f"{result.get('skipped_count', 0)} skipped",
                errors,
            )

        if step == STEP_PORTAL_DOWNLOAD:
            opportunity = session.get(Opportunity, opportunity_id)
            available = (
                portal_document_download_available(opportunity, session)
                if opportunity is not None
                else {"available": False, "reason": "Opportunity not found"}
            )
            if not available["available"]:
                return _step_result(
                    step,
                    "skipped",
                    available["reason"],
                    [],
                )
            result = download_portal_documents_headed(opportunity_id, session)
            metrics["documents_downloaded"] += result.get("downloaded_count", 0)
            errors = result.get("errors", [])
            return _step_result(
                step,
                "ok" if not errors else "error",
                f"{result.get('downloaded_count', 0)} portal document(s) downloaded, "
                f"{result.get('skipped_count', 0)} skipped",
                errors,
            )

        if step == STEP_PARSE:
            result = parse_documents_for_opportunity(opportunity_id, session)
            metrics["documents_parsed"] += result.get("parsed_count", 0)
            errors = result.get("errors", [])
            return _step_result(
                step,
                "ok" if not errors else "error",
                f"{result.get('parsed_count', 0)} parsed, "
                f"{result.get('skipped_count', 0)} skipped, "
                f"{result.get('failed_count', 0)} failed",
                errors,
            )

        if step == STEP_AI:
            result = evaluate_opportunity_with_local_ai(opportunity_id, session)
            if result.get("error"):
                return _step_result(step, "error", result["error"], [result["error"]])
            metrics["ai_evaluated"] = True
            evaluation = result.get("evaluation")
            recommendation = getattr(evaluation, "recommendation", None)
            return _step_result(step, "ok", f"AI recommendation: {recommendation}", [])

        if step == STEP_REQUIREMENTS:
            result = extract_requirements_with_local_ai(opportunity_id, session)
            if result.get("error"):
                return _step_result(step, "error", result["error"], [result["error"]])
            count = result.get("requirements_count", 0)
            metrics["requirements_extracted"] += count
            return _step_result(step, "ok", f"{count} requirements extracted", [])

        if step == STEP_LOGISTICS:
            result = apply_logistics_to_opportunity(opportunity_id, session)
            if result.get("error"):
                return _step_result(step, "error", result["error"], [result["error"]])
            metrics["logistics_extracted"] = True
            return _step_result(step, "ok", "Logistics extracted", [])

        if step == STEP_LOGISTICS_QA:
            result = run_logistics_qa(opportunity_id, session)
            if result.get("error"):
                return _step_result(step, "error", result["error"], [result["error"]])
            metrics["logistics_qa_ran"] = True
            return _step_result(
                step,
                "ok",
                f"Logistics QA: {result.get('qa_status')} ({result.get('risk_level')} risk)",
                [],
            )

        return _step_result(step, "skipped", "Unknown step", [])
    except Exception as exc:  # defensive: a step failure must not crash the run
        return _step_result(step, "error", f"Step raised: {exc}", [str(exc)])


def _step_result(step: str, status: str, summary: str, errors: list[str]) -> dict:
    return {"step": step, "status": status, "summary": summary, "errors": errors}


def _document_counts(session, opportunity_id: int) -> tuple[int, int]:
    documents = list(
        session.exec(
            select(Document).where(Document.opportunity_id == opportunity_id)
        ).all()
    )
    downloaded = sum(1 for d in documents if d.path)
    pending = sum(1 for d in documents if not d.path)
    return downloaded, pending


def _decide_next_action(metrics: dict, downloaded_total: int, pending_total: int) -> str:
    # No documents found anywhere: the portal likely hides them behind JS/login.
    if downloaded_total == 0 and pending_total == 0:
        return "Verify Portal"
    if metrics["requirements_extracted"] > 0:
        return "Review Requirements"
    return "Manual Review"
