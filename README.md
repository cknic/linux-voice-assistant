# Linux Voice Assistant

Experimental Linux voice assistant (LVA) for [Home Assistant][homeassistant] that uses the [ESPHome][esphome] protocol/API (via [aioesphomeapi](https://github.com/esphome/aioesphomeapi)).

Runs on Linux `aarch64` and `x86_64` platforms. Tested with Python 3.13 and Python 3.11.
Supports announcments, start/continue conversation, and timers.

See [the tutorial](docs/linux-voice-assistant-2mic-install.md) to build a satellite using a [Raspberry Pi Zero 2 W](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/) and a [ReSpeaker 2Mic HAT](https://wiki.keyestudio.com/Ks0314_keyestudio_ReSpeaker_2-Mic_Pi_HAT_V1.0). 

### What's working:
- This fork is from https://github.com/OHF-Voice/linux-voice-assistant Release v1.0.0 which introduces the ablity to use both MicroWakeWord and OpenWakeWord detections models.
- Updated to support LED Events including GPIO based LED controls. Defaults to the ReSpeaker 2Mic Hat SPI leds, but you can use the Grove port GPIO12/13 by adding run config statements.
- Updated to support running either APA102 or WS2812B LEDs from the SPI interface using a Micro Connectors 40-pin GPIO 1 to 2 Expansion Board. See the tutorial for instructions.
- Now supports **ALSA, PulseAudio and PipeWire** playback backends using the updated `linux_voice_assistant/mpv_player.py`.
- LVA will detect PipeWire, PulseAudio, and Alse audio backends and automatically use them in this order. You can override the by using the run configurations.
- You can choose between all MWW and OWW wake word within HA after the VLA is registered. Choosen wake words are saved to preferences.json in the linux-voice-assistant folder.
- The volume control is now persistant between connections and reboots. The volume setting gets stored in prefernces.json and loaded when LVA starts.

### Add Full MQTT Control for LEDs and Mute
- This branch introduces a comprehensive MQTT integration to bypass limitations in the pinned aioesphomeapi library and provide full remote control over the voice satellite's features and appearance.

- It uses MQTT Discovery to automatically create and configure a device and its associated entities within Home Assistant. This allows for real-time control from the HA interface and enables powerful automations.

#### Key Features:

- A switch entity to mute and unmute the microphone.

- A full suite of select and light entities to customize the effect, color, and brightness for each voice assistant state (Idle, Listening, Thinking, Responding, Error).

- A number entity to configure the number of LEDs in the strip, allowing for use with custom hardware.

- All settings are persistent, retained by the MQTT broker and re-applied whenever the application restarts.

  See [the tutorial](docs/linux-voice-assistant-2mic-install.md) to enable MQTT Controls.

## Installation

Install system dependencies (`apt-get`):

* `libportaudio2` (for `sounddevice`)
* `build-essential` (for `pymicro-features`)
* `libmpv-dev` (for `python-mpv`)
* `mpv` (for testing)
* `libmpv-dev` (for building spidev)
  
Clone and install project:

``` sh
git clone https://github.com/OHF-Voice/linux-voice-assistant.git
cd linux-voice-assistant
script/setup
```

## Running

Use `script/run` or `python3 -m linux_voice_assistant`

See `--help` for more options.

<<<<<<< HEAD
### Microphone

Use `--audio-input-device` to change the microphone device. Use `--list-input-devices` to see the available microphones. 

The microphone device **must** support 16Khz mono audio.

### Speaker

Use `--audio-output-device` to change the speaker device. Use `--list-output-devices` to see the available speakers.

## Wake Word

Change the default wake word with `--wake-model <id>` where `<id>` is the name of a model in the `wakewords` directory. For example, `--wake-model hey_jarvis` will load `wakewords/hey_jarvis.tflite` by default.

You can include more wakeword directories by adding `--wake-word-dir <DIR>` where `<DIR>` contains either [microWakeWord][] or [openWakeWord][] config files and `.tflite` models. For example, `--wake-word-dir wakewords/openWakeWord` will include the default wake words for openWakeWord.

If you want to add [other wakeword][wakewords-collection], make sure to create a small JSON config file to identify it as an openWakeWord model. For example, download the [GLaDOS][glados] model to `glados.tflite` and create `glados.json` with:

``` json
{
  "type": "openWakeWord",
  "wake_word": "GLaDOS",
  "model": "glados.tflite"
}
```

Add `--wake-word-dir <DIR>` with the directory containing `glados.tflite` and `glados.json` to your command-line.

=======
>>>>>>> imonlinux/main
## Connecting to Home Assistant

1. In Home Assistant, go to "Settings" -> "Device & services"
2. Click the "Add integration" button
3. Choose "ESPHome" and then "Set up another instance of ESPHome"
4. Enter the IP address of your voice satellite with port 6053
5. Click "Submit"

<<<<<<< HEAD
## Acoustic Echo Cancellation

Enable the echo cancel PulseAudio module:

``` sh
pactl load-module module-echo-cancel \
  aec_method=webrtc \
  aec_args="analog_gain_control=0 digital_gain_control=1 noise_suppression=1"
```

Verify that the `echo-cancel-source` and `echo-cancel-sink` devices are present:

``` sh
pactl list short sources
pactl list short sinks
```

Use the new devices:

``` sh
# The device names may be different on your system.
# Double check with --list-input-devices and --list-output-devices
python3 -m linux_voice_assistant ... \
     --audio-input-device 'Echo-Cancel Source' \
     --audio-output-device 'pipewire/echo-cancel-sink'
```

<!-- Links -->
[homeassistant]: https://www.home-assistant.io/
[esphome]: https://esphome.io/
[microWakeWord]: https://github.com/kahrendt/microWakeWord
[openWakeWord]: https://github.com/dscripka/openWakeWord
[wakewords-collection]: https://github.com/fwartner/home-assistant-wakewords-collection
[glados]: https://github.com/fwartner/home-assistant-wakewords-collection/blob/main/en/glados/glados.tflite
=======

## ToDo:

* Implement echo-cancellation filter in PipeWire. (Improves wake word detection when audio is being played)
* ~~Merge jianyu-li's PR from source project to add mute switch function in this branch~~
* ~~Implement MQTT entities to support advanced controls of the LVA.~~
* ~~Configure LVA to advertise on Zeroconf/mDNS via Avahi for HA to auto detect (in progress)~~ (Not needed as Release v1.0.0 implemented in code)
* Implement a single LVA systemd unit file that can be addapted using profiles and drop-ins (in progress)
* Implement OWW model validation checks and error handling so that a bad model doesn't crash OWW
* Make the selection of the right ALSA ar PA device more scripted
* ~~Make a Docker of the project~~ Already done in parent repo.
* ~~Add sensor entity that displays which wake word engine is being used for HA~~ (Not needed as you can use both at the same time)
* Could this be an DEB package?
* ~~Implement Stop for OWW~~ (Not needed, Stop with MWW works even when using OWW detection models)
* Stretch goal: create a smart installer full of validation and sanity checks
<!-- Links -->
[homeassistant]: https://www.home-assistant.io/
[esphome]: https://esphome.io/
[wyoming]: https://github.com/rhasspy/wyoming-openwakeword/
[future proof home]: https://github.com/FutureProofHomes/wyoming-enhancements/
>>>>>>> imonlinux/main
