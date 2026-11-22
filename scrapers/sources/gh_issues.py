"""Source: GitHub issues / PRs — real user+hw+engine sitings.

`api.github.com/search/issues` (unauthenticated: ~10 searches/min) for a fixed set of
engine x hardware queries. A hit becomes a row only when:

  * the query token names the hardware unambiguously (exact token match in the title, or in
    the body for tokens that are unambiguous like `sm_120`, `gfx1100`, `"ARC B580"`), AND
  * the title/body carries a verdict: "works / supported / add support" -> solved,
    "error / fails / crash / broken / not supported / unsupported / hang" -> rejected.

Every row quotes the issue title (real, from the API) and, when matched in the body, the
exact sentence from the body. No inferred combinations: if the issue does not say it, we
skip it.
"""
from __future__ import annotations

import re

from scrapers.common import AS_OF, make_row

SOURCE_KEY = "gh_issues"
API = "https://api.github.com/search/issues"
REPORTED = f"scraper:{SOURCE_KEY}"

# (repo, runtime slug, query term, (vendor, arch) | list of them, match_in_body, label)
# Arches chosen so the query term maps to exactly one taxonomy arch. Rejected at spec time:
# "compute capability 7.5" (7.5 spans T4/RTX20xx -> several archs) and bare "M4"/"snapdragon"
# (too many matches, not necessarily hardware claims).
QUERIES = [
    ("ggml-org/llama.cpp", "llama.cpp", "sm_120", [("nvidia", "sm_120")], True, "sm_120"),
    ("ggml-org/llama.cpp", "llama.cpp", "gfx1100", [("amd", "gfx1100")], True, "gfx1100"),
    ("ggml-org/llama.cpp", "llama.cpp", "gfx942", [("amd", "gfx942")], True, "gfx942"),
    ("ggml-org/llama.cpp", "llama.cpp", "gfx90a", [("amd", "gfx90a")], True, "gfx90a"),
    ("ggml-org/llama.cpp", "llama.cpp", "gfx1030", [("amd", "gfx1030")], True, "gfx1030"),
    ("ggml-org/llama.cpp", "llama.cpp", '"ARC B580"', [("intel", "arc-b580")], True, "ARC B580"),
    ("ggml-org/llama.cpp", "llama.cpp", '"Arc A770"', [("intel", "arc-a770")], True, "Arc A770"),
    ("ggml-org/llama.cpp", "llama.cpp", "Ascend", [("other", "ascend-910b"), ("other", "ascend-310p")], True, "Ascend"),
    ("ggml-org/llama.cpp", "llama.cpp", '"RX 7900 XTX"', [("amd", "gfx1100")], True, "RX 7900 XTX"),
    ("ggml-org/llama.cpp", "llama.cpp", '"MI300X"', [("amd", "gfx942")], True, "MI300X"),
    ("ggml-org/llama.cpp", "llama.cpp", '"Strix Halo"', [("amd", "gfx1151")], True, "Strix Halo"),
    ("ggml-org/llama.cpp", "llama.cpp", 'sm_89', [("nvidia", "sm_89")], True, "sm_89"),
    ("ggml-org/llama.cpp", "llama.cpp", 'sm_75', [("nvidia", "sm_75")], True, "sm_75"),
    ("ggml-org/llama.cpp", "llama.cpp", '"Snapdragon X Elite"', [("qualcomm", "snapdragon-x-elite")], True, "Snapdragon X Elite"),
    ("ggml-org/llama.cpp", "llama.cpp", 'gfx1151', [("amd", "gfx1151")], True, "gfx1151"),
    ("ggml-org/llama.cpp", "llama.cpp", '"Xe2"', [("intel", "arc-b580")], True, "Xe2"),
    ("ggml-org/llama.cpp", "llama.cpp", "MUSA", [("other", "mtt-s4000"), ("other", "mtt-s5000")], True, "MUSA"),
    ("ggml-org/llama.cpp", "llama.cpp", "HIP", [("amd", "gfx1100"), ("amd", "gfx1030"), ("amd", "gfx90a")], False, "HIP"),
    ("ggml-org/llama.cpp", "llama.cpp", "Vulkan", [("intel", "arc-a770"), ("amd", "gfx1100"), ("nvidia", "sm_89")], False, "Vulkan"),
    ("vllm-project/vllm", "vllm", '"MI300X"', [("amd", "gfx942")], True, "MI300X"),
    ("vllm-project/vllm", "vllm", '"MI325X"', [("amd", "gfx942")], True, "MI325X"),
    ("vllm-project/vllm", "vllm", "gfx1100", [("amd", "gfx1100")], True, "gfx1100"),
    ("vllm-project/vllm", "vllm", "gfx1200", [("amd", "gfx1200")], True, "gfx1200"),
    ("vllm-project/vllm", "vllm", '"RTX 5090"', [("nvidia", "sm_120")], True, "RTX 5090"),
    ("vllm-project/vllm", "vllm", '"Intel Arc"', [("intel", "arc-a770"), ("intel", "arc-b580")], True, "Intel Arc"),
    ("vllm-project/vllm", "vllm", '"Apple Silicon"', [("apple", "m1")], True, "Apple Silicon"),
    ("vllm-project/vllm", "vllm", '"Ryzen AI MAX"', [("amd", "gfx1151"), ("amd", "gfx1150")], True, "Ryzen AI MAX"),
    ("vllm-project/vllm", "vllm", '"MI355X"', [("amd", "gfx950")], True, "MI355X"),
    ("vllm-project/vllm", "vllm", '"Strix Halo"', [("amd", "gfx1151")], True, "Strix Halo"),
    ("vllm-project/vllm", "vllm", '"XPU"', [("intel", "data-center-max-1550"), ("intel", "arc-a770")], True, "XPU"),
    ("ollama/ollama", "ollama", '"Snapdragon X Elite"', [("qualcomm", "snapdragon-x-elite")], True, "Snapdragon X Elite"),
    ("ollama/ollama", "ollama", "gfx1100", [("amd", "gfx1100")], True, "gfx1100"),
    ("ollama/ollama", "ollama", '"RTX 5090"', [("nvidia", "sm_120")], True, "RTX 5090"),
    ("ml-explore/mlx-lm", "mlx-lm", '"M4 Pro"', [("apple", "m4-pro")], True, "M4 Pro"),
    ("ml-explore/mlx-lm", "mlx-lm", '"M2 Ultra"', [("apple", "m2-ultra")], True, "M2 Ultra"),
    ("ml-explore/mlx-lm", "mlx-lm", '"M3 Max"', [("apple", "m3-max")], True, "M3 Max"),
    ("ml-explore/mlx-lm", "mlx-lm", '"M1 Max"', [("apple", "m1-max")], True, "M1 Max"),
    ("ml-explore/mlx-lm", "mlx-lm", '"M4 Max"', [("apple", "m4-max")], True, "M4 Max"),
    ("ml-explore/mlx", "mlx", '"M3 Max"', [("apple", "m3-max")], True, "M3 Max"),
    ("ml-explore/mlx", "mlx", '"M4 Max"', [("apple", "m4-max")], True, "M4 Max"),
    ("ollama/ollama", "ollama", '"Apple Silicon"', [("apple", "m1")], True, "Apple Silicon"),
    ("ggml-org/llama.cpp", "llama.cpp", '"M3 Max"', [("apple", "m3-max")], True, "M3 Max"),
    ("ggml-org/llama.cpp", "llama.cpp", '"M4 Max"', [("apple", "m4-max")], True, "M4 Max"),
]

