#!/usr/bin/env python3
"""Synchronize Hyprsunset with an on/off state published to an ntfy topic."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


LOG = logging.getLogger("hyprsunset-sync")
TOPIC_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
ON_VALUES = frozenset({"on", "1", "true"})
OFF_VALUES = frozenset({"off", "0", "false"})


class ConfigurationError(ValueError):
    """Raised when the local configuration is invalid."""


@dataclass(frozen=True)
class Config:
    ntfy_base_url: str
    ntfy_topic: str
    temperature: int = 4500
    off_action: str = "identity"
    ntfy_token: str = ""
    reconnect_min_seconds: float = 2.0
    reconnect_max_seconds: float = 60.0

    @property
    def topic_url(self) -> str:
        topic = urllib.parse.quote(self.ntfy_topic, safe="")
        return f"{self.ntfy_base_url.rstrip('/')}/{topic}"


class StateStore:
    def __init__(self, path: Path | None = None) -> None:
        state_home = Path(
            os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")
        )
        self.path = path or state_home / "hyprsunset-sync" / "state"

    def read(self) -> bool | None:
        try:
            value = self.path.read_text(encoding="utf-8").strip().lower()
        except FileNotFoundError:
            return None
        if value == "on":
            return True
        if value == "off":
            return False
        return None

    def write(self, enabled: bool) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temporary.write_text("on\n" if enabled else "off\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, self.path)


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ConfigurationError(f"configuration file does not exist: {path}") from exc

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigurationError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ConfigurationError(f"{path}:{line_number}: invalid setting name {key!r}")
        values[key] = _strip_optional_quotes(value.strip())
    return values


def load_config(path: Path) -> Config:
    values = read_env_file(path)
    base_url = values.get("NTFY_BASE_URL", "https://ntfy.sh").rstrip("/")
    topic = values.get("NTFY_TOPIC", "")
    token = values.get("NTFY_TOKEN", "")
    off_action = values.get("OFF_ACTION", "identity").lower()

    parsed_url = urllib.parse.urlparse(base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ConfigurationError("NTFY_BASE_URL must be an http(s) URL")
    if not TOPIC_PATTERN.fullmatch(topic):
        raise ConfigurationError(
            "NTFY_TOPIC must be 8-64 characters using only letters, numbers, _ or -"
        )
    try:
        temperature = int(values.get("TEMPERATURE", "4500"))
    except ValueError as exc:
        raise ConfigurationError("TEMPERATURE must be an integer") from exc
    if not 1000 <= temperature <= 10000:
        raise ConfigurationError("TEMPERATURE must be between 1000 and 10000 kelvin")
    if off_action not in {"identity", "stop"}:
        raise ConfigurationError("OFF_ACTION must be 'identity' or 'stop'")

    return Config(
        ntfy_base_url=base_url,
        ntfy_topic=topic,
        temperature=temperature,
        off_action=off_action,
        ntfy_token=token,
    )


class NtfySubscriber:
    def __init__(self, config: Config, timeout: float = 90.0) -> None:
        self.config = config
        self.timeout = timeout

    def _request(self, *, poll: bool) -> urllib.request.Request:
        query = {"since": "latest"}
        if poll:
            query["poll"] = "1"
        url = f"{self.config.topic_url}/json?{urllib.parse.urlencode(query)}"
        headers = {
            "Accept": "application/x-ndjson",
            "User-Agent": "hyprsunset-sync/1",
        }
        if self.config.ntfy_token:
            headers["Authorization"] = f"Bearer {self.config.ntfy_token}"
        return urllib.request.Request(url, headers=headers)

    def events(self, *, poll: bool = False) -> Iterator[dict[str, object]]:
        request = self._request(poll=poll)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            for raw_line in response:
                if not raw_line.strip():
                    continue
                try:
                    event = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    LOG.warning("Ignoring malformed ntfy response line")
                    continue
                if isinstance(event, dict):
                    yield event


class NtfyPublisher:
    def __init__(self, config: Config, timeout: float = 15.0) -> None:
        self.config = config
        self.timeout = timeout

    def publish(self, enabled: bool) -> None:
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "User-Agent": "hyprsunset-sync/1",
        }
        if self.config.ntfy_token:
            headers["Authorization"] = f"Bearer {self.config.ntfy_token}"
        request = urllib.request.Request(
            self.config.topic_url,
            data=b"on" if enabled else b"off",
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout):
            pass


class HyprsunsetController:
    def __init__(self, config: Config, *, dry_run: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run

    def _run(self, command: list[str], *, quiet: bool = False) -> bool:
        if self.dry_run:
            LOG.info("DRY RUN: %s", " ".join(command))
            return True
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL if quiet else subprocess.PIPE,
                stderr=subprocess.DEVNULL if quiet else subprocess.PIPE,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            if not quiet:
                LOG.warning("Could not run %s: %s", " ".join(command), exc)
            return False
        if result.returncode != 0 and not quiet:
            detail = (result.stderr or result.stdout or "").strip()
            LOG.warning(
                "Command failed (%d): %s%s",
                result.returncode,
                " ".join(command),
                f": {detail}" if detail else "",
            )
        return result.returncode == 0

    def _set_temperature(self) -> bool:
        return self._run(
            ["hyprctl", "hyprsunset", "temperature", str(self.config.temperature)]
        )

    def is_running(self) -> bool:
        return self._run(
            ["hyprctl", "hyprsunset", "temperature"], quiet=True
        )

    def apply(self, enabled: bool) -> bool:
        if enabled:
            if self._set_temperature():
                LOG.info("Eye Comfort Shield ON -> Hyprsunset %dK", self.config.temperature)
                return True

            LOG.info("Hyprsunset is unavailable; starting its user service")
            if not self._run(
                ["systemctl", "--user", "start", "hyprsunset.service"], quiet=True
            ):
                LOG.warning(
                    "Could not start hyprsunset.service; ensure Hyprsunset is installed"
                )
                return False
            for _ in range(8):
                time.sleep(0.25)
                if self._set_temperature():
                    LOG.info(
                        "Eye Comfort Shield ON -> Hyprsunset %dK",
                        self.config.temperature,
                    )
                    return True
            return False

        # Identity is harmless and is Hyprsunset's supported way to disable filtering.
        identity_applied = self._run(
            ["hyprctl", "hyprsunset", "identity"], quiet=True
        )
        if self.config.off_action == "stop":
            stopped = self._run(
                ["systemctl", "--user", "stop", "hyprsunset.service"], quiet=True
            )
            if not stopped:
                # Covers installations launched by Hyprland's exec-once instead.
                self._run(["pkill", "-x", "hyprsunset"], quiet=True)
            LOG.info("Eye Comfort Shield OFF -> Hyprsunset stopped")
            return True

        if identity_applied:
            LOG.info("Eye Comfort Shield OFF -> Hyprsunset identity")
        else:
            LOG.info("Eye Comfort Shield OFF -> Hyprsunset already inactive")
        return True


def message_to_state(event: dict[str, object]) -> bool | None:
    if event.get("event") != "message":
        return None
    message = str(event.get("message", "")).strip().lower()
    if message in ON_VALUES:
        return True
    if message in OFF_VALUES:
        return False
    LOG.warning("Ignoring unknown state message: %r", message)
    return None


def consume_connection(
    subscriber: NtfySubscriber,
    controller: HyprsunsetController,
    state_store: StateStore,
    *,
    poll: bool,
) -> tuple[bool, bool]:
    """Consume one connection and return (saw_state, applied_successfully)."""
    applied = False
    saw_state = False
    reconcile_attempted = False
    reconciled = False

    for event in subscriber.events(poll=poll):
        state = message_to_state(event)
        if state is not None:
            saw_state = True
            previous_state = state_store.read()

            if previous_state != state:
                state_store.write(state)
                reconcile_attempted = True
                applied = controller.apply(state)
                reconciled = applied
            elif reconcile_attempted and not reconciled:
                # Retry a retained state that could not be applied during startup.
                applied = controller.apply(state)
                reconciled = applied
            elif not reconcile_attempted:
                # The desktop control wrote and applied this state immediately
                # before publishing it. Do not restart Hyprsunset's transition.
                reconciled = True
            continue

        event_type = event.get("event")
        stored_state = state_store.read()
        if event_type == "open" and stored_state is not None:
            reconcile_attempted = True
            applied = controller.apply(stored_state)
            reconciled = applied
        elif (
            event_type == "keepalive"
            and stored_state is True
            and not controller.is_running()
        ):
            # Recover if Hyprsunset crashed without repeatedly resetting a healthy
            # transition on every ntfy keepalive.
            reconcile_attempted = True
            applied = controller.apply(True)
            reconciled = applied
    return saw_state, applied


def check_dependencies() -> bool:
    missing = [name for name in ("hyprctl", "hyprsunset", "systemctl") if not shutil.which(name)]
    if missing:
        LOG.error("Missing required command(s): %s", ", ".join(missing))
        return False
    LOG.info("Required PC commands are installed")
    return True


def parse_args(argv: list[str]) -> argparse.Namespace:
    default_config = (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "hyprsunset-sync"
        / "config.env"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=default_config)
    parser.add_argument(
        "--once",
        action="store_true",
        help="fetch and apply the latest cached state, then exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show Hyprsunset commands without executing them",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate configuration and installed commands, then exit",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="print the synchronized state as on, off, or unknown",
    )
    parser.add_argument(
        "--set",
        choices=("on", "off", "toggle"),
        help="apply and publish a state (used by desktop controls)",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        config = load_config(args.config)
    except ConfigurationError as exc:
        LOG.error("%s", exc)
        return 2

    if args.check:
        return 0 if check_dependencies() else 1

    subscriber = NtfySubscriber(config)
    controller = HyprsunsetController(config, dry_run=args.dry_run)
    state_store = StateStore()

    if args.status:
        state = state_store.read()
        print("unknown" if state is None else ("on" if state else "off"))
        return 0

    if args.set:
        current = state_store.read()
        enabled = (
            not current
            if args.set == "toggle" and current is not None
            else args.set in {"on", "toggle"}
        )
        if not controller.apply(enabled):
            return 1
        state_store.write(enabled)
        try:
            NtfyPublisher(config).publish(enabled)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            # The desktop control must still work without internet. A later phone
            # event or panel action will reconcile the shared topic.
            LOG.warning("Applied locally, but could not publish to ntfy: %s", exc)
        return 0

    if args.once:
        try:
            saw_state, applied = consume_connection(
                subscriber, controller, state_store, poll=True
            )
        except (OSError, urllib.error.URLError) as exc:
            LOG.error("ntfy request failed: %s", exc)
            return 1
        if not saw_state:
            LOG.error("No retained state found; publish 'on' or 'off' from Tasker")
            return 3
        return 0 if applied else 1

    delay = config.reconnect_min_seconds
    while True:
        try:
            LOG.info("Subscribing to configured ntfy topic at %s", config.ntfy_base_url)
            consume_connection(subscriber, controller, state_store, poll=False)
            delay = config.reconnect_min_seconds
            LOG.warning("ntfy stream ended; reconnecting in %.0fs", delay)
            time.sleep(delay)
        except KeyboardInterrupt:
            return 0
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            LOG.warning("ntfy connection lost: %s; retrying in %.0fs", exc, delay)
            time.sleep(delay)
            delay = min(delay * 2, config.reconnect_max_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
