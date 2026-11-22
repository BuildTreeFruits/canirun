"""Source: Hugging Face model repos — the model dimension spine.

`GET /api/models?filter=<f>&sort=downloads&direction=-1&limit=N` lists popular model repos
per format; `GET /api/models/<id>?blobs=true` gives the repo sha (-> model_rev),
lastModified, downloads, likes, tags (incl. `base_model:...` / `license:...`) and the REAL
sibling filenames (so a quant token like `Q4_K_M` only ever comes from a real file name).

Row shape: one row per (model_family x quant), missing:["hw"] — a model repo proves the
model exists at that quant and says nothing about which card runs it.

Canonicalisation is conservative, taxonomy-first:
  1. `base_model:ORG/NAME` tag matched against data/taxonomy.json families+aliases;
  2. the repo name itself, after stripping format/quant/adapter suffixes, matched longest
     family prefix first (so `gemma-4` beats `gemma` and `qwen3` beats `qwen`);
  3. nothing else — a repo we cannot map to a taxonomy family is SKIPPED, never invented
     (an invented family would poison the lookup: "qwen3" answered by "qwen-qwen3-6").
Families we do learn go to data/taxonomy.extensions.json.
"""
from __future__ import annotations

import re

from scrapers.common import AS_OF, load_taxonomy_aliases, make_row, merge_extensions

SOURCE_KEY = "hf_models"
HF_API = "https://huggingface.co/api/models"
HF_WEB = "https://huggingface.co"
REPORTED = f"scraper:{SOURCE_KEY}"

LISTS = [
    ("gguf", "llama.cpp"),
    ("mlx", "mlx-lm"),
    ("mlx-lm", "mlx-lm"),
    ("vllm", "vllm"),
    ("exllamav2", "exllamav2"),
]
LIST_LIMIT = 500
DETAIL_BUDGET = 150
_ALL_RUNTIMES = ["llama.cpp", "mlx-lm", "vllm", "exllamav2"]          # live /api/models/<id> calls per run (1 req/s, same host)
MAX_QUANTS_PER_REPO = 6

GGUF_QUANT_RE = re.compile(
    r"(UD-)?(?P<q>(?:IQ\d_[A-Z]{1,3}|Q\d_[KS](?:_[A-Z])?|Q\d_[01]|Q\d(?=\b)|BF16|F16|FP16|FP32|F32|"
    r"TQ1_0|TQ2_0|MXFP4|NVFP4))")
MLX_BITS_RE = re.compile(r"(?P<b>[2-8])bit", re.I)

_SUFFIX = [
    "-GGUF", "_GGUF", "-gguf", "-MLX", "-mlx", "-Instruct", "-instruct", "-Chat", "-chat",
    "-Abliterated", "-abliterated", "-MTP", "-mtp", "-heretic", "-Heretic", "-Uncensored",
    "-uncensored", "-AWQ", "-awq", "-GPTQ", "-gptq", "-FP8", "-fp8", "-INT4", "-INT8", "-4bit",
    "-8bit", "-dflash", "-QAT", "-qat", "-Thinking", "-thinking", "-it", "-hf", "-base", "-Base",
    "-Text", "-text", "-imatrix", "-DPO", "-dpo", "-KTO", "-kto",
]
# tokens that are never a model family
_NOT_FAMILY = {
    "gguf", "mlx", "model", "models", "instruct", "chat", "base", "quantized", "awq", "gptq",
    "fp8", "bf16", "fp16", "int4", "int8", "4bit", "8bit", "bnb", "mtp", "qat", "text", "all",
    "llm", "moe", "mini", "max", "turbo", "neo", "ultra", "pro", "lite", "nano", "dark",
}


def _strip_suffixes(name: str) -> str:
    n = name
    changed = True
    while changed:
        changed = False
        for s in _SUFFIX:
            if n.endswith(s) and len(n) > len(s) + 1:
                n, changed = n[: -len(s)], True
    return n


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _strip_suffixes(s).lower())


