from __future__ import annotations

from dataclasses import dataclass
import os
import threading
import time
from typing import Any, Callable

import paho.mqtt.client as mqtt

from wandering_contract import serialize_behavior_payload


TOPIC = "pauseable/ai/wandering/decision"
QOS = 1
RETAIN = False


def mqtt_code_value(code: Any) -> int:
    return int(getattr(code, "value", code))


def env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return None
    return value


@dataclass(frozen=True)
class PublisherConfig:
    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    client_id: str = "pauseable-wandering-ai-pi5-home-01"
    keepalive: int = 60
    connect_timeout: float = 8.0
    publish_timeout: float = 5.0
    publish_retries: int = 3

    def __post_init__(self) -> None:
        if not self.host:
            raise ValueError("MQTT host must not be empty")

        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("MQTT port must be between 1 and 65535")

        if self.keepalive <= 0:
            raise ValueError("MQTT keepalive must be positive")

        if self.connect_timeout <= 0:
            raise ValueError("MQTT connect timeout must be positive")

        if self.publish_timeout <= 0:
            raise ValueError("MQTT publish timeout must be positive")

        if type(self.publish_retries) is not int or self.publish_retries < 1:
            raise ValueError("MQTT publish retries must be positive")

        if self.password is not None and self.username is None:
            raise ValueError("MQTT_USER is required when MQTT_PASSWORD is set")

    @classmethod
    def from_env(cls) -> "PublisherConfig":
        return cls(
            host=os.getenv("MQTT_HOST", "127.0.0.1"),
            port=int(os.getenv("MQTT_PORT", "1883")),
            username=env_value("MQTT_USER"),
            password=env_value("MQTT_PASSWORD"),
            client_id=os.getenv(
                "MQTT_CLIENT_ID",
                "pauseable-wandering-ai-pi5-home-01",
            ),
        )


class WanderingMqttPublisher:
    def __init__(
        self,
        config: PublisherConfig,
        *,
        client: Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._sleep = sleeper
        self._connected = threading.Event()
        self._connect_finished = threading.Event()
        self._last_connect_error: str | None = None
        self._loop_started = False

        if client is None:
            self._client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=config.client_id,
                protocol=mqtt.MQTTv311,
            )
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.reconnect_delay_set(
                min_delay=1,
                max_delay=30,
            )

            if config.username is not None:
                self._client.username_pw_set(
                    config.username,
                    config.password or "",
                )
        else:
            self._client = client

        if self._client.is_connected():
            self._connected.set()

    def _on_connect(
        self,
        client: Any,
        userdata: Any,
        connect_flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        code = mqtt_code_value(reason_code)

        if code == 0:
            self._last_connect_error = None
            self._connected.set()
        else:
            self._last_connect_error = str(reason_code)
            self._connected.clear()

        self._connect_finished.set()

    def _on_disconnect(
        self,
        client: Any,
        userdata: Any,
        disconnect_flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        self._connected.clear()

    def connect(self) -> None:
        if self._client.is_connected():
            self._connected.set()
            return

        self._connected.clear()
        self._connect_finished.clear()
        self._last_connect_error = None

        try:
            result = self._client.connect(
                self.config.host,
                self.config.port,
                keepalive=self.config.keepalive,
            )
        except Exception as error:
            raise RuntimeError(
                f"MQTT connection failed: {error}"
            ) from error

        if mqtt_code_value(result) != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(
                f"MQTT connect returned rc={result}"
            )

        self._client.loop_start()
        self._loop_started = True

        if self._client.is_connected():
            self._connected.set()
            return

        if not self._connect_finished.wait(
            timeout=self.config.connect_timeout
        ):
            self.close()
            raise RuntimeError("MQTT connection timed out")

        if not self._connected.is_set():
            reason = self._last_connect_error or "unknown reason"
            self.close()
            raise RuntimeError(
                f"MQTT connection was rejected: {reason}"
            )

    def _ensure_connection(self) -> None:
        if self._client.is_connected():
            self._connected.set()
            return

        self._connected.clear()
        self._connect_finished.clear()

        try:
            result = self._client.reconnect()
        except Exception as error:
            raise RuntimeError(
                f"MQTT reconnection failed: {error}"
            ) from error

        if mqtt_code_value(result) != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(
                f"MQTT reconnect returned rc={result}"
            )

        if self._client.is_connected():
            self._connected.set()
            return

        if not self._connect_finished.wait(
            timeout=self.config.connect_timeout
        ):
            raise RuntimeError("MQTT reconnection timed out")

        if not self._connected.is_set():
            reason = self._last_connect_error or "unknown reason"
            raise RuntimeError(
                f"MQTT reconnection was rejected: {reason}"
            )

    def publish(self, payload: dict[str, Any]) -> str:
        encoded = serialize_behavior_payload(payload)
        last_error: Exception | None = None

        for attempt in range(1, self.config.publish_retries + 1):
            try:
                self._ensure_connection()

                message_info = self._client.publish(
                    TOPIC,
                    encoded,
                    qos=QOS,
                    retain=RETAIN,
                )

                if (
                    mqtt_code_value(message_info.rc)
                    != mqtt.MQTT_ERR_SUCCESS
                ):
                    raise RuntimeError(
                        f"MQTT publish returned rc={message_info.rc}"
                    )

                message_info.wait_for_publish(
                    timeout=self.config.publish_timeout
                )

                if not message_info.is_published():
                    raise TimeoutError(
                        "MQTT publish acknowledgement timed out"
                    )

                return payload["event_id"]
            except Exception as error:
                last_error = error

            if attempt < self.config.publish_retries:
                delay = min(2 ** (attempt - 1), 30)
                self._sleep(float(delay))

        raise RuntimeError(
            "MQTT publish failed after "
            f"{self.config.publish_retries} attempts: {last_error}"
        ) from last_error

    def close(self) -> None:
        try:
            if self._client.is_connected():
                self._client.disconnect()
        finally:
            if self._loop_started:
                self._client.loop_stop()
                self._loop_started = False

            self._connected.clear()

    def __enter__(self) -> "WanderingMqttPublisher":
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: Any,
        exc_value: Any,
        traceback: Any,
    ) -> None:
        self.close()
