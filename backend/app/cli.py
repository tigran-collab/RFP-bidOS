import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import typer
from sqlmodel import Session, select

from app.config import get_settings
from app.db import engine, init_db
from app.models import Document, Opportunity, ScrapeRun, SourceConfig
from app.schemas import OpportunityCreate, OpportunityUpdate
from app.services.ai_evaluator import evaluate_opportunity_with_local_ai
from app.services.downloader import download_documents_for_opportunity
from app.services.ollama_client import list_ollama_models
from app.services.parser import (
    parse_all_documents,
    parse_document,
    parse_documents_for_opportunity,
)
from app.services.requirement_extractor import extract_requirements_with_local_ai
from app.services.scraper import (
    discover_documents_for_opportunity,
    preview_source,
    scrape_source,
)
from app.seed_sources import seed_real_sources
from app.services.scrapers.socrata_discovery import (
    discover_socrata_sources,
    seed_discovered_sources,
)
from app.services.scrapers.capabilities import get_source_scraper_capabilities
from app.services.dashboard import get_operations_dashboard
from app.services.exports import (
    export_deadlines_ics,
    export_documents_csv,
    export_logistics_qa_csv,
    export_opportunities_csv,
    export_requirements_csv,
)
from app.services.notifications import build_digest, render_digest_text
from app.services.logistics_extractor import (
    apply_logistics_all,
    apply_logistics_for_status,
    apply_logistics_to_opportunity,
)
from app.services.logistics_qa import (
    run_logistics_qa,
    run_logistics_qa_for_status,
)
from app.services.pursuit_workflow import (
    run_pursuit_prep,
    run_pursuit_prep_for_status,
)
from app.services.scorer import apply_scored_review_status, score_opportunity_text
from app.services.source_credentials import (
    CREDENTIAL_TYPE_KEYRING,
    update_source_auth_status,
)
from app.services import credential_store
from app.services.scrapers.portal_templates import get_template, list_templates

cli = typer.Typer(help="RFP BidOS backend commands.")


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@cli.command("init-db")
def init_database() -> None:
    init_db()
    typer.echo("Database initialized")


@cli.command("backup-db")
def backup_db_command(
    output_dir: str = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Directory for the backup. Defaults to <db folder>/backups.",
    ),
) -> None:
    """Write a timestamped, consistent snapshot of the local SQLite database.

    Uses SQLite's online backup API so it is safe to run while the app is
    running. This protects the irreplaceable triage/scoring/review data, which
    lives only in the local .db file and is intentionally not in git.
    """
    import sqlite3

    settings = get_settings()
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        typer.echo("backup-db only supports local SQLite databases.")
        raise typer.Exit(code=1)

    db_path = Path(url.replace("sqlite:///", "", 1))
    if not db_path.exists():
        typer.echo(f"Database file not found: {db_path}. Run init-db first.")
        raise typer.Exit(code=1)

    dest_dir = Path(output_dir) if output_dir else db_path.parent / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().strftime("%Y%m%d_%H%M%S")
    dest_path = dest_dir / f"{db_path.stem}_{stamp}.db"

    source = sqlite3.connect(str(db_path))
    try:
        destination = sqlite3.connect(str(dest_path))
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()

    size_kb = dest_path.stat().st_size / 1024
    typer.echo(f"Backup written: {dest_path} ({size_kb:.1f} KB)")


@cli.command("seed-demo")
def seed_demo() -> None:
    init_db()
    demo_opportunities = [
        Opportunity(
            title="Strong security opportunity",
            agency="City Facilities Department",
            solicitation_number="DEMO-SEC-001",
            source="demo",
            source_url="https://example.com/opportunities/demo-sec-001",
            location="Local",
            service_type="Security services",
            contract_type="Fixed price",
            estimated_value=250000.0,
            bid_decision="bid",
            bid_score=92.0,
            bid_reason="Strong fit for core security capabilities.",
            status="demo",
        ),
        Opportunity(
            title="As-needed low-priority security opportunity",
            agency="County Procurement Office",
            solicitation_number="DEMO-SEC-002",
            source="demo",
            source_url="https://example.com/opportunities/demo-sec-002",
            location="Regional",
            service_type="As-needed security services",
            contract_type="On-call",
            estimated_value=50000.0,
            bid_decision="review",
            bid_score=48.0,
            bid_reason="Security related, but low priority and uncertain volume.",
            status="demo",
        ),
        Opportunity(
            title="Non-security opportunity",
            agency="Public Works Department",
            solicitation_number="DEMO-NONSEC-001",
            source="demo",
            source_url="https://example.com/opportunities/demo-nonsec-001",
            location="Local",
            service_type="Landscaping",
            contract_type="Fixed price",
            estimated_value=75000.0,
            bid_decision="no-bid",
            bid_score=10.0,
            bid_reason="Outside security service scope.",
            status="demo",
        ),
    ]
    demo_sources = [
        SourceConfig(
            name="Demo Public Procurement Page",
            source_type="public_page",
            base_url="https://example.com",
            enabled=False,
            notes="Placeholder public scraper source",
        ),
        SourceConfig(
            name="Demo City Procurement Placeholder",
            source_type="public_page",
            base_url="https://example.com/procurement",
            enabled=False,
            notes="Disabled placeholder for future public procurement testing",
        ),
        SourceConfig(
            name="Demo County Bids Placeholder",
            source_type="public_page",
            base_url="https://example.com/bids",
            enabled=False,
            notes="Disabled placeholder for future public bid page testing",
        ),
        SourceConfig(
            name="Demo BidNet Future Auth Placeholder",
            source_type="public_page",
            base_url="https://www.bidnetdirect.com",
            enabled=False,
            requires_credentials=True,
            credential_type="Future Secret Store",
            credential_secret_ref="future:bidnet",
            credential_notes=(
                "BidNet credentials will be added in a future authenticated-source phase."
            ),
            auth_status="Unsupported This Phase",
            portal_type="BidNet",
            notes="Authenticated BidNet scraping is intentionally not implemented yet.",
        ),
        # Disabled PlanetBids assisted-login template. Replace the placeholder
        # cid with a real agency/company id, run `set-credentials` and
        # `portal-login`, then enable it. No real credentials or cid are seeded.
        SourceConfig(
            name="Demo PlanetBids Assisted-Login Template",
            source_type="planetbids",
            base_url="https://vendors.planetbids.com/portal/00000/bo/bo-search",
            login_url="https://vendors.planetbids.com/portal/00000/bo/bo-search",
            enabled=False,
            requires_credentials=True,
            credential_type="Keyring",
            portal_type="PlanetBids",
            config_json=json.dumps(
                {
                    "cid": 0,
                    "api_base": "https://api-external.prod.planetbids.com",
                    "bids_path": "/papi/bids",
                    "params": {"per_page": 100, "page": 1},
                    "portal_bid_url_template": (
                        "https://vendors.planetbids.com/portal/{cid}/bo/bo-detail/{bid_id}"
                    ),
                    "agency": "Example Agency",
                    "field_map": {
                        "id": "id",
                        "title": "title",
                        "solicitation_number": "bidNumber",
                        "due_date": "dueDate",
                        "description": "description",
                    },
                }
            ),
            notes=(
                "Assisted-login PlanetBids template (disabled). Set the real cid "
                "in config_json, run set-credentials and portal-login, then enable."
            ),
        ),
    ]

    with Session(engine) as session:
        opportunities_created = 0
        for opportunity in demo_opportunities:
            statement = select(Opportunity).where(
                Opportunity.solicitation_number == opportunity.solicitation_number
            )
            existing = session.exec(statement).first()
            if existing is None:
                session.add(opportunity)
                opportunities_created += 1

        sources_created = 0
        for source in demo_sources:
            statement = select(SourceConfig).where(SourceConfig.name == source.name)
            existing = session.exec(statement).first()
            if existing is None:
                session.add(source)
                sources_created += 1
            elif source.requires_credentials:
                existing.requires_credentials = source.requires_credentials
                existing.credential_type = source.credential_type
                existing.credential_secret_ref = source.credential_secret_ref
                existing.credential_notes = source.credential_notes
                existing.auth_status = source.auth_status
                existing.portal_type = source.portal_type
                session.add(existing)
        session.commit()

    typer.echo(
        "Demo seed complete: "
        f"{opportunities_created} opportunities created, "
        f"{sources_created} sources created"
    )


@cli.command("seed-sources")
def seed_sources_command() -> None:
    """Seed curated real public procurement sources for CA, TX, NV, and AZ."""
    init_db()
    with Session(engine) as session:
        result = seed_real_sources(session)
    typer.echo(
        f"Source seed complete: {result['created']} created, "
        f"{result['updated']} updated, "
        f"{result['skipped_existing']} already present, "
        f"{result['total_curated']} curated total"
    )


