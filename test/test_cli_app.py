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
            "temperature": 0.1,
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
            self.assertTrue(self.app.handle_command("/allow all"))
            self.assertTrue(self.app.handle_command("/allow off"))

        self.assertEqual(mock_set_allow.call_count, 2)
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


if __name__ == "__main__":
    unittest.main()
