## Limitation

Odoo Online exposed several fixed, affixed, and hide-on-scroll header states, but offered no module-level access to replace the header behavior. Their competing transforms changed page geometry during scroll and caused the homepage to jump vertically.

## Workaround

I neutralized the conflicting public header states with one editor-safe CSS layer rather than changing Odoo's template or JavaScript. The rules are scoped outside `editor_enable`, preserve the header markup, remove transition-driven geometry changes, and contain horizontal overflow. Product and carousel transforms were also disabled where they amplified repainting during scroll.

## Result

Homepage scrolling became monotonic and predictable, the white band below the header disappeared, and the Website Builder remained usable.
