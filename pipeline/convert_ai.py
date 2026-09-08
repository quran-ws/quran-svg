#!/usr/bin/env python3
"""Batch-convert a publisher's Illustrator pages to SVG with Inkscape.

The King Fahd Complex distributes each muṣḥaf as one ``.ai`` per page.  They are PDFs with an
Illustrator wrapper, and their layers are declared as PDF optional-content groups, so Inkscape
carries the layer structure across as ``<g id="layer-MCn">`` in the order the groups are
declared.  For the 1422 Hafs edition that is

    MC0 Header & Page No.   MC1 Marks   MC2 Border   MC3 Aya_Number   MC4 Quran_TEXT

and ``normalize.py`` keeps the last two.  Inkscape prints a warning per page about text it
cannot read as UTF-16 -- that is the folio number's font, which it converts to a path anyway,
and it is not an error.

    python3 pipeline/convert_ai.py --zip ~/Downloads/hafs_1422.zip --out .work/hafs1422
    python3 pipeline/convert_ai.py --ai .work/hafs1422/ai --out .work/hafs1422 --force

Conversion is skipped for a page that already has a non-empty SVG, so an interrupted run
resumes.  Roughly three seconds a page, and the output is large: the 1422 edition is 2.2 GB
of raw SVG before anything is done to it.
"""

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def extract(zip_path, out_dir):
    """Unpack the archive's ``.ai`` files, and return where they landed."""
    ai_dir = os.path.join(out_dir, "ai")
    os.makedirs(ai_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".ai")]
        if not names:
            raise SystemExit("%s contains no .ai files" % zip_path)
        for name in names:
            target = os.path.join(ai_dir, os.path.basename(name))
            if os.path.exists(target) and os.path.getsize(target):
                continue
            with zf.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return ai_dir


def _convert(job):
    ai, out, force = job
    if not force and os.path.exists(out) and os.path.getsize(out):
        return os.path.basename(out), "kept"
    proc = subprocess.run(["inkscape", "--export-type=svg", "--export-plain-svg",
                           "--export-filename=" + out, ai], capture_output=True)
    if proc.returncode or not os.path.exists(out) or not os.path.getsize(out):
        return os.path.basename(out), (proc.stderr.decode("utf-8", "replace").strip()
                                       or "inkscape produced nothing")
    return os.path.basename(out), "converted"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", help="the publisher's archive; unpacked next to --out")
    ap.add_argument("--ai", help="a directory of .ai files, if it is already unpacked")
    ap.add_argument("--out", default=os.path.join(ROOT, ".work", "hafs1422"))
    ap.add_argument("--force", action="store_true", help="re-convert pages already done")
    ap.add_argument("--workers", type=int, default=min(6, os.cpu_count() or 4))
    args = ap.parse_args(argv)

    if not shutil.which("inkscape"):
        raise SystemExit("inkscape is not on PATH")
    if not (args.zip or args.ai):
        ap.error("pass --zip or --ai")

    os.makedirs(args.out, exist_ok=True)
    ai_dir = extract(args.zip, args.out) if args.zip else args.ai
    raw_dir = os.path.join(args.out, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    jobs = []
    for name in sorted(os.listdir(ai_dir)):
        if not name.lower().endswith(".ai"):
            continue
        jobs.append((os.path.join(ai_dir, name),
                     os.path.join(raw_dir, os.path.splitext(name)[0] + ".svg"),
                     args.force))
    if not jobs:
        raise SystemExit("no .ai files in %s" % ai_dir)

    done, kept, failed = 0, 0, []
    with Pool(args.workers) as pool:
        for name, status in pool.imap_unordered(_convert, jobs, chunksize=1):
            if status == "converted":
                done += 1
            elif status == "kept":
                kept += 1
            else:
                failed.append((name, status.splitlines()[-1] if status else "?"))
    print("%d converted, %d already present, %d failed -> %s" % (done, kept, len(failed), raw_dir))
    for name, why in sorted(failed)[:20]:
        print("   FAILED %s  %s" % (name, why))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
