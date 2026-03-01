# SPDX-License-Identifier: BSD-4-Clause
# Copyright (c) 2026 Rasul Khiriev

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
