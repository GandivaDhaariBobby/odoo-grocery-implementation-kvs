## Limitation

The standard Odoo delivery-status column displayed the internal state `Started`, which is unclear in a consumer grocery pickup journey. Odoo Online did not allow changing the underlying module template in source control.

## Workaround

In developer mode, I created a minimal extension view inheriting Odoo's standard portal shipping-status view. The XPath replaces only the `started` branch and leaves the workflow state, table structure, other statuses, and upgrade-owned parent view untouched. This follows Odoo's recommended inheritance model instead of editing core architecture or relabeling the DOM with fragile JavaScript.

## Result

Customers see `Ready to pick` in order history while native portal behavior and backend fulfilment logic remain unchanged.
