# Copyright 2024 Marimo. All rights reserved.
from __future__ import annotations

import json
import os
import tempfile
from functools import partial
from inspect import cleandoc
from textwrap import dedent
from typing import Any, Optional

import codegen_data.test_main as mod
import pytest

from marimo import __version__
from marimo._ast import codegen, compiler
from marimo._ast.app import App, InternalApp, _AppConfig
from marimo._ast.cell import CellConfig
from marimo._ast.names import is_internal_cell_name

compile_cell = partial(compiler.compile_cell, cell_id="0")

DIR_PATH = os.path.dirname(os.path.realpath(__file__))


def get_expected_filecontents(name: str) -> str:
    with open(os.path.join(DIR_PATH, f"codegen_data/{name}.py"), "r") as f:
        contents = f.read()
    lines = contents.split("\n")
    break_index = None
    for i, line in enumerate(lines):
        if line.startswith("__generated_with"):
            break_index = i
            break
    assert break_index is not None
    return "\n".join(
        lines[:break_index]
        + [f'__generated_with = "{__version__}"']
        + lines[break_index + 1 :]
    )


def get_filepath(name: str) -> str:
    return os.path.join(DIR_PATH, f"codegen_data/{name}.py")


def sanitized_version(output: str) -> str:
    return output.replace(__version__, "0.0.0")


def wrap_generate_filecontents(
    codes: list[str],
    names: list[str],
    cell_configs: Optional[list[CellConfig]] = None,
    **kwargs: Any,
) -> str:
    """
    Wraps codegen.generate_filecontents to make the
    cell_configs argument optional."""
    if cell_configs is None:
        resolved_configs = [CellConfig() for _ in range(len(codes))]
    else:
        resolved_configs = cell_configs
    return codegen.generate_filecontents(
        codes, names, cell_configs=resolved_configs, **kwargs
    )


def strip_blank_lines(text: str) -> str:
    return "\n".join([line for line in text.splitlines() if line.strip()])


def get_idempotent_marimo_source(name: str) -> str:
    from marimo._utils.formatter import Formatter

    path = get_filepath(name)
    app = codegen.get_app(path)
    header_comments = codegen.get_header_comments(path)
    generated_contents = codegen.generate_filecontents(
        list(app._cell_manager.codes()),
        list(app._cell_manager.names()),
        list(app._cell_manager.configs()),
        app._config,
        header_comments,
    )
    generated_contents = sanitized_version(generated_contents)

    with open(path) as f:
        python_source = sanitized_version(f.read())

    # TODO(dmadisetti): not totally idempotent for now. Revise; seems to strip
    # on imports (possibly during compile?).
    formatted = Formatter(codegen.MAX_LINE_LENGTH).format(
        {"source": python_source, "generated": generated_contents}
    )

    assert strip_blank_lines(formatted["source"]) == strip_blank_lines(
        formatted["generated"]
    )
    return formatted["generated"]


