"""GPT Image 2.5 Flare/Sunburst through ChatGPT/Codex OAuth."""

from __future__ import annotations

import base64
import importlib
import threading
from typing import Any, Dict, List, Optional

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    resolve_aspect_ratio,
    save_b64_image,
    success_response,
)
from plugins.image_gen._common import (
    StaticImageGenProvider,
    error_factory,
    prompt_required_error,
    resolve_static_model,
    size_for,
)

_base = importlib.import_module("plugins.image_gen.openai-codex")
_model_lock = threading.Lock()

MODELS: Dict[str, Dict[str, Any]] = {
    model if quality == "auto" else f"{model}-{quality}": {
        "display": f"GPT Image 2.5 {name} ({quality.title()})",
        "speed": speed,
        "strengths": strengths,
        "api_model": model,
        "quality": quality,
    }
    for model, name, speed, strengths in (
        ("gpt-image-2.5-flare", "Flare", "Fast", "Everyday image generation and editing"),
        ("gpt-image-2.5-sunburst", "Sunburst", "Slower", "Precision generation and editing"),
    )
    for quality in ("auto", "low", "medium", "high", "xhigh", "max")
}
DEFAULT_MODEL = "gpt-image-2.5-flare-medium"


class OpenAICodex25ImageGenProvider(StaticImageGenProvider):
    provider_id = "openai-codex-25"
    label = "OpenAI GPT Image 2.5 (Codex auth)"
    models = MODELS
    default_model_id = DEFAULT_MODEL
    price = "varies"

    def is_available(self) -> bool:
        return bool(_base._read_codex_access_token()) and _base._httpx_available()

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "OpenAI GPT Image 2.5 (Codex auth)",
            "badge": "subscription",
            "tag": "Flare/Sunburst via existing ChatGPT/Codex OAuth; no API key required",
            "env_vars": [],
        }

    def capabilities(self) -> Dict[str, Any]:
        return {"modalities": ["text", "image"], "max_reference_images": 16}

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        *,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        prompt = (prompt or "").strip()
        aspect = resolve_aspect_ratio(aspect_ratio)
        if not prompt:
            return prompt_required_error(self.provider_id, aspect)

        token = _base._read_codex_access_token()
        if not token:
            return error_factory(self.provider_id, aspect)(
                "No Codex/ChatGPT OAuth credentials available.", "auth_required"
            )
        if not _base._httpx_available():
            return error_factory(self.provider_id, aspect)(
                "httpx Python package not installed.", "missing_dependency"
            )

        tier_id, meta = resolve_static_model(
            MODELS,
            DEFAULT_MODEL,
            env_var="OPENAI_IMAGE_MODEL",
            config_key="openai-codex-25",
        )
        size = size_for(aspect)
        fail = error_factory(self.provider_id, aspect, model=tier_id, prompt=prompt)

        try:
            input_images = _base._normalize_input_images(image_url, reference_image_urls)
        except Exception as exc:
            return fail(f"Invalid image input: {exc}", "invalid_image_input")

        try:
            collected = None
            # The bundled Codex transport stores the hosted image model in a
            # module global. Lock across the request so different model picks
            # cannot race in concurrent generations.
            with _model_lock:
                previous_model = _base.API_MODEL
                _base.API_MODEL = meta["api_model"]
                try:
                    for _ in range(2):
                        collected = _base._collect_image_b64(
                            token,
                            prompt=prompt,
                            size=size,
                            quality=meta["quality"],
                            input_images=input_images or None,
                        )
                        if collected and collected.get("source") == "final" and collected.get("b64"):
                            break
                finally:
                    _base.API_MODEL = previous_model
        except Exception as exc:
            return fail(f"GPT Image 2.5 via Codex auth failed: {exc}", "api_error")

        if not collected or collected.get("source") != "final" or not collected.get("b64"):
            return fail("No final image was returned after two attempts.", "incomplete_image")

        try:
            raw = base64.b64decode(collected["b64"])
            pixel_size = _base._png_pixel_size(raw)
            saved_path = save_b64_image(collected["b64"], prefix=f"openai_codex25_{tier_id}")
        except Exception as exc:
            return fail(f"Could not save image: {exc}", "io_error")

        return success_response(
            image=str(saved_path),
            model=tier_id,
            prompt=prompt,
            aspect_ratio=aspect,
            provider=self.provider_id,
            modality="image" if input_images else "text",
            extra={
                "api_model": meta["api_model"],
                "size": size,
                "quality": meta["quality"],
                "input_image_count": len(input_images),
                "pixel_size": pixel_size,
            },
        )


def register(ctx) -> None:
    ctx.register_image_gen_provider(OpenAICodex25ImageGenProvider())
