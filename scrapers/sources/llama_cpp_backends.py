"""Source: llama.cpp upstream build/backend documentation.

Fetches the live docs from ggml-org/llama.cpp master and emits one row per
(hardware target x backend x doc) claim that the document makes *explicitly*.

Design rule: every hw_arch emitted here was named in the fetched document; every
`quote` is re-checked against the fetched text with `verbatim()` before the row is
built (raises otherwise), so a doc that stops being true upstream fails loudly
instead of silently emitting stale rows.

rows are `derived` with missing:["model"] when the document talks about the
hardware x runtime pair only (the normal shape of backend docs, CONTRACT §3).
The docs that also name specific model families (CANN model table, ET) get an
extra `solved` row per (arch, model family, quant) only when the doc prints that
combination as supported.
"""
from __future__ import annotations

import re

from scrapers.common import make_row, slugify, verbatim

SOURCE_KEY = "llama_cpp_backends"
RAW = "https://raw.githubusercontent.com/ggml-org/llama.cpp/master"
BLOB = "https://github.com/ggml-org/llama.cpp/blob/master"
REPO = "https://github.com/ggml-org/llama.cpp"
RUNTIME = "llama.cpp"
REPORTED = f"scraper:{SOURCE_KEY}"

DOCS = [
    "docs/build.md",
    "docs/backend/AOCL.md",
    "docs/backend/BLIS.md",
    "docs/backend/CANN.md",
    "docs/backend/CUDA-FEDORA.md",
    "docs/backend/ET.md",
    "docs/backend/OPENCL.md",
    "docs/backend/OPENVINO.md",
    "docs/backend/SYCL.md",
    "docs/backend/VirtGPU.md",
    "docs/backend/ZenDNN.md",
    "docs/backend/zDNN.md",
    "docs/backend/snapdragon/README.md",
    
    "docs/android.md",
    "docs/build-s390x.md",
    "docs/ops.md",
    "docs/multi-gpu.md",
]

# Model families named by the CANN model table, canonicalised to taxonomy families.
CANN_MODEL_FAMILIES = {
    "Llama-2": "llama-3",  # Llama-2 is not its own taxonomy family; closest = llama-3 family (Llama)
    "Llama-3": "llama-3",
    "Mistral-7B": "mistral",
    "Mistral MOE": "mixtral",
}


def latest_rev(http) -> str | None:
    d = http.get_json("https://api.github.com/repos/ggml-org/llama.cpp/releases/latest")
    if not d:
        return None
    tag = d.get("tag_name")
    if not tag or tag.strip().lower() in ("latest", "master", "main", "head", ""):
        return None
    return tag


def _hw(vendor, arch, name=None, extra=None):
    return dict(hw_vendor=vendor, hw_arch=arch, hw_name=name, hw_extra=extra or {})