@cli.command("discover-socrata-sources")
def discover_socrata_sources_command(
    query: str = typer.Option(
        None,
        "--query",
        help="Comma-separated catalog query terms (overrides the defaults).",
    ),
    limit: int = typer.Option(20, "--limit", help="Max datasets per query term."),
    states: str = typer.Option(
        None,
        "--states",
        help="Comma-separated state codes to keep (e.g. CA,TX,NV,AZ). "
        "Filters out other geographies before probing.",
    ),
    no_probe: bool = typer.Option(
        False, "--no-probe", help="Skip per-dataset column probing."
    ),
    seed: bool = typer.Option(
        False,
        "--seed",
        help="Seed procurement candidates as DISABLED socrata sources.",
    ),
) -> None:
    """Discover candidate procurement datasets from the Socrata catalog.

    Without --seed, prints a table of candidates. With --seed, inserts each
    procurement candidate not already configured as a DISABLED socrata source
    for human verification (field maps are best-guess and must be checked).
    """
    import json as _json

    queries = None
    if query:
        queries = [part.strip() for part in query.split(",") if part.strip()]

    state_codes = None
    if states:
        state_codes = [part.strip() for part in states.split(",") if part.strip()]

    candidates = discover_socrata_sources(
        queries=queries,
        limit_per_query=limit,
        probe=not no_probe,
        states=state_codes,
    )
    procurement = [c for c in candidates if c.get("is_procurement")]
    others = [c for c in candidates if not c.get("is_procurement")]

    if not seed:
        typer.echo(
            f"Discovered {len(candidates)} gov candidate(s): "
            f"{len(procurement)} procurement, {len(others)} other"
        )
        typer.echo("\n== Procurement candidates ==")
        if not procurement:
            typer.echo("  (none)")
        for candidate in procurement:
            state_tag = (
                f"{'/'.join(candidate.get('states') or [])} | "
                if candidate.get("states")
                else ""
            )
            typer.echo(
                f"  [{candidate['domain']}] {candidate['dataset_id']} | "
                f"{state_tag}{candidate['name'][:60]}"
            )
            typer.echo(
                f"      field_map: {_json.dumps(candidate.get('suggested_field_map') or {})}"
            )
            if candidate.get("probe_error"):
                typer.echo(f"      probe_error: {candidate['probe_error']}")
        typer.echo("\n== Other gov candidates (not procurement-shaped) ==")
        if not others:
            typer.echo("  (none)")
        for candidate in others:
            note = (
                f" probe_error: {candidate['probe_error']}"
                if candidate.get("probe_error")
                else ""
            )
            typer.echo(
                f"  [{candidate['domain']}] {candidate['dataset_id']} | "
                f"{candidate['name'][:60]}{note}"
            )
        return

    init_db()
    with Session(engine) as session:
        result = seed_discovered_sources(session, candidates)

    typer.echo(
        f"Seed complete: {result['created']} created (disabled), "
        f"{result['skipped']} already present "
        f"({len(procurement)} procurement candidate(s) considered)"
    )


def _parse_cli_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise typer.BadParameter(f"Could not parse date: {value} (use YYYY-MM-DD)")


@cli.command("add-opportunity")
def add_opportunity_command(
    title: str = typer.Option(..., "--title", help="Opportunity title (required)"),
    agency: str = typer.Option(None, "--agency"),
    solicitation_number: str = typer.Option(None, "--solicitation-number"),
    source: str = typer.Option(None, "--source"),
    source_url: str = typer.Option(None, "--source-url"),
    portal_url: str = typer.Option(None, "--portal-url"),
    location: str = typer.Option(None, "--location"),
    service_type: str = typer.Option(None, "--service-type"),
    contract_type: str = typer.Option(None, "--contract-type"),
    estimated_value: float = typer.Option(None, "--estimated-value"),
    due_date: str = typer.Option(None, "--due-date", help="YYYY-MM-DD"),
    q_and_a_deadline: str = typer.Option(None, "--q-and-a-deadline", help="YYYY-MM-DD"),
    pre_bid_date: str = typer.Option(None, "--pre-bid-date", help="YYYY-MM-DD"),
    submission_method: str = typer.Option(None, "--submission-method"),
    submission_portal: str = typer.Option(None, "--submission-portal"),
    description: str = typer.Option(None, "--description"),
    notes: str = typer.Option(None, "--notes"),
    review_status: str = typer.Option(None, "--review-status"),
    priority: str = typer.Option(None, "--priority"),
    next_action: str = typer.Option(None, "--next-action"),
) -> None:
    init_db()
    payload = OpportunityCreate(
        title=title,
        agency=agency,
        solicitation_number=solicitation_number,
        source=source or "Manual",
        source_url=source_url,
        portal_url=portal_url,
        location=location,
        service_type=service_type,
        contract_type=contract_type,
        estimated_value=estimated_value,
        due_date=_parse_cli_date(due_date),
        q_and_a_deadline=_parse_cli_date(q_and_a_deadline),
        pre_bid_date=_parse_cli_date(pre_bid_date),
        submission_method=submission_method,
        submission_portal=submission_portal,
        description=description,
        notes=notes,
        review_status=review_status or "New",
        priority=priority,
        next_action=next_action,
    )
    opportunity = Opportunity(**payload.model_dump())
    opportunity.created_at = utc_now()
    opportunity.updated_at = utc_now()
    with Session(engine) as session:
        session.add(opportunity)
        session.commit()
        session.refresh(opportunity)
        typer.echo(
            f"Created opportunity [{opportunity.id}] {opportunity.title} "
            f"(source={opportunity.source}, review={opportunity.review_status})"
        )


@cli.command("update-opportunity")
def update_opportunity_command(
    opportunity_id: int,
    title: str = typer.Option(None, "--title"),
    agency: str = typer.Option(None, "--agency"),
    solicitation_number: str = typer.Option(None, "--solicitation-number"),
    source_url: str = typer.Option(None, "--source-url"),
    portal_url: str = typer.Option(None, "--portal-url"),
    location: str = typer.Option(None, "--location"),
    service_type: str = typer.Option(None, "--service-type"),
    contract_type: str = typer.Option(None, "--contract-type"),
    estimated_value: float = typer.Option(None, "--estimated-value"),
    due_date: str = typer.Option(None, "--due-date", help="YYYY-MM-DD"),
    q_and_a_deadline: str = typer.Option(None, "--q-and-a-deadline", help="YYYY-MM-DD"),
    pre_bid_date: str = typer.Option(None, "--pre-bid-date", help="YYYY-MM-DD"),
    submission_method: str = typer.Option(None, "--submission-method"),
    submission_portal: str = typer.Option(None, "--submission-portal"),
    description: str = typer.Option(None, "--description"),
    notes: str = typer.Option(None, "--notes"),
    review_status: str = typer.Option(None, "--review-status"),
    priority: str = typer.Option(None, "--priority"),
    next_action: str = typer.Option(None, "--next-action"),
    review_notes: str = typer.Option(None, "--review-notes"),
) -> None:
    raw = {
        "title": title,
        "agency": agency,
        "solicitation_number": solicitation_number,
        "source_url": source_url,
        "portal_url": portal_url,
        "location": location,
        "service_type": service_type,
        "contract_type": contract_type,
        "estimated_value": estimated_value,
        "due_date": _parse_cli_date(due_date),
        "q_and_a_deadline": _parse_cli_date(q_and_a_deadline),
        "pre_bid_date": _parse_cli_date(pre_bid_date),
        "submission_method": submission_method,
        "submission_portal": submission_portal,
        "description": description,
        "notes": notes,
        "review_status": review_status,
        "priority": priority,
        "next_action": next_action,
        "review_notes": review_notes,
    }
    provided = {key: value for key, value in raw.items() if value is not None}
    if not provided:
        typer.echo("No fields provided to update", err=True)
        raise typer.Exit(code=1)

    # Validate choice fields through the schema.
    OpportunityUpdate(**provided)

    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            typer.echo(f"Opportunity not found: {opportunity_id}", err=True)
            raise typer.Exit(code=1)
        for key, value in provided.items():
            setattr(opportunity, key, value)
        opportunity.updated_at = utc_now()
        session.add(opportunity)
        session.commit()
        session.refresh(opportunity)
        typer.echo(
            f"Updated opportunity [{opportunity.id}] {opportunity.title} "
            f"({len(provided)} field(s) changed; review={opportunity.review_status})"
        )


