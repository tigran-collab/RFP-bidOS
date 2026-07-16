"""Portal template catalog for adding authenticated sources by config.

Each template is a starting point for a new authenticated portal source. It
carries a ``source_type`` (either ``planetbids`` for the dedicated PlanetBids
adapter, or ``authenticated_browser`` for the generic config-driven browser
adapter), a login URL, and a ``config_json`` skeleton with clearly-marked TODO
placeholders that the user finalizes for their agency.

NO real credentials, cids, or verified selectors live here — every
portal-specific value is a placeholder. Selectors for the generic browser
portals in particular typically need to be finalized from a real logged-in
session (the DOM is not knowable without inspecting the authenticated page).

The catalog feeds the ``add-portal`` / ``list-portal-templates`` CLI commands.
"""

from __future__ import annotations

import copy

# Placeholder markers make it obvious what still needs filling in.
_TODO_URL = "TODO_REPLACE_WITH_LIST_URL"
_TODO_SELECTOR = "TODO_REPLACE_WITH_CSS_SELECTOR"

# Post-login URL markers per portal type: when the browser lands on a URL
# containing this substring, assisted login is complete and the window can
# close itself. Used as a fallback when a source's config_json does not set
# success_url_substring (e.g. sources created before this was added).
DEFAULT_LOGIN_SUCCESS_SUBSTRINGS: dict[str, str] = {
    "bidnet": "/private/",
}


