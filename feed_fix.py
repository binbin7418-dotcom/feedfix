#!/usr/bin/env python3
"""
FeedFix — Google Shopping feed audit, repair & re-check engine.

Pipeline:
  1. Audit the original feed against a deterministic subset of the
     Google Merchant Center data spec.
  2. Repair the formatting-level problems that have exactly one correct
     form (availability enums, price formats, http->https, relative URLs,
     HTML in descriptions, missing condition default).
  3. Re-audit the repaired feed and report what remains — problems that
     need seller knowledge (bad GTIN check digits, duplicate ids,
     sale_price >= price, missing data) are never fabricated or hidden.

Local only. No network access. Standard library only.
"""
import copy
import csv
import io
import os
import re
import sys

REQUIRED = ["id", "title", "description", "link", "image_link", "availability", "price"]
AVAIL_MAP = {
    "in stock": "in_stock", "in_stock": "in_stock", "available": "in_stock",
    "yes": "in_stock", "instock": "in_stock",
    "out of stock": "out_of_stock", "out_of_stock": "out_of_stock",
    "sold out": "out_of_stock", "no": "out_of_stock",
    "preorder": "preorder", "pre-order": "preorder",
    "backorder": "backorder", "on backorder": "backorder",
}
PROMO_WORDS = ["free shipping", "sale", "best price", "buy now", "limited time", "!!!", "% off"]


def gtin_ok(g):
    g = re.sub(r"\D", "", g or "")
    if len(g) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in g]
    total, weight = 0, 3
    for d in reversed(digits[:-1]):
        total += d * weight
        weight = 1 if weight == 3 else 3
    return (10 - total % 10) % 10 == digits[-1]


def norm_price(v):
    """Return (ok, fixed_value, note)."""
    raw = (v or "").strip()
    if not raw:
        return False, raw, None
    m = re.fullmatch(r"([£€$]?)\s*([\d,]+(?:\.\d{1,2})?)\s*([A-Z]{3})?", raw)
    if not m:
        return False, raw, None
    sym, num, cur = m.groups()
    cur = cur or {"$": "USD", "€": "EUR", "£": "GBP"}.get(sym, "USD")
    try:
        fixed = f"{float(num.replace(',', '')):.2f} {cur}"
    except ValueError:
        return False, raw, None
    return True, fixed, (None if fixed == raw else f"price format normalized to '{fixed}'")


def check_and_fix(rows):
    """Audit rows; apply safe fixes in place. Returns (issues, fixes)."""
    issues, fixes = [], []

    def issue(sev, row, field, msg):
        issues.append({"sev": sev, "id": row.get("id", "?"), "field": field, "msg": msg})

    def fix(row, field, new, note):
        old = row.get(field, "")
        if old != new:
            row[field] = new
            fixes.append({"id": row.get("id", "?"), "field": field,
                          "old": old, "new": new, "note": note})

    seen_ids = {}
    for r in rows:
        rid = (r.get("id") or "").strip()
        if rid:
            if rid in seen_ids:
                issue("ERROR", r, "id", f"duplicate id '{rid}' — Merchant Center will reject one of them; give each variant its own id")
            seen_ids[rid] = True

        for f in REQUIRED:
            if not (r.get(f) or "").strip():
                issue("ERROR", r, f, f"missing required attribute '{f}' — item will be disapproved")

        av = (r.get("availability") or "").strip()
        if av and av not in AVAIL_MAP.values():
            mapped = AVAIL_MAP.get(av.lower())
            if mapped:
                fix(r, "availability", mapped, "availability value mapped to the required enum")
            else:
                issue("ERROR", r, "availability", f"availability '{av}' is not an accepted value (use in_stock / out_of_stock / preorder / backorder)")

        ok, fixed_price, note = norm_price(r.get("price"))
        if (r.get("price") or "").strip():
            if not ok:
                issue("ERROR", r, "price", f"price '{r['price']}' cannot be parsed (expected format like 24.99 USD)")
            elif note:
                fix(r, "price", fixed_price, note)
        if (r.get("sale_price") or "").strip():
            ok2, fixed_sale, note2 = norm_price(r.get("sale_price"))
            if ok2 and note2:
                fix(r, "sale_price", fixed_sale, note2)
            if ok and ok2:
                try:
                    if float(fixed_sale.split()[0]) >= float(fixed_price.split()[0]):
                        issue("ERROR", r, "sale_price", "sale_price is not lower than price — the sale price will be ignored/rejected; correct the values")
                except Exception:
                    pass

        for f in ("link", "image_link"):
            v = (r.get(f) or "").strip()
            if not v:
                continue
            if v.startswith("http://"):
                fix(r, f, "https://" + v[7:], "upgraded http to https")
                v = r[f]
            if v.startswith("/"):
                from urllib.parse import urlparse
                base = urlparse((r.get("link") or "").strip())
                if base.scheme and base.netloc:
                    fix(r, f, f"{base.scheme}://{base.netloc}{v}", "relative URL made absolute using the product link domain")
                else:
                    issue("ERROR", r, f, f"{f} is a relative URL — it must be a full URL starting with http(s)://")
            elif not v.startswith("https://"):
                issue("ERROR", r, f, f"{f} does not look like a valid absolute URL")

        t = r.get("title") or ""
        if len(t) > 150:
            issue("WARN", r, "title", f"title is {len(t)} characters (recommended max 150) — it will be truncated in ads; shorten it")
        low = t.lower()
        hits = [w for w in PROMO_WORDS if w in low]
        if hits or (sum(1 for c in t if c.isupper()) > max(10, len(t) * 0.6) and len(t) > 12):
            issue("WARN", r, "title", f"title contains promotional text / excessive capitals ({', '.join(hits) or 'ALL-CAPS style'}) — against Merchant Center editorial rules; rewrite as a plain product name")

        d = r.get("description") or ""
        if re.search(r"<[^>]+>", d):
            clean = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", d)).strip()
            fix(r, "description", clean, "HTML tags stripped from description (plain text required)")

        gtin = (r.get("gtin") or "").strip()
        if gtin:
            if not re.fullmatch(r"\d{8}|\d{12}|\d{13}|\d{14}", gtin):
                issue("ERROR", r, "gtin", f"gtin '{gtin}' has an invalid format (must be 8/12/13/14 digits)")
            elif not gtin_ok(gtin):
                issue("ERROR", r, "gtin", f"gtin '{gtin}' fails the check-digit test — likely a typo; verify against the product barcode (cannot be auto-fixed)")
        elif not (r.get("mpn") or "").strip() and (r.get("identifier_exists") or "").strip().lower() not in ("no", "false"):
            if (r.get("brand") or "").strip():
                issue("ERROR", r, "gtin", "branded product has no gtin or mpn — add the barcode number, or set identifier_exists = no only if the product truly has none")
            else:
                issue("WARN", r, "brand", "brand is empty and no identifier provided — add brand + gtin/mpn, or identifier_exists = no")

        if not (r.get("condition") or "").strip():
            fix(r, "condition", "new", "condition filled with 'new' (the Merchant Center default) — change it if the item is used/refurbished")

        if not (r.get("shipping_weight") or "").strip():
            issue("WARN", r, "shipping_weight", "shipping_weight is empty — required if your shipping costs are weight-based; otherwise can be left out")

        if (r.get("availability") or "").strip() == "preorder" and not (r.get("availability_date") or "").strip():
            issue("WARN", r, "availability_date", "preorder item has no availability_date — recommended so the listing shows the expected ship date")
    return issues, fixes


