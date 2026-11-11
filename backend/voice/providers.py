import os
import sys
import subprocess
import tempfile
from typing import Dict, Any, Optional

class BaseSTTProvider:
    """Abstract interface for Speech-to-Text inference."""
    def transcribe(self, audio_data: bytes, filename: str = "audio.wav") -> Dict[str, Any]:
        raise NotImplementedError

class BrowserSTTProvider(BaseSTTProvider):
    """Zero-overhead Web Speech API client-driven transcription provider."""
    def transcribe(self, audio_data: bytes, filename: str = "audio.wav") -> Dict[str, Any]:
        return {
            "provider": "browser_web_speech",
            "transcription": "",
            "note": "Transcription handled client-side via Web Speech API with 0ms latency."
        }

class LocalWhisperSTTProvider(BaseSTTProvider):
    """Local offline speech recognition adapter via Faster-Whisper or Whisper.cpp."""
    def __init__(self, model_size: str = "base"):
        self.model_size = model_size
        self._is_available = self._check_availability()

    def _check_availability(self) -> bool:
        try:
            import importlib.util
            return importlib.util.find_spec("faster_whisper") is not None or importlib.util.find_spec("whisper") is not None
        except Exception:
            return False

    def is_available(self) -> bool:
        return self._is_available

    def transcribe(self, audio_data: bytes, filename: str = "audio.wav") -> Dict[str, Any]:
        if not self._is_available:
            return {
                "success": False,
                "error": "faster-whisper is not installed. To enable local STT, install: pip install faster-whisper",
                "fallback_provider": "browser_web_speech"
            }
        
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_data)
                tmp_path = tmp.name

            try:
                from faster_whisper import WhisperModel
                model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
                segments, info = model.transcribe(tmp_path, beam_size=5)
                full_text = " ".join([seg.text for seg in segments]).strip()
                return {
                    "success": True,
                    "provider": "faster_whisper",
                    "text": full_text,
                    "language": info.language,
                    "duration": info.duration
                }
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        except Exception as e:
            return {"success": False, "error": str(e), "fallback_provider": "browser_web_speech"}

class BaseTTSProvider:
    """Abstract interface for Text-to-Speech synthesis."""
    def synthesize(self, text: str, voice_name: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError

class WindowsSapiTTSProvider(BaseTTSProvider):
    """Native Windows SAPI Text-to-Speech provider with zero external dependencies."""
    def __init__(self):
        self._installed_voices = self._get_installed_voices()

    def _get_installed_voices(self) -> list:
        try:
            script = "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices().VoiceInfo.Name"
            res = subprocess.run(["powershell", "-Command", script], capture_output=True, text=True, timeout=3.0)
            if res.returncode == 0:
                return [v.strip() for v in res.stdout.strip().split("\n") if v.strip()]
        except Exception:
            pass
        return ["Microsoft David Desktop", "Microsoft Zira Desktop"]

    def synthesize(self, text: str, voice_name: Optional[str] = None) -> Dict[str, Any]:
        clean_text = text.replace('"', '`"').replace("'", "''")
        voice_clause = f"$synth.SelectVoice('{voice_name}');" if voice_name else ""
        script = f"""
        Add-Type -AssemblyName System.Speech;
        $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer;
        {voice_clause}
        $synth.Speak('{clean_text}');
        """
        try:
            subprocess.run(["powershell", "-Command", script], capture_output=True, text=True, timeout=10.0)
            return {"status": "success", "provider": "windows_sapi", "spoken": text}
        except Exception as e:
            return {"status": "error", "message": str(e)}

class SpeechManager:
    """Unified voice engine manager coordinating STT and TTS providers."""
    def __init__(self):
        self.browser_stt = BrowserSTTProvider()
        self.local_whisper = LocalWhisperSTTProvider()
        self.windows_tts = WindowsSapiTTSProvider()

    def get_hardware_status(self) -> Dict[str, Any]:
        return {
            "browser_web_speech": True,
            "local_whisper_available": self.local_whisper.is_available(),
            "windows_sapi_available": sys.platform == "win32",
            "installed_sapi_voices": self.windows_tts._installed_voices,
            "recommended_mode": "browser_continuous"
        }
