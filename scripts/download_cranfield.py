"""Re-download the Cranfield collection (TREC-XML version) into data/cranfield/."""
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/oussbenk/cranfield-trec-dataset/main/"
FILES = ["cran.all.1400.xml", "cran.qry.xml", "cranqrel.trec.txt"]
out = Path(__file__).resolve().parents[1] / "data/cranfield"
out.mkdir(parents=True, exist_ok=True)
for f in FILES:
    print("fetching", f)
    urllib.request.urlretrieve(BASE + f, out / f)
print("done ->", out)
