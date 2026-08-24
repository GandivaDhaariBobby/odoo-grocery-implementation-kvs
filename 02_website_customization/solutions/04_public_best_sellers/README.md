## Limitation

Odoo Online's built-in `Recently Sold Products` dynamic filter produced session-dependent results, so an administrator preview could show several products while a fresh public visitor saw only one. There was no custom server method available to provide a stable bestseller query.

## Workaround

I created a published ecommerce category as an editor-managed merchandising source and assigned five selected bestseller products to it. The homepage dynamic snippet uses Odoo's public `Newest Products` filter only as the supported retrieval mechanism, constrained to that category and five records. This avoids hardcoded product HTML while keeping future curation available to non-developers in the Odoo backend.

## Result

Anonymous and authenticated visitors use the same public product source, and store staff can update the selection without code or a redeployment.
