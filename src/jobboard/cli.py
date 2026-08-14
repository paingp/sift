"""`jobs` CLI entrypoint (Typer). Thin adapter over service.py — no business
logic here; see CLAUDE.md "Architecture rules".
"""

from __future__ import annotations

import typer

from jobboard import service

app = typer.Typer(no_args_is_help=True, add_completion=False)

_NOT_IMPLEMENTED = (
    "not yet implemented — see BUILD_GUIDE.md for the phase that adds this command"
)


@app.command()
def ingest(
    source: str = typer.Option(None, help="Limit to one adapter, e.g. greenhouse"),
    company: str = typer.Option(None, help="Limit to one company slug"),
    all: bool = typer.Option(False, "--all", help="Ingest from all enabled sources"),
) -> None:
    """Fetch postings from configured sources into the database."""
    if all:
        typer.echo("--all not yet implemented — see BUILD_GUIDE.md Phase 2")
        raise typer.Exit(1)
    if not source or not company:
        typer.echo("specify --source and --company, e.g. --source greenhouse --company anthropic")
        raise typer.Exit(1)

    result = service.ingest(source, company)
    typer.echo(
        f"{result.source}/{result.company}: {result.status} "
        f"(fetched={result.fetched} new={result.new} updated={result.updated})"
    )
    if result.status == "failed":
        typer.echo(f"error: {result.error}")
        raise typer.Exit(1)


@app.command()
def score(
    limit: int = typer.Option(40, help="LLM-score the top N by embedding similarity"),
    force: bool = typer.Option(False, help="Rescore even if already scored at this version"),
) -> None:
    """LLM-score the top candidates by embedding similarity."""
    typer.echo(_NOT_IMPLEMENTED)
    raise typer.Exit(1)


@app.command(name="run")
def run_all(all: bool = typer.Option(False, "--all", help="Ingest + embed + score")) -> None:
    """Full pipeline run: ingest, embed, score. What the systemd timer runs."""
    typer.echo(_NOT_IMPLEMENTED)
    raise typer.Exit(1)


@app.command(name="list")
def list_jobs(
    sort: str = typer.Option("score", help="score | date | blended"),
    show_hidden: bool = typer.Option(False, "--show-hidden"),
) -> None:
    """Print the board to the terminal."""
    typer.echo(_NOT_IMPLEMENTED)
    raise typer.Exit(1)


@app.command()
def apply(job_id: int) -> None:
    """Mark a job applied."""
    typer.echo(_NOT_IMPLEMENTED)
    raise typer.Exit(1)


@app.command()
def dismiss(job_id: int) -> None:
    """Mark a job dismissed."""
    typer.echo(_NOT_IMPLEMENTED)
    raise typer.Exit(1)


@app.command()
def why(job_id: int) -> None:
    """Explain why a job is or isn't showing on the board."""
    typer.echo(_NOT_IMPLEMENTED)
    raise typer.Exit(1)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8080),
) -> None:
    """Run the web UI."""
    typer.echo(_NOT_IMPLEMENTED)
    raise typer.Exit(1)


@app.command()
def doctor() -> None:
    """Health check: DB, migrations, Ollama, config. Prints a table."""
    checks = service.run_doctor()

    symbols = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}
    name_width = max(len(c.name) for c in checks)
    status_width = max(len(symbols[c.status]) for c in checks)

    colors = {"ok": typer.colors.GREEN, "warn": typer.colors.YELLOW, "fail": typer.colors.RED}
    for check in checks:
        status = symbols[check.status].ljust(status_width)
        line = f"{check.name.ljust(name_width)}  {status}  {check.detail}"
        typer.secho(line, fg=colors[check.status])

    if any(c.status == "fail" for c in checks):
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
