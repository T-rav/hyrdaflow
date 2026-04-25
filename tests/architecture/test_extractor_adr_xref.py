from arch.extractors.adr_xref import extract_adr_refs


def test_extracts_module_symbol_and_path_refs(fixture_src_tree):
    root = fixture_src_tree(
        {
            "docs/adr/0001-thing.md": """
            # ADR-0001: Thing

            Reference src/foo.py and another at src/bar.py:Bar.
            See also `src/baz.py:baz_function`.
        """,
            "docs/adr/0002-other.md": "# ADR-0002: Other\n\nNo refs here.\n",
        }
    )
    idx = extract_adr_refs(root / "docs/adr")
    by_id = {r.adr_id: r for r in idx.adr_to_modules}
    assert "ADR-0001" in by_id
    assert "ADR-0002" in by_id
    refs = by_id["ADR-0001"].cited_modules
    assert "src.foo" in refs
    assert "src.bar" in refs
    assert "src.baz" in refs
    assert by_id["ADR-0002"].cited_modules == []


def test_skips_readme_and_template(fixture_src_tree):
    root = fixture_src_tree(
        {
            "docs/adr/README.md": "# Index\n",
            "docs/adr/0001-thing.md": "# ADR-0001\n",
        }
    )
    idx = extract_adr_refs(root / "docs/adr")
    assert [r.adr_id for r in idx.adr_to_modules] == ["ADR-0001"]
