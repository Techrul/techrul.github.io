#!/usr/bin/env python3
"""Copy the static pages and assets from site/ into docs/ (the folder GitHub Pages serves).

    python3 scripts/build_site.py --site site --out docs

Data files under docs/*/data are produced by the other scripts and are left alone.
Preview locally with:  python3 -m http.server -d docs   (then open http://localhost:8000)
"""
import argparse
import os
import shutil

SKIP = {"template.html"}  # the old single-page template, kept only for reference


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="site")
    ap.add_argument("--out", default="docs")
    args = ap.parse_args()
    n = 0
    for folder, _dirs, files in os.walk(args.site):
        rel = os.path.relpath(folder, args.site)
        for f in files:
            if f in SKIP:
                continue
            dest_dir = os.path.join(args.out, rel)
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(os.path.join(folder, f), os.path.join(dest_dir, f))
            n += 1
    # GitHub Pages: serve files as-is (no Jekyll processing)
    open(os.path.join(args.out, ".nojekyll"), "w").close()
    print(f"copied {n} files into {args.out}")


if __name__ == "__main__":
    main()
