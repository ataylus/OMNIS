"""Smoke tests for the CLI command layer (argparse wiring + perf path)."""

from omnis.cli import build_parser, main


def test_build_parser_exposes_all_commands():
    parser = build_parser()
    # Pull the subcommand names from the subparsers action.
    sub = next(a for a in parser._actions if hasattr(a, "choices") and a.choices)
    for cmd in ("run", "eval", "score", "report", "serve", "synth", "perf"):
        assert cmd in sub.choices


def test_perf_command_runs_and_passes_bar(capsys):
    # A small corpus keeps the test fast; the pipeline must stay under the bar.
    rc = main(["perf", "--n", "100"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "TOTAL" in out
    assert "PASS" in out