@cli.command("attach-document-url")
def attach_document_url_command(
    opportunity_id: int,
    url: str = typer.Option(..., "--url", help="Document URL (http/https)"),
    label: str = typer.Option(None, "--label", help="Document label"),
) -> None:
    clean = (url or "").strip()
    if not (clean.lower().startswith("http://") or clean.lower().startswith("https://")):
        typer.echo("URL must start with http:// or https://", err=True)
        raise typer.Exit(code=1)

    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            typer.echo(f"Opportunity not found: {opportunity_id}", err=True)
            raise typer.Exit(code=1)
        existing = session.exec(
            select(Document).where(
                Document.opportunity_id == opportunity_id,
                Document.source_url == clean,
            )
        ).first()
        if existing is not None:
            typer.echo(f"Document URL already attached (document {existing.id})")
            return
        suffix = Path(unquote(urlparse(clean).path)).suffix.lower().lstrip(".") or None
        filename = label or Path(unquote(urlparse(clean).path)).name or "document"
        document = Document(
            opportunity_id=opportunity_id,
            filename=filename,
            path="",
            file_type=suffix,
            source_url=clean,
            parsed_status="Not Downloaded",
        )
        session.add(document)
        session.commit()
        session.refresh(document)
        typer.echo(
            f"Attached document [{document.id}] {document.filename} to opportunity {opportunity_id}"
        )


@cli.command("score-opportunity")
def score_opportunity(opportunity_id: int) -> None:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            typer.echo(f"Opportunity not found: {opportunity_id}", err=True)
            raise typer.Exit(code=1)

        scoring_result = score_opportunity_text(opportunity)
        opportunity.bid_score = scoring_result["score"]
        opportunity.bid_decision = scoring_result["decision"]
        opportunity.bid_reason = scoring_result["reason"]
        apply_scored_review_status(opportunity, scoring_result["suggested_review_status"])
        opportunity.updated_at = utc_now()

        session.add(opportunity)
        session.commit()

        typer.echo(f"Score: {scoring_result['score']}")
        typer.echo(f"Decision: {scoring_result['decision']}")
        typer.echo(f"Reason: {scoring_result['reason']}")


@cli.command("score-all-opportunities")
def score_all_opportunities() -> None:
    with Session(engine) as session:
        opportunities = list(session.exec(select(Opportunity)).all())
        for opportunity in opportunities:
            scoring_result = score_opportunity_text(opportunity)
            opportunity.bid_score = scoring_result["score"]
            opportunity.bid_decision = scoring_result["decision"]
            opportunity.bid_reason = scoring_result["reason"]
            apply_scored_review_status(opportunity, scoring_result["suggested_review_status"])
            opportunity.updated_at = utc_now()
            session.add(opportunity)
            typer.echo(
                f"{opportunity.title}: {scoring_result['decision']} "
                f"({scoring_result['score']})"
            )
        session.commit()


def _echo_logistics(result: dict) -> None:
    if result.get("error"):
        typer.echo(result["error"])
        return
    typer.echo(f"[{result['opportunity_id']}] {result.get('title') or '-'}")
    typer.echo(f"  due date: {result.get('due_date') or '-'}")
    typer.echo(f"  Q&A deadline: {result.get('q_and_a_deadline') or '-'}")
    typer.echo(f"  pre-bid date: {result.get('pre_bid_date') or '-'}")
    typer.echo(f"  pre-bid mandatory: {result.get('pre_bid_mandatory')}")
    typer.echo(f"  submission method: {result.get('submission_method') or '-'}")
    typer.echo(f"  submission portal: {result.get('submission_portal') or '-'}")
    typer.echo(f"  required forms: {result.get('required_forms_summary') or '-'}")
    typer.echo(f"  deadline risk: {result.get('deadline_risk') or '-'}")
    typer.echo(f"  confidence: {result.get('logistics_confidence_score')}")
    if result.get("logistics_notes"):
        typer.echo(f"  notes: {result['logistics_notes']}")


@cli.command("extract-logistics")
def extract_logistics_command(opportunity_id: int) -> None:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            typer.echo(f"Opportunity not found: {opportunity_id}", err=True)
            raise typer.Exit(code=1)
        result = apply_logistics_to_opportunity(opportunity_id, session)
    _echo_logistics(result)


@cli.command("extract-logistics-by-status")
def extract_logistics_by_status_command(
    status: str = typer.Option(..., "--status", help="Review status, e.g. Pursue"),
    limit: int = typer.Option(10, "--limit", help="Max opportunities to process"),
) -> None:
    with Session(engine) as session:
        batch = apply_logistics_for_status(status, session, limit=limit)
    typer.echo(
        f"{batch['label']}: {batch['matched_count']} matched, "
        f"{batch['processed_count']} processed (limit {batch['limit']})"
    )
    if batch.get("warning"):
        typer.echo(f"WARNING: {batch['warning']}")
    for result in batch["results"]:
        _echo_logistics(result)


@cli.command("extract-logistics-all")
def extract_logistics_all_command(
    limit: int = typer.Option(25, "--limit", help="Max opportunities to process"),
) -> None:
    with Session(engine) as session:
        batch = apply_logistics_all(session, limit=limit)
    typer.echo(
        f"{batch['label']}: {batch['matched_count']} matched, "
        f"{batch['processed_count']} processed (limit {batch['limit']})"
    )
    if batch.get("warning"):
        typer.echo(f"WARNING: {batch['warning']}")
    for result in batch["results"]:
        _echo_logistics(result)


def _echo_logistics_qa(result: dict) -> None:
    if result.get("error"):
        typer.echo(result["error"])
        return
    typer.echo(f"[{result['opportunity_id']}] {result.get('title') or '-'}")
    typer.echo(f"  QA status: {result.get('qa_status')}")
    typer.echo(f"  risk level: {result.get('risk_level')}")
    typer.echo(f"  summary: {result.get('summary')}")
    for issue in result.get("issues", []):
        typer.echo(f"  - issue [{issue['risk']}]: {issue['issue']}")
    for action in result.get("recommended_actions", []):
        typer.echo(f"  -> action: {action}")


@cli.command("logistics-qa")
def logistics_qa_command(opportunity_id: int) -> None:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            typer.echo(f"Opportunity not found: {opportunity_id}", err=True)
            raise typer.Exit(code=1)
        result = run_logistics_qa(opportunity_id, session)
    _echo_logistics_qa(result)


@cli.command("logistics-qa-by-status")
def logistics_qa_by_status_command(
    status: str = typer.Option(..., "--status", help="Review status, e.g. Pursue"),
    limit: int = typer.Option(10, "--limit", help="Max opportunities to process"),
) -> None:
    with Session(engine) as session:
        batch = run_logistics_qa_for_status(status, session, limit=limit)
    typer.echo(
        f"Status '{batch['status']}': {batch['matched_count']} matched, "
        f"{batch['processed_count']} processed (limit {batch['limit']})"
    )
    if batch.get("warning"):
        typer.echo(f"WARNING: {batch['warning']}")
    for result in batch["results"]:
        _echo_logistics_qa(result)


def _write_export(content: str, output: str) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")
    # Row count excludes the header line.
    row_count = max(0, content.count("\n") - 1) if content else 0
    typer.echo(f"Wrote {row_count} row(s) to {path}")


@cli.command("export-opportunities")
def export_opportunities_command(
    output: str = typer.Option("exports/opportunities.csv", "--output"),
    review_status: str = typer.Option(None, "--review-status"),
    priority: str = typer.Option(None, "--priority"),
) -> None:
    with Session(engine) as session:
        content = export_opportunities_csv(
            session, filters={"review_status": review_status, "priority": priority}
        )
    _write_export(content, output)


@cli.command("export-requirements")
def export_requirements_command(
    output: str = typer.Option("exports/requirements.csv", "--output"),
    opportunity_id: int = typer.Option(None, "--opportunity-id"),
) -> None:
    with Session(engine) as session:
        content = export_requirements_csv(session, opportunity_id=opportunity_id)
    _write_export(content, output)


@cli.command("export-documents")
def export_documents_command(
    output: str = typer.Option("exports/documents.csv", "--output"),
    opportunity_id: int = typer.Option(None, "--opportunity-id"),
) -> None:
    with Session(engine) as session:
        content = export_documents_csv(session, opportunity_id=opportunity_id)
    _write_export(content, output)


@cli.command("export-logistics-qa")
def export_logistics_qa_command(
    output: str = typer.Option("exports/logistics_qa.csv", "--output"),
    opportunity_id: int = typer.Option(None, "--opportunity-id"),
) -> None:
    with Session(engine) as session:
        content = export_logistics_qa_csv(session, opportunity_id=opportunity_id)
    _write_export(content, output)


