def test_parse_basic():
    from src.parser import parse

    assert parse("3") == 3
