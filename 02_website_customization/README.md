# KVS Cash & Carry - Odoo Online Website Customization

KVS Cash & Carry runs on Odoo Online, where there is no repository, server shell, custom module deployment, or direct access to Odoo's theme source. Every solution therefore had to work through hosted Website Builder controls, dynamic-snippet configuration, developer-mode inherited views, and narrowly scoped frontend assets without breaking catalogue, cart, checkout, portal, or editor behavior.

The design goal was to turn a recognizable generic Odoo storefront into a professional Indian, African, and Asian grocery experience: faster product discovery, stable mobile shopping, consistent buying controls, strong KVS green-and-saffron identity, and customer-facing language that does not expose internal Odoo concepts.

## Selected Solutions

| Solution | What it demonstrates |
| --- | --- |
| [01 - Scroll-stable storefront](solutions/01_scroll_stable_storefront/) | Neutralizing Odoo's competing affix/hide-on-scroll states without module access or editor regressions. |
| [02 - Cross-template product cards](solutions/02_cross_template_product_cards/) | Creating one reliable grocery-card action system across Odoo-generated catalogue and snippet markup. |
| [03 - Mobile purchase priority](solutions/03_mobile_purchase_priority/) | Reordering and progressively enhancing an immutable product template so purchase controls appear sooner. |
| [04 - Visitor-independent Best Sellers](solutions/04_public_best_sellers/) | Replacing a session-dependent dynamic feed with a public, editor-managed merchandising source. |
| [05 - Retail portal status](solutions/05_retail_portal_status/) | Extending a standard Odoo portal QWeb view safely instead of modifying core architecture. |

Plus [consolidated theme refinements](theme_refinements.css).

## Screenshots

### Before

The original annotated homepage screenshot came from a temporary clipboard attachment that was unavailable when the repository package was rebuilt. [The before folder](before/) preserves the recovery note and exact expected filename; no replacement image is presented as original evidence.

### After

- [Homepage above the fold](after/homepage-desktop.jpg)
- [Pantry & Staples category](after/category-pantry-staples-desktop.jpg)
- [Representative product detail](after/product-detail-desktop.jpg)

The captures are from the public storefront and contain no customer, order, revenue, or credential data.
