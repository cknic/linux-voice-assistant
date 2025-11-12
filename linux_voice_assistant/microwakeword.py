"""Wrapper around pymicro-wakeword library."""
from pymicro_wakeword import MicroWakeWord
from .base_detector import BaseDetector
from pathlib import Path
import logging

_LOGGER = logging.getLogger(__name__)


class MicroWakeWordFeatures:
    """Features extracted for micro wake word detection."""
    
    def __init__(self):
        self.features = []


class MicroWakeWordDetector(BaseDetector):
    """Detector using MicroWakeWord."""
    
    def __init__(
        self,
        model_id: str,
        model_path: Path,
        threshold: float = 0.5,
        libtensorflowlite_c_path: Path | None = None,
    ):
        super().__init__(model_id, threshold)
        self.model = MicroWakeWord.from_file(
            str(model_path),
            str(libtensorflowlite_c_path) if libtensorflowlite_c_path else None
        )
        
    def process_audio(self, audio_chunk: bytes) -> float | None:
        """Process audio and return detection score."""
        return self.model.process_audio(audio_chunk)
        
    def reset(self):
        """Reset the detector state."""
        if hasattr(self.model, 'reset'):
            self.model.reset()
