"""Voice satellite protocol."""

import logging
import time
from collections.abc import Iterable
from typing import Dict, Optional, Set, Union

# pylint: disable=no-name-in-module
from aioesphomeapi.api_pb2 import (  # type: ignore[attr-defined]
    DeviceInfoRequest,
    DeviceInfoResponse,
    ListEntitiesDoneResponse,
    ListEntitiesRequest,
    MediaPlayerCommandRequest,
    SubscribeHomeAssistantStatesRequest,
    VoiceAssistantAnnounceFinished,
    VoiceAssistantAnnounceRequest,
    VoiceAssistantAudio,
    VoiceAssistantConfigurationRequest,
    VoiceAssistantConfigurationResponse,
    VoiceAssistantEventResponse,
    VoiceAssistantRequest,
    VoiceAssistantSetConfiguration,
    VoiceAssistantTimerEventResponse,
    VoiceAssistantWakeWord,
)
from aioesphomeapi.model import (
    VoiceAssistantEventType,
    VoiceAssistantFeature,
    VoiceAssistantTimerEventType,
)
from google.protobuf import message

from .api_server import APIServer
from .entity import MediaPlayerEntity, ThinkingSoundEntity
from .models import AvailableWakeWord, ServerState, WakeWordType
from .util import call_all

_LOGGER = logging.getLogger(__name__)


