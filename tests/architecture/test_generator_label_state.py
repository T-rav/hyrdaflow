from arch._models import LabelStateMachine, LabelTransition
from arch.generators.label_state import render_label_state


def test_renders_state_diagram_v2_block():
    sm = LabelStateMachine(
        states=["a", "b", "c"],
        transitions=[
            LabelTransition(from_state="a", to_state="b", trigger="trig1"),
            LabelTransition(from_state="b", to_state="c", trigger="trig2"),
        ],
    )
    md = render_label_state(sm)
    assert "stateDiagram-v2" in md
    assert "a --> b" in md
    assert "b --> c" in md
    assert "trig1" in md


def test_handles_empty_state_machine():
    md = render_label_state(LabelStateMachine())
    assert "no transitions" in md.lower()
