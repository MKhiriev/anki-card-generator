# Anki Card Generator (Self-hosted LLM на ноутбуке)

Локальный инструмент для преобразования заметок/статей в формате `.yml.md` в карточки Anki через:
- локальную модель в **Ollama** (self-hosted, без облака),
- **AnkiConnect** для автоматического добавления карточек в колоду.

Основная цель проекта: ускорить изучение новой информации и её запоминание через автоматическую генерацию качественных карточек.

## Что делает проект

Pipeline:

1. Читает файл статьи `.yml.md` (frontmatter + текст).
2. Делит текст на параграфные чанки (`max_chars`, `overlap`).
3. Отправляет каждый чанк в локальную LLM через Ollama (`/api/chat`).
4. Парсит JSON-ответ, валидирует карточки, удаляет дубликаты.
5. Добавляет карточки в Anki через AnkiConnect (`/addNote`).

Поддерживаемые типы карточек:
- `qa`: поля `front` + `back`
- `cloze`: поле `text` с `{{c1::...}}`

## Стек и зависимости

- Python 3.10+
- [Ollama](https://ollama.com/) (локально запущенный сервер)
- [Anki](https://apps.ankiweb.net/) + AnkiConnect addon
- Python-зависимости (см. `requirements.txt`):
  - `requests`
  - `pytest`

## Структура проекта

```text
anki-card-generator/
├── main.py          # CLI-оркестратор всего пайплайна
├── anki/
│   ├── anki_connect.py       # вызовы AnkiConnect, addNote/createDeck
│   ├── card_validator.py     # валидация карточек (qa/cloze)
│   └── normalization.py      # ключ для дедупликации
├── input/
│   ├── ymlmd_parser.py       # парсинг frontmatter + body
│   ├── data_slicer.py        # чанкинг по параграфам
│   └── file_validator.py     # проверка входного файла
├── llm/
│   ├── system_prompt.py      # системный промпт генерации
│   ├── ollama.py             # API-обертка Ollama + prompt builder
│   └── response.py           # строгий JSON array parser
├── configs/
│   ├── anki.py               # загрузка anki config
│   ├── generator.py          # загрузка llm/chunk config
│   └── validator.py          # проверка config path
├── models/
│   ├── article.py            # dataclass Article
│   └── configs.py            # dataclass AnkiConfig/GeneratorConfig
├── anki_config.json
├── generator_config.json
├── article.yml.md            # пример входного файла
├── docs/how-to-use.md
└── tests/
```

## Быстрый старт

### 1. Проверить сервисы

```bash
curl http://127.0.0.1:11434/api/tags
curl http://127.0.0.1:8765
```

Оба запроса должны вернуть JSON.

### 2. Установить Python-зависимости

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Настроить конфиги

`generator_config.json`:

```json
{
  "model": "qwen2.5:7b-instruct-q8_0",
  "ollama_url": "http://127.0.0.1:11434",
  "temperature": 0.2,
  "max_chars": 2200,
  "overlap": 1
}
```

`anki_config.json`:

```json
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

### 4. Подготовить входной файл

Формат `.yml.md`:

```md
---
title: "Как устроена оперативная память"
source_url: "https://example.com/article"
deck: "Inbox::Articles"
tags: ["topic:hardware", "topic:ram"]
---
Текст статьи...
```

Обязательно:
- `title`

Опционально:
- `source_url`
- `deck` (если пусто, берётся `default_deck`)
- `tags` (массив или строка)

Автоматически добавляются теги:
- `article:<slug>`
- `src:<domain>` (если задан `source_url`)

### 5. Dry-run (без отправки в Anki)

```bash
python3 main.py article.yml.md --dry-run --temperature 0.0
```

### 6. Реальная отправка в Anki

```bash
python3 main.py article.yml.md --temperature 0.0
```

Пример финального лога:

```text
Done. Chunks=... Cards=... Added=... Failed=... Deck='...'
```

## CLI параметры

Основные:

- `input` — путь к `.ymlmd` или `.md`
- `--dry-run` — только вывести JSON карточек
- `--sleep` — пауза между chunk-запросами к LLM
- `-v/--verbose` — подробные логи (`-v` подробно, `-vv` максимально детально)

Пути к конфигам:

- `--anki-config` (по умолчанию `anki_config.json`)
- `--gen-config` (по умолчанию `generator_config.json`)
- можно отключить конфиг: `--anki-config ""` / `--gen-config ""`

Переопределения:

- `--anki`
- `--model`
- `--ollama`
- `--temperature`
- `--max-chars`
- `--overlap`

## Ограничения и правила качества (по текущему коду)

- Валидация `qa`:
  - обязательны `front`, `back`
  - `front <= 400`, `back <= 1200`
- Валидация `cloze`:
  - обязательен `text`
  - должен содержать `{{c1::...}}`
  - `text <= 1800`
- Дедупликация:
  - по нормализованному ключу (`type + front/text`), регистр/пробелы схлопываются
- При сбое JSON:
  - до 3 попыток генерации на chunk
  - между попытками используется `repair_prompt`
- Для `addNote` используется `allowDuplicate: false`

## Текущее состояние тестов

На текущем состоянии репозитория:

```bash
.venv/bin/python -m pytest -q
```

Результат: `24 passed`.

## Типовой сценарий использования для обучения

1. Берёшь материал (статья/конспект) и сохраняешь в `.yml.md`.
2. Запускаешь `--dry-run`, смотришь качество вопросов.
3. При необходимости меняешь:
   - модель (`--model`)
   - температуру (`--temperature 0.0` для стабильности)
   - размер чанка (`--max-chars`)
4. Запускаешь без `--dry-run` и получаешь карточки в Anki.
5. Повторяешь цикл для новых материалов.

## Идеи развития (из TODO)

Roadmap переведён в формат `MVP-first` (см. `TODO.md`):

- Этап 2 (MVP): `critic` v1, подбор размера входа для Ollama, метрики качества и KPI релиза.
- Этап 3: устойчивость и качество (улучшенный парсинг YAML, формализация контракта `critic`).
- Этап 4: расширение источников с приоритетом `PDF -> YouTube -> остальное`.
- Этап 5: генерация данных для fine-tuning на основе реального использования.
