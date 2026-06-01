import unittest
from unittest.mock import patch

from tools.base import Tool, ToolParameter, UserRefusedError
from tools.confirm import set_allow_all_windows_cmd, set_default_tool_confirm
from tools.registry import ToolRegistry


class DummyTool(Tool):
    def __init__(self):
        super().__init__(name="dummy", description="dummy tool", expandable=False)

    def get_parameters(self):
        return [
            ToolParameter(
                name="text",
                type="string",
                description="input text",
                required=True,
            )
        ]

    def run(self, parameters):
        return f"ok:{parameters['text']}"


class ToolConfirmTests(unittest.TestCase):
    def setUp(self):
        set_default_tool_confirm(True)
        self.registry = ToolRegistry()
        self.registry.register(DummyTool())

    def tearDown(self):
        set_default_tool_confirm(True)

    def test_default_requires_confirmation(self):
        with patch("tools.registry.confirm_in_cli", return_value=True) as mock_confirm:
            result = self.registry.execute_tool_by_params("dummy", {"text": "hello"})

        self.assertEqual(result, "ok:hello")
        mock_confirm.assert_called_once()

    def test_confirm_false_skips_confirmation(self):
        with patch("tools.registry.confirm_in_cli", return_value=True) as mock_confirm:
            result = self.registry.execute_tool_by_params(
                "dummy", {"text": "hello", "confirm": False}
            )

        self.assertEqual(result, "ok:hello")
        mock_confirm.assert_not_called()

    def test_confirm_true_forces_confirmation_even_when_allow_all(self):
        set_allow_all_windows_cmd(True)
        with patch("tools.registry.confirm_in_cli", return_value=True) as mock_confirm:
            result = self.registry.execute_tool_by_params(
                "dummy", {"text": "hello", "confirm": True}
            )

        self.assertEqual(result, "ok:hello")
        mock_confirm.assert_called_once()

    def test_refused_confirmation_raises(self):
        with patch("tools.registry.confirm_in_cli", return_value=False):
            with self.assertRaises(UserRefusedError):
                self.registry.execute_tool_by_params("dummy", {"text": "hello"})


if __name__ == "__main__":
    unittest.main()
