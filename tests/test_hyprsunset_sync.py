import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "src" / "hyprsunset_sync.py"
SPEC = importlib.util.spec_from_file_location("hyprsunset_sync", MODULE_PATH)
assert SPEC and SPEC.loader
sync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync
SPEC.loader.exec_module(sync)


class ConfigTests(unittest.TestCase):
    def test_loads_valid_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.env"
            path.write_text(
                "NTFY_BASE_URL=https://example.test/\n"
                "NTFY_TOPIC=hyprsunset_123456\n"
                "TEMPERATURE=3900\n"
                "OFF_ACTION=stop\n",
                encoding="utf-8",
            )
            config = sync.load_config(path)

        self.assertEqual(config.topic_url, "https://example.test/hyprsunset_123456")
        self.assertEqual(config.temperature, 3900)
        self.assertEqual(config.off_action, "stop")

    def test_rejects_short_topic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.env"
            path.write_text("NTFY_TOPIC=short\n", encoding="utf-8")
            with self.assertRaises(sync.ConfigurationError):
                sync.load_config(path)

    def test_rejects_topic_over_ntfy_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.env"
            path.write_text(f"NTFY_TOPIC={'x' * 65}\n", encoding="utf-8")
            with self.assertRaises(sync.ConfigurationError):
                sync.load_config(path)


class StateTests(unittest.TestCase):
    def test_recognizes_boolean_messages(self):
        for value in ("on", "ON", "1", "true"):
            self.assertIs(
                sync.message_to_state({"event": "message", "message": value}), True
            )
        for value in ("off", "OFF", "0", "false"):
            self.assertIs(
                sync.message_to_state({"event": "message", "message": value}), False
            )

    def test_ignores_non_message_events(self):
        self.assertIsNone(sync.message_to_state({"event": "keepalive"}))


class StateStoreTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = sync.StateStore(Path(directory) / "state")
            self.assertIsNone(store.read())
            store.write(True)
            self.assertIs(store.read(), True)
            store.write(False)
            self.assertIs(store.read(), False)
            self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)


class FakeResponse:
    def __init__(self, events):
        self.lines = [(json.dumps(event) + "\n").encode() for event in events]

    def __enter__(self):
        return iter(self.lines)

    def __exit__(self, *_args):
        return False


class SubscriberTests(unittest.TestCase):
    def test_latest_poll_request_and_auth(self):
        config = sync.Config(
            ntfy_base_url="https://example.test",
            ntfy_topic="topic_123456",
            ntfy_token="secret",
        )
        subscriber = sync.NtfySubscriber(config)
        response = FakeResponse(
            [{"event": "message", "message": "on", "id": "abc"}]
        )

        with patch.object(sync.urllib.request, "urlopen", return_value=response) as open_mock:
            events = list(subscriber.events(poll=True))

        request = open_mock.call_args.args[0]
        self.assertIn("poll=1", request.full_url)
        self.assertIn("since=latest", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(events[0]["message"], "on")

    def test_publisher_posts_plain_state(self):
        config = sync.Config(
            ntfy_base_url="https://example.test",
            ntfy_topic="topic_123456",
            ntfy_token="secret",
        )
        response = FakeResponse([])

        with patch.object(sync.urllib.request, "urlopen", return_value=response) as open_mock:
            sync.NtfyPublisher(config).publish(False)

        request = open_mock.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.data, b"off")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")


class ControllerTests(unittest.TestCase):
    def test_on_uses_temperature(self):
        config = sync.Config("https://example.test", "topic_123456", temperature=4200)
        controller = sync.HyprsunsetController(config)

        with patch.object(controller, "_run", return_value=True) as run:
            self.assertTrue(controller.apply(True))

        run.assert_called_once_with(
            ["hyprctl", "hyprsunset", "temperature", "4200"]
        )

    def test_off_defaults_to_identity(self):
        config = sync.Config("https://example.test", "topic_123456")
        controller = sync.HyprsunsetController(config)

        with patch.object(controller, "_run", return_value=True) as run:
            self.assertTrue(controller.apply(False))

        run.assert_called_once_with(
            ["hyprctl", "hyprsunset", "identity"], quiet=True
        )


class FakeSubscriber:
    def __init__(self, events, between=None):
        self._events = events
        self._between = between

    def events(self, *, poll=False):
        del poll
        for index, event in enumerate(self._events):
            yield event
            if index == 0 and self._between is not None:
                self._between()


class FakeController:
    def __init__(self):
        self.applied = []
        self.running = True

    def apply(self, enabled):
        self.applied.append(enabled)
        return True

    def is_running(self):
        return self.running


class ReconciliationTests(unittest.TestCase):
    def test_same_message_does_not_restart_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            store = sync.StateStore(Path(directory) / "state")
            controller = FakeController()

            def desktop_set():
                store.write(True)
                controller.apply(True)

            subscriber = FakeSubscriber(
                [
                    {"event": "open"},
                    {"event": "message", "message": "on"},
                ],
                between=desktop_set,
            )

            sync.consume_connection(
                subscriber, controller, store, poll=False
            )

            self.assertEqual(controller.applied, [True])

    def test_changed_phone_state_is_applied(self):
        with tempfile.TemporaryDirectory() as directory:
            store = sync.StateStore(Path(directory) / "state")
            store.write(False)
            subscriber = FakeSubscriber(
                [{"event": "message", "message": "on"}]
            )
            controller = FakeController()

            sync.consume_connection(
                subscriber, controller, store, poll=False
            )

            self.assertEqual(controller.applied, [True])
            self.assertIs(store.read(), True)


if __name__ == "__main__":
    unittest.main()
