def parse(s):
    if not s:
        raise ValueError("empty input")
    if not s.lstrip("-").isdigit():
        raise ValueError(f"not numeric: {s!r}")
    return int(s)
