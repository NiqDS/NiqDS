# Economic Article Generator

A locally-runnable Python web app that generates newsletter-ready economic
analysis articles using the Anthropic API. It's a Flask + vanilla-JS port of
the original `economic-article-app.jsx` React artifact, with the same features
and dark editorial design.

## Features

- Pick a **random** theme or type your own **custom** theme
- Calls Claude to generate a structured markdown article (headline, executive
  summary, body sections, outlook)
- Styled markdown rendering with a dark editorial look
- **Copy** (copies the raw markdown) and **New Article** buttons
- Idle / loading / done / error UI states

## Prerequisites

- Python 3.9+
- An Anthropic API key

## Setup

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Create your `.env` file from the template and add your key:

   ```bash
   cp .env.example .env
   ```

   Then edit `.env`:

   ```
   ANTHROPIC_API_KEY=your_key_here
   ```

   > `.env` is gitignored so your key is never committed.

## Run

```bash
python app.py
```

Then open <http://localhost:5000> in your browser.

## Project structure

```
economic-article-app/
├── app.py               # Flask server + Anthropic API logic
├── templates/
│   └── index.html       # Single-page UI (HTML + CSS + vanilla JS)
├── .env.example         # Copy to .env and add your API key
├── .gitignore
├── requirements.txt
└── README.md
```

## How it works

- `GET /` serves the single-page UI.
- `POST /generate` accepts JSON `{ "theme": "..." | null }`. Flask uses the
  custom theme if provided, otherwise picks a random one, calls the Anthropic
  API, renders the markdown to HTML server-side, and returns
  `{ "theme": "...", "article": "...", "article_html": "..." }`.
- The browser stores the raw markdown for the **Copy** button and displays the
  HTML version.

The model used is `claude-sonnet-4-6` (a good balance of quality and cost for
high-volume content generation). To change it, edit the `model` argument in
`generate_article()` in `app.py`.
