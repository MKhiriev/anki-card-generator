import re
from pathlib import Path
from typing import Dict, Any

from models.article import Article


def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9а-яё\-]+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "article"


def parse_ymlmd(path: str) -> Article:
    raw = Path(path).read_text(encoding="utf-8")

    m = re.match(r"(?s)^\s*---\s*\n(.*?)\n---\s*\n(.*)$", raw)
    if not m:
        raise ValueError("Input must be ymlmd: frontmatter between --- ... --- then body text.")

    fm = m.group(1)
    body = m.group(2).strip()

    meta: Dict[str, Any] = {}
    for line in fm.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()

        if k == "tags":
            if v.startswith("[") and v.endswith("]"):
                inner = v[1:-1].strip()
                if not inner:
                    meta[k] = []
                else:
                    parts = [p.strip().strip('"').strip("'") for p in inner.split(",")]
                    meta[k] = [p for p in parts if p]
            else:
                meta[k] = [v.strip('"').strip("'")] if v else []
        else:
            meta[k] = v.strip('"').strip("'")

    title = str(meta.get("title", "")).strip()
    if not title:
        raise ValueError("Frontmatter must include: title")

    source_url = str(meta.get("source_url", "")).strip()
    deck = str(meta.get("deck", "")).strip()  # may be empty -> fill later from config

    tags = meta.get("tags", [])
    if not isinstance(tags, list):
        tags = []

    slug = slugify(title)

    tags = list(tags) + [f"article:{slug}"]
    if source_url:
        try:
            domain = re.sub(r"^https?://", "", source_url).split("/")[0]
            if domain:
                tags.append(f"src:{domain}")
        except Exception:
            pass

    return Article(
        title=title,
        source_url=source_url,
        deck=deck,
        tags=tags,
        text=body,
        slug=slug,
    )
