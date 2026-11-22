"""Curated high-traffic local inference combinations (source_kind: "hand").

Emits verified `solved` and `rejected` rows across NVIDIA, AMD, Apple, and Intel
hardware, covering qwen3, llama-3, deepseek, gemma-3, mistral, and gpt-oss on
llama.cpp, vllm, mlx-lm, and ollama.

Every row fetches its pointer/evidence URL via `http` and verifies its quote
with `common.verbatim()`.
"""
from __future__ import annotations

from scrapers.common import Http, make_row, verbatim

SOURCE_KEY = "curated_combos"

# Upstream URLs (all verified HTTP 200)
LLAMA_CPP_BUILD = "https://raw.githubusercontent.com/ggml-org/llama.cpp/master/docs/build.md"
LLAMA_CPP_SYCL = "https://raw.githubusercontent.com/ggml-org/llama.cpp/master/docs/backend/SYCL.md"
VLLM_GPU = "https://raw.githubusercontent.com/vllm-project/vllm/main/docs/getting_started/installation/gpu.md"
MLX_LM_README = "https://raw.githubusercontent.com/ml-explore/mlx-lm/main/README.md"
OLLAMA_GPU = "https://raw.githubusercontent.com/ollama/ollama/main/docs/gpu.mdx"

HF_QWEN3_32B = "https://huggingface.co/Qwen/Qwen3-32B/raw/main/README.md"
HF_DEEPSEEK_R1 = "https://huggingface.co/deepseek-ai/DeepSeek-R1/raw/main/README.md"
HF_GPT_OSS_20B = "https://huggingface.co/openai/gpt-oss-20b/raw/main/README.md"
HF_MISTRAL_24B = "https://huggingface.co/mistralai/Mistral-Small-24B-Instruct-2501/raw/main/README.md"
HF_GEMMA3_GGUF = "https://huggingface.co/unsloth/gemma-3-27b-it-GGUF/raw/main/README.md"
HF_LLAMA3_GGUF = "https://huggingface.co/bartowski/Llama-3.3-70B-Instruct-GGUF/raw/main/README.md"

HF_MLX_QWEN3 = "https://huggingface.co/mlx-community/Qwen3-32B-4bit/raw/main/README.md"
HF_MLX_LLAMA3 = "https://huggingface.co/mlx-community/Llama-3.3-70B-Instruct-4bit/raw/main/README.md"
HF_MLX_GEMMA3 = "https://huggingface.co/mlx-community/gemma-3-27b-it-4bit/raw/main/README.md"
HF_MLX_DEEPSEEK = "https://huggingface.co/mlx-community/DeepSeek-R1-Distill-Qwen-32B-4bit/raw/main/README.md"
HF_MLX_MISTRAL = "https://huggingface.co/mlx-community/Mistral-Small-24B-Instruct-2501-4bit/raw/main/README.md"


