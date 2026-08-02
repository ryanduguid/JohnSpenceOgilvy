"""Export a Xero Trial Balance to a tidy, Power BI-ready CSV.

Usage:
    python export_tb.py --date 2026-06-30
    python export_tb.py --date 2026-06-30 --tenant "Demo Company" --out tb.csv

Output: one row per account —
    ReportDate, Tenant, Section, AccountID, AccountName, AccountCode,
    Debit, Credit, YTDDebit, YTDCredit

Column semantics per Xero's report: Debit/Credit are the CURRENT MONTH's
movement up to the report date; YTDDebit/YTDCredit are the cumulative as-at
balances (the pair an accountant means by "trial balance"). AccountID is the
account GUID — the stable join key.

The balance check covers both pairs (movement and YTD) and runs before
anything is written; an unbalanced report (truncated or misparsed) writes
no file and exits non-zero.
"""

import argparse
import csv
import os
import re
import sys
import tempfile
from datetime import date

from dotenv import load_dotenv

from xero_client import api_get, get_connections

REPORT_URL = "https://api.xero.com/api.xro/2.0/Reports/TrialBalance"

# "Business Bank Account (090)" -> name + code
ACCOUNT_PATTERN = re.compile(r"^(?P<name>.*?)\s*\((?P<code>[^()]+)\)\s*$")


def flatten_report(report: dict) -> tuple[list[str], list[dict]]:
    """Walk the nested Rows structure into flat account rows.

    Xero reports arrive as: Rows[] where RowType is Header (column titles),
    Section (Title + nested Rows), or Row/SummaryRow. Cell order follows the
    Header titles. SummaryRow (section totals) is skipped — totals are
    recomputed, not trusted.
    """
    column_titles: list[str] = []
    flat: list[dict] = []

    def cell_values(row: dict) -> list[str]:
        return [c.get("Value", "") for c in row.get("Cells", [])]

    def account_id(row: dict) -> str:
        # Every data cell carries Attributes: [{"Value": "<account guid>",
        # "Id": "account"}] — the stable join key; codes and names change.
        cells = row.get("Cells", [])
        if not cells:
            return ""
        for attr in cells[0].get("Attributes", []):
            if attr.get("Id") == "account":
                return attr.get("Value", "")
        return ""

    for top in report.get("Rows", []):
        row_type = top.get("RowType")
        if row_type == "Header":
            column_titles = cell_values(top)
        elif row_type == "Section":
            section = top.get("Title", "")
            for row in top.get("Rows", []):
                if row.get("RowType") != "Row":
                    continue  # skip SummaryRow
                values = cell_values(row)
                record = {}
                # strict: a row/header length mismatch means the API shape
                # changed — fail loudly instead of exporting silent zeros
                for title, value in zip(column_titles, values, strict=True):
                    record[title] = value
                # synthetic keys set last so they win any header collision
                record["Section"] = section
                record["AccountID"] = account_id(row)
                flat.append(record)

    return column_titles, flat


def to_number(value: str) -> float:
    if value is None or str(value).strip() == "":
        return 0.0
    return float(value)


def iso_date(value: str) -> str:
    """argparse type= for --date: reject anything but YYYY-MM-DD up front,
    before an AU-habit 30/06/2026 wastes the API call and then breaks the
    output filename with slashes."""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f'"{value}" is not YYYY-MM-DD (e.g. 2026-06-30). Note the order: '
            "ISO year-month-day, not the AU DD/MM/YYYY."
        ) from None


def excel_safe(value: str) -> str:
    """CSV formula-injection guard, covering OWASP's trigger set: = + - @
    plus tab, CR and LF. Xero account and organisation names are free text
    anyone in the org can edit. A leading apostrophe forces Excel to read
    the cell as text; everything else passes through untouched."""
    return "'" + value if str(value)[:1] in ("=", "+", "-", "@", "\t", "\r", "\n") else value


