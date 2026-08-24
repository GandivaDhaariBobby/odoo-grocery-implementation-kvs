## Limitation

Odoo's hosted product template placed large imagery, long descriptions, and auxiliary availability blocks before the primary buying controls on small screens. Without module access, the QWeb structure could not be safely reordered at source.

## Workaround

I used CSS flex ordering and bounded media dimensions to move the existing native CTA block into the initial mobile purchase area without cloning or replacing it. A defensive progressive-enhancement script collapses only genuinely long descriptions and inserts an accessible expansion button. It exits in editor mode, initializes once, and leaves Odoo's pricing, quantity, variants, and cart handlers untouched.

## Result

Mobile customers reach price, quantity, and Add to Cart sooner while retaining access to the full product description and all native Odoo commerce behavior.
