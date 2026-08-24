#!/usr/bin/env python3
"""Enrich a barcode list with product data from the Go-UPC API.

The script is intentionally restartable and conservative:

* Barcodes are kept as text, including leading zeroes.
* Existing successful results are reused on the next run.
* Network and rate-limit failures are retried with exponential backoff.
* Every input barcode receives a status instead of silently disappearing.
* The API key is read from ``GO_UPC_API_KEY`` and is never stored in code.

Example:
    python scripts/01_go_upc_enrich.py \
        --input examples/barcodes.csv \
        --output output/go_upc_products.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests


API_URL = "https://go-upc.com/api/v1/code/{barcode}"
OUTPUT_COLUMNS = [
    "barcode",
    "name",
    "brand",
    "description",
    "ingredients",
    "image_url",
    "category",
    "code_type",
    "status",
    "http_status",
]
FINAL_STATUSES = {"ok", "not_found", "invalid_barcode"}
BARCODE_COLUMN_ALIASES = {"barcode", "bar code", "ean", "ean13", "ean-13", "gtin", "upc"}


@dataclass(frozen=True)
class LookupSettings:
    timeout_seconds: float
    delay_seconds: float
    max_retries: int
    backoff_seconds: float
    save_raw_json: bool
    raw_json_dir: Path


def value_to_text(value: Any) -> str:
    """Flatten multilingual or nested API values without losing information."""
    if value is None:
        return ""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "; ".join(filter(None, (value_to_text(item) for item in value)))
    if isinstance(value, dict):
        for preferred in ("en", "en_GB", "en_US", "english", "value", "text"):
            if value.get(preferred):
                return value_to_text(value[preferred])
        parts = [value_to_text(item) for item in value.values()]
        return "; ".join(part for part in parts if part)
    return str(value).strip()


def canonical_barcode(value: Any) -> str:
    """Return a digits-only barcode while refusing lossy scientific notation."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none", "null"}:
        return ""
    if re.search(r"[eE][+-]?\d+$", text):
        raise ValueError(
            f"Barcode {text!r} is in scientific notation. Re-export the source "
            "with the barcode column formatted as text; the original digits may be lost."
        )
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    digits = re.sub(r"[\s-]", "", text)
    if not digits.isdigit():
        raise ValueError(f"Barcode {text!r} contains non-digit characters.")
    return digits


def gtin_check_digit_is_valid(barcode: str) -> bool:
    """Validate the check digit for common GTIN lengths."""
    if len(barcode) not in {8, 12, 13, 14} or not barcode.isdigit():
        return False
    total = 0
    for offset, digit in enumerate(reversed(barcode[:-1]), start=1):
        total += int(digit) * (3 if offset % 2 == 1 else 1)
    expected = (10 - total % 10) % 10
    return expected == int(barcode[-1])


def find_barcode_column(columns: Iterable[str], requested: str | None) -> str:
    original = [str(column) for column in columns]
    normalized = {column.strip().casefold(): column for column in original}
    if requested:
        match = normalized.get(requested.strip().casefold())
        if match:
            return match
        raise ValueError(f"Barcode column {requested!r} not found. Available: {original}")
    for alias in BARCODE_COLUMN_ALIASES:
        if alias in normalized:
            return normalized[alias]
    raise ValueError(f"No barcode column found. Available: {original}")


def load_barcodes(path: Path, column_name: str | None) -> tuple[list[str], list[dict[str, str]]]:
    """Load and de-duplicate barcodes, returning invalid input rows separately."""
    if path.suffix.casefold() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            columns = reader.fieldnames or []
    elif path.suffix.casefold() in {".xlsx", ".xls"}:
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError("Excel input requires pandas and openpyxl.") from exc
        frame = pd.read_excel(path, dtype=object).fillna("")
        rows = frame.to_dict(orient="records")
        columns = [str(column) for column in frame.columns]
    else:
        raise ValueError("Input must be .csv, .xlsx, or .xls.")

    barcode_column = find_barcode_column(columns, column_name)
    barcodes: list[str] = []
    invalid: list[dict[str, str]] = []
    seen: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        raw = row.get(barcode_column, "")
        try:
            barcode = canonical_barcode(raw)
        except ValueError as exc:
            invalid.append(empty_result(str(raw), "invalid_barcode", error=str(exc)))
            continue
        if not barcode or barcode in seen:
            continue
        seen.add(barcode)
        barcodes.append(barcode)
    return barcodes, invalid


