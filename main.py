#!/usr/bin/env python3
import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

from anki.anki_connect import ensure_deck, add_note_basic, add_note_cloze
from anki.card_validator import validate_card
from anki.normalization import normalize_key
from configs.anki import load_anki_config
from configs.generator import load_generator_config
from configs.validator import validate_optional_config_file
from input.data_slicer import chunk_paragraphs
from input.file_validator import validate_input_file
from input.ymlmd_parser import parse_ymlmd
from llm.ollama import build_user_prompt, ollama_chat, repair_prompt
from llm.response import parse_json_array_strict
from llm.system_prompt import SYSTEM_PROMPT


class PrettyFormatter(logging.Formatter):
    LEVEL_LABELS = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO ",
        logging.WARNING: "WARN ",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "FATAL",
    }
    LEVEL_COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[35m",
    }
    RESET = "\033[0m"

    def __init__(self, use_color: bool) -> None:
        super().__init__()
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, datefmt="%H:%M:%S")
        level = self.LEVEL_LABELS.get(record.levelno, record.levelname[:5].ljust(5))
        if self.use_color and record.levelno in self.LEVEL_COLORS:
            color = self.LEVEL_COLORS[record.levelno]
            level = f"{color}{level}{self.RESET}"
        return f"{ts} | {level} | {record.getMessage()}"


def configure_logging(verbose: int) -> logging.Logger:
    logger = logging.getLogger("anki-card-generator")
    logger.handlers.clear()
    logger.propagate = False

    level = logging.DEBUG if verbose > 0 else logging.INFO
    logger.setLevel(level)

    use_color = sys.stderr.isatty() and os.getenv("NO_COLOR") is None
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(PrettyFormatter(use_color=use_color))
    logger.addHandler(handler)
    return logger


