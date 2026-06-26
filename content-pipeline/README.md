# Content Pipeline — Python Flask App

A local web app that generates a full **4-draft weekly content arc** for the
_Digital Economics · AI · Finance · Financial Literacy_ series, using the
Anthropic API. Each draft is shown in a tabbed dark-editorial UI and saved as a
markdown file organised by week.

## Arc Model

| Tab          | Format    | Length  | Movement            |
| ------------ | --------- | ------- | ------------------- |
| Tuesday      | LinkedIn  | ~400w   | The Question        |
| Thursday     | LinkedIn  | ~850w   | The Evidence        |
| Fri LinkedIn | LinkedIn  | ~500w   | Preview + Results   |
| Fri Substack | Substack  | ~2100w  | Full Article        |

## Quick start

1. **Prerequisites:** Python 3.9+

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Add your API key:** copy `.env.example` to `.env` and fill in your key:

   ```bash
   cp .env.example .env
   # then edit .env → ANTHROPIC_API_KEY=sk-ant-...
   ```

4. **Run:**

   ```bash
   python app.py
   ```

5. Open **http://localhost:5000**

6. Each Monday: fill in the week #, topic, arc thesis, source notes, and next
   week's tease — then click **Generate** on a tab, or **⚡ Generate All Four
   Drafts**.

## How it works

- The left panel collects the weekly inputs. Topic, thesis, and source notes are
  required before generation is enabled.
- Each tab renders its draft as markdown HTML, with a word count and a **Copy**
  button (copies the raw markdown).
- Every generated draft is auto-saved to `drafts/week-<N>/` as
  `YYYY-MM-DD-<label>-<topic-slug>.md`.

## Routes

| Method | Path             | Purpose                                  |
| ------ | ---------------- | ---------------------------------------- |
| GET    | `/`              | Serve the UI                             |
| POST   | `/generate`      | Generate one draft (`draft_id` in body)  |
| POST   | `/generate-all`  | Generate all four drafts sequentially    |
| GET    | `/drafts/<week>` | List saved drafts for a week             |

## Output structure

```
drafts/
  week-4/
    2026-06-24-tuesday-linkedin-who-controls-ai-in-finance.md
    2026-06-26-thursday-deep-dive-who-controls-ai-in-finance.md
    2026-06-27-friday-linkedin-who-controls-ai-in-finance.md
    2026-06-27-friday-substack-who-controls-ai-in-finance.md
```

## Configuration

| What            | Where                                          |
| --------------- | ---------------------------------------------- |
| API key         | `ANTHROPIC_API_KEY` in `.env`                  |
| Model           | `ANTHROPIC_MODEL` in `.env` (default sonnet)   |
| Prompts / tone  | `PROMPTS` dict in `app.py`                     |
| Per-draft length| `max_tokens` in `DRAFT_META` in `app.py`       |
| Accent colours  | `:root` CSS vars in `templates/index.html`     |

> **Note on `max_tokens`:** the Substack article (~2100 words) needs a larger
> token budget than the LinkedIn posts, so `max_tokens` is set per-draft in
> `DRAFT_META` rather than a single flat value.
