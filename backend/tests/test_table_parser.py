"""Tests for the HTML table scraper (scrapers/table_parser.py).

Offline -- parses static HTML only. Pins down two bugs: a <td>-based header row
being emitted as a bogus opportunity, and substring column matching mis-mapping
the title/agency columns.
"""

from app.services.scrapers.table_parser import parse_tables

BASE_URL = "https://example.gov/bids"


def test_td_header_row_not_emitted_and_columns_mapped():
    # Header cells use <td> (not <th>). The header row must be skipped, and the
    # single data row must map title/solicitation/due from the right columns --
    # note "Agency Name" must NOT be picked as the title even though TITLE
    # columns include "name".
    html = """
    <table>
      <tr>
        <td>Agency Name</td>
        <td>Bid Title</td>
        <td>Solicitation Number</td>
        <td>Due Date</td>
      </tr>
      <tr>
        <td>City of Springfield</td>
        <td>Unarmed Security Guard Services</td>
        <td>RFP-2026-07</td>
        <td>07/15/2026</td>
      </tr>
    </table>
    """
    results = parse_tables(html, BASE_URL)

    assert len(results) == 1
    bid = results[0]
    assert bid.title == "Unarmed Security Guard Services"
    assert bid.agency == "City of Springfield"
    assert bid.solicitation_number == "RFP-2026-07"
    assert bid.due_date is not None
    assert bid.due_date.year == 2026 and bid.due_date.month == 7 and bid.due_date.day == 15


def test_th_header_row_still_works():
    html = """
    <table>
      <tr>
        <th>Bid Title</th>
        <th>Solicitation Number</th>
        <th>Due Date</th>
      </tr>
      <tr>
        <td>Mobile Patrol Services</td>
        <td>IFB-2026-12</td>
        <td>08/01/2026</td>
      </tr>
    </table>
    """
    results = parse_tables(html, BASE_URL)

    assert len(results) == 1
    assert results[0].title == "Mobile Patrol Services"
    assert results[0].solicitation_number == "IFB-2026-12"
