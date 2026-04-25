from arch._models import ADRRef, ADRRefIndex
from arch.generators.adr_cross_reference import render_adr_cross_reference


def test_emits_forward_and_reverse_tables():
    idx = ADRRefIndex(
        adr_to_modules=[
            ADRRef(adr_id="ADR-0001", cited_modules=["src.foo", "src.bar"]),
            ADRRef(adr_id="ADR-0002", cited_modules=["src.foo"]),
        ]
    )
    md = render_adr_cross_reference(idx)
    assert "## ADR → Modules" in md
    assert "## Module → ADRs" in md
    assert "src.foo" in md
    assert "ADR-0001" in md
    # src.foo is cited by both ADRs — assert both appear in the reverse section
    reverse_section = md.split("## Module → ADRs", 1)[1]
    assert "ADR-0001" in reverse_section
    assert "ADR-0002" in reverse_section
