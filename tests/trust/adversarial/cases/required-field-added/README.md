# required-field-added

A new required field `reporter: str` was added to a Pydantic model
without a default. Every existing construction site of `Issue(...)` that
omitted `reporter` now raises a ValidationError at runtime. Diff sanity
must flag the missing default on a required field.

Keyword: required field
