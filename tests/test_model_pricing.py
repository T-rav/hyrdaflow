"""Tests for model_pricing.py."""

from __future__ import annotations

import json

from model_pricing import ModelPricingTable, ModelRate, load_pricing


class TestModelRate:
    def test_estimate_cost_input_only(self):
        rate = ModelRate(
            input_cost_per_million=3.0,
            output_cost_per_million=15.0,
            cache_write_cost_per_million=0.0,
            cache_read_cost_per_million=0.0,
        )
        cost = rate.estimate_cost(input_tokens=1_000_000, output_tokens=0)
        assert cost == 3.0

    def test_estimate_cost_output_only(self):
        rate = ModelRate(
            input_cost_per_million=3.0,
            output_cost_per_million=15.0,
            cache_write_cost_per_million=0.0,
            cache_read_cost_per_million=0.0,
        )
        cost = rate.estimate_cost(input_tokens=0, output_tokens=1_000_000)
        assert cost == 15.0

    def test_estimate_cost_with_cache(self):
        rate = ModelRate(
            input_cost_per_million=3.0,
            output_cost_per_million=15.0,
            cache_write_cost_per_million=3.75,
            cache_read_cost_per_million=0.30,
        )
        cost = rate.estimate_cost(
            input_tokens=500_000,
            output_tokens=100_000,
            cache_write_tokens=200_000,
            cache_read_tokens=300_000,
        )
        expected = (
            3.0 * 500_000 + 15.0 * 100_000 + 3.75 * 200_000 + 0.30 * 300_000
        ) / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_frozen_dataclass(self):
        rate = ModelRate(
            input_cost_per_million=3.0,
            output_cost_per_million=15.0,
            cache_write_cost_per_million=0.0,
            cache_read_cost_per_million=0.0,
        )
        try:
            rate.input_cost_per_million = 999  # type: ignore[misc]
            raise AssertionError("Should be frozen")
        except AttributeError:
            pass


class TestModelPricingTable:
    def _write_asset(self, tmp_path, data):
        path = tmp_path / "pricing.json"
        path.write_text(json.dumps(data))
        return path

    def test_load_and_get_rate_by_exact_id(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {
                    "claude-sonnet-4-20250514": {
                        "input_cost_per_million": 3.0,
                        "output_cost_per_million": 15.0,
                        "aliases": ["sonnet"],
                    }
                },
            },
        )
        table = ModelPricingTable(path)
        rate = table.get_rate("claude-sonnet-4-20250514")
        assert rate is not None
        assert rate.input_cost_per_million == 3.0
        assert rate.output_cost_per_million == 15.0
        assert rate.cache_write_cost_per_million == 0.0

    def test_get_rate_by_alias(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {
                    "claude-opus-4-20250514": {
                        "input_cost_per_million": 15.0,
                        "output_cost_per_million": 75.0,
                        "aliases": ["opus", "claude-4-opus"],
                    }
                },
            },
        )
        table = ModelPricingTable(path)
        rate = table.get_rate("opus")
        assert rate is not None
        assert rate.output_cost_per_million == 75.0

    def test_get_rate_case_insensitive(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {
                    "claude-3-5-haiku-20241022": {
                        "input_cost_per_million": 0.8,
                        "output_cost_per_million": 4.0,
                        "aliases": ["haiku"],
                    }
                },
            },
        )
        table = ModelPricingTable(path)
        assert table.get_rate("HAIKU") is not None
        assert table.get_rate("Haiku") is not None

    def test_get_rate_fuzzy_substring_match(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {
                    "claude-sonnet-4-20250514": {
                        "input_cost_per_million": 3.0,
                        "output_cost_per_million": 15.0,
                        "aliases": ["sonnet"],
                    }
                },
            },
        )
        table = ModelPricingTable(path)
        rate = table.get_rate("claude-sonnet-4-20250514-extended")
        assert rate is not None
        assert rate.input_cost_per_million == 3.0

    def test_get_rate_unknown_returns_none(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {},
            },
        )
        table = ModelPricingTable(path)
        assert table.get_rate("unknown-model") is None

    def test_estimate_cost_delegates_to_rate(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {
                    "claude-sonnet-4-20250514": {
                        "input_cost_per_million": 3.0,
                        "output_cost_per_million": 15.0,
                        "aliases": ["sonnet"],
                    }
                },
            },
        )
        table = ModelPricingTable(path)
        cost = table.estimate_cost("sonnet", input_tokens=1000, output_tokens=500)
        expected = (3.0 * 1000 + 15.0 * 500) / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_estimate_cost_unknown_returns_none(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {},
            },
        )
        table = ModelPricingTable(path)
        assert (
            table.estimate_cost("unknown", input_tokens=100, output_tokens=50) is None
        )

    def test_missing_file_returns_none(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        table = ModelPricingTable(path)
        assert table.get_rate("anything") is None

    def test_corrupt_json_handled_gracefully(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json")
        table = ModelPricingTable(path)
        assert table.get_rate("anything") is None

    def test_skips_entry_missing_required_fields(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {
                    "incomplete": {"input_cost_per_million": 1.0},
                },
            },
        )
        table = ModelPricingTable(path)
        assert table.get_rate("incomplete") is None

    def test_lazy_loading(self, tmp_path):
        path = self._write_asset(
            tmp_path,
            {
                "schema_version": 1,
                "models": {
                    "model-a": {
                        "input_cost_per_million": 1.0,
                        "output_cost_per_million": 2.0,
                    },
                },
            },
        )
        table = ModelPricingTable(path)
        assert not table._loaded
        table.get_rate("model-a")
        assert table._loaded


class TestLoadPricing:
    def test_returns_table_instance(self, tmp_path):
        path = tmp_path / "pricing.json"
        path.write_text(json.dumps({"schema_version": 1, "models": {}}))
        table = load_pricing(path)
        assert isinstance(table, ModelPricingTable)
