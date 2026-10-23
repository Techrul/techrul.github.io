#!/usr/bin/env python3
"""Copy the static pages and assets from site/ into docs/ (the folder GitHub Pages serves).

    python3 scripts/build_site.py --site site --out docs

Data files under docs/*/data are produced by the other scripts and are left alone.
Pages get the shared site.js and site.css with ?v=<content hash>, so a browser never pairs a new page with a
cached old script (GitHub Pages lets browsers cache files for 10 minutes).
Preview locally with:  python3 -m http.server -d docs   (then open http://localhost:8000)
"""
import argparse
import hashlib
import os
import re
import shutil

SKIP = {"template.html"}  # the old single-page template, kept only for reference


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="site")
    ap.add_argument("--out", default="docs")
    args = ap.parse_args()
    assets = os.path.join(args.site, "rankings", "assets")
    version = {}
    for name in ("site.js", "site.css"):
        with open(os.path.join(assets, name), "rb") as fh:
            version[name] = hashlib.sha256(fh.read()).hexdigest()[:10]
    stamp = re.compile(r'(assets/(site\.(?:js|css)))(?:\?v=[0-9a-f]+)?"')
    n = 0
    for folder, _dirs, files in os.walk(args.site):
        rel = os.path.relpath(folder, args.site)
        for f in files:
            if f in SKIP:
                continue
            dest_dir = os.path.join(args.out, rel)
            os.makedirs(dest_dir, exist_ok=True)
            src, dest = os.path.join(folder, f), os.path.join(dest_dir, f)
            if f.endswith(".html"):
                with open(src, encoding="utf-8") as fh:
                    text = fh.read()
                with open(dest, "w", encoding="utf-8") as fh:
                    fh.write(stamp.sub(lambda m: f'{m.group(1)}?v={version[m.group(2)]}"', text))
            else:
                shutil.copy2(src, dest)
            n += 1
    # GitHub Pages: serve files as-is (no Jekyll processing)
    open(os.path.join(args.out, ".nojekyll"), "w").close()
    print(f"copied {n} files into {args.out}")


if __name__ == "__main__":
    main()
