#!/usr/bin/env python3
"""XVF3800-specific LED controller using xvf_host commands."""

import subprocess
import time
import logging
from pathlib import Path
from typing import Optional

from .event_bus import EventHandler, subscribe

_LOGGER = logging.getLogger(__name__)


class XVF3800LEDController(EventHandler):
    """LED controller for XVF3800 using xvf_host."""
    
    def __init__(self, state, xvf_host_path: Optional[Path] = None):
        super().__init__(state)
        self.xvf_host = xvf_host_path or Path("/home/chris/reSpeakerXVF_rpi/xvf_host")
        
        if not self.xvf_host.exists():
            _LOGGER.error("xvf_host not found at %s", self.xvf_host)
            raise FileNotFoundError(f"xvf_host not found: {self.xvf_host}")
        
        _LOGGER.info("XVF3800 LED controller initialized with xvf_host: %s", self.xvf_host)
        self.setup_off()
    
    def xvf_cmd(self, cmd: str, *args):
        """Execute xvf_host command."""
        try:
            result = subprocess.run(
                ["sudo", str(self.xvf_host), cmd] + list(map(str, args)),
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                _LOGGER.debug("XVF command succeeded: %s %s", cmd, args)
                return True
            else:
                _LOGGER.error("XVF command failed: %s", result.stderr)
                return False
        except Exception as e:
            _LOGGER.error("XVF command error: %s", e)
            return False
    
    def setup_off(self):
        """Turn off LEDs."""
        self.xvf_cmd("LED_EFFECT", "0")
    
    def setup_wake_word(self):
        """Wake word detected animation."""
        _LOGGER.info("LED: Wake word animation")
        self.xvf_cmd("LED_EFFECT", "2")
        self.xvf_cmd("LED_SPEED", "8")
        self.xvf_cmd("LED_BRIGHTNESS", "255")
        time.sleep(0.7)
        self.setup_listening()
    
    def setup_listening(self):
        """Listening mode (DOA effect)."""
        _LOGGER.info("LED: Listening mode")
        self.xvf_cmd("LED_EFFECT", "4")
        self.xvf_cmd("LED_DOA_COLOR", "0xFFFF00", "0x0000FF")
        self.xvf_cmd("LED_BRIGHTNESS", "200")
    
    def setup_thinking(self):
        """Thinking/processing mode."""
        _LOGGER.info("LED: Thinking mode")
        self.xvf_cmd("LED_EFFECT", "1")
        self.xvf_cmd("LED_COLOR", "0x00FFFF")
        self.xvf_cmd("LED_SPEED", "5")
        self.xvf_cmd("LED_BRIGHTNESS", "180")
    
    def setup_speaking(self):
        """Speaking/TTS mode."""
        _LOGGER.info("LED: Speaking mode")
        self.xvf_cmd("LED_EFFECT", "1")
        self.xvf_cmd("LED_COLOR", "0xFF00FF")
        self.xvf_cmd("LED_SPEED", "7")
        self.xvf_cmd("LED_BRIGHTNESS", "200")
    
    def setup_error(self):
        """Error mode."""
        _LOGGER.info("LED: Error mode")
        self.xvf_cmd("LED_EFFECT", "3")
        self.xvf_cmd("LED_COLOR", "0xFF0000")
        for i in range(3):
            self.xvf_cmd("LED_BRIGHTNESS", "255")
            time.sleep(0.3)
            self.xvf_cmd("LED_BRIGHTNESS", "0")
            time.sleep(0.3)
        self.setup_off()
    
    def setup_success(self):
        """Success animation."""
        _LOGGER.info("LED: Success animation")
        self.xvf_cmd("LED_EFFECT", "3")
        self.xvf_cmd("LED_COLOR", "0x00FF00")
        self.xvf_cmd("LED_BRIGHTNESS", "255")
        time.sleep(0.2)
        self.xvf_cmd("LED_BRIGHTNESS", "50")
        time.sleep(0.1)
        self.xvf_cmd("LED_BRIGHTNESS", "255")
        time.sleep(0.2)
        self.setup_off()
    
    def setup_startup(self):
        """Startup animation."""
        _LOGGER.info("LED: Startup animation")
        self.setup_wake_word()
        time.sleep(1)
        self.setup_off()
    
    # Event handlers using the event bus
    @subscribe
    def ha_connected(self, data: dict):
        """Home Assistant connected."""
        _LOGGER.debug("Event: HA connected")
        self.setup_startup()
    
    @subscribe
    def voice_wakeword(self, data: dict):
        """Wake word detected."""
        _LOGGER.debug("Event: Wake word detected")
        self.setup_wake_word()
    
    @subscribe
    def voice_stt_start(self, data: dict):
        """STT started."""
        _LOGGER.debug("Event: STT start")
        self.setup_listening()
    
    @subscribe
    def voice_stt_end(self, data: dict):
        """STT ended."""
        _LOGGER.debug("Event: STT end")
        # Keep listening visual until intent starts
    
    @subscribe
    def voice_intent_start(self, data: dict):
        """Intent processing started."""
        _LOGGER.debug("Event: Intent start")
        self.setup_thinking()
    
    @subscribe
    def voice_tts_start(self, data: dict):
        """TTS started."""
        _LOGGER.debug("Event: TTS start")
        self.setup_speaking()
    
    @subscribe
    def voice_run_end(self, data: dict):
        """Voice run ended."""
        _LOGGER.debug("Event: Run end")
        self.setup_success()
    
    @subscribe
    def voice_idle(self, data: dict):
        """Back to idle."""
        _LOGGER.debug("Event: Idle")
        # Success animation already played in voice_run_end
        pass
    
    @subscribe
    def voice_error(self, data: dict):
        """Error occurred."""
        _LOGGER.debug("Event: Error")
        self.setup_error()