def empty_result(
    barcode: str,
    status: str,
    *,
    http_status: int | str = "",
    error: str = "",
) -> dict[str, str]:
    row = {column: "" for column in OUTPUT_COLUMNS}
    row["barcode"] = barcode
    row["status"] = status if not error else f"{status}: {error}"
    row["http_status"] = str(http_status)
    return row


def parse_product(barcode: str, payload: dict[str, Any], http_status: int) -> dict[str, str]:
    product = payload.get("product") or {}
    row = empty_result(barcode, "ok", http_status=http_status)
    row.update(
        {
            "barcode": value_to_text(payload.get("code")) or barcode,
            "name": value_to_text(product.get("name")),
            "brand": value_to_text(product.get("brand")),
            "description": value_to_text(product.get("description")),
            "ingredients": value_to_text(product.get("ingredients")),
            "image_url": value_to_text(
                product.get("imageUrl") or product.get("image") or product.get("images")
            ),
            "category": value_to_text(product.get("category")),
            "code_type": value_to_text(payload.get("codeType")),
        }
    )
    useful = [row["name"], row["brand"], row["description"], row["image_url"]]
    if not any(useful):
        row["status"] = "not_found"
    return row


def lookup_barcode(
    session: requests.Session,
    barcode: str,
    api_key: str,
    settings: LookupSettings,
) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    url = API_URL.format(barcode=barcode)
    last_error = "request failed"

    for attempt in range(settings.max_retries + 1):
        try:
            response = session.get(url, headers=headers, timeout=settings.timeout_seconds)
        except requests.RequestException as exc:
            last_error = str(exc)
            response = None

        if response is not None:
            if response.status_code == 404:
                return empty_result(barcode, "not_found", http_status=404)
            if response.status_code == 401:
                return empty_result(
                    barcode,
                    "error",
                    http_status=401,
                    error="unauthorized; check GO_UPC_API_KEY",
                )
            if response.ok:
                try:
                    payload = response.json()
                except ValueError:
                    return empty_result(
                        barcode,
                        "error",
                        http_status=response.status_code,
                        error="response was not valid JSON",
                    )
                if settings.save_raw_json:
                    settings.raw_json_dir.mkdir(parents=True, exist_ok=True)
                    raw_path = settings.raw_json_dir / f"{barcode}.json"
                    raw_path.write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                return parse_product(barcode, payload, response.status_code)

            snippet = re.sub(r"\s+", " ", response.text)[:240]
            last_error = f"HTTP {response.status_code}: {snippet}"
            retryable = response.status_code == 429 or response.status_code >= 500
            if not retryable:
                return empty_result(
                    barcode, "error", http_status=response.status_code, error=last_error
                )

        if attempt < settings.max_retries:
            retry_after = None
            if response is not None:
                retry_after = response.headers.get("Retry-After")
            try:
                wait_seconds = float(retry_after) if retry_after else 0.0
            except ValueError:
                wait_seconds = 0.0
            wait_seconds = max(wait_seconds, settings.backoff_seconds * (2**attempt))
            time.sleep(wait_seconds)

    return empty_result(barcode, "error", error=last_error)


