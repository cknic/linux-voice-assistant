#!/usr/bin/env python3
"""Linux Voice Assistant main entry point."""

import argparse
import asyncio
import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from queue import Queue
from typing import Dict, List, Optional, Union

import numpy as np
import sounddevice as sd

from .event_bus import EventBus
from .models import AvailableWakeWord, Preferences, ServerState, WakeWordType
from .mpv_player import MpvMediaPlayer
from .satellite import VoiceSatelliteProtocol
from .util import get_mac, is_arm
from .zeroconf import HomeAssistantZeroconf

# Optional Porcupine support
try:
    import pvporcupine
    PORCUPINE_AVAILABLE = True
except ImportError:
    PORCUPINE_AVAILABLE = False

# Optional MQTT support
try:
    from .mqtt_controller import MQTTController
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

_LOGGER = logging.getLogger(__name__)
_MODULE_DIR = Path(__file__).parent
_REPO_DIR = _MODULE_DIR.parent
_WAKEWORDS_DIR = _REPO_DIR / "wakewords"
_OWW_DIR = _WAKEWORDS_DIR / "openWakeWord"
_SOUNDS_DIR = _REPO_DIR / "sounds"

if is_arm():
    _LIB_DIR = _REPO_DIR / "lib" / "linux_arm64"
else:
    _LIB_DIR = _REPO_DIR / "lib" / "linux_amd64"


def detect_xvf3800_device():
    """Detect XVF3800 audio device index."""
    devices = sd.query_devices()
    
    for idx, device in enumerate(devices):
        name = device['name'].lower()
        if 'xvf' in name or 'respeaker' in name or 'usb audio' in name:
            if device['max_input_channels'] > 0:
                _LOGGER.info("Detected audio device at index %d: %s", idx, device['name'])
                return idx
    
    _LOGGER.warning("Audio device not auto-detected, using default")
    return None


def set_audio_levels(device_id: int = 0):
    """Set audio levels using amixer."""
    _LOGGER.info("Setting audio levels for device %d", device_id)
    commands = [
        ["amixer", "-c", str(device_id), "set", "PCM", "100%", "unmute"],
        ["amixer", "-c", str(device_id), "set", "PCM1", "100%", "unmute"],
        ["amixer", "-c", str(device_id), "set", "Master", "100%", "unmute"],
    ]
    
    for cmd in commands:
        try:
            subprocess.run(cmd, capture_output=True, timeout=2)
        except Exception as e:
            _LOGGER.debug("Amixer command failed (may be normal): %s", e)


