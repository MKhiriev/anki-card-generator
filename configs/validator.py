import sys
from pathlib import Path
from typing import Optional


def validate_optional_config_file(path_str: str) -> Optional[Path]:
    if not path_str:
        return None
    p = Path(path_str).expanduser()
    if not p.exists():
        print(f"Error: config file does not exist: {p}", file=sys.stderr)
        sys.exit(1)
    if not p.is_file():
        print(f"Error: config path is not a file: {p}", file=sys.stderr)
        sys.exit(1)
    try:
        with p.open("r", encoding="utf-8") as _:
            pass
    except Exception as e:
        print(f"Error: cannot read config file '{p}': {e}", file=sys.stderr)
        sys.exit(1)
    return p.resolve()
