"""验证 entrypoints/cli.py 的快速路径不会触碰重型模块。

参考 Claude Code 的 cli.tsx —— --version / --help / --config-path
等参数命中后必须 return，不应导入 ChatApp / OpenAI / Rich 等。
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from entrypoints import cli as cli_entry


class CliEntrypointFastPathTests(unittest.TestCase):
    def test_version_prints_inline_constant_and_skips_full_app(self):
        buf = io.StringIO()
        with patch("entrypoints.cli._run_full_app") as mock_full, \
             patch("entrypoints.init.init_app") as mock_init, \
             redirect_stdout(buf):
            cli_entry.main(["--version"])

        self.assertIn(cli_entry.VERSION, buf.getvalue())
        self.assertIn("MyCLI", buf.getvalue())
        mock_full.assert_not_called()
        mock_init.assert_not_called()

    def test_help_prints_static_text_and_skips_full_app(self):
        buf = io.StringIO()
        with patch("entrypoints.cli._run_full_app") as mock_full, redirect_stdout(buf):
            cli_entry.main(["--help"])

        self.assertIn("MyCLI", buf.getvalue())
        self.assertIn("--version", buf.getvalue())
        mock_full.assert_not_called()

    def test_config_path_only_imports_config_module(self):
        buf = io.StringIO()
        with patch("entrypoints.cli._run_full_app") as mock_full, redirect_stdout(buf):
            cli_entry.main(["--config-path"])

        self.assertIn(".mycli", buf.getvalue())
        mock_full.assert_not_called()

    def test_no_args_falls_through_to_full_app(self):
        with patch("entrypoints.cli._run_full_app") as mock_full:
            cli_entry.main([])
        mock_full.assert_called_once_with()


class SdkPublicSurfaceTests(unittest.TestCase):
    def test_query_options_rejects_unknown_fields(self):
        from entrypoints.sdk_types import QueryOptions

        with self.assertRaises(Exception):
            QueryOptions(unknown_field=1)

    def test_create_sdk_tool_registry_includes_builtins(self):
        from entrypoints.sdk_types import create_sdk_tool_registry

        reg = create_sdk_tool_registry()
        self.assertIsNotNone(reg.get_tool("echo"))
        self.assertIsNotNone(reg.get_tool("view"))


if __name__ == "__main__":
    unittest.main()
