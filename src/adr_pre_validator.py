"""Pre-review validation for ADRs — catches structural defects before council."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ADRValidationIssue:
    """A single validation issue found in an ADR."""

    code: str
    message: str
    fixable: bool = False


@dataclass
class ADRValidationResult:
    """Result of pre-review validation."""

    issues: list[ADRValidationIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.issues) == 0

    @property
    def has_fixable_only(self) -> bool:
        return len(self.issues) > 0 and all(i.fixable for i in self.issues)


_STATUS_RE = re.compile(r"\*\*Status:\*\*\s*(\w+)", re.IGNORECASE)
_SUPERSEDE_RE = re.compile(
    r"supersed(?:es?|ed|ing)\s+(?:ADR[- ]?)(\d{4})", re.IGNORECASE
)
_SUPERSEDED_BY_RE = re.compile(r"superseded\s+by\s+(?:ADR[- ]?)(\d{4})", re.IGNORECASE)
# Statuses that require the superseding ADR to be at least Accepted
_SETTLED_STATUSES = frozenset({"accepted", "superseded", "deprecated", "rejected"})
_REQUIRED_SECTIONS = ("## Context", "## Decision", "## Consequences")
# Matches patterns like "(line 42)", "(line 1122)", "(lines 10-20)", "(lines 51 and 127)"
_LINE_CITATION_RE = re.compile(
    r"\(lines?\s+\d+(?:(?:\s*[-–]\s*|\s+and\s+)\d+)?\)",
    re.IGNORECASE,
)

# Matches ADR-NNNN references. Group 1 = the 4-digit number.
_ADR_REF_RE = re.compile(r"ADR[- ](\d{4})")

# Matches an ADR-NNNN reference that is followed by a title annotation:
#   ADR-0006 (Title)          — parenthesized title
#   ADR-0006 — Title          — em-dash title
#   ADR-0006: Title           — heading-style (only in # headings)
_ADR_REF_WITH_TITLE_RE = re.compile(r"ADR[- ]\d{4}\s*(?:\(|—)")

# Captures the title text from a parenthesized annotation: ADR-0006 (Title Here)
# Supports one level of nested parentheses, e.g. ADR-0004 (Title (sub-info)).
_ADR_PAREN_TITLE_RE = re.compile(r"ADR[- ]\d{4}\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)")
# Captures the title text from an em-dash annotation: ADR-0006 — Title Here
# Title runs to end of line or next sentence boundary.
# Uses "\.\s" (period+space) rather than bare "\." to avoid stopping inside
# titles that contain dots (e.g. "Pi.dev" in ADR-0004's title).
_ADR_EMDASH_TITLE_RE = re.compile(r"ADR[- ]\d{4}\s*—\s*(.+?)(?:\.\s|,|;|$)")


class ADRPreValidator:
    """Validates ADR structure before sending to the council."""

    def validate(
        self,
        content: str,
        all_adrs: list[tuple[int, str, str, str]] | None = None,
    ) -> ADRValidationResult:
        """Run all validation checks on an ADR.

        Args:
            content: The full markdown content of the ADR.
            all_adrs: Optional list of (number, title, content, filename) for cross-reference checks.

        Returns:
            ADRValidationResult with any issues found.
        """
        result = ADRValidationResult()
        self._check_status_field(content, result)
        self._check_required_sections(content, result)
        self._check_empty_sections(content, result)
        self._check_supersession(content, all_adrs or [], result)
        self._check_volatile_line_citations(content, result)
        self._check_bare_adr_references(content, all_adrs or [], result)
        return result

    def _check_status_field(self, content: str, result: ADRValidationResult) -> None:
        """Check that the Status field exists and is a known value."""
        match = _STATUS_RE.search(content)
        if not match:
            result.issues.append(
                ADRValidationIssue(
                    code="missing_status",
                    message="ADR is missing a **Status:** field",
                    fixable=True,
                )
            )

    def _check_required_sections(
        self, content: str, result: ADRValidationResult
    ) -> None:
        """Check that all required sections are present."""
        for section in _REQUIRED_SECTIONS:
            if not re.search(
                rf"^{re.escape(section)}\s*$", content, re.IGNORECASE | re.MULTILINE
            ):
                result.issues.append(
                    ADRValidationIssue(
                        code=f"missing_section_{section.replace('## ', '').lower()}",
                        message=f"ADR is missing required section: {section}",
                        fixable=False,
                    )
                )

    def _check_empty_sections(self, content: str, result: ADRValidationResult) -> None:
        """Check that required sections have non-trivial content."""
        for section in _REQUIRED_SECTIONS:
            pattern = re.compile(
                rf"^{re.escape(section)}[ \t]*\n(.*?)(?=^##\s|\Z)",
                re.DOTALL | re.MULTILINE | re.IGNORECASE,
            )
            match = pattern.search(content)
            if match:
                body = match.group(1).strip()
                if not body:
                    section_name = section.replace("## ", "")
                    result.issues.append(
                        ADRValidationIssue(
                            code=f"empty_section_{section_name.lower()}",
                            message=f"Section '{section_name}' is present but empty",
                            fixable=False,
                        )
                    )

    def _check_volatile_line_citations(
        self, content: str, result: ADRValidationResult
    ) -> None:
        """Flag line-number citations that become stale as source files change."""
        matches = _LINE_CITATION_RE.findall(content)
        if matches:
            result.issues.append(
                ADRValidationIssue(
                    code="volatile_line_citation",
                    message=(
                        f"ADR contains {len(matches)} line-number citation(s) "
                        f"that will become stale as source files change — "
                        f"use function/class names only"
                    ),
                    fixable=True,
                )
            )

    def _check_supersession(
        self,
        content: str,
        all_adrs: list[tuple[int, str, str, str]],
        result: ADRValidationResult,
    ) -> None:
        """Check supersession references for existence, reciprocity, and status coherence."""
        supersedes_refs = _SUPERSEDE_RE.findall(content)
        superseded_by_refs = _SUPERSEDED_BY_RE.findall(content)

        # De-conflict: if the same number appears in both directions (circular reference),
        # only process it via the "superseded by" path to avoid double-reporting.
        # Deduplicate both lists so repeated mentions don't generate duplicate issues.
        superseded_by_refs = list(dict.fromkeys(superseded_by_refs))
        supersedes_only = list(
            dict.fromkeys(r for r in supersedes_refs if r not in superseded_by_refs)
        )

        if not supersedes_only and not superseded_by_refs:
            return

        existing_numbers = {num for num, *_ in all_adrs}
        adr_contents: dict[int, str] = {num: c for num, _, c, _ in all_adrs}

        # Extract this ADR's number and status
        heading_match = re.search(r"^#\s+ADR[- ](\d{4})", content, re.MULTILINE)
        self_number = int(heading_match.group(1)) if heading_match else None
        status_match = _STATUS_RE.search(content)
        self_status = status_match.group(1).lower() if status_match else None

        for ref_str in supersedes_only:
            ref_num = int(ref_str)
            if ref_num not in existing_numbers:
                result.issues.append(
                    ADRValidationIssue(
                        code="invalid_supersession",
                        message=(
                            f"ADR references superseding ADR-{ref_num:04d} "
                            f"but that ADR does not exist"
                        ),
                        fixable=False,
                    )
                )
                continue

            # Bidirectional check: target must say "Superseded by <self>"
            if self_number is not None and ref_num in adr_contents:
                target_content = adr_contents[ref_num]
                target_back_refs = _SUPERSEDED_BY_RE.findall(target_content)
                if str(self_number).zfill(4) not in target_back_refs:
                    result.issues.append(
                        ADRValidationIssue(
                            code="missing_reciprocal_supersession",
                            message=(
                                f"ADR supersedes ADR-{ref_num:04d} but "
                                f"ADR-{ref_num:04d} does not contain a reciprocal "
                                f"'Superseded by ADR-{self_number:04d}' reference"
                            ),
                            fixable=True,
                        )
                    )

            # Status coherence: Proposed cannot supersede a settled ADR
            if self_status == "proposed" and ref_num in adr_contents:
                target_status_match = _STATUS_RE.search(adr_contents[ref_num])
                if target_status_match:
                    target_status = target_status_match.group(1).lower()
                    if target_status in _SETTLED_STATUSES:
                        result.issues.append(
                            ADRValidationIssue(
                                code="status_incoherent_supersession",
                                message=(
                                    f"A Proposed ADR cannot supersede "
                                    f"ADR-{ref_num:04d} which has "
                                    f"{target_status_match.group(1)} status — "
                                    f"use 'Will supersede (pending acceptance)' "
                                    f"or accept this ADR first"
                                ),
                                fixable=True,
                            )
                        )

        for ref_str in superseded_by_refs:
            ref_num = int(ref_str)
            if ref_num not in existing_numbers:
                result.issues.append(
                    ADRValidationIssue(
                        code="invalid_supersession",
                        message=(
                            f"ADR references superseded by ADR-{ref_num:04d} "
                            f"but that ADR does not exist"
                        ),
                        fixable=False,
                    )
                )
                continue

            # Bidirectional check: superseding ADR must say "Supersedes <self>"
            if self_number is not None and ref_num in adr_contents:
                target_content = adr_contents[ref_num]
                target_supersedes = _SUPERSEDE_RE.findall(target_content)
                target_superseded_by = _SUPERSEDED_BY_RE.findall(target_content)
                target_supersedes_only = [
                    r for r in target_supersedes if r not in target_superseded_by
                ]
                if str(self_number).zfill(4) not in target_supersedes_only:
                    result.issues.append(
                        ADRValidationIssue(
                            code="missing_reciprocal_supersession",
                            message=(
                                f"ADR is superseded by ADR-{ref_num:04d} but "
                                f"ADR-{ref_num:04d} does not contain a reciprocal "
                                f"'Supersedes ADR-{self_number:04d}' reference"
                            ),
                            fixable=True,
                        )
                    )

                # Status coherence: superseding ADR should not be Proposed
                # when this ADR is already settled
                if self_status in _SETTLED_STATUSES:
                    target_status_match = _STATUS_RE.search(target_content)
                    if target_status_match:
                        target_status = target_status_match.group(1).lower()
                        if target_status == "proposed":
                            result.issues.append(
                                ADRValidationIssue(
                                    code="status_incoherent_supersession",
                                    message=(
                                        f"ADR-{ref_num:04d} is Proposed but claims "
                                        f"to supersede this {self_status.capitalize()}-status ADR — "
                                        f"ADR-{ref_num:04d} must be at least Accepted "
                                        f"before supersession takes effect"
                                    ),
                                    fixable=True,
                                )
                            )

    def _check_bare_adr_references(
        self,
        content: str,
        all_adrs: list[tuple[int, str, str, str]],
        result: ADRValidationResult,
    ) -> None:
        """Check that ADR cross-references include the referenced ADR's title.

        Bare references like ``ADR-0006`` are opaque; the reader cannot tell
        what the referenced ADR covers without opening it.  Each cross-reference
        should include the title in parentheses — e.g. ``ADR-0006 (RepoRuntime
        Isolation Architecture)`` — or after an em-dash.

        When *all_adrs* is provided, also validates that:
        - Referenced ADR numbers actually exist.
        - Title annotations match the real ADR title.

        Exceptions: the ADR's own heading line (``# ADR-NNNN: Title``) and
        markdown table rows (which may contain example/illustration text).
        """
        # Build lookup from ADR number → title for existence and title checks
        adr_titles: dict[int, str] = {num: title for num, title, *_ in all_adrs}

        # Extract self-number from the heading to skip self-references
        heading_match = re.search(r"^#\s+ADR[- ](\d{4})", content, re.MULTILINE)
        self_number = heading_match.group(1) if heading_match else None

        bare_numbers: set[str] = set()
        nonexistent_numbers: set[str] = set()
        mismatched: dict[str, tuple[str, str]] = {}  # num → (cited_title, real_title)

        for line in content.splitlines():
            # Skip heading lines (contain the ADR's own title after ':')
            if line.lstrip().startswith("#"):
                continue
            # Skip markdown table rows (may contain example text)
            if "|" in line:
                continue

            for match in _ADR_REF_RE.finditer(line):
                ref_num = match.group(1)
                # Skip self-references
                if ref_num == self_number:
                    continue
                # Check if this specific occurrence has a title annotation
                rest = line[match.start() :]
                has_title = _ADR_REF_WITH_TITLE_RE.match(rest)
                if not has_title:
                    bare_numbers.add(ref_num)
                else:
                    # Validate the cited title against the real ADR title
                    self._check_title_accuracy(ref_num, rest, adr_titles, mismatched)

                # Check existence when all_adrs is available
                if adr_titles and int(ref_num) not in adr_titles:
                    nonexistent_numbers.add(ref_num)

        for ref_num in sorted(bare_numbers):
            result.issues.append(
                ADRValidationIssue(
                    code="bare_adr_reference",
                    message=(
                        f"ADR-{ref_num} is referenced without its title. "
                        f"Add the title in parentheses, e.g. "
                        f"ADR-{ref_num} (Title Here)"
                    ),
                    fixable=True,
                )
            )

        for ref_num in sorted(nonexistent_numbers):
            result.issues.append(
                ADRValidationIssue(
                    code="nonexistent_adr_reference",
                    message=(
                        f"ADR-{ref_num} is referenced but does not exist "
                        f"in the ADR index"
                    ),
                    fixable=False,
                )
            )

        for ref_num in sorted(mismatched):
            cited, real = mismatched[ref_num]
            result.issues.append(
                ADRValidationIssue(
                    code="mismatched_adr_title",
                    message=(
                        f"ADR-{ref_num} title mismatch: cited as "
                        f'"{cited}" but the actual title is "{real}"'
                    ),
                    fixable=True,
                )
            )

    @staticmethod
    def _check_title_accuracy(
        ref_num: str,
        text: str,
        adr_titles: dict[int, str],
        mismatched: dict[str, tuple[str, str]],
    ) -> None:
        """Compare a cited title annotation against the real ADR title."""
        num = int(ref_num)
        if num not in adr_titles:
            return  # Can't verify — nonexistence is flagged separately.
        real_title = adr_titles[num]

        # Extract the cited title from either parenthesized or em-dash form
        cited_title: str | None = None
        paren_match = _ADR_PAREN_TITLE_RE.match(text)
        if paren_match:
            cited_title = paren_match.group(1).strip()
        else:
            emdash_match = _ADR_EMDASH_TITLE_RE.match(text)
            if emdash_match:
                cited_title = emdash_match.group(1).strip()

        if not cited_title:
            return

        # For em-dash form, the captured text may include trailing words
        # (e.g. "Title for details") — check if the real title is a prefix.
        cited_lower = cited_title.lower()
        real_lower = real_title.lower()
        if cited_lower == real_lower:
            return
        if cited_lower.startswith(real_lower):
            return
        mismatched[ref_num] = (cited_title, real_title)
