import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.remote_console import RemoteConsoleServer


class _FakeLearningSkillEngine:
    @staticmethod
    def training_progress_snapshot():
        return {"profiles": []}


class _FakeAssistant:
    def __init__(self):
        self.listeners = []
        self.learning_skill_engine = _FakeLearningSkillEngine()
        self._confirmation_provider = None

    def add_status_listener(self, callback):
        self.listeners.append(callback)

    @staticmethod
    def training_runtime_snapshot():
        return {
            "running": False,
            "cycle_count": 0,
            "last_result": "sin ciclos todavia",
            "stop_hint": "ctrl+c",
        }

    @staticmethod
    def handle_command(command):
        return f"ok:{command}"

    def set_confirmation_provider(self, callback):
        self._confirmation_provider = callback


class RemoteConsoleTests(unittest.TestCase):
    def setUp(self):
        self.assistant = _FakeAssistant()
        self.temp_dir = TemporaryDirectory()
        self.state_path = Path(self.temp_dir.name) / "remote_console_state.json"
        self.server = RemoteConsoleServer(self.assistant, state_path=self.state_path)

    def tearDown(self):
        self.server.stop()
        self.temp_dir.cleanup()

    def test_start_can_rebind_running_server_from_local_to_online(self):
        first = self.server.start(host="127.0.0.1", port=0, token="abc123")
        self.assertTrue(first["running"])
        self.assertGreater(first["port"], 0)
        self.assertEqual(first["host"], "127.0.0.1")

        rebound = self.server.start(host="0.0.0.0", port=first["port"], token="abc123")

        self.assertTrue(rebound["running"])
        self.assertEqual(rebound["host"], "0.0.0.0")
        self.assertEqual(rebound["port"], first["port"])
        self.assertTrue(any("127.0.0.1" in url for url in rebound["access_urls"]))

    def test_token_persists_across_server_reinstantiation_until_stop(self):
        started = self.server.start(host="127.0.0.1", port=0, token="persist123")
        self.assertTrue(started["running"])
        self.assertTrue(self.state_path.exists())

        replacement = RemoteConsoleServer(self.assistant, state_path=self.state_path)
        status = replacement.status_payload()

        self.assertEqual(status["token"], "persist123")
        self.assertEqual(status["port"], started["port"])
        replacement.stop()

    def test_stop_clears_persisted_token(self):
        self.server.start(host="127.0.0.1", port=0, token="persist123")
        self.assertTrue(self.state_path.exists())

        stopped = self.server.stop()

        self.assertFalse(self.state_path.exists())
        self.assertEqual(stopped["token"], "")

    def test_client_disconnect_errors_are_treated_as_expected(self):
        self.assertTrue(self.server._is_client_disconnect_error(ConnectionAbortedError(10053, "abort")))
        self.assertTrue(self.server._is_client_disconnect_error(ConnectionResetError(10054, "reset")))
        self.assertTrue(self.server._is_client_disconnect_error(BrokenPipeError()))
        self.assertFalse(self.server._is_client_disconnect_error(RuntimeError("otro error")))


if __name__ == "__main__":
    unittest.main()
