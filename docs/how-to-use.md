# Anki Card Generator --- How To Use

## 1. Requirements

-   macOS / Linux
-   Python 3.10+
-   Ollama installed and running
-   Anki running with AnkiConnect enabled

Verify services:

``` bash
curl http://127.0.0.1:11434/api/tags
curl http://127.0.0.1:8765
```

Both must return JSON.

------------------------------------------------------------------------

## 2. Project Structure

    anki-card-generator/
    ├── main.py
    ├── anki_config.json
    ├── generator_config.json
    ├── article.yml.md
    └── docs/
        └── how-to-use.md

------------------------------------------------------------------------

## 3. Configuration

### 3.1 generator_config.json

Controls LLM + chunking behavior.

``` json
{
  "model": "qwen2.5:7b-instruct-q8_0",
  "ollama_url": "http://127.0.0.1:11434",
  "temperature": 0.2,
  "max_chars": 2200,
  "overlap": 1
}
```

### 3.2 anki_config.json

Controls AnkiConnect behavior.

``` json
{
  "anki_url": "http://127.0.0.1:8765",
  "default_deck": "Inbox::Articles",
  "model_basic": "Basic",
  "model_cloze": "Cloze",
  "field_front": "Front",
  "field_back": "Back",
  "field_cloze_text": "Text"
}
```

------------------------------------------------------------------------

## 4. Article Format (.yml.md)

Required format:

``` md
---
title: How RAM Works
source_url: https://example.com/article
deck: Tech::Memory
tags: [memory, hardware]
---

Your article text here...
```

Mandatory: - `title` Optional: - `source_url` - `deck` - `tags`

------------------------------------------------------------------------

## 5. Dry Run (No Anki)

``` bash
python3 main.py article.yml.md --dry-run --temperature 0.0
```

Output: JSON array of generated cards.

------------------------------------------------------------------------

## 6. Generate and Send to Anki

``` bash
python3 main.py article.yml.md --temperature 0.0
```

Expected result:

    Done. Chunks=... Cards=... Added=... Failed=... Deck='...'

Cards will appear in the configured deck.

------------------------------------------------------------------------

## 7. CLI Overrides

Override model:

``` bash
--model qwen2.5:7b-instruct-q8_0
```

Override Ollama URL:

``` bash
--ollama http://localhost:11434
```

Override temperature:

``` bash
--temperature 0.0
```

Override chunk size:

``` bash
--max-chars 1800
```

Disable config files:

``` bash
--anki-config ""
--gen-config ""
```

Verbose logging:

``` bash
-v
-vv
```

------------------------------------------------------------------------

## 8. Troubleshooting

### 404 on /api/chat

Cause: - Wrong model name - Wrong Ollama URL

Fix: Check installed models:

``` bash
curl http://127.0.0.1:11434/api/tags
```

Set exact model name in generator_config.json.

------------------------------------------------------------------------

### No cards generated

Possible causes: - Chunk too small - Model output invalid JSON - Article
format invalid

Check with `--dry-run`.

------------------------------------------------------------------------

## 9. Recommended Settings

For deterministic card generation:

    temperature = 0.0
    max_chars = 1800–2200
    overlap = 1

------------------------------------------------------------------------

## 10. Workflow Summary

1.  Add article in `.yml.md`
2.  Run dry-run
3.  Inspect JSON
4.  Run real generation
5.  Review in Anki
6.  Refine config if needed
