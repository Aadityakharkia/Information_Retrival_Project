"""Build the CSD358 course-project submission ZIP.

    python scripts/make_submission.py --pdf ~/Downloads/searchbridge_ieee.pdf

Creates submission/CSD358_AadityaKharkia_PrekshaChavan_AdityaChauhan.zip containing
  Report/      the report PDF, its LaTeX source and the GitHub link
  SourceCode/  the committed source code (git HEAD, without the data folder)
  Dataset/     the collections the app and experiments use, with their sources
  README.md    team, how to run, what is where
Only committed code is packed, so commit (and push) before running it.
"""
from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "CSD358_AadityaKharkia_PrekshaChavan_AdityaChauhan"
GITHUB = "https://github.com/Aadityakharkia/Information_Retrival_Project"
TEAM = [("Aaditya Kharkia", "2410110492", "ak897@snu.edu.in"),
        ("Preksha Chavan", "2410110590", "pc782@snu.edu.in"),
        ("Aditya Chauhan", "2410110504", "ac830@snu.edu.in")]
DATASETS = ["cranfield", "dblp", "bbc", "cs_papers", "web", "sample", "ontology.json"]

DATASET_README = """# Datasets

| Folder | Documents | Source | Licence / note |
|---|---|---|---|
| dblp/ | 21,000 papers, 165,793 citations, 6 fields | Sampled from DBLP-Citation-network V12 (AMiner, Tang et al. 2008; Kaggle "Citation Network Dataset") with scripts/prepare_dblp.py | CC BY-NC-SA 4.0 |
| bbc/ | 2,225 news articles, 5 topics | BBC full-text classification dataset (Greene & Cunningham 2006), converted with scripts/prepare_bbc.py | research use |
| cranfield/ | 1,400 abstracts, 225 judged queries | Cranfield 1400 test collection (Cleverdon 1967) | research use |
| cs_papers/ | 2,243 papers | SemEval-2010 Task 5 (243 ACM papers) and Inspec (2,000 abstracts) | research use |
| web/ | 200 pages, 2,428 links | Our own polite crawl of Wikipedia (scripts/crawl_web.py) | CC BY-SA (Wikipedia) |
| sample/ | sample documents for "My Library" | written for this project | |

The raw 12 GB DBLP dump is not included; scripts/prepare_dblp.py rebuilds dblp/ from it.
Place this folder's contents in searchbridge-ai/data/ (the source code expects data/<collection>/).
"""


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", required=True, type=Path, help="the compiled report PDF (e.g. downloaded from Overleaf)")
    ap.add_argument("--out", type=Path, default=ROOT / "submission")
    a = ap.parse_args(argv)
    if not a.pdf.expanduser().is_file():
        sys.exit(f"Report PDF not found: {a.pdf}")
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True, text=True).stdout
    if dirty.strip():
        print("Warning: uncommitted changes are NOT included (only git HEAD is packed):\n" + dirty)

    stage = a.out / NAME
    shutil.rmtree(stage, ignore_errors=True)
    (stage / "Report").mkdir(parents=True)

    # Report
    shutil.copy2(a.pdf.expanduser(), stage / "Report" / f"{NAME}_Report.pdf")
    (stage / "Report" / "GITHUB_LINK.txt").write_text(GITHUB + "\n")
    src = ROOT / "docs/report"
    shutil.copytree(src, stage / "Report" / "latex_source", ignore=shutil.ignore_patterns("*.zip", ".*"))

    # Source code: committed files only, without the data folder (packed separately)
    tar = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, capture_output=True, check=True).stdout
    code = stage / "SourceCode" / "searchbridge-ai"
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        members = [m for m in t.getmembers() if not m.name.startswith(("data/", ".agents/")) and not m.issym() and not m.islnk()]
        t.extractall(code, members=members, filter="data")

    # Dataset
    ds = stage / "Dataset"
    ds.mkdir()
    for name in DATASETS:
        p = ROOT / "data" / name
        if p.is_dir():
            shutil.copytree(p, ds / name, ignore=shutil.ignore_patterns(".*", "*.tmp"))
        elif p.is_file():
            shutil.copy2(p, ds / name)
    (ds / "README.md").write_text(DATASET_README)

    team = "\n".join(f"| {n} | {r} | {e} |" for n, r, e in TEAM)
    (stage / "README.md").write_text(f"""# SearchBridge AI — CSD358 Information Retrieval project

| Member | Roll no. | Email |
|---|---|---|
{team}

GitHub: {GITHUB}

## Contents
- `Report/` — the report (PDF), its LaTeX source and the GitHub link
- `SourceCode/searchbridge-ai/` — the full source code
- `Dataset/` — the collections used (see Dataset/README.md)

## Run it (macOS / Linux)
1. Copy the contents of `Dataset/` into `SourceCode/searchbridge-ai/data/`.
2. In `SourceCode/searchbridge-ai/`, run `./start.sh`. It creates a virtual environment, installs the
   requirements and opens http://127.0.0.1:8000 (the first start indexes the collections in a few minutes).
3. Tests: `python -m pytest`. Benchmarks: `python experiments/run_benchmark.py`.
""")

    zip_path = a.out / f"{NAME}.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(stage.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(a.out))
    print(f"Wrote {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
