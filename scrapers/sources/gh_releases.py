"""Source: GitHub releases — pinned runtime_rev provenance.

Loopback discipline: release notes usually do NOT state a hardware claim, so this source
emits almost no rows. Its real product is `scrapers/out/runtime_revs.json`: the release tag
(and an unambiguous hardware-token scan of the notes) that every other source used as
`runtime_rev`, so a row's pin is traceable to a published release.

A release only becomes a row when its notes name a hardware arch AND a verdict word in the
same bullet (e.g. "CUDA: add sm_120 support"). Those rows are `scraped` (notes + pointer).
"""
from __future__ import annotations

import json
import re

from scrapers.common import AS_OF, OUT, make_row

SOURCE_KEY = "gh_releases"
REPORTED = f"scraper:{SOURCE_KEY}"

REPOS = [
    ("ggml-org/llama.cpp", "llama.cpp"),
    ("vllm-project/vllm", "vllm"),
    ("ollama/ollama", "ollama"),
    ("ml-explore/mlx-lm", "mlx-lm"),
]

# unambiguous hardware tokens -> (vendor, arch). Only tokens that mean exactly one arch.
TOKENS = {
    "sm_120": ("nvidia", "sm_120"), "sm_121": ("nvidia", "sm_121"), "sm_100": ("nvidia", "sm_100"),
    "sm_89": ("nvidia", "sm_89"), "sm_90": ("nvidia", "sm_90"), "sm_86": ("nvidia", "sm_86"),
    "gfx1100": ("amd", "gfx1100"), "gfx1101": ("amd", "gfx1101"), "gfx1200": ("amd", "gfx1200"),
    "gfx1201": ("amd", "gfx1201"), "gfx942": ("amd", "gfx942"), "gfx950": ("amd", "gfx950"),
    "gfx90a": ("amd", "gfx90a"), "gfx1151": ("amd", "gfx1151"), "gfx1030": ("amd", "gfx1030"),

    "ARC B580": ("intel", "arc-b580"), "Arc B580": ("intel", "arc-b580"),
    "Arc A770": ("intel", "arc-a770"), "Lunar Lake": ("intel", "arc-igpu-lunar-lake"),
    "Arrow Lake": ("intel", "arc-igpu-arrow-lake"), "Meteor Lake": ("intel", "arc-igpu-meteor-lake"),
    "Strix Halo": ("amd", "gfx1151"),
    # product names that map to exactly one arch via taxonomy hw_aliases
    "MI350X": ("amd", "gfx950"), "MI325X": ("amd", "gfx942"), "MI300X": ("amd", "gfx942"),
}
POS = re.compile(r"\b(support|supports|supported|works|working|enabled?|improve[sd]?|fix(?:es|ed)?|speedup)\b", re.I)


def fetch(http):
    rows = []
    revs = {}
    budget = 2
    for repo, runtime in REPOS:
        latest = http.get_json(f"https://api.github.com/repos/{repo}/releases/latest", ttl_s=6 * 3600)
        rels = http.get_json(f"https://api.github.com/repos/{repo}/releases?per_page=5", ttl_s=6 * 3600)
        if latest:
            revs[repo] = {"runtime": runtime, "tag": latest.get("tag_name"),
                          "published_at": latest.get("published_at"),
                          "url": latest.get("html_url"),
                          "assets": [a.get("name") for a in (latest.get("assets") or [])][:12]}
        seen = set()
        for rel in (rels or [])[:budget]:
            tag = rel.get("tag_name")
            if not tag or tag in seen:
                continue
            seen.add(tag)
            body = rel.get("body") or ""
            url = rel.get("html_url")
            for line in body.split("\n"):
                s = line.strip()
                if len(s) < 15 or not POS.search(s):
                    continue
                for tok, (vendor, arch) in TOKENS.items():
                    # exact arch / product token: boundaries so "MI350" never swallows "MI355X"
                    if re.search(r"(?<![A-Za-z0-9])" + re.escape(tok) + r"(?![A-Za-z0-9])", s):
                        rows.append(make_row(
                            hw_vendor=vendor, hw_arch=arch, model_family="*", runtime=runtime,
                            status="solved", source_kind="scraped",
                            evidence=[{"url": url, "kind": "release", "quote": s[:400]}],
                            reported_by=REPORTED, pointer=url, runtime_rev=tag,
                            missing=["model"],
                            notes=(f"Release {tag} of {repo} names {tok} in a change bullet. "
                                   "Applies to all models (engine x hardware claim)."),
                            as_of=AS_OF,
                            created_by="scraper"))
                        break
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "runtime_revs.json").write_text(json.dumps(revs, indent=1, sort_keys=True) + "\n")
    return rows, []
