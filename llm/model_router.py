"""Automatic model selection based on task content."""

import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_SIMPLE_KEYWORDS = re.compile(
    r"\b(質問|教えて|何\?|what is|how do|explain|describe|tell me)\b",
    re.IGNORECASE,
)
_IMAGE_KEYWORDS = re.compile(
    r"\b(image|screenshot|画像|スクリーンショット|photo|picture|図|図版)\b",
    re.IGNORECASE,
)


class ModelRouter:
    """Selects the most appropriate model for a given task.

    Reads ``config/models.yaml`` and applies routing rules to pick
    between the ``main``, ``fast``, and ``vision`` models.
    """

    def __init__(self, models_yaml_path: str | None = None) -> None:
        """Initialise the router.

        Args:
            models_yaml_path: Optional path to the models YAML file.
                Defaults to ``config/models.yaml`` relative to this file.
        """
        if models_yaml_path is None:
            models_yaml_path = str(
                Path(__file__).parent.parent / "config" / "models.yaml"
            )
        self._config = self._load_config(models_yaml_path)

    def select_model(self, task: str, has_images: bool = False) -> str:
        """Select the best model for the given task.

        Args:
            task: Natural language task description.
            has_images: Whether the task includes images.

        Returns:
            Model name string (e.g. ``qwen3.6:35b-a3b-q4_K_M``).
        """
        if has_images or _IMAGE_KEYWORDS.search(task):
            model_key = "vision"
        elif _SIMPLE_KEYWORDS.search(task):
            model_key = "fast"
        else:
            model_key = "main"

        model_name: str = self._config["models"][model_key]["name"]
        logger.debug("ModelRouter: task='%s...' → %s (%s)", task[:40], model_key, model_name)
        return model_name

    def _load_config(self, path: str) -> dict[str, object]:
        """Load and return the models YAML configuration.

        Args:
            path: Path to the YAML file.

        Returns:
            Parsed YAML dictionary.
        """
        try:
            with open(path, encoding="utf-8") as fh:
                return yaml.safe_load(fh)  # type: ignore[no-any-return]
        except FileNotFoundError:
            logger.warning("models.yaml not found at %s – using defaults", path)
            return {
                "models": {
                    "main": {"name": "qwen3.6:35b-a3b-q4_K_M"},
                    "fast": {"name": "qwen3.5:9b"},
                    "vision": {"name": "gemma4:26b"},
                }
            }