class TestGeneration:
    @staticmethod
    def test_generate_filecontents_empty() -> None:
        contents = wrap_generate_filecontents([], [])
        assert contents == get_expected_filecontents(
            "test_generate_filecontents_empty"
        )

    @staticmethod
    def test_generate_filecontents_empty_with_config() -> None:
        config = _AppConfig(
            app_title="test_title", width="full", css_file=r"a\b.css"
        )
        contents = wrap_generate_filecontents([], [], config=config)
        assert contents == get_expected_filecontents(
            "test_generate_filecontents_empty_with_config"
        )

    @staticmethod
    def test_generate_filecontents() -> None:
        cell_one = "import numpy as np"
        cell_two = "x = 0\nxx = 1"
        cell_three = "y = x + 1"
        cell_four = "# comment\nz = np.array(x + y)"
        cell_five = "# just a comment"
        codes = [cell_one, cell_two, cell_three, cell_four, cell_five]
        names = ["one", "two", "three", "four", "five"]
        contents = wrap_generate_filecontents(codes, names)
        assert contents == get_expected_filecontents(
            "test_generate_filecontents"
        )

    @staticmethod
    def test_generate_filecontents_async() -> None:
        cell_one = "import numpy as np\nimport asyncio"
        cell_two = "x = 0\nxx = 1\nawait asyncio.sleep(1)"
        cell_three = "async def _():\n    await asyncio.sleep(x)"
        codes = [cell_one, cell_two, cell_three]
        names = ["one", "two", "three"]
        contents = wrap_generate_filecontents(codes, names)
        assert contents == get_expected_filecontents(
            "test_generate_filecontents_async"
        )

    @staticmethod
    def test_generate_filecontents_async_long_signature() -> None:
        cell_one = cleandoc(
            """
            (
                client,
                get_calculation_trigger,
                get_components_configuration,
                get_conditions_state,
            ) = (1, 1, 1, 1)
            """
        )
        cell_two = cleandoc(
            """
            _conditions = [c for c in get_conditions_state().values()]
            _configuration = get_components_configuration()

            _configuration_conditions_list = {
                "configuration": _configuration,
                "condition": _conditions,
            }

            _trigger = get_calculation_trigger()

            async for data_point in client("test", "ws://localhost:8000"):
                print(data_point)
            data_point
            """
        )
        codes = [cell_one, cell_two]
        names = ["one", "two"]
        contents = wrap_generate_filecontents(codes, names)
        assert contents == get_expected_filecontents(
            "test_generate_filecontents_async_long_signature"
        )

    @staticmethod
    def test_generate_filecontents_single_cell() -> None:
        cell_one = "import numpy as np"
        codes = [cell_one]
        names = ["one"]
        contents = wrap_generate_filecontents(codes, names)
        assert contents == get_expected_filecontents(
            "test_generate_filecontents_single_cell"
        )

    @staticmethod
    def test_generate_filecontents_with_syntax_error() -> None:
        cell_one = "import numpy as np"
        cell_two = "_ error"
        cell_three = "'all good'"
        cell_four = '_ another_error\n_ and """another"""\n\n    \\t'
        codes = [cell_one, cell_two, cell_three, cell_four]
        names = ["one", "two", "__", "__"]
        contents = wrap_generate_filecontents(codes, names)
        assert contents == get_expected_filecontents(
            "test_generate_filecontents_with_syntax_error"
        )

    @staticmethod
    def test_generate_unparsable_cell() -> None:
        code = "    error\n\\t"
        raw = codegen.generate_unparsable_cell(code, None, CellConfig())
        stringified = eval("\n".join(raw.split("\n")[1:5])).split("\n")
        # first line empty
        assert not stringified[0]
        # leading 4 spaces followed by source line
        assert stringified[1] == " " * 4 + "    error"
        # leading 4 spaces followed by source line
        assert stringified[2] == " " * 4 + "\\t"
        # leading 4 spaces followed by nothing
        assert stringified[3] == " " * 4

    @staticmethod
    def test_generate_unparsable_cell_with_await() -> None:
        code = "    await error\n\\t"
        raw = codegen.generate_unparsable_cell(code, None, CellConfig())
        stringified = eval("\n".join(raw.split("\n")[1:5])).split("\n")
        # first line empty
        assert not stringified[0]
        # leading 4 spaces followed by source line
        assert stringified[1] == " " * 4 + "    await error"
        # leading 4 spaces followed by source line
        assert stringified[2] == " " * 4 + "\\t"
        # leading 4 spaces followed by nothing
        assert stringified[3] == " " * 4

    @staticmethod
    def test_long_line_in_main() -> None:
        cell_one = "\n".join(
            [
                "i_am_a_very_long_name = 0",
                "i_am_another_very_long_name = 0",
                "yet_another_very_long_name = 0",
            ]
        )
        cell_two = (
            "z = i_am_a_very_long_name + "
            + "i_am_another_very_long_name + "
            + "yet_another_very_long_name"
        )
        contents = wrap_generate_filecontents(
            [cell_one, cell_two], ["one", "two"]
        )
        assert contents == get_expected_filecontents("test_long_line_in_main")

    @staticmethod
    def test_generate_filecontents_unshadowed_builtin() -> None:
        cell_one = "type"
        codes = [cell_one]
        names = ["one"]
        contents = wrap_generate_filecontents(codes, names)
        assert contents == get_expected_filecontents(
            "test_generate_filecontents_unshadowed_builtin"
        )

    @staticmethod
    def test_generate_filecontents_shadowed_builtin() -> None:
        cell_one = "type = 1"
        cell_two = "type"
        codes = [cell_one, cell_two]
        names = ["one", "two"]
        contents = wrap_generate_filecontents(codes, names)
        assert contents == get_expected_filecontents(
            "test_generate_filecontents_shadowed_builtin"
        )

    @staticmethod
    def test_generate_app_constructor_with_auto_download() -> None:
        config = _AppConfig(
            width="full",
            app_title="Test App",
            css_file="custom.css",
            auto_download=["html", "markdown"],
        )
        result = codegen.generate_app_constructor(config)
        expected = (
            "app = marimo.App(\n"
            '    width="full",\n'
            '    app_title="Test App",\n'
            '    css_file="custom.css",\n'
            '    auto_download=["html", "markdown"],\n'
            ")"
        )
        assert result == expected

    @staticmethod
    def test_generate_app_constructor_with_empty_auto_download() -> None:
        config = _AppConfig(auto_download=[])
        result = codegen.generate_app_constructor(config)
        assert result == "app = marimo.App()"

    @staticmethod
    def test_generate_app_constructor_with_single_auto_download() -> None:
        config = _AppConfig(auto_download=["html"])
        result = codegen.generate_app_constructor(config)
        assert result == 'app = marimo.App(auto_download=["html"])'

    @staticmethod
    def test_generate_file_contents_overwrite_default_cell_names() -> None:
        contents = wrap_generate_filecontents(
            ["import numpy as np", "x = 0", "y = x + 1"],
            ["is_named", "__", "__"],
        )
        # __9 and __10 are overwritten by the default names
        assert "is_named" in contents
        assert "def _" in contents
        assert "def __" not in contents

    @staticmethod
    def test_generate_filecontents_toplevel() -> None:
        source = get_idempotent_marimo_source(
            "test_generate_filecontents_toplevel"
        )
        assert "import marimo" in source
        split = source.split("import marimo")
        # The default one, the as mo in top level, in as mo in cell
        assert len(split) == 4

    @staticmethod
    def test_generate_filecontents_toplevel_pytest() -> None:
        source = get_idempotent_marimo_source(
            "test_generate_filecontents_toplevel_pytest"
        )
        assert "import marimo" in source


