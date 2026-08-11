# Intake Gate — public marketing site

A static, framework-free marketing site (plain HTML + one CSS file) that
implements the pre-launch checklist. This is the **public / SEO** layer and is
deliberately separate from the signed-in app in `../app` (the "website vs
webapp" split).

Serve locally:

```bash
cd website && python3 -m http.server 8080   # http://127.0.0.1:8080
```

Deploy anywhere that hosts static files (Netlify, Cloudflare Pages, S3, GitHub
Pages). Point the domain, then do the find-and-replace below.

## Pre-launch checklist — where each item lives

| # | Item | Where |
|---|------|-------|
| 1 | Custom 404 page | `404.html` (+ a branded 404 in the app via a FastAPI handler) |
| 2 | CTA above the fold | Hero in `index.html` |
| 3 | Internal links | Header nav + footer + in-copy links |
| 4 | Thank-you page | `thank-you.html` (demo form redirects here) |
| 5 | Breadcrumbs | `thank-you.html`, `privacy.html` |
| 6 | Case studies | `index.html#case-studies` — **PLACEHOLDER** |
| 7 | 5 FAQs | `index.html#faq` (also emitted as FAQ schema) |
| 8 | Response-time promise | Hero line + dedicated banner |
| 9 | Sticky mobile CTA | `.sticky-cta` (shows under 720px) |
| 10 | robots.txt | `robots.txt` (+ `sitemap.xml`; app has its own disallow-all) |
| 11 | Unique page titles | Distinct `<title>` on every page |
| 12 | Meta descriptions | Distinct `<meta name="description">` per page |
| 13 | Social share image | `assets/og-image.png` (1200×630) + OG/Twitter tags |
| 14 | Maps + directions | Contact section — **PLACEHOLDER** map embed |
| 15 | Real reviews | `index.html#reviews` — **PLACEHOLDER** |
| 16 | Alt text on images | Every `<img>` has `alt` |
| 17 | Local/structured schema | JSON-LD Organization + SoftwareApplication + FAQ |
| 18 | Privacy-policy page | `privacy.html` — **TEMPLATE, needs legal review** |
| 19 | Google Analytics | GA4 snippet in `index.html` — **commented placeholder** |
| 20 | Team photo | `assets/team-placeholder.svg` — **PLACEHOLDER** |

## Before you go live — do these

1. **Replace the domain.** Find-and-replace `intakegate.example.com` with your real
   domain across `index.html`, `privacy.html`, `robots.txt`, `sitemap.xml`.
2. **Fill the placeholders** (all marked with `PLACEHOLDER` comments or `[brackets]`):
   real case studies (#6), real reviews (#15), team photo (#20), office address +
   Google Maps embed (#14, or remove if remote-only).
3. **Privacy policy (#18):** complete every `[bracketed]` field and have a solicitor
   review it. Register with the ICO if required.
4. **Google Analytics (#19):** put your GA4 ID in and uncomment — after you've added a
   cookie/consent notice.
5. **Wire the demo form (#4):** the form currently just redirects to the thank-you
   page. Point its `action` at your form handler / CRM (Formspree, HubSpot, etc.).
6. Regenerate `assets/og-image.png` if you rebrand (see how it was built in the repo
   history / `fixtures/generate.py` uses Pillow the same way).

Nothing here fabricates reviews, testimonials, people, or an address — those are
scaffolded placeholders for you to fill with real content.
