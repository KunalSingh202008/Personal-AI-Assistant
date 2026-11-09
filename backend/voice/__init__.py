"""
KELA Voice & Speech Processing Engine
Provides intent routing, Hinglish/Hindi pattern matching, fast command execution,
and speech dispatching.
"""

from .router import dispatch_voice_command, is_wake_word_present, detect_language

__all__ = [
    "dispatch_voice_command",
    "is_wake_word_present",
    "detect_language",
]
