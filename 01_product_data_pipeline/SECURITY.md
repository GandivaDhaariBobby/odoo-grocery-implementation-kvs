# Security

The scripts never require an API key inside source code. Set `GO_UPC_API_KEY`
in the environment and keep `.env` outside version control.

Before publishing a fork, run a secret scanner such as Gitleaks and inspect the
Git history as well as the current files. Removing a key from the latest commit
does not remove it from older commits. Revoke and rotate any credential that was
ever stored in a script, terminal transcript, screenshot, or committed file.

The catalog builder is intentionally offline. It cannot write to Odoo. Review
`catalog_review.xlsx` and `external_id_change_map.csv` before performing a live
import or editing Odoo External Identifiers.

