"""
WeCo Documentation router.

Serves a dedicated documentation page for the WeCo correlation engine,
accessible only from the WeCo UI (not the ORES landing page).

Routes:
  GET /weco/docs       → WeCo docs index (structured guide)
  GET /weco/docs/{slug} → Individual article rendered from markdown
"""
from __future__ import annotations

import os
from pathlib import Path as _Path

import markdown as _md
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)

# In Docker: /app/weco_engine/doc/ ; locally: <repo>/weco_engine/doc/
_WECO_DOC_DIR = _Path(__file__).resolve().parent.parent / "weco_engine" / "doc"
if not _WECO_DOC_DIR.is_dir():
    # Fallback: check relative to CWD (Docker WORKDIR=/app)
    _WECO_DOC_DIR = _Path("/app/weco_engine/doc")


# ── WeCo Documentation Catalog ───────────────────────────────────────────
# Organized as: User Guide → Tutorials → Technical Reference
_WECO_DOC_SECTIONS: list[dict] = [
    # ── User Guide ────────────────────────────────────────────────────
    {
        "title": "User Guide",
        "articles": [
            {
                "slug": "geology-primer",
                "file": "geology_primer.md",
                "title": "Geology Primer",
                "desc": "What is well correlation and how does WeCo solve it?",
            },
            {
                "slug": "parameters",
                "file": "parameters.md",
                "title": "Parameter Reference",
                "desc": "All parameters, their geological meaning, and recommended settings",
            },
            {
                "slug": "examples",
                "file": "examples.md",
                "title": "Examples & Use Cases",
                "desc": "Run examples, use the datasets, and set up your own project",
            },
            {
                "slug": "decision-tree",
                "file": "decision_tree.md",
                "title": "Workflow Decision Tree",
                "desc": "Guided workflow recommending parameters for your data",
            },
            {
                "slug": "domain-strategies",
                "file": "domain_strategies.md",
                "title": "Domain Strategies",
                "desc": "Per-domain correlation strategies (hydrogeology, marine, fluvial, …)",
            },
            {
                "slug": "formats",
                "file": "formats.md",
                "title": "File Formats",
                "desc": "Supported input/output formats, capabilities, and roadmap",
            },
        ],
    },
    # ── Tutorials ─────────────────────────────────────────────────────
    {
        "title": "Tutorials",
        "articles": [
            {
                "slug": "hierarchical",
                "file": "hierarchical_tutorial.md",
                "title": "Hierarchical Correlation",
                "desc": "Sequence stratigraphy meets Graph-DTW — multi-scale correlation",
            },
            {
                "slug": "biostratigraphy",
                "file": "tutorial_biostratigraphy.md",
                "title": "Adding Biostratigraphy",
                "desc": "Use biostratigraphic data as independent age control",
            },
            {
                "slug": "export",
                "file": "tutorial_export.md",
                "title": "Exporting Results",
                "desc": "Export to GOCAD, RESQML, RMS, and other geomodelling tools",
            },
            {
                "slug": "seistiles",
                "file": "seistiles_constraint.md",
                "title": "Seismic Constraint",
                "desc": "Constrain correlation with seismic tiles — algorithm and usage",
            },
        ],
    },
    # ── Technical Reference ───────────────────────────────────────────
    {
        "title": "Technical Reference",
        "articles": [
            {
                "slug": "architecture",
                "file": "architecture.md",
                "title": "Architecture",
                "desc": "System design, modules, and data flow",
            },
            {
                "slug": "cost-normalization",
                "file": "cost_normalization.md",
                "title": "Cost Normalization",
                "desc": "Multi-criteria cost functions and normalization (Baville 2022)",
            },
            {
                "slug": "ores-integration",
                "file": "ores_integration.md",
                "title": "ORES Integration",
                "desc": "How WeCo integrates with ORES — in-process API and job routing",
            },
            {
                "slug": "rddms-stratcolumn",
                "file": "rddms_stratcolumn.md",
                "title": "RDDMS / Stratigraphic Column",
                "desc": "Import/export stratigraphic columns via RDDMS and RESQML",
            },
            {
                "slug": "developer",
                "file": "developer.md",
                "title": "Developer Guide",
                "desc": "Build instructions, C++ compilation, testing, and contribution",
            },
        ],
    },
]

# Flat lookup: slug → (filename, title)
_WECO_DOC_FLAT: dict[str, tuple[str, str]] = {}
for _sec in _WECO_DOC_SECTIONS:
    for _item in _sec["articles"]:
        _WECO_DOC_FLAT[_item["slug"]] = (_item["file"], _item["title"])

_md_extensions = [
    "tables",
    "fenced_code",
    "toc",
    "attr_list",
    "md_in_html",
    "pymdownx.superfences",
]


def _mermaid_fence(source, language, class_name, options, md, **kw):
    """Render mermaid fenced blocks as <pre class="mermaid"> with HTML-escaped
    source so that browsers don't interpret <br/> or & as HTML before
    mermaid.js reads the textContent."""
    import html
    return f'<pre class="mermaid">{html.escape(source)}</pre>'


def _render_md(filename: str) -> tuple[str, str]:
    """Read a WeCo markdown doc and return (html_body, toc_html)."""
    md_path = _WECO_DOC_DIR / filename
    if not md_path.is_file():
        raise HTTPException(404, f"WeCo doc not found: {filename}")
    source = md_path.read_text(encoding="utf-8")
    converter = _md.Markdown(extensions=_md_extensions, extension_configs={
        "toc": {"permalink": "#", "toc_depth": "2-4"},
        "pymdownx.superfences": {
            "custom_fences": [{
                "name": "mermaid",
                "class": "mermaid",
                "format": _mermaid_fence,
            }],
        },
    })
    html_body = converter.convert(source)
    toc_html = getattr(converter, "toc", "")
    return html_body, toc_html


@router.get("/docs", response_class=HTMLResponse, summary="WeCo documentation index")
async def weco_docs_index(request: Request):
    return templates.TemplateResponse(
        request, "weco_docs.html",
        {"sections": _WECO_DOC_SECTIONS},
    )


@router.get("/docs/{slug}", response_class=HTMLResponse, summary="WeCo doc article")
async def weco_docs_article(request: Request, slug: str):
    entry = _WECO_DOC_FLAT.get(slug)
    if not entry:
        raise HTTPException(404, f"Unknown WeCo doc: {slug}")
    filename, title = entry
    html_body, toc_html = _render_md(filename)
    return templates.TemplateResponse(
        request, "weco_docs_article.html",
        {
            "title": title,
            "slug": slug,
            "toc_html": toc_html,
            "article_html": html_body,
            "sections": _WECO_DOC_SECTIONS,
        },
    )