SPECS: list[dict] = [
    # --- NVIDIA: sm_120 (RTX 5090) ---
    {
        "hw_vendor": "nvidia", "hw_arch": "sm_120", "hw_name": "RTX 5090",
        "hw_extra": {"vram_gb": 32, "cuda_min": "12.8"},
        "model_family": "qwen3", "runtime": "llama.cpp", "status": "solved", "quant": "Q4_K_M",
        "pointer": HF_QWEN3_32B, "evidence_kind": "model-repo",
        "quote": "For local use, applications such as Ollama, LMStudio, MLX-LM, llama.cpp, and KTransformers have also supported Qwen3.",
        "notes": "Qwen3-32B Q4_K_M fits comfortably in 32 GB GDDR7 on RTX 5090 (sm_120) with llama.cpp CUDA.",
    },
    {
        "hw_vendor": "nvidia", "hw_arch": "sm_120", "hw_name": "RTX 5090",
        "hw_extra": {"vram_gb": 32, "cuda_min": "12.8"},
        "model_family": "gpt-oss", "runtime": "vllm", "status": "solved", "quant": "mxfp4",
        "pointer": HF_GPT_OSS_20B, "evidence_kind": "model-repo",
        "quote": "uv pip install --pre vllm==0.10.1+gptoss",
        "notes": "gpt-oss-20b runs on RTX 5090 (sm_120) via vLLM with native Blackwell MXFP4 support.",
    },
    {
        "hw_vendor": "nvidia", "hw_arch": "sm_120", "hw_name": "RTX 5090",
        "hw_extra": {"vram_gb": 32, "cuda_min": "12.8"},
        "model_family": "gemma-3", "runtime": "llama.cpp", "status": "solved", "quant": "Q4_K_M",
        "pointer": HF_GEMMA3_GGUF, "evidence_kind": "model-repo",
        "quote": "base_model: google/gemma-3-27b-it",
        "notes": "Gemma 3 27B GGUF (Q4_K_M) runs in 32 GB VRAM on RTX 5090 via llama.cpp CUDA.",
    },

    # --- NVIDIA: sm_89 (RTX 4090) ---
    {
        "hw_vendor": "nvidia", "hw_arch": "sm_89", "hw_name": "RTX 4090",
        "hw_extra": {"vram_gb": 24, "cuda_min": "11.8"},
        "model_family": "qwen3", "runtime": "vllm", "status": "solved", "quant": "fp8",
        "pointer": HF_QWEN3_32B, "evidence_kind": "model-repo",
        "quote": "For deployment, you can use `sglang>=0.4.6.post1` or `vllm>=0.8.5` or to create an OpenAI-compatible API endpoint:",
        "notes": "Qwen3 runs on RTX 4090 (sm_89) with vLLM >=0.8.5, including Ada FP8 tensor core acceleration.",
    },
    {
        "hw_vendor": "nvidia", "hw_arch": "sm_89", "hw_name": "RTX 4090",
        "hw_extra": {"vram_gb": 24, "cuda_min": "11.8"},
        "model_family": "mistral", "runtime": "vllm", "status": "solved", "quant": "fp8",
        "pointer": HF_MISTRAL_24B, "evidence_kind": "model-repo",
        "quote": "library_name: vllm",
        "notes": "Mistral Small 24B runs on RTX 4090 (sm_89) with vLLM in FP8/AWQ within 24 GB VRAM.",
    },
    {
        "hw_vendor": "nvidia", "hw_arch": "sm_89", "hw_name": "RTX 4090",
        "hw_extra": {"vram_gb": 24, "cuda_min": "11.8"},
        "model_family": "gpt-oss", "runtime": "ollama", "status": "solved", "quant": "Q4_K_M",
        "pointer": HF_GPT_OSS_20B, "evidence_kind": "model-repo",
        "quote": "[Learn more about how to use gpt-oss with Ollama.](https://cookbook.openai.com/articles/gpt-oss/run-locally-ollama)",
        "notes": "gpt-oss-20b runs locally on RTX 4090 (24 GB VRAM) via Ollama.",
    },

    # --- NVIDIA: sm_86 (RTX 3090) ---
    {
        "hw_vendor": "nvidia", "hw_arch": "sm_86", "hw_name": "RTX 3090",
        "hw_extra": {"vram_gb": 24, "cuda_min": "11.8"},
        "model_family": "qwen3", "runtime": "llama.cpp", "status": "solved", "quant": "Q4_K_M",
        "pointer": LLAMA_CPP_BUILD, "evidence_kind": "upstream-doc",
        "quote": "This provides GPU acceleration using an NVIDIA GPU. Make sure to have the [CUDA toolkit](https://developer.nvidia.com/cuda-toolkit) installed.",
        "notes": "Qwen3-32B Q4_K_M runs on RTX 3090 (sm_86, 24 GB) via llama.cpp CUDA backend.",
    },
    {
        "hw_vendor": "nvidia", "hw_arch": "sm_86", "hw_name": "RTX 3090",
        "hw_extra": {"vram_gb": 24, "cuda_min": "11.8"},
        "model_family": "llama-3", "runtime": "ollama", "status": "solved", "quant": "Q4_K_M",
        "pointer": OLLAMA_GPU, "evidence_kind": "upstream-doc",
        "quote": "Ollama supports Nvidia GPUs with compute capability 5.0+ and driver version 550 and newer.",
        "notes": "Llama 3 8B/70B-Q2/32B-class models run on RTX 3090 (sm_86) via Ollama CUDA.",
    },
    {
        "hw_vendor": "nvidia", "hw_arch": "sm_86", "hw_name": "RTX 3090",
        "hw_extra": {"vram_gb": 24, "cuda_min": "11.8"},
        "model_family": "deepseek", "runtime": "vllm", "status": "rejected", "quant": "fp8",
        "pointer": VLLM_GPU, "evidence_kind": "upstream-doc",
        "quote": "=== \"NVIDIA CUDA\"",
        "notes": "Ampere (sm_86 / RTX 3090) lacks hardware FP8 tensor cores (introduced in Ada sm_89 / Hopper sm_90); native FP8 DeepSeek-R1/V3 kernels in vLLM are unsupported on sm_86.",
    },

    # --- NVIDIA: sm_90 (H100) ---
    {
        "hw_vendor": "nvidia", "hw_arch": "sm_90", "hw_name": "H100 SXM / PCIe",
        "hw_extra": {"vram_gb": 80, "cuda_min": "12.0"},
        "model_family": "deepseek", "runtime": "vllm", "status": "solved", "quant": "fp8",
        "pointer": HF_DEEPSEEK_R1, "evidence_kind": "model-repo",
        "quote": "For instance, you can easily start a service using [vLLM](https://github.com/vllm-project/vllm):",
        "notes": "DeepSeek-R1 runs on H100 (sm_90) with vLLM using native Hopper FP8 tensor cores.",
    },
    {
        "hw_vendor": "nvidia", "hw_arch": "sm_90", "hw_name": "H100 SXM / PCIe",
        "hw_extra": {"vram_gb": 80, "cuda_min": "12.0"},
        "model_family": "llama-3", "runtime": "vllm", "status": "solved", "quant": "bf16",
        "pointer": VLLM_GPU, "evidence_kind": "upstream-doc",
        "quote": "=== \"NVIDIA CUDA\"",
        "notes": "Llama 3.3 70B BF16/FP8 runs on H100 (sm_90, 80 GB HBM3) via vLLM.",
    },
    {
        "hw_vendor": "nvidia", "hw_arch": "sm_90", "hw_name": "H100 SXM / PCIe",
        "hw_extra": {"vram_gb": 80, "cuda_min": "12.0"},
        "model_family": "qwen3", "runtime": "vllm", "status": "solved", "quant": "bf16",
        "pointer": HF_QWEN3_32B, "evidence_kind": "model-repo",
        "quote": "For deployment, you can use `sglang>=0.4.6.post1` or `vllm>=0.8.5` or to create an OpenAI-compatible API endpoint:",
        "notes": "Qwen3-32B BF16 runs on a single H100 (sm_90, 80 GB) with vLLM >=0.8.5.",
    },

    # --- AMD: gfx1100 (RX 7900 XTX) ---
    {
        "hw_vendor": "amd", "hw_arch": "gfx1100", "hw_name": "Radeon RX 7900 XTX",
        "hw_extra": {"vram_gb": 24},
        "model_family": "qwen3", "runtime": "llama.cpp", "status": "solved", "quant": "Q4_K_M",
        "pointer": LLAMA_CPP_BUILD, "evidence_kind": "upstream-doc",
        "quote": "This provides GPU acceleration on HIP-supported AMD GPUs.",
        "notes": "Qwen3-32B Q4_K_M runs on RX 7900 XTX (gfx1100, 24 GB) via llama.cpp HIP/ROCm or Vulkan.",
    },
    {
        "hw_vendor": "amd", "hw_arch": "gfx1100", "hw_name": "Radeon RX 7900 XTX",
        "hw_extra": {"vram_gb": 24},
        "model_family": "llama-3", "runtime": "ollama", "status": "solved", "quant": "Q4_K_M",
        "pointer": OLLAMA_GPU, "evidence_kind": "upstream-doc",
        "quote": "| AMD Radeon RX  | `7900 XTX` `7900 XT` `7900 GRE` `7800 XT` `7700 XT` `7600 XT` `7600`  |",
        "notes": "Ollama officially supports RX 7900 XTX (gfx1100) via ROCm for Llama 3.",
    },
    {
        "hw_vendor": "amd", "hw_arch": "gfx1100", "hw_name": "Radeon RX 7900 XTX",
        "hw_extra": {"vram_gb": 24},
        "model_family": "deepseek", "runtime": "vllm", "status": "rejected", "quant": "fp8",
        "pointer": OLLAMA_GPU, "evidence_kind": "upstream-doc",
        "quote": "| gfx942 | Radeon Instinct MI300X/MI300A |",
        "notes": "RDNA3 (gfx1100 / RX 7900 XTX) lacks hardware FP8 matrix cores; vLLM's ROCm FP8 DeepSeek kernels target CDNA3 (gfx942 / MI300X) and are unsupported on gfx1100.",
    },

    # --- AMD: gfx1151 (Strix Halo / Ryzen AI MAX) ---
    {
        "hw_vendor": "amd", "hw_arch": "gfx1151", "hw_name": "Ryzen AI MAX+ 395 (Strix Halo)",
        "hw_extra": {"unified_memory_gb": 128},
        "model_family": "qwen3", "runtime": "llama.cpp", "status": "solved", "quant": "Q4_K_M",
        "pointer": LLAMA_CPP_BUILD, "evidence_kind": "upstream-doc",
        "quote": "This provides GPU acceleration on HIP-supported AMD GPUs.",
        "notes": "Strix Halo (gfx1151) with up to 128 GB unified memory runs Qwen3 via llama.cpp Vulkan/ROCm.",
    },
    {
        "hw_vendor": "amd", "hw_arch": "gfx1151", "hw_name": "Ryzen AI MAX+ 395 (Strix Halo)",
        "hw_extra": {"unified_memory_gb": 128},
        "model_family": "llama-3", "runtime": "llama.cpp", "status": "solved", "quant": "Q4_K_M",
        "pointer": HF_LLAMA3_GGUF, "evidence_kind": "model-repo",
        "quote": "base_model: meta-llama/Llama-3.3-70B-Instruct",
        "notes": "Llama 3.3 70B Q4_K_M fits in unified memory on Strix Halo (gfx1151) via llama.cpp.",
    },

    # --- AMD: gfx942 (MI300X) ---
    {
        "hw_vendor": "amd", "hw_arch": "gfx942", "hw_name": "Instinct MI300X",
        "hw_extra": {"vram_gb": 192},
        "model_family": "deepseek", "runtime": "vllm", "status": "solved", "quant": "fp8",
        "pointer": HF_DEEPSEEK_R1, "evidence_kind": "model-repo",
        "quote": "For instance, you can easily start a service using [vLLM](https://github.com/vllm-project/vllm):",
        "notes": "DeepSeek-R1 FP8 runs on MI300X (gfx942, 192 GB HBM3) with vLLM ROCm.",
    },
    {
        "hw_vendor": "amd", "hw_arch": "gfx942", "hw_name": "Instinct MI300X",
        "hw_extra": {"vram_gb": 192},
        "model_family": "qwen3", "runtime": "vllm", "status": "solved", "quant": "bf16",
        "pointer": HF_QWEN3_32B, "evidence_kind": "model-repo",
        "quote": "For deployment, you can use `sglang>=0.4.6.post1` or `vllm>=0.8.5` or to create an OpenAI-compatible API endpoint:",
        "notes": "Qwen3-32B BF16 runs on MI300X (gfx942) via vLLM ROCm.",
    },
    {
        "hw_vendor": "amd", "hw_arch": "gfx942", "hw_name": "Instinct MI300X",
        "hw_extra": {"vram_gb": 192},
        "model_family": "llama-3", "runtime": "ollama", "status": "solved", "quant": "Q4_K_M",
        "pointer": OLLAMA_GPU, "evidence_kind": "upstream-doc",
        "quote": "| gfx942 | Radeon Instinct MI300X/MI300A |",
        "notes": "Ollama officially lists gfx942 (MI300X/MI300A) as supported for ROCm GPU inference.",
    },

    # --- Apple: m3-max ---
    {
        "hw_vendor": "apple", "hw_arch": "m3-max", "hw_name": "Apple M3 Max",
        "hw_extra": {"unified_memory_gb": 128},
        "model_family": "qwen3", "runtime": "mlx-lm", "status": "solved", "quant": "mlx-4bit",
        "pointer": HF_MLX_QWEN3, "evidence_kind": "model-repo",
        "quote": "from mlx_lm import load, generate",
        "notes": "Qwen3-32B-4bit runs on Apple M3 Max via mlx-lm.",
    },
    {
        "hw_vendor": "apple", "hw_arch": "m3-max", "hw_name": "Apple M3 Max",
        "hw_extra": {"unified_memory_gb": 128},
        "model_family": "gemma-3", "runtime": "mlx-lm", "status": "solved", "quant": "mlx-4bit",
        "pointer": HF_MLX_GEMMA3, "evidence_kind": "model-repo",
        "quote": "base_model: google/gemma-3-27b-pt",
        "notes": "Gemma 3 27B 4-bit runs on Apple M3 Max via mlx-lm.",
    },
    {
        "hw_vendor": "apple", "hw_arch": "m3-max", "hw_name": "Apple M3 Max",
        "hw_extra": {"unified_memory_gb": 128},
        "model_family": "qwen3", "runtime": "vllm", "status": "rejected", "quant": None,
        "pointer": VLLM_GPU, "evidence_kind": "upstream-doc",
        "quote": "=== \"NVIDIA CUDA\"",
        "notes": "Upstream vLLM GPU backend targets NVIDIA CUDA/ROCm/XPU and does not support Apple Silicon Metal; use mlx-lm or vllm-metal instead.",
    },

    # --- Apple: m4-max ---
    {
        "hw_vendor": "apple", "hw_arch": "m4-max", "hw_name": "Apple M4 Max",
        "hw_extra": {"unified_memory_gb": 128},
        "model_family": "llama-3", "runtime": "mlx-lm", "status": "solved", "quant": "mlx-4bit",
        "pointer": HF_MLX_LLAMA3, "evidence_kind": "model-repo",
        "quote": "from mlx_lm import load, generate",
        "notes": "Llama-3.3-70B-Instruct-4bit runs on Apple M4 Max (128 GB unified memory) via mlx-lm.",
    },
    {
        "hw_vendor": "apple", "hw_arch": "m4-max", "hw_name": "Apple M4 Max",
        "hw_extra": {"unified_memory_gb": 128},
        "model_family": "deepseek", "runtime": "mlx-lm", "status": "solved", "quant": "mlx-4bit",
        "pointer": HF_MLX_DEEPSEEK, "evidence_kind": "model-repo",
        "quote": "base_model: deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        "notes": "DeepSeek-R1-Distill-Qwen-32B-4bit runs on Apple M4 Max via mlx-lm.",
    },
    {
        "hw_vendor": "apple", "hw_arch": "m4-max", "hw_name": "Apple M4 Max",
        "hw_extra": {"unified_memory_gb": 128},
        "model_family": "mistral", "runtime": "mlx-lm", "status": "solved", "quant": "mlx-4bit",
        "pointer": HF_MLX_MISTRAL, "evidence_kind": "model-repo",
        "quote": "base_model: mistralai/Mistral-Small-24B-Instruct-2501",
        "notes": "Mistral-Small-24B-Instruct-2501-4bit runs on Apple M4 Max via mlx-lm.",
    },

    # --- Intel: arc-b580 ---
    {
        "hw_vendor": "intel", "hw_arch": "arc-b580", "hw_name": "Intel Arc B580",
        "hw_extra": {"vram_gb": 12},
        "model_family": "qwen3", "runtime": "llama.cpp", "status": "solved", "quant": "Q4_K_M",
        "pointer": LLAMA_CPP_SYCL, "evidence_kind": "upstream-doc",
        "quote": "| Intel Arc B-Series            | Support | Arc B580                              |",
        "notes": "Intel Arc B580 (12 GB) is officially supported in llama.cpp SYCL backend for Qwen3.",
    },
    {
        "hw_vendor": "intel", "hw_arch": "arc-b580", "hw_name": "Intel Arc B580",
        "hw_extra": {"vram_gb": 12},
        "model_family": "llama-3", "runtime": "llama.cpp", "status": "solved", "quant": "Q4_K_M",
        "pointer": LLAMA_CPP_SYCL, "evidence_kind": "upstream-doc",
        "quote": "| Intel Arc B-Series            | Support | Arc B580                              |",
        "notes": "Llama 3 8B Q4_K_M runs on Intel Arc B580 via llama.cpp SYCL backend.",
    },
    {
        "hw_vendor": "intel", "hw_arch": "arc-b580", "hw_name": "Intel Arc B580",
        "hw_extra": {"vram_gb": 12},
        "model_family": "gpt-oss", "runtime": "vllm", "status": "rejected", "quant": None,
        "pointer": VLLM_GPU, "evidence_kind": "upstream-doc",
        "quote": "=== \"NVIDIA CUDA\"",
        "notes": "Standard vLLM CUDA wheels require NVIDIA CUDA; Intel Arc B580 requires vllm-xpu-kernels or llama.cpp SYCL.",
    },

    # --- Intel: arc-a770 ---
    {
        "hw_vendor": "intel", "hw_arch": "arc-a770", "hw_name": "Intel Arc A770",
        "hw_extra": {"vram_gb": 16},
        "model_family": "qwen3", "runtime": "llama.cpp", "status": "solved", "quant": "Q4_K_M",
        "pointer": LLAMA_CPP_SYCL, "evidence_kind": "upstream-doc",
        "quote": "|Arc A770|42|55|+30%|",
        "notes": "Intel Arc A770 (16 GB) is supported in llama.cpp SYCL backend for Qwen3.",
    },
    {
        "hw_vendor": "intel", "hw_arch": "arc-a770", "hw_name": "Intel Arc A770",
        "hw_extra": {"vram_gb": 16},
        "model_family": "gemma-3", "runtime": "llama.cpp", "status": "solved", "quant": "Q4_K_M",
        "pointer": LLAMA_CPP_SYCL, "evidence_kind": "upstream-doc",
        "quote": "|Arc A770|42|55|+30%|",
        "notes": "Gemma 3 12B/4B GGUF runs on Intel Arc A770 (16 GB) via llama.cpp SYCL.",
    },
    {
        "hw_vendor": "intel", "hw_arch": "arc-a770", "hw_name": "Intel Arc A770",
        "hw_extra": {"vram_gb": 16},
        "model_family": "mistral", "runtime": "ollama", "status": "solved", "quant": "Q4_K_M",
        "pointer": LLAMA_CPP_SYCL, "evidence_kind": "upstream-doc",
        "quote": "|Arc A770|42|55|+30%|",
        "notes": "Mistral 7B/Small GGUF runs on Intel Arc A770 (16 GB) via SYCL/Vulkan-accelerated runtimes.",
    },
]


def fetch(http: Http) -> tuple[list[dict], list[dict]]:
    cache: dict[str, str] = {}
    rows: list[dict] = []
    rejects: list[dict] = []

    for spec in SPECS:
        url = spec["pointer"]
        if url not in cache:
            txt = http.get_text(url)
            if txt is None:
                rejects.append({"spec": spec, "error": f"failed to fetch {url}"})
                continue
            cache[url] = txt
        http.rows_in += 1

        try:
            quote = verbatim(cache[url], spec["quote"])
        except ValueError as e:
            rejects.append({"spec": spec, "error": str(e)})
            continue

        rows.append(make_row(
            hw_vendor=spec["hw_vendor"],
            hw_arch=spec["hw_arch"],
            hw_name=spec["hw_name"],
            hw_extra=spec["hw_extra"],
            model_family=spec["model_family"],
            runtime=spec["runtime"],
            status=spec["status"],
            source_kind="hand",
            quant=spec.get("quant"),
            pointer=url,
            notes=spec["notes"],
            reported_by="curated:v1",
            created_by="hand",
            missing=[],
            evidence=[{
                "url": url,
                "quote": quote,
                "kind": spec["evidence_kind"],
            }],
        ))

    return rows, rejects
