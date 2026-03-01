# SPDX-License-Identifier: BSD-4-Clause
# Copyright (c) 2026 Rasul Khiriev

import json
import re
from typing import List, Dict, Any


def parse_json_array_strict(s: str) -> List[Dict[str, Any]]:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    obj = json.loads(s)
    if not isinstance(obj, list):
        raise ValueError("LLM output JSON must be an array.")
    out: List[Dict[str, Any]] = []
    for x in obj:
        if isinstance(x, dict):
            out.append(x)
    return out
