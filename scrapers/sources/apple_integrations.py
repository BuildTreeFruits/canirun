"""Source: Apple Silicon / Mac integration docs (mlx, mlx-lm, vllm-metal, ollama, mlc-llm).

Fetches upstream READMEs / docs from the major macOS / Apple Silicon inference engines:
  - ml-explore/mlx
  - ml-explore/mlx-lm
  - vllm-project/vllm-metal
  - ollama/ollama (docs/gpu.mdx)
  - mlc-ai/mlc-llm

Every quote is re-verified against the fetched text via `common.verbatim`.
"""
from __future__ import annotations

from scrapers.common import make_row, verbatim

SOURCE_KEY = "apple_integrations"
REPORTED = f"scraper:{SOURCE_KEY}"

# Standard Apple Silicon M-series chips: (hw_arch, hw_name, unified_memory_gb)
APPLE_CHIPS: list[tuple[str, str, int]] = [
    ("m1", "Apple M1", 16),
    ("m1-pro", "Apple M1 Pro", 32),
    ("m1-max", "Apple M1 Max", 64),
    ("m1-ultra", "Apple M1 Ultra", 128),
    ("m2", "Apple M2", 24),
    ("m2-pro", "Apple M2 Pro", 32),
    ("m2-max", "Apple M2 Max", 96),
    ("m2-ultra", "Apple M2 Ultra", 192),
    ("m3", "Apple M3", 24),
    ("m3-pro", "Apple M3 Pro", 36),
    ("m3-max", "Apple M3 Max", 128),
    ("m3-ultra", "Apple M3 Ultra", 512),
    ("m4", "Apple M4", 32),
    ("m4-pro", "Apple M4 Pro", 64),
    ("m4-max", "Apple M4 Max", 128),
    ("m4-ultra", "Apple M4 Ultra", 256),
    ("m5", "Apple M5", 32),
    ("m5-pro", "Apple M5 Pro", 64),
    ("m5-max", "Apple M5 Max", 128),
]

DOCS = [
    {
        "url": "https://raw.githubusercontent.com/vllm-project/vllm-metal/main/README.md",
        "pointer": "https://github.com/vllm-project/vllm-metal/blob/main/README.md",
        "runtime": "vllm-metal",
        "hw_vendor": "apple",
        "hw_arch": "m1",
        "hw_name": "Apple Silicon (macOS 15+)",
        "model_family": "*",
        "missing": ["model"],
        "quote": "vLLM Metal is a plugin that enables vLLM to run on Apple Silicon Macs using MLX as the primary compute backend.",
    },
    {
        "url": "https://raw.githubusercontent.com/vllm-project/vllm-metal/main/README.md",
        "pointer": "https://github.com/vllm-project/vllm-metal/blob/main/README.md",
        "runtime": "vllm-metal",
        "hw_vendor": "apple",
        "hw_arch": "m5",
        "hw_name": "Apple M5 (NAX tensor units)",
        "model_family": "*",
        "missing": ["model"],
        "quote": "vLLM Metal now uses M5 NAX tensor units to accelerate MHA, GQA, and MQA prefill.",
    },
    {
        "url": "https://raw.githubusercontent.com/vllm-project/vllm-metal/main/README.md",
        "pointer": "https://github.com/vllm-project/vllm-metal/blob/main/README.md",
        "runtime": "vllm-metal",
        "hw_vendor": "apple",
        "hw_arch": "m5-pro",
        "hw_name": "Apple M5 Pro (Metal)",
        "model_family": "*",
        "missing": ["model"],
        "quote": "DiffusionGemma now supports Jev-like System 1 decisions on Metal, with median decision latency under 0.2 s on an M5 Pro.",
    },
    {
        "url": "https://raw.githubusercontent.com/vllm-project/vllm-metal/main/README.md",
        "pointer": "https://github.com/vllm-project/vllm-metal/blob/main/README.md",
        "runtime": "vllm-metal",
        "hw_vendor": "apple",
        "hw_arch": "m1",
        "hw_name": "Apple Silicon (macOS 15+)",
        "model_family": "qwen3",
        "quant": "mlx-8bit",
        "missing": [],
        "quote": "Qwen3.8 now runs on Metal! `mlx-community/Qwen3.8-27B-8bit` serves a 27B hybrid SDPA + GDN linear model on a single Apple Silicon Mac.",
    },
    {
        "url": "https://raw.githubusercontent.com/vllm-project/vllm-metal/main/README.md",
        "pointer": "https://github.com/vllm-project/vllm-metal/blob/main/README.md",
        "runtime": "vllm-metal",
        "hw_vendor": "apple",
        "hw_arch": "m1",
        "hw_name": "Apple Silicon (macOS 15+)",
        "model_family": "stable-diffusion",
        "missing": [],
        "quote": "[Text-to-image generation](https://docs.vllm.ai/projects/vllm-metal/en/latest/omni/#text-to-image) is now supported through vLLM-Omni, starting with SDXL.",
    },
    {
        "url": "https://raw.githubusercontent.com/mlc-ai/mlc-llm/main/README.md",
        "pointer": "https://github.com/mlc-ai/mlc-llm/blob/main/README.md",
        "runtime": "mlc-llm",
        "hw_vendor": "apple",
        "hw_arch": "m1",
        "hw_name": "Apple Silicon (Metal)",
        "model_family": "*",
        "missing": ["model"],
        "quote": "<td>macOS</td>",
    },
]