class TestGetCodes:
    @staticmethod
    def test_get_codes() -> None:
        app = codegen.get_app(get_filepath("test_generate_filecontents"))
        assert app is not None
        cell_manager = app._cell_manager
        assert list(cell_manager.names()) == [
            "one",
            "two",
            "three",
            "four",
            "five",
        ]
        assert list(cell_manager.codes()) == [
            "import numpy as np",
            "x = 0\nxx = 1",
            "y = x + 1",
            "# comment\nz = np.array(x + y)",
            "# just a comment",
        ]

    @staticmethod
    def test_get_codes_async() -> None:
        app = codegen.get_app(get_filepath("test_generate_filecontents_async"))
        assert app is not None
        cell_manager = app._cell_manager
        assert list(cell_manager.names()) == [
            "one",
            "two",
            "three",
        ]
        assert list(cell_manager.codes()) == [
            "import numpy as np\nimport asyncio",
            "x = 0\nxx = 1\nawait asyncio.sleep(1)",
            "async def _():\n    await asyncio.sleep(x)",
        ]

    @staticmethod
    def test_get_codes_with_incorrect_args_rets() -> None:
        app = codegen.get_app(
            get_filepath("test_get_codes_with_incorrect_args_rets")
        )
        assert app is not None
        cell_manager = app._cell_manager
        assert list(cell_manager.names()) == [
            "one",
            "two",
            "three",
            "four",
            "five",
        ]
        assert list(cell_manager.codes()) == [
            "import numpy as np",
            "x = 0\nxx = 1",
            "y = x + 1",
            "# comment\nz = np.array(x + y)",
            "# just a comment\n...",
        ]

    @staticmethod
    def test_get_codes_with_name_error() -> None:
        # name mo is not defined --- make sure this file is still parseable
        app = codegen.get_app(get_filepath("test_get_codes_with_name_error"))
        assert app is not None
        cell_manager = app._cell_manager
        assert list(cell_manager.names()) == ["one"]
        assert list(cell_manager.codes()) == [
            "mo",
        ]

    @staticmethod
    def test_get_codes_multiline_fndef() -> None:
        app = codegen.get_app(get_filepath("test_get_codes_multiline_fndef"))
        assert app is not None
        cell_manager = app._cell_manager
        assert list(cell_manager.names()) == ["one"]
        assert list(cell_manager.codes()) == [
            "# comment\nx = 0 + a + b + c + d",
        ]

    @staticmethod
    def test_get_codes_messy() -> None:
        app = codegen.get_app(get_filepath("test_get_codes_messy"))
        assert app is not None
        cell_manager = app._cell_manager
        assert list(cell_manager.names()) == ["__"]
        assert list(cell_manager.codes()) == [
            "# comment\n# another comment\n\n# yet another comment\n"
            + "x = 0 + a + b + c + d",
        ]

    @staticmethod
    def test_get_codes_single_line_fn() -> None:
        app = codegen.get_app(get_filepath("test_get_codes_single_line_fn"))
        assert app is not None
        cell_manager = app._cell_manager
        assert list(cell_manager.names()) == ["one"]
        assert list(cell_manager.codes()) == ["c = a + b; print(c); "]

    @staticmethod
    def test_get_codes_multiline_string() -> None:
        app = codegen.get_app(get_filepath("test_get_codes_multiline_string"))
        assert app is not None
        cell_manager = app._cell_manager
        assert list(cell_manager.names()) == ["one"]
        assert list(cell_manager.codes()) == ['c = """\n  a, b"""; ']

    @staticmethod
    def test_get_codes_comment_after_sig() -> None:
        app = codegen.get_app(get_filepath("test_get_codes_comment_after_sig"))
        assert app is not None
        cell_manager = app._cell_manager
        assert list(cell_manager.names()) == ["one"]
        assert list(cell_manager.codes()) == ['print("hi")']

    @staticmethod
    def test_get_codes_empty() -> None:
        app = codegen.get_app(get_filepath("test_get_codes_empty"))
        assert app is not None
        cell_manager = app._cell_manager
        assert list(cell_manager.names()) == ["one", "two"]
        assert [c.strip() for c in cell_manager.codes()] == ["", ""]

    @staticmethod
    def test_get_codes_syntax_error() -> None:
        app = codegen.get_app(
            get_filepath("test_generate_filecontents_with_syntax_error")
        )
        assert app is not None
        cell_manager = app._cell_manager
        assert list(cell_manager.names()) == ["one", "two", "_", "_"]
        assert list(cell_manager.codes()) == [
            "import numpy as np",
            "_ error",
            "'all good'",
            '_ another_error\n_ and """another"""\n\n    \\t',
        ]

    @staticmethod
    def test_get_codes_app_with_only_comments() -> None:
        app = codegen.get_app(get_filepath("test_app_with_only_comments"))
        assert app is None

    @staticmethod
    def test_get_codes_app_with_no_cells() -> None:
        app = codegen.get_app(get_filepath("test_app_with_no_cells"))
        assert app is not None
        app._cell_manager.ensure_one_cell()
        assert list(app._cell_manager.names()) == ["_"]
        assert list(app._cell_manager.codes()) == [""]


