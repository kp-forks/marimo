# Copyright 2024 Marimo. All rights reserved.
from __future__ import annotations

from functools import partial
from typing import cast

from marimo._ast import compiler
from marimo._ast.names import SETUP_CELL_NAME
from marimo._messaging.errors import (
    CycleError,
    DeleteNonlocalError,
    MultipleDefinitionError,
    SetupRootError,
)
from marimo._runtime import dataflow
from marimo._runtime.validate_graph import check_for_errors

parse_cell = partial(compiler.compile_cell, cell_id="0")


def test_multiple_definition_error() -> None:
    graph = dataflow.DirectedGraph()
    graph.register_cell("0", parse_cell("x = 0"))
    graph.register_cell("1", parse_cell("x = 1"))
    errors = check_for_errors(graph)
    assert set(errors.keys()) == set(["0", "1"])
    assert errors["0"] == (MultipleDefinitionError(name="x", cells=("1",)),)
    assert errors["1"] == (MultipleDefinitionError(name="x", cells=("0",)),)

    graph.register_cell("2", parse_cell("x = 1"))
    errors = check_for_errors(graph)
    assert set(errors.keys()) == set(["0", "1", "2"])
    assert errors["0"] == (
        MultipleDefinitionError(name="x", cells=("1", "2")),
    )
    assert errors["1"] == (
        MultipleDefinitionError(name="x", cells=("0", "2")),
    )
    assert errors["2"] == (
        MultipleDefinitionError(name="x", cells=("0", "1")),
    )


def test_overlapping_multiple_definition_errors() -> None:
    graph = dataflow.DirectedGraph()
    graph.register_cell("0", parse_cell("x = 0"))
    graph.register_cell("1", parse_cell("x, y = 1, 2"))
    graph.register_cell("2", parse_cell("y, z = 3, 4"))
    errors = check_for_errors(graph)
    assert set(errors.keys()) == set(["0", "1", "2"])
    assert errors["0"] == (MultipleDefinitionError(name="x", cells=("1",)),)
    assert errors["1"] == (
        MultipleDefinitionError(name="x", cells=("0",)),
        MultipleDefinitionError(name="y", cells=("2",)),
    )
    assert errors["2"] == (MultipleDefinitionError(name="y", cells=("1",)),)


def test_underscore_variables_are_private() -> None:
    graph = dataflow.DirectedGraph()
    graph.register_cell("0", parse_cell("_x = 0"))
    graph.register_cell("1", parse_cell("_x = 1"))
    errors = check_for_errors(graph)
    assert not errors

    graph = dataflow.DirectedGraph()
    graph.register_cell("0", parse_cell("_x = 0"))
    graph.register_cell("1", parse_cell("del _x"))
    errors = check_for_errors(graph)
    assert not errors


def test_delete_nonlocal_error() -> None:
    graph = dataflow.DirectedGraph()
    graph.register_cell("0", parse_cell("x = 0"))
    graph.register_cell("1", parse_cell("del x"))
    errors = check_for_errors(graph)
    assert set(errors.keys()) == set(["1"])
    assert errors["1"] == (DeleteNonlocalError(name="x", cells=("0",)),)


def test_two_node_cycle() -> None:
    graph = dataflow.DirectedGraph()
    graph.register_cell("0", parse_cell("x = y"))
    graph.register_cell("1", parse_cell("y = x"))
    errors = check_for_errors(graph)
    assert set(errors.keys()) == set(["0", "1"])
    assert errors["0"] == (
        CycleError(edges_with_vars=(("0", ["x"], "1"), ("1", ["y"], "0"))),
    )
    assert errors["1"] == (
        CycleError(edges_with_vars=(("0", ["x"], "1"), ("1", ["y"], "0"))),
    )


def test_three_node_cycle() -> None:
    graph = dataflow.DirectedGraph()
    graph.register_cell("0", parse_cell("x = y"))
    graph.register_cell("1", parse_cell("y = z"))
    graph.register_cell("2", parse_cell("z = x"))
    errors = check_for_errors(graph)
    assert set(errors.keys()) == set(["0", "1", "2"])
    for t in errors.values():
        assert len(t) == 1
        assert isinstance(t[0], CycleError)
        edges_with_vars = t[0].edges_with_vars
        assert len(edges_with_vars) == 3
        assert ("0", ["x"], "2") in edges_with_vars
        assert ("1", ["y"], "0") in edges_with_vars
        assert ("2", ["z"], "1") in edges_with_vars


def test_cycle_and_multiple_def() -> None:
    graph = dataflow.DirectedGraph()
    graph.register_cell("0", parse_cell("x, z = y, 0"))
    graph.register_cell("1", parse_cell("y, z = x, 0"))
    errors = check_for_errors(graph)
    assert set(errors.keys()) == set(["0", "1"])
    for cell, t in errors.items():
        assert len(t) == 2
        assert isinstance(t[0], CycleError) or isinstance(t[1], CycleError)
        assert isinstance(t[0], MultipleDefinitionError) or isinstance(
            t[1], MultipleDefinitionError
        )
        cycle_error = cast(
            CycleError, t[0] if isinstance(t[0], CycleError) else t[1]
        )
        edges_with_vars = cycle_error.edges_with_vars
        assert len(edges_with_vars) == 2
        assert ("0", ["x"], "1") in edges_with_vars
        assert ("1", ["y"], "0") in edges_with_vars

        multiple_definition_error = cast(
            MultipleDefinitionError,
            t[0] if isinstance(t[0], MultipleDefinitionError) else t[1],
        )
        assert multiple_definition_error.name == "z"
        assert multiple_definition_error.cells == (str((int(cell) + 1) % 2),)


def test_setup_has_refs() -> None:
    graph = dataflow.DirectedGraph()
    graph.register_cell(SETUP_CELL_NAME, parse_cell("z = y"))
    graph.register_cell("0", parse_cell("y = 1"))
    errors = check_for_errors(graph)
    assert set(errors.keys()) == set([SETUP_CELL_NAME])
    for t in errors.values():
        assert len(t) == 1
        assert isinstance(t[0], SetupRootError)
        setup_error = cast(SetupRootError, t[0])
        edges_with_vars = setup_error.edges_with_vars
        assert len(edges_with_vars) == 1
        assert ("0", ["y"], SETUP_CELL_NAME) in edges_with_vars