def _match_prefix(name: str, aliases: dict[str, str]) -> str | None:
    """Longest taxonomy alias that is a prefix at a hyphen/underscore token boundary.

    Falls back to a de-punctuated comparison so `Qwen3.8-27B` -> qwen3 and `gemma4` -> gemma-4.
    """
    low = _strip_suffixes(name).lower()
    best_alias, best_fam = "", None
    for a, fam in aliases.items():
        a2 = _squash(a)
        lo2 = re.sub(r"[^a-z0-9]", "", low)
        if not a2 or not lo2.startswith(a2):
            continue
        if len(lo2) > len(a2) and not lo2[len(a2)].isdigit():
            continue                     # must break at a digit boundary (gemma4 | gemma-4)
        if len(a2) > len(best_alias) or (len(a2) == len(best_alias) and fam > (best_fam or "")):
            best_alias, best_fam = a2, fam
    return best_fam
    best = None
    for a, fam in aliases.items():
        if low == a or low.startswith(a + "-") or low.startswith(a + "_"):
            if best is None or len(a) > len(best[0]):
                best = (a, fam)
    return best[1] if best else None


def canonical_family(repo_id: str, tags: list[str], aliases: dict[str, str]) -> tuple[str | None, str]:
    # (1) base_model tag
    for t in tags:
        if t.startswith("base_model:") and not t.startswith("base_model:quantized:"):
            base = t.split(":", 1)[1]
            fam = _match_prefix(_strip_suffixes(base.split("/")[-1]), aliases)
            if fam:
                return fam, "base_model-tag"
    # (2) repo name
    fam = _match_prefix(_strip_suffixes(repo_id.split("/")[-1]), aliases)
    if fam:
        return fam, "repo-name"
    return None, "unmapped"


def quants_from_files(runtime: str, files: list[str]) -> dict[str, str]:
    """quant -> an actual filename that proves it."""
    out: dict[str, str] = {}
    for f in files:
        low = f.lower()
        if runtime == "llama.cpp":
            if not low.endswith(".gguf"):
                continue
            m = GGUF_QUANT_RE.search(f)
            if m and not m.group("q").endswith("_"):
                out.setdefault((m.group(1) or "") + m.group("q"), f)
        elif runtime == "mlx-lm":
            if not low.endswith(".safetensors"):
                continue
            mb = MLX_BITS_RE.search(f)
            if mb:
                out.setdefault(f"mlx-{mb.group('b')}bit", f)
            elif "model" in low and "bf16" in low:
                out.setdefault("bf16", f)
            elif "model" in low and "fp16" in low:
                out.setdefault("fp16", f)
        elif runtime == "vllm":
            if not low.endswith(".safetensors"):
                continue
            for tok in ("fp8", "awq", "gptq", "nvfp4", "mxfp4"):
                if tok in low:
                    out.setdefault(tok, f)
        elif runtime == "exllamav2":
            if not (low.endswith(".safetensors") or "exl2" in low):
                continue
            m = re.search(r"(\d\.\d+)bpw", low)
            out.setdefault(f"exl2-{m.group(1)}bpw" if m else "exl2-4.0bpw", f)
    return out