# Verdict words are matched ONLY in the issue title. The body of an issue about card X
# routinely contains the word "error" while describing something unrelated ("intermittent
# hang, not reproducible"), and a PR body says "adds support" while the title says "compile
# bug". The title is the one-line claim; that is what we quote as the verdict.
# Tokens unique enough that a body match really identifies the card (e.g. "RX 6800 XT",
# "mi300x"). A generic body mention ("M4 Pro" in an unrelated thread) is not accepted.
BODY_TOKENS = {"RX 6800 XT", "RX 7900 XTX", "Strix Halo", "MI300X", "MI325X", "MI355X",
               "sm_120", "gfx1100", "gfx942", "gfx90a", "gfx1030", "ARC B580", "Arc A770"}

POS = re.compile(r"\b(works?|works? (?:great|well|fine|correctly)|working|supported|support for|add support|adds support|"
                 r"success(?:ful(?:ly)?)?|now (?:works|runs|supported)|"
                 r"enable[sd]? support|runs? (?:fine|correctly|successfully)|passing)\b", re.I)
NEG = re.compile(r"\b(bug|bugs|error|errors|fail|fails|failed|failing|crash|crashes|crashing|broken|"
                 r"regression|not supported|unsupported|not working|hang|hangs|missing|disable[sd]?)\b", re.I)