@pytest.fixture
def marimo_app() -> App:
    return mod.app


class TestApp:
    @staticmethod
    def test_run(marimo_app: App) -> None:
        outputs, defs = marimo_app.run()
        assert outputs == (None, "z", None)
        assert defs == {"x": 0, "y": 1, "z": 2, "a": 1}

    @staticmethod
    def test_app_with_title(marimo_app: App) -> None:
        """Update title in app config"""
        NEW_TITLE = "test_title"
        marimo_internal_app = InternalApp(marimo_app)
        assert marimo_internal_app.config.app_title is None
        marimo_internal_app.update_config({"app_title": NEW_TITLE})
        assert marimo_internal_app.config.app_title == "test_title"


class TestToFunctionDef:
    def test_tofunctiondef_one_def(self) -> None:
        code = "x = 0"
        cell = compile_cell(code)
        fndef = codegen.to_functiondef(cell, "foo")
        expected = "\n".join(
            ["@app.cell", "def foo():", "    x = 0", "    return (x,)"]
        )
        assert fndef == expected

    def test_tofunctiondef_one_ref(self) -> None:
        code = "y + 1"
        cell = compile_cell(code)
        fndef = codegen.to_functiondef(cell, "foo")
        expected = "\n".join(
            ["@app.cell", "def foo(y):", "    y + 1", "    return"]
        )
        assert fndef == expected

    def test_tofunctiondef_empty_cells(self) -> None:
        code = ""
        cell = compile_cell(code)
        fndef = codegen.to_functiondef(cell, "foo")
        expected = "\n".join(["@app.cell", "def foo():", "    return"])

        code = "\n #\n"
        cell = compile_cell(code)
        fndef = codegen.to_functiondef(cell, "foo")
        expected = cleandoc(
            """
            @app.cell
            def foo():

                 #

                return
            """
        )
        assert fndef == expected

    def test_tofunctiondef_builtin_not_a_ref(self) -> None:
        code = "print(y)"
        cell = compile_cell(code)
        fndef = codegen.to_functiondef(cell, "foo")
        expected = "\n".join(
            ["@app.cell", "def foo(y):", "    print(y)", "    return"]
        )
        assert fndef == expected

    def test_tofunctiondef_refs_and_defs(self) -> None:
        code = "\n".join(["y = x", "z = x", "z = w + y"])
        cell = compile_cell(code)
        fndef = codegen.to_functiondef(cell, "foo")
        expected = "\n".join(
            ["@app.cell", "def foo(w, x):"]
            + ["    " + line for line in code.split("\n")]
            + ["    return y, z"]
        )
        assert fndef == expected

    def test_with_empty_config(self) -> None:
        code = "x = 0"
        cell = compile_cell(code)
        cell = cell.configure(CellConfig())
        fndef = codegen.to_functiondef(cell, "foo")
        expected = "\n".join(
            ["@app.cell", "def foo():", "    x = 0", "    return (x,)"]
        )
        assert fndef == expected

    def test_with_some_config(self) -> None:
        code = "x = 0"
        cell = compile_cell(code)
        cell = cell.configure(CellConfig(disabled=True))
        fndef = codegen.to_functiondef(cell, "foo")
        expected = "\n".join(
            [
                "@app.cell(disabled=True)",
                "def foo():",
                "    x = 0",
                "    return (x,)",
            ]
        )
        assert fndef == expected

    def test_with_all_config(self) -> None:
        code = "x = 0"
        cell = compile_cell(code)
        cell = cell.configure(CellConfig(disabled=True, hide_code=True))
        fndef = codegen.to_functiondef(cell, "foo")
        expected = "\n".join(
            [
                "@app.cell(disabled=True, hide_code=True)",
                "def foo():",
                "    x = 0",
                "    return (x,)",
            ]
        )
        assert fndef == expected

    def test_should_remove_defaults(self) -> None:
        code = "x = 0"
        cell = compile_cell(code)
        cell = cell.configure(CellConfig(disabled=False, hide_code=False))
        fndef = codegen.to_functiondef(cell, "foo")
        expected = "\n".join(
            [
                "@app.cell",
                "def foo():",
                "    x = 0",
                "    return (x,)",
            ]
        )
        assert fndef == expected

    def test_fn_with_empty_config(self) -> None:
        code = "\n".join(["def foo():", "    x = 0", "    return (x,)"])
        cell = compile_cell(code)
        cell = cell.configure(CellConfig())
        fndef = codegen.to_top_functiondef(cell)
        expected = "@app.function\n" + code
        assert fndef == expected

    def test_fn_with_all_config(self) -> None:
        code = "\n".join(["def foo():", "    x = 0", "    return (x,)"])
        cell = compile_cell(code)
        cell = cell.configure(CellConfig(disabled=True, hide_code=True))
        fndef = codegen.to_top_functiondef(cell)
        expected = "@app.function(disabled=True, hide_code=True)\n" + code
        assert fndef == expected


