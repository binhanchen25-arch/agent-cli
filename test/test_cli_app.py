import unittest
from unittest.mock import MagicMock, patch

from cli.app import ChatApp


class FakeBaseLLM:
    def __init__(self, config):
        self.config = config
        self.last_stream_messages = None

    def stream(self, messages):
        self.last_stream_messages = messages
        yield "chunk"

    def invoke(self, messages):
        return "invoke-result"


class ChatAppTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "model": "gpt-4o-mini",
            "api_key": "test-key",
            "base_url": "https://example.com/v1",
            "max_tokens": 512,
            "temperature": 0.8,
            "system_prompt": "system prompt",
        }

        self.p_ensure_dirs = patch("cli.app.ensure_dirs")
        self.p_load_config = patch("cli.app.load_config", return_value=dict(self.config))
        self.p_openai_compat = patch(
            "cli.app.OpenAICompatLLM", side_effect=lambda cfg: FakeBaseLLM(cfg)
        )
        self.p_prompt_session = patch("cli.app.PromptSession", return_value=MagicMock())
        self.p_file_history = patch("cli.app.FileHistory", return_value=MagicMock())
        self.p_completer = patch("cli.app.CliCompleter", return_value=MagicMock())

        self.p_ensure_dirs.start()
        self.p_load_config.start()
        self.p_openai_compat.start()
        self.p_prompt_session.start()
        self.p_file_history.start()
        self.p_completer.start()

        self.addCleanup(self.p_ensure_dirs.stop)
        self.addCleanup(self.p_load_config.stop)
        self.addCleanup(self.p_openai_compat.stop)
        self.addCleanup(self.p_prompt_session.stop)
        self.addCleanup(self.p_file_history.stop)
        self.addCleanup(self.p_completer.stop)

        self.app = ChatApp()

    def test_model_command_updates_config_and_persists(self):
        with patch("cli.app.save_config") as mock_save, patch("cli.app.print_system") as mock_print:
            keep_running = self.app.handle_command("/model gpt-4.1")

        self.assertTrue(keep_running)
        self.assertEqual(self.app.config["model"], "gpt-4.1")
        mock_save.assert_called_once_with(self.app.config)
        mock_print.assert_called_once_with("模型已切换为: gpt-4.1")

    def test_allow_all_and_allow_off_toggle_execution_guard(self):
        with patch("cli.app.set_allow_all_windows_cmd") as mock_set_allow:
            self.assertTrue(self.app.handle_command("/allow"))
            self.assertTrue(self.app.handle_command("/allow all"))
            self.assertTrue(self.app.handle_command("/allow off"))

        self.assertEqual(mock_set_allow.call_count, 3)
        mock_set_allow.assert_any_call(True)
        mock_set_allow.assert_any_call(False)

    def test_react_command_switches_llm_wrapper(self):
        fake_agent = object()
        fake_wrapper = object()

        with patch("cli.app.ReActAgent", return_value=fake_agent) as mock_agent_cls, patch(
            "cli.app.ReActChatLLM", return_value=fake_wrapper
        ) as mock_wrapper_cls:
            keep_running = self.app.handle_command("/react")

        self.assertTrue(keep_running)
        mock_agent_cls.assert_called_once_with("MyCLI", self.app.base_llm)
        mock_wrapper_cls.assert_called_once_with(fake_agent)
        self.assertIs(self.app.llm, fake_wrapper)

    def test_react_command_with_question_runs_react_once(self):
        with patch.object(self.app, "_run_react") as mock_run_react:
            keep_running = self.app.handle_command("/react 你好")

        self.assertTrue(keep_running)
        mock_run_react.assert_called_once_with("你好")

    def test_chat_uses_current_llm_stream_and_records_reply(self):
        fake_stream = iter(["chunk-a", "chunk-b"])
        fake_llm = MagicMock()
        fake_llm.stream.return_value = fake_stream
        self.app.llm = fake_llm
        self.app.use_demo = False

        with patch("cli.app.print_user_message"), patch(
            "cli.app.render_stream", return_value="final-reply"
        ) as mock_render:
            self.app.chat("test question")

        self.assertEqual(self.app.messages[-2], {"role": "user", "content": "test question"})
        self.assertEqual(self.app.messages[-1], {"role": "assistant", "content": "final-reply"})
        fake_llm.stream.assert_called_once()
        called_messages = fake_llm.stream.call_args[0][0]
        self.assertEqual(called_messages[0], {"role": "system", "content": "system prompt"})
        self.assertEqual(called_messages[1], {"role": "user", "content": "test question"})
        mock_render.assert_called_once_with(fake_stream)

    def test_exit_command_returns_false(self):
        self.assertFalse(self.app.handle_command("/exit"))

    def test_apikey_command_sets_key_and_disables_demo(self):
        self.app.use_demo = True
        with patch("cli.app.save_config") as mock_save, patch("cli.app.print_system"):
            self.app.handle_command("/apikey sk-new-test-key-12345")

        self.assertEqual(self.app.config["api_key"], "sk-new-test-key-12345")
        self.assertFalse(self.app.use_demo)
        mock_save.assert_called_once_with(self.app.config)

    def test_apikey_command_no_args_shows_masked_key(self):
        self.app.config["api_key"] = "sk-abcdef1234567890"
        with patch("cli.app.print_system") as mock_print:
            self.app.handle_command("/apikey")
        mock_print.assert_called_once()
        msg = mock_print.call_args[0][0]
        self.assertIn("sk-abcde", msg)
        self.assertNotIn("1234567890", msg)

    def test_base_url_command_updates_config(self):
        with patch("cli.app.save_config") as mock_save, patch("cli.app.print_system"):
            self.app.handle_command("/base_url https://my-proxy.com/v1")

        self.assertEqual(self.app.config["base_url"], "https://my-proxy.com/v1")
        mock_save.assert_called_once()

    def test_temperature_command_valid_value(self):
        with patch("cli.app.save_config") as mock_save, patch("cli.app.print_system"):
            self.app.handle_command("/temperature 0.5")

        self.assertEqual(self.app.config["temperature"], 0.5)
        mock_save.assert_called_once()

    def test_temperature_command_rejects_out_of_range(self):
        original = self.app.config["temperature"]
        with patch("cli.app.save_config") as mock_save, patch("cli.app.print_error"):
            self.app.handle_command("/temperature 3.0")

        self.assertEqual(self.app.config["temperature"], original)
        mock_save.assert_not_called()

    def test_temperature_command_rejects_non_number(self):
        original = self.app.config["temperature"]
        with patch("cli.app.save_config") as mock_save, patch("cli.app.print_error"):
            self.app.handle_command("/temperature abc")

        self.assertEqual(self.app.config["temperature"], original)
        mock_save.assert_not_called()

    def test_max_tokens_command_valid_value(self):
        with patch("cli.app.save_config") as mock_save, patch("cli.app.print_system"):
            self.app.handle_command("/max_tokens 4096")

        self.assertEqual(self.app.config["max_tokens"], 4096)
        mock_save.assert_called_once()

    def test_max_tokens_command_rejects_non_positive(self):
        original = self.app.config["max_tokens"]
        with patch("cli.app.save_config") as mock_save, patch("cli.app.print_error"):
            self.app.handle_command("/max_tokens -1")

        self.assertEqual(self.app.config["max_tokens"], original)
        mock_save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
