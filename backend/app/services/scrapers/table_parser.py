from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.services.scrapers.base import ScraperResult
from app.services.scrapers.extraction_utils import (
    confidence_from_text,
    extract_contract_type,
    extract_document_urls,
    extract_due_date,
    extract_estimated_value,
    extract_location,
    extract_pre_bid_date,
    extract_q_and_a_deadline,
    extract_service_type,
    extract_solicitation_number,
    normalize_space,
)

TITLE_COLUMNS = ("title", "bid title", "project name", "description", "name")
SOLICITATION_COLUMNS = ("solicitation", "bid number", "rfp number", "rfq number", "ifb number", "number")
AGENCY_COLUMNS = ("department", "agency", "owner")
DUE_COLUMNS = ("due date", "closing date", "deadline", "close date", "bids due")
CATEGORY_COLUMNS = ("category", "type")


def parse_tables(html: str, base_url: str, portal_url: str | None = None) -> list[ScraperResult]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[ScraperResult] = []
    for table in soup.find_all("table"):
        headers = _headers_for_table(table)
        if not headers:
            continue

        rows = table.find_all("tr")
        # The first row supplied the headers; skip it so a <td>-based header row
        # is not emitted as a bogus opportunity.
        for row in rows[1:]:
            cells = row.find_all("td")
            if not cells or len(cells) < 2:
                continue

            values = {
                headers[index]: normalize_space(cell.get_text(" ", strip=True))
                for index, cell in enumerate(cells[: len(headers)])
            }
            row_text = normalize_space(" ".join(values.values()))
            if not _looks_like_opportunity_row(values, row_text):
                continue

            detail_url = _first_anchor_url(cells, base_url)
            documents = extract_document_urls(str(row), base_url)
            title = _first_value(values, TITLE_COLUMNS) or row_text[:120] or detail_url
            solicitation = _first_value(values, SOLICITATION_COLUMNS) or extract_solicitation_number(row_text)
            due_date = _first_date_value(values, DUE_COLUMNS) or extract_due_date(row_text)
            agency = _first_value(values, AGENCY_COLUMNS)
            service_type = extract_service_type(row_text) or _first_value(values, CATEGORY_COLUMNS)

            results.append(
                ScraperResult(
                    title=title or "Untitled opportunity",
                    extraction_method="table_row",
                    agency=agency,
                    solicitation_number=solicitation,
                    source_url=detail_url or base_url,
                    detail_url=detail_url,
                    portal_url=portal_url or base_url,
                    due_date=due_date,
                    pre_bid_date=extract_pre_bid_date(row_text),
                    q_and_a_deadline=extract_q_and_a_deadline(row_text),
                    service_type=service_type,
                    contract_type=extract_contract_type(row_text),
                    estimated_value=extract_estimated_value(row_text),
                    location=extract_location(row_text),
                    description=row_text,
                    document_urls=documents,
                    raw_text=row_text,
                    confidence_score=confidence_from_text(title or "", row_text, documents),
                )
            )
    return results


def _headers_for_table(table) -> list[str]:
    header_row = table.find("tr")
    if header_row is None:
        return []
    header_cells = header_row.find_all("th")
    if not header_cells:
        header_cells = header_row.find_all("td")
    headers = [normalize_space(cell.get_text(" ", strip=True)).lower() for cell in header_cells]
    if len(headers) < 2:
        return []
    known_terms = TITLE_COLUMNS + SOLICITATION_COLUMNS + AGENCY_COLUMNS + DUE_COLUMNS + CATEGORY_COLUMNS
    if not any(any(term in header for term in known_terms) for header in headers):
        return []
    return headers


def _looks_like_opportunity_row(values: dict[str, str], row_text: str) -> bool:
    lowered = row_text.lower()
    if any(token in lowered for token in ("rfp", "rfq", "ifb", "itb", "bid", "solicitation", "proposal")):
        return True
    return any(_first_value(values, columns) for columns in (TITLE_COLUMNS, SOLICITATION_COLUMNS, DUE_COLUMNS))


def _first_value(values: dict[str, str], columns: tuple[str, ...]) -> str | None:
    # Prefer an exact header match before falling back to substring matching,
    # and try the expected tokens in priority order (most specific first) so a
    # generic token like "name" cannot pre-empt a more specific "agency name".
    for expected in columns:
        for column, value in values.items():
            if value and column == expected:
                return value
    for expected in columns:
        for column, value in values.items():
            if value and expected in column:
                return value
    return None


def _first_date_value(values: dict[str, str], columns: tuple[str, ...]):
    value = _first_value(values, columns)
    if not value:
        return None
    return extract_due_date(f"due date: {value}")


def _first_anchor_url(cells, base_url: str) -> str | None:
    for cell in cells:
        anchor = cell.find("a", href=True)
        if anchor:
            return urljoin(base_url, str(anchor.get("href") or "").strip())
    return None
