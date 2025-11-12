"""Partial ESPHome server implementation."""

import asyncio
import logging
from abc import abstractmethod
from collections.abc import Iterable
from typing import TYPE_CHECKING, List, Optional

# pylint: disable=no-name-in-module
from aioesphomeapi.api_pb2 import (  # type: ignore[attr-defined]
    DisconnectRequest,
    DisconnectResponse,
    HelloRequest,
    HelloResponse,
    PingRequest,
    PingResponse,
)
from aioesphomeapi.core import MESSAGE_TYPE_TO_PROTO
from google.protobuf import message

def _varuint_to_bytes(value: int) -> bytes:
    """Convert a varuint to bytes."""
    if value <= 0x7F:
        return bytes((value,))

    result = bytearray()
    while value:
        temp = value & 0x7F
        value >>= 7
        if value:
            result.append(temp | 0x80)
        else:
            result.append(temp)

    return bytes(result)


varuint_to_bytes = _varuint_to_bytes


PROTO_TO_MESSAGE_TYPE = {v: k for k, v in MESSAGE_TYPE_TO_PROTO.items()}

_LOGGER = logging.getLogger(__name__)


class APIServer(asyncio.Protocol):

    def __init__(self, name: str) -> None:
        self.name = name

        self._buffer: Optional[bytes] = None
        self._buffer_len: int = 0
        self._pos: int = 0
        self._transport = None
        self._writelines = None

    @abstractmethod
    def handle_message(self, msg: message.Message) -> Iterable[message.Message]:
        pass

    def process_packet(self, msg_type: int, packet_data: bytes) -> None:
        msg_class = MESSAGE_TYPE_TO_PROTO[msg_type]
        msg_inst = msg_class.FromString(packet_data)

        if isinstance(msg_inst, HelloRequest):
            self.send_messages(
                [
                    HelloResponse(
                        api_version_major=1,
                        api_version_minor=10,
                        name=self.name,
                    )
                ]
            )
            return

        elif isinstance(msg_inst, DisconnectRequest):
            self.send_messages([DisconnectResponse()])
            _LOGGER.debug("Disconnect requested")
            if self._transport:
                self._transport.close()
                self._transport = None
                self._writelines = None
        elif isinstance(msg_inst, PingRequest):
            self.send_messages([PingResponse()])
        elif msgs := self.handle_message(msg_inst):
            if isinstance(msgs, message.Message):
                msgs = [msgs]

            self.send_messages(msgs)

    def send_messages(self, msgs: List[message.Message]):
        if self._writelines is None:
            return

        packets = [
            (PROTO_TO_MESSAGE_TYPE[msg.__class__], msg.SerializeToString())
            for msg in msgs
        ]
        # Manually create plain text packets using the new API
        out: list[bytes] = []
        for packet in packets:
            type_: int = packet[0]
            data: bytes = packet[1]
            out.append(b"\0")
            out.append(varuint_to_bytes(len(data)))
            out.append(varuint_to_bytes(type_))
            if data:
                out.append(data)
        
        self._writelines(out)

    def connection_made(self, transport) -> None:
        self._transport = transport
        self._writelines = transport.writelines

    def data_received(self, data: bytes):
        if self._buffer is None:
            self._buffer = data
            self._buffer_len = len(data)
        else:
            self._buffer += data
            self._buffer_len += len(data)

        while self._buffer_len >= 3:
            self._pos = 0
            # Read preamble, which should always 0x00
            if (preamble := self._read_varuint()) != 0x00:
                _LOGGER.error("Incorrect preamble: %s", preamble)
                return

            if (length := self._read_varuint()) == -1:
                _LOGGER.error("Incorrect length: %s", length)
                return

            if (msg_type := self._read_varuint()) == -1:
                _LOGGER.error("Incorrect message type: %s", msg_type)
                return

            if length == 0:
                # Empty message (allowed)
                self._remove_from_buffer()
                self.process_packet(msg_type, b"")
                continue

            if (packet_data := self._read(length)) is None:
                return

            self._remove_from_buffer()
            self.process_packet(msg_type, packet_data)

    def _read(self, length: int) -> bytes | None:
        """Read exactly length bytes from the buffer or None if all the bytes are not yet available."""
        new_pos = self._pos + length
        if self._buffer_len < new_pos:
            return None
        original_pos = self._pos
        self._pos = new_pos
        if TYPE_CHECKING:
            assert self._buffer is not None, "Buffer should be set"
        cstr = self._buffer
        # Important: we must keep the bounds check (self._buffer_len < new_pos)
        # above to verify we never try to read past the end of the buffer
        return cstr[original_pos:new_pos]

    def connection_lost(self, exc):
        self._transport = None
        self._writelines = None

    def _read_varuint(self) -> int:
        """Read a varuint from the buffer or -1 if the buffer runs out of bytes."""
        if not self._buffer:
            return -1

        result = 0
        bitpos = 0
        cstr = self._buffer
        while self._buffer_len > self._pos:
            val = cstr[self._pos]
            self._pos += 1
            result |= (val & 0x7F) << bitpos
            if (val & 0x80) == 0:
                return result
            bitpos += 7
        return -1

    def _remove_from_buffer(self) -> None:
        """Remove data from the buffer."""
        end_of_frame_pos = self._pos
        self._buffer_len -= end_of_frame_pos
        if self._buffer_len == 0:
            # This is the best case scenario, we can just set the buffer to None
            # and don't have to copy the data. This is the most common case as well.
            self._buffer = None
            return
        if TYPE_CHECKING:
            assert self._buffer is not None, "Buffer should be set"
        # This is the worst case scenario, we have to copy the data
        # and can't just use the buffer directly. This should only happen
        # when we read multiple frames at once because the event loop
        # is blocked and we cannot pull the data out of the buffer fast enough.
        cstr = self._buffer
        # Important: we must use the explicit length for the slice
        # since Cython will stop at any '\0' character if we don't
        self._buffer = cstr[end_of_frame_pos : self._buffer_len + end_of_frame_pos]
