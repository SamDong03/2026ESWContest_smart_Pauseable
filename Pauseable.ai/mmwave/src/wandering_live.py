from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import os
import selectors
import time
from typing import Any, BinaryIO, Callable

from trajectory_windows import (
    MAX_PACKET_BYTES,
    parse_event,
)
from wandering_contract import serialize_behavior_payload


class LiveInputError(ValueError):
    pass


@dataclass(frozen=True)
class LiveEvent:
    event: dict[str, Any]
    received_at: float


@dataclass(frozen=True)
class LiveTimeout:
    pass


@dataclass(frozen=True)
class LiveEnd:
    pass


class JsonlEventDecoder:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.line_number = 0
        self.closed = False

    def _decode_line(
        self,
        raw: bytes,
    ) -> dict[str, Any] | None:
        self.line_number += 1

        if raw.endswith(b"\r"):
            raw = raw[:-1]

        if len(raw) > MAX_PACKET_BYTES:
            raise LiveInputError(
                f"Line {self.line_number}: "
                "record exceeds maximum packet size"
            )

        if not raw.strip():
            return None

        try:
            return parse_event(raw)
        except (ValueError, TypeError) as error:
            raise LiveInputError(
                f"Line {self.line_number}: {error}"
            ) from error

    def _validate_partial(self) -> None:
        size = len(self.buffer)

        if size <= MAX_PACKET_BYTES:
            return

        if (
            size == MAX_PACKET_BYTES + 1
            and self.buffer[-1:] == b"\r"
        ):
            return

        raise LiveInputError(
            f"Line {self.line_number + 1}: "
            "record exceeds maximum packet size"
        )

    def feed(
        self,
        data: bytes,
    ) -> list[dict[str, Any]]:
        if self.closed:
            raise RuntimeError(
                "Decoder is already closed"
            )

        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")

        self.buffer.extend(data)
        events = []

        while True:
            try:
                delimiter = self.buffer.index(10)
            except ValueError:
                break

            raw = bytes(
                self.buffer[:delimiter]
            )
            del self.buffer[: delimiter + 1]

            event = self._decode_line(raw)

            if event is not None:
                events.append(event)

        self._validate_partial()

        return events

    def finish(self) -> list[dict[str, Any]]:
        if self.closed:
            return []

        self.closed = True

        if not self.buffer:
            return []

        raw = bytes(self.buffer)
        self.buffer.clear()
        event = self._decode_line(raw)

        return [] if event is None else [event]


class SelectorLiveSource:
    def __init__(
        self,
        stream: BinaryIO,
        *,
        clock: Callable[[], float] = time.monotonic,
        read_size: int = 4096,
    ) -> None:
        if type(read_size) is not int or read_size <= 0:
            raise ValueError(
                "read_size must be positive"
            )

        self.stream = stream
        self.clock = clock
        self.read_size = read_size
        self.decoder = JsonlEventDecoder()
        self.pending = deque()
        self.ended = False
        self.selector = selectors.SelectSelector()

        try:
            self.file_descriptor = stream.fileno()
            self.selector.register(
                self.file_descriptor,
                selectors.EVENT_READ,
            )
        except (OSError, ValueError) as error:
            self.selector.close()
            raise LiveInputError(
                f"Cannot monitor live input: {error}"
            ) from error

    def receive(
        self,
        timeout: float | None,
    ) -> LiveEvent | LiveTimeout | LiveEnd:
        if self.pending:
            return self.pending.popleft()

        if self.ended:
            return LiveEnd()

        deadline = (
            None
            if timeout is None
            else self.clock() + timeout
        )

        while True:
            remaining = None

            if deadline is not None:
                remaining = max(
                    0.0,
                    deadline - self.clock(),
                )

            try:
                ready = self.selector.select(
                    remaining
                )
            except OSError as error:
                raise LiveInputError(
                    f"Live input polling failed: {error}"
                ) from error

            if not ready:
                return LiveTimeout()

            try:
                data = os.read(
                    self.file_descriptor,
                    self.read_size,
                )
            except OSError as error:
                raise LiveInputError(
                    f"Live input read failed: {error}"
                ) from error

            received_at = self.clock()

            if data == b"":
                self.ended = True
                events = self.decoder.finish()
            else:
                events = self.decoder.feed(data)

            for event in events:
                self.pending.append(
                    LiveEvent(
                        event=event,
                        received_at=received_at,
                    )
                )

            if self.pending:
                return self.pending.popleft()

            if self.ended:
                return LiveEnd()

    def close(self) -> None:
        self.selector.close()

    def __enter__(self) -> "SelectorLiveSource":
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        self.close()


def write_payload(
    payload: dict[str, Any],
    output: Callable[[str], None],
) -> None:
    output(
        serialize_behavior_payload(payload)
    )


def run_live_source(
    source: Any,
    runtime: Any,
    *,
    silence_timeout: float,
    clock: Callable[[], float] = time.monotonic,
    output: Callable[[str], None] = print,
) -> int:
    if (
        type(silence_timeout) not in (int, float)
        or not math.isfinite(silence_timeout)
        or silence_timeout <= 0
    ):
        raise ValueError(
            "silence_timeout must be positive"
        )

    published = 0
    silence_active = False
    deadline = clock() + float(
        silence_timeout
    )

    while True:
        wait_seconds = (
            None
            if silence_active
            else max(0.0, deadline - clock())
        )

        try:
            item = source.receive(wait_seconds)
        except LiveInputError:
            if not silence_active:
                payload = runtime.mark_input_missing()

                if payload is not None:
                    write_payload(payload, output)
                    published += 1

            raise

        if isinstance(item, LiveTimeout):
            if silence_active:
                continue

            payload = runtime.mark_input_missing()

            if payload is not None:
                write_payload(payload, output)
                published += 1

            silence_active = True
            continue

        if isinstance(item, LiveEvent):
            if (
                not silence_active
                and runtime.has_source_gap_before(
                    item.event,
                    silence_timeout=float(silence_timeout),
                )
            ):
                payload = runtime.mark_input_missing(
                    occurred_at=item.event.get("occurred_at")
                )

                if payload is not None:
                    write_payload(payload, output)
                    published += 1

            silence_active = False
            deadline = (
                item.received_at
                + float(silence_timeout)
            )
            payload = runtime.process_event(
                item.event
            )

            if payload is not None:
                write_payload(payload, output)
                published += 1

            continue

        if isinstance(item, LiveEnd):
            if not silence_active:
                payload = runtime.finish()

                if payload is not None:
                    write_payload(payload, output)
                    published += 1

            return published

        raise RuntimeError(
            "Unknown live source result"
        )


def run_live_stream(
    stream: BinaryIO,
    runtime: Any,
    *,
    silence_timeout: float,
    clock: Callable[[], float] = time.monotonic,
    output: Callable[[str], None] = print,
) -> int:
    with SelectorLiveSource(
        stream,
        clock=clock,
    ) as source:
        return run_live_source(
            source,
            runtime,
            silence_timeout=silence_timeout,
            clock=clock,
            output=output,
        )
