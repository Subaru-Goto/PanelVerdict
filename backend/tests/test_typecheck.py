"""The type checker catches the two silent failures 103/#221 was written for.

Each test hands mypy a small module, using the repo's own config, and expects a
report. The first shows the ticket's headline hazard is caught at all; the
second turns red if `check_untyped_defs` is removed.
"""

import subprocess
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parent.parent

MISSPELLED_STATE_KEY = """
from app.graph import EvaluateState

def node(state: EvaluateState) -> EvaluateState:
    return {"quesry": "widened"}
"""

# The double lacks `screen`, and is built inside an unannotated function — the
# shape every test in this suite has. Only `check_untyped_defs` looks in there.
DOUBLE_MISSING_A_METHOD = """
from app.screening import screen_inputs

class Silent:
    def scren(self, text: str) -> None: ...

def test_something():
    screen_inputs(Silent(), ["a headline"])
"""


def mypy(tmp_path: Path, name: str, source: str) -> str:
    module = tmp_path / name
    module.write_text(source)
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(BACKEND / "pyproject.toml"),
            str(module),
        ],
        capture_output=True,
        text=True,
        cwd=BACKEND,
        env={"MYPYPATH": str(BACKEND), "PATH": ""},
        check=False,
    )
    return run.stdout + run.stderr


def test_a_misspelled_state_key_is_reported(tmp_path: Path) -> None:
    report = mypy(tmp_path, "probe_state.py", MISSPELLED_STATE_KEY)
    assert "typeddict-unknown-key" in report, report


def test_a_double_missing_a_protocol_method_is_reported_inside_a_test(
    tmp_path: Path,
) -> None:
    report = mypy(tmp_path, "test_probe_double.py", DOUBLE_MISSING_A_METHOD)
    assert "arg-type" in report, report
    assert '"Silent"' in report, report
