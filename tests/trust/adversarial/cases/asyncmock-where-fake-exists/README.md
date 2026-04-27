# asyncmock-where-fake-exists

An `AsyncMock` is used to stand in for the GitHub adapter when a stateful
fake `FakeGitHub` already exists under `src/mockworld/fakes/fake_github.py`.
Per the HydraFlow avoided-patterns list, AsyncMock substitution for
adapters with an existing stateful fake is a bug — test-adequacy must
flag it.

Keyword: AsyncMock