@cli.command("export-deadlines")
def export_deadlines_command(
    output: str = typer.Option("exports/deadlines.ics", "--output"),
    opportunity_id: int = typer.Option(None, "--opportunity-id"),
) -> None:
    """Export bid/Q&A/pre-bid deadlines as an RFC 5545 .ics calendar."""
    with Session(engine) as session:
        content = export_deadlines_ics(session, opportunity_id=opportunity_id)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")
    event_count = content.count("BEGIN:VEVENT")
    typer.echo(f"Wrote {event_count} event(s) to {path}")


@cli.command("digest")
def digest_command(
    days: int = typer.Option(7, "--days", help="Look-back/look-ahead window in days"),
    limit: int = typer.Option(50, "--limit", help="Max items per section"),
) -> None:
    """Print a notification digest of new, upcoming, and at-risk opportunities."""
    with Session(engine) as session:
        digest = build_digest(session, days=days, limit=limit)
    typer.echo(render_digest_text(digest))


@cli.command("daily-run")
def daily_run_command(
    days: int = typer.Option(7, "--days", help="Digest window in days"),
    skip_scrape: bool = typer.Option(
        False, "--skip-scrape", help="Skip scraping enabled sources (offline)"
    ),
) -> None:
    """Scrape enabled sources, score all opportunities, and print a digest."""
    from app.services.daily_run import daily_run

    with Session(engine) as session:
        result = daily_run(session, do_scrape=not skip_scrape, days=days)

    scrape = result["scrape"]
    if scrape.get("skipped"):
        typer.echo("Scrape: skipped")
    else:
        typer.echo(
            f"Scrape: {scrape['sources_scraped']} source(s), "
            f"{scrape['created']} created, {scrape['updated']} updated, "
            f"{scrape['skipped_duplicates']} skipped duplicates, "
            f"{len(scrape['errors'])} error(s)"
        )
        for err in scrape["errors"]:
            typer.echo(f"  error: {err}")
    typer.echo(f"Scored: {result['scored']} opportunity(ies)")
    typer.echo("")
    typer.echo(render_digest_text(result["digest"]))


@cli.command("dashboard")
def dashboard_command() -> None:
    """Print a concise operations dashboard."""
    with Session(engine) as session:
        data = get_operations_dashboard(session)

    counts = data["counts"]
    typer.echo("== Counts ==")
    typer.echo(
        f"  total={counts['total_opportunities']} | new={counts['new']} | "
        f"needs_review={counts['needs_review']} | pursue={counts['pursue']} | "
        f"watchlist={counts['watchlist']} | do_not_pursue={counts['do_not_pursue']} | "
        f"archived={counts['archived']}"
    )
    typer.echo(
        f"  docs: pending_download={counts['documents_pending_download']} | "
        f"downloaded={counts['documents_downloaded']} | "
        f"parsed={counts['documents_parsed']} | "
        f"parse_failed={counts['documents_parse_failed']} | "
        f"requirements={counts['requirements_extracted']}"
    )
    typer.echo(
        f"  sources: enabled={counts['sources_enabled']} | "
        f"requiring_credentials={counts['sources_requiring_credentials']}"
    )
    typer.echo(
        f"  deadlines: high_risk={counts['deadline_risk_high']} | "
        f"past_due={counts['deadline_past_due']} | "
        f"missing={counts['deadline_missing']}"
    )
    typer.echo(
        f"  logistics QA: needs_review={counts['logistics_qa_needs_review']} | "
        f"failed={counts['logistics_qa_failed']} | "
        f"missing_critical={counts['missing_critical_logistics']}"
    )

    typer.echo("\n== Upcoming Deadlines (next 30 days) ==")
    deadlines = data["upcoming_deadlines"]
    if not deadlines:
        typer.echo("  (none)")
    for item in deadlines[:10]:
        due = (item["due_date"] or "")[:10]
        typer.echo(
            f"  [{item['id']}] {item['title'][:50]:50} | due {due} | "
            f"{item['review_status']} | score {item['bid_score'] if item['bid_score'] is not None else '-'}"
        )

    typer.echo("\n== Top Opportunities ==")
    for item in data["top_opportunities"][:5]:
        typer.echo(
            f"  [{item['id']}] {item['title'][:50]:50} | {item['review_status']} | "
            f"score {item['bid_score'] if item['bid_score'] is not None else '-'} | "
            f"AI {item['ai_recommendation'] or '-'}"
        )

    typer.echo("\n== Needs Action ==")
    needs = data["needs_action"]
    if not needs:
        typer.echo("  (none)")
    for item in needs[:10]:
        typer.echo(
            f"  [{item['id']}] {item['title'][:50]:50} | {item['reason']} "
            f"-> {item['suggested_action'] or '-'}"
        )


REVIEW_STATUS_ORDER = {
    "Pursue": 0,
    "Needs Review": 1,
    "New": 2,
    "Watchlist": 3,
    "Do Not Pursue": 4,
    "Archived": 5,
}


@cli.command("review-queue")
def review_queue_command(
    status: str = typer.Option(None, "--status", help="Filter by review status"),
    priority: str = typer.Option(None, "--priority", help="Filter by priority"),
) -> None:
    with Session(engine) as session:
        opportunities = list(session.exec(select(Opportunity)).all())

    if status:
        opportunities = [
            o for o in opportunities if (o.review_status or "New") == status
        ]
    if priority:
        opportunities = [o for o in opportunities if (o.priority or "") == priority]

    if not opportunities:
        typer.echo("No opportunities in the review queue match the filters")
        return

    opportunities.sort(
        key=lambda o: (
            REVIEW_STATUS_ORDER.get(o.review_status or "New", 2),
            0 if o.due_date else 1,
            o.due_date or datetime.max,
            -(o.bid_score if o.bid_score is not None else -1e9),
            -(o.created_at or datetime.min).timestamp(),
        )
    )

    for opp in opportunities:
        due = opp.due_date.strftime("%Y-%m-%d") if opp.due_date else "-"
        agency = opp.agency or opp.source or "-"
        typer.echo(
            f"[{opp.id}] {opp.title[:50]:50} | {agency[:24]:24} | due {due} | "
            f"score {opp.bid_score if opp.bid_score is not None else '-'} | "
            f"{opp.bid_decision or '-'} | review={opp.review_status or 'New'} | "
            f"priority={opp.priority or '-'} | next={opp.next_action or '-'}"
        )


@cli.command("mark-opportunity")
def mark_opportunity_command(
    opportunity_id: int,
    status: str = typer.Option(None, "--status", help="New review status"),
    notes: str = typer.Option(None, "--notes", help="Review notes"),
    priority: str = typer.Option(None, "--priority", help="Priority"),
    next_action: str = typer.Option(None, "--next-action", help="Next action"),
    reviewed_by: str = typer.Option(None, "--reviewed-by", help="Reviewer name"),
) -> None:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            typer.echo(f"Opportunity not found: {opportunity_id}", err=True)
            raise typer.Exit(code=1)

        if status is not None:
            opportunity.review_status = status
        if notes is not None:
            opportunity.review_notes = notes
        if priority is not None:
            opportunity.priority = priority
        if next_action is not None:
            opportunity.next_action = next_action
        if reviewed_by is not None:
            opportunity.reviewed_by = reviewed_by
        opportunity.reviewed_at = utc_now()
        opportunity.updated_at = utc_now()

        session.add(opportunity)
        session.commit()
        session.refresh(opportunity)

        typer.echo(
            f"[{opportunity.id}] {opportunity.title}: "
            f"review={opportunity.review_status or 'New'}, "
            f"priority={opportunity.priority or '-'}, "
            f"next={opportunity.next_action or '-'}"
        )


def _parse_steps(steps: str | None) -> list[str] | None:
    if not steps:
        return None
    return [part.strip() for part in steps.split(",") if part.strip()]


def _echo_pursuit_summary(summary: dict) -> None:
    typer.echo(
        f"[{summary['opportunity_id']}] {summary.get('title') or '-'}: "
        f"{summary['final_status']} | next={summary.get('next_action') or '-'}"
    )
    for step in summary.get("step_results", []):
        typer.echo(f"  - {step['step']}: {step['status']} - {step['summary']}")
    if summary.get("errors"):
        typer.echo(f"  errors: {'; '.join(summary['errors'])}")


@cli.command("pursuit-prep")
def pursuit_prep_command(
    opportunity_id: int,
    steps: str = typer.Option(
        None, "--steps", help="Comma-separated steps (default: all five steps)"
    ),
) -> None:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            typer.echo(f"Opportunity not found: {opportunity_id}", err=True)
            raise typer.Exit(code=1)
        summary = run_pursuit_prep(opportunity_id, session, steps=_parse_steps(steps))
    _echo_pursuit_summary(summary)