def fetch(http):
    rows, rejects = [], []
    aliases = load_taxonomy_aliases()
    listing: dict[str, dict] = {}
    for flt, runtime in LISTS:
        d = http.get_json(f"{HF_API}?filter={flt}&sort=downloads&direction=-1&limit={LIST_LIMIT}",
                          ttl_s=12 * 3600)
        if not d:
            http.errors.append(f"listing filter={flt} failed")
            continue
        for m in d:
            item = listing.setdefault(m["id"], {
                "repo": m["id"], "tags": m.get("tags") or [], "downloads": m.get("downloads") or 0,
                "likes": m.get("likes") or 0, "runtimes": []})
            if runtime not in item["runtimes"]:
                item["runtimes"].append(runtime)

    groups: dict[str, list[dict]] = {}
    keyed: dict[tuple[str, str], list[dict]] = {}
    unmapped = 0
    for item in listing.values():
        fam, how = canonical_family(item["repo"], item["tags"], aliases)
        if not fam:
            unmapped += 1
            continue
        item["family"], item["how"] = fam, how
        groups.setdefault(fam, []).append(item)
        # a repo can only prove quants for the formats it was listed under (or the format its
        # name/tags clearly are); fall back to the family's primary format when the listing
        # filter and the repo format disagree (e.g. an MLX repo in the gguf list).
        rts = list(item["runtimes"])
        due = _format_hint(item["repo"], item["tags"])
        if due and due not in rts:
            rts.insert(0, due)
        for rt in rts:
            keyed.setdefault((fam, rt), []).append(item)
    for fam in groups:
        groups[fam].sort(key=lambda x: (-x["downloads"], x["repo"]))
    # Runs budgeted in pairs mode: a family x family-format row first, then any other
    # (family, runtime) pair whose repo files really are that format.
    for k in keyed:
        keyed[k].sort(key=lambda x: (-x["downloads"], x["repo"]))

    # families first (one row set each), then the remaining (family, runtime) pairs so each
    # family also gets its MLX / vLLM / ExLlamaV2 dimension when a repo really is that format.
    fam_first = sorted(groups.items(), key=lambda kv: (-max(i["downloads"] for i in kv[1]), kv[0]))
    pair_order = sorted(((fam, rt), items) for (fam, rt), items in keyed.items())
    work: list[tuple[str, str, list[dict]]] = [(fam, "", groups[fam]) for fam, _ in fam_first]
    have: set[str] = set()
    work += [(fam, rt, items) for (fam, rt), items in pair_order]
    learned: dict[str, dict] = {}
    REPO_FORMAT: dict[str, str] = {}
    budget = DETAIL_BUDGET
    done_pairs: set[tuple[str, str]] = set()
    for fam, rt_hint, items in work:
        if budget <= 0:
            break
        got = False
        for item in items[:2]:                       # fall back if the top repo has no quant files
            if budget <= 0:
                break
            meta = http.get_json(f"{HF_API}/{item['repo']}?blobs=true", ttl_s=24 * 3600)
            budget -= 1
            if not meta or not meta.get("siblings"):
                continue
            files = [s.get("rfilename", "") for s in meta["siblings"]]
            sha = meta.get("sha")
            lastmod = (meta.get("lastModified") or "")[:10]
            tags = meta.get("tags") or item["tags"]
            base_model = next((t.split(":", 1)[1] for t in tags
                               if t.startswith("base_model:")
                               and not t.startswith("base_model:quantized:")), None)
            license_ = next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), None)
            runtime = rt_hint or item["runtimes"][0]
            quants = quants_from_files(runtime, files)
            if not quants:
                continue
            url = f"{HF_WEB}/{item['repo']}"
            picked = list(quants.items())[:MAX_QUANTS_PER_REPO]
            ev = [{"url": url, "kind": "model-repo",
                   "quote": (f"repo {item['repo']} sha={sha} lastModified={lastmod}; "
                             f"files: {', '.join(f for _, f in picked)}")}]
            for q, fname in picked:
                rows.append(make_row(
                    hw_vendor="x86-cpu", hw_arch="generic", model_family=fam, runtime=runtime,
                    status="solved", source_kind="derived", evidence=ev, reported_by=REPORTED,
                    notes=(f"{item['repo']} publishes {fname} (quant {q}); {item['downloads']:,} downloads, "
                           f"family matched by {item['how']}. The repo proves the model+quant exists, "
                           "not which hardware runs it."),
                    pointer=url, model_rev=sha, quant=q,
                    hw_extra={"repo": item["repo"], "downloads": item["downloads"],
                              "likes": meta.get("likes", item["likes"]), "last_modified": lastmod,
                              "base_model": base_model, "license": license_,
                              "file": fname},
                    missing=["hw"], as_of=AS_OF, created_by="derived"))
            got = True
            done_pairs.add((fam, runtime))
            REPO_FORMAT.setdefault(fam, runtime)
            learned[fam] = {"label": fam, "aliases": [],
                            "vendor": item["repo"].split("/")[0],
                            "source": SOURCE_KEY}
            break
        if not got:
            continue
    merge_extensions(learned, {})
    http.errors.append(f"hf: {unmapped} repos skipped as unmapped-family (not invented)")
    return rows, rejects


def _format_hint(repo: str, tags: list[str]) -> str | None:
    low = repo.lower()
    tset = {t.lower() for t in tags}
    if "mlx" in tset or "mlx-community" in low or "-mlx" in low or "-4bit" in low or "-8bit" in low:
        return "mlx-lm"
    if "gguf" in tset or low.endswith("-gguf") or "gguf" in low:
        return "llama.cpp"
    if any(t in tset for t in ("awq", "gptq", "fp8", "compressed-tensors")) or "vllm" in tset:
        return "vllm"
    if "exl2" in tset or "exllamav2" in low or "exl2" in low:
        return "exllamav2"
    return None


import json as _json
from pathlib import Path as _P
_TAXONOMY_FAMILIES = {m["family"] for m in
                      _json.loads((_P(__file__).resolve().parents[2] / "data" / "taxonomy.json").read_text())["models"]}