def load_existing_results(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != OUTPUT_COLUMNS:
            raise ValueError(
                f"Existing output schema does not match. Expected {OUTPUT_COLUMNS}; "
                f"found {reader.fieldnames}. Use a new output path or --overwrite."
            )
        return {
            canonical_barcode(row.get("barcode", "")): row
            for row in reader
            if row.get("barcode", "").strip()
        }


def write_row(writer: csv.DictWriter, handle: Any, row: dict[str, str]) -> None:
    writer.writerow({column: row.get(column, "") for column in OUTPUT_COLUMNS})
    handle.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restartable Go-UPC product enrichment for CSV or Excel barcode lists."
    )
    parser.add_argument("--input", required=True, type=Path, help="Input CSV/XLSX file.")
    parser.add_argument("--output", type=Path, default=Path("output/go_upc_products.csv"))
    parser.add_argument("--barcode-column", help="Column name when automatic detection is not enough.")
    parser.add_argument("--limit", type=int, help="Only process the first N unique barcodes.")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.55,
        help="Delay between API calls (default: 0.55s, below Go-UPC's 2 requests/second limit).",
    )
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds.")
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument("--backoff", type=float, default=1.0, help="Initial retry delay.")
    parser.add_argument("--overwrite", action="store_true", help="Discard existing output.")
    parser.add_argument(
        "--keep-errors",
        action="store_true",
        help="Do not retry rows whose previous status starts with 'error'.",
    )
    parser.add_argument(
        "--validate-check-digit",
        action="store_true",
        help="Reject invalid GTIN-8/12/13/14 check digits before using API credits.",
    )
    parser.add_argument("--save-raw-json", action="store_true")
    parser.add_argument("--raw-json-dir", type=Path, default=Path("output/raw_go_upc"))
    parser.add_argument("--summary", type=Path, default=Path("output/go_upc_summary.json"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    api_key = os.environ.get("GO_UPC_API_KEY", "").strip()
    if not api_key:
        print(
            "GO_UPC_API_KEY is not set. See .env.example and README.md.",
            file=sys.stderr,
        )
        return 2
    if not args.input.exists():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        return 2

    try:
        barcodes, invalid_rows = load_barcodes(args.input, args.barcode_column)
    except (ValueError, RuntimeError) as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2

    if args.limit is not None:
        if args.limit < 1:
            print("--limit must be greater than zero.", file=sys.stderr)
            return 2
        barcodes = barcodes[: args.limit]

    if args.validate_check_digit:
        valid: list[str] = []
        for barcode in barcodes:
            if gtin_check_digit_is_valid(barcode):
                valid.append(barcode)
            else:
                invalid_rows.append(
                    empty_result(barcode, "invalid_barcode", error="GTIN check digit failed")
                )
        barcodes = valid

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    existing = {} if args.overwrite else load_existing_results(args.output)
    completed = {
        barcode
        for barcode, row in existing.items()
        if row.get("status") in FINAL_STATUSES
        or (args.keep_errors and row.get("status", "").startswith("error"))
    }
    pending = [barcode for barcode in barcodes if barcode not in completed]

    mode = "w" if args.overwrite or not args.output.exists() else "a"
    settings = LookupSettings(
        timeout_seconds=args.timeout,
        delay_seconds=args.delay,
        max_retries=args.max_retries,
        backoff_seconds=args.backoff,
        save_raw_json=args.save_raw_json,
        raw_json_dir=args.raw_json_dir,
    )

    counts = {"ok": 0, "not_found": 0, "invalid_barcode": 0, "error": 0}
    with args.output.open(mode, encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        if mode == "w":
            writer.writeheader()
            for row in invalid_rows:
                write_row(writer, handle, row)
                counts["invalid_barcode"] += 1

        with requests.Session() as session:
            for index, barcode in enumerate(pending, start=1):
                row = lookup_barcode(session, barcode, api_key, settings)
                write_row(writer, handle, row)
                status_group = row["status"].split(":", 1)[0]
                counts[status_group if status_group in counts else "error"] += 1
                preview = row["name"][:58]
                print(f"[{index:>5}/{len(pending)}] {status_group:<15} {barcode:<14} {preview}")
                if index < len(pending):
                    time.sleep(max(0.0, settings.delay_seconds))

    summary = {
        "input": str(args.input.resolve()),
        "output": str(args.output.resolve()),
        "unique_input_barcodes": len(barcodes),
        "already_completed": len(completed.intersection(barcodes)),
        "processed_this_run": len(pending),
        "invalid_input_rows": len(invalid_rows),
        "this_run_status_counts": counts,
    }
    args.summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
