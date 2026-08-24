## Limitation

Odoo renders catalogue cards, category cards, and dynamic-snippet cards through different markup, while Odoo Online provides no deployable theme component to replace them together. Default actions could expand into oversized text buttons or expose comparison controls inappropriate for grocery shopping.

## Workaround

I built a selector-based product-card contract that targets Odoo's stable semantic classes across those rendering paths. A two-column footer grid reserves a fixed 40 x 40 action area, clamps titles, normalizes imagery, and hides comparison/wishlist placeholders without altering cart behavior. Public-only scoping protects the editor and keeps native Odoo add-to-cart events intact.

## Result

Product grids became denser and visually consistent, with stable prices and compact cart actions on desktop and mobile.
