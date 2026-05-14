"""
HowTo / ORES landing-page router.

Serves the ORES index page (``/ores``, ``/howto``) and individual
markdown-based articles (``/howto/{slug}``).  Extracted from main.py
to keep routing modules focused and manageable.
"""
from __future__ import annotations

import os
from pathlib import Path as _Path

import markdown as _md
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .instances import get_instances, get_active_name

router = APIRouter()
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)

_MD_DIR = _Path(__file__).resolve().parent.parent / "md"

# ── HowTo article catalog ────────────────────────────────────────────────
# Grouped structure for the HowTo index page.
# Each section has a title and a list of items.
# Items can optionally carry ``children`` (sub-articles shown indented).
_HOWTO_SECTIONS: list[dict] = [
    # ── Getting Started ───────────────────────────────────────────────
    {
        "title": "Getting Started",
        "items": [
            {
                "slug": "ores-overview",
                "file": "Readme.md",
                "title": "ORES Overview",
                "desc": "Web client capabilities, project layout & pipeline guide",
            },
            {
                "slug": "query-guide",
                "file": "Query.md",
                "title": "Querying Data",
                "desc": "REST, ETP, GraphQL & OSDU Search – all query paths explained",
            },
        ],
    },
    # ── Subsurface Data Models ────────────────────────────────────────
    {
        "title": "Subsurface Data Models",
        "items": [
            {
                "slug": "business-decision",
                "file": "BusinessDecision.md",
                "title": "Business Decision",
                "desc": "Model DG1–DG4 decisions as BusinessDecision records",
                "children": [
                    {"slug": "bd-demo",      "file": "BdDemo.md",       "title": "Drogon Demo",    "desc": "Drogon DG package: search, analyse & data model"},
                    {"slug": "volumes",      "file": "Volumes.md",      "title": "Volumes",        "desc": "ReservoirEstimatedVolumes WPC & fmu-dataio mapping"},
                    {"slug": "geolabelset",  "file": "GeoLabelSet.md",  "title": "GeoLabelSet",   "desc": "Reservoir volumes & statistics manifests"},
                    {"slug": "risk",         "file": "Risk.md",         "title": "Risk",           "desc": "Subsurface risk data management"},
                    {"slug": "uncertainty",  "file": "Uncertainty.md",  "title": "Uncertainty",    "desc": "FMU ensemble / Monte Carlo in OSDU"},
                ],
            },
            {
                "slug": "seismic-interp",
                "file": "SeisInt.md",
                "title": "Seismic Interpretation",
                "desc": "M27 data model, RDDMS patterns & Drogon demo",
            },
            {
                "slug": "strat-column",
                "file": "StratColumn.md",
                "title": "Stratigraphy",
                "desc": "Data model, tooling & workflow",
            },
            {
                "slug": "activity",
                "file": "Activity.md",
                "title": "Activity & Provenance",
                "desc": "ActivityTemplate + Activity records for workflow provenance",
            },
        ],
    },
    # ── Infrastructure ─────────────────────────────────────────────
    {
        "title": "Infrastructure",
        "items": [
            {
                "slug": "pws",
                "file": "PWS.md",
                "title": "Project & Workflow Service",
                "desc": "P&WS lifecycle, endpoints & RDDMS integration",
            },
            {
                "slug": "_ext_rddms_home",
                "external_url": "https://community.opengroup.org/osdu/platform/domain-data-mgmt-services/reservoir/home/-/blob/main/README.md",
                "title": "Reservoir DDMS Home ↗",
                "desc": "Official OSDU Reservoir DDMS documentation – data model, ETP protocol, deployment & API reference",
            },
            {
                "slug": "_ext_etp_best",
                "external_url": "https://community.opengroup.org/osdu/platform/domain-data-mgmt-services/reservoir/open-etp-server/-/blob/main/docs/bestPracticesForClients.md",
                "title": "ETP Client Best Practices ↗",
                "desc": "Transactions, large arrays, dataspace creation & locking – recommended patterns for ETP clients",
            },
        ],
    },
    # ── Reference ─────────────────────────────────────────────────────
    {
        "title": "Reference",
        "items": [
            {
                "slug": "crs-guide",
                "file": "CrsGuide.md",
                "title": "CRS Guide",
                "desc": "RESQML ⇄ OSDU coordinate reference systems",
            },
        ],
    },
]

# Flat lookup: slug → (filename, title)  - used by the article route
_HOWTO_FLAT: dict[str, tuple[str, str]] = {}
for _sec in _HOWTO_SECTIONS:
    for _item in _sec["items"]:
        if "file" in _item:
            _HOWTO_FLAT[_item["slug"]] = (_item["file"], _item["title"])
        for _child in _item.get("children", []):
            if "file" in _child:
                _HOWTO_FLAT[_child["slug"]] = (_child["file"], _child["title"])

_md_extensions = [
    "tables",
    "fenced_code",
    "toc",
    "attr_list",
    "md_in_html",
    "pymdownx.superfences",
]


def _render_md(filename: str) -> tuple[str, str]:
    """Read a markdown file and return (html_body, toc_html)."""
    md_path = _MD_DIR / filename
    if not md_path.is_file():
        raise HTTPException(404, f"Article not found: {filename}")
    source = md_path.read_text(encoding="utf-8")
    converter = _md.Markdown(extensions=_md_extensions, extension_configs={
        "toc": {"permalink": True, "toc_depth": "2-4"},
        "pymdownx.superfences": {
            "custom_fences": [{
                "name": "mermaid",
                "class": "mermaid",
                "format": lambda source, language, class_name, options, md, **kw: (
                    f'<pre class="mermaid">{source}</pre>'
                ),
            }],
        },
    })
    html_body = converter.convert(source)
    toc_html = getattr(converter, "toc", "")
    return html_body, toc_html


@router.get("/ores", response_class=HTMLResponse, summary="ORES landing page")
@router.get("/howto", response_class=HTMLResponse, include_in_schema=False)
async def howto_index(request: Request):
    insts = get_instances()
    return templates.TemplateResponse(
        request, "ores.html",
        {
            "sections": _HOWTO_SECTIONS,
            "instances": {n: {"hostname": i.hostname, "partition": i.data_partition_id, "auth_mode": i.auth_mode} for n, i in insts.items()},
            "active_instance": get_active_name(),
        },
    )


@router.get("/howto/{slug}", response_class=HTMLResponse, summary="HowTo article")
async def howto_article(request: Request, slug: str):
    entry = _HOWTO_FLAT.get(slug)
    if not entry:
        raise HTTPException(404, f"Unknown article: {slug}")
    filename, title = entry
    html_body, toc_html = _render_md(filename)
    # Find children for this slug (if it's a parent article)
    children: list[dict] = []
    for sec in _HOWTO_SECTIONS:
        for item in sec["items"]:
            if item["slug"] == slug:
                children = item.get("children", [])
                break
    return templates.TemplateResponse(
        request, "howto_article.html",
        {
            "title": title,
            "slug": slug,
            "toc_html": toc_html,
            "article_html": html_body,
            "sections": _HOWTO_SECTIONS,
            "children": children,
        },
    )
