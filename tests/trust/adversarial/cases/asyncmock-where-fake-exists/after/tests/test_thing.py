from unittest.mock import AsyncMock


def test_github_integration():
    gh = AsyncMock()
    gh.create_pr = AsyncMock(return_value=42)
    # ... call code under test ...
    assert gh.create_pr.await_count == 1
