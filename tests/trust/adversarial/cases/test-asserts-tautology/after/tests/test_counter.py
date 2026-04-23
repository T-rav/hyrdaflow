def test_reset_exists():
    from src.counter import Counter

    c = Counter()
    c.reset()
    # Tautology — doesn't actually verify behavior.
    assert c is not None
