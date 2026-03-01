import json

import requests

from models.article import Article


def ollama_chat(ollama_url: str, model: str, system: str, user: str, temperature: float = 0.2) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": temperature},
        "stream": False,
    }
    r = requests.post(f"{ollama_url}/api/chat", json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    return data["message"]["content"]


def build_user_prompt(article: Article, chunk_text: str, chunk_index: int) -> str:
    meta = {
        "title": article.title,
        "source_url": article.source_url,
        "article_slug": article.slug,
        "chunk": chunk_index,
        "base_tags": article.tags,
    }
    return (
            "Метаданные (JSON):\n"
            + json.dumps(meta, ensure_ascii=False)
            + "\n\n"
              "Текст фрагмента:\n"
            + chunk_text
            + "\n\n"
              "Сгенерируй карточки согласно правилам. Верни ТОЛЬКО JSON-массив."
    )


def repair_prompt(bad_output: str) -> str:
    return (
            "Твой предыдущий ответ НЕ является валидным JSON-массивом.\n"
            "Исправь его и верни ТОЛЬКО валидный JSON-массив (array) без текста и без Markdown.\n\n"
            "Плохой вывод:\n"
            + bad_output
    )
