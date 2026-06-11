from datetime import UTC, datetime

import typer
from sqlmodel import Session, select

from app.db import engine, init_db
from app.models import Opportunity, ScrapeRun, SourceConfig
from app.services.ai_evaluator import evaluate_opportunity_with_local_ai
from app.services.downloader import download_documents_for_opportunity
from app.services.parser import (
    parse_all_documents,
    parse_document,
    parse_documents_for_opportunity,
)
from app.services.requirement_extractor import extract_requirements_with_local_ai
from app.services.scraper import preview_source, scrape_source
from app.services.scorer import score_opportunity_text
from app.services.source_credentials import update_source_auth_status

cli = typer.Typer(help="RFP BidOS backend commands.")


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@cli.command("init-db")
def init_database() -> None:
    init_db()
    typer.echo("Database initialized")


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
            notes="Authenticated BidNet scraping is intentionally not implemented yet.",
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
                session.add(existing)
        session.commit()

    typer.echo(
        "Demo seed complete: "
        f"{opportunities_created} opportunities created, "
        f"{sources_created} sources created"
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
            opportunity.updated_at = utc_now()
            session.add(opportunity)
            typer.echo(
                f"{opportunity.title}: {scoring_result['decision']} "
                f"({scoring_result['score']})"
            )
        session.commit()


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
def preview_source_command(source_id: int) -> None:
    with Session(engine) as session:
        source = session.get(SourceConfig, source_id)
        if source is None:
            typer.echo(f"Source not found: {source_id}", err=True)
            raise typer.Exit(code=1)

    result = preview_source(source)
    _echo_scrape_result(source.name, result)
    for candidate in result.get("candidates", [])[:10]:
        typer.echo(
            f"- {candidate['title']} | due: {candidate.get('due_date') or '-'} | "
            f"confidence: {candidate.get('confidence_score')} | "
            f"documents: {candidate.get('document_count')}"
        )


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
def download_all_documents_command() -> None:
    total_downloaded = 0
    total_skipped = 0
    total_errors: list[str] = []

    with Session(engine) as session:
        opportunities = list(session.exec(select(Opportunity)).all())
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
        f"{total_skipped} skipped, {len(total_errors)} errors"
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

    result = scrape_source(source)
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
        f"{source_name}: {result['records_found']} candidates, "
        f"{result['created_count']} created, "
        f"{result['updated_count']} updated, "
        f"{result['skipped_duplicates']} skipped duplicates, "
        f"{len(result['errors'])} errors"
    )
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
        f"{result['records_found']} candidates, "
        f"{result['created_count']} created, "
        f"{result['updated_count']} updated, "
        f"{result['skipped_duplicates']} skipped duplicates, "
        f"{len(result['errors'])} errors"
    )


if __name__ == "__main__":
    cli()