PORTAL_TEMPLATES: dict[str, dict] = {
    "planetbids": {
        "display_name": "PlanetBids (vendor portal)",
        "source_type": "planetbids",
        "portal_type": "PlanetBids",
        "login_url": "https://vendors.planetbids.com/portal/TODO_CID/bo/bo-search",
        "config_json": {
            "cid": "TODO_REPLACE_WITH_NUMERIC_CID",
            "api_base": "https://api-external.prod.planetbids.com",
            "bids_path": "/papi/bids",
            "params": {"per_page": 100, "page": 1},
            "portal_bid_url_template": (
                "https://vendors.planetbids.com/portal/{cid}/bo/bo-detail/{bid_id}"
            ),
            "agency": "TODO_REPLACE_WITH_AGENCY_NAME",
            "field_map": {
                "id": "id",
                "title": "title",
                "solicitation_number": "bidNumber",
                "due_date": "dueDate",
                "description": "description",
            },
        },
        "notes": (
            "PlanetBids uses the dedicated papi adapter. Replace TODO_CID / cid "
            "with the agency's numeric portal id (from the vendor portal URL), "
            "then set-credentials, portal-login, and enable."
        ),
    },
    "bidnet": {
        "display_name": "BidNet Direct",
        "source_type": "authenticated_browser",
        "portal_type": "BidNet",
        "login_url": "https://www.bidnetdirect.com/",
        "config_json": {
            "list_url": _TODO_URL,
            "wait_selector": _TODO_SELECTOR,
            "success_url_substring": "/private/",
            "agency": "BidNet Direct",
            "search_keywords": ["California", "Texas"],
            "search_input_selector": "#solicitationSingleBoxSearch",
            "search_submit_selector": "#topSearchButton",
            "state_filter": ["CA", "TX"],
            "row_selector": _TODO_SELECTOR,
            "field_map": {
                "title": _TODO_SELECTOR,
                "solicitation_number": _TODO_SELECTOR,
                "due_date": _TODO_SELECTOR,
                "agency": _TODO_SELECTOR,
                "source_url": _TODO_SELECTOR,
            },
        },
        "notes": (
            "BidNet Direct login is at https://www.bidnetdirect.com/. The exact "
            "list_url and row/field selectors must be captured from a real "
            "logged-in session. The template searches California and Texas only "
            "and filters results to CA/TX evidence. Run "
            "add-portal -> set-credentials -> portal-login, then open the saved "
            "bids-list page and finalize list_url, row_selector, and field_map "
            "from the real DOM. If you leave row_selector/field_map as "
            "placeholders, the adapter falls back to the generic table parser."
        ),
    },
    "bonfire": {
        "display_name": "Bonfire (bonfirehub.com)",
        "source_type": "authenticated_browser",
        "portal_type": "Bonfire",
        "login_url": "https://gobonfire.com/login",
        "config_json": {
            "list_url": _TODO_URL,
            "wait_selector": _TODO_SELECTOR,
            "agency": "TODO_REPLACE_WITH_AGENCY_NAME",
            "row_selector": _TODO_SELECTOR,
            "field_map": {
                "title": _TODO_SELECTOR,
                "solicitation_number": _TODO_SELECTOR,
                "due_date": _TODO_SELECTOR,
                "source_url": _TODO_SELECTOR,
            },
        },
        "notes": (
            "Bonfire portals are per-agency (e.g. {agency}.bonfirehub.com). "
            "Finalize list_url and selectors from a real logged-in session."
        ),
    },
    "opengov": {
        "display_name": "OpenGov Procurement (formerly ProcureNow)",
        "source_type": "authenticated_browser",
        "portal_type": "OpenGov",
        "login_url": "https://procurement.opengov.com/login",
        "config_json": {
            "list_url": _TODO_URL,
            "wait_selector": _TODO_SELECTOR,
            "agency": "TODO_REPLACE_WITH_AGENCY_NAME",
            "row_selector": _TODO_SELECTOR,
            "field_map": {
                "title": _TODO_SELECTOR,
                "solicitation_number": _TODO_SELECTOR,
                "due_date": _TODO_SELECTOR,
                "source_url": _TODO_SELECTOR,
            },
        },
        "notes": (
            "OpenGov Procurement (ProcureNow) renders its list client-side; set "
            "wait_selector so rows have loaded. Finalize selectors from a real "
            "logged-in session."
        ),
    },
    "demandstar": {
        "display_name": "DemandStar",
        "source_type": "authenticated_browser",
        "portal_type": "DemandStar",
        "login_url": "https://network.demandstar.com/login",
        "config_json": {
            "list_url": _TODO_URL,
            "wait_selector": _TODO_SELECTOR,
            "agency": "DemandStar",
            "row_selector": _TODO_SELECTOR,
            "field_map": {
                "title": _TODO_SELECTOR,
                "solicitation_number": _TODO_SELECTOR,
                "due_date": _TODO_SELECTOR,
                "source_url": _TODO_SELECTOR,
            },
        },
        "notes": (
            "DemandStar aggregates many agencies. Finalize list_url and "
            "selectors from a real logged-in session."
        ),
    },
    "generic": {
        "display_name": "Generic authenticated portal",
        "source_type": "authenticated_browser",
        "portal_type": "Generic",
        "login_url": _TODO_URL,
        "config_json": {
            "list_url": _TODO_URL,
            "wait_selector": _TODO_SELECTOR,
            "agency": "TODO_REPLACE_WITH_AGENCY_NAME",
            "row_selector": _TODO_SELECTOR,
            "field_map": {
                "title": _TODO_SELECTOR,
                "solicitation_number": _TODO_SELECTOR,
                "due_date": _TODO_SELECTOR,
                "agency": _TODO_SELECTOR,
                "source_url": _TODO_SELECTOR,
            },
        },
        "notes": (
            "All-placeholder template for any assisted-login portal. Set "
            "login_url and list_url, then finalize row_selector/field_map from a "
            "real logged-in session (or leave them as placeholders to use the "
            "generic table parser fallback)."
        ),
    },
}


def list_templates() -> list[dict]:
    """Return a summary of every template: slug, display_name, source_type."""
    return [
        {
            "slug": slug,
            "display_name": template["display_name"],
            "source_type": template["source_type"],
            "portal_type": template.get("portal_type"),
        }
        for slug, template in PORTAL_TEMPLATES.items()
    ]


def get_template(slug: str) -> dict | None:
    """Return a DEEP COPY of the template for ``slug``, or None if unknown.

    A copy is returned so callers can mutate (e.g. fill placeholders) without
    corrupting the shared catalog.
    """
    template = PORTAL_TEMPLATES.get((slug or "").strip().lower())
    if template is None:
        return None
    return copy.deepcopy(template)
