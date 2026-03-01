from dataclasses import dataclass
from typing import List


@dataclass
class Article:
    title: str
    source_url: str
    deck: str
    tags: List[str]
    text: str
    slug: str
