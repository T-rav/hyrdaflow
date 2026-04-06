"""Tests for PRListItem author field."""

from models import PRListItem


def test_pr_list_item_has_author_field():
    item = PRListItem(pr=42, author="dependabot[bot]")
    assert item.author == "dependabot[bot]"


def test_pr_list_item_author_defaults_empty():
    item = PRListItem(pr=42)
    assert item.author == ""