@cli.command("pursuit-prep-by-status")
def pursuit_prep_by_status_command(
    status: str = typer.Option(..., "--status", help="Review status, e.g. Pursue or Watchlist"),
    limit: int = typer.Option(10, "--limit", help="Max opportunities to process"),
    steps: str = typer.Option(None, "--steps", help="Comma-separated steps"),
) -> None:
    with Session(engine) as session:
        batch = run_pursuit_prep_for_status(
            status, session, steps=_parse_steps(steps), limit=limit
        )

    typer.echo(
        f"Status '{batch['status']}': {batch['matched_count']} matched, "
        f"{batch['processed_count']} processed (limit {batch['limit']})"
    )
    if batch.get("warning"):
        typer.echo(f"WARNING: {batch['warning']}")
    for summary in batch["results"]:
        _echo_pursuit_summary(summary)


@cli.command("scrape-source")
def scrape_source_command(source_id: int) -> None:
    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            typer.echo(f"Source not found: {source_id}", err=True)
            raise typer.Exit(code=1)
        if not source.enabled:
            typer.echo(f"Source is disabled: {source.name}", err=True)
            raise typer.Exit(code=1)

    result = run_scrape_for_source(source)
    _echo_scrape_result(source.name, result)


@cli.command("scrape-enabled-sources")
def scrape_enabled_sources_command() -> None:
    with Session(engine) as session:
        sources = list(
            session.exec(select(SourceConfig).where(SourceConfig.enabled == True)).all()
        )

    if not sources:
        typer.echo("No enabled sources to scrape")
        return

    for source in sources:
        result = run_scrape_for_source(source)
        _echo_scrape_result(source.name, result)


@cli.command("preview-source")
def preview_source_command(
    source_id: int,
    show_filtered: bool = typer.Option(
        False,
        "--show-filtered",
        help="Also show candidates rejected by quality or relevance filters",
    ),
) -> None:
    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            typer.echo(f"Source not found: {source_id}", err=True)
            raise typer.Exit(code=1)

    result = preview_source(source, include_filtered=show_filtered)
    _echo_scrape_result(source.name, result)
    for diagnostic in result.get("diagnostics", []):
        typer.echo(f"{source.name} diagnostic: {diagnostic}")
    for candidate in result.get("candidates", [])[:10]:
        typer.echo(
            f"- {candidate['title']} | due: {candidate.get('due_date') or '-'} | "
            f"quality: {candidate.get('quality_score')} | "
            f"documents: {candidate.get('document_count')} | "
            f"doc links: {candidate.get('document_candidate_count')}"
        )
        for doc in (candidate.get("document_candidates") or [])[:3]:
            typer.echo(
                f"    doc [{doc['confidence_score']}] {doc['label'][:60]} -> {doc['url']}"
            )


@cli.command("preview-enabled-sources")
def preview_enabled_sources_command(
    detail_limit: int = typer.Option(3, help="Max detail pages fetched per source"),
    top: int = typer.Option(5, help="Top candidate titles to print per source"),
    show_filtered: bool = typer.Option(
        False, "--show-filtered", help="Also show candidates rejected by the quality filter"
    ),
) -> None:
    """Smoke-test all enabled sources without saving opportunities."""
    with Session(engine) as session:
        sources = list(
            session.exec(select(SourceConfig).where(SourceConfig.enabled == True)).all()
        )

    if not sources:
        typer.echo("No enabled sources to preview")
        return

    for source in sources:
        try:
            result = preview_source(
                source, detail_limit=detail_limit, include_filtered=show_filtered
            )
        except Exception as exc:
            typer.echo(f"{source.name}: preview failed ({exc})")
            continue

        typer.echo(
            f"{source.name} [{source.state or '-'} | {source.portal_type or '-'}]: "
            f"{result.get('total_candidates_found', 0)} found, "
            f"{result.get('candidates_filtered_quality', 0)} quality filtered, "
            f"{result.get('candidates_filtered_relevance', 0)} relevance filtered, "
            f"{result.get('relevant', 0)} relevant, "
            f"{result.get('maybe_relevant', 0)} maybe, "
            f"{result.get('as_needed_warning_count', 0)} as-needed warnings, "
            f"{result.get('candidates_kept', 0)} kept, "
            f"{len(result['errors'])} errors"
        )
        for candidate in result.get("candidates", [])[:top]:
            matches = ", ".join(candidate.get("keyword_matches") or []) or "-"
            warning = " | AS-NEEDED WARNING" if candidate.get("as_needed_warning") else ""
            typer.echo(
                f"  - {candidate['title'][:90]} "
                f"({candidate.get('relevance_decision') or '-'} "
                f"{candidate.get('relevance_score')}, "
                f"matches: {matches}{warning}, "
                f"quality: {candidate.get('quality_score')}, "
                f"docs: {candidate.get('document_count')}, "
                f"doc links: {candidate.get('document_candidate_count')})"
            )
            for doc in (candidate.get("document_candidates") or [])[:3]:
                typer.echo(
                    f"      doc [{doc['confidence_score']}] {doc['label'][:60]} -> {doc['url']}"
                )
        reasons = result.get("filter_reasons") or {}
        if reasons:
            summary = ", ".join(f"{reason} x{count}" for reason, count in reasons.items())
            typer.echo(f"  filter reasons: {summary}")
        if result["errors"]:
            typer.echo(f"  errors: {'; '.join(result['errors'])}")


def _keyring_ref_for_source(source: SourceConfig) -> str:
    return source.credential_secret_ref or f"rfp-bidos:{source.id}"


@cli.command("set-credentials")
def set_credentials_command(
    source_id: int,
    username: str = typer.Option(..., "--username", "-u", help="Portal login username"),
) -> None:
    """Store a source's portal password in the OS keychain (never the DB).

    Prompts for the password without echoing it, stores it in the OS keychain
    under a per-source reference, and records only the username + reference +
    credential type on the SourceConfig. The password is never written to the
    database, printed, or logged.
    """
    if not credential_store.is_available():
        typer.echo(
            "OS keychain (keyring) is not available. Install it with "
            "`pip install keyring` and ensure your OS keychain is accessible.",
            err=True,
        )
        raise typer.Exit(code=1)

    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            typer.echo(f"Source not found: {source_id}", err=True)
            raise typer.Exit(code=1)

        ref = _keyring_ref_for_source(source)
        # hide_input=True prevents the password from being echoed to the terminal.
        password = typer.prompt("Portal password", hide_input=True)
        store_result = credential_store.set_password(ref, username, password)
        # Do not keep the plaintext around any longer than needed.
        del password
        if not store_result["ok"]:
            typer.echo(store_result["message"], err=True)
            raise typer.Exit(code=1)

        source.credential_username = username
        source.credential_secret_ref = ref
        source.credential_type = CREDENTIAL_TYPE_KEYRING
        source.requires_credentials = True
        session.add(source)
        session.commit()
        session.refresh(source)
        result = update_source_auth_status(source.id, session)

    typer.echo(
        f"Stored credentials for '{source.name}' in the OS keychain "
        f"(username={username}, ref={ref}). Password not saved to the database."
    )
    _echo_auth_status(result)


@cli.command("portal-login")
def portal_login_command(
    source_id: int,
    timeout: int = typer.Option(
        180, "--timeout", help="Seconds to wait for you to finish logging in"
    ),
) -> None:
    """Open a visible browser to log in to a source's portal (assisted login).

    You complete the login (and any CAPTCHA / MFA) in the opened window. The
    authenticated session is persisted to a local browser profile and reused by
    later scrapes. Re-run this when the session expires. The username/password
    are pre-filled from the OS keychain when available; nothing is submitted
    automatically.
    """
    from app.services.scrapers import browser_session
    from app.services.scrapers.planetbids import profile_dir_for_source

    if not browser_session.playwright_available():
        typer.echo(
            "Playwright is not installed. Run `pip install -r requirements.txt` "
            "then `playwright install chromium` (one-time) before using "
            "portal-login.",
            err=True,
        )
        raise typer.Exit(code=1)

    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            typer.echo(f"Source not found: {source_id}", err=True)
            raise typer.Exit(code=1)

        portal_url = source.login_url or source.base_url
        if not portal_url:
            typer.echo(
                f"Source '{source.name}' has no login_url or base_url to open.",
                err=True,
            )
            raise typer.Exit(code=1)

        username = source.credential_username
        password = None
        if username and source.credential_secret_ref:
            password = credential_store.get_password(
                source.credential_secret_ref, username
            )
        profile_dir = profile_dir_for_source(source)
        config = _load_source_config(source)
        success_substr = config.get("success_url_substring")

    typer.echo(
        f"Opening a browser for '{source.name}' at {portal_url}.\n"
        "Complete the login (and any CAPTCHA/MFA) in the window that opens. "
        "The window closes automatically once login is detected, or you can "
        "close it when done."
    )
    result = browser_session.assisted_login(
        portal_url,
        profile_dir,
        prefill_username=username,
        prefill_password=password,
        success_url_substring=success_substr,
        timeout_seconds=timeout,
    )
    # Drop the plaintext password reference promptly.
    del password
    typer.echo(result["message"])
    if not result["ok"]:
        raise typer.Exit(code=1)


