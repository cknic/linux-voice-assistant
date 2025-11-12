"""Wrapper around pyopen-wakeword library."""
from pyopen_wakeword import Model as OpenWakeWordModel
from .base_detector import BaseDetector
from pathlib import Path
import logging
import numpy as np

_LOGGER = logging.getLogger(__name__)


class OpenWakeWordFeatures:
    """Features extracted for OpenWakeWord detection."""
    
    def __init__(self):
        self.features = []


class OpenWakeWord:
    """OpenWakeWord model wrapper."""
    
    def __init__(
        self,
        model_path: str,
        inference_framework: str = "tflite"
    ):
        self.model = OpenWakeWordModel(
            wakeword_models=[model_path],
            inference_framework=inference_framework
        )
        
    def predict(self, audio_data: np.ndarray) -> dict:
        """Make prediction on audio data."""
        return self.model.predict(audio_data)
        
    def reset(self):
        """Reset the model state."""
        if hasattr(self.model, 'reset'):
            self.model.reset()


class OpenWakeWordDetector(BaseDetector):
    """Detector using OpenWakeWord."""
    
    def __init__(
        self,
        model_id: str,
        model_path: Path,
        threshold: float = 0.5,
    ):
        super().__init__(model_id, threshold)
        self.model = OpenWakeWord(str(model_path))
        
    def process_audio(self, audio_chunk: bytes) -> float | None:
        """Process audio and return detection score."""
        # Convert bytes to numpy array
        audio_data = np.frombuffer(audio_chunk, dtype=np.int16)
        result = self.model.predict(audio_data)
        
        # Get the score for our model
        if self.model_id in result:
            return result[self.model_id]
        return None
        
    def reset(self):
        """Reset the detector state."""
        self.model.reset()
