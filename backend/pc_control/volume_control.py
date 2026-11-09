import ctypes
from typing import Dict, Any

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
KEYEVENTF_KEYUP = 0x0002

def _send_key(vk_code: int):
    """Send keydown and keyup for virtual key code in <0.1ms."""
    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)

def change_volume(direction: str, steps: int = 5) -> Dict[str, Any]:
    """
    Change volume up or down instantly using native Windows virtual key events.
    Each step is 2% volume.
    """
    vk = VK_VOLUME_UP if direction.lower() == "up" else VK_VOLUME_DOWN
    try:
        for _ in range(max(1, min(25, steps))):
            _send_key(vk)
        return {"status": "success", "message": f"Adjusted volume {direction} by {steps * 2}%"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to adjust volume: {str(e)}"}

def toggle_mute() -> Dict[str, Any]:
    """Toggle audio mute state instantly."""
    try:
        _send_key(VK_VOLUME_MUTE)
        return {"status": "success", "message": "Toggled mute status"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to toggle mute: {str(e)}"}

def set_volume(level: int) -> Dict[str, Any]:
    """
    Set volume to approximate target percentage (0-100).
    Zeroes volume down then steps up to target. Runs in <5ms.
    """
    target = max(0, min(100, int(level)))
    steps_up = target // 2
    try:
        # Zero out volume
        for _ in range(50):
            _send_key(VK_VOLUME_DOWN)
        # Step up to target
        for _ in range(steps_up):
            _send_key(VK_VOLUME_UP)
        return {"status": "success", "message": f"Set volume to approximately {target}%"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to set volume: {str(e)}"}