def chunk_size_stats(chunks: List[str]) -> str:
    sizes = [len(x) for x in chunks]
    if not sizes:
        return "min=0 avg=0 max=0"
    return f"min={min(sizes)} avg={sum(sizes) // len(sizes)} max={max(sizes)}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert article.ymlmd -> Anki via Ollama + AnkiConnect")

    ap.add_argument("input", help="Path to article in ymlmd format (.ymlmd or .md)")

    # Config files
    ap.add_argument(
        "--anki-config",
        default="anki_config.json",
        help="Path to Anki config JSON (default: ./anki_config.json). Use empty string to disable.",
    )
    ap.add_argument(
        "--gen-config",
        default="generator_config.json",
        help="Path to generator config JSON (default: ./generator_config.json). Use empty string to disable.",
    )

    # CLI overrides (optional)
    ap.add_argument("--anki", default="", help="Override AnkiConnect URL (otherwise from anki config)")
    ap.add_argument("--model", default="", help="Override Ollama model (otherwise from generator config)")
    ap.add_argument("--ollama", default="", help="Override Ollama base URL (otherwise from generator config)")
    ap.add_argument("--temperature", type=float, default=None,
                    help="Override temperature (otherwise from generator config)")
    ap.add_argument("--max-chars", type=int, default=None,
                    help="Override max chars per chunk (otherwise from generator config)")
    ap.add_argument("--overlap", type=int, default=None,
                    help="Override paragraph overlap (otherwise from generator config)")

    # execution
    ap.add_argument("--dry-run", action="store_true", help="Do not send to Anki, just print JSON")
    ap.add_argument("--sleep", type=float, default=0.0, help="Sleep seconds between chunk requests")
    ap.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v for detailed logs, -vv for very detailed logs).",
    )
    args = ap.parse_args()

    logger = configure_logging(args.verbose)
    input_path = validate_input_file(args.input)
    logger.info("Input file: %s", input_path)

    anki_cfg_path = None if args.anki_config == "" else validate_optional_config_file(args.anki_config)
    anki_cfg = load_anki_config(anki_cfg_path)

    gen_cfg_path = None if args.gen_config == "" else validate_optional_config_file(args.gen_config)
    gen_cfg = load_generator_config(gen_cfg_path)

    # Apply CLI overrides
    if args.anki.strip():
        anki_cfg.anki_url = args.anki.strip()

    if args.model.strip():
        gen_cfg.model = args.model.strip()

    if args.ollama.strip():
        gen_cfg.ollama_url = args.ollama.strip()

    if args.temperature is not None:
        gen_cfg.temperature = max(0.0, float(args.temperature))

    if args.max_chars is not None:
        gen_cfg.max_chars = max(200, int(args.max_chars))

    if args.overlap is not None:
        gen_cfg.overlap = max(0, int(args.overlap))

    logger.info(
        "Runtime config | model=%s | ollama=%s | anki=%s | temperature=%.3f | max_chars=%d | overlap=%d | dry_run=%s",
        gen_cfg.model,
        gen_cfg.ollama_url,
        anki_cfg.anki_url,
        gen_cfg.temperature,
        gen_cfg.max_chars,
        gen_cfg.overlap,
        args.dry_run,
    )

    # parse + chunk
    try:
        article = parse_ymlmd(str(input_path))
    except Exception as e:
        logger.error("Failed to parse ymlmd '%s': %s", input_path, e)
        sys.exit(2)

    # deck fallback from config if missing in article
    if not article.deck:
        article.deck = anki_cfg.default_deck
        logger.debug("Article deck not set, fallback to default deck: %s", article.deck)

    logger.info(
        "Article parsed | title='%s' | tags=%d | deck='%s'",
        article.title,
        len(article.tags),
        article.deck,
    )

    chunks = chunk_paragraphs(article.text, max_chars=gen_cfg.max_chars, overlap_paras=gen_cfg.overlap)
    if not chunks:
        logger.error("No text chunks produced.")
        sys.exit(2)
    logger.info("Chunking complete | chunks=%d | %s", len(chunks), chunk_size_stats(chunks))

    all_cards: List[Dict[str, Any]] = []
    seen = set()

    for idx, chunk in enumerate(chunks, start=1):
        logger.info("Chunk %d/%d | chars=%d", idx, len(chunks), len(chunk))
        user_prompt = build_user_prompt(article, chunk, idx)

        content: Optional[List[Dict[str, Any]]] = None
        last_err: Optional[Exception] = None
        last_raw: str = ""

        for attempt in range(1, 4):
            logger.debug("[chunk %d] LLM request attempt %d/3", idx, attempt)
            try:
                last_raw = ollama_chat(gen_cfg.ollama_url, gen_cfg.model, SYSTEM_PROMPT, user_prompt,
                                       temperature=gen_cfg.temperature)
                if args.verbose >= 2:
                    logger.debug("[chunk %d] LLM raw response chars=%d", idx, len(last_raw))
                content = parse_json_array_strict(last_raw)
                logger.debug("[chunk %d] Parsed JSON candidates=%d", idx, len(content))
                break
            except Exception as e:
                last_err = e
                logger.warning("[chunk %d] Parse failed on attempt %d: %s", idx, attempt, e)
                try:
                    repaired = ollama_chat(
                        gen_cfg.ollama_url,
                        gen_cfg.model,
                        SYSTEM_PROMPT,
                        repair_prompt(last_raw),
                        temperature=0.0,
                    )
                    if args.verbose >= 2:
                        logger.debug("[chunk %d] Repair response chars=%d", idx, len(repaired))
                    content = parse_json_array_strict(repaired)
                    logger.debug("[chunk %d] Repair succeeded, candidates=%d", idx, len(content))
                    break
                except Exception as e2:
                    last_err = e2
                    logger.warning("[chunk %d] Repair failed on attempt %d: %s", idx, attempt, e2)

        if content is None:
            logger.error("[chunk %d] Failed after retries: %s", idx, last_err)
            continue

        chunk_added = 0
        chunk_invalid = 0
        chunk_duplicates = 0
        chunk_skipped_non_dict = 0

        for c in content:
            if not isinstance(c, dict):
                chunk_skipped_non_dict += 1
                continue

            # merge tags + enforce source.chunk
            c_tags = c.get("tags", [])
            if not isinstance(c_tags, list):
                c_tags = []
            merged_tags = list(dict.fromkeys(article.tags + [str(x) for x in c_tags if str(x).strip()]))
            c["tags"] = merged_tags

            src = c.get("source", {})
            if not isinstance(src, dict):
                src = {}
            src["chunk"] = idx
            c["source"] = src

            vc = validate_card(c)
            if not vc:
                chunk_invalid += 1
                continue

            k = normalize_key(vc)
            if k in seen:
                chunk_duplicates += 1
                continue
            seen.add(k)
            all_cards.append(vc)
            chunk_added += 1

        logger.info(
            "[chunk %d] candidates=%d | added=%d | invalid=%d | duplicates=%d | non_dict=%d",
            idx,
            len(content),
            chunk_added,
            chunk_invalid,
            chunk_duplicates,
            chunk_skipped_non_dict,
        )

        if args.sleep > 0:
            logger.debug("[chunk %d] Sleeping %.2fs", idx, args.sleep)
            time.sleep(args.sleep)

    if args.dry_run:
        logger.info("Dry-run mode: generated cards=%d", len(all_cards))
        print(json.dumps(all_cards, ensure_ascii=False, indent=2))
        return

    logger.info("Ensuring deck exists: %s", article.deck)
    ensure_deck(anki_cfg.anki_url, article.deck)

    added = 0
    failed = 0
    for c in all_cards:
        try:
            if c["type"] == "qa":
                add_note_basic(anki_cfg, article.deck, c["front"], c["back"], c.get("tags", []))
            else:
                add_note_cloze(anki_cfg, article.deck, c["text"], c.get("tags", []))
            added += 1
        except Exception as e:
            failed += 1
            logger.error("Failed to add note type=%s: %s", c.get("type", "?"), e)

    logger.info(
        "Done. Chunks=%d Cards=%d Added=%d Failed=%d Deck='%s'",
        len(chunks),
        len(all_cards),
        added,
        failed,
        article.deck,
    )


if __name__ == "__main__":
    main()
