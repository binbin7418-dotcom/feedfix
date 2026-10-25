# FeedFix — Google Shopping Feed Audit, Fix & Re-Check

FeedFix audits your Google Shopping product feed, repairs the formatting
errors, then **re-audits the repaired file** so you can see exactly what was
fixed and what still needs your judgment. 100% local — your feed data never
leaves your computer.

## What it fixes on its own
- Availability values mapped to the required enums (`In Stock` → `in_stock`, `available` → `in_stock`, …)
- Price formats normalized (`$19.99` → `19.99 USD`, `9.9 USD` → `9.90 USD`)
- `http://` links upgraded to `https://`
- Relative image URLs made absolute using your product-link domain
- HTML tags stripped from descriptions
- Missing `condition` filled with the Merchant Center default (`new`)

## What it reports, but never silently changes
- GTINs that fail the check-digit test (likely typos — auto-"fixing" a barcode would fabricate data)
- Duplicate product ids, `sale_price` not lower than `price`
- Missing required attributes, invalid GTIN formats, branded products with no identifier
- Promotional / ALL-CAPS titles, over-long titles, missing shipping weight, preorders without a date

## Verified behaviour
On a seeded 12-product test feed containing 21 planted problems, FeedFix
auto-repaired 10, and the re-check confirmed the same 11 human-decision items
remained (5 blocking errors) with 0 new issues introduced.

## Run from source
```
python feed_fix.py your_feed.csv output_folder
```
Writes `<name>_fixed.csv` and `fix_report.md` into the output folder.
The Windows app (`gui.py`, packaged with PyInstaller) wraps the same engine.

## Scope
File-level data-spec audit (attributes, formats, identifiers). Account-level
issues (suspensions, policy/misrepresentation) cannot be seen from the feed
file alone and are out of scope.
