"""Pre-review validation for ADRs — catches structural defects before council."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


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

# Matches "requires amending ADR-NNNN" notes that reference another ADR.
# These notes become stale once the referenced ADR's amendment is completed.
# Group 1 = the 4-digit ADR number.
_REQUIRES_AMENDING_ADR_RE = re.compile(
    r"requires\s+amending\s+ADR[- ]?(\d{4})",
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

# Matches source file + symbol citations like `src/config.py:_resolve_paths` or
# `src/config.py:HydraFlowConfig`.  Group 1 = file path, Group 2 = symbol name.
# Symbol must start with a letter or underscore (not a digit) to exclude line numbers.
_SOURCE_SYMBOL_RE = re.compile(r"`(src/[^`:\s]+\.py):([A-Za-z_]\w*)`")

# Matches inline line-number citations in the `src/file.py:DIGITS` format.
# These are a variant of volatile line citations that embed the number in the
# symbol position of a source reference.  Group 1 = file path, Group 2 = digits.
_INLINE_LINE_NUM_RE = re.compile(r"`(src/[^`:\s]+\.py):(\d[\d,]*)`")


class ADRPreValidator:
    """Validates ADR structure before sending to the council."""

    def validate(
        self,
        content: str,
        all_adrs: list[tuple[int, str, str, str]] | None = None,
        *,
        repo_root: Path | None = None,
    ) -> ADRValidationResult:
        """Run all validation checks on an ADR.

        Args:
            content: The full markdown content of the ADR.
            all_adrs: Optional list of (number, title, content, filename) for cross-reference checks.
            repo_root: Optional repo root path for verifying source symbol references.

        Returns:
            ADRValidationResult with any issues found.
        """
        result = ADRValidationResult()
        self._check_status_field(content, result)
        self._check_required_sections(content, result)
        self._check_empty_sections(content, result)
        self._check_number_collision(content, all_adrs or [], result)
        self._check_supersession(content, all_adrs or [], result)
        self._check_volatile_line_citations(content, result)
        self._check_stale_amending_notes(content, all_adrs or [], result)
        self._check_bare_adr_references(content, all_adrs or [], result)
        self._check_source_function_refs(content, repo_root, result)
        self._check_cross_reference_titles(content, all_adrs or [], result)
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

    def _check_number_collision(
        self,
        content: str,
        all_adrs: list[tuple[int, str, str, str]],
        result: ADRValidationResult,
    ) -> None:
        """Detect ADR number collisions — multiple ADRs sharing the same number."""
        if not all_adrs:
            return

        heading_match = re.search(r"^#\s+ADR[- ](\d{4})", content, re.MULTILINE)
        if not heading_match:
            return

        self_number = int(heading_match.group(1))
        same_number = [
            (num, title, fname)
            for num, title, _content, fname in all_adrs
            if num == self_number
        ]
        if len(same_number) > 1:
            other_titles = [
                title
                for _num, title, fname in same_number
                if fname not in content  # rough heuristic: skip self
            ]
            result.issues.append(
                ADRValidationIssue(
                    code="number_collision",
                    message=(
                        f"ADR-{self_number:04d} number collision: "
                        f"{len(same_number)} ADRs share this number. "
                        f"Other ADRs: {', '.join(other_titles[:3])}"
                        + (
                            f" (+{len(other_titles) - 3} more)"
                            if len(other_titles) > 3
                            else ""
                        )
                    ),
                    fixable=False,
                )
            )

    def _check_volatile_line_citations(
        self, content: str, result: ADRValidationResult
    ) -> None:
        """Flag line-number citations that become stale as source files change."""
        paren_matches = _LINE_CITATION_RE.findall(content)
        inline_matches = _INLINE_LINE_NUM_RE.findall(content)
        total = len(paren_matches) + len(inline_matches)
        if total:
            result.issues.append(
                ADRValidationIssue(
                    code="volatile_line_citation",
                    message=(
                        f"ADR contains {total} line-number citation(s) "
                        f"that will become stale as source files change — "
                        f"use function/class names only"
                    ),
                    fixable=True,
                )
            )

    def _check_stale_amending_notes(
        self,
        content: str,
        all_adrs: list[tuple[int, str, str, str]],
        result: ADRValidationResult,
    ) -> None:
        """Flag 'requires amending ADR-NNNN' notes where the amendment is already done.

        Uses **Status: Accepted** on the referenced ADR as a heuristic for
        "the amendment was completed."  This is reliable when the workflow
        transitions a referenced ADR from Proposed → Accepted after applying
        the mandated changes.  It will not fire for referenced ADRs that remain
        Proposed even after being content-amended (a false negative), and may
        fire prematurely if a note is written pointing at an ADR that was
        already Accepted before the amendment was applied (a false positive).
        """
        # Build a lookup: ADR number → status extracted from content
        adr_status: dict[int, str] = {}
        for num, _title, adr_content, _filename in all_adrs:
            status_match = _STATUS_RE.search(adr_content)
            if status_match:
                adr_status[num] = status_match.group(1)

        seen: set[int] = set()
        for match in _REQUIRES_AMENDING_ADR_RE.finditer(content):
            ref_num = int(match.group(1))
            # Skip if the referenced ADR doesn't exist in the index
            if ref_num not in adr_status:
                continue
            # Deduplicate: one issue per ADR number, even if mentioned multiple times
            if ref_num in seen:
                continue
            # Only flag if the referenced ADR is Accepted (amendment completed)
            if adr_status[ref_num].lower() == "accepted":
                seen.add(ref_num)
                result.issues.append(
                    ADRValidationIssue(
                        code="stale_amendment_note",
                        message=(
                            f"'Requires amending ADR-{ref_num:04d}' is stale — "
                            f"ADR-{ref_num:04d} already has Status: Accepted. "
                            f"Update or remove the note."
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
        # Build lookup from ADR number → titles for existence and title checks.
        # Use list values to handle multiple ADRs sharing the same number.
        adr_titles: dict[int, list[str]] = {}
        for num, title, *_ in all_adrs:
            adr_titles.setdefault(num, []).append(title)

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

    def _check_source_function_refs(
        self,
        content: str,
        repo_root: Path | None,
        result: ADRValidationResult,
    ) -> None:
        """Verify that function/class names cited in source references actually exist.

        Scans for backtick-quoted references like `src/config.py:_resolve_paths`
        and greps the referenced file for a matching ``def`` or ``class`` definition.
        Skips gracefully when *repo_root* is None or the referenced file doesn't exist.
        """
        if repo_root is None:
            return

        # Collect unique (file, symbol) pairs
        refs: dict[tuple[str, str], None] = {}
        for match in _SOURCE_SYMBOL_RE.finditer(content):
            file_path, symbol = match.group(1), match.group(2)
            refs[(file_path, symbol)] = None

        # Cache file contents to avoid re-reading
        file_cache: dict[str, str | None] = {}

        for file_path, symbol in refs:
            if file_path not in file_cache:
                full_path = repo_root / file_path
                try:
                    file_cache[file_path] = full_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    file_cache[file_path] = None

            source = file_cache[file_path]
            if source is None:
                # File doesn't exist or is unreadable — skip silently
                continue

            # Match both top-level and indented definitions (class methods, async defs)
            pattern = re.compile(
                rf"^\s*(?:async\s+)?(?:def|class)\s+{re.escape(symbol)}\b", re.MULTILINE
            )
            if not pattern.search(source):
                result.issues.append(
                    ADRValidationIssue(
                        code="phantom_source_symbol",
                        message=(
                            f"`{file_path}:{symbol}` is cited but "
                            f"`{symbol}` is not defined as a function or class in `{file_path}`"
                        ),
                        fixable=False,
                    )
                )

    @staticmethod
    def _word_prefix_overlap(cited: str, real: str, min_words: int = 3) -> bool:
        """Check if *cited* and *real* share a significant word-prefix.

        Strips trailing punctuation from each word so that ``"routing"``
        matches ``"routing,"`` — this handles em-dash titles where the regex
        captures trailing prose (e.g. ``"Title for details."``) while the real
        title continues with different words (e.g. ``"Title, Not Just X"``).

        Returns True when the shared word-prefix is at least *min_words* long
        and shorter than the real title (i.e. the cited text is an abbreviation).
        """
        strip = str.maketrans("", "", ".,;:!?")
        cited_words = [w.translate(strip) for w in cited.lower().split()]
        real_words = [w.translate(strip) for w in real.lower().split()]
        common = 0
        for cw, rw in zip(cited_words, real_words, strict=False):
            if cw == rw:
                common += 1
            else:
                break
        return common >= min_words and common < len(real_words)

    @staticmethod
    def _extract_cited_title(text: str) -> str | None:
        """Extract the cited title from parenthesized or em-dash annotation."""
        paren_match = _ADR_PAREN_TITLE_RE.match(text)
        if paren_match:
            return paren_match.group(1).strip()
        emdash_match = _ADR_EMDASH_TITLE_RE.match(text)
        if emdash_match:
            return emdash_match.group(1).strip()
        return None

    @staticmethod
    def _check_title_accuracy(
        ref_num: str,
        text: str,
        adr_titles: dict[int, list[str]],
        mismatched: dict[str, tuple[str, str]],
    ) -> None:
        """Compare a cited title annotation against the real ADR title(s).

        Handles multiple ADRs sharing the same number by checking against
        all titles for that number.
        """
        num = int(ref_num)
        if num not in adr_titles:
            return  # Can't verify — nonexistence is flagged separately.
        titles = adr_titles[num]

        cited_title = ADRPreValidator._extract_cited_title(text)
        if not cited_title:
            return

        cited_lower = cited_title.lower()
        for real_title in titles:
            real_lower = real_title.lower()
            if cited_lower == real_lower:
                return
            # For em-dash form, the captured text may include trailing words
            # (e.g. "Title for details") — check if a real title is a prefix.
            if cited_lower.startswith(real_lower):
                return
            # Abbreviated case: cited is a prefix of the real title.
            # Let _check_cross_reference_titles flag it as abbreviated_cross_ref_title
            # to avoid double-flagging with mismatched_adr_title.
            if real_lower.startswith(cited_lower):
                return
            # Em-dash form may capture trailing prose (e.g. "Title for details.")
            # so the simple prefix check fails.  Fall back to word-prefix overlap.
            if ADRPreValidator._word_prefix_overlap(cited_lower, real_lower):
                return
        # No match against any title for this number
        mismatched[ref_num] = (cited_title, titles[0])

    def _check_cross_reference_titles(
        self,
        content: str,
        all_adrs: list[tuple[int, str, str, str]],
        result: ADRValidationResult,
    ) -> None:
        """Check that cross-reference titles use the full ADR title.

        When multiple ADRs share the same number, abbreviated titles are
        ambiguous.  This check flags cited titles that are a prefix of a
        real title but not an exact match.
        """
        if not all_adrs:
            return

        # Build multi-value lookup: number → list of titles
        adr_titles: dict[int, list[str]] = {}
        for num, title, *_ in all_adrs:
            adr_titles.setdefault(num, []).append(title)

        # Extract self-number from the heading to skip self-references
        heading_match = re.search(r"^#\s+ADR[- ](\d{4})", content, re.MULTILINE)
        self_number: int | None = int(heading_match.group(1)) if heading_match else None

        for line in content.splitlines():
            if line.lstrip().startswith("#") or "|" in line:
                continue
            for match in _ADR_REF_RE.finditer(line):
                ref_num = int(match.group(1))
                if ref_num == self_number:
                    continue
                if ref_num not in adr_titles:
                    continue  # Nonexistence is flagged by _check_bare_adr_references
                rest = line[match.start() :]
                cited_title = ADRPreValidator._extract_cited_title(rest)
                if not cited_title:
                    continue  # bare reference — handled by _check_bare_adr_references
                titles = adr_titles[ref_num]
                cited_lower = cited_title.lower()

                # Exact match against any title — pass
                if any(cited_lower == t.lower() for t in titles):
                    continue

                # Abbreviated: cited is a prefix of a real title, or shares
                # a significant word-prefix (handles em-dash trailing prose)
                abbreviated_of = [
                    t
                    for t in titles
                    if t.lower().startswith(cited_lower)
                    or ADRPreValidator._word_prefix_overlap(cited_lower, t)
                ]
                if abbreviated_of:
                    result.issues.append(
                        ADRValidationIssue(
                            code="abbreviated_cross_ref_title",
                            message=(
                                f"ADR-{ref_num:04d} cross-reference uses abbreviated "
                                f'title "{cited_title}" — use the full title '
                                f'"{abbreviated_of[0]}"'
                            ),
                            fixable=True,
                        )
                    )
