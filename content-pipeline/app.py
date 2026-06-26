"""Content Pipeline — Flask web app.

Generates the four-draft weekly content arc (Tuesday LinkedIn, Thursday deep
dive, Friday LinkedIn, Friday Substack) via the Anthropic API and saves each
draft as a markdown file organised by week.

Run:  python app.py   →   http://localhost:5000
"""

import os
import re
from datetime import date

import anthropic
import markdown as md
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Model is configurable via .env; defaults to the spec's choice.
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# ─── Prompts ──────────────────────────────────────────────────────────────────

PROMPTS = {
    "tue": lambda week, topic, thesis, notes, tease: f"""You are writing Movement I of a 4-part weekly content arc about Digital Economics, AI, Finance, and Financial Literacy.

WEEK: {week}
TOPIC / ARC TITLE: {topic}
ARC THESIS (THE CONCLUSION): {thesis}
SOURCE NOTES & KEY DATA: {notes}
NEXT WEEK'S TEASE: {tease}

Write the TUESDAY LINKEDIN POST — Movement I: The Question.
- ~400 words
- Opens with ONE striking data point from the source notes
- Poses the central question of the week
- Builds intrigue — do NOT answer the question
- Ends by teasing Thursday's evidence and Friday's full article
- Tone: sharp, accessible, thought-provoking. No jargon dumps.
- Format: plain text, short punchy paragraphs, no headers""",

    "thu": lambda week, topic, thesis, notes, tease: f"""You are writing Movement II of a 4-part weekly content arc about Digital Economics, AI, Finance, and Financial Literacy.

WEEK: {week}
TOPIC / ARC TITLE: {topic}
ARC THESIS (THE CONCLUSION): {thesis}
SOURCE NOTES & KEY DATA: {notes}
NEXT WEEK'S TEASE: {tease}

Write the THURSDAY DEEP DIVE — Movement II: The Evidence.
- ~850 words
- Answers Tuesday's question with evidence and analysis
- 3–4 structured sections building toward the thesis
- Ground every claim in the source notes
- Confident conclusion that lands the arc thesis
- Tone: analytical, authoritative, readable. Think FT meets Substack.
- Format: plain text with ## section headers""",

    "fri-li": lambda week, topic, thesis, notes, tease: f"""You are writing Movement III of a 4-part weekly content arc about Digital Economics, AI, Finance, and Financial Literacy.

WEEK: {week}
TOPIC / ARC TITLE: {topic}
ARC THESIS (THE CONCLUSION): {thesis}
SOURCE NOTES & KEY DATA: {notes}
NEXT WEEK'S TEASE: {tease}

Write the FRIDAY LINKEDIN POST — Movement III: Preview + Results.
- ~500 words
- Briefly recaps the week's question and key finding (1–2 sentences)
- Previews the key Substack insight to compel a click
- Ends with next week tease: "{tease}"
- Clear CTA to read the full Substack article
- Tone: warm, conversational, community-building
- Format: plain text, short paragraphs""",

    "fri-sub": lambda week, topic, thesis, notes, tease: f"""You are writing Movement IV of a 4-part weekly content arc about Digital Economics, AI, Finance, and Financial Literacy.

WEEK: {week}
TOPIC / ARC TITLE: {topic}
ARC THESIS (THE CONCLUSION): {thesis}
SOURCE NOTES & KEY DATA: {notes}
NEXT WEEK'S TEASE: {tease}

Write the FRIDAY SUBSTACK FULL ARTICLE — Movement IV.
- ~2100 words
- Structure: Hook → Context → The Question → Evidence (3–4 sections) → Implications → Conclusion
- Every factual claim grounded in the source notes
- Thesis lands in conclusion: "{thesis}"
- Tone: rigorous but readable — reader feels smarter having read it
- Format: markdown with # title, ## section headers, **bold** for key terms
- Final line: "Next week: {tease}" """,
}

DRAFT_META = {
    "tue":     {"label": "Tuesday LinkedIn",   "tag": "400w",  "color": "#e8534b", "max_tokens": 1200},
    "thu":     {"label": "Thursday Deep Dive", "tag": "850w",  "color": "#4b8fe8", "max_tokens": 2000},
    "fri-li":  {"label": "Friday LinkedIn",    "tag": "500w",  "color": "#9b6fe8", "max_tokens": 1400},
    "fri-sub": {"label": "Friday Substack",    "tag": "2100w", "color": "#e8a84b", "max_tokens": 4096},
}

# ─── Core logic ───────────────────────────────────────────────────────────────


def call_api(draft_id, week, topic, thesis, notes, tease):
    prompt = PROMPTS[draft_id](week or "—", topic, thesis, notes, tease)
    response = client.messages.create(
        model=MODEL,
        max_tokens=DRAFT_META[draft_id]["max_tokens"],
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def save_draft(week, draft_id, topic, content):
    slug = re.sub(r"[^a-z0-9-]", "", topic.lower().replace(" ", "-"))[:40]
    label = DRAFT_META[draft_id]["label"].lower().replace(" ", "-")
    folder = os.path.join("drafts", f"week-{week}")
    os.makedirs(folder, exist_ok=True)
    filename = os.path.join(folder, f"{date.today()}-{label}-{slug}.md")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    return filename


def build_result(draft_id, week, topic, thesis, notes, tease):
    content = call_api(draft_id, week, topic, thesis, notes, tease)
    saved = save_draft(week, draft_id, topic, content)
    return {
        "draft_id": draft_id,
        "theme": DRAFT_META[draft_id]["label"],
        "content": content,
        "content_html": md.markdown(content),
        "word_count": len(content.split()),
        "saved_path": saved,
    }


# ─── Routes ───────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    return render_template("index.html", draft_meta=DRAFT_META)


@app.route("/generate", methods=["POST"])
def generate():
    data = request.json
    try:
        result = build_result(
            data["draft_id"], data.get("week", ""), data["topic"],
            data["thesis"], data["notes"], data.get("tease", ""),
        )
        return jsonify(result)
    except anthropic.APIError as e:
        return jsonify({"error": str(e)}), 502
    except KeyError as e:
        return jsonify({"error": f"Missing field: {e}"}), 400


@app.route("/generate-all", methods=["POST"])
def generate_all():
    data = request.json
    results = {}
    try:
        for draft_id in DRAFT_META:
            results[draft_id] = build_result(
                draft_id, data.get("week", ""), data["topic"],
                data["thesis"], data["notes"], data.get("tease", ""),
            )
        return jsonify(results)
    except anthropic.APIError as e:
        return jsonify({"error": str(e), "partial": results}), 502
    except KeyError as e:
        return jsonify({"error": f"Missing field: {e}"}), 400


@app.route("/drafts/<week>")
def list_drafts(week):
    folder = os.path.join("drafts", f"week-{week}")
    if not os.path.isdir(folder):
        return jsonify({"week": week, "files": []})
    files = sorted(f for f in os.listdir(folder) if f.endswith(".md"))
    return jsonify({"week": week, "files": files})


if __name__ == "__main__":
    app.run(debug=True)