def test_recover() -> None:
    cells = {
        "cells": [
            {"name": "a", "code": '"santa"\n\n"clause"\n\n\n'},
            {"name": "b", "code": ""},
            {"name": "c", "code": "\n123"},
        ]
    }
    filecontents = json.dumps(cells)
    # keep open for windows compat
    tempfile_name = ""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False
    ) as f:
        f.write(filecontents)
        f.seek(0)
        tempfile_name = f.name
    try:
        recovered = codegen.recover(tempfile_name)
    finally:
        os.remove(tempfile_name)

    codes = [
        "\n".join(['"santa"', "", '"clause"', "", "", ""]),
        "",
        "\n".join(["", "123"]),
    ]
    names = ["a", "b", "c"]

    expected = wrap_generate_filecontents(codes, names)
    assert recovered == expected


# TODO(akshayka): more tests for attributes, classdefs, and closures
# TODO(akshayka): test builtin functions
# TODO(akshayka): test delete cell


def test_get_header_comments() -> None:
    filepath = get_filepath("test_get_header_comments")
    comments = codegen.get_header_comments(filepath)

    assert comments, "No comments found"
    assert '"""Docstring"""' in comments, "Docstring not found"
    assert '"""multi\n    line\n"""' in comments, "Multiline string not found"
    assert "# A copyright" in comments, "Comment not found"
    assert "# A linter" in comments, "Comment not found"


