from pathlib import Path
from functools import lru_cache
from typing import Any, Union, Optional
import yaml

# Default to config.yaml located next to this script
DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.yaml")


@lru_cache(maxsize=1)
def _load_config(path: Union[str, Path] = DEFAULT_CONFIG_PATH) -> dict:
    """
    Load YAML config from the given path and cache the result.
    """
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def get_param(
    name: str,
    default: Optional[Any] = None,
    path: Union[str, Path] = DEFAULT_CONFIG_PATH,
) -> Any:
    """
    Get a parameter value from config.yaml.
    Supports nested keys using dot notation (e.g., "database.host").
    Returns `default` if the key is not found or the file is missing.
    """
    cfg = _load_config(path)
    current: Any = cfg

    for part in name.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default

    return current


def reload_config(path: Union[str, Path] = DEFAULT_CONFIG_PATH) -> None:
    """
    Clear cache and reload config for subsequent calls.
    """
    _load_config.cache_clear()
    _load_config(path)