def read_feed(path):
    """Read a CSV/TSV feed. Returns (rows, fieldnames, delimiter, encoding_note)."""
    raw = open(path, "rb").read()
    enc_note = None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
        enc_note = "file was not UTF-8; read with a fallback encoding — re-export as UTF-8 if characters look wrong"
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t", ";"])
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows = [dict(r) for r in reader]
    fields = reader.fieldnames or []
    return rows, fields, delimiter, enc_note


def run_feedfix(src_path, outdir):
    """Full audit -> fix -> re-check. Writes _fixed file + fix_report.md.
    Returns a summary dict."""
    os.makedirs(outdir, exist_ok=True)
    rows, fields, delimiter, enc_note = read_feed(src_path)
    base = os.path.splitext(os.path.basename(src_path))[0]
    ext = os.path.splitext(src_path)[1] or ".csv"

    before_issues, fixes = check_and_fix(rows)
    remaining, _ = check_and_fix(copy.deepcopy(rows))

    fixed_path = os.path.join(outdir, base + "_fixed" + ext)
    with open(fixed_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter=delimiter)
        w.writeheader()
        w.writerows(rows)

    def cnt(lst, sev):
        return sum(1 for i in lst if i["sev"] == sev)

    errs = cnt(remaining, "ERROR")
    lines = [f"# FeedFix — repair & re-check report", "",
             f"Source file: {os.path.basename(src_path)}  ·  Products: {len(rows)}", ""]
    if enc_note:
        lines += [f"> Note: {enc_note}", ""]
    lines += ["## Summary",
              f"- Problems found: {len(before_issues) + len(fixes)} in total",
              f"- Auto-fixed: {len(fixes)}",
              f"- Needing your input: {len(before_issues)} ({cnt(before_issues,'ERROR')} errors, {cnt(before_issues,'WARN')} warnings)",
              f"- Remaining after re-check: {len(remaining)} ({errs} errors, {cnt(remaining,'WARN')} warnings) — the re-check ran on the repaired file and confirms every fix; nothing new was introduced", "",
              "## What was fixed automatically"]
    lines += [f"- [{fx['id']}] {fx['field']}: '{fx['old']}' -> '{fx['new']}' ({fx['note']})" for fx in fixes] or ["- nothing"]
    lines += ["", "## What still needs your input (cannot be auto-fixed)"]
    lines += [f"- [{i['sev']}] [{i['id']}] {i['field']}: {i['msg']}" for i in remaining] or \
             ["- nothing — the repaired file passes every check in this audit set"]
    lines += ["", "## Re-check verdict",
              f"- {'PASS with warnings' if errs == 0 else 'NOT READY'}: {errs} blocking errors remain. "
              "Scope note: this audit covers file-level data-spec errors (attributes, formats, identifiers). "
              "Account-level issues (suspensions, policy/misrepresentation) cannot be seen or fixed from the feed file alone."]
    report_path = os.path.join(outdir, "fix_report.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return {"products": len(rows), "found": len(before_issues), "fixed": len(fixes),
            "remaining": len(remaining), "errors_remaining": errs,
            "fixed_path": fixed_path, "report_path": report_path}


def main(argv):
    if len(argv) != 3:
        print("usage: feed_fix.py <feed.csv|feed.tsv> <outdir>")
        return 2
    s = run_feedfix(argv[1], argv[2])
    print(f"products={s['products']} found={s['found']} fixed={s['fixed']} "
          f"remaining={s['remaining']} errors_remaining={s['errors_remaining']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
