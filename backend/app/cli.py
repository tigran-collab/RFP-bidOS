from datetime import UTC, datetime

import typer
from sqlmodel import Session, select

from app.db import engine, init_db
from app.models import Opportunity, ScrapeRun, SourceConfig
from app.services.scraper import scrape_source
from app.services.scorer import score_opportunity_text

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
    typer.echo(f"Records found: {result['records_found']}")
    typer.echo(f"Created: {result['created_count']}")
    typer.echo(f"Skipped duplicates: {result['skipped_duplicates']}")
    if result["errors"]:
        typer.echo(f"Errors: {'; '.join(result['errors'])}")


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
        typer.echo(
            f"{source.name}: {result['records_found']} found, "
            f"{result['created_count']} created, "
            f"{result['skipped_duplicates']} duplicates"
        )
        if result["errors"]:
            typer.echo(f"{source.name} errors: {'; '.join(result['errors'])}")


def run_scrape_for_source(source: SourceConfig) -> dict:
    run = ScrapeRun(source_name=source.name, status="running")
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
            scrape_run.error_message = "; ".join(result["errors"]) or None
            session.add(scrape_run)
            session.commit()

    return result


if __name__ == "__main__":
    cli()