def main() -> None:
    load_dotenv()
    client_id = os.environ.get("XERO_CLIENT_ID")
    client_secret = os.environ.get("XERO_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.exit("Set XERO_CLIENT_ID and XERO_CLIENT_SECRET in .env (see .env.example).")

    parser = argparse.ArgumentParser(description="Export a Xero Trial Balance to CSV.")
    parser.add_argument("--date", type=iso_date, default=date.today().isoformat(), help="Report date YYYY-MM-DD")
    parser.add_argument("--tenant", default=None, help="Tenant name substring (required when multiple orgs are connected)")
    parser.add_argument("--out", default=None, help="Output CSV path")
    parser.add_argument("--payments-only", action="store_true", help="Cash-basis report")
    args = parser.parse_args()

    # api_get looks the access token up fresh per call — no token is held
    # here, so a mid-run refresh can never leave a later call using the
    # stale one; the creds also cover the surprise-401 forced refresh
    creds = (client_id, client_secret)

    connections = get_connections(creds)
    if not connections:
        sys.exit("No Xero organisations authorised for this app — run auth.py again.")
    if args.tenant:
        matches = [c for c in connections if args.tenant.lower() in c["tenantName"].lower()]
        if not matches:
            names = ", ".join(c["tenantName"] for c in connections)
            sys.exit(f'No tenant matching "{args.tenant}". Connected: {names}')
        if len(matches) > 1:
            names = ", ".join(c["tenantName"] for c in matches)
            sys.exit(f'"{args.tenant}" matches more than one organisation ({names}) — narrow it.')
        tenant = matches[0]
    else:
        if len(connections) > 1:
            names = ", ".join(c["tenantName"] for c in connections)
            sys.exit(f"More than one organisation connected ({names}) — pick one with --tenant.")
        tenant = connections[0]
    print(f"Tenant: {tenant['tenantName']}")

    params = {"date": args.date}
    if args.payments_only:
        params["paymentsOnly"] = "true"

    payload = api_get(REPORT_URL, creds, tenant_id=tenant["tenantId"], params=params)
    reports = payload.get("Reports", [])
    if not reports:
        sys.exit("Empty Reports payload — check the date parameter and API scopes.")

    column_titles, rows = flatten_report(reports[0])
    if not rows:
        sys.exit("Report contained no account rows — nothing to export.")

    # The strict zip in flatten_report only catches a cell-COUNT change; a
    # retitled column (count unchanged) would slip through and silently zero
    # every value via record.get(). Guard the titles themselves.
    missing = {"Account", "Debit", "Credit", "YTD Debit", "YTD Credit"} - set(column_titles)
    if missing:
        sys.exit(f"Unexpected report columns — missing {sorted(missing)}. Has the API shape changed?")

    safe_tenant = re.sub(r"[^A-Za-z0-9._-]+", "-", tenant["tenantName"]).strip("-").lower()
    if not safe_tenant:  # all-symbol org names sanitise to nothing
        safe_tenant = tenant["tenantId"][:8]
    basis = "cash" if args.payments_only else "accrual"
    # {entity}-{report}-{period-end}-{basis}: matches the file convention in
    # the sibling repos, and keeps cash vs accrual runs from overwriting
    # each other
    out_path = args.out or f"{safe_tenant}-tb-{args.date}-{basis}.csv"

    fieldnames = [
        "ReportDate", "Tenant", "Section", "AccountID", "AccountName", "AccountCode",
        "Debit", "Credit", "YTDDebit", "YTDCredit",
    ]

    # Build everything in memory and balance-check BEFORE any file exists —
    # a scheduled Power BI refresh reads the path, not the exit code, so an
    # unbalanced export must never reach disk.
    out_rows = []
    total_debit = total_credit = 0.0
    total_ytd_debit = total_ytd_credit = 0.0
    for record in rows:
        account_raw = record.get("Account", "")
        match = ACCOUNT_PATTERN.match(account_raw)
        name = match.group("name") if match else account_raw
        code = match.group("code") if match else ""

        debit = to_number(record.get("Debit"))
        credit = to_number(record.get("Credit"))
        ytd_debit = to_number(record.get("YTD Debit"))
        ytd_credit = to_number(record.get("YTD Credit"))
        total_debit += debit
        total_credit += credit
        total_ytd_debit += ytd_debit
        total_ytd_credit += ytd_credit

        out_rows.append(
            {
                "ReportDate": args.date,
                "Tenant": excel_safe(tenant["tenantName"]),
                "Section": excel_safe(record.get("Section", "")),
                "AccountID": record.get("AccountID", ""),
                "AccountName": excel_safe(name),
                "AccountCode": excel_safe(code),
                "Debit": debit,
                "Credit": credit,
                "YTDDebit": ytd_debit,
                "YTDCredit": ytd_credit,
            }
        )

    # Both pairs must balance — the movement columns AND the YTD as-at
    # balances (the pair the README tells users to slice). Either one out
    # means the report is truncated or misparsed.
    unbalanced = False
    for label, debits, credits in (
        ("movement", total_debit, total_credit),
        ("YTD", total_ytd_debit, total_ytd_credit),
    ):
        diff = round(debits - credits, 2)
        if diff != 0:
            print(f"WARNING: {label} debits {debits:,.2f} != credits {credits:,.2f} (diff {diff:,.2f})")
            unbalanced = True
    if unbalanced:
        print("Nothing written — report likely truncated or misparsed.")
        sys.exit(1)

    # Atomic write (temp file + replace), mirroring save_tokens(): a crash
    # or disk-full mid-write must never leave a truncated CSV at the path a
    # scheduled Power BI refresh reads.
    out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=out_dir, suffix=".csv.tmp")
    try:
        # utf-8-sig: the BOM is what makes Excel's double-click open decode
        # non-ASCII names correctly; Power BI and pandas strip it anyway.
        with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(out_rows)
        os.replace(tmp_path, out_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    print(f"Wrote {len(out_rows)} accounts to {out_path}")
    print(f"Balance check OK: movement debits = credits = {total_debit:,.2f}; YTD = {total_ytd_debit:,.2f}")


if __name__ == "__main__":
    main()