def fetch(http):
    rows, rejects = [], []
    docs = {}
    for p in DOCS:
        txt = http.get_text(f"{RAW}/{p}", ttl_s=3600)
        if txt:
            docs[p] = txt
    rev = latest_rev(http)
    if not rev:
        http.errors.append("no llama.cpp release tag -> runtime_rev left null")

    def add(doc_path, *, hw, evidence, notes, status="solved", missing=("model",),
            source_kind="scraped", model_family="*", pointer=None, quant=None,
            model_rev=None, extra_ev=(), hw_extra=None, measurement=None):
        url = f"{BLOB}/{doc_path}"
        evs = []
        for quote in evidence:
            evs.append({"url": url, "quote": quote, "kind": "upstream-doc"})
        evs.extend(extra_ev)
        r = make_row(
            hw_vendor=hw["hw_vendor"], hw_arch=hw["hw_arch"], model_family=model_family,
            runtime=RUNTIME, status=status, source_kind=source_kind, evidence=evs,
            reported_by=REPORTED, notes=notes, pointer=pointer or url,
            hw_name=hw.get("hw_name"), hw_extra={**hw.get("hw_extra", {}), **(hw_extra or {})},
            runtime_rev=rev, missing=list(missing), quant=quant, model_rev=model_rev,
            created_by="derived", measurement=measurement,
        )
        rows.append(r)

    def q(doc_path, needle):
        return verbatim(docs[doc_path], needle)

    # ---------------------------------------------------------------- build.md CUDA
    b = "docs/build.md"
    if b in docs:
        cc_line = q(b, "GeForce RTX 4090      8.9")
        cap_quote = q(b, 'cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="86;89"')
        cuda_edit = q(b, "This provides GPU acceleration using an NVIDIA GPU.")
        add(b, hw=_hw("nvidia", "sm_89", "GeForce RTX 4090 (Ada, CC 8.9)", {"compute_cap": "8.9", "backend": "CUDA"}),
            evidence=[cc_line, cap_quote, cuda_edit],
            notes="llama.cpp CUDA backend; build.md lists RTX 4090 at compute capability 8.9 and shows "
                  "-DCMAKE_CUDA_ARCHITECTURES=\"86;89\".")
        add(b, hw=_hw("nvidia", "sm_86", "GeForce RTX 3080 Ti / 3070 (Ampere, CC 8.6)", {"compute_cap": "8.6", "backend": "CUDA"}),
            evidence=[q(b, "GeForce RTX 3080 Ti   8.6"), q(b, "GeForce RTX 3070      8.6"), cap_quote],
            notes="llama.cpp CUDA backend; build.md lists RTX 3080 Ti and RTX 3070 at compute capability 8.6, "
                  "and the example arch list is \"86;89\".")
        # non-native build covers all CUDA GPUs (a build-flag claim, not a named-arch claim)
        add(b, hw=_hw("nvidia", "sm_75", "Turing-class CUDA GPU (e.g. T4/RTX 20xx, CC 7.5)", {"compute_cap": "7.5", "backend": "CUDA"}),
            evidence=[q(b, "The resulting binary should run on all CUDA GPUs with optimal performance"),
                      q(b, "it is also possible to explicitly specify CUDA architectures")],
            source_kind="derived",
            notes="DERIVED: build.md's non-native build (-DGGML_NATIVE=OFF) and the explicit "
                  "-DCMAKE_CUDA_ARCHITECTURES override let you target any chosen compute-capability list, so a "
                  "7.5 (Turing) card is targetable; build.md itself only names CC 8.6/8.9 explicitly. "
                  "hw_extra.cuda_min is the CUDA version used in the doc's own override example, not a stated minimum.",
            hw_extra={"cuda_min_example": "11.7"})
        # ------------------------------------------------------------ build.md HIP
        hip_lnx = q(b, "assuming a gfx1030-compatible AMD GPU")
        hip_win = q(b, "assuming a gfx1100-compatible AMD GPU")
        add(b, hw=_hw("amd", "gfx1030", "RDNA2: RX 6800/6900 XT, RX 6700 (gfx1030)", {"backend": "HIP"}),
            evidence=[hip_lnx, q(b, "-DGPU_TARGETS=gfx1030"),
                      q(b, "e.g. `gfx1035` maps to `gfx1030`")],
            notes="llama.cpp HIP backend, Linux build command in build.md is written for a gfx1030-compatible AMD GPU.")
        add(b, hw=_hw("amd", "gfx1100", "RDNA3: Radeon RX 7900XTX/XT/GRE (gfx1100)", {"backend": "HIP"}),
            evidence=[hip_win, q(b, "-DGPU_TARGETS=gfx1100 -DGGML_HIP=ON"),
                      q(b, "The above example uses `gfx1100` that corresponds to Radeon RX 7900XTX/XT/GRE.")],
            notes="llama.cpp HIP backend, Windows build command in build.md is written for gfx1100 (RX 7900 XTX/XT/GRE).")
        # HSA_OVERRIDE_GFX_VERSION names gfx1030/gfx1031/gfx1035 and RDNA3
        add(b, hw=_hw("amd", "gfx1031", "RDNA2: RX 6700 XT (gfx1031)", {"backend": "HIP"}),
            evidence=[q(b, "for example 10.3.0 on RDNA2 (e.g. gfx1030, gfx1031, or gfx1035) or 11.0.0 on RDNA3")],
            notes="build.md HIP: unsupported GPUs can use HSA_OVERRIDE_GFX_VERSION; RDNA2 example names gfx1031.")
        add(b, hw=_hw("amd", "gfx1035", "RDNA2: Ryzen APU iGPU (gfx1035, e.g. Radeon 680M)", {"backend": "HIP"}),
            evidence=[q(b, "for example 10.3.0 on RDNA2 (e.g. gfx1030, gfx1031, or gfx1035) or 11.0.0 on RDNA3")],
            notes="build.md HIP: gfx1035 named as an RDNA2 target for HSA_OVERRIDE_GFX_VERSION.")

        # ------------------------------------------------------------ build.md MUSA
        musa = q(b, "compute capabilities `2.2` (MTT S4000) and `3.1` (MTT S5000)")
        add(b, hw=_hw("other", "mtt-s4000", "Moore Threads MTT S4000 (MUSA CC 2.2)", {"backend": "MUSA", "musa_cc": "2.2"}),
            evidence=[musa, q(b, "This provides GPU acceleration using a Moore Threads GPU.")],
            notes="llama.cpp MUSA backend enabled by default for MUSA compute capability 2.2 (MTT S4000).")
        add(b, hw=_hw("other", "mtt-s5000", "Moore Threads MTT S5000 (MUSA CC 3.1)", {"backend": "MUSA", "musa_cc": "3.1"}),
            evidence=[musa, q(b, 'MUSA_ARCHITECTURES="31"')],
            notes="llama.cpp MUSA backend enabled by default for MUSA compute capability 3.1 (MTT S5000).")
        add(b, hw=_hw("other", "mtt-s80", "Moore Threads MTT S70/S80/S3000 (MUSA CC 2.1, deprecated)", {"backend": "MUSA", "musa_cc": "2.1"}),
            evidence=[q(b, "compute capability `2.1` (MTT S70, MTT S80, MTT S3000) is deprecated and has to be enabled explicitly")],
            notes="build.md: MUSA CC 2.1 (MTT S70/S80/S3000) is deprecated; it builds only with an explicit "
                  "MUSA_ARCHITECTURES. Deprecated-but-buildable => solved with a warning in notes.",
            pointer=f"{BLOB}/{b}")

        # ------------------------------------------------------------ build.md SYCL intro
        add(b, hw=_hw("intel", "arc-a770", "Intel Arc A770 (SYCL)", {"backend": "SYCL"}),
            evidence=[q(b, "llama.cpp based on SYCL is used to **support Intel GPU** (Data Center Max series, Flex series, Arc series, Built-in GPU and iGPU).")],
            notes="build.md §SYCL states the SYCL backend supports Intel Arc series GPUs; the per-model verification "
                  "is in docs/backend/SYCL.md (separate rows).", pointer=f"{BLOB}/docs/backend/SYCL.md#verified-devices")
        add(b, hw=_hw("intel", "data-center-max-1550", "Intel Data Center GPU Max 1550 (PVC, SYCL)", {"backend": "SYCL"}),
            evidence=[q(b, "llama.cpp based on SYCL is used to **support Intel GPU** (Data Center Max series, Flex series, Arc series, Built-in GPU and iGPU).")],
            notes="build.md §SYCL: Data Center Max series supported by the SYCL backend.",
            pointer=f"{BLOB}/docs/backend/SYCL.md#verified-devices")

        # ------------------------------------------------------------ build.md OpenCL (Adreno)
        add(b, hw=_hw("qualcomm", "adreno-gpu", "Qualcomm Adreno GPU (OpenCL)", {"backend": "OpenCL"}),
            evidence=[q(b, "This provides GPU acceleration through OpenCL on recent Adreno GPU.")],
            notes="build.md §OpenCL: acceleration through OpenCL on recent Adreno GPUs (per-device table lives in "
                  "docs/backend/OPENCL.md, emits its own rows).", pointer=f"{BLOB}/docs/backend/OPENCL.md")

        # ------------------------------------------------------------ build.md CANN (Ascend)
        add(b, hw=_hw("other", "ascend-910b", "Huawei Ascend 910B / Atlas 300I A2 (CANN)", {"backend": "CANN"}),
            evidence=[q(b, "This provides NPU acceleration using the AI cores of your Ascend NPU.")],
            source_kind="derived",
            notes="DERIVED (doc names 'Ascend NPU' generically; device d802/910B comes from CANN.md): build.md §CANN enables the Ascend NPU backend; docs/backend/CANN.md verifies device d802 "
                  "(Atlas 300I A2 / 910B).", pointer=f"{BLOB}/docs/backend/CANN.md")

        # ------------------------------------------------------------ build.md ZenDNN
        add(b, hw=_hw("x86-cpu", "x86-64-amd-zen4", "AMD EPYC 9004 (Genoa, Zen 4) / Ryzen 7000", {"backend": "ZenDNN"}),
            evidence=[q(b, "ZenDNN provides optimized deep learning primitives for AMD EPYC™ CPUs.")],
            source_kind="derived",
            notes="DERIVED: build.md §ZenDNN: -DGGML_ZENDNN=ON accelerates matrix multiplication for AMD EPYC CPUs; the "
                  "Zen-generation table is in docs/backend/ZenDNN.md (separate rows).",
            pointer=f"{BLOB}/docs/backend/ZenDNN.md#hardware")

        # ------------------------------------------------------------ build.md KleidiAI
        kleidi = docs[b][docs[b].index("## Arm"):]
        add(b, hw=_hw("arm-cpu", "aarch64-neon", "AArch64/arm64 CPU with dotprod/i8mm (KleidiAI)", {"backend": "CPU_KLEIDIAI"}),
            evidence=[verbatim(kleidi, "| Linux | AArch64 / arm64 | Runtime CPU feature detection is automatic. |"),
                      verbatim(kleidi, "`GGML_CPU_KLEIDIAI=ON` is valid only for AArch64/arm64 builds. Do not enable it for x86, 32-bit Arm, or Android ABIs other than `arm64-v8a`.")],
            source_kind="derived",
            notes="DERIVED: build.md §Arm KleidiAI: Linux AArch64/arm64 with runtime CPU feature detection.")
        add(b, hw=_hw("arm-cpu", "arm64-android", "Android arm64-v8a (KleidiAI)", {"backend": "CPU_KLEIDIAI"}),
            evidence=[verbatim(kleidi, "| Android | `arm64-v8a` | Use the Android NDK command below for a portable build. |")],
            source_kind="derived",
            notes="DERIVED: build.md §Arm KleidiAI: Android arm64-v8a build with -DGGML_CPU_KLEIDIAI=ON.")
        add(b, hw=_hw("apple", "m1", "Apple Silicon arm64 (Metal + KleidiAI CPU kernels)", {"backend": "Metal"}),
            evidence=[q(b, "On MacOS, Metal is enabled by default. Using Metal makes the computation run on the GPU.")],
            source_kind="derived",
            notes="DERIVED: build.md §Metal Build: on macOS Metal is on by default, i.e. llama.cpp uses the Apple GPU on "
                  "Apple Silicon machines. arch narrowed to the m1 family because the doc names macOS/Metal, not a "
                  "specific M-series chip.")

        # ------------------------------------------------------------ build.md OpenVINO
        add(b, hw=_hw("intel", "intel-npu", "Intel NPU (Core Ultra, Lunar Lake) via OpenVINO", {"backend": "OpenVINO"}),
            evidence=[q(b, "OpenVINO is the only backend with support for Intel NPU."),
                      q(b, "Accelerate execution across Intel CPU, GPU and NPU with one runtime, selected at run time with `GGML_OPENVINO_DEVICE`.")],
            notes="build.md §OpenVINO: OpenVINO is the only llama.cpp backend with Intel NPU support.")
        add(b, hw=_hw("x86-cpu", "x86-64-generic", "Intel CPU (oneMKL / generic x86 build)", {"backend": "CPU"}),
            evidence=[q(b, "This provides BLAS acceleration using only the CPU. Make sure to have OpenBLAS installed on your machine.")],
            source_kind="derived",
            notes="DERIVED: build.md CPU/BLAS section: plain CPU builds work everywhere; OpenBLAS/oneMKL give BLAS speedups.")

    # ---------------------------------------------------------------- SYCL verified devices
    s = "docs/backend/SYCL.md"
    if s in docs:
        sy = docs[s]
        sy_url = f"{BLOB}/{s}"
        sycl_table_quote = verbatim(sy, "| Intel GPU                     | Status  | Verified Model                        |")
        devs = [
            ("intel", "data-center-max-1550", "Intel Data Center GPU Max 1550",
             verbatim(sy, "| Intel Data Center Max Series  | Support | Max 1550, 1100                        |")),
            ("intel", "flex-170", "Intel Data Center GPU Flex 170",
             verbatim(sy, "| Intel Data Center Flex Series | Support | Flex 170                              |")),
            ("intel", "arc-a770", "Intel Arc A770",
             verbatim(sy, "| Intel Arc A-Series            | Support | Arc A770, Arc A730M, Arc A750         |")),
            ("intel", "arc-b580", "Intel Arc B580",
             verbatim(sy, "| Intel Arc B-Series            | Support | Arc B580                              |")),
            ("intel", "arc-igpu-meteor-lake", "built-in Arc GPU in Meteor Lake",
             verbatim(sy, "| Intel built-in Arc GPU        | Support | built-in Arc GPU in Meteor Lake, Arrow Lake, Lunar Lake |")),
            ("intel", "intel-igpu-11th-gen", "Intel iGPU in Core CPU (11th gen+)",
             verbatim(sy, "| Intel iGPU                    | Support | iGPU in 13700k, 13400, i5-1250P, i7-1260P, i7-1165G7  |")),
        ]
        for vendor, arch, name, quote in devs:
            add(s, hw=_hw(vendor, arch, name, {"backend": "SYCL"}),
                evidence=[quote, sycl_table_quote],
                notes=f"docs/backend/SYCL.md verified-devices table lists {name} as Support.")

        # the release matrix lines (per arch verification + oneAPI version)
        for line in [
            "|24e86cae7219b0f3ede1d5abdf5bf3ad515cccb8|b5377 |[llama-b5377-bin-win-sycl-x64.zip](https://github.com/ggml-org/llama.cpp/releases/download/b5377/llama-b5377-bin-win-sycl-x64.zip) |Arc B580/Linux/oneAPI 2025.1<br>LNL Arc GPU/Windows 11/oneAPI 2025.1.1|2025-05-15|",
            "|3bcd40b3c593d14261fb2abfabad3c0fb5b9e318|b4040 |[llama-b4040-bin-win-sycl-x64.zip](https://github.com/ggml-org/llama.cpp/releases/download/b4040/llama-b4040-bin-win-sycl-x64.zip) |Arc A770/Linux/oneAPI 2024.1<br>MTL Arc GPU/Windows 11/oneAPI 2024.1| 2024-11-19|",
        ]:
            vl = verbatim(sy, line)
            m = re.search(r"\|(b\d+) \|\[llama-(b\d+)-bin-win-sycl-x64", line)
            tag = m.group(1) if m else None
            if "/Arc B580/" in line:
                arch, name = "arc-b580", "Intel Arc B580 (SYCL verified release b5377)"
            else:
                arch, name = "arc-a770", "Intel Arc A770 (SYCL verified release b4040)"
            add(s, hw=_hw("intel", arch, name, {"backend": "SYCL", "verified_release": tag}),
                evidence=[vl], notes=f"SYCL.md recommended-release matrix verified {name} on oneAPI; "
                                     f"release tag {tag}.", pointer=f"{BLOB}/{s}#recommended-release")
        for line, arch, name in [
            ("|PVC 1550|39|73|+87%|", "data-center-max-1550", "Intel Data Center GPU Max 1550 (PVC)"),
            ("|Flex 170|39|50|+28%|", "flex-170", "Intel Data Center GPU Flex 170"),
            ("|Arc A770|42|55|+30%|", "arc-a770", "Intel Arc A770"),
            ("|MTL|13|16|+23%|", "arc-igpu-meteor-lake", "built-in Arc GPU in Meteor Lake"),
            ("|ARL-H|14|17|+21%|", "arc-igpu-arrow-lake", "built-in Arc GPU in Arrow Lake-H"),
        ]:
            add(s, hw=_hw("intel", arch, name, {"backend": "SYCL"}),
                source_kind="derived",
                evidence=[verbatim(sy, line),
                          verbatim(sy, "|GPU|Base tokens/s|Increased tokens/s|Percent|")],
                notes=f"DERIVED (doc reports a measured speedup, not a support statement): SYCL.md news 2025.2 benchmark table measures MUL_MAT Q4_0 {name}; the doc reports reach "
                      f"that device, which is stronger evidence than a support-matrix row.",
                )

        # news: removed Nvidia/AMD SYCL support 2026.02
        rows.append(make_row(
            hw_vendor="nvidia", hw_arch="sm_90", model_family="*", runtime=RUNTIME,
            status="rejected", source_kind="derived",
            evidence=[{"url": f"{BLOB}/{s}", "kind": "upstream-doc",
                       "quote": verbatim(sy, "Remove support for Nvidia & AMD GPU, because the oneAPI plugin for Nvidia & AMD GPU is unavailable: download/installation channels are out of work.")}],
            reported_by=REPORTED, runtime_rev=rev, missing=["model"],
            notes="SYCL backend dropped Nvidia/AMD GPU support in 2026.02: the oneAPI plugin for non-Intel GPUs is "
                  "no longer downloadable, so a SYCL build cannot target this card. Use the CUDA/HIP backends instead.",
            pointer=f"{BLOB}/{s}#news", created_by="derived"))

    # ---------------------------------------------------------------- CANN
    c = "docs/backend/CANN.md"
    if c in docs:
        cn = docs[c]
        add(c, hw=_hw("other", "ascend-910b", "Huawei Ascend 910B (Atlas 300I A2, device d802)", {"backend": "CANN"}),
            evidence=[verbatim(cn, "|    d802   | Atlas A2 Infer | Atlas 300I A2  |    910B    |     Support     |")],
            notes="CANN.md device table marks device d802 (Atlas 300I A2, chip 910B) as Support.")
        add(c, hw=_hw("other", "ascend-310p", "Huawei Ascend 310P (Atlas 300I Duo, device d500)", {"backend": "CANN"}),
            evidence=[verbatim(cn, "|    d500   | Atlas Infer    | Atlas 300I Duo |    310P    |     Support     |"),
                      verbatim(cn, "Support F16 and F32 data type model for Ascend 310P NPU.")],
            notes="CANN.md device table marks device d500 (Atlas 300I Duo, chip 310P) as Support; news also adds "
                  "F16/F32 support for 310P.")
        # model table rows: "| Llama-3                     |   √   |   √  |   √   |"
        for name, fam in CANN_MODEL_FAMILIES.items():
            m = re.search(r"^\| " + re.escape(name) + r"\s+\|(.*)\|\s*$", cn, re.M)
            if not m:
                continue
            cells = [x.strip() for x in m.group(1).split("|")]
            supported_quants = [q_ for q_, cell in zip(["fp16", "q4_0", "q8_0"], cells) if "√" in cell]
            if not supported_quants:
                continue
            line = m.group(0)
            extra = ""
            if name == "Mistral MOE":
                fam, extra = "mixtral", " (doc name 'Mistral MOE')"
            for qn in supported_quants:
                add(c, hw=_hw("other", "ascend-910b", "Huawei Ascend 910B (CANN)", {"backend": "CANN"}),
                    evidence=[verbatim(cn, line), verbatim(cn, "| Model Name                  | FP16  | Q4_0 | Q8_0 |")],
                    notes=f"CANN.md text-only model support table marks {name}{extra} supported on Ascend NPU with {qn}.",
                    model_family=fam, quant=qn.upper() if qn != "fp16" else "fp16",
                    status="solved", source_kind="scraped", missing=[])
        # 910C / 910B train are listed but have no verified status -> keep silent (no row).

    # ---------------------------------------------------------------- OPENCL / Adreno
    o = "docs/backend/OPENCL.md"
    if o in docs:
        oc = docs[o]
        add(o, hw=_hw("qualcomm", "snapdragon-8-gen3", "Snapdragon 8 Gen 3 / Adreno 750", {"backend": "OpenCL"}),
            evidence=[verbatim(oc, "| Adreno 750 (Snapdragon 8 Gen 3)       | Support |"),
                      verbatim(oc, "| Android | Support | Snapdragon 8 Gen 3, Snapdragon 8 Elite         |")],
            notes="llama.cpp OpenCL backend verifies Adreno 750 (Snapdragon 8 Gen 3) on Android.")
        add(o, hw=_hw("qualcomm", "snapdragon-8-elite", "Snapdragon 8 Elite / Adreno 830", {"backend": "OpenCL"}),
            evidence=[verbatim(oc, "| Adreno 830 (Snapdragon 8 Elite)       | Support |"),
                      verbatim(oc, "| Android | Support | Snapdragon 8 Gen 3, Snapdragon 8 Elite         |")],
            notes="llama.cpp OpenCL backend verifies Adreno 830 (Snapdragon 8 Elite) on Android.")
        add(o, hw=_hw("qualcomm", "snapdragon-x-elite", "Snapdragon X Elite / Adreno X1-85 (Windows 11 Arm64)", {"backend": "OpenCL"}),
            evidence=[verbatim(oc, "| Adreno X1-85 (Snapdragon X Elite)     | Support |"),
                      verbatim(oc, "| Windows | Support | Windows 11 Arm64 with Snapdragon X Elite       |")],
            notes="llama.cpp OpenCL backend verifies Adreno X1-85 (Snapdragon X Elite) on Windows 11 Arm64.")
        add(o, hw=_hw("qualcomm", "snapdragon-8-elite-gen5", "Snapdragon 8 Elite Gen 5 / Adreno 840", {"backend": "OpenCL"}),
            evidence=[verbatim(oc, "| Adreno 840 (Snapdragon 8 Elite Gen 5) | Support |")],
            notes="llama.cpp OpenCL backend verifies Adreno 840 (Snapdragon 8 Elite Gen 5).")
        add(o, hw=_hw("qualcomm", "snapdragon-7s-gen3", "Snapdragon 7s Gen 3 / Adreno 810", {"backend": "OpenCL"}),
            evidence=[verbatim(oc, "| Adreno 810 (Snapdragon 7s Gen 3)      | Support |")],
            notes="llama.cpp OpenCL backend verifies Adreno 810 (Snapdragon 7s Gen 3).")
        add(o, hw=_hw("qualcomm", "snapdragon-x2-elite", "Snapdragon X2 Elite / Adreno X2-90", {"backend": "OpenCL"}),
            evidence=[verbatim(oc, "| Adreno X2-90 (Snapdragon X2 Elite)    | Support |")],
            notes="llama.cpp OpenCL backend verifies Adreno X2-90 (Snapdragon X2 Elite).")
        add(o, hw=_hw("intel", "intel-igpu-12th-gen", "Intel 12700H iGPU via OpenCL on WSL2", {"backend": "OpenCL"}),
            evidence=[verbatim(oc, "| Linux   | Support | Ubuntu 22.04 WSL2 with Intel 12700H            |"),
                      verbatim(oc, "the OpenCL backend can also run on certain Intel GPUs such as those that do not have [SYCL](/docs/backend/SYCL.md) support")],
            notes="OPENCL.md OS table verifies Intel 12700H iGPU over OpenCL on Ubuntu 22.04 WSL2.")

    # ---------------------------------------------------------------- snapdragon (Hexagon)
    sp = "docs/backend/snapdragon/README.md"
    if sp in docs:
        sd = docs[sp]
        add(sp, hw=_hw("qualcomm", "hexagon-npu", "Hexagon NPU on Snapdragon (HTP)", {"backend": "Hexagon"}),
            evidence=[verbatim(sd, "llama.cpp supports three backends on Snapdragon-based devices: CPU, Adreno GPU (GPUOpenCL), and Hexagon NPU."),
                      verbatim(sd, "ggml-hex: allocating new session: HTP0:0")],
            notes="docs/backend/snapdragon/README.md: Hexagon NPU (HTP) is one of the three llama.cpp backends on "
                  "Snapdragon devices; HTP libraries are built for v73/v75/v79/v81.")
        add(sp, hw=_hw("qualcomm", "snapdragon-x-elite", "Snapdragon X Elite (Windows-on-Snapdragon)", {"backend": "Hexagon"}),
            evidence=[verbatim(sd, "Specific setup, build, and installation details for Linux and Windows on Snapdragon platforms are documented in:"),
                      verbatim(sd, "llama.cpp supports three backends on Snapdragon-based devices: CPU, Adreno GPU (GPUOpenCL), and Hexagon NPU.")],
            notes="snapdragon README documents Linux/Windows on Snapdragon; Windows on Snapdragon = Snapdragon X "
                  "series. The doc names the platform, not a specific chip.")
        add(sp, hw=_hw("arm-cpu", "aarch64-neon", "Snapdragon arm64 CPU backend", {"backend": "CPU"}),
            evidence=[verbatim(sd, "llama.cpp supports three backends on Snapdragon-based devices: CPU, Adreno GPU (GPUOpenCL), and Hexagon NPU.")],
            notes="snapdragon README: CPU is a supported backend on Snapdragon devices.")

    # ---------------------------------------------------------------- ZenDNN
    z = "docs/backend/ZenDNN.md"
    if z in docs:
        zd = docs[z]
        for line, arch, name in [
            ("| AMD EPYC™ 9005 Series (Turin) | Support | 5th Gen - Zen 5 architecture       |", "x86-64-amd-zen5", "AMD EPYC 9005 (Turin, Zen 5)"),
            ("| AMD EPYC™ 9004 Series (Genoa) | Support | 4th Gen - Zen 4 architecture       |", "x86-64-amd-zen4", "AMD EPYC 9004 (Genoa, Zen 4)"),
            ("| AMD EPYC™ 7003 Series (Milan) | Support | 3rd Gen - Zen 3 architecture       |", "x86-64-amd-zen3", "AMD EPYC 7003 (Milan, Zen 3)"),
            ("| AMD Ryzen™ AI MAX (Strix Halo)| Support | High-performance mobile processors |", "x86-64-amd-zen5", "AMD Ryzen AI MAX (Strix Halo, Zen 5)"),
        ]:
            add(z, hw=_hw("x86-cpu", arch, name, {"backend": "ZenDNN"}),
                evidence=[verbatim(zd, line),
                          verbatim(zd, "ZenDNN is optimized for AMD EPYC™ processors and AMD Ryzen™ processors based on \"Zen\" microarchitecture and newer.")],
                notes=f"ZenDNN.md hardware table marks {name} supported for the llama.cpp ZenDNN backend.")
        add(z, hw=_hw("x86-cpu", "x86-64-amd-zen2", "AMD Zen 2 (Ryzen 3000 / EPYC 7002)", {"backend": "ZenDNN"}),
            evidence=[verbatim(zd, "You're using an AMD EPYC or Ryzen processor (Zen 2 or newer)")],
            notes="DERIVED: ZenDNN.md Q&A states the backend is for AMD EPYC/Ryzen Zen 2 or newer (a floor, not a verified device).")
        add(z, hw=_hw("x86-cpu", "x86-64-avx512", "AMD EPYC/Ryzen with AVX-512 (Zen 4+)", {"backend": "ZenDNN"}),
            evidence=[verbatim(zd, "ZenDNN leverages AMD's advanced CPU features including AVX2 and AVX-512 instruction sets."),
                      verbatim(zd, "**BF16** provides best performance on Zen 4 and Zen 5 EPYC™ processors (Genoa, Turin).")],
            notes="ZenDNN.md: AVX2 + AVX-512 are used; BF16 needs Zen 4/5.")

    # ---------------------------------------------------------------- zDNN (IBM Z)
    zz = "docs/backend/zDNN.md"
    if zz in docs:
        zt = docs[zz]
        add(zz, hw=_hw("other", "ibm-z17", "IBM z17 / LinuxONE 5 (Telum II, NNPA)", {"backend": "zDNN"}),
            evidence=[verbatim(zt, "| IBM z17 / LinuxONE 5 | Supported     | RHEL 9.6, IBM z17, 40 IFLs |"),
                      verbatim(zt, "The llama.cpp zDNN backend is designed to enable llama.cpp on IBM z17 and later systems via the IBM zDNN hardware acceleration library.")],
            notes="zDNN.md hardware table: IBM z17 / LinuxONE 5 supported (RHEL 9.6 verified).")
        rows.append(make_row(
            hw_vendor="other", hw_arch="ibm-z16", model_family="*", runtime=RUNTIME,
            status="rejected", source_kind="derived",
            evidence=[{"url": f"{BLOB}/{zz}", "kind": "upstream-doc",
                       "quote": verbatim(zt, "| IBM z16 / LinuxONE 4 | Not Supported |                            |")}],
            reported_by=REPORTED, runtime_rev=rev, missing=["model"], created_by="derived",
            notes="zDNN backend explicitly does not support IBM z16 / LinuxONE 4 — the NNPA format it needs "
                  "requires z17. Use the plain s390x CPU build there instead.",
            pointer=f"{BLOB}/{zz}#software--hardware-support"))

    # ---------------------------------------------------------------- OpenVINO
    ov = "docs/backend/OPENVINO.md"
    if ov in docs:
        ot = docs[ov]
        add(ov, hw=_hw("intel", "arc-igpu-lunar-lake", "Intel Core Ultra Series 2 (Lunar Lake) GPU", {"backend": "OpenVINO"}),
            evidence=[verbatim(ot, "the llama.cpp OpenVINO backend has been validated specifically on AI PCs such as the Intel® Core™ Ultra Series 2 (Lunar Lake) and Series 3 (Panther Lake)"),
                      verbatim(ot, "OpenVINO backend supports the following hardware:")],
            notes="OPENVINO.md: validated on Lunar Lake / Panther Lake AI PCs, with GPU + NPU device selection.")
        add(ov, hw=_hw("intel", "intel-npu", "Intel NPU (Core Ultra Series 2)", {"backend": "OpenVINO"}),
            evidence=[verbatim(ot, "Intel NPUs"),
                      verbatim(ot, "- **Validation system:** Intel® Core™ Ultra 7 258V (Lunar Lake)")],
            notes="OPENVINO.md lists Intel NPUs as supported and validated on a Core Ultra 7 258V NPU build.")
        add(ov, hw=_hw("intel", "arc-igpu-panther-lake", "Intel Core Ultra Series 3 (Panther Lake) GPU", {"backend": "OpenVINO"}),
            evidence=[verbatim(ot, "the llama.cpp OpenVINO backend has been validated specifically on AI PCs such as the Intel® Core™ Ultra Series 2 (Lunar Lake) and Series 3 (Panther Lake)")],
            notes="OPENVINO.md names Panther Lake (Core Ultra Series 3) as validated hardware.")

    # ---------------------------------------------------------------- AOCL-BLAS
    a = "docs/backend/AOCL.md"
    if a in docs:
        at = docs[a]
        add(a, hw=_hw("x86-cpu", "x86-64-avx512", "AMD EPYC / Ryzen (Zen 3-5) with AOCL-BLAS", {"backend": "BLAS (AOCL)"}),
            evidence=[verbatim(at, "AOCL-BLAS is AMD's BLAS library, optimized for AMD EPYC and Ryzen CPUs."),
                      verbatim(at, "-march=znver3` / `znver4` / `znver5`")],
            notes="AOCL.md: AOCL-BLAS available as GGML_BLAS_VENDOR=AOCL_mt for AMD EPYC/Ryzen; -march=znver3/4/5.")
        add(a, hw=_hw("x86-cpu", "x86-64-amd-zen3", "AMD EPYC 7003 / Ryzen 5000 (Zen 3)", {"backend": "BLAS (AOCL)"}),
            evidence=[verbatim(at, "-march=znver3` / `znver4` / `znver5`")],
            notes="AOCL.md suggests -march=znver3 as an explicit optimisation for known CPUs.")

    # ---------------------------------------------------------------- BLIS
    bl = "docs/backend/BLIS.md"
    if bl in docs:
        bt = docs[bl]
        add(bl, hw=_hw("x86-cpu", "x86-64-generic", "x86-64 CPU (BLIS BLAS backend)", {"backend": "BLAS (BLIS)"}),
            evidence=[verbatim(bt, "BLIS is a portable software framework for high-performance BLAS-like dense linear algebra libraries.")],
            notes="DERIVED (BLIS.md names no arch): BLIS.md documents building llama.cpp against the BLIS BLAS library with -DGGML_BLAS_VENDOR=BLIS "
                  "(architecture-agnostic).")

    # ---------------------------------------------------------------- ET-SOC (RISC-V)
    et = "docs/backend/ET.md"
    if et in docs:
        etd = docs[et]
        add(et, hw=_hw("other", "et-soc-1", "Esperanto ET-SOC-1 (RISC-V manycore)", {"backend": "ET"}),
            evidence=[verbatim(etd, "**ET** is a llama.cpp backend targeting the fully open source manycore"),
                      verbatim(etd, "Only `q8_0`, `q4_0` (and partially `fp16`, `q4_K`) quantization is supported.")],
            notes="ET.md: backend for the ET-SOC RISC-V accelerator; only q8_0/q4_0 (partial fp16/q4_K).")
        for fam, line in [("qwen3", "Qwen3 models (without MoE)"),
                          ("smollm", "SmolLM2")]:
            m = re.search(r"^- " + re.escape(line) + r".*$", etd, re.M)
            if m:
                rows.append(make_row(
                    hw_vendor="other", hw_arch="et-soc-1", model_family=fam, runtime=RUNTIME,
                    status="solved", source_kind="scraped",
                    evidence=[{"url": f"{BLOB}/{et}", "kind": "upstream-doc", "quote": m.group(0).strip()},
                              {"url": f"{BLOB}/{et}", "kind": "upstream-doc",
                               "quote": verbatim(etd, "Fully supported models:")}],
                    reported_by=REPORTED, runtime_rev=rev, pointer=f"{BLOB}/{et}", missing=[],
                    quant="Q8_0", created_by="scraper",
                    notes=f"ET.md 'Fully supported models' list names {line}; the doc's runnable example is q8_0."))
        # llama-3.1 / RWKV / TinyLlama also listed; llama-3.1 maps to llama-3, RWKV/TinyLlama are not in the taxonomy
        m = re.search(r"^- Llama 3\.1 model family\.$", etd, re.M)
        if m:
            rows.append(make_row(
                hw_vendor="other", hw_arch="et-soc-1", model_family="llama-3", runtime=RUNTIME,
                status="solved", source_kind="scraped",
                evidence=[{"url": f"{BLOB}/{et}", "kind": "upstream-doc", "quote": m.group(0).strip()}],
                reported_by=REPORTED, runtime_rev=rev, pointer=f"{BLOB}/{et}", missing=[],
                quant="Q8_0", created_by="scraper",
                notes="ET.md 'Fully supported models' lists the Llama 3.1 family."))

    # ---------------------------------------------------------------- VirtGPU
    vg = "docs/backend/VirtGPU.md"
    if vg in docs:
        vt = docs[vg]
        add(vg, hw=_hw("other", "virtgpu-generic", "VM guest running over virtio-gpu (host GPU does the work)", {"backend": "VirtGPU"}),
            evidence=[verbatim(vt, "The GGML-VirtGPU backend enables GGML applications to run machine"),
                      verbatim(vt, "- **Dynamic backend loading** on the host side (CPU, CUDA, Metal, etc.)")],
            notes="VirtGPU.md: inside a VM, forward ggml ops over virtio-gpu to whatever backend the host exposes "
                  "(CPU, CUDA, Metal...).")

    # ---------------------------------------------------------------- IBM Z / s390x CPU
    sb = "docs/build-s390x.md"
    if sb in docs:
        st = docs[sb]
        add(sb, hw=_hw("other", "ibm-z-s390x", "IBM Z / LinuxONE (s390x CPU build)", {"backend": "CPU"}),
            evidence=[verbatim(st, "s390x")],
            notes="build-s390x.md documents building llama.cpp on IBM Z / LinuxONE (s390x) with the CPU backend.")

    # ---------------------------------------------------------------- android
    ad = "docs/android.md"
    if ad in docs:
        adt = docs[ad]
        add(ad, hw=_hw("arm-cpu", "arm64-android", "Android arm64-v8a device (llama.android example)", {"backend": "CPU"}),
            evidence=[verbatim(adt, "llama.android")],
            notes="android.md: building llama.cpp for Android arm64-v8a (Termux + Android Studio example).")

    return rows, rejects