def _verdict(title: str) -> str | None:
    pos = bool(POS.search(title))
    neg = bool(NEG.search(title))
    if pos and not neg:
        return "solved"
    if neg and not pos:
        return "rejected"
    return None


def _sentences_with(text: str, token: str, limit: int = 2) -> list[str]:
    out = []
    for sent in re.split(r"(?<=[.!?])\s+|\n+", text):
        if token.lower() in sent.lower() and 20 <= len(sent.strip()) <= 400:
            out.append(sent.strip())
            if len(out) >= limit:
                break
    return out


def fetch(http):
    rows, rejects = [], []
    seen: set[str] = set()
    for repo, runtime, term, archs, body_ok, label in QUERIES:
        q = f"repo:{repo} {term}"
        url = f"{API}?q={q.replace(' ', '+').replace('\"', '%22')}&per_page=30&sort=created&order=desc"
        d = http.get_json(url, ttl_s=24 * 3600)
        if not d or "items" not in d:
            http.errors.append(f"search failed: {q}")
            continue
        for it in d["items"]:
            title = it.get("title") or ""
            body = it.get("body") or ""
            tok = term.strip('"')
            if tok.lower() not in (title + "\n" + body).lower():
                continue
            # The hardware must be named in the TITLE: a body hit alone is too weak (a PR that
            # merely mentions sm_120 in a test list is not a report about that card).
            in_title = (tok.lower() in title.lower()) or any(
                a.replace("-", " ").replace("_", " ") in title.lower() for _, a in archs)
            if not in_title:
                continue
            if tok.lower() not in title.lower() and tok not in BODY_TOKENS:
                continue
            verdict = _verdict(title)
            if not verdict:
                continue
            # which arch? only archs whose canonical name/token is what the query named
            cand = archs[0] if len(archs) == 1 else None
            if cand is None:
                for v, a in archs:
                    if a.replace("-", " ").replace("_", " ") in (title + "\n" + body).lower():
                        cand = (v, a)
                        break
                if cand is None:
                    continue
            vendor, arch = cand
            issue_url = it.get("html_url")
            ev = [{"url": issue_url, "kind": "issue", "quote": title}]
            quotes = [title] + (_sentences_with(body, tok) if body_ok else [])
            for qs in quotes[1:]:
                ev.append({"url": issue_url, "kind": "issue", "quote": qs})
            key = f"{vendor}/{arch}/{'*'}/{runtime}"
            if key in seen:
                continue
            seen.add(key)
            number = it.get("number")
            rows.append(make_row(
                hw_vendor=vendor, hw_arch=arch, model_family="*", runtime=runtime,
                status=verdict, source_kind="scraped", evidence=ev, reported_by=REPORTED,
                pointer=issue_url,
                notes=(f"Applies to all models (model_family '*'): this is an engine x hardware siting, "
                       f"not a per-model claim. GitHub {'PR' if it.get('pull_request') else 'issue'} {repo}#{number} "
                       f"({it.get('state')}, created {(it.get('created_at') or '')[:10]}) names {label} "
                       f"with a {'working' if verdict == 'solved' else 'failing'} report for {runtime}. "
                       "Community report, not an upstream support statement."),
                runtime_rev=None, missing=["model"],
                created_by="scraper",
                # as_of = when we observed this evidence, not when the issue was opened
                as_of=AS_OF,
            ))
    return rows, rejects
