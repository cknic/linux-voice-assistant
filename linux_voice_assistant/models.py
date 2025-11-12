"""Data models."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from queue import Queue
from typing import TYPE_CHECKING, Dict, List, Optional, Set

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop
    from .event_bus import EventBus
    from .microwakeword import MicroWakeWord
    from .mpv_player import MpvMediaPlayer
    from .openwakeword import OpenWakeWord


class WakeWordType(str, Enum):
    """Type of wake word model."""

    MICRO = "micro"
    OPENWAKEWORD = "openwakeword"


@dataclass
class AvailableWakeWord:
    """Information about an available wake word."""

    id: str
    type: WakeWordType
    wake_word: str
    trained_languages: List[str]
    wake_word_path: Path

    def load(self, libtensorflowlite_c_path: Path):
        """Load wake word model."""
        if self.type == WakeWordType.MICRO:
            from .microwakeword import MicroWakeWord

            return MicroWakeWord.from_config(
                self.wake_word_path, libtensorflowlite_c_path
            )

        if self.type == WakeWordType.OPENWAKEWORD:
            from .openwakeword import OpenWakeWord

            return OpenWakeWord.from_config(
                self.wake_word_path, libtensorflowlite_c_path
            )

        raise ValueError(f"Unsupported wake word type: {self.type}")


@dataclass
class Preferences:
    """User preferences."""

    active_wake_words: List[str] = field(default_factory=list)
    volume_level: float = 1.0
    thinking_sound: int = 0
    num_leds: int = 3


@dataclass
class ServerState:
    """Server state."""

    name: str
    mac_address: str
    audio_queue: "Queue[Optional[bytes]]"
    entities: list
    available_wake_words: Dict[str, AvailableWakeWord]
    wake_words: Dict[str, "MicroWakeWord | OpenWakeWord"]
    active_wake_words: Set[str] = field(default_factory=set)
    wake_words_changed: bool = False
    stop_word: Optional["MicroWakeWord"] = None
    music_player: Optional["MpvMediaPlayer"] = None
    tts_player: Optional["MpvMediaPlayer"] = None
    wakeup_sound: str = ""
    processing_sound: str = ""
    timer_finished_sound: str = ""
    preferences: Preferences = field(default_factory=Preferences)
    preferences_path: Optional[Path] = None
    satellite: Optional["VoiceSatelliteProtocol"] = None
    media_player_entity: Optional["MediaPlayerEntity"] = None
    thinking_sound_entity: Optional["ThinkingSoundEntity"] = None
    event_bus: Optional["EventBus"] = None
    loop: Optional["AbstractEventLoop"] = None
    libtensorflowlite_c_path: Optional[Path] = None
    oww_melspectrogram_path: Optional[Path] = None
    oww_embedding_path: Optional[Path] = None
    refractory_seconds: float = 2.0
    thinking_sound_enabled: bool = False

    def save_preferences(self) -> None:
        """Save preferences to disk."""
        import json

        if self.preferences_path is None:
            return

        with open(self.preferences_path, "w", encoding="utf-8") as prefs_file:
            json.dump(
                {
                    "active_wake_words": self.preferences.active_wake_words,
                    "volume_level": self.preferences.volume_level,
                    "thinking_sound": self.preferences.thinking_sound,
                    "num_leds": self.preferences.num_leds,
                },
                prefs_file,
            )
