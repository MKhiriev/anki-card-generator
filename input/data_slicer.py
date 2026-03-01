# SPDX-License-Identifier: BSD-4-Clause
# Copyright (c) 2026 Rasul Khiriev

import re
from typing import List


def chunk_paragraphs(text: str, max_chars: int = 2200, overlap_paras: int = 1) -> List[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        return []

    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0

    def flush():
        nonlocal cur, cur_len
        if cur:
            chunks.append("\n\n".join(cur).strip())
        cur = []
        cur_len = 0

    for p in paras:
        add_len = len(p) + (2 if cur else 0)
        if cur and (cur_len + add_len > max_chars):
            flush()
            if overlap_paras > 0 and chunks:
                prev_paras = chunks[-1].split("\n\n")
                overlap = prev_paras[-overlap_paras:]
                cur = overlap[:]
                cur_len = sum(len(x) for x in cur) + 2 * (len(cur) - 1)

        cur.append(p)
        cur_len += add_len

    flush()
    return chunks
