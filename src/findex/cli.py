"""Findex terminal entry point."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import time
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from findex.index import build_index
from findex.parallel import build_parallel
from findex.search import BM25, TfIdf, search as run_search
from findex.store import load, save

app = typer.Typer(no_args_is_help=True, help="Index and search text collections.")
console = Console(stderr=True)


@app.callback()
def configure(verbose: Annotated[int, typer.Option("--verbose", "-v", count=True)] = 0) -> None:
    logging.basicConfig(
        level=logging.WARNING if verbose == 0 else logging.INFO if verbose == 1 else logging.DEBUG,
        format="%(levelname)s %(message)s",
    )


@app.command("index")
def index_cmd(
    corpus: Path,
    out: Path = typer.Option(Path("index.bin"), "--out"),
    positions: bool = typer.Option(True, "--positions/--no-positions"),
    limit: int | None = typer.Option(None, "--limit"),
    workers: int = typer.Option(1, "--workers", min=1),
    executor: Literal["serial", "threads", "processes"] = typer.Option("serial", "--executor"),
) -> None:
    start = time.perf_counter()
    if not corpus.is_dir():
        raise typer.BadParameter("Corpus directory does not exist")
    with Progress(console=console) as progress:
        task = progress.add_task("Building index", total=1)
        ix = (
            build_parallel(corpus, workers=workers, executor=executor, positions=positions, limit=limit)
            if executor != "serial" or workers > 1
            else build_index(corpus, positions=positions, limit=limit)
        )
        save(ix, out)
        progress.advance(task)
    console.print(f"Indexed {ix.num_docs} documents, {len(ix)} terms in {time.perf_counter() - start:.3f}s → {out}")


@app.command("search")
def search_cmd(
    index: Path,
    query: str,
    k: int = typer.Option(10, "--k", min=1),
    scorer: Literal["bm25", "tfidf"] = typer.Option("bm25", "--scorer"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    ix = load(index)
    results = run_search(ix, query, scorer=BM25() if scorer == "bm25" else TfIdf(), k=k)
    if json_output:
        for result in results:
            typer.echo(
                json.dumps(
                    {"doc_id": result.doc_id, "score": result.score, "title": result.title, "snippet": result.snippet},
                    ensure_ascii=False,
                )
            )
    else:
        table = Table("Document", "Score", "Snippet")
        for result in results:
            table.add_row(result.title, f"{result.score:.4f}", result.snippet)
        console.print(table)


@app.command("stats")
def stats_cmd(index: Path) -> None:
    ix = load(index)
    console.print(
        f"Documents: {ix.num_docs}\nTokens: {sum(ix.doc_lengths.values())}\nVocabulary: {len(ix)}\nAverage document length: {ix.avg_doc_length:.2f}"
    )


async def _run_crawl(
    seed: str,
    *,
    out: Path,
    max_pages: int,
    concurrency: int,
    per_host: int,
    user_agent: str,
    min_host_delay: float,
) -> None:
    """Stream crawler pages to disk without buffering the corpus in memory."""
    import aiofiles
    from dataclasses import asdict
    from rich.live import Live
    from findex.crawler.crawl import CrawlStats, crawl

    out.parent.mkdir(parents=True, exist_ok=True)
    crawler_logger = logging.getLogger("findex.crawler")
    crawler_logger.setLevel(logging.INFO)
    from logging.handlers import QueueHandler, QueueListener
    from queue import SimpleQueue

    log_handler = logging.FileHandler("crawl.log", encoding="utf-8")
    log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    queue_handler = QueueHandler(SimpleQueue())
    listener = QueueListener(queue_handler.queue, log_handler)
    listener.start()
    crawler_logger.addHandler(queue_handler)
    started = time.perf_counter()
    current = CrawlStats(pages=0, errors=0, in_flight=0, queued=0)

    def update_stats(stats: CrawlStats) -> None:
        nonlocal current
        current = stats
        elapsed = max(time.perf_counter() - started, 0.001)
        live.update(
            Text(
                f"Pages: {stats.pages} | Pages/s: {stats.pages / elapsed:.2f} | "
                f"In-flight: {stats.in_flight} | Errors: {stats.errors} | Queue: {stats.queued}"
            )
        )

    from rich.text import Text

    status = Text("Starting crawl...")
    try:
        with Live(status, console=console, refresh_per_second=4) as live:
            async with aiofiles.open(out, "w", encoding="utf-8") as handle:
                async for page in crawl(
                    [seed],
                    max_pages=max_pages,
                    concurrency=concurrency,
                    per_host=per_host,
                    min_host_delay=min_host_delay,
                    user_agent=user_agent,
                    on_progress=update_stats,
                ):
                    await handle.write(json.dumps(asdict(page), ensure_ascii=False) + "\n")
    finally:
        crawler_logger.removeHandler(queue_handler)
        listener.stop()
        log_handler.close()
    console.print(f"Saved {current.pages} pages to {out}; per-URL details in crawl.log")


@app.command("crawl")
def crawl_cmd(
    seed_url: str,
    max_pages: int = typer.Option(500, "--max-pages", min=1),
    concurrency: int = typer.Option(10, "--concurrency", min=1),
    per_host: int = typer.Option(2, "--per-host", min=1),
    out: Path = typer.Option(Path("data/crawl.jsonl"), "--out"),
    user_agent: str = typer.Option(..., "--user-agent", help="Identify your crawler with a real contact URL"),
    min_host_delay: float = typer.Option(0.2, "--min-host-delay", min=0),
) -> None:
    """Crawl a permitted site and write a streaming JSONL corpus."""
    import asyncio

    asyncio.run(
        _run_crawl(
            seed_url,
            out=out,
            max_pages=max_pages,
            concurrency=concurrency,
            per_host=per_host,
            user_agent=user_agent,
            min_host_delay=min_host_delay,
        )
    )


@app.command("serve")
def serve_cmd(
    port: int | None = typer.Option(None, "--port", min=1, max=65535),
    workers: int = typer.Option(1, "--workers", min=1),
) -> None:
    """Serve the FastAPI application with Uvicorn."""
    import uvicorn
    from findex.web.settings import Settings

    settings = Settings()
    uvicorn.run(
        "findex.web.app:app",
        host="0.0.0.0",
        port=port or settings.port,
        workers=workers,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    app()
