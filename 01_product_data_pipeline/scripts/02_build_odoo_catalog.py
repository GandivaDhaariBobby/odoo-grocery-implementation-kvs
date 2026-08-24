#!/usr/bin/env python3
"""Clean multilingual product data, classify it, and assign stable Odoo IDs.

This script does not connect to Odoo. It creates reviewable files for a human
approval step before any live import or Technical > External Identifiers work.

Classification order:
    1. Exact manual override by barcode, External ID, or product name.
    2. High-priority business/brand and product-form rules.
    3. Functional grocery rules loaded from JSON.
    4. Existing valid category as a conservative fallback.
    5. Unknown + review required when no safe decision is available.

Example:
    python scripts/02_build_odoo_catalog.py \
        --products source_products.xlsx \
        --enrichment output/go_upc_products.csv \
        --taxonomy KVS_CATEGORIES.xlsx \
        --rules config/classification_rules.json \
        --mappings config/channel_mappings.json \
        --output-dir output/catalog
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

try:
    from unidecode import unidecode
except ImportError:  # The fallback still handles Latin accents.
    unidecode = None


CANONICAL_COLUMN_ALIASES = {
    "Barcode": {"barcode", "bar code", "ean", "ean13", "ean-13", "gtin", "upc"},
    "Name": {"name", "product name", "product"},
    "External ID": {"external id", "external_id", "internal reference", "reference", "sku"},
    "Main_Category": {"main_category", "main category", "department"},
    "Product Category": {"product category", "inventory category", "subcategory", "sub category"},
    "Point of Sale Category": {"point of sale category", "pos category"},
    "Website Product Category": {"website product category", "website category"},
    "eCommerce Description": {"ecommerce description", "description", "sales description"},
    "Image URL": {"image url", "image_url", "image"},
    "Brand": {"brand", "manufacturer"},
    "Ingredients": {"ingredients", "ingredient"},
}

PACK_PATTERN = re.compile(
    r"(?<!\w)(\d{1,3})\s*[xX*]\s*(\d+(?:[.,]\d+)?)\s*"
    r"(g|gm|gms|gr|grams?|kg|kgs?|ml|mls?|l|ltr|liters?|litres?|cl|oz|lb|lbs)\b",
    re.IGNORECASE,
)
QTY_PATTERN = re.compile(
    r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*"
    r"(g|gm|gms|gr|grams?|kg|kgs?|ml|mls?|l|ltr|liters?|litres?|cl|oz|lb|lbs)\b",
    re.IGNORECASE,
)
REVERSE_QTY_PATTERN = re.compile(
    r"\b(g|gm|gms|gr|grams?|kg|kgs?|ml|mls?|l|ltr|liters?|litres?)\s*[:.]?\s*"
    r"(\d+(?:[.,]\d+)?)\b",
    re.IGNORECASE,
)
UNIT_NORMALIZE = {
    "g": "g", "gm": "g", "gms": "g", "gr": "g", "gram": "g", "grams": "g",
    "kg": "kg", "kgs": "kg", "ml": "ml", "mls": "ml", "l": "L", "ltr": "L",
    "liter": "L", "liters": "L", "litre": "L", "litres": "L", "cl": "cl",
    "oz": "oz", "lb": "lb", "lbs": "lb",
}
FLUFF_PHRASES = (
    "family pack", "value pack", "mega pack", "jumbo pack", "economy pack",
    "multi pack", "mini pack", "family size", "large size", "special pack",
    "new improved", "newly launched", "limited edition", "best quality",
    "premium quality", "high quality", "export quality", "free inside", "with free",
)
KNOWN_ACRONYMS = {
    "aachi": "Aachi", "dabur": "Dabur", "haldirams": "Haldiram's", "mtr": "MTR",
    "mdh": "MDH", "trs": "TRS", "okf": "OKF", "ufc": "UFC", "gits": "Gits",
    "shan": "Shan", "pri ya": "Priya",
}


@dataclass(frozen=True)
class Taxonomy:
    code_by_main: dict[str, str]
    main_by_sub: dict[str, str]
    rank_by_pair: dict[tuple[str, str], int]


@dataclass(frozen=True)
class Decision:
    main_category: str
    product_category: str
    confidence: float
    reason: str
    rule_id: str


def clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\ufffd", " ")).strip()


def match_text(value: Any) -> str:
    """Normalize multilingual text for matching while preserving source text in output."""
    text = clean_text(value)
    text = unicodedata.normalize("NFKC", text).casefold()
    text = unidecode(text) if unidecode else "".join(
        char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9&+]+", " ", text).strip()


def term_matches(text: str, term: str) -> bool:
    normalized = match_text(term)
    if not normalized:
        return False
    if " " in normalized:
        return normalized in text
    return re.search(rf"\b{re.escape(normalized)}\b", text) is not None


def canonical_barcode(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    if re.search(r"[eE][+-]?\d+$", text):
        return ""  # A lossy barcode must not be guessed.
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    digits = re.sub(r"[\s-]", "", text)
    return digits if digits.isdigit() else ""


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.casefold() == ".csv":
        frame = pd.read_csv(path, dtype=object, encoding="utf-8-sig")
        return frame.where(frame.notna(), "")
    if path.suffix.casefold() in {".xlsx", ".xls"}:
        frame = pd.read_excel(path, dtype=object)
        return frame.where(frame.notna(), "")
    raise ValueError(f"Unsupported file type: {path.suffix}")


def canonicalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = {match_text(column): str(column) for column in frame.columns}
    rename: dict[str, str] = {}
    for canonical, aliases in CANONICAL_COLUMN_ALIASES.items():
        for alias in aliases | {canonical}:
            source = normalized.get(match_text(alias))
            if source:
                rename[source] = canonical
                break
    result = frame.rename(columns=rename).copy()
    required = ["Barcode", "Name", "External ID", "Main_Category", "Product Category"]
    missing = [column for column in required if column not in result.columns]
    if missing:
        raise ValueError(f"Missing required product columns: {missing}")
    return result


def find_header_row(raw: pd.DataFrame, required: set[str]) -> int:
    for index, row in raw.iterrows():
        values = {match_text(value) for value in row.tolist()}
        if {match_text(value) for value in required}.issubset(values):
            return int(index)
    raise ValueError(f"Could not locate taxonomy header containing {sorted(required)}")


def parse_taxonomy(path: Path, sheet_name: str) -> Taxonomy:
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None, dtype=object)
    raw = raw.where(raw.notna(), "")
    header_index = find_header_row(raw, {"Main Category", "Code", "Sub Category"})
    headers = [clean_text(value) for value in raw.iloc[header_index].tolist()]
    rows = raw.iloc[header_index + 1 :].copy()
    rows.columns = headers

    rank_column = next(
        (column for column in rows.columns if "rank" in match_text(column)), None
    )
    if rank_column is None:
        raise ValueError("Taxonomy needs a category rank column.")
    rows[["Main Category", "Code"]] = rows[["Main Category", "Code"]].replace("", pd.NA).ffill()

    code_by_main: dict[str, str] = {}
    main_by_sub: dict[str, str] = {}
    rank_by_pair: dict[tuple[str, str], int] = {}
    for _, row in rows.iterrows():
        main = clean_text(row.get("Main Category"))
        code = clean_text(row.get("Code")).upper()
        sub = clean_text(row.get("Sub Category"))
        rank_text = clean_text(row.get(rank_column))
        if not main or not code or not sub or not rank_text:
            continue
        rank = int(float(rank_text))
        code_by_main[main] = code
        main_by_sub[sub] = main
        rank_by_pair[(main, sub)] = rank
    if not rank_by_pair:
        raise ValueError("No valid inventory categories were found in the taxonomy workbook.")
    return Taxonomy(code_by_main, main_by_sub, rank_by_pair)


def normalize_quantity(value: str) -> str:
    value = value.replace(",", ".")
    return value[:-2] if value.endswith(".0") else value


def extract_size(*texts: str) -> tuple[str, str | None]:
    for index, text in enumerate(texts):
        if not text:
            continue
        pack = PACK_PATTERN.search(text)
        if pack:
            count, quantity, unit = pack.groups()
            size = f"{count}x{normalize_quantity(quantity)}{UNIT_NORMALIZE[unit.casefold()]}"
            return size, pack.group(0) if index == 0 else None
        quantity_match = QTY_PATTERN.search(text)
        if quantity_match:
            quantity, unit = quantity_match.groups()
            size = f"{normalize_quantity(quantity)}{UNIT_NORMALIZE[unit.casefold()]}"
            return size, quantity_match.group(0) if index == 0 else None
    return "", None


def smart_title(text: str) -> str:
    """Improve casing without damaging common brand acronyms."""
    tokens = re.split(r"(\s+)", text.strip())
    output: list[str] = []
    for token in tokens:
        key = match_text(token)
        if token.isspace():
            output.append(token)
        elif key in KNOWN_ACRONYMS:
            output.append(KNOWN_ACRONYMS[key])
        elif token.isupper() and 2 <= len(token) <= 5:
            output.append(token)
        elif any(char.isdigit() for char in token):
            output.append(token)
        else:
            output.append(token[:1].upper() + token[1:].lower())
    return "".join(output)


def clean_product_name(name: str, brand: str, description: str = "", ingredients: str = "") -> str:
    """Build a consistent ``Brand Product Size`` display name."""
    name = clean_text(name)
    brand = clean_text(brand)
    description = clean_text(description)
    ingredients = clean_text(ingredients)
    if match_text(brand) in {"object object", "none", "null", "n a"}:
        brand = ""

    def reverse_quantity(match: re.Match[str]) -> str:
        unit, quantity = match.groups()
        return f"{normalize_quantity(quantity)}{UNIT_NORMALIZE[unit.casefold()]}"

    name = REVERSE_QTY_PATTERN.sub(reverse_quantity, name)
    size, size_in_name = extract_size(name, description, ingredients)
    core = name.replace(size_in_name, "", 1) if size_in_name else name
    core = re.sub(r"^\[?object object\]?\s*", "", core, flags=re.IGNORECASE)
    if brand:
        core = re.sub(rf"^\s*{re.escape(brand)}\b[\s,:-]*", "", core, flags=re.IGNORECASE)
    for phrase in FLUFF_PHRASES:
        core = re.sub(rf"\b{re.escape(phrase)}\b", " ", core, flags=re.IGNORECASE)
    core = re.sub(r"\s*[-_–—]+\s*", " ", core)
    core = PACK_PATTERN.sub(" ", core)
    core = QTY_PATTERN.sub(" ", core)
    core = re.sub(r"\s+", " ", core).strip(" ,;.-")

    parts = []
    if brand:
        parts.append(smart_title(brand))
    if core and not (brand and match_text(core).startswith(match_text(brand))):
        parts.append(smart_title(core))
    elif core and not parts:
        parts.append(smart_title(core))
    middle = " ".join(parts).strip()
    return f"{middle} {size}".strip() if size else middle


def merge_enrichment(
    products: pd.DataFrame,
    enrichment_path: Path | None,
    replace_names: bool,
) -> tuple[pd.DataFrame, dict[str, int]]:
    result = products.copy()
    for column in ("Brand", "Ingredients", "Image URL", "eCommerce Description"):
        if column not in result.columns:
            result[column] = ""
    stats = {"source_rows": len(result), "enrichment_matches": 0, "names_replaced": 0}
    if enrichment_path is None:
        return result, stats

    enrichment = canonicalize_enrichment(read_table(enrichment_path))
    lookup = {
        canonical_barcode(row["barcode"]): row
        for _, row in enrichment.iterrows()
        if clean_text(row.get("status")) == "ok" and canonical_barcode(row.get("barcode"))
    }
    for index, row in result.iterrows():
        barcode = canonical_barcode(row.get("Barcode"))
        enriched = lookup.get(barcode)
        if enriched is None:
            continue
        stats["enrichment_matches"] += 1
        raw_name = clean_text(enriched.get("name"))
        brand = clean_text(enriched.get("brand"))
        description = clean_text(enriched.get("description"))
        ingredients = clean_text(enriched.get("ingredients"))
        cleaned_name = clean_product_name(raw_name, brand, description, ingredients)
        if cleaned_name and (replace_names or not clean_text(row.get("Name"))):
            result.at[index, "Name"] = cleaned_name
            stats["names_replaced"] += 1
        if brand:
            result.at[index, "Brand"] = brand
        if description and match_text(description) != "no description found":
            result.at[index, "eCommerce Description"] = description
        if ingredients:
            result.at[index, "Ingredients"] = ingredients
        image_url = clean_text(enriched.get("image_url"))
        if image_url:
            result.at[index, "Image URL"] = image_url
        if barcode:
            result.at[index, "Barcode"] = barcode
    return result, stats


def canonicalize_enrichment(frame: pd.DataFrame) -> pd.DataFrame:
    columns = {match_text(column): str(column) for column in frame.columns}
    required = ["barcode", "name", "brand", "description", "ingredients", "image_url", "category", "status"]
    missing = [name for name in required if match_text(name) not in columns]
    if missing:
        raise ValueError(f"Enrichment file is missing columns: {missing}")
    rename = {columns[match_text(name)]: name for name in required}
    return frame.rename(columns=rename).copy()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_overrides(path: Path | None) -> dict[tuple[str, str], dict[str, str]]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    overrides: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        match_type = match_text(row.get("match_type"))
        match_value = clean_text(row.get("match_value"))
        if match_type and match_value:
            key_value = canonical_barcode(match_value) if match_type == "barcode" else match_text(match_value)
            overrides[(match_type, key_value)] = row
    return overrides


def rule_matches(text: str, rule: dict[str, Any]) -> bool:
    include_any = rule.get("include_any", [])
    include_all = rule.get("include_all", [])
    exclude_any = rule.get("exclude_any", [])
    if include_any and not any(term_matches(text, term) for term in include_any):
        return False
    if include_all and not all(term_matches(text, term) for term in include_all):
        return False
    if exclude_any and any(term_matches(text, term) for term in exclude_any):
        return False
    return bool(include_any or include_all)


def classify(
    row: pd.Series,
    rules: list[dict[str, Any]],
    taxonomy: Taxonomy,
    overrides: dict[tuple[str, str], dict[str, str]],
) -> Decision:
    keys = [
        ("barcode", canonical_barcode(row.get("Barcode"))),
        ("external id", match_text(row.get("External ID"))),
        ("name", match_text(row.get("Name"))),
    ]
    for key in keys:
        override = overrides.get(key)
        if override:
            return Decision(
                clean_text(override.get("main_category")),
                clean_text(override.get("product_category")),
                float(override.get("confidence") or 1.0),
                clean_text(override.get("reason")) or "Exact manual override.",
                "manual_override",
            )

    combined = " ".join(
        match_text(row.get(column, ""))
        for column in ("Name", "Brand", "eCommerce Description", "Ingredients")
    )
    for rule in rules:
        if rule_matches(combined, rule):
            return Decision(
                rule["main_category"],
                rule["product_category"],
                float(rule["confidence"]),
                rule["reason"],
                rule["id"],
            )

    old_main = clean_text(row.get("Main_Category"))
    old_sub = clean_text(row.get("Product Category"))
    if taxonomy.rank_by_pair.get((old_main, old_sub)) is not None:
        return Decision(
            old_main,
            old_sub,
            0.86,
            "Kept the existing valid taxonomy value because no stronger rule matched.",
            "existing_valid_category",
        )
    return Decision("Unknown", "Unknown", 0.35, "No safe rule matched.", "unresolved")


def validate_decision(decision: Decision, taxonomy: Taxonomy) -> None:
    if decision.main_category == "Unknown":
        return
    expected_main = taxonomy.main_by_sub.get(decision.product_category)
    if expected_main != decision.main_category:
        raise ValueError(
            f"Rule {decision.rule_id!r} points to invalid pair "
            f"{decision.main_category!r} / {decision.product_category!r}."
        )


def parse_external_id(value: Any) -> tuple[str, int, int] | None:
    match = re.fullmatch(r"([A-Z0-9]+)-(\d{4,})", clean_text(value).upper())
    if not match:
        return None
    number = int(match.group(2))
    return match.group(1), number // 1000, number


def assign_external_ids(
    frame: pd.DataFrame,
    taxonomy: Taxonomy,
) -> tuple[list[str], list[str]]:
    proposed: list[str | None] = []
    reasons: list[str] = []
    used: set[str] = set()
    maximum: defaultdict[tuple[str, int], int] = defaultdict(int)

    for _, row in frame.iterrows():
        main = row["New Main Category"]
        sub = row["New Product Category"]
        old_id = clean_text(row.get("External ID")).upper()
        if main == "Unknown":
            proposed.append(None)
            reasons.append("Unresolved category; no External ID was generated.")
            continue
        code = taxonomy.code_by_main[main]
        rank = taxonomy.rank_by_pair[(main, sub)]
        parsed = parse_external_id(old_id)
        if parsed and parsed[:2] == (code, rank) and old_id not in used:
            proposed.append(old_id)
            reasons.append("Preserved: prefix and rank already match the classified category.")
            used.add(old_id)
            maximum[(code, rank)] = max(maximum[(code, rank)], parsed[2])
        else:
            proposed.append(None)
            reasons.append("Reassigned: old prefix/rank did not match the classified category.")

    for index, row in frame.iterrows():
        if proposed[index] is not None:
            continue
        main = row["New Main Category"]
        sub = row["New Product Category"]
        if main == "Unknown":
            proposed[index] = ""
            continue
        code = taxonomy.code_by_main[main]
        rank = taxonomy.rank_by_pair[(main, sub)]
        number = max(maximum[(code, rank)] + 1, rank * 1000 + 1)
        candidate = f"{code}-{number:04d}"
        while candidate in used:
            number += 1
            candidate = f"{code}-{number:04d}"
        proposed[index] = candidate
        used.add(candidate)
        maximum[(code, rank)] = number
    return [value or "" for value in proposed], reasons


def write_outputs(
    products: pd.DataFrame,
    audit: pd.DataFrame,
    output_dir: Path,
    omit_columns: list[str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    review_path = output_dir / "catalog_review.xlsx"
    candidate_path = output_dir / "catalog_import_candidate.xlsx"
    id_map_path = output_dir / "external_id_change_map.csv"

    category_summary = (
        products.groupby(["Main_Category", "Product Category"], dropna=False)
        .size()
        .reset_index(name="Products")
        .sort_values(["Main_Category", "Products"], ascending=[True, False])
    )
    with pd.ExcelWriter(review_path, engine="openpyxl") as writer:
        audit.to_excel(writer, sheet_name="All Products", index=False)
        audit[audit["Review Required"]].to_excel(writer, sheet_name="Review Required", index=False)
        audit[audit["Category Changed"]].to_excel(writer, sheet_name="Category Changes", index=False)
        audit[audit["External ID Changed"]].to_excel(writer, sheet_name="External ID Changes", index=False)
        category_summary.to_excel(writer, sheet_name="Category Summary", index=False)

    candidate = products[products["Main_Category"] != "Unknown"].copy()
    candidate = candidate.drop(columns=[column for column in omit_columns if column in candidate.columns])
    candidate.to_excel(candidate_path, index=False)

    id_map_columns = [
        "Old External ID", "New External ID", "Name", "Barcode",
        "Old Main Category", "New Main Category", "Old Product Category",
        "New Product Category", "Confidence", "Rule ID", "Decision Reason",
        "Suggested External Identifier Display Name",
    ]
    audit[audit["External ID Changed"]][id_map_columns].to_csv(
        id_map_path, index=False, encoding="utf-8-sig"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a reviewable multilingual Odoo product catalog."
    )
    parser.add_argument("--products", type=Path, required=True, help="Legacy product CSV/XLSX.")
    parser.add_argument("--enrichment", type=Path, help="Output from 01_go_upc_enrich.py.")
    parser.add_argument("--taxonomy", type=Path, required=True, help="KVS category workbook.")
    parser.add_argument("--taxonomy-sheet", default="Inventory Categories")
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--mappings", type=Path, required=True)
    parser.add_argument("--overrides", type=Path, help="Optional exact manual override CSV.")
    parser.add_argument("--output-dir", type=Path, default=Path("output/catalog"))
    parser.add_argument("--review-threshold", type=float, default=0.85)
    parser.add_argument(
        "--keep-source-names",
        action="store_true",
        help="Only use Go-UPC names where the source name is blank.",
    )
    parser.add_argument(
        "--omit-column",
        action="append",
        default=[],
        help="Drop a column from the import candidate; repeat as needed (for example Unit).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    required_paths = [args.products, args.taxonomy, args.rules, args.mappings]
    if args.enrichment:
        required_paths.append(args.enrichment)
    if args.overrides:
        required_paths.append(args.overrides)
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        print(f"Missing input files: {missing}", file=sys.stderr)
        return 2

    try:
        taxonomy = parse_taxonomy(args.taxonomy, args.taxonomy_sheet)
        rules_config = load_json(args.rules)
        mappings = load_json(args.mappings)
        rules = sorted(rules_config["rules"], key=lambda rule: rule["priority"], reverse=True)
        products = canonicalize_columns(read_table(args.products))
        products, merge_stats = merge_enrichment(
            products, args.enrichment, replace_names=not args.keep_source_names
        )
        overrides = load_overrides(args.overrides)
    except (ValueError, KeyError, OSError) as exc:
        print(f"Configuration/input error: {exc}", file=sys.stderr)
        return 2

    old_main = products["Main_Category"].map(clean_text)
    old_sub = products["Product Category"].map(clean_text)
    old_pos = products.get("Point of Sale Category", pd.Series("", index=products.index)).map(clean_text)
    old_web = products.get("Website Product Category", pd.Series("", index=products.index)).map(clean_text)

    decisions: list[Decision] = []
    for _, row in products.iterrows():
        decision = classify(row, rules, taxonomy, overrides)
        validate_decision(decision, taxonomy)
        decisions.append(decision)

    work = products.copy()
    work["New Main Category"] = [decision.main_category for decision in decisions]
    work["New Product Category"] = [decision.product_category for decision in decisions]
    work["Confidence"] = [decision.confidence for decision in decisions]
    work["Rule ID"] = [decision.rule_id for decision in decisions]
    work["Decision Reason"] = [decision.reason for decision in decisions]

    def channel_value(channel: str, main: str, sub: str) -> str:
        if main == "Unknown":
            return "Unknown"
        if channel == "pos":
            return mappings["pos_by_main"][main]
        return mappings["website_by_main_sub"][f"{main}|||{sub}"]

    work["New Point of Sale Category"] = [
        channel_value("pos", decision.main_category, decision.product_category)
        for decision in decisions
    ]
    work["New Website Product Category"] = [
        channel_value("website", decision.main_category, decision.product_category)
        for decision in decisions
    ]

    proposed_ids, id_reasons = assign_external_ids(work, taxonomy)
    work["Old External ID"] = products["External ID"].map(clean_text)
    work["New External ID"] = proposed_ids
    work["External ID Reason"] = id_reasons
    work["Old Main Category"] = old_main
    work["Old Product Category"] = old_sub
    work["Old Point of Sale Category"] = old_pos
    work["Old Website Product Category"] = old_web
    work["Category Changed"] = (
        old_main.ne(work["New Main Category"])
        | old_sub.ne(work["New Product Category"])
        | old_pos.ne(work["New Point of Sale Category"])
        | old_web.ne(work["New Website Product Category"])
    )
    work["External ID Changed"] = work["Old External ID"].ne(work["New External ID"])
    work["Review Required"] = (
        work["New Main Category"].eq("Unknown")
        | work["Confidence"].lt(args.review_threshold)
        | work["Name"].map(clean_text).eq("")
    )
    work["Suggested External Identifier Display Name"] = [
        f"[{external_id}] {clean_text(name)}" if external_id else ""
        for external_id, name in zip(work["New External ID"], work["Name"])
    ]

    final_products = products.copy()
    final_products["External ID"] = work["New External ID"]
    final_products["Main_Category"] = work["New Main Category"]
    final_products["Product Category"] = work["New Product Category"]
    final_products["Point of Sale Category"] = work["New Point of Sale Category"]
    final_products["Website Product Category"] = work["New Website Product Category"]

    audit_columns = [
        "Old External ID", "New External ID", "Name", "Barcode",
        "Old Main Category", "New Main Category", "Old Product Category",
        "New Product Category", "Old Point of Sale Category",
        "New Point of Sale Category", "Old Website Product Category",
        "New Website Product Category", "Confidence", "Rule ID", "Decision Reason",
        "Category Changed", "External ID Changed", "Review Required",
        "External ID Reason", "Suggested External Identifier Display Name",
    ]
    audit = work[audit_columns].copy()
    write_outputs(final_products, audit, args.output_dir, args.omit_column)

    nonblank_barcodes = final_products["Barcode"].map(canonical_barcode)
    nonblank_barcodes = nonblank_barcodes[nonblank_barcodes.ne("")]
    nonblank_ids = final_products["External ID"].map(clean_text)
    nonblank_ids = nonblank_ids[nonblank_ids.ne("")]
    summary = {
        **merge_stats,
        "classified_rows": int(final_products["Main_Category"].ne("Unknown").sum()),
        "unknown_rows": int(final_products["Main_Category"].eq("Unknown").sum()),
        "review_required_rows": int(audit["Review Required"].sum()),
        "category_changes": int(audit["Category Changed"].sum()),
        "external_id_changes": int(audit["External ID Changed"].sum()),
        "duplicate_nonblank_barcodes": int(nonblank_barcodes.duplicated().sum()),
        "duplicate_nonblank_external_ids": int(nonblank_ids.duplicated().sum()),
        "output_dir": str(args.output_dir.resolve()),
        "safety_note": "No connection to Odoo was made.",
    }
    (args.output_dir / "run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 1 if summary["unknown_rows"] or summary["duplicate_nonblank_external_ids"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
