from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


go_upc = load_script("go_upc_enrich", "01_go_upc_enrich.py")
catalog = load_script("build_odoo_catalog", "02_build_odoo_catalog.py")


class GoUpcTests(unittest.TestCase):
    def test_barcode_preserves_leading_zero(self):
        self.assertEqual(go_upc.canonical_barcode("0012345678905"), "0012345678905")

    def test_scientific_notation_is_rejected(self):
        with self.assertRaises(ValueError):
            go_upc.canonical_barcode("8.90160E+12")

    def test_known_gtin_check_digit(self):
        self.assertTrue(go_upc.gtin_check_digit_is_valid("4006381333931"))
        self.assertFalse(go_upc.gtin_check_digit_is_valid("4006381333932"))

    def test_multilingual_api_value_prefers_english(self):
        value = {"de": "Kichererbsen", "en": "Chickpeas"}
        self.assertEqual(go_upc.value_to_text(value), "Chickpeas")


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (ROOT / "config" / "classification_rules.json").open(encoding="utf-8") as handle:
            rules = json.load(handle)["rules"]
        cls.rules = sorted(rules, key=lambda rule: rule["priority"], reverse=True)
        cls.taxonomy = catalog.Taxonomy({}, {}, {})

    def classify_name(self, name: str):
        row = pd.Series(
            {
                "Name": name,
                "Barcode": "",
                "External ID": "",
                "Main_Category": "",
                "Product Category": "",
                "Brand": "",
                "eCommerce Description": "",
                "Ingredients": "",
            }
        )
        return catalog.classify(row, self.rules, self.taxonomy, {})

    def assert_category(self, name: str, main: str, sub: str):
        decision = self.classify_name(name)
        self.assertEqual((decision.main_category, decision.product_category), (main, sub))

    def test_name_cleanup_keeps_brand_and_size(self):
        cleaned = catalog.clean_product_name(
            "TRS Ginger Powder 100 grams Premium Quality", "TRS"
        )
        self.assertEqual(cleaned, "TRS Ginger Powder 100g")

    def test_high_risk_false_friends(self):
        cases = [
            ("DAX Vegetable Oils Pomade Now With Lanolin 14oz", "BEAUTY & PERSONAL CARE", "Hair Care"),
            ("Guinea Fresh Palm Oil 1L", "AFRICAN PRODUCTS", "African Oils & Condiments"),
            ("V-Fresh Pomegranate Juice", "BEVERAGES", "Soft Drinks & Juice"),
            ("Fresh Drumstick (Moringa Pod) from India", "FRESH FRUITS & VEGETABLES", "Fresh Vegetables"),
            ("Horlicks Original Malted Drink 400g", "BEVERAGES", "Other Drinks"),
            ("Maliban Ginger Cookie 80g", "SNACKS & SAVORY", "Baked Snacks"),
            ("Annam Curry Leaves 100g", "SPICES & SEASONINGS", "Dried Herbs"),
            ("Ashoka Mixed Vegetable Paratha", "DAIRY & FROZEN FOODS", "Frozen Foods"),
            ("Tasty Nibbles Brown Sugar Jaggery Powder 500g", "SPICES & SEASONINGS", "Other Seasonings"),
        ]
        for name, main, sub in cases:
            with self.subTest(name=name):
                self.assert_category(name, main, sub)

    def test_gin_does_not_match_ginger(self):
        decision = self.classify_name("TRS Ginger Powder")
        self.assertNotEqual(decision.product_category, "Alcohol")

    def test_external_id_is_preserved_or_reassigned_deterministically(self):
        taxonomy = catalog.Taxonomy(
            code_by_main={"SPICES & SEASONINGS": "SPIC", "BEVERAGES": "BEVR"},
            main_by_sub={"Powdered Masalas": "SPICES & SEASONINGS", "Tea": "BEVERAGES"},
            rank_by_pair={
                ("SPICES & SEASONINGS", "Powdered Masalas"): 3,
                ("BEVERAGES", "Tea"): 1,
            },
        )
        frame = pd.DataFrame(
            [
                {
                    "External ID": "SPIC-3144",
                    "New Main Category": "SPICES & SEASONINGS",
                    "New Product Category": "Powdered Masalas",
                },
                {
                    "External ID": "BEVR-1009",
                    "New Main Category": "SPICES & SEASONINGS",
                    "New Product Category": "Powdered Masalas",
                },
                {
                    "External ID": "BEVR-1002",
                    "New Main Category": "BEVERAGES",
                    "New Product Category": "Tea",
                },
            ]
        )
        proposed, _ = catalog.assign_external_ids(frame, taxonomy)
        self.assertEqual(proposed, ["SPIC-3144", "SPIC-3145", "BEVR-1002"])


if __name__ == "__main__":
    unittest.main()
