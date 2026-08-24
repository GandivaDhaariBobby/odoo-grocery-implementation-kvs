# By - GandivaDhaariBobby
# Odoo Grocery Retail Implementation — KVS Cash & Carry

A complete, single-handed Odoo Online implementation for a multicultural grocery store
(Indian, wider Asian, and African products) in Germany: POS, inventory, eCommerce
website, hardware integration, data migration, and multilingual staff training.

This repository is a curated engineering case study. Each section documents a real
constraint of the hosted Odoo Online platform, the workaround that was engineered
within that constraint, and the measured result.

> **Companion project:** the retail-scale hardware integration from this implementation
> was generalized into a standalone open-source tool —
> [Universal Odoo Scale Toolkit](https://github.com/YOUR_USERNAME/universal-odoo-scale-toolkit) —
> which discovers unknown serial scale protocols and generates installable Odoo
> Virtual IoT adapters.

## Results at a glance

| Area | Outcome |
|---|---|
| Legacy POS data | ~8,000 raw entries reduced to 2,872 approved, deduplicated products |
| API enrichment | 2,947 products enriched via Go-UPC (81.5% hit rate), 2,876 with images |
| Categorization | 20-category retail taxonomy applied by a multilingual rule engine; 0 products left uncategorized |
| Hardware | Undocumented legacy scanner/scale protocol reverse-engineered and bridged to Odoo IoT (see companion repo) |
| Website | Generic Odoo Online storefront rebuilt into a professional grocery identity within hosted-platform limits |
| Training | 111-page operations manual in English, German, Tamil, and Arabic (RTL), designed for a non-technical owner |

## Sections

### [01 — Product Data Pipeline](01_product_data_pipeline/)

The legacy POS export was unusable as-is: duplicate barcodes, broken names,
no reliable categories. A two-stage Python pipeline rebuilt the catalog —
resumable Go-UPC barcode enrichment, multilingual name normalization
(Indian, Asian, and African product names), a configurable classification
rule engine with manual-override transparency, and deterministic Odoo
External ID allocation. Includes sample data, automated tests, and an
illustrated engineering report.

**Constraint → workaround:** no server access on Odoo Online, so the entire
migration runs as an external, auditable pipeline producing review workbooks
and import files rather than writing to the database directly.

### [02 — Website Customization](02_website_customization/)

Odoo Online allows no custom modules, no theme source, and no server shell.
Five selected solutions show how a recognizable generic storefront was turned
into a professional grocery experience anyway — scroll-stable headers,
a cross-template product-card system, mobile purchase prioritization,
a visitor-independent Best Sellers feed, and a safely extended portal view —
using only Website Builder controls, inherited views, and scoped frontend assets.

### [03 — Training & Documentation](03_training_documentation/)

Software only creates value if the owner can run it. An 8-step, 111-page
operations manual was designed around the daily workflow of a non-technical
grocery owner, then translated into German, Tamil, and Arabic (with verified
right-to-left layout) while keeping all Odoo interface terms in English.
A separate Design Philosophy document explains the reasoning behind the
system and the documentation approach. All 141 embedded screenshots were
privacy-audited before publication.

## Role and positioning

All work in this repository — analysis, data engineering, integration,
frontend customization, hardware protocol work, and documentation — was
performed by a single implementer. This is deliberately presented as
**Odoo implementation and integration engineering** on the hosted Odoo Online
platform, not custom module development: the recurring theme is delivering
production outcomes despite the platform's restrictions, using external
tooling where the platform does not permit code.

## Stack

Python 3 (requests, pandas, openpyxl) · Odoo Online 17 (POS, Inventory,
eCommerce, Website Builder, inherited QWeb views) · Go-UPC REST API ·
serial protocol analysis (RS-232 / Mettler-Toledo Dialog 04/02, MT-8217) ·
Brother QL-700 label workflow · CSS/HTML/XML frontend assets

## License

MIT — see [LICENSE](LICENSE). Client-identifying data has been removed or
redacted; sample datasets are illustrative. No production credentials or
customer data are contained in this repository.
