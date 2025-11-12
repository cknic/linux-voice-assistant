"""ESPHome API server."""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Iterable
from typing import Callable, Optional

from google.protobuf import message

# pylint: disable=no-name-in-module
from aioesphomeapi.api_pb2 import (  # type: ignore[attr-defined]
    ConnectRequest,
    ConnectResponse,
    DisconnectRequest,
    DisconnectResponse,
    GetTimeRequest,
    GetTimeResponse,
    HelloRequest,
    HelloResponse,
    PingRequest,
    PingResponse,
)

_LOGGER = logging.getLogger(__name__)


def _make_message_serializer() -> (
    tuple[
        Callable[[type], int],
        Callable[[message.Message], bytes],
        Callable[[int, bytes], message.Message],
    ]
):
    """Create message serializer and deserializer."""
    # Message type -> id
    message_type_to_id: dict[type, int] = {}

    # Message id -> type
    id_to_message_type: dict[int, type] = {}

    # pylint: disable=protected-access
    for msg_id, msg_type in message._sym_db._symbols.items():
        message_type_to_id[msg_type] = msg_id
        id_to_message_type[msg_id] = msg_type

    def get_message_id(msg_type: type) -> int:
        """Get id for a message type."""
        return message_type_to_id[msg_type]

    def serialize(msg: message.Message) -> bytes:
        """Serialize a protobuf message."""
        msg_id = message_type_to_id[type(msg)]
        msg_data = msg.SerializeToString()
        header = bytes(
            [0x00, (len(msg_data) >> 8) & 0xFF, len(msg_data) & 0xFF, msg_id]
        )
        return header + msg_data

    def deserialize(msg_id: int, msg_data: bytes) -> message.Message:
        """Deserialize a protobuf message."""
        msg_type = id_to_message_type[msg_id]
        msg = msg_type()
        msg.ParseFromString(msg_data)
        return msg

    return get_message_id, serialize, deserialize


_GET_MESSAGE_ID, _SERIALIZE, _DESERIALIZE = _make_message_serializer()


class APIServer(asyncio.Protocol):
    """ESPHome API server protocol implementation."""

    def __init__(self, name: str):
        self.name = name
        self.transport: Optional[asyncio.Transport] = None
        self._message_handlers: dict[int, list] = defaultdict(list)
        self._buffer = bytes()

    def connection_made(self, transport):
        """Handle new connection."""
        self.transport = transport
        _LOGGER.debug("Client connected")

    def data_received(self, data: bytes):
        """Handle received data."""
        self._buffer += data

        while len(self._buffer) >= 4:
            # Check preamble
            if self._buffer[0] != 0x00:
                _LOGGER.warning("Invalid preamble: %s", self._buffer[0])
                self._buffer = self._buffer[1:]
                continue

            # Get message length and type
            msg_length = (self._buffer[1] << 8) | self._buffer[2]
            msg_id = self._buffer[3]

            if len(self._buffer) < (4 + msg_length):
                # Wait for more data
                break

            # Extract message
            msg_data = self._buffer[4 : 4 + msg_length]
            self._buffer = self._buffer[4 + msg_length :]

            try:
                msg = _DESERIALIZE(msg_id, msg_data)
                _LOGGER.debug("Received: %s", msg)
                self._handle_message(msg)
            except Exception:
                _LOGGER.exception("Error deserializing message")

    def _handle_message(self, msg: message.Message):
        """Handle a received message."""
        try:
            if isinstance(msg, HelloRequest):
                self.send_messages([HelloResponse(server_info=self.name, api_version_minor=1, api_version_major=1)])
            elif isinstance(msg, ConnectRequest):
                self.send_messages([ConnectResponse(invalid_password=False)])
            elif isinstance(msg, DisconnectRequest):
                self.send_messages([DisconnectResponse()])
                if self.transport:
                    self.transport.close()
            elif isinstance(msg, PingRequest):
                self.send_messages([PingResponse()])
            elif isinstance(msg, GetTimeRequest):
                import time
                self.send_messages([GetTimeResponse(epoch_seconds=int(time.time()))])
            else:
                # Let subclass handle it
                responses = self.handle_message(msg)
                if responses:
                    self.send_messages(responses)
        except Exception:
            _LOGGER.exception("Error handling message: %s", msg)

    def handle_message(self, msg: message.Message) -> Iterable[message.Message]:
        """Handle message (override in subclass)."""
        return []

    def send_messages(self, messages: Iterable[message.Message]):
        """Send messages to client."""
        if not self.transport:
            return

        for msg in messages:
            try:
                data = _SERIALIZE(msg)
                self.transport.write(data)
                _LOGGER.debug("Sent: %s", msg)
            except Exception:
                _LOGGER.exception("Error sending message: %s", msg)

    def connection_lost(self, exc):
        """Handle connection loss."""
        _LOGGER.debug("Client disconnected")
        self.transport = None
