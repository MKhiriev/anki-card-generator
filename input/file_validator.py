import sys
from pathlib import Path


def validate_input_file(path_str: str) -> Path:
    input_path = Path(path_str).expanduser()

    if not input_path.exists():
        print(f"Error: file does not exist: {input_path}", file=sys.stderr)
        sys.exit(1)

    if not input_path.is_file():
        print(f"Error: not a file: {input_path}", file=sys.stderr)
        sys.exit(1)

    if input_path.suffix.lower() not in (".ymlmd", ".md"):
        print(
            f"Error: invalid file extension '{input_path.suffix}'. Expected .ymlmd or .md",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        with input_path.open("r", encoding="utf-8") as _:
            pass
    except Exception as e:
        print(f"Error: cannot read file '{input_path}': {e}", file=sys.stderr)
        sys.exit(1)

    return input_path.resolve()
