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
) -> None:
    start = time.perf_counter()
    if not corpus.is_dir():
        raise typer.BadParameter("Corpus directory does not exist")
    with Progress(console=console) as progress:
        task = progress.add_task("Building index", total=1)
        ix = build_index(corpus, positions=positions, limit=limit)
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


if __name__ == "__main__":
    app()
