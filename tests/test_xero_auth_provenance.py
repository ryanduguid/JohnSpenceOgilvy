"""Bind date-sensitive Xero OAuth claims to exact source blocks."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTH_PATH = ROOT / "auth.py"
README_PATH = ROOT / "README.md"

RUNTIME_SCOPES = "offline_access accounting.reports.trialbalance.read"
SCOPES_URL = "https://developer.xero.com/documentation/guides/oauth2/scopes/"
GRANULAR_FAQ_URL = "https://developer.xero.com/faq/granular-scopes"
OAUTH_FAQ_URL = "https://developer.xero.com/faq/oauth2"
CHANGELOG_URL = "https://developer.xero.com/changelog"

SCOPE_HEADING = "## Scope and disclaimer"
REFRESH_HEADING = "## The refresh-token gotcha"

EXPECTED_AUTH_COMMENT = "\n".join(
    (
        "# Web and PKCE apps created on or after 2 March 2026 use granular scopes.",
        "# Existing apps using accounting.reports.read must migrate by 13 September 2027.",
        "# This exporter needs only offline_access and accounting.reports.trialbalance.read.",
        "# Xero contract checked 2026-08-20 (20 August 2026):",
        f"# {SCOPES_URL}",
        f"# {GRANULAR_FAQ_URL}",
        f"# {CHANGELOG_URL}",
        "# Recheck these pages for apps created or used after that date.",
    )
)
EXPECTED_SCOPE_PARAGRAPH = (
    "Read-only (`accounting.reports.trialbalance.read`); this tool cannot write "
    "to any ledger. Web and PKCE apps created on or after 2 March 2026 use "
    "granular scopes, while existing apps using the broad "
    "`accounting.reports.read` scope must migrate by 13 September 2027. "
    f"Xero's [OAuth scope list]({SCOPES_URL}), "
    f"[Granular Scopes FAQ]({GRANULAR_FAQ_URL}) and "
    f"[developer changelog]({CHANGELOG_URL}) were checked on 20 August 2026 "
    "(`2026-08-20`); recheck them for apps created or used after that date. "
    "`token.json` and `.env` are gitignored. They are credentials, so treat "
    "them like passwords."
)
EXPECTED_REFRESH_PARAGRAPH = (
    "Xero refresh tokens **rotate on use**: every refresh returns a replacement "
    "refresh token. If the refresh response does not arrive, Xero permits "
    "retrying the previous token for up to a 30-minute grace period; outside "
    "that window, the user must re-authorise. "
    f"The [Xero OAuth FAQ]({OAUTH_FAQ_URL}) was checked on 20 August 2026 "
    "(`2026-08-20`); recheck it for apps created or used after that date."
)


def _normalise_newlines(text: str) -> str:
    normalised = text.replace("\r\n", "\n")
    if "\r" in normalised:
        raise AssertionError("source contains a bare carriage return")
    return normalised


def _replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise AssertionError(f"expected one mutation target, found {count}")
    return text.replace(old, new, 1)


def _mutate_claim(markdown: str, expected: str, old: str, new: str) -> str:
    return _replace_once(markdown, expected, _replace_once(expected, old, new))


def _scopes_assignment(source: str) -> tuple[ast.Assign | ast.AnnAssign, str]:
    assignments: list[ast.Assign | ast.AnnAssign] = []
    for node in ast.parse(_normalise_newlines(source)).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SCOPES"
            for target in node.targets
        ):
            assignments.append(node)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "SCOPES"
        ):
            assignments.append(node)

    if len(assignments) != 1:
        raise AssertionError(
            f"expected one top-level SCOPES assignment, found {len(assignments)}"
        )
    assignment = assignments[0]
    try:
        value = ast.literal_eval(assignment.value)
    except (TypeError, ValueError) as exc:
        raise AssertionError("SCOPES must remain a literal string") from exc
    if not isinstance(value, str):
        raise AssertionError("SCOPES must remain a literal string")
    return assignment, value


def _validate_runtime_scopes(source: str) -> None:
    _, value = _scopes_assignment(source)
    if value != RUNTIME_SCOPES:
        raise AssertionError(
            f"runtime SCOPES changed: expected {RUNTIME_SCOPES!r}, found {value!r}"
        )


def _validate_auth_contract(source: str) -> None:
    normalised = _normalise_newlines(source)
    assignment, _ = _scopes_assignment(normalised)
    lines = normalised.split("\n")
    index = assignment.lineno - 2
    comment: list[str] = []
    while index >= 0 and lines[index].startswith("#"):
        comment.append(lines[index])
        index -= 1
    comment.reverse()

    _validate_runtime_scopes(normalised)
    if "\n".join(comment) != EXPECTED_AUTH_COMMENT:
        raise AssertionError("the contiguous SCOPES provenance comment changed")


def _section_paragraphs(markdown: str, heading: str) -> list[str]:
    lines = _normalise_newlines(markdown).split("\n")
    starts = [index for index, line in enumerate(lines) if line == heading]
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
    section = lines[start:end]
    if not section or section[-1] != "" or (len(section) > 1 and section[-2] == ""):
        raise AssertionError(f"{heading!r} changed its exact section boundary")

    paragraphs = "\n".join(section[:-1]).split("\n\n")
    if any(not paragraph for paragraph in paragraphs):
        raise AssertionError(f"{heading!r} contains an empty paragraph")
    return paragraphs


def _validate_readme_claim(
    markdown: str,
    heading: str,
    expected: str,
    expected_paragraphs: int,
) -> None:
    paragraphs = _section_paragraphs(markdown, heading)
    if len(paragraphs) != expected_paragraphs:
        raise AssertionError(f"{heading!r} paragraph count changed")
    if paragraphs[0] != heading or paragraphs[1] != expected:
        raise AssertionError(f"{heading!r} owning claim paragraph changed")


def _validate_scope(markdown: str) -> None:
    _validate_readme_claim(markdown, SCOPE_HEADING, EXPECTED_SCOPE_PARAGRAPH, 4)


def _validate_refresh(markdown: str) -> None:
    _validate_readme_claim(markdown, REFRESH_HEADING, EXPECTED_REFRESH_PARAGRAPH, 3)


class XeroAuthProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = _normalise_newlines(AUTH_PATH.read_text(encoding="utf-8"))
        self.readme = _normalise_newlines(README_PATH.read_text(encoding="utf-8"))

    def assert_rejected(self, cases) -> None:
        for label, validator, source in cases:
            with self.subTest(variant=label):
                with self.assertRaises(AssertionError):
                    validator(source)

    def scope_mutation(self, old: str, new: str) -> str:
        return _mutate_claim(self.readme, EXPECTED_SCOPE_PARAGRAPH, old, new)

    def refresh_mutation(self, old: str, new: str) -> str:
        return _mutate_claim(self.readme, EXPECTED_REFRESH_PARAGRAPH, old, new)

    def test_canonical_contracts_accept_lf_and_crlf_only(self) -> None:
        for label, newline in (("LF", "\n"), ("CRLF", "\r\n")):
            with self.subTest(newlines=label):
                _validate_auth_contract(self.auth.replace("\n", newline))
                _validate_scope(self.readme.replace("\n", newline))
                _validate_refresh(self.readme.replace("\n", newline))

        self.assert_rejected(
            (
                ("bare CR in auth", _validate_auth_contract, self.auth.replace("\n", "\r")),
                ("bare CR in README", _validate_scope, self.readme.replace("\n", "\r")),
            )
        )

    def test_runtime_scope_is_one_exact_literal(self) -> None:
        _validate_runtime_scopes(self.auth)
        assignment = f'SCOPES = "{RUNTIME_SCOPES}"'
        self.assert_rejected(
            (
                (
                    "broadened scope",
                    _validate_runtime_scopes,
                    _replace_once(
                        self.auth,
                        assignment,
                        'SCOPES = "offline_access accounting.reports.read"',
                    ),
                ),
                (
                    "computed scope",
                    _validate_runtime_scopes,
                    _replace_once(
                        self.auth,
                        assignment,
                        (
                            'SCOPES = "offline_access " + '
                            '"accounting.reports.trialbalance.read"'
                        ),
                    ),
                ),
                (
                    "duplicate assignment",
                    _validate_runtime_scopes,
                    self.auth + f"\n{assignment}\n",
                ),
            )
        )

    def test_reviewer_hidden_and_semantic_mutations_are_rejected(self) -> None:
        fenced_scope = _replace_once(
            self.readme,
            f"{SCOPE_HEADING}\n\n{EXPECTED_SCOPE_PARAGRAPH}",
            f"```text\n{SCOPE_HEADING}\n\n{EXPECTED_SCOPE_PARAGRAPH}\n```",
        )
        fenced_refresh = _replace_once(
            self.readme,
            f"{REFRESH_HEADING}\n\n{EXPECTED_REFRESH_PARAGRAPH}",
            f"```text\n{REFRESH_HEADING}\n\n{EXPECTED_REFRESH_PARAGRAPH}\n```",
        )
        cases = [
            (
                "scope paragraph hidden in HTML",
                _validate_scope,
                _replace_once(
                    self.readme,
                    EXPECTED_SCOPE_PARAGRAPH,
                    f"<!-- {EXPECTED_SCOPE_PARAGRAPH} -->",
                ),
            ),
            ("scope heading and paragraph fenced", _validate_scope, fenced_scope),
            (
                "refresh paragraph hidden in HTML",
                _validate_refresh,
                _replace_once(
                    self.readme,
                    EXPECTED_REFRESH_PARAGRAPH,
                    f"<!-- {EXPECTED_REFRESH_PARAGRAPH} -->",
                ),
            ),
            ("refresh heading and paragraph fenced", _validate_refresh, fenced_refresh),
            (
                "visible deadline stale; correct value hidden",
                _validate_scope,
                self.scope_mutation(
                    "13 September 2027",
                    "12 September 2027 <!-- 13 September 2027 -->",
                ),
            ),
            (
                "visible checked date stale; correct values hidden",
                _validate_scope,
                self.scope_mutation(
                    "20 August 2026 (`2026-08-20`)",
                    (
                        "19 August 2026 (`2026-08-19`) "
                        "<!-- 20 August 2026 (`2026-08-20`) -->"
                    ),
                ),
            ),
            (
                "visible grace stale; correct value hidden",
                _validate_refresh,
                self.refresh_mutation(
                    "30-minute grace period",
                    "60-minute grace period <!-- 30-minute grace period -->",
                ),
            ),
        ]
        for label, validator, old, new in (
            (
                "do not use granular scopes",
                _validate_scope,
                "use granular scopes",
                "do not use granular scopes",
            ),
            ("must not migrate", _validate_scope, "must migrate", "must not migrate"),
            ("removed use relationship", _validate_scope, "use granular", "have granular"),
            ("removed migration obligation", _validate_scope, "must migrate", "faces"),
            ("forbids retrying", _validate_refresh, "permits retrying", "forbids retrying"),
            ("removed retry permission", _validate_refresh, "permits retrying", "mentions"),
            (
                "removed missing-response condition",
                _validate_refresh,
                "If the refresh response does not arrive, ",
                "",
            ),
            ("removed previous-token subject", _validate_refresh, "the previous token", "a token"),
            (
                "removed re-authorisation outcome",
                _validate_refresh,
                "the user must re-authorise",
                "the user may continue",
            ),
            (
                "removed replacement result",
                _validate_refresh,
                "returns a replacement refresh token",
                "returns a token",
            ),
        ):
            mutate = self.scope_mutation if validator is _validate_scope else self.refresh_mutation
            cases.append((label, validator, mutate(old, new)))

        self.assert_rejected(cases)

    def test_moved_added_stale_and_decoy_content_is_rejected(self) -> None:
        without_scope = _replace_once(
            self.readme,
            f"{EXPECTED_SCOPE_PARAGRAPH}\n\n",
            "",
        )
        without_refresh = _replace_once(
            self.readme,
            f"{EXPECTED_REFRESH_PARAGRAPH}\n\n",
            "",
        )
        cases = [
            (
                "scope claim moved to Files",
                _validate_scope,
                _replace_once(
                    without_scope,
                    "## Files\n\n",
                    f"## Files\n\n{EXPECTED_SCOPE_PARAGRAPH}\n\n",
                ),
            ),
            (
                "refresh claim moved to Files",
                _validate_refresh,
                _replace_once(
                    without_refresh,
                    "## Files\n\n",
                    f"## Files\n\n{EXPECTED_REFRESH_PARAGRAPH}\n\n",
                ),
            ),
            (
                "added contradictory scope clause",
                _validate_scope,
                _replace_once(
                    self.readme,
                    EXPECTED_SCOPE_PARAGRAPH,
                    EXPECTED_SCOPE_PARAGRAPH + " Web apps do not use granular scopes.",
                ),
            ),
            (
                "added contradictory scope paragraph",
                _validate_scope,
                _replace_once(
                    self.readme,
                    f"{EXPECTED_SCOPE_PARAGRAPH}\n\n",
                    (
                        f"{EXPECTED_SCOPE_PARAGRAPH}\n\n"
                        "Web apps do not use granular scopes.\n\n"
                    ),
                ),
            ),
            (
                "added contradictory refresh paragraph",
                _validate_refresh,
                _replace_once(
                    self.readme,
                    f"{EXPECTED_REFRESH_PARAGRAPH}\n\n",
                    (
                        f"{EXPECTED_REFRESH_PARAGRAPH}\n\n"
                        "Xero forbids retrying the previous token.\n\n"
                    ),
                ),
            ),
            (
                "scope broadened",
                _validate_scope,
                self.scope_mutation(
                    "accounting.reports.trialbalance.read",
                    "accounting.reports.read",
                ),
            ),
            (
                "single-use label restored",
                _validate_refresh,
                self.refresh_mutation("**rotate on use**", "**are single-use**"),
            ),
        ]

        for url in (SCOPES_URL, GRANULAR_FAQ_URL, CHANGELOG_URL):
            auth = _replace_once(self.auth, f"# {url}", "#")
            scope = _replace_once(
                self.readme,
                f"]({url})",
                "](https://example.invalid/)",
            )
            cases.extend(
                (
                    (
                        f"auth URL moved: {url}",
                        _validate_auth_contract,
                        auth + f"\n# Decoy: {url}\n",
                    ),
                    (
                        f"scope URL moved: {url}",
                        _validate_scope,
                        scope + f"\n\nDecoy: {url}\n",
                    ),
                )
            )

        refresh = _replace_once(
            self.readme,
            f"]({OAUTH_FAQ_URL})",
            "](https://example.invalid/)",
        )
        cases.append(
            (
                "OAuth FAQ moved",
                _validate_refresh,
                refresh + f"\n\nDecoy: {OAUTH_FAQ_URL}\n",
            )
        )

        for label, old, new in (
            ("auth checked date stale", "2026-08-20", "2026-08-19"),
            ("auth deadline vague", "13 September 2027", "September 2027"),
            ("auth scope negated", "use granular scopes", "do not use granular scopes"),
            ("auth migration negated", "must migrate", "must not migrate"),
        ):
            cases.append(
                (label, _validate_auth_contract, _replace_once(self.auth, old, new))
            )

        self.assert_rejected(cases)


if __name__ == "__main__":
    unittest.main()
