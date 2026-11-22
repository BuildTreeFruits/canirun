"""Source: vLLM upstream installation docs.

Fetches the live mkdocs "hardware tabs" from vllm-project/vllm main:
  docs/getting_started/installation/gpu.md          (tab container)
  gpu.cuda.inc.md / gpu.rocm.inc.md / gpu.apple.inc.md / gpu.xpu.inc.md
  cpu.md + cpu.apple.inc.md / cpu.arm.inc.md / cpu.x86.inc.md / cpu.s390x.inc.md

Emits:
  - the ROCm prebuilt-wheel table as `package-table` rows keyed on the architectures the
    requirements section names for each wheel variant (rocm700/rocm721/rocm72/rocm100);
  - one row per architecture explicitly named in a requirements section
    (gfx targets, compute capability / named CUDA cards, Intel DC GPU / Arc, Apple Silicon);
  - CPU rows for the ISA corners the docs make claims about (AVX-512/AVX2 x86, NEON arm64,
    BF16 on ARMv8.6-A, s390x VXE/z15, AMD Zen 4/5 zentorch).
Every quote is re-verified against the fetched text.
"""
from __future__ import annotations

import re

from scrapers.common import make_row, verbatim

SOURCE_KEY = "vllm_install"
RAW = "https://raw.githubusercontent.com/vllm-project/vllm/main"
BLOB = "https://github.com/vllm-project/vllm/blob/main"
RUNTIME = "vllm"
REPORTED = f"scraper:{SOURCE_KEY}"

FILES = [
    "docs/getting_started/installation/gpu.md",
    "docs/getting_started/installation/gpu.cuda.inc.md",
    "docs/getting_started/installation/gpu.rocm.inc.md",
    "docs/getting_started/installation/gpu.apple.inc.md",
    "docs/getting_started/installation/gpu.xpu.inc.md",
    "docs/getting_started/installation/cpu.md",
    "docs/getting_started/installation/cpu.apple.inc.md",
    "docs/getting_started/installation/cpu.arm.inc.md",
    "docs/getting_started/installation/cpu.x86.inc.md",
    "docs/getting_started/installation/cpu.s390x.inc.md",
]

# ROCm requirements line -> (hw_arch, hw_name, rocm_min from the requirements bullets)
ROCM_GFX = [
    ("gfx90a", "MI200s (MI210/MI250/MI250X, gfx90a)", None),
    ("gfx942", "MI300 / MI325X (gfx942)", None),
    ("gfx950", "MI350 / MI355X (gfx950)", "7.0"),
    ("gfx1100", "Radeon RX 7900 series (gfx1100/1101)", None),
    ("gfx1101", "Radeon RX 7900 (gfx1101)", None),
    ("gfx1200", "Radeon RX 9000 series (gfx1200/1201)", None),
    ("gfx1201", "Radeon RX 9000 (gfx1201)", None),
    ("gfx1151", "Ryzen AI MAX / AI 300 (gfx1151/1150)", "7.0.2"),
    ("gfx1150", "Ryzen AI 300 (gfx1150)", "7.0.2"),
]


def latest_rev(http):
    d = http.get_json("https://api.github.com/repos/vllm-project/vllm/releases/latest")
    tag = (d or {}).get("tag_name")
    if not tag or tag.strip().lower() in ("latest", "master", "main", "head", ""):
        return None
    return tag


def parse_wheels(txt):
    """Parse the `#### Prebuilt Wheels` markdown table -> list of dicts."""
    m = re.search(r"#### Prebuilt Wheels\s*\n\n(\|.*?\n)\n", txt, re.S)
    if not m:
        return [], None
    block = m.group(1)
    lines = [ln for ln in block.strip().split("\n") if ln.strip().startswith("|")]
    hdr = [c.strip() for c in lines[0].strip("|").split("|")]
    out = []
    for ln in lines[2:]:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) != len(hdr):
            continue
        out.append(dict(zip(hdr, cells)))
    return out, block.strip()


