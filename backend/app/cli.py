import typer

from app.db import init_db

cli = typer.Typer(help="RFP BidOS backend commands.")


@cli.command("init-db")
def init_database() -> None:
    init_db()
    typer.echo("Database initialized")


@cli.command("seed-demo")
def seed_demo() -> None:
    typer.echo("Demo seed not implemented yet")


if __name__ == "__main__":
    cli()
