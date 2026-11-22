from typer.testing import CliRunner
from findex.cli import app


def test_cli_index_and_search(corpus, tmp_path):
    runner = CliRunner()
    index_file = tmp_path / "index.bin"
    build = runner.invoke(app, ["index", str(corpus), "--out", str(index_file)])
    assert build.exit_code == 0, build.exception
    result = runner.invoke(app, ["search", str(index_file), "python", "--json"])
    assert result.exit_code == 0, result.exception
    assert "doc_id" in result.stdout
    assert runner.invoke(app, ["stats", str(index_file)]).exit_code == 0
