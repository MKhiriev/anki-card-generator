import json
import sys
from pathlib import Path
from typing import Optional

from models.configs import GeneratorConfig


def load_generator_config(config_path: Optional[Path]) -> GeneratorConfig:
    cfg = GeneratorConfig()

    if config_path is None:
        return cfg

    try:
        raw = config_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Config JSON must be an object")
    except Exception as e:
        print(f"Error: invalid generator config JSON '{config_path}': {e}", file=sys.stderr)
        sys.exit(1)

    def get_str(key: str, default: str) -> str:
        v = data.get(key, default)
        return str(v).strip() if v is not None else default

    def get_int(key: str, default: int) -> int:
        v = data.get(key, default)
        try:
            return int(v)
        except Exception:
            return default

    def get_float(key: str, default: float) -> float:
        v = data.get(key, default)
        try:
            return float(v)
        except Exception:
            return default

    cfg.model = get_str("model", cfg.model)
    cfg.ollama_url = get_str("ollama_url", cfg.ollama_url)
    cfg.temperature = get_float("temperature", cfg.temperature)
    cfg.max_chars = get_int("max_chars", cfg.max_chars)
    cfg.overlap = get_int("overlap", cfg.overlap)

    if cfg.max_chars < 200:
        cfg.max_chars = 200
    if cfg.overlap < 0:
        cfg.overlap = 0
    if cfg.temperature < 0:
        cfg.temperature = 0.0

    return cfg
