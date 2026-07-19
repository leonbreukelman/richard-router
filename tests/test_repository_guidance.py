from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_agents_entrypoint_loads_method_once_and_points_to_contributing() -> None:
    agents = read_repo_file("AGENTS.md")

    assert agents.count("load docs/method/METHOD.md then docs/method/PROJECT.md") == 1
    assert "CONTRIBUTING.md" in agents
    assert "SmactorIO" in agents


def test_contributing_defines_smactorio_authorization_and_pre_pr_contract() -> None:
    contributing = read_repo_file("CONTRIBUTING.md")

    for label in (
        "smactorio",
        "autonomy:ready",
        "risk:low",
        "smactorio:claimed",
        "smactorio:blocked",
        "smactorio:needs-attention",
        "smactorio:done",
    ):
        assert f"`{label}`" in contributing

    for command in (
        "uv sync --all-groups",
        "uv run ruff check .",
        "uv run pytest -v",
    ):
        assert command in contributing

    assert "`uv / ruff / pytest`" in contributing
    assert "Necessary, not sufficient" in contributing
    assert "runtime/operator-managed" in contributing
    assert "A maintainer adds `autonomy:ready` and `risk:low`" in contributing
    assert "tests/test_repository_guidance.py" in contributing
    assert "governance guardrail" in contributing


def test_smactorio_issue_form_requests_triage_without_self_authorizing_pickup() -> None:
    issue_form = read_repo_file(".github/ISSUE_TEMPLATE/smactorio-task.yml")

    labels_block = re.search(r"^labels:\n(?P<labels>(?:  - .*\n)+)^body:", issue_form, re.MULTILINE)
    assert labels_block is not None
    labels = re.findall(r'^  - "([^"]+)"$', labels_block.group("labels"), re.MULTILINE)
    assert labels == ["smactorio"]

    for forbidden in (
        "autonomy:ready",
        "risk:low",
        "smactorio:claimed",
        "smactorio:blocked",
        "smactorio:needs-attention",
        "smactorio:done",
    ):
        assert f'  - "{forbidden}"' not in labels_block.group("labels")

    assert "Maintainer authorization" in issue_form
    assert "does not guarantee pickup" in issue_form
    assert "CONTRIBUTING.md" in issue_form


def test_pull_request_template_puts_required_gates_in_every_pr() -> None:
    template = read_repo_file(".github/pull_request_template.md")

    for marker in (
        "uv run ruff check .",
        "uv run pytest -v",
        "uv / ruff / pytest",
        "secret",
        "local config",
        "protected path",
    ):
        assert marker in template


def test_readme_links_contribution_and_smactorio_entrypoints() -> None:
    readme = read_repo_file("README.md")

    assert "[CONTRIBUTING.md](CONTRIBUTING.md)" in readme
    assert "[SmactorIO task form](.github/ISSUE_TEMPLATE/smactorio-task.yml)" in readme
    assert "`smactorio`" in readme
    assert "`autonomy:ready`" in readme
    assert "`risk:low`" in readme


def test_project_card_records_current_branch_protection_without_stale_decision() -> None:
    project = read_repo_file("docs/method/PROJECT.md")

    assert "strictly requires `uv / ruff / pytest`" in project
    assert "Consider adding branch protection" not in project
    assert "Resolve the base from current `origin/main`" in project
    assert "everything else is human-controlled" in project.lower()
