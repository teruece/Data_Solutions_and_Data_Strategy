"""Load an authoritative daily retail CSV batch and report current market totals."""

import argparse
import csv
import hashlib
import io
import re
import sqlite3
import sys
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import NamedTuple, TextIO


SOURCE_HEADER = ["sale_date", "market_code", "sku", "units", "net_sales_gbp"]

CREATE_FACT = """
CREATE TABLE IF NOT EXISTS fact_sales_daily (
    sale_date TEXT NOT NULL,
    market_code TEXT NOT NULL,
    sku TEXT NOT NULL,
    units INTEGER NOT NULL CHECK (units BETWEEN 0 AND 999999999),
    net_sales_pence INTEGER NOT NULL CHECK (net_sales_pence BETWEEN 0 AND 99999999999999),
    PRIMARY KEY (sale_date, market_code, sku)
) STRICT
"""

CREATE_LEDGER = """
CREATE TABLE IF NOT EXISTS batch_ledger (
    batch_id TEXT PRIMARY KEY,
    payload_sha256 TEXT NOT NULL,
    row_count INTEGER NOT NULL CHECK (row_count > 0),
    loaded_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT
"""

UPSERT_FACT = """
INSERT INTO fact_sales_daily (sale_date, market_code, sku, units, net_sales_pence)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT (sale_date, market_code, sku) DO UPDATE SET
    units = excluded.units,
    net_sales_pence = excluded.net_sales_pence
"""

MARKET_TOTALS = """
SELECT market_code, COUNT(*) AS rows, SUM(units), SUM(net_sales_pence)
FROM fact_sales_daily
GROUP BY market_code
ORDER BY market_code
"""


class BatchError(ValueError):
    """An input batch violates the source contract."""


class Sale(NamedTuple):
    sale_date: str
    market_code: str
    sku: str
    units: int
    net_sales_pence: int


def parse_sale(fields: list[str], line: int) -> Sale:
    if len(fields) != len(SOURCE_HEADER):
        raise BatchError(f"line {line}: expected {len(SOURCE_HEADER)} fields")

    sale_date, market, sku, units, sales_gbp = fields
    try:
        parsed_date = date.fromisoformat(sale_date)
        if parsed_date.isoformat() != sale_date:
            raise ValueError
    except ValueError:
        raise BatchError(f"line {line}: sale_date must be a valid YYYY-MM-DD date") from None

    if re.fullmatch(r"[A-Z]{3}", market) is None:
        raise BatchError(f"line {line}: market_code must contain 3 uppercase letters")
    if re.fullmatch(r"[A-Z0-9][A-Z0-9-]{0,23}", sku) is None:
        raise BatchError(f"line {line}: invalid sku (use uppercase letters, digits or hyphens)")
    if re.fullmatch(r"[0-9]{1,9}", units) is None:
        raise BatchError(f"line {line}: units must contain 1 to 9 digits")
    if re.fullmatch(r"[0-9]{1,12}\.[0-9]{2}", sales_gbp) is None:
        raise BatchError(
            f"line {line}: net_sales_gbp must use 1 to 12 whole digits and two decimal places"
        )

    pounds, pence = sales_gbp.split(".")
    return Sale(sale_date, market, sku, int(units), int(pounds) * 100 + int(pence))


def parse_batch(payload: bytes) -> list[Sale]:
    try:
        csv_text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise BatchError("CSV must be UTF-8 encoded") from None

    reader = csv.reader(io.StringIO(csv_text, newline=""), strict=True)
    seen_lines = {}
    sales = []
    try:
        if next(reader, None) != SOURCE_HEADER:
            raise BatchError(f"invalid CSV header: expected {','.join(SOURCE_HEADER)}")

        for fields in reader:
            line = reader.line_num
            sale = parse_sale(fields, line)
            key = (sale.sale_date, sale.market_code, sale.sku)
            if key in seen_lines:
                first_line = seen_lines[key]
                raise BatchError(
                    f"line {line}: duplicate business key {key} (first on line {first_line})"
                )
            seen_lines[key] = line
            sales.append(sale)
    except csv.Error as error:
        raise BatchError(f"line {reader.line_num}: malformed CSV: {error}") from error

    if not sales:
        raise BatchError("batch has no data rows")
    return sales


def load_batch(db_path: Path, batch_id: str, source_path: Path) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", batch_id) is None:
        raise BatchError("batch-id must be 1 to 64 letters, digits, periods, underscores or hyphens")

    payload = source_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path, timeout=10, isolation_level=None)) as connection:
        with connection:
            # Reserve the single writer before checking the ledger or changing Gold.
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(CREATE_FACT)
            connection.execute(CREATE_LEDGER)
            previous = connection.execute(
                "SELECT payload_sha256, row_count FROM batch_ledger WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            if previous is not None:
                previous_digest, row_count = previous
                if previous_digest != digest:
                    raise BatchError(f"batch ID '{batch_id}' already has a different payload")
                return f"Replay '{batch_id}': no changes ({row_count} previously accepted rows)."

            sales = parse_batch(payload)
            connection.executemany(UPSERT_FACT, sales)
            connection.execute(
                "INSERT INTO batch_ledger (batch_id, payload_sha256, row_count) VALUES (?, ?, ?)",
                (batch_id, digest, len(sales)),
            )
    return f"Loaded '{batch_id}': {len(sales)} accepted rows."


def report_market_totals(db_path: Path, output: TextIO) -> None:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        results = connection.execute(MARKET_TOTALS).fetchall()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("market_code", "rows", "units", "net_sales_gbp"))
    for market, rows, units, total_pence in results:
        pounds, pence = divmod(total_pence, 100)
        writer.writerow((market, rows, units, f"{pounds}.{pence:02d}"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    load = commands.add_parser("load", help="validate and load a CSV batch")
    load.add_argument("--db", required=True, type=Path)
    load.add_argument("--batch-id", required=True)
    load.add_argument("--csv", required=True, type=Path)

    report = commands.add_parser("report", help="write current market totals as CSV")
    report.add_argument("--db", required=True, type=Path)

    args = parser.parse_args()
    if sqlite3.sqlite_version_info < (3, 37, 0):
        print("Error: SQLite 3.37 or newer is required.", file=sys.stderr)
        return 1

    try:
        if args.command == "load":
            print(load_batch(args.db, args.batch_id, args.csv))
        else:
            report_market_totals(args.db, sys.stdout)
    except (BatchError, OSError, sqlite3.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
