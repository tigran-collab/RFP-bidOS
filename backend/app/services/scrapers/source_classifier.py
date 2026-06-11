from bs4 import BeautifulSoup

from app.services.scrapers.extraction_utils import extract_document_urls


def classify_source(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if _has_procurement_table(tables):
        return "table_listing"

    document_urls = extract_document_urls(html, base_url)
    if len(document_urls) >= 3:
        return "document_listing"

    links = soup.find_all("a", href=True)
    portal_terms = ("bid", "rfp", "solicitation", "procurement", "vendor", "project")
    portal_link_count = 0
    for link in links:
        text = f"{link.get_text(' ', strip=True)} {link.get('href')}".lower()
        if any(term in text for term in portal_terms):
            portal_link_count += 1

    if portal_link_count >= 3:
        return "portal_listing"
    if soup.find("html"):
        return "generic_html"
    return "unknown"


def _has_procurement_table(tables) -> bool:
    columns = (
        "title",
        "bid title",
        "project name",
        "solicitation",
        "bid number",
        "rfp number",
        "status",
        "due date",
        "closing date",
        "deadline",
        "department",
        "agency",
        "category",
        "description",
    )
    for table in tables:
        header_text = " ".join(
            cell.get_text(" ", strip=True).lower()
            for cell in table.find_all(["th", "td"], limit=12)
        )
        if any(column in header_text for column in columns):
            return True
    return False
