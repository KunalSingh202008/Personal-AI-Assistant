"""
Nexus AI — Multimodal Vision & Image Understanding Agent
Inspects image metadata, prepares multimodal payloads, and coordinates
with Ollama vision models (e.g. Qwen2.5-VL, LLaVA, Moondream) with
graceful fallbacks and image attribute extraction.
"""

import base64
import logging
from pathlib import Path
import struct
from typing import Any
import httpx

from database import get_setting

logger = logging.getLogger("nexus.vision")

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
KNOWN_VISION_MODELS = [
    "qwen2.5-vl",
    "llava",
    "llava-llama3",
    "llava-phi3",
    "bakllava",
    "moondream",
    "minicpm-v",
]


def inspect_image_header(image_bytes: bytes) -> dict[str, Any]:
    """
    Pure Python image metadata parser using binary headers (PNG, JPEG, GIF, BMP, WEBP).
    Requires zero external dependencies.
    """
    size = len(image_bytes)
    if size < 16:
        return {"format": "unknown", "width": 0, "height": 0, "size_bytes": size}

    # 1. PNG
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n") and len(image_bytes) >= 24:
        w, h = struct.unpack(">II", image_bytes[16:24])
        return {"format": "PNG", "width": w, "height": h, "size_bytes": size, "mime_type": "image/png"}

    # 2. GIF
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        w, h = struct.unpack("<HH", image_bytes[6:10])
        return {"format": "GIF", "width": w, "height": h, "size_bytes": size, "mime_type": "image/gif"}

    # 3. BMP
    if image_bytes.startswith(b"BM") and len(image_bytes) >= 26:
        w, h = struct.unpack("<ii", image_bytes[18:26])
        return {"format": "BMP", "width": abs(w), "height": abs(h), "size_bytes": size, "mime_type": "image/bmp"}

    # 4. WEBP
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP" and len(image_bytes) >= 30:
        vp8 = image_bytes[12:16]
        if vp8 == b"VP8 " and len(image_bytes) >= 30:
            w, h = struct.unpack("<HH", image_bytes[26:30])
            return {"format": "WEBP", "width": w & 0x3FFF, "height": h & 0x3FFF, "size_bytes": size, "mime_type": "image/webp"}
        elif vp8 == b"VP8L" and len(image_bytes) >= 25:
            b1, b2, b3, b4 = image_bytes[21:25]
            w = 1 + (((b2 & 0x3F) << 8) | b1)
            h = 1 + (((b4 & 0xF) << 10) | (b3 << 2) | ((b2 & 0xC0) >> 6))
            return {"format": "WEBP", "width": w, "height": h, "size_bytes": size, "mime_type": "image/webp"}
        return {"format": "WEBP", "width": 0, "height": 0, "size_bytes": size, "mime_type": "image/webp"}

    # 5. JPEG
    if image_bytes.startswith(b"\xff\xd8"):
        offset = 2
        while offset < len(image_bytes) - 9:
            marker, length = struct.unpack(">HH", image_bytes[offset:offset + 4])
            offset += 2
            if marker in (0xFFC0, 0xFFC1, 0xFFC2):  # SOF0, SOF1, SOF2
                h, w = struct.unpack(">HH", image_bytes[offset + 1:offset + 5])
                return {"format": "JPEG", "width": w, "height": h, "size_bytes": size, "mime_type": "image/jpeg"}
            offset += length
        return {"format": "JPEG", "width": 0, "height": 0, "size_bytes": size, "mime_type": "image/jpeg"}

    return {"format": "UNKNOWN", "width": 0, "height": 0, "size_bytes": size, "mime_type": "application/octet-stream"}


class VisionAgent:
    def __init__(self, ollama_url: str = OLLAMA_BASE_URL):
        self.ollama_url = ollama_url

    async def detect_available_vision_models(self) -> list[str]:
        """Detect which vision-capable models are currently available in Ollama."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.ollama_url}/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    installed = [m.get("name", "") for m in models]
                    # Check matching vision models
                    vision_available = []
                    for model_name in installed:
                        lower_name = model_name.lower()
                        if any(vm in lower_name for vm in KNOWN_VISION_MODELS):
                            vision_available.append(model_name)
                    return vision_available
        except Exception as exc:
            logger.warning(f"Could not query Ollama for vision models: {exc}")
        return []

    async def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str = "Describe what you see in this image in detail.",
        model_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Analyze an image using a local vision model via Ollama.
        If no vision model is available, returns metadata and setup guidance.
        """
        meta = inspect_image_header(image_bytes)
        b64_img = base64.b64encode(image_bytes).decode("utf-8")

        # Find best model
        available_vision = await self.detect_available_vision_models()

        target_model = model_name
        if not target_model:
            if available_vision:
                target_model = available_vision[0]
            else:
                target_model = get_setting("model_name") or "qwen2.5-coder:7b"

        has_vision = any(vm in target_model.lower() for vm in KNOWN_VISION_MODELS)

        if not has_vision and not available_vision:
            # Honest, actionable response when no vision model is installed
            return {
                "success": False,
                "metadata": meta,
                "model_used": target_model,
                "error": "No vision model currently installed in Ollama.",
                "analysis": (
                    f"**Image Metadata Analyzed:**\n"
                    f"- Format: `{meta['format']}`\n"
                    f"- Resolution: `{meta['width']}x{meta['height']} px`\n"
                    f"- File size: `{meta['size_bytes']:,} bytes`\n\n"
                    f"The currently loaded model (`{target_model}`) is a text/code LLM. "
                    f"To enable full multimodal image understanding (reading screenshots, analyzing diagrams, UI inspection), "
                    f"run in your terminal:\n\n"
                    f"```bash\nollama pull llava\n# or\nollama pull qwen2.5-vl\n```\n"
                    f"Once pulled, Nexus AI will automatically detect and route visual queries to it."
                ),
            }

        # Send request to Ollama
        chosen_model = target_model if has_vision else available_vision[0]

        payload = {
            "model": chosen_model,
            "prompt": prompt,
            "images": [b64_img],
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(f"{self.ollama_url}/api/generate", json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "success": True,
                        "metadata": meta,
                        "model_used": chosen_model,
                        "prompt": prompt,
                        "analysis": data.get("response", ""),
                    }
                else:
                    return {
                        "success": False,
                        "metadata": meta,
                        "model_used": chosen_model,
                        "error": f"Ollama vision request failed with HTTP {resp.status_code}: {resp.text}",
                    }
        except Exception as exc:
            logger.error(f"Failed to communicate with vision model: {exc}")
            return {
                "success": False,
                "metadata": meta,
                "model_used": chosen_model,
                "error": f"Vision inference error: {str(exc)}",
            }