@cli.command("portal-fetch-debug")
def portal_fetch_debug_command(
    source_id: int,
    url: str = typer.Option(None, "--url", help="Page to fetch; defaults to the source's config list_url"),
    out: str = typer.Option(None, "--out", help="Where to save the rendered HTML"),
    headed: bool = typer.Option(
        True, "--headed/--headless", help="Reuse the session in a visible window (default) or headless"
    ),
) -> None:
    """Fetch a logged-in page via the persisted session and save the rendered HTML.

    Diagnostic aid: reuses the source's browser profile to fetch a page (a
    solicitations/search results URL), writing the rendered HTML to a file so
    the list/row/field selectors can be finalized — or so a WAF 403 vs. a real
    page can be told apart. Uses a visible window by default (`--headless` to
    hide). Nothing is submitted; this only reads a page you can already see.
    """
    from app.services.scrapers import browser_session
    from app.services.scrapers.planetbids import profile_dir_for_source

    if not browser_session.playwright_available():
        typer.echo("Playwright not installed; run pip install + playwright install chromium.", err=True)
        raise typer.Exit(code=1)

    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            typer.echo(f"Source not found: {source_id}", err=True)
            raise typer.Exit(code=1)
        config = _load_source_config(source)
        page_url = url or config.get("list_url")
        profile_dir = profile_dir_for_source(source)

    if not page_url or "TODO" in str(page_url):
        typer.echo("No usable URL. Pass --url with the logged-in solicitations page.", err=True)
        raise typer.Exit(code=1)

    out_path = Path(out) if out else Path("data") / f"portal_debug_{source_id}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    typer.echo(f"Fetching {page_url} via the saved session ({'visible' if headed else 'headless'})...")
    try:
        result = browser_session.capture_page(page_url, profile_dir, headless=not headed)
    except browser_session.SessionExpiredError as exc:
        typer.echo(f"No session: {exc}", err=True)
        raise typer.Exit(code=1)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Fetch failed: {exc}", err=True)
        raise typer.Exit(code=1)

    html = result.get("html") or ""
    out_path.write_text(html, encoding="utf-8")
    typer.echo(f"HTTP {result.get('status')} | final URL: {result.get('final_url')}")
    typer.echo(f"Title: {result.get('title')!r}")
    typer.echo(f"Saved {len(html)} chars to {out_path}")
    typer.echo(f"First 300 chars: {html[:300]!r}")


def _slug_for_name(name: str) -> str:
    slug = "".join(char if char.isalnum() else "-" for char in (name or "").lower())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "portal"


def add_portal_source(
    session: Session,
    *,
    name: str,
    template: str | None = None,
    source_type: str | None = None,
    login_url: str | None = None,
    list_url: str | None = None,
    portal_type: str | None = None,
) -> dict:
    """Create a DISABLED, credential-requiring SourceConfig for a new portal.

    Two modes:
      * template: prefill source_type/login_url/portal_type/config_json from the
        portal catalog.
      * explicit: pass source_type + login_url (and optional list_url) directly.

    The credential_secret_ref is derived from the name (keyring service). The
    source is created disabled with requires_credentials=True and
    credential_type=Keyring so the operator runs set-credentials + portal-login
    before enabling. Returns a summary dict; never stores any password.
    """
    if not name:
        raise ValueError("name is required")

    existing = session.exec(
        select(SourceConfig).where(SourceConfig.name == name)
    ).first()

    config_json: str | None = None
    if template:
        tpl = get_template(template)
        if tpl is None:
            raise ValueError(
                f"Unknown template '{template}'. "
                f"Available: {', '.join(t['slug'] for t in list_templates())}"
            )
        source_type = source_type or tpl["source_type"]
        login_url = login_url or tpl.get("login_url")
        portal_type = portal_type or tpl.get("portal_type")
        skeleton = tpl.get("config_json") or {}
        # If the caller supplied a list_url, drop it into the skeleton.
        if list_url and isinstance(skeleton, dict):
            skeleton = {**skeleton, "list_url": list_url}
        config_json = json.dumps(skeleton) if skeleton else None
    else:
        if not source_type:
            raise ValueError("source-type is required without a template")
        if not login_url:
            raise ValueError("login-url is required without a template")
        if list_url:
            config_json = json.dumps({"list_url": list_url})

    # A deterministic keyring service reference derived from the name so each
    # portal keeps its own keychain entry. The actual password lives only in the
    # OS keychain, added later via set-credentials.
    secret_ref = f"rfp-bidos:{_slug_for_name(name)}"

    source = SourceConfig(
        name=name,
        source_type=source_type,
        base_url=login_url,
        login_url=login_url,
        enabled=False,
        requires_credentials=True,
        credential_type=CREDENTIAL_TYPE_KEYRING,
        credential_secret_ref=secret_ref,
        auth_status="Not Configured",
        portal_type=portal_type,
        config_json=config_json,
        notes=(
            "Authenticated portal added via add-portal (disabled). Run "
            "set-credentials, portal-login, finalize config_json selectors, "
            "then enable."
        ),
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    return {
        "source_id": source.id,
        "name": source.name,
        "source_type": source.source_type,
        "credential_secret_ref": source.credential_secret_ref,
        "existing_warning": (
            f"A source named '{name}' already exists (id={existing.id}); "
            "created another. Consider removing the duplicate."
            if existing is not None
            else None
        ),
    }


@cli.command("list-portal-templates")
def list_portal_templates_command() -> None:
    """Print the available portal templates for add-portal."""
    templates = list_templates()
    typer.echo(f"{len(templates)} portal template(s):")
    for tpl in templates:
        typer.echo(
            f"  {tpl['slug']:14} {tpl['display_name']:40} "
            f"[{tpl['source_type']}]"
        )


@cli.command("add-portal")
def add_portal_command(
    name: str = typer.Option(..., "--name", help="Source display name (required)"),
    template: str = typer.Option(
        None, "--template", help="Template slug (see list-portal-templates)"
    ),
    source_type: str = typer.Option(
        None, "--source-type", help="Explicit source type (without a template)"
    ),
    login_url: str = typer.Option(
        None, "--login-url", help="Portal login URL (without a template)"
    ),
    list_url: str = typer.Option(
        None, "--list-url", help="Bids list URL (fills config_json.list_url)"
    ),
) -> None:
    """Create a DISABLED authenticated portal source, from a template or args.

    Sets requires_credentials=True, credential_type=Keyring, and a per-source
    keychain reference. No password is stored here. Echoes the next steps.
    """
    init_db()
    with Session(engine) as session:
        try:
            result = add_portal_source(
                session,
                name=name,
                template=template,
                source_type=source_type,
                login_url=login_url,
                list_url=list_url,
            )
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1)

    if result["existing_warning"]:
        typer.echo(f"WARNING: {result['existing_warning']}")
    source_id = result["source_id"]
    typer.echo(
        f"Created disabled portal source [{source_id}] {result['name']} "
        f"(source_type={result['source_type']}, "
        f"credential ref={result['credential_secret_ref']})."
    )
    typer.echo("Next steps:")
    typer.echo(f"  1. python -m app.cli set-credentials {source_id} --username you@example.com")
    typer.echo(f"  2. python -m app.cli portal-login {source_id}")
    typer.echo(
        "  3. Finalize config_json (list_url / row_selector / field_map) from "
        "your logged-in session if needed."
    )
    typer.echo(
        f"  4. Enable the source (set enabled=True via the API/DB), then "
        f"python -m app.cli scrape-source {source_id}."
    )


