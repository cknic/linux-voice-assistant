#!/bin/bash

cd ~/linux-voice-assistant
source .venv/bin/activate

# Set audio levels for XVF3800
echo "Setting audio levels..."
amixer -c 0 set PCM 100% unmute 2>/dev/null || true
amixer -c 0 set PCM1 100% unmute 2>/dev/null || true
amixer -c 0 set Master 100% unmute 2>/dev/null || true

# Cleanup function
cleanup() {
    echo "Shutting down..."
    pkill -f "linux_voice_assistant" 2>/dev/null || true
    # Turn off LEDs via xvf_host
    sudo /home/chris/reSpeakerXVF_rpi/xvf_host LED_EFFECT 0 2>/dev/null || true
    exit 0
}

trap cleanup EXIT INT TERM

# Start LVA with XVF3800 support
python -m linux_voice_assistant \
    --name "XVF Satellite" \
    --audio-input-device 0 \
    --audio-output-device 0 \
    --set-audio-levels \
    --use-xvf-leds \
    --xvf-host-path /home/chris/reSpeakerXVF_rpi/xvf_host \
    --porcupine-key 'mHg3CsdYc6KcRNTY37uAfXP9X7mP6MN8++UJl1Xj1OmOMnXgkXLMcg==' \
    --porcupine-model /home/chris/linux-voice-assistant/wakewords/alexa.ppn \
    --porcupine-sensitivity 0.6 \
    --wakeup-sound /home/chris/linux-voice-assistant/sounds/awake.wav \
    --processing-sound /home/chris/linux-voice-assistant/sounds/processing.wav \
    --timer-finished-sound /home/chris/linux-voice-assistant/sounds/done.wav \
    --enable-thinking-sound \
    --host 0.0.0.0 \
    --port 10700 \
    --debug