async def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="Satellite name")
    parser.add_argument(
        "--audio-input-device",
        type=int,
        default=None,
        help="sounddevice index for input device (auto-detect if not specified)",
    )
    parser.add_argument(
        "--audio-input-block-size", 
        type=int, 
        default=1024,
        help="Audio input block size"
    )
    parser.add_argument(
        "--audio-output-device", 
        help="mpv name for output device"
    )
    parser.add_argument(
        "--set-audio-levels",
        action="store_true",
        help="Set audio levels using amixer at startup"
    )
    parser.add_argument(
        "--wake-word-dir",
        default=[_WAKEWORDS_DIR],
        action="append",
        help="Directory with wake word models (.tflite) and configs (.json)",
    )
    parser.add_argument(
        "--wake-model", 
        default="okay_nabu", 
        help="Id of active wake model"
    )
    parser.add_argument(
        "--stop-model", 
        default="stop", 
        help="Id of stop model"
    )
    parser.add_argument(
        "--refractory-seconds",
        default=2.0,
        type=float,
        help="Seconds before wake word can be activated again",
    )
    
    # Porcupine options
    parser.add_argument(
        "--porcupine-key",
        help="Porcupine access key for wake word detection"
    )
    parser.add_argument(
        "--porcupine-model",
        help="Path to Porcupine .ppn model file"
    )
    parser.add_argument(
        "--porcupine-sensitivity",
        type=float,
        default=0.6,
        help="Porcupine sensitivity (0.0 to 1.0)"
    )
    
    # OpenWakeWord options
    parser.add_argument(
        "--oww-melspectrogram-model",
        default=_OWW_DIR / "melspectrogram.tflite",
        help="Path to openWakeWord melspectrogram model",
    )
    parser.add_argument(
        "--oww-embedding-model",
        default=_OWW_DIR / "embedding_model.tflite",
        help="Path to openWakeWord embedding model",
    )
    
    # Sound files
    parser.add_argument(
        "--wakeup-sound", 
        default=str(_SOUNDS_DIR / "awake.wav"),
        help="Sound to play when wake word is detected"
    )
    parser.add_argument(
        "--processing-sound",
        default=str(_SOUNDS_DIR / "processing.wav"),
        help="Sound to play during intent processing"
    )
    parser.add_argument(
        "--timer-finished-sound", 
        default=str(_SOUNDS_DIR / "timer_finished.flac"),
        help="Sound to play when timer finishes"
    )
    
    # XVF3800 LED options
    parser.add_argument(
        "--use-xvf-leds",
        action="store_true",
        help="Use XVF3800 LED controller instead of generic LED controller"
    )
    parser.add_argument(
        "--xvf-host-path",
        default="/home/chris/reSpeakerXVF_rpi/xvf_host",
        help="Path to xvf_host executable for XVF3800"
    )
    
    # Generic LED options
    parser.add_argument(
        "--led-type",
        choices=["dotstar", "neopixel"],
        help="Type of LED strip (dotstar or neopixel)"
    )
    parser.add_argument(
        "--led-interface",
        choices=["spi", "gpio"],
        default="spi",
        help="Interface for LED strip (spi or gpio)"
    )
    parser.add_argument(
        "--led-clock-pin",
        type=int,
        help="GPIO pin for LED clock (SPI mode)"
    )
    parser.add_argument(
        "--led-data-pin",
        type=int,
        help="GPIO pin for LED data"
    )
    parser.add_argument(
        "--num-leds",
        type=int,
        default=3,
        help="Number of LEDs in the strip"
    )
    
    # MQTT options
    parser.add_argument(
        "--mqtt-host",
        help="MQTT broker host"
    )
    parser.add_argument(
        "--mqtt-port",
        type=int,
        default=1883,
        help="MQTT broker port"
    )
    parser.add_argument(
        "--mqtt-username",
        help="MQTT username"
    )
    parser.add_argument(
        "--mqtt-password",
        help="MQTT password"
    )
    
    # Other options
    parser.add_argument(
        "--enable-thinking-sound",
        action="store_true",
        help="Enable thinking/processing sound"
    )
    parser.add_argument(
        "--preferences-file", 
        default=_REPO_DIR / "preferences.json",
        help="Path to preferences file"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Address for ESPHome server (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=6053, 
        help="Port for ESPHome server (default: 6053)"
    )
    parser.add_argument(
        "--debug", 
        action="store_true", 
        help="Print DEBUG messages to console"
    )
    
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    _LOGGER.debug(args)

    # Check Porcupine availability
    if args.porcupine_key and not PORCUPINE_AVAILABLE:
        _LOGGER.error("Porcupine key provided but pvporcupine not installed")
        _LOGGER.error("Install with: pip install pvporcupine")
        return

    # Auto-detect audio device if not specified
    if args.audio_input_device is None:
        detected = detect_xvf3800_device()
        if detected is not None:
            args.audio_input_device = detected
        else:
            args.audio_input_device = 0
    
    # Set audio levels if requested
    if args.set_audio_levels:
        set_audio_levels(args.audio_input_device)

    # Load available wake words
    wake_word_dirs = [Path(ww_dir) for ww_dir in args.wake_word_dir]
    available_wake_words: Dict[str, AvailableWakeWord] = {}

    for wake_word_dir in wake_word_dirs:
        for model_config_path in wake_word_dir.glob("**/*.json"):
            model_id = model_config_path.stem
            if model_id == args.stop_model:
                # Don't show stop model as an available wake word
                continue

            try:
                with open(model_config_path, "r", encoding="utf-8") as model_config_file:
                    model_config = json.load(model_config_file)
                    model_type = model_config["type"]
                    available_wake_words[model_id] = AvailableWakeWord(
                        id=model_id,
                        type=WakeWordType(model_type),
                        wake_word=model_config["wake_word"],
                        trained_languages=model_config.get("trained_languages", []),
                        wake_word_path=model_config_path,
                    )
            except Exception as e:
                _LOGGER.warning("Failed to load wake word %s: %s", model_config_path, e)

    _LOGGER.debug("Available wake words: %s", list(sorted(available_wake_words.keys())))

    # Load preferences
    preferences_path = Path(args.preferences_file)
    if preferences_path.exists():
        _LOGGER.debug("Loading preferences: %s", preferences_path)
        with open(preferences_path, "r", encoding="utf-8") as preferences_file:
            preferences_dict = json.load(preferences_file)
            preferences = Preferences(**preferences_dict)
    else:
        preferences = Preferences()

    # Update preferences from command line
    if args.enable_thinking_sound:
        preferences.thinking_sound = 1
    
    if args.num_leds:
        preferences.num_leds = args.num_leds

    libtensorflowlite_c_path = _LIB_DIR / "libtensorflowlite_c.so"
    _LOGGER.debug("libtensorflowlite_c path: %s", libtensorflowlite_c_path)

    # Load wake word models (but don't activate Porcupine yet if specified)
    wake_models: Dict[str, Union["MicroWakeWord", "OpenWakeWord"]] = {}
    
    # Only load MicroWakeWord/OpenWakeWord if not using Porcupine exclusively
    if not args.porcupine_key:
        if args.wake_model in available_wake_words:
            model_info = available_wake_words[args.wake_model]
            _LOGGER.debug("Loading wake model: %s", model_info.wake_word_path)
            wake_models[args.wake_model] = model_info.load(libtensorflowlite_c_path)

    # Load stop model
    from .microwakeword import MicroWakeWord
    
    stop_model: Optional[MicroWakeWord] = None
    for wake_word_dir in wake_word_dirs:
        stop_config_path = wake_word_dir / f"{args.stop_model}.json"
        if not stop_config_path.exists():
            continue

        _LOGGER.debug("Loading stop model: %s", stop_config_path)
        stop_model = MicroWakeWord.from_config(
            stop_config_path, libtensorflowlite_c_path
        )
        break

    if stop_model is None:
        _LOGGER.error("Stop model not found: %s", args.stop_model)
        return

    # Create event bus
    event_bus = EventBus()
    loop = asyncio.get_running_loop()

    # Create server state
    state = ServerState(
        name=args.name,
        mac_address=get_mac(),
        audio_queue=Queue(),
        entities=[],
        available_wake_words=available_wake_words,
        wake_words=wake_models,
        active_wake_words=set(wake_models.keys()),
        stop_word=stop_model,
        music_player=MpvMediaPlayer(device=args.audio_output_device),
        tts_player=MpvMediaPlayer(device=args.audio_output_device),
        wakeup_sound=args.wakeup_sound,
        processing_sound=args.processing_sound,
        timer_finished_sound=args.timer_finished_sound,
        preferences=preferences,
        preferences_path=preferences_path,
        libtensorflowlite_c_path=libtensorflowlite_c_path,
        event_bus=event_bus,
        loop=loop,
        oww_melspectrogram_path=Path(args.oww_melspectrogram_model),
        oww_embedding_path=Path(args.oww_embedding_model),
        refractory_seconds=args.refractory_seconds,
        thinking_sound_enabled=bool(preferences.thinking_sound),
    )

    # Initialize LED controller
    led_controller = None
    if args.use_xvf_leds:
        try:
            from .led_controller_xvf3800 import XVF3800LEDController
            led_controller = XVF3800LEDController(
                state=state,
                xvf_host_path=Path(args.xvf_host_path)
            )
            _LOGGER.info("Using XVF3800 LED controller")
        except (ImportError, FileNotFoundError) as e:
            _LOGGER.error("XVF3800 LED controller initialization failed: %s", e)
    elif args.led_type:
        try:
            from .led_controller import LedController
            led_controller = LedController(
                state=state,
                led_type=args.led_type,
                interface=args.led_interface,
                clock_pin=args.led_clock_pin,
                data_pin=args.led_data_pin,
                num_leds=preferences.num_leds,
            )
            _LOGGER.info("Using generic LED controller: %s", args.led_type)
        except ImportError as e:
            _LOGGER.error("Generic LED controller initialization failed: %s", e)

    # Initialize MQTT controller
    mqtt_controller = None
    if args.mqtt_host and MQTT_AVAILABLE:
        try:
            mqtt_controller = MQTTController(
                state=state,
                host=args.mqtt_host,
                port=args.mqtt_port,
                username=args.mqtt_username,
                password=args.mqtt_password,
            )
            _LOGGER.info("MQTT controller initialized: %s:%d", args.mqtt_host, args.mqtt_port)
        except Exception as e:
            _LOGGER.error("MQTT controller initialization failed: %s", e)

    # Start audio processing thread
    porcupine_handle = None
    if args.porcupine_key and args.porcupine_model:
        _LOGGER.info("Initializing Porcupine wake word with model: %s", args.porcupine_model)
        try:
            porcupine_handle = pvporcupine.create(
                access_key=args.porcupine_key,
                keyword_paths=[args.porcupine_model],
                sensitivities=[args.porcupine_sensitivity]
            )
            _LOGGER.info("Porcupine initialized successfully")
        except Exception as e:
            _LOGGER.error("Failed to initialize Porcupine: %s", e)
            return

    process_audio_thread = threading.Thread(
        target=process_audio, 
        args=(state, porcupine_handle), 
        daemon=True
    )
    process_audio_thread.start()

    def sd_callback(indata, _frames, _time, _status):
        """Sounddevice callback to queue audio."""
        state.audio_queue.put_nowait(bytes(indata))

    server = await loop.create_server(
        lambda: VoiceSatelliteProtocol(state), host=args.host, port=args.port
    )

    # Auto discovery (zeroconf, mDNS)
    discovery = HomeAssistantZeroconf(port=args.port, name=args.name)
    await discovery.register_server()

    try:
        _LOGGER.debug("Opening audio input device: %s", args.audio_input_device)
        with sd.RawInputStream(
            samplerate=16000,
            blocksize=args.audio_input_block_size,
            device=args.audio_input_device,
            dtype="int16",
            channels=1,
            callback=sd_callback,
        ):
            async with server:
                _LOGGER.info("Server started (host=%s, port=%s)", args.host, args.port)
                await server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.audio_queue.put_nowait(None)
        process_audio_thread.join()
        if porcupine_handle:
            porcupine_handle.delete()
        if led_controller:
            led_controller.setup_off()
        if mqtt_controller:
            mqtt_controller.disconnect()

    _LOGGER.debug("Server stopped")


def process_audio(state: ServerState, porcupine_handle=None):
    """Process audio chunks from the microphone."""
    from .microwakeword import MicroWakeWord, MicroWakeWordFeatures
    from .openwakeword import OpenWakeWord, OpenWakeWordFeatures
    
    wake_words: List[Union[MicroWakeWord, OpenWakeWord]] = []
    micro_features: Optional[MicroWakeWordFeatures] = None
    micro_inputs: List[np.ndarray] = []

    oww_features: Optional[OpenWakeWordFeatures] = None
    oww_inputs: List[np.ndarray] = []
    has_oww = False

    last_active: Optional[float] = None

    # Simple Porcupine wake word wrapper for compatibility
    class PorcupineWakeWord:
        def __init__(self):
            self.id = "porcupine"
            self.wake_word = "Alexa"

    try:
        while True:
            audio_chunk = state.audio_queue.get()
            if audio_chunk is None:
                break

            if state.satellite is None:
                continue

            try:
                state.satellite.handle_audio(audio_chunk)

                # Process with Porcupine if available
                if porcupine_handle:
                    pcm = np.frombuffer(audio_chunk, dtype=np.int16)
                    frame_length = porcupine_handle.frame_length
                    
                    if len(pcm) >= frame_length:
                        for i in range(0, len(pcm) - frame_length + 1, frame_length):
                            frame = pcm[i:i + frame_length]
                            result = porcupine_handle.process(frame)
                            if result >= 0:
                                now = time.monotonic()
                                if (last_active is None) or ((now - last_active) > state.refractory_seconds):
                                    _LOGGER.info("Porcupine wake word detected")
                                    state.satellite.wakeup(PorcupineWakeWord())
                                    last_active = now

                # Process with MicroWakeWord/OpenWakeWord if configured
                elif state.wake_words:
                    # Check if we need to reload wake words
                    if state.wake_words_changed:
                        state.wake_words_changed = False
                        wake_words.clear()
                        wake_words.extend(state.wake_words.values())
                        
                        # Reset features
                        has_oww = any(isinstance(ww, OpenWakeWord) for ww in wake_words)
                        if has_oww and oww_features is None:
                            oww_features = OpenWakeWordFeatures(
                                melspectrogram_path=state.oww_melspectrogram_path,
                                embedding_path=state.oww_embedding_path,
                                libtensorflowlite_c_path=state.libtensorflowlite_c_path,
                            )

                    if wake_words:
                        # Process MicroWakeWord
                        if micro_features is None:
                            micro_features = MicroWakeWordFeatures(
                                libtensorflowlite_c_path=state.libtensorflowlite_c_path,
                            )

                        micro_inputs.clear()
                        micro_inputs.extend(micro_features.process_streaming(audio_chunk))

                        for micro_input in micro_inputs:
                            for wake_word in wake_words:
                                if not isinstance(wake_word, MicroWakeWord):
                                    continue
                                if not wake_word.is_active:
                                    continue
                                if wake_word.process_streaming(micro_input):
                                    now = time.monotonic()
                                    if (last_active is None) or (
                                        (now - last_active) > state.refractory_seconds
                                    ):
                                        state.satellite.wakeup(wake_word)
                                        last_active = now

                        # Process OpenWakeWord
                        if has_oww and oww_features:
                            oww_inputs.clear()
                            oww_inputs.extend(oww_features.process_streaming(audio_chunk))

                            for oww_input in oww_inputs:
                                for wake_word in wake_words:
                                    if not isinstance(wake_word, OpenWakeWord):
                                        continue
                                    if not wake_word.is_active:
                                        continue
                                    if wake_word.process_streaming(oww_input):
                                        now = time.monotonic()
                                        if (last_active is None) or (
                                            (now - last_active) > state.refractory_seconds
                                        ):
                                            state.satellite.wakeup(wake_word)
                                            last_active = now

                # Always process stop word
                if micro_features is None:
                    micro_features = MicroWakeWordFeatures(
                        libtensorflowlite_c_path=state.libtensorflowlite_c_path,
                    )

                micro_inputs.clear()
                micro_inputs.extend(micro_features.process_streaming(audio_chunk))

                stopped = False
                for micro_input in micro_inputs:
                    if state.stop_word.process_streaming(micro_input):
                        stopped = True

                if stopped and state.stop_word.is_active:
                    state.satellite.stop()

            except Exception:
                _LOGGER.exception("Unexpected error handling audio")

    except Exception:
        _LOGGER.exception("Unexpected error processing audio")


if __name__ == "__main__":
    asyncio.run(main())
