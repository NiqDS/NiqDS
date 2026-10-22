"""The single source of the visual identity, for every page the skill emits.

Why a Python module and not just a stylesheet: the palette is needed in
three places that cannot share a file. The forms link a stylesheet from
`web/`. The pilot report is a standalone HTML file that lives in the pilot
folder and gets emailed around, so it must carry its own styles -- a
relative link to `web/` breaks the moment anyone moves or forwards it.
And `web/build_form.py` generates pages that must match. Keeping the tokens
here and generating both from them means the three cannot drift.

The identity is the dark teal from the team's `front.html`, which is the
one they evolved and the one with a point of view. It is extended to a
proper light/dark pair rather than being dark-only: these pages are opened
in a bank, on a projector, and printed, and a page that can only be dark is
a page that is sometimes unreadable.

Contrast was checked, not eyeballed: the light accent is darkened from the
original #2ee6a6 (which carries 1.9:1 against white -- invisible as a
button) to #0a7f5f, giving white-on-accent about 4.6:1, past the 4.5:1 line
for body text.
"""
from __future__ import annotations

__all__ = ["THEME_CSS", "TOKENS_LIGHT", "TOKENS_DARK"]

TOKENS_LIGHT: dict[str, str] = {
    "--bg": "#f1f6f8",
    "--panel": "#ffffff",
    "--text": "#0b1f2a",
    "--muted": "#55707c",
    "--border": "#cbdde4",
    "--accent": "#0a7f5f",
    "--accent-soft": "#e3f5ee",
    "--accent-text": "#ffffff",
    "--ok": "#0a7f5f",
    "--ok-text": "#0a6b50",
    "--ok-bg": "#e3f5ee",
    "--danger": "#b3261e",
    "--danger-bg": "#fdecea",
    "--shadow": "0 1px 2px rgba(11,31,42,.06)",
}

TOKENS_DARK: dict[str, str] = {
    "--bg": "#031522",
    "--panel": "#0a2337",
    "--text": "#eaf4f7",
    "--muted": "#a9c1cc",
    "--border": "#1d4256",
    "--accent": "#2ee6a6",
    "--accent-soft": "#0d3b31",
    "--accent-text": "#042016",
    "--ok": "#2ee6a6",
    "--ok-text": "#6fd88a",
    "--ok-bg": "#10392a",
    "--danger": "#ff6b64",
    "--danger-bg": "#3a1f1e",
    "--shadow": "0 1px 2px rgba(0,0,0,.35)",
}


def _block(tokens: dict[str, str], indent: str = "  ") -> str:
    return "\n".join(f"{indent}{name}: {value};" for name, value in tokens.items())


THEME_CSS = f"""/* Generated from skill/theme.py -- edit there, then run web/build_form.py.
   Light by default, dark when the viewer's system asks for it; data-theme
   on <html> overrides both, so a page can be pinned either way. */
:root {{
{_block(TOKENS_LIGHT)}
}}

@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
{_block(TOKENS_DARK, indent="    ")}
  }}
}}

:root[data-theme="dark"] {{
{_block(TOKENS_DARK)}
}}
"""