def fetch(http):
    rows, rejects = [], []
    docs = {}
    for f in FILES:
        t = http.get_text(f"{RAW}/{f}", ttl_s=3600)
        if t:
            docs[f] = t
    rev = latest_rev(http)
    if not rev:
        http.errors.append("no vLLM release tag -> runtime_rev null")

    def add(path, *, hw, quotes, notes, kind="upstream-doc", pointer=None,
            status="solved", source_kind="scraped", missing=("model",), model_family="*",
            extra_ev=()):
        url = f"{BLOB}/{path}"
        ev = [{"url": url, "quote": q, "kind": kind} for q in quotes] + list(extra_ev)
        rows.append(make_row(
            hw_vendor=hw["hw_vendor"], hw_arch=hw["hw_arch"], model_family=model_family,
            runtime=RUNTIME, status=status, source_kind=source_kind, evidence=ev,
            reported_by=REPORTED, notes=notes, pointer=pointer or url,
            hw_name=hw.get("hw_name"), hw_extra=hw.get("hw_extra", {}),
            runtime_rev=rev, missing=list(missing), created_by="derived"))

    # ------------------------------------------------------------ CUDA
    cu = "docs/getting_started/installation/gpu.cuda.inc.md"
    if cu in docs:
        t = docs[cu]
        cc = verbatim(t, "- GPU: compute capability 7.5 or higher (e.g., T4, RTX20xx, A100, L4, H100, B200, etc.)")
        bins = verbatim(t, "vLLM contains pre-compiled C++ and CUDA (13.0) binaries.")
        for arch, name in [
            ("sm_75", "Turing: T4, RTX 20xx (CC 7.5)"),
            ("sm_80", "Ampere datacenter: A100 (CC 8.0)"),
            ("sm_89", "Ada: L4, RTX 4090 (CC 8.9)"),
            ("sm_90", "Hopper: H100 (CC 9.0)"),
            ("sm_100", "Blackwell datacenter: B200 (CC 10.0)"),
        ]:
            add(cu, hw={"hw_vendor": "nvidia", "hw_arch": arch, "hw_name": name,
                        "hw_extra": {"backend": "CUDA", "cuda": "13.0 wheel"}},
                quotes=[cc, bins],
                notes="vLLM CUDA wheels: pre-compiled CUDA 13.0 binaries; the requirements list names this "
                      "card class and sets the floor at compute capability 7.5.")

    # ------------------------------------------------------------ ROCm
    ro = "docs/getting_started/installation/gpu.rocm.inc.md"
    if ro in docs:
        t = docs[ro]
        req = verbatim(t, "- GPU: MI200s (gfx90a), MI300 (gfx942), MI350 (gfx950), Radeon RX 7900 series (gfx1100/1101), Radeon RX 9000 series (gfx1200/1201), Ryzen AI MAX / AI 300 Series (gfx1151/1150)")
        rocm63 = verbatim(t, "vLLM supports AMD GPUs with ROCm 6.3 or above. Pre-built wheels are available for ROCm 10.0; ROCm 7.2 wheels remain available for earlier releases.")
        mi350 = verbatim(t, "- MI350 requires ROCm 7.0 or above")
        ryzen = verbatim(t, "- Ryzen AI MAX / AI 300 Series requires ROCm 7.0.2 or above")
        wheels, wheel_block = parse_wheels(t)
        wheel_quotes = [req, rocm63]
        if wheel_block:
            wheel_quotes.append(verbatim(t, wheel_block))
        for arch, name, rocm_min in ROCM_GFX:
            extra_quotes = []
            if rocm_min == "7.0":
                extra_quotes.append(mi350)
            if rocm_min == "7.0.2":
                extra_quotes.append(ryzen)
            add(ro, hw={"hw_vendor": "amd", "hw_arch": arch, "hw_name": name,
                        "hw_extra": {"backend": "ROCm", **({"rocm_min": rocm_min} if rocm_min else {})}},
                quotes=wheel_quotes + extra_quotes,
                notes=f"vLLM ROCm: requirements section lists {name} as a supported GPU"
                      + (f" (ROCm {rocm_min}+)" if rocm_min else "")
                      + "; prebuilt wheels are published per ROCm variant (rocm700/rocm721/rocm72/rocm100).")

    # ------------------------------------------------------------ wheel-variant side file
    # The ROCm prebuilt-wheel table is a (variant x python x ROCm x glibc x supported-versions)
    # fact, not a hardware claim per se, and one row id cannot carry four variants.
    # Emit it to out/vllm_install.wheels.json for the pipeline/export to consume as a side file.
    wheel_facts = []
    if ro in docs:
        wheels, _ = parse_wheels(docs[ro])
        for w in wheels:
            wheel_facts.append({
                "runtime": RUNTIME, "runtime_rev": rev,
                "wheel_variant": w.get("ROCm Variant", "").strip("`"),
                "python": w.get("Python Version"), "rocm": w.get("ROCm Version"),
                "glibc_min": w.get("glibc Requirement", "").replace(">=", "").strip(),
                "supported_versions": w.get("Supported Versions"),
                "url": f"{BLOB}/{ro}#prebuilt-wheels",
            })
    import json as _json
    from pathlib import Path as _P
    _p = _P(__file__).resolve().parents[1] / "out" / "vllm_install.wheels.json"
    _p.write_text(_json.dumps(wheel_facts, indent=1) + "\n")

    # ------------------------------------------------------------ Apple
    ap = "docs/getting_started/installation/gpu.apple.inc.md"
    if ap in docs:
        t = docs[ap]
        add(ap, hw={"hw_vendor": "apple", "hw_arch": "m1", "hw_name": "Apple M1 family (Metal via vLLM-Metal)",
                    "hw_extra": {"backend": "Metal"}},
            quotes=[verbatim(t, "- Hardware: Apple Silicon"),
                    verbatim(t, "vLLM-Metal works with MLX-optimized models from the [mlx-community](https://huggingface.co/mlx-community) organization on Hugging Face")],
            notes="vLLM's Apple GPU path is the vLLM-Metal plugin: Apple Silicon + Metal, runs MLX-optimized "
                  "mlx-community models. Doc says Apple Silicon, not an M-generation; arch is the baseline M1 family.",
            pointer="https://github.com/vllm-project/vllm-metal")

    # ------------------------------------------------------------ XPU
    xp = "docs/getting_started/installation/gpu.xpu.inc.md"
    if xp in docs:
        t = docs[xp]
        add(xp, hw={"hw_vendor": "intel", "hw_arch": "data-center-max-1550",
                    "hw_name": "Intel Data Center GPU (Max series) — XPU",
                    "hw_extra": {"backend": "XPU"}},
            quotes=[verbatim(t, "- Supported Hardware: Intel Data Center GPU, Intel ARC GPU"),
                    verbatim(t, "vLLM initially supports basic model inference and serving on Intel GPU platform.")],
            notes="vLLM XPU: supports Intel Data Center GPU and Intel ARC GPU via vllm-xpu-kernels.")
        add(xp, hw={"hw_vendor": "intel", "hw_arch": "arc-a770", "hw_name": "Intel Arc GPU — XPU",
                    "hw_extra": {"backend": "XPU"}},
            quotes=[verbatim(t, "- Supported Hardware: Intel Data Center GPU, Intel ARC GPU")],
            notes="vLLM XPU: supports Intel ARC GPUs via vllm-xpu-kernels.")

    # ------------------------------------------------------------ CPU: x86
    xx = "docs/getting_started/installation/cpu.x86.inc.md"
    if xx in docs:
        t = docs[xx]
        avx = verbatim(t, "- CPU flags: `avx512f` (Recommended), `avx2` (Limited features)")
        add(xx, hw={"hw_vendor": "x86-cpu", "hw_arch": "x86-64-avx512", "hw_name": "x86-64 with AVX-512",
                    "hw_extra": {"backend": "CPU"}},
            quotes=[avx], notes="vLLM CPU (x86): AVX-512 is the recommended target.")
        add(xx, hw={"hw_vendor": "x86-cpu", "hw_arch": "x86-64-avx2", "hw_name": "x86-64 with AVX2 only",
                    "hw_extra": {"backend": "CPU", "features": "limited"}},
            quotes=[avx], notes="vLLM CPU (x86): AVX2-only CPUs work with limited features.")

    # ------------------------------------------------------------ CPU: Zen (AMD)
    cp = "docs/getting_started/installation/cpu.md"
    if cp in docs:
        t = docs[cp]
        zen = verbatim(t, "On an AMD Zen 4 / Zen 5 CPU, install the CPU wheel with the `zen` extra so vLLM pulls the tested `zentorch` version for that release:")
        nofp16 = verbatim(t, "On AMD Zen CPUs (`ZenCpuPlatform`), `float16` requires AVX512-FP16, available from Venice (6th Gen EPYC) onwards. On Turin (5th Gen EPYC) and earlier only `bfloat16` and `float32` are accepted")
        for arch, name in [("x86-64-amd-zen4", "AMD Zen 4 (EPYC 9004 / Genoa, Ryzen 7000)"),
                           ("x86-64-amd-zen5", "AMD Zen 5 (EPYC 9005 / Turin)")]:
            add(cp, hw={"hw_vendor": "x86-cpu", "hw_arch": arch, "hw_name": name,
                        "hw_extra": {"backend": "CPU", "extra": "zen (zentorch)"}},
                quotes=[zen, nofp16],
                notes="vLLM CPU: AMD Zen 4/5 get the `zen` extra (zentorch, ZenDNN-backed GEMMs); float16 needs "
                      "AVX512-FP16 (Venice / EPYC 6th gen), earlier Zen is bf16/f32 only.")
        add(cp, hw={"hw_vendor": "x86-cpu", "hw_arch": "x86-64-amd-zen5", "hw_name": "AMD EPYC Venice (Zen 6) f16 path",
                    "hw_extra": {"backend": "CPU", "dtype_fp16": True}},
            quotes=[nofp16],
            notes="vLLM CPU: float16 is accepted from Venice (6th Gen EPYC) onwards because AVX512-FP16 exists there.")

    # ------------------------------------------------------------ CPU: ARM
    ar = "docs/getting_started/installation/cpu.arm.inc.md"
    if ar in docs:
        t = docs[ar]
        neon = verbatim(t, "- Instruction Set Architecture (ISA): NEON support is required")
        add(ar, hw={"hw_vendor": "arm-cpu", "hw_arch": "aarch64-neon", "hw_name": "ARM AArch64 with NEON",
                    "hw_extra": {"backend": "CPU"}},
            quotes=[neon], notes="vLLM CPU (ARM AArch64): NEON is the required ISA baseline.")
        bf16 = re.search(r"!!! note \"ARM BF16 requirements\"\s*\n\s*(.+?)\n", t)
        if bf16:
            add(ar, hw={"hw_vendor": "arm-cpu", "hw_arch": "aarch64-bf16", "hw_name": "ARMv8.6-A with FEAT_BF16 (Graviton3/4, AmpereOne)",
                        "hw_extra": {"backend": "CPU"}},
                quotes=[verbatim(t, bf16.group(1).strip())],
                notes="vLLM CPU (ARM): BF16 requires ARMv8.6-A (FEAT_BF16), supported on Graviton3/4 and AmpereOne.")

    # ------------------------------------------------------------ CPU: s390x / IBM Z
    sz = "docs/getting_started/installation/cpu.s390x.inc.md"
    if sz in docs:
        t = docs[sz]
        vxe = verbatim(t, "- Instruction Set Architecture (ISA): VXE support is required. Works with Z15 and above.")
        add(sz, hw={"hw_vendor": "other", "hw_arch": "ibm-z15", "hw_name": "IBM Z15 and above (s390x CPU)",
                    "hw_extra": {"backend": "CPU"}},
            quotes=[vxe,
                    verbatim(t, "Currently, the CPU implementation for s390x architecture supports FP32, BF16 and FP16, as well as AWQ and GPTQ 4-bit quantization and compressed-tensors INT8 W8A8.")],
            notes="vLLM CPU (s390x): requires VXE, works on z15 and above; FP32/BF16/FP16 + AWQ/GPTQ 4-bit.")

    # ------------------------------------------------------------ CPU: Apple (macOS CPU)
    ca = "docs/getting_started/installation/cpu.apple.inc.md"
    if ca in docs:
        t = docs[ca]
        add(ca, hw={"hw_vendor": "apple", "hw_arch": "m1", "hw_name": "Apple Silicon (CPU-only vLLM build)",
                    "hw_extra": {"backend": "CPU"}},
            quotes=[verbatim(t, "Currently the CPU implementation for macOS supports FP32 and FP16 datatypes."),
                    verbatim(t, "The macOS CPU build is smoke-tested in CI on the latest GA Apple Silicon")],
            notes="vLLM CPU on macOS: FP32/FP16 only, CI-tested on Apple Silicon; GPU acceleration needs vllm-metal.")

    return rows, rejects
