"""Source: Apple Silicon / Mac integration docs (mlx, mlx-lm, vllm-metal, ollama, mlc-llm).

Fetches upstream READMEs from the major macOS / Apple Silicon inference engines:
  - ml-explore/mlx
  - ml-explore/mlx-lm
  - vllm-project/vllm-metal
  - ollama/ollama
  - mlc-ai/mlc-llm

Every quote is re-verified against the fetched text via `common.verbatim`.
"""
from __future__ import annotations

from scrapers.common import make_row, verbatim

SOURCE_KEY = "apple_integrations"
REPORTED = f"scraper:{SOURCE_KEY}"

DOCS = [
    {
        "url": "https://raw.githubusercontent.com/ml-explore/mlx/main/README.md",
        "pointer": "https://github.com/ml-explore/mlx/blob/main/README.md",
        "runtime": "mlx",
        "hw_vendor": "apple",
        "hw_arch": "m1",
        "hw_name": "Apple Silicon (Metal)",
        "quote": "MLX is an array framework for machine learning on Apple silicon",
    },
    {
        "url": "https://raw.githubusercontent.com/ml-explore/mlx-lm/main/README.md",
        "pointer": "https://github.com/ml-explore/mlx-lm/blob/main/README.md",
        "runtime": "mlx-lm",
        "hw_vendor": "apple",
        "hw_arch": "m1",
        "hw_name": "Apple Silicon (Metal)",
        "quote": "models on Apple silicon with MLX.",
    },
    {
        "url": "https://raw.githubusercontent.com/vllm-project/vllm-metal/main/README.md",
        "pointer": "https://github.com/vllm-project/vllm-metal/blob/main/README.md",
        "runtime": "vllm-metal",
        "hw_vendor": "apple",
        "hw_arch": "m1",
        "hw_name": "Apple Silicon (macOS 15+)",
        "quote": "vLLM Metal is a plugin that enables vLLM to run on Apple Silicon Macs using MLX as the primary compute backend.",
    },
    {
        "url": "https://raw.githubusercontent.com/vllm-project/vllm-metal/main/README.md",
        "pointer": "https://github.com/vllm-project/vllm-metal/blob/main/README.md",
        "runtime": "vllm-metal",
        "hw_vendor": "apple",
        "hw_arch": "m5",
        "hw_name": "Apple M5 (NAX tensor units)",
        "quote": "vLLM Metal now uses M5 NAX tensor units to accelerate MHA, GQA, and MQA prefill.",
    },
    {
        "url": "https://raw.githubusercontent.com/ollama/ollama/main/README.md",
        "pointer": "https://github.com/ollama/ollama/blob/main/README.md",
        "runtime": "ollama",
        "hw_vendor": "apple",
        "hw_arch": "m1",
        "hw_name": "macOS (Apple Silicon)",
        "quote": "### macOS",
    },
    {
        "url": "https://raw.githubusercontent.com/mlc-ai/mlc-llm/main/README.md",
        "pointer": "https://github.com/mlc-ai/mlc-llm/blob/main/README.md",
        "runtime": "mlc-llm",
        "hw_vendor": "apple",
        "hw_arch": "m1",
        "hw_name": "Apple Silicon (Metal)",
        "quote": "<td>macOS</td>",
    },
]


def fetch(http) -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    cache: dict[str, str] = {}
    for spec in DOCS:
        url = spec["url"]
        if url not in cache:
            cache[url] = http.get(url).decode("utf-8", errors="replace")
        body = cache[url]
        ev = verbatim(body, spec["quote"])
        rows.append(make_row(
            hw_vendor=spec["hw_vendor"],
            hw_arch=spec["hw_arch"],
            hw_name=spec["hw_name"],
            model_family="*",
            runtime=spec["runtime"],
            status="solved",
            missing=["model"],
            source_kind="scraped",
            evidence=[{"url": spec["pointer"], "quote": ev}],
            pointer=spec["pointer"],
            reported_by=REPORTED,
        ))
    return rows, []
