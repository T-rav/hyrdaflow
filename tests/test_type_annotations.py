"""Tests for type annotation tightening (issue #6309).

Verifies that public functions and model fields use parameterized dict types
instead of bare ``dict`` or ``dict | None``, and that ``store_lifecycle``
has an explicit return type annotation.
"""

from __future__ import annotations

import types
import typing
from collections.abc import AsyncGenerator


class TestStoreLifecycleReturnType:
    """store_lifecycle must be annotated -> AsyncGenerator[None, None]."""

    def test_return_annotation_is_async_generator(self) -> None:
        from phase_utils import store_lifecycle

        hints = typing.get_type_hints(store_lifecycle)
        ret = hints["return"]
        # Should be AsyncGenerator[None, None]
        origin = typing.get_origin(ret)
        assert origin is AsyncGenerator, f"Expected AsyncGenerator origin, got {origin}"
        args = typing.get_args(ret)
        # With `from __future__ import annotations`, None resolves as the
        # value None rather than NoneType — accept either form.
        expected = ((type(None), type(None)), (None, None))
        assert args in expected, f"Expected None type args, got {args}"


class TestPortsLoadStateReturnType:
    """StateBackendPort.load_state must return dict[str, object] | None."""

    def test_load_state_return_is_parameterized_dict_or_none(self) -> None:
        from ports import StateBackendPort

        hints = typing.get_type_hints(StateBackendPort.load_state)
        ret = hints["return"]
        # Should be dict[str, object] | None  (a Union)
        origin = typing.get_origin(ret)
        assert origin is types.UnionType, f"Expected UnionType, got {origin}"
        args = typing.get_args(ret)
        # One arm is dict[str, object], the other is NoneType
        dict_args = [a for a in args if typing.get_origin(a) is dict]
        none_args = [a for a in args if a is type(None)]
        assert len(dict_args) == 1, f"Expected one dict arm, got {dict_args}"
        assert len(none_args) == 1, f"Expected one NoneType arm, got {none_args}"
        assert typing.get_args(dict_args[0]) == (str, object), (
            f"Expected dict[str, object], got dict{typing.get_args(dict_args[0])}"
        )


class TestDoltBackendReturnTypes:
    """DoltBackend.load_state and get_session must return dict[str, object] | None."""

    def test_load_state_return_is_parameterized(self) -> None:
        from dolt_backend import DoltBackend

        hints = typing.get_type_hints(DoltBackend.load_state)
        ret = hints["return"]
        origin = typing.get_origin(ret)
        assert origin is types.UnionType
        dict_args = [a for a in typing.get_args(ret) if typing.get_origin(a) is dict]
        assert len(dict_args) == 1
        assert typing.get_args(dict_args[0]) == (str, object)

    def test_get_session_return_is_parameterized(self) -> None:
        from dolt_backend import DoltBackend

        hints = typing.get_type_hints(DoltBackend.get_session)
        ret = hints["return"]
        origin = typing.get_origin(ret)
        assert origin is types.UnionType
        dict_args = [a for a in typing.get_args(ret) if typing.get_origin(a) is dict]
        assert len(dict_args) == 1
        assert typing.get_args(dict_args[0]) == (str, object)


class TestDiagnosticRunnerReturnType:
    """_extract_json must return dict[str, object] | None."""

    def test_extract_json_return_is_parameterized(self) -> None:
        from diagnostic_runner import _extract_json

        hints = typing.get_type_hints(_extract_json)
        ret = hints["return"]
        origin = typing.get_origin(ret)
        assert origin is types.UnionType
        dict_args = [a for a in typing.get_args(ret) if typing.get_origin(a) is dict]
        assert len(dict_args) == 1
        assert typing.get_args(dict_args[0]) == (str, object)


class TestEpicReturnType:
    """_get_release_data must return dict[str, object] | None."""

    def test_get_release_data_return_is_parameterized(self) -> None:
        from epic import EpicManager

        hints = typing.get_type_hints(EpicManager._get_release_data)
        ret = hints["return"]
        origin = typing.get_origin(ret)
        assert origin is types.UnionType
        dict_args = [a for a in typing.get_args(ret) if typing.get_origin(a) is dict]
        assert len(dict_args) == 1
        assert typing.get_args(dict_args[0]) == (str, object)


class TestModelsReleaseField:
    """EpicDetail.release field must be dict[str, object] | None."""

    def test_release_field_is_parameterized(self) -> None:
        from models import EpicDetail

        field_info = EpicDetail.model_fields["release"]
        annotation = field_info.annotation
        # Should be dict[str, object] | None
        origin = typing.get_origin(annotation)
        assert origin is types.UnionType, f"Expected UnionType, got {origin}"
        dict_args = [
            a for a in typing.get_args(annotation) if typing.get_origin(a) is dict
        ]
        assert len(dict_args) == 1
        assert typing.get_args(dict_args[0]) == (str, object)


class TestExpertCouncilReturnTypes:
    """to_dict methods must return dict[str, object]."""

    def test_expert_vote_to_dict_return_is_parameterized(self) -> None:
        from expert_council import CouncilVote

        hints = typing.get_type_hints(CouncilVote.to_dict)
        ret = hints["return"]
        assert typing.get_origin(ret) is dict, (
            f"Expected dict origin, got {typing.get_origin(ret)}"
        )
        assert typing.get_args(ret) == (str, object), (
            f"Expected (str, object), got {typing.get_args(ret)}"
        )

    def test_council_result_to_dict_return_is_parameterized(self) -> None:
        from expert_council import CouncilResult

        hints = typing.get_type_hints(CouncilResult.to_dict)
        ret = hints["return"]
        assert typing.get_origin(ret) is dict
        assert typing.get_args(ret) == (str, object)


class TestSpecMatchReturnType:
    """extract_spec_match must return dict[str, object]."""

    def test_extract_spec_match_return_is_parameterized(self) -> None:
        from spec_match import extract_spec_match

        hints = typing.get_type_hints(extract_spec_match)
        ret = hints["return"]
        assert typing.get_origin(ret) is dict, (
            f"Expected dict origin, got {typing.get_origin(ret)}"
        )
        assert typing.get_args(ret) == (str, object), (
            f"Expected (str, object), got {typing.get_args(ret)}"
        )
