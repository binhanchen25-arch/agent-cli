import unittest
from unittest.mock import patch

from tools.base import Tool, ToolParameter, UserRefusedError
from tools.confirm import set_default_tool_confirm
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
        # 默认策略：模型不传 confirm 时直接放行（由模型自主决定是否人工审核）。
        set_default_tool_confirm(False)
        self.registry = ToolRegistry()
        self.registry.register(DummyTool())

    def tearDown(self):
        set_default_tool_confirm(False)

    def test_default_skips_confirmation_when_model_omits_confirm(self):
        with patch("tools.registry.confirm_in_cli", return_value=True) as mock_confirm:
            result = self.registry.execute_tool_by_params("dummy", {"text": "hello"})

        self.assertEqual(result, "ok:hello")
        mock_confirm.assert_not_called()

    def test_model_can_force_confirmation(self):
        with patch("tools.registry.confirm_in_cli", return_value=True) as mock_confirm:
            result = self.registry.execute_tool_by_params(
                "dummy", {"text": "hello", "confirm": True}
            )

        self.assertEqual(result, "ok:hello")
        mock_confirm.assert_called_once()

    def test_global_default_can_force_confirmation_when_model_omits(self):
        set_default_tool_confirm(True)
        with patch("tools.registry.confirm_in_cli", return_value=True) as mock_confirm:
            result = self.registry.execute_tool_by_params("dummy", {"text": "hello"})

        self.assertEqual(result, "ok:hello")
        mock_confirm.assert_called_once()

    def test_confirm_false_skips_even_when_global_requires(self):
        set_default_tool_confirm(True)
        with patch("tools.registry.confirm_in_cli", return_value=True) as mock_confirm:
            result = self.registry.execute_tool_by_params(
                "dummy", {"text": "hello", "confirm": False}
            )

        self.assertEqual(result, "ok:hello")
        mock_confirm.assert_not_called()

    def test_refused_confirmation_raises(self):
        with patch("tools.registry.confirm_in_cli", return_value=False):
            with self.assertRaises(UserRefusedError):
                self.registry.execute_tool_by_params(
                    "dummy", {"text": "hello", "confirm": True}
                )


if __name__ == "__main__":
    unittest.main()