@cli.command("portal-login-all")
def portal_login_all_command(
    timeout: int = typer.Option(
        180, "--timeout", help="Seconds to wait for each login"
    ),
) -> None:
    """Run assisted login sequentially for every enabled credential source.

    Each portal opens its own visible browser window. To avoid stacking many
    windows at once, this pauses for confirmation between portals.
    """
    from app.services.scrapers import browser_session
    from app.services.scrapers.planetbids import profile_dir_for_source

    if not browser_session.playwright_available():
        typer.echo(
            "Playwright is not installed. Run `pip install -r requirements.txt` "
            "then `playwright install chromium` (one-time) before using "
            "portal-login-all.",
            err=True,
        )
        raise typer.Exit(code=1)

    with Session(engine) as session:
        sources = list(
            session.exec(
                select(SourceConfig).where(
                    SourceConfig.enabled == True,  # noqa: E712
                    SourceConfig.requires_credentials == True,  # noqa: E712
                )
            ).all()
        )

    if not sources:
        typer.echo("No enabled credential-requiring sources to log in to.")
        return

    typer.echo(f"{len(sources)} portal(s) to log in to, one window at a time.")
    for index, source in enumerate(sources, start=1):
        portal_url = source.login_url or source.base_url
        if not portal_url:
            typer.echo(f"  [{source.id}] {source.name}: no login_url/base_url; skipping.")
            continue

        if index > 1:
            typer.confirm(
                f"Ready to open the login window for '{source.name}'?",
                default=True,
                abort=False,
            )

        username = source.credential_username
        password = None
        if username and source.credential_secret_ref:
            password = credential_store.get_password(
                source.credential_secret_ref, username
            )
        profile_dir = profile_dir_for_source(source)
        success_substr = _load_source_config(source).get("success_url_substring")

        typer.echo(f"Opening login for [{source.id}] {source.name} at {portal_url}")
        result = browser_session.assisted_login(
            portal_url,
            profile_dir,
            prefill_username=username,
            prefill_password=password,
            success_url_substring=success_substr,
            timeout_seconds=timeout,
        )
        del password
        typer.echo(f"  {result['message']}")


@cli.command("scrape-authenticated-all")
def scrape_authenticated_all_command() -> None:
    """Scrape every enabled source served by an authenticated adapter.

    Covers planetbids and authenticated_browser sources. Continues past
    per-source failures (session expired, Playwright missing, etc.), collecting
    counts and diagnostics. Reuses the standard scrape/persist path.
    """
    authenticated_types = {"planetbids", "authenticated_browser"}
    with Session(engine) as session:
        sources = list(
            session.exec(
                select(SourceConfig).where(SourceConfig.enabled == True)  # noqa: E712
            ).all()
        )
    sources = [
        s for s in sources if (s.source_type or "").lower() in authenticated_types
    ]

    if not sources:
        typer.echo("No enabled authenticated sources to scrape.")
        return

    total_created = 0
    total_updated = 0
    for source in sources:
        try:
            result = run_scrape_for_source(source)
        except Exception as exc:
            typer.echo(f"{source.name}: scrape failed ({exc})")
            continue
        total_created += result["created_count"]
        total_updated += result["updated_count"]
        _echo_scrape_result(source.name, result)
        for diagnostic in result.get("diagnostics", []):
            typer.echo(f"  {source.name} diagnostic: {diagnostic}")

    typer.echo(
        f"Authenticated scrape complete: {len(sources)} source(s), "
        f"{total_created} created, {total_updated} updated."
    )


def _load_source_config(source: SourceConfig) -> dict:
    raw = source.config_json
    if not raw:
        return {}
    try:
        import json as _json

        parsed = _json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


@cli.command("check-source-auth")
def check_source_auth_command(source_id: int) -> None:
    with Session(engine) as session:
        result = update_source_auth_status(source_id, session)
        if result.get("error"):
            typer.echo(result["error"], err=True)
            raise typer.Exit(code=1)
        _echo_auth_status(result)


@cli.command("check-all-source-auth")
def check_all_source_auth_command() -> None:
    with Session(engine) as session:
        sources = list(session.exec(select(SourceConfig)).all())
        if not sources:
            typer.echo("No sources found")
            return
        for source in sources:
            result = update_source_auth_status(source.id, session)
            _echo_auth_status(result)


@cli.command("source-capabilities")
def source_capabilities_command(source_id: int) -> None:
    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            typer.echo(f"Source not found: {source_id}", err=True)
            raise typer.Exit(code=1)
    _echo_capabilities(get_source_scraper_capabilities(source))


@cli.command("all-source-capabilities")
def all_source_capabilities_command() -> None:
    with Session(engine) as session:
        sources = list(session.exec(select(SourceConfig)).all())
    if not sources:
        typer.echo("No sources found")
        return
    for source in sources:
        _echo_capabilities(get_source_scraper_capabilities(source))


@cli.command("discover-documents")
def discover_documents_command(opportunity_id: int) -> None:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            typer.echo(f"Opportunity not found: {opportunity_id}", err=True)
            raise typer.Exit(code=1)
        title = opportunity.title
        result = discover_documents_for_opportunity(opportunity_id, session)

    typer.echo(
        f"{title}: {result['documents_discovered']} new document links, "
        f"{result['documents_skipped']} already known, "
        f"{len(result['candidates'])} candidates scanned"
    )
    for candidate in result["candidates"][:10]:
        typer.echo(
            f"  - [{candidate['confidence_score']}] {candidate['label'][:70]} "
            f"({candidate.get('file_type') or 'link'}) {candidate['url']}"
        )
    if result["errors"]:
        typer.echo(f"  errors: {'; '.join(result['errors'])}")


@cli.command("download-documents")
def download_documents_command(opportunity_id: int) -> None:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            typer.echo(f"Opportunity not found: {opportunity_id}", err=True)
            raise typer.Exit(code=1)

        result = download_documents_for_opportunity(opportunity_id, session)

    typer.echo(f"Downloaded: {result['downloaded_count']}")
    typer.echo(f"Skipped: {result['skipped_count']}")
    if result["errors"]:
        typer.echo(f"Errors: {'; '.join(result['errors'])}")


@cli.command("download-all-documents")
def download_all_documents_command(
    limit: int = typer.Option(
        10,
        "--limit",
        help="Max opportunities to process; use deliberately for larger batches",
    ),
    status: str = typer.Option(
        None,
        "--status",
        help="Optional review status filter, e.g. Pursue or Watchlist",
    ),
) -> None:
    if limit < 1:
        typer.echo("--limit must be at least 1", err=True)
        raise typer.Exit(code=1)

    total_downloaded = 0
    total_skipped = 0
    total_errors: list[str] = []

    with Session(engine) as session:
        statement = select(Opportunity)
        if status:
            statement = statement.where(Opportunity.review_status == status)
        opportunities = list(session.exec(statement).all())
        matched_count = len(opportunities)
        opportunities = opportunities[:limit]
        for opportunity in opportunities:
            result = download_documents_for_opportunity(opportunity.id, session)
            total_downloaded += result["downloaded_count"]
            total_skipped += result["skipped_count"]
            total_errors.extend(result["errors"])
            typer.echo(
                f"{opportunity.title}: {result['downloaded_count']} downloaded, "
                f"{result['skipped_count']} skipped"
            )

    typer.echo(
        f"Summary: {total_downloaded} downloaded, "
        f"{total_skipped} skipped, {len(total_errors)} errors "
        f"({len(opportunities)} processed of {matched_count} matched, limit {limit})"
    )
    if matched_count > limit:
        typer.echo(
            f"WARNING: {matched_count - limit} matched opportunities were not processed. "
            "Increase --limit deliberately if needed."
        )


@cli.command("parse-document")
def parse_document_command(document_id: int) -> None:
    with Session(engine) as session:
        result = parse_document(document_id, session)

    typer.echo(f"Status: {result['status']}")
    typer.echo(f"Parsed: {result['parsed_count']}")
    typer.echo(f"Skipped: {result['skipped_count']}")
    typer.echo(f"Failed: {result['failed_count']}")
    if result["extracted_text_path"]:
        typer.echo(f"Extracted text: {result['extracted_text_path']}")
    if result["errors"]:
        typer.echo(f"Errors: {'; '.join(result['errors'])}")


@cli.command("parse-opportunity-documents")
def parse_opportunity_documents_command(opportunity_id: int) -> None:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            typer.echo(f"Opportunity not found: {opportunity_id}", err=True)
            raise typer.Exit(code=1)
        result = parse_documents_for_opportunity(opportunity_id, session)

    typer.echo(f"Parsed: {result['parsed_count']}")
    typer.echo(f"Skipped: {result['skipped_count']}")
    typer.echo(f"Failed: {result['failed_count']}")
    if result["errors"]:
        typer.echo(f"Errors: {'; '.join(result['errors'])}")