class VoiceSatelliteProtocol(APIServer):
    """ESPHome voice satellite protocol implementation."""
    
    def __init__(self, state: ServerState) -> None:
        super().__init__(state.name)

        self.state = state
        self.state.satellite = self

        if self.state.media_player_entity is None:
            self.state.media_player_entity = MediaPlayerEntity(
                server=self,
                state=state,
                key=len(state.entities),
                name="Media Player",
                object_id="linux_voice_assistant_media_player",
                music_player=state.music_player,
                announce_player=state.tts_player,
            )
            self.state.entities.append(self.state.media_player_entity)

        existing_thinking_sound_switches = [
            entity
            for entity in self.state.entities
            if isinstance(entity, ThinkingSoundEntity)
        ]
        if existing_thinking_sound_switches:
            self.state.thinking_sound_entity = existing_thinking_sound_switches[0]
            for extra in existing_thinking_sound_switches[1:]:
                self.state.entities.remove(extra)

        # Add/update thinking sound entity
        thinking_sound_switch = self.state.thinking_sound_entity
        if thinking_sound_switch is None:
            thinking_sound_switch = ThinkingSoundEntity(
                server=self,
                key=len(state.entities),
                name="Thinking Sound",
                object_id="thinking_sound",
                get_thinking_sound_enabled=lambda: self.state.thinking_sound_enabled,
                set_thinking_sound_enabled=self._set_thinking_sound_enabled,
            )
            self.state.entities.append(thinking_sound_switch)
            self.state.thinking_sound_entity = thinking_sound_switch
        elif thinking_sound_switch not in self.state.entities:
            self.state.entities.append(thinking_sound_switch)

        # Load thinking sound enabled state from preferences
        if hasattr(self.state.preferences, 'thinking_sound') and self.state.preferences.thinking_sound in (0, 1):
            self.state.thinking_sound_enabled = bool(self.state.preferences.thinking_sound)
        else:
            self.state.thinking_sound_enabled = False

        thinking_sound_switch.server = self
        thinking_sound_switch.update_get_thinking_sound_enabled(lambda: self.state.thinking_sound_enabled)
        thinking_sound_switch.update_set_thinking_sound_enabled(self._set_thinking_sound_enabled)
        thinking_sound_switch.sync_with_state()

        self._is_streaming_audio = False
        self._tts_url: Optional[str] = None
        self._tts_played = False
        self._continue_conversation = False
        self._timer_finished = False
        self._processing = False
        self._external_wake_words: Dict[str, VoiceAssistantExternalWakeWord] = {}

    def _set_thinking_sound_enabled(self, new_state: bool) -> None:
        """Set thinking sound enabled state."""
        self.state.thinking_sound_enabled = bool(new_state)
        self.state.preferences.thinking_sound = 1 if self.state.thinking_sound_enabled else 0

        if self.state.thinking_sound_enabled:
            _LOGGER.debug("Thinking sound enabled")
        else:
            _LOGGER.debug("Thinking sound disabled")
        self.state.save_preferences()
        

    def handle_voice_event(
        self, event_type: VoiceAssistantEventType, data: Dict[str, str]
    ) -> None:
        """Handle voice assistant events."""
        _LOGGER.debug("Voice event: type=%s, data=%s", event_type.name, data)

        if event_type == VoiceAssistantEventType.VOICE_ASSISTANT_RUN_START:
            self._tts_url = data.get("url")
            self._tts_played = False
            self._continue_conversation = False
            self._run_finished = False
        elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_STT_START:
            self.state.event_bus.publish("voice_stt_start", data)
        elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_STT_VAD_START:
            self.state.event_bus.publish("voice_vad_start", data)
        elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_INTENT_START:
            self.state.event_bus.publish("voice_intent_start", data)
            if self.state.thinking_sound_enabled:
                processing = getattr(self.state, "processing_sound", None)
                if processing:
                    _LOGGER.debug("Playing processing sound: %s", processing)
                    self.state.stop_word.is_active = True
                    self.duck()
                    self.state.tts_player.play(self.state.processing_sound)
        elif event_type in (
            VoiceAssistantEventType.VOICE_ASSISTANT_STT_VAD_END,
            VoiceAssistantEventType.VOICE_ASSISTANT_STT_END,
        ):
            self.state.event_bus.publish("voice_stt_end", data)
            self._is_streaming_audio = False
        elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_INTENT_PROGRESS:
            if data.get("tts_start_streaming") == "1":
                self.play_tts()
        elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_INTENT_END:
            self.state.event_bus.publish("voice_intent_end", data)
            if data.get("continue_conversation") == "1":
                self._continue_conversation = True
        elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_TTS_END:
            self._tts_url = data.get("url")
            self.play_tts()
        elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END:
            self._run_finished = True
            if not self._is_speaking:
                self._determine_final_state()
        elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_ERROR:
            self.state.event_bus.publish("voice_error", data)
            self._determine_final_state()

    def handle_timer_event(
        self,
        event_type: VoiceAssistantTimerEventType,
        msg: VoiceAssistantTimerEventResponse,
    ) -> None:
        """Handle timer events."""
        _LOGGER.debug("Timer event: type=%s", event_type.name)
        if event_type == VoiceAssistantTimerEventType.VOICE_ASSISTANT_TIMER_FINISHED:
            if not self._timer_finished:
                self.state.stop_word.is_active = True
                self._timer_finished = True
                self.duck()
                self._play_timer_finished()

    def handle_message(self, msg: message.Message) -> Iterable[message.Message]:
        """Handle ESPHome protocol messages."""
        if isinstance(msg, VoiceAssistantEventResponse):
            data: Dict[str, str] = {}
            for arg in msg.data:
                data[arg.name] = arg.value
            self.handle_voice_event(VoiceAssistantEventType(msg.event_type), data)
        elif isinstance(msg, VoiceAssistantAnnounceRequest):
            _LOGGER.debug("Announcing: %s", msg.text)
            assert self.state.media_player_entity is not None
            urls = []
            if msg.preannounce_media_id:
                urls.append(msg.preannounce_media_id)
            urls.append(msg.media_id)

            self.state.stop_word.is_active = True
            self._continue_conversation = msg.start_conversation
            self.duck()
            yield from self.state.media_player_entity.play(
                urls, announcement=True, done_callback=self._tts_finished
            )
        elif isinstance(msg, VoiceAssistantTimerEventResponse):
            self.handle_timer_event(VoiceAssistantTimerEventType(msg.event_type), msg)
        elif isinstance(msg, DeviceInfoRequest):
            yield DeviceInfoResponse(
                uses_password=False,
                name=self.state.name,
                mac_address=self.state.mac_address,
                voice_assistant_feature_flags=(
                    VoiceAssistantFeature.VOICE_ASSISTANT
                    | VoiceAssistantFeature.API_AUDIO
                    | VoiceAssistantFeature.ANNOUNCE
                    | VoiceAssistantFeature.START_CONVERSATION
                    | VoiceAssistantFeature.TIMERS
                ),
            )
        elif isinstance(
            msg,
            (
                ListEntitiesRequest,
                SubscribeHomeAssistantStatesRequest,
                MediaPlayerCommandRequest,
            ),
        ):
            for entity in self.state.entities:
                yield from entity.handle_message(msg)

            if isinstance(msg, ListEntitiesRequest):
                yield ListEntitiesDoneResponse()
        elif isinstance(msg, VoiceAssistantConfigurationRequest):
            yield VoiceAssistantConfigurationResponse(
                available_wake_words=[
                    VoiceAssistantWakeWord(
                        id=ww.id,
                        wake_word=ww.wake_word,
                        trained_languages=ww.trained_languages,
                    )
                    for ww in self.state.available_wake_words.values()
                ],
                active_wake_words=[
                    ww.id
                    for ww in self.state.wake_words.values()
                    if ww.id in self.state.active_wake_words
                ],
                max_active_wake_words=2,
            )
            _LOGGER.info("Connected to Home Assistant")
            self.state.event_bus.publish("ha_connected", {})
        elif isinstance(msg, VoiceAssistantSetConfiguration):
            active_wake_words: Set[str] = set()
            for wake_word_id in msg.active_wake_words:
                if wake_word_id in self.state.wake_words:
                    active_wake_words.add(wake_word_id)
                    continue
                model_info = self.state.available_wake_words.get(wake_word_id)
                if not model_info:
                    continue

                _LOGGER.debug("Loading wake word: %s", model_info.wake_word_path)
                self.state.wake_words[wake_word_id] = model_info.load(
                    self.state.libtensorflowlite_c_path
                )

                _LOGGER.info("Wake word set: %s", wake_word_id)
                active_wake_words.add(wake_word_id)
                break

            # Update is_active flag on all wake words
            for wake_word in self.state.wake_words.values():
                wake_word.is_active = wake_word.id in active_wake_words

            self.state.active_wake_words = active_wake_words
            _LOGGER.debug("Active wake words: %s", active_wake_words)
            self.state.preferences.active_wake_words = list(active_wake_words)
            self.state.save_preferences()
            self.state.wake_words_changed = True

    def handle_audio(self, audio_chunk: bytes) -> None:
        """Handle audio streaming to Home Assistant."""
        if not self._is_streaming_audio:
            return
        self.send_messages([VoiceAssistantAudio(data=audio_chunk)])

    def wakeup(self, wake_word: Union["MicroWakeWord", "OpenWakeWord", object]) -> None:
        """Handle wake word detection."""
        self.state.event_bus.publish("voice_wakeword", {})
        
        if self._timer_finished:
            self._timer_finished = False
            self.state.tts_player.stop()
            _LOGGER.debug("Stopping timer finished sound")
            return
        
        wake_word_phrase = getattr(wake_word, "wake_word", "unknown")
        _LOGGER.debug("Detected wake word: %s", wake_word_phrase)
        self.send_messages(
            [VoiceAssistantRequest(start=True, wake_word_phrase=wake_word_phrase)]
        )
        self.duck()
        self._is_streaming_audio = True
        self.state.tts_player.play(self.state.wakeup_sound)

    def stop(self) -> None:
        """Stop current activity."""
        self.state.stop_word.is_active = False
        self.state.tts_player.stop()
        if self._timer_finished:
            self._timer_finished = False
            _LOGGER.debug("Stopping timer finished sound")
        else:
            _LOGGER.debug("TTS response stopped manually")
            self._tts_finished()

    def play_tts(self) -> None:
        """Play TTS response."""
        if (not self._tts_url) or self._tts_played:
            return

        if not self._is_speaking:
            self.state.event_bus.publish("voice_tts_start", {})

        self._is_speaking = True
        self._tts_played = True
        _LOGGER.debug("Playing TTS response: %s", self._tts_url)
        self.state.stop_word.is_active = True
        self.state.tts_player.play(self._tts_url, done_callback=self._tts_finished)

    def duck(self) -> None:
        """Duck music volume."""
        _LOGGER.debug("Ducking music")
        self.state.music_player.duck()

    def unduck(self) -> None:
        """Restore music volume."""
        _LOGGER.debug("Unducking music")
        self.state.music_player.unduck()

    def _determine_final_state(self) -> None:
        """Determine final state after run completion."""
        self._is_streaming_audio = False
        self.state.stop_word.is_active = False

        if self._continue_conversation:
            self.send_messages([VoiceAssistantRequest(start=True)])
            self._is_streaming_audio = True
            _LOGGER.debug("Continuing conversation")
            self.state.event_bus.publish("voice_listen", {})
        else:
            self.unduck()
            self.state.event_bus.publish("voice_run_end", {})
            self.state.event_bus.publish("voice_idle", {})
        
        _LOGGER.debug("Final state determined")

    def _tts_finished(self) -> None:
        """Handle TTS playback completion."""
        self._is_speaking = False
        self.send_messages([VoiceAssistantAnnounceFinished()])
        _LOGGER.debug("TTS audio playback finished")

        if self._run_finished:
            self._determine_final_state()

    def _play_timer_finished(self) -> None:
        """Play timer finished sound."""
        if not self._timer_finished:
            self.unduck()
            return
        self.state.tts_player.play(
            self.state.timer_finished_sound,
            done_callback=lambda: call_all(
                lambda: time.sleep(1.0), self._play_timer_finished
            ),
        )

    def connection_lost(self, exc):
        """Handle connection loss."""
        super().connection_lost(exc)
        _LOGGER.info("Disconnected from Home Assistant")
