"""Bind date-sensitive Xero OAuth claims to their owning sources."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTH_PATH = ROOT / "auth.py"
README_PATH = ROOT / "README.md"

CHECKED_DATE = "2026-08-20"
CHECKED_DATE_LONG = "20 August 2026"
GRANULAR_START = "2 March 2026"
MIGRATION_DEADLINE = "13 September 2027"
RUNTIME_SCOPES = "offline_access accounting.reports.trialbalance.read"

SCOPES_URL = "https://developer.xero.com/documentation/guides/oauth2/scopes/"
GRANULAR_FAQ_URL = "https://developer.xero.com/faq/granular-scopes"
OAUTH_FAQ_URL = "https://developer.xero.com/faq/oauth2"
CHANGELOG_URL = "https://developer.xero.com/changelog"


def _scopes_assignment(source: str) -> tuple[ast.Assign | ast.AnnAssign, str]:
    assignments: list[ast.Assign | ast.AnnAssign] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "SCOPES" for target in node.targets):
                assignments.append(node)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "SCOPES"
        ):
            assignments.append(node)
    if len(assignments) != 1:
        raise AssertionError(f"expected one top-level SCOPES assignment, found {len(assignments)}")
    assignment = assignments[0]
    try:
        value = ast.literal_eval(assignment.value)
    except (TypeError, ValueError) as exc:
        raise AssertionError("SCOPES must remain a literal string") from exc
    if not isinstance(value, str):
        raise AssertionError("SCOPES must remain a literal string")
    return assignment, value


def _contiguous_comment_before_scopes(source: str) -> str:
    assignment, _ = _scopes_assignment(source)
    lines = source.splitlines()
    index = assignment.lineno - 2
    comment_lines: list[str] = []
    while index >= 0 and lines[index].lstrip().startswith("#"):
        comment_lines.append(lines[index])
        index -= 1
    comment_lines.reverse()
    if not comment_lines:
        raise AssertionError("SCOPES must have an immediately adjacent comment block")
    return "\n".join(comment_lines)


def _markdown_section(markdown: str, heading: str) -> str:
    lines = markdown.replace("\r\n", "\n").splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.rstrip("\n") == heading]
    if len(starts) != 1:
        raise AssertionError(f"expected one {heading!r} section, found {len(starts)}")
    start = starts[0]
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("## ")
        ),
        len(lines),
    )
    return "".join(lines[start:end])


def _unique_paragraph_containing(section: str, marker: str) -> str:
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", section.replace("\r\n", "\n"))
        if marker in paragraph
    ]
    if len(paragraphs) != 1:
        raise AssertionError(
            f"expected one paragraph containing {marker!r}, found {len(paragraphs)}"
        )
    return paragraphs[0]


def _compact(block: str) -> str:
    return " ".join(block.split())


def _require_values(block: str, *values: str) -> None:
    for value in values:
        if value not in block:
            raise AssertionError(f"claim block is missing {value!r}")


def _require_recheck_instruction(block: str) -> None:
    compact = _compact(block).lower()
    _require_values(compact, "recheck", "created or used after")


def _validate_scope_claim(block: str) -> None:
    _require_values(
        block,
        CHECKED_DATE,
        CHECKED_DATE_LONG,
        GRANULAR_START,
        MIGRATION_DEADLINE,
        "Web",
        "PKCE",
        "accounting.reports.trialbalance.read",
        SCOPES_URL,
        GRANULAR_FAQ_URL,
        CHANGELOG_URL,
    )
    _require_recheck_instruction(block)


def _validate_runtime_scopes(source: str) -> None:
    _, value = _scopes_assignment(source)
    if value != RUNTIME_SCOPES:
        raise AssertionError(
            f"runtime SCOPES changed: expected {RUNTIME_SCOPES!r}, found {value!r}"
        )


def _validate_refresh_claim(block: str) -> None:
    compact = _compact(block)
    _require_values(
        compact,
        CHECKED_DATE,
        CHECKED_DATE_LONG,
        "rotate on use",
        "replacement refresh token",
        "30-minute grace period",
        OAUTH_FAQ_URL,
    )
    _require_recheck_instruction(compact)
    if "single-use" in compact.lower():
        raise AssertionError("the sourced paragraph must describe rotation, not claim an official single-use label")


class XeroAuthProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth_source = AUTH_PATH.read_text(encoding="utf-8")
        self.readme = README_PATH.read_text(encoding="utf-8")
        self.auth_scope_comment = _contiguous_comment_before_scopes(self.auth_source)
        self.readme_scope_paragraph = _unique_paragraph_containing(
            _markdown_section(self.readme, "## Scope and disclaimer"),
            "accounting.reports.trialbalance.read",
        )
        self.readme_refresh_paragraph = _unique_paragraph_containing(
            _markdown_section(self.readme, "## The refresh-token gotcha"),
            "30-minute grace period",
        )

    def test_runtime_scope_value_is_unchanged(self) -> None:
        _validate_runtime_scopes(self.auth_source)

    def test_scopes_comment_binds_current_xero_contract(self) -> None:
        _validate_scope_claim(self.auth_scope_comment)

    def test_readme_scope_claim_binds_current_xero_contract(self) -> None:
        _validate_scope_claim(self.readme_scope_paragraph)

    def test_readme_refresh_claim_binds_current_xero_contract(self) -> None:
        _validate_refresh_claim(self.readme_refresh_paragraph)

    def test_required_urls_cannot_be_satisfied_by_decoys_elsewhere(self) -> None:
        _validate_scope_claim(self.auth_scope_comment)
        _validate_scope_claim(self.readme_scope_paragraph)
        _validate_refresh_claim(self.readme_refresh_paragraph)

        auth_with_decoy = self.auth_source.replace(SCOPES_URL, "", 1)
        auth_with_decoy += f"\n# Unrelated decoy: {SCOPES_URL}\n"
        with self.assertRaisesRegex(AssertionError, re.escape(SCOPES_URL)):
            _validate_scope_claim(_contiguous_comment_before_scopes(auth_with_decoy))

        scope_without_changelog = self.readme_scope_paragraph.replace(CHANGELOG_URL, "", 1)
        readme_with_changelog_decoy = self.readme.replace(
            self.readme_scope_paragraph,
            scope_without_changelog,
            1,
        )
        readme_with_changelog_decoy += f"\n\nUnrelated decoy: {CHANGELOG_URL}\n"
        moved_scope_paragraph = _unique_paragraph_containing(
            _markdown_section(readme_with_changelog_decoy, "## Scope and disclaimer"),
            "accounting.reports.trialbalance.read",
        )
        with self.assertRaisesRegex(AssertionError, re.escape(CHANGELOG_URL)):
            _validate_scope_claim(moved_scope_paragraph)

        refresh_without_faq = self.readme_refresh_paragraph.replace(OAUTH_FAQ_URL, "", 1)
        readme_with_faq_decoy = self.readme.replace(
            self.readme_refresh_paragraph,
            refresh_without_faq,
            1,
        )
        scope_section = _markdown_section(readme_with_faq_decoy, "## Scope and disclaimer")
        readme_with_faq_decoy = readme_with_faq_decoy.replace(
            scope_section,
            f"{scope_section.rstrip()}\n\nUnrelated decoy: {OAUTH_FAQ_URL}\n\n",
            1,
        )
        moved_refresh_paragraph = _unique_paragraph_containing(
            _markdown_section(readme_with_faq_decoy, "## The refresh-token gotcha"),
            "30-minute grace period",
        )
        with self.assertRaisesRegex(AssertionError, re.escape(OAUTH_FAQ_URL)):
            _validate_refresh_claim(moved_refresh_paragraph)

    def test_checked_dates_are_bound_to_each_claim(self) -> None:
        for label, validator, block in (
            ("auth scope comment", _validate_scope_claim, self.auth_scope_comment),
            ("README scope paragraph", _validate_scope_claim, self.readme_scope_paragraph),
            ("README refresh paragraph", _validate_refresh_claim, self.readme_refresh_paragraph),
        ):
            validator(block)
            with self.subTest(block=label):
                with self.assertRaisesRegex(AssertionError, re.escape(CHECKED_DATE)):
                    validator(block.replace(CHECKED_DATE, "2026-08-19", 1))

    def test_changed_vendor_claims_are_rejected(self) -> None:
        _validate_scope_claim(self.auth_scope_comment)
        _validate_scope_claim(self.readme_scope_paragraph)
        _validate_refresh_claim(self.readme_refresh_paragraph)

        for label, validator, block, old, new in (
            (
                "migration deadline",
                _validate_scope_claim,
                self.auth_scope_comment,
                MIGRATION_DEADLINE,
                "September 2027",
            ),
            (
                "granular report scope",
                _validate_scope_claim,
                self.readme_scope_paragraph,
                "accounting.reports.trialbalance.read",
                "accounting.reports.read",
            ),
            (
                "refresh grace period",
                _validate_refresh_claim,
                self.readme_refresh_paragraph,
                "30-minute grace period",
                "60-minute grace period",
            ),
            (
                "unsupported single-use label",
                _validate_refresh_claim,
                self.readme_refresh_paragraph,
                "rotate on use",
                "are single-use",
            ),
        ):
            with self.subTest(claim=label):
                with self.assertRaises(AssertionError):
                    validator(block.replace(old, new, 1))

        changed_runtime_scope = self.auth_source.replace(
            f'SCOPES = "{RUNTIME_SCOPES}"',
            'SCOPES = "offline_access accounting.reports.read"',
            1,
        )
        with self.assertRaisesRegex(AssertionError, "runtime SCOPES changed"):
            _validate_runtime_scopes(changed_runtime_scope)


if __name__ == "__main__":
    unittest.main()
