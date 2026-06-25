"""Economic Article Generator — Flask server + Anthropic API logic.

Run locally with:  python app.py
Then open:          http://localhost:5000
"""

import os
import random

import anthropic
import markdown as md
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)

# Anthropic client — resolves ANTHROPIC_API_KEY from the environment (.env).
client = anthropic.Anthropic()

# Same theme list as the original React app.
THEMES = [
    "Inflation and consumer behaviour",
    "Central bank policy and interest rates",
    "Labour market trends",
    "Global supply chain disruptions",
    "Energy markets and geopolitics",
    "Emerging market debt",
    "Housing affordability",
    "AI's impact on productivity",
    "Trade deficits and currency dynamics",
    "Fiscal policy and government spending",
]


def generate_article(theme: str) -> str:
    """Call the Anthropic API and return a newsletter-ready article in markdown."""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[
            {
                "role": "user",
                "content": f"""Write a concise, well-structured economic analysis article on the theme: "{theme}".

Include:
- A compelling headline
- An executive summary (2–3 sentences)
- 3–4 body sections with subheadings
- A concluding outlook paragraph

Tone: analytical, accessible, suitable for a financial newsletter audience.
Format: plain markdown.""",
            }
        ],
    )
    # Concatenate any text blocks in the response (robust against thinking blocks etc.).
    return "".join(block.text for block in response.content if block.type == "text")


def render_markdown(text: str) -> str:
    """Convert markdown to HTML for styled display."""
    return md.markdown(text, extensions=["extra", "sane_lists"])


@app.route("/")
def index():
    """Serve the single-page UI."""
    return render_template("index.html", themes=THEMES)


@app.route("/generate", methods=["POST"])
def generate():
    """Accept JSON { "theme": "..." | null } and return the generated article."""
    data = request.get_json(silent=True) or {}
    custom = (data.get("theme") or "").strip()

    # Use the custom theme if provided, otherwise pick a random one.
    theme = custom if custom else random.choice(THEMES)

    try:
        article = generate_article(theme)
    except anthropic.AuthenticationError:
        return jsonify({"error": "Invalid or missing ANTHROPIC_API_KEY. Check your .env file."}), 500
    except anthropic.RateLimitError:
        return jsonify({"error": "Rate limited by the Anthropic API. Please wait and try again."}), 429
    except anthropic.APIError as exc:
        return jsonify({"error": f"Anthropic API error: {exc.message}"}), 502
    except Exception as exc:  # noqa: BLE001 — surface anything else to the UI
        return jsonify({"error": f"Unexpected error: {exc}"}), 500

    return jsonify(
        {
            "theme": theme,
            "article": article,
            "article_html": render_markdown(article),
        }
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