@cli.command("parse-all-documents")
def parse_all_documents_command() -> None:
    with Session(engine) as session:
        result = parse_all_documents(session)

    typer.echo(f"Parsed: {result['parsed_count']}")
    typer.echo(f"Skipped: {result['skipped_count']}")
    typer.echo(f"Failed: {result['failed_count']}")
    if result["errors"]:
        typer.echo(f"Errors: {'; '.join(result['errors'])}")


@cli.command("ai-status")
def ai_status_command() -> None:
    result = list_ollama_models()
    typer.echo(f"Local AI: {'Available' if result['available'] else 'Unavailable'}")
    typer.echo(f"Base URL: {result['base_url']}")
    typer.echo(f"Model: {result['model']}")
    if not result["available"]:
        typer.echo(result["error"])
        return
    models = result.get("models") or []
    if models:
        names = [m.get("name") or m.get("model") for m in models if isinstance(m, dict)]
        names = [name for name in names if name]
        typer.echo(f"Installed models: {', '.join(names) if names else '-'}")
        if result["model"] not in names:
            typer.echo(f"Configured model is not installed. Run: ollama pull {result['model']}")
    else:
        typer.echo("Installed models: -")
        typer.echo(f"Configured model is not installed. Run: ollama pull {result['model']}")


@cli.command("ai-evaluate-opportunity")
def ai_evaluate_opportunity_command(opportunity_id: int) -> None:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            typer.echo(f"Opportunity not found: {opportunity_id}", err=True)
            raise typer.Exit(code=1)

        result = evaluate_opportunity_with_local_ai(opportunity_id, session)
        if result.get("error"):
            typer.echo(result["error"])
            return

        evaluation = result["evaluation"]
        typer.echo(f"Title: {opportunity.title}")
        typer.echo(f"AI recommendation: {evaluation.recommendation}")
        typer.echo(f"AI score: {evaluation.score}")
        typer.echo(f"Risk level: {evaluation.risk_level}")
        typer.echo(f"Reason: {evaluation.reason}")


@cli.command("ai-evaluate-all-opportunities")
def ai_evaluate_all_opportunities_command() -> None:
    with Session(engine) as session:
        opportunities = list(session.exec(select(Opportunity)).all())
        for opportunity in opportunities:
            result = evaluate_opportunity_with_local_ai(opportunity.id, session)
            if result.get("error"):
                typer.echo(f"{opportunity.title}: {result['error']}")
                continue

            evaluation = result["evaluation"]
            typer.echo(f"Title: {opportunity.title}")
            typer.echo(f"AI recommendation: {evaluation.recommendation}")
            typer.echo(f"AI score: {evaluation.score}")
            typer.echo(f"Risk level: {evaluation.risk_level}")
            typer.echo(f"Reason: {evaluation.reason}")


@cli.command("extract-requirements")
def extract_requirements_command(opportunity_id: int) -> None:
    with Session(engine) as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            typer.echo(f"Opportunity not found: {opportunity_id}", err=True)
            raise typer.Exit(code=1)
        result = extract_requirements_with_local_ai(opportunity_id, session)

    if result.get("error"):
        typer.echo(result["error"])
        return

    typer.echo(f"Title: {opportunity.title}")
    typer.echo(f"Requirements extracted: {result['requirements_count']}")
    typer.echo(f"Missing information items: {len(result['missing_information'])}")
    typer.echo(f"Risk flags: {', '.join(result['risk_flags']) or '-'}")


@cli.command("extract-all-requirements")
def extract_all_requirements_command() -> None:
    with Session(engine) as session:
        opportunities = list(session.exec(select(Opportunity)).all())
        for opportunity in opportunities:
            result = extract_requirements_with_local_ai(opportunity.id, session)
            if result.get("error"):
                typer.echo(f"{opportunity.title}: {result['error']}")
                continue
            typer.echo(f"Title: {opportunity.title}")
            typer.echo(f"Requirements extracted: {result['requirements_count']}")
            typer.echo(f"Missing information items: {len(result['missing_information'])}")
            typer.echo(f"Risk flags: {', '.join(result['risk_flags']) or '-'}")


def run_scrape_for_source(source: SourceConfig) -> dict:
    run = ScrapeRun(source_name=source.name, source_id=source.id, status="running")
    with Session(engine) as session:
        session.add(run)
        session.commit()
        session.refresh(run)

    try:
        result = scrape_source(source)
    except Exception as exc:
        # Without this, a raising scraper leaves the ScrapeRun stuck in
        # "running" forever with no record of the failure.
        finished = utc_now()
        message = str(exc)
        with Session(engine) as session:
            scrape_run = session.get(ScrapeRun, run.id)
            if scrape_run is not None:
                scrape_run.finished_at = finished
                scrape_run.status = "failed"
                scrape_run.error_message = message
                session.add(scrape_run)
            source_record = session.get(SourceConfig, source.id)
            if source_record is not None:
                source_record.last_scrape_at = finished
                source_record.last_scrape_status = "failed"
                source_record.last_scrape_summary = f"Scrape failed: {message}"
                session.add(source_record)
            session.commit()
        raise

    status = "failed" if result["errors"] else "completed"

    with Session(engine) as session:
        scrape_run = session.get(ScrapeRun, run.id)
        if scrape_run is not None:
            scrape_run.finished_at = utc_now()
            scrape_run.status = status
            scrape_run.records_found = result["records_found"]
            scrape_run.created_count = result["created_count"]
            scrape_run.updated_count = result["updated_count"]
            scrape_run.skipped_duplicates = result["skipped_duplicates"]
            scrape_run.error_message = "; ".join(result["errors"]) or None
            session.add(scrape_run)
        source_record = session.get(SourceConfig, source.id)
        if source_record is not None:
            source_record.last_scrape_at = utc_now()
            source_record.last_scrape_status = status
            source_record.last_scrape_summary = _scrape_summary(result)
            session.add(source_record)
        session.commit()

    return result


def _echo_scrape_result(source_name: str, result: dict) -> None:
    typer.echo(
        f"{source_name}: {result.get('total_candidates_found', result['records_found'])} found, "
        f"{result.get('candidates_filtered_quality', result.get('candidates_filtered', 0))} quality filtered, "
        f"{result.get('candidates_filtered_relevance', 0)} relevance filtered, "
        f"{result.get('relevant', 0)} relevant, "
        f"{result.get('maybe_relevant', 0)} maybe, "
        f"{result.get('as_needed_warning_count', 0)} as-needed warnings, "
        f"{result.get('candidates_kept', result['records_found'])} kept, "
        f"{result['created_count']} created, "
        f"{result['updated_count']} updated, "
        f"{result['skipped_duplicates']} skipped duplicates, "
        f"{result.get('documents_discovered', 0)} docs discovered, "
        f"{result.get('documents_skipped', 0)} docs skipped, "
        f"{len(result['errors'])} errors"
    )
    reasons = result.get("filter_reasons") or {}
    if reasons:
        summary = ", ".join(f"{reason} x{count}" for reason, count in reasons.items())
        typer.echo(f"  filtered: {summary}")
    if result["errors"]:
        typer.echo(f"{source_name} errors: {'; '.join(result['errors'])}")


def _echo_auth_status(result: dict) -> None:
    missing_fields = result.get("missing_fields") or []
    typer.echo(
        f"{result['source_name']}: "
        f"requires credentials={result['requires_credentials']}, "
        f"credential type={result.get('credential_type') or '-'}, "
        f"auth status={result['auth_status']}"
    )
    if missing_fields:
        typer.echo(f"{result['source_name']} missing: {', '.join(missing_fields)}")


def _scrape_summary(result: dict) -> str:
    return (
        f"{result.get('total_candidates_found', result['records_found'])} found, "
        f"{result.get('candidates_filtered_quality', 0)} quality filtered, "
        f"{result.get('candidates_filtered_relevance', 0)} relevance filtered, "
        f"{result.get('records_found', 0)} kept, "
        f"{result['created_count']} created, "
        f"{result['updated_count']} updated, "
        f"{result['skipped_duplicates']} skipped duplicates, "
        f"{len(result['errors'])} errors"
    )


def _echo_capabilities(caps: dict) -> None:
    with Session(engine) as session:
        source = session.get(SourceConfig, caps["source_id"])
        source_name = source.name if source else str(caps["source_id"])
    typer.echo(
        f"{source_name}: portal={caps['portal_type'] or 'Unknown'}, "
        f"requires credentials={caps['requires_credentials']}, "
        f"auth status={caps['auth_status'] or '-'}, "
        f"public scrape={'yes' if caps['supports_public_scrape'] else 'no'}, "
        f"authenticated scrape={'yes' if caps['supports_authenticated_scrape'] else 'not enabled'}"
    )
    typer.echo(f"  {caps['message']}")


if __name__ == "__main__":
    cli()