# Runtimes whose upstream docs state general Apple Silicon / Metal support,
# expanded across all M1-M5 chip tiers (`scraped` on m1, `derived` on others).
M_SERIES_RUNTIMES = [
    {
        "url": "https://raw.githubusercontent.com/ollama/ollama/main/docs/gpu.mdx",
        "pointer": "https://github.com/ollama/ollama/blob/main/docs/gpu.mdx",
        "runtime": "ollama",
        "quote": "Ollama supports GPU acceleration on Apple devices via the Metal API.",
        "notes": "Upstream Ollama docs state Metal GPU acceleration on Apple devices; expanded across Apple Silicon M-series tiers.",
    },
    {
        "url": "https://raw.githubusercontent.com/ml-explore/mlx/main/README.md",
        "pointer": "https://github.com/ml-explore/mlx/blob/main/README.md",
        "runtime": "mlx",
        "quote": "MLX is an array framework for machine learning on Apple silicon",
        "notes": "Upstream MLX targets all Apple Silicon M-series GPUs via Metal.",
    },
    {
        "url": "https://raw.githubusercontent.com/ml-explore/mlx-lm/main/README.md",
        "pointer": "https://github.com/ml-explore/mlx-lm/blob/main/README.md",
        "runtime": "mlx-lm",
        "quote": "models on Apple silicon with MLX.",
        "notes": "Upstream MLX-LM targets all Apple Silicon M-series GPUs via Metal.",
    },
]


def fetch(http) -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    cache: dict[str, str] = {}

    def get_body(url: str) -> str:
        if url not in cache:
            cache[url] = http.get(url).decode("utf-8", errors="replace")
        return cache[url]

    for spec in DOCS:
        body = get_body(spec["url"])
        ev = verbatim(body, spec["quote"])
        rows.append(make_row(
            hw_vendor=spec["hw_vendor"],
            hw_arch=spec["hw_arch"],
            hw_name=spec["hw_name"],
            model_family=spec["model_family"],
            runtime=spec["runtime"],
            quant=spec.get("quant"),
            status="solved",
            missing=spec["missing"],
            source_kind="scraped",
            evidence=[{"url": spec["pointer"], "quote": ev}],
            pointer=spec["pointer"],
            reported_by=REPORTED,
        ))

    for rt in M_SERIES_RUNTIMES:
        body = get_body(rt["url"])
        ev = verbatim(body, rt["quote"])
        for hw_arch, hw_name, mem_gb in APPLE_CHIPS:
            is_base = hw_arch == "m1"
            rows.append(make_row(
                hw_vendor="apple",
                hw_arch=hw_arch,
                hw_name=f"{hw_name} (Metal)",
                hw_extra={"backend": "Metal", "unified_memory_gb": mem_gb},
                model_family="*",
                runtime=rt["runtime"],
                status="solved",
                missing=["model"],
                source_kind="scraped" if is_base else "derived",
                created_by="scraper" if is_base else "derived",
                notes=rt["notes"],
                evidence=[{"url": rt["pointer"], "quote": ev}],
                pointer=rt["pointer"],
                reported_by=REPORTED,
            ))

    return rows, []