def test_get_header_comments_invalid() -> None:
    filepath = get_filepath("test_get_header_comments_invalid")
    comments = codegen.get_header_comments(filepath)

    assert comments is None, "Comments found when there should be none"


def test_sqls() -> None:
    code = dedent(
        """
    db.sql("SELECT * FROM foo")
    db.sql("ATTACH TABLE bar")
    """
    )
    cell = compile_cell(code)
    sqls = cell.sqls
    assert sqls == ["SELECT * FROM foo", "ATTACH TABLE bar"]


def test_is_internal_cell_name() -> None:
    assert is_internal_cell_name("__")
    assert is_internal_cell_name("_")
    assert not is_internal_cell_name("___")
    assert not is_internal_cell_name("__1213123123")
    assert not is_internal_cell_name("foo")


def test_format_tuple_elements() -> None:
    kv_case = codegen.format_tuple_elements(
        "@app.fn(...)",
        tuple(["a", "b", "c"]),
    )
    assert kv_case == "@app.fn(a, b, c)"

    indent_case = codegen.format_tuple_elements(
        "def fn(...):", tuple(["a", "b", "c"]), indent=True
    )
    assert indent_case == "    def fn(a, b, c):"

    multiline_case = codegen.format_tuple_elements(
        "return (...)",
        (
            "very",
            "long",
            "arglist",
            "that",
            "exceeds",
            "maximum",
            "characters",
            "for",
            "some",
            "reason",
            "or",
            "the",
            "other",
            "wowza",
        ),
        allowed_naked=True,
    )
    assert multiline_case == (
        "return (\n    "
        "very,\n    long,\n    arglist,\n    that,\n    exceeds,\n    maximum,\n"
        "    characters,\n    for,\n    some,\n    reason,\n"
        "    or,\n    the,\n    other,\n    wowza,\n)"
    )

    long_case = codegen.format_tuple_elements(
        "return (...)",
        (
            "very_long_name_that_exceeds_76_characters_for_some_reason_or_the_other_woowee",
        ),
        allowed_naked=True,
    )
    assert long_case == (
        "return (\n    "
        "very_long_name_that_exceeds_76_characters_for_some_reason_or_the_other_woowee,"
        "\n)"
    )
