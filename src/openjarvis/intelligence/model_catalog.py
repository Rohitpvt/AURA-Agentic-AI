"""Built-in model catalog with well-known ModelSpec entries."""

from __future__ import annotations

from typing import List

from openjarvis.core.registry import ModelRegistry
from openjarvis.core.types import ModelSpec, Quantization

BUILTIN_MODELS: List[ModelSpec] = [
    # -----------------------------------------------------------------------
    # Local models — Dense
    # -----------------------------------------------------------------------
    ModelSpec(
        model_id="qwen3:0.6b",
        name="Qwen3 0.6B",
        parameter_count_b=0.6,
        context_length=40960,
        supported_engines=("ollama", "vllm", "llamacpp", "sglang", "mlx", "lemonade"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen3-0.6B",
        },
    ),
    ModelSpec(
        model_id="qwen3:1.7b",
        name="Qwen3 1.7B",
        parameter_count_b=1.7,
        context_length=40960,
        supported_engines=("ollama", "vllm", "llamacpp", "sglang", "mlx", "lemonade"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen3-1.7B",
        },
    ),
    ModelSpec(
        model_id="qwen3:4b",
        name="Qwen3 4B",
        parameter_count_b=4.0,
        context_length=262144,
        supported_engines=("ollama", "vllm", "llamacpp", "sglang", "mlx", "lemonade"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen3-4B",
        },
    ),
    ModelSpec(
        model_id="qwen3:8b",
        name="Qwen3 8B",
        parameter_count_b=8.2,
        context_length=32768,
        supported_engines=("vllm", "ollama", "llamacpp", "sglang", "mlx", "lemonade"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen3-8B",
        },
    ),
    ModelSpec(
        model_id="qwen3:14b",
        name="Qwen3 14B",
        parameter_count_b=14.0,
        context_length=40960,
        supported_engines=("ollama", "vllm", "llamacpp", "sglang", "lemonade"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen3-14B",
        },
    ),
    ModelSpec(
        model_id="qwen3:30b",
        name="Qwen3 30B",
        parameter_count_b=30.0,
        context_length=262144,
        min_vram_gb=18.0,
        supported_engines=("ollama", "vllm", "sglang"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen3-30B",
        },
    ),
    ModelSpec(
        model_id="qwen3:32b",
        name="Qwen3 32B",
        parameter_count_b=32.0,
        context_length=32768,
        min_vram_gb=20.0,
        supported_engines=("ollama", "vllm"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen3-32B",
        },
    ),
    # -----------------------------------------------------------------------
    # Local models — Qwen3.5 (dense and MoE)
    # -----------------------------------------------------------------------
    ModelSpec(
        model_id="qwen3.5:0.8b",
        name="Qwen3.5 0.8B",
        parameter_count_b=0.8,
        context_length=131072,
        supported_engines=("ollama", "vllm", "llamacpp", "sglang", "mlx"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen3.5-0.8B",
            "mlx_repo": "mlx-community/Qwen3.5-0.8B-OptiQ-4bit",
        },
    ),
    ModelSpec(
        model_id="qwen3.5:2b",
        name="Qwen3.5 2B",
        parameter_count_b=2.0,
        context_length=131072,
        supported_engines=("ollama", "vllm", "llamacpp", "sglang", "mlx"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen3.5-2B",
            "mlx_repo": "mlx-community/Qwen3.5-2B-OptiQ-4bit",
        },
    ),
    ModelSpec(
        model_id="qwen3.5:9b",
        name="Qwen3.5 9B",
        parameter_count_b=9.0,
        context_length=131072,
        supported_engines=("ollama", "vllm", "llamacpp", "sglang", "mlx"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen3.5-9B",
            "gguf_file": "qwen3.5-9b-q4_k_m.gguf",
            "mlx_repo": "mlx-community/Qwen3.5-9B-MLX-4bit",
        },
    ),
    ModelSpec(
        model_id="qwen3.5:27b",
        name="Qwen3.5 27B",
        parameter_count_b=27.0,
        context_length=131072,
        min_vram_gb=16.0,
        supported_engines=("ollama", "vllm", "llamacpp", "sglang", "mlx"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen3.5-27B",
            "gguf_file": "qwen3.5-27b-q4_k_m.gguf",
            "mlx_repo": "mlx-community/Qwen3.5-27B-4bit-DWQ",
        },
    ),
    ModelSpec(
        model_id="qwen3.5:35b",
        name="Qwen3.5 35B",
        parameter_count_b=35.0,
        active_parameter_count_b=3.0,
        context_length=131072,
        supported_engines=("ollama", "vllm", "sglang"),
        provider="alibaba",
        metadata={
            "architecture": "moe",
            "hf_repo": "Qwen/Qwen3.5-35B",
        },
    ),
    ModelSpec(
        model_id="qwen3.5:122b",
        name="Qwen3.5 122B",
        parameter_count_b=122.0,
        active_parameter_count_b=10.0,
        context_length=131072,
        min_vram_gb=70.0,
        supported_engines=("ollama", "vllm", "sglang"),
        provider="alibaba",
        metadata={
            "architecture": "moe",
            "hf_repo": "Qwen/Qwen3.5-122B",
        },
    ),
    ModelSpec(
        model_id="qwen3.5:397b",
        name="Qwen3.5 397B",
        parameter_count_b=397.0,
        active_parameter_count_b=17.0,
        context_length=131072,
        min_vram_gb=220.0,
        supported_engines=("vllm", "sglang"),
        provider="alibaba",
        metadata={
            "architecture": "moe",
            "hf_repo": "Qwen/Qwen3.5-397B",
        },
    ),
    ModelSpec(
        model_id="llama3.3:70b",
        name="Llama 3.3 70B",
        parameter_count_b=70.0,
        context_length=131072,
        min_vram_gb=40.0,
        supported_engines=("ollama", "vllm"),
        provider="meta",
        metadata={
            "architecture": "dense",
            "hf_repo": "meta-llama/Llama-3.3-70B-Instruct",
        },
    ),
    ModelSpec(
        model_id="llama3.2:3b",
        name="Llama 3.2 3B",
        parameter_count_b=3.0,
        context_length=131072,
        supported_engines=("ollama", "vllm", "llamacpp"),
        provider="meta",
        metadata={
            "architecture": "dense",
            "hf_repo": "meta-llama/Llama-3.2-3B-Instruct",
        },
    ),
    ModelSpec(
        model_id="deepseek-coder-v2:16b",
        name="DeepSeek Coder V2 16B",
        parameter_count_b=16.0,
        context_length=131072,
        supported_engines=("ollama", "vllm"),
        provider="deepseek",
        metadata={
            "architecture": "dense",
            "hf_repo": "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct",
        },
    ),
    ModelSpec(
        model_id="llama3.2:1b",
        name="Llama 3.2 1B",
        parameter_count_b=1.2,
        context_length=131072,
        supported_engines=("ollama", "vllm", "llamacpp"),
        provider="meta",
        metadata={
            "architecture": "dense",
            "hf_repo": "meta-llama/Llama-3.2-1B-Instruct",
        },
    ),
    ModelSpec(
        model_id="llama3.1:8b",
        name="Llama 3.1 8B",
        parameter_count_b=8.0,
        context_length=131072,
        supported_engines=("ollama", "vllm", "llamacpp"),
        provider="meta",
        metadata={
            "architecture": "dense",
            "hf_repo": "meta-llama/Llama-3.1-8B-Instruct",
        },
    ),
    ModelSpec(
        model_id="qwen2.5:3b",
        name="Qwen 2.5 3B",
        parameter_count_b=3.09,
        context_length=32768,
        supported_engines=("ollama", "vllm", "llamacpp"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen2.5-3B-Instruct",
        },
    ),
    ModelSpec(
        model_id="qwen2.5:7b",
        name="Qwen 2.5 7B",
        parameter_count_b=7.61,
        context_length=32768,
        supported_engines=("ollama", "vllm", "llamacpp"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen2.5-7B-Instruct",
        },
    ),
    ModelSpec(
        model_id="qwen2.5:14b",
        name="Qwen 2.5 14B",
        parameter_count_b=14.7,
        context_length=32768,
        supported_engines=("ollama", "vllm", "llamacpp"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen2.5-14B-Instruct",
        },
    ),
    ModelSpec(
        model_id="qwen2.5-coder:7b",
        name="Qwen 2.5 Coder 7B",
        parameter_count_b=7.61,
        context_length=32768,
        supported_engines=("ollama", "vllm", "llamacpp"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen2.5-Coder-7B-Instruct",
        },
    ),
    ModelSpec(
        model_id="qwen2.5-coder:14b",
        name="Qwen 2.5 Coder 14B",
        parameter_count_b=14.7,
        context_length=32768,
        supported_engines=("ollama", "vllm", "llamacpp"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen2.5-Coder-14B-Instruct",
        },
    ),
    ModelSpec(
        model_id="deepseek-r1:7b",
        name="DeepSeek R1 7B (Distill)",
        parameter_count_b=7.0,
        context_length=64000,
        supported_engines=("ollama", "vllm", "llamacpp"),
        provider="deepseek",
        metadata={
            "architecture": "dense",
            "hf_repo": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
        },
    ),
    ModelSpec(
        model_id="deepseek-r1:8b",
        name="DeepSeek R1 8B (Distill)",
        parameter_count_b=8.0,
        context_length=64000,
        supported_engines=("ollama", "vllm", "llamacpp"),
        provider="deepseek",
        metadata={
            "architecture": "dense",
            "hf_repo": "deepseek-ai/DeepSeek-R1-Distill-Llama-8B",
        },
    ),
    ModelSpec(
        model_id="deepseek-r1:14b",
        name="DeepSeek R1 14B (Distill)",
        parameter_count_b=14.0,
        context_length=64000,
        supported_engines=("ollama", "vllm", "llamacpp"),
        provider="deepseek",
        metadata={
            "architecture": "dense",
            "hf_repo": "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B",
        },
    ),
    ModelSpec(
        model_id="phi4:14b",
        name="Phi-4 14B",
        parameter_count_b=14.0,
        context_length=16384,
        supported_engines=("ollama", "vllm", "llamacpp"),
        provider="microsoft",
        metadata={
            "architecture": "dense",
            "hf_repo": "microsoft/phi-4",
        },
    ),
    ModelSpec(
        model_id="gemma2:9b",
        name="Gemma 2 9B",
        parameter_count_b=9.0,
        context_length=8192,
        supported_engines=("ollama", "vllm", "llamacpp"),
        provider="google",
        metadata={
            "architecture": "dense",
            "hf_repo": "google/gemma-2-9b-it",
        },
    ),
    ModelSpec(
        model_id="mistral:7b",
        name="Mistral 7B",
        parameter_count_b=7.0,
        context_length=32768,
        supported_engines=("ollama", "vllm", "llamacpp"),
        provider="mistral",
        metadata={
            "architecture": "dense",
            "hf_repo": "mistralai/Mistral-7B-Instruct-v0.3",
        },
    ),
    # -----------------------------------------------------------------------
    # Local models — Mixture of Experts (MoE)
    # -----------------------------------------------------------------------
    ModelSpec(
        model_id="gpt-oss:120b",
        name="GPT-OSS 120B",
        parameter_count_b=117.0,
        active_parameter_count_b=5.1,
        context_length=131072,
        min_vram_gb=12.0,
        supported_engines=("vllm", "ollama"),
        provider="open-source",
        metadata={
            "architecture": "moe",
            "hf_repo": "OpenBuddy/GPT-OSS-120B",
        },
    ),
    ModelSpec(
        model_id="glm-4.7-flash",
        name="GLM 4.7 Flash",
        parameter_count_b=30.0,
        active_parameter_count_b=3.0,
        context_length=131072,
        min_vram_gb=8.0,
        supported_engines=("vllm", "sglang", "llamacpp"),
        provider="zhipu",
        metadata={
            "architecture": "moe",
            "hf_repo": "THUDM/GLM-4.7-Flash-Chat",
        },
    ),
    ModelSpec(
        model_id="trinity-mini",
        name="Trinity Mini",
        parameter_count_b=26.0,
        active_parameter_count_b=3.0,
        context_length=128000,
        min_vram_gb=8.0,
        supported_engines=("vllm", "llamacpp"),
        provider="trinity",
        metadata={
            "architecture": "moe",
            "hf_repo": "TrinityAI/Trinity-Mini-26B",
        },
    ),
    # -----------------------------------------------------------------------
    # Local models — Qwen3.5 (4B dense, plus MoE variants)
    # -----------------------------------------------------------------------
    ModelSpec(
        model_id="qwen3.5:4b",
        name="Qwen3.5 4B",
        parameter_count_b=4.0,
        context_length=262144,
        min_vram_gb=3.0,
        supported_engines=("ollama", "vllm", "sglang", "llamacpp", "mlx"),
        provider="alibaba",
        metadata={
            "architecture": "dense",
            "hf_repo": "Qwen/Qwen3.5-4B",
            "gguf_file": "qwen3.5-4b-q4_k_m.gguf",
            "mlx_repo": "mlx-community/Qwen3.5-4B-OptiQ-4bit",
        },
    ),
    ModelSpec(
        model_id="qwen3.5:35b-a3b",
        name="Qwen3.5 35B A3B",
        parameter_count_b=35.0,
        active_parameter_count_b=3.0,
        context_length=262144,
        min_vram_gb=8.0,
        supported_engines=("ollama", "vllm", "sglang"),
        provider="alibaba",
        metadata={
            "architecture": "moe",
            "hf_repo": "Qwen/Qwen3.5-35B-A3B",
        },
    ),
    ModelSpec(
        model_id="qwen3.5:122b-a10b",
        name="Qwen3.5 122B A10B",
        parameter_count_b=122.0,
        active_parameter_count_b=10.0,
        context_length=262144,
        min_vram_gb=20.0,
        supported_engines=("vllm", "sglang"),
        provider="alibaba",
        metadata={
            "architecture": "moe",
            "hf_repo": "Qwen/Qwen3.5-122B-A10B",
        },
    ),
    ModelSpec(
        model_id="qwen3.5:397b-a17b",
        name="Qwen3.5 397B A17B",
        parameter_count_b=397.0,
        active_parameter_count_b=17.0,
        context_length=262144,
        min_vram_gb=50.0,
        supported_engines=("vllm", "sglang"),
        provider="alibaba",
        metadata={
            "architecture": "moe",
            "hf_repo": "Qwen/Qwen3.5-397B-A17B",
        },
    ),
    # -----------------------------------------------------------------------
    # Local models — Unsloth GGUF Quantizations
    # -----------------------------------------------------------------------
    ModelSpec(
        model_id="unsloth/Qwen3.5-35B-A3B-GGUF",
        name="Qwen3.5 35B A3B (Unsloth GGUF)",
        parameter_count_b=35.0,
        active_parameter_count_b=3.0,
        context_length=262144,
        min_vram_gb=6.0,
        quantization=Quantization.GGUF,
        supported_engines=("ollama", "llamacpp"),
        provider="unsloth",
        metadata={
            "architecture": "moe",
            "hf_repo": "unsloth/Qwen3.5-35B-A3B-GGUF",
            "base_model": "Qwen/Qwen3.5-35B-A3B",
        },
    ),
    ModelSpec(
        model_id="unsloth/Qwen3.5-122B-A10B-GGUF",
        name="Qwen3.5 122B A10B (Unsloth GGUF)",
        parameter_count_b=122.0,
        active_parameter_count_b=10.0,
        context_length=262144,
        min_vram_gb=16.0,
        quantization=Quantization.GGUF,
        supported_engines=("ollama", "llamacpp"),
        provider="unsloth",
        metadata={
            "architecture": "moe",
            "hf_repo": "unsloth/Qwen3.5-122B-A10B-GGUF",
            "base_model": "Qwen/Qwen3.5-122B-A10B",
        },
    ),
    ModelSpec(
        model_id="unsloth/Qwen3.5-397B-A17B-GGUF",
        name="Qwen3.5 397B A17B (Unsloth GGUF)",
        parameter_count_b=397.0,
        active_parameter_count_b=17.0,
        context_length=262144,
        min_vram_gb=40.0,
        quantization=Quantization.GGUF,
        supported_engines=("ollama", "llamacpp"),
        provider="unsloth",
        metadata={
            "architecture": "moe",
            "hf_repo": "unsloth/Qwen3.5-397B-A17B-GGUF",
            "base_model": "Qwen/Qwen3.5-397B-A17B",
        },
    ),
    ModelSpec(
        model_id="unsloth/GLM-5-GGUF",
        name="GLM-5 (Unsloth GGUF)",
        parameter_count_b=100.0,
        context_length=131072,
        min_vram_gb=12.0,
        quantization=Quantization.GGUF,
        supported_engines=("ollama", "llamacpp"),
        provider="unsloth",
        metadata={
            "architecture": "dense",
            "hf_repo": "unsloth/GLM-5-GGUF",
            "base_model": "THUDM/GLM-5",
        },
    ),
    ModelSpec(
        model_id="unsloth/GLM-4.7-Flash-GGUF",
        name="GLM 4.7 Flash (Unsloth GGUF)",
        parameter_count_b=30.0,
        active_parameter_count_b=3.0,
        context_length=131072,
        min_vram_gb=6.0,
        quantization=Quantization.GGUF,
        supported_engines=("ollama", "llamacpp"),
        provider="unsloth",
        metadata={
            "architecture": "moe",
            "hf_repo": "unsloth/GLM-4.7-Flash-GGUF",
            "base_model": "THUDM/GLM-4.7-Flash-Chat",
        },
    ),
    ModelSpec(
        model_id="unsloth/Qwen3-Coder-Next-GGUF",
        name="Qwen3 Coder Next (Unsloth GGUF)",
        parameter_count_b=80.0,
        context_length=131072,
        min_vram_gb=12.0,
        quantization=Quantization.GGUF,
        supported_engines=("ollama", "llamacpp"),
        provider="unsloth",
        metadata={
            "architecture": "moe",
            "hf_repo": "unsloth/Qwen3-Coder-Next-GGUF",
            "base_model": "Qwen/Qwen3-Coder-Next",
        },
    ),
    ModelSpec(
        model_id="unsloth/MiniMax-M2.5-GGUF",
        name="MiniMax M2.5 (Unsloth GGUF)",
        parameter_count_b=229.0,
        context_length=131072,
        min_vram_gb=30.0,
        quantization=Quantization.GGUF,
        supported_engines=("ollama", "llamacpp"),
        provider="unsloth",
        metadata={
            "architecture": "moe",
            "hf_repo": "unsloth/MiniMax-M2.5-GGUF",
            "base_model": "MiniMax/MiniMax-M2.5",
        },
    ),
    ModelSpec(
        model_id="unsloth/Kimi-K2.5-GGUF",
        name="Kimi K2.5 (Unsloth GGUF)",
        parameter_count_b=1000.0,
        active_parameter_count_b=32.0,
        context_length=131072,
        min_vram_gb=40.0,
        quantization=Quantization.GGUF,
        supported_engines=("ollama", "llamacpp"),
        provider="unsloth",
        metadata={
            "architecture": "moe",
            "hf_repo": "unsloth/Kimi-K2.5-GGUF",
            "base_model": "moonshotai/Kimi-K2.5",
        },
    ),
    # -----------------------------------------------------------------------
    # Local models — LiquidAI LFM2.5 (Hybrid SSM+Transformer)
    # -----------------------------------------------------------------------
    ModelSpec(
        model_id="LiquidAI/LFM2.5-1.2B-Instruct-GGUF",
        name="LFM2.5 1.2B Instruct (GGUF)",
        parameter_count_b=1.2,
        context_length=32768,
        min_vram_gb=1.0,
        quantization=Quantization.GGUF,
        supported_engines=("llamacpp", "ollama"),
        provider="liquidai",
        metadata={
            "architecture": "hybrid_ssm_transformer",
            "hf_repo": "LiquidAI/LFM2.5-1.2B-Instruct-GGUF",
            "layers": "10 LIV convolution + 6 GQA",
            "languages": 8,
        },
    ),
    ModelSpec(
        model_id="LiquidAI/LFM2.5-1.2B-Instruct-MLX",
        name="LFM2.5 1.2B Instruct (MLX)",
        parameter_count_b=1.2,
        context_length=32768,
        min_vram_gb=1.0,
        supported_engines=("mlx",),
        provider="liquidai",
        metadata={
            "architecture": "hybrid_ssm_transformer",
            "hf_repo": "LiquidAI/LFM2.5-1.2B-Instruct-MLX",
            "layers": "10 LIV convolution + 6 GQA",
            "languages": 8,
        },
    ),
    ModelSpec(
        model_id="LiquidAI/LFM2.5-1.2B-Thinking-GGUF",
        name="LFM2.5 1.2B Thinking (GGUF)",
        parameter_count_b=1.2,
        context_length=32768,
        min_vram_gb=1.0,
        quantization=Quantization.GGUF,
        supported_engines=("llamacpp", "ollama"),
        provider="liquidai",
        metadata={
            "architecture": "hybrid_ssm_transformer",
            "hf_repo": "LiquidAI/LFM2.5-1.2B-Thinking-GGUF",
            "layers": "10 LIV convolution + 6 GQA",
            "variant": "reasoning-optimized",
            "languages": 8,
        },
    ),
    ModelSpec(
        model_id="LiquidAI/LFM2.5-1.2B-Thinking-MLX",
        name="LFM2.5 1.2B Thinking (MLX)",
        parameter_count_b=1.2,
        context_length=32768,
        min_vram_gb=1.0,
        supported_engines=("mlx",),
        provider="liquidai",
        metadata={
            "architecture": "hybrid_ssm_transformer",
            "hf_repo": "LiquidAI/LFM2.5-1.2B-Thinking-MLX",
            "layers": "10 LIV convolution + 6 GQA",
            "variant": "reasoning-optimized",
            "languages": 8,
        },
    ),
    # -----------------------------------------------------------------------
    # Local models — IBM Granite
    # -----------------------------------------------------------------------
    ModelSpec(
        model_id="granite3.3:8b",
        name="Granite 3.3 8B",
        parameter_count_b=8.0,
        context_length=128000,
        supported_engines=("ollama", "vllm", "llamacpp"),
        provider="ibm",
        metadata={
            "architecture": "dense",
            "hf_repo": "ibm-granite/granite-3.3-8b-instruct",
            "url": "https://www.ibm.com/granite",
        },
    ),
    ModelSpec(
        model_id="granite4.0-micro",
        name="Granite 4.0 Micro 3B",
        parameter_count_b=3.0,
        context_length=128000,
        supported_engines=("ollama", "vllm", "llamacpp"),
        provider="ibm",
        metadata={
            "architecture": "dense",
            "hf_repo": "ibm-granite/granite-4.0-micro",
            "url": "https://www.ibm.com/granite",
        },
    ),
    ModelSpec(
        model_id="granite4.0-h-small",
        name="Granite 4.0 H Small 32B",
        parameter_count_b=32.0,
        active_parameter_count_b=9.0,
        context_length=128000,
        supported_engines=("ollama", "vllm"),
        provider="ibm",
        metadata={
            "architecture": "moe",
            "hf_repo": "ibm-granite/granite-4.0-h-small",
            "url": "https://www.ibm.com/granite",
        },
    ),
    # -----------------------------------------------------------------------
    # Cloud models — OpenAI
    # -----------------------------------------------------------------------
    ModelSpec(
        model_id="gpt-4o",
        name="GPT-4o",
        parameter_count_b=0.0,
        context_length=128000,
        supported_engines=("cloud",),
        provider="openai",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 2.50,
            "pricing_output": 10.00,
            "url": "https://platform.openai.com/docs/models/gpt-4o",
        },
    ),
    ModelSpec(
        model_id="gpt-4o-mini",
        name="GPT-4o Mini",
        parameter_count_b=0.0,
        context_length=128000,
        supported_engines=("cloud",),
        provider="openai",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 0.15,
            "pricing_output": 0.60,
            "url": "https://platform.openai.com/docs/models/gpt-4o-mini",
        },
    ),
    ModelSpec(
        model_id="o1",
        name="o1",
        parameter_count_b=0.0,
        context_length=200000,
        supported_engines=("cloud",),
        provider="openai",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 15.00,
            "pricing_output": 60.00,
            "url": "https://platform.openai.com/docs/models/o1",
        },
    ),
    ModelSpec(
        model_id="o1-mini",
        name="o1-mini",
        parameter_count_b=0.0,
        context_length=128000,
        supported_engines=("cloud",),
        provider="openai",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 1.10,
            "pricing_output": 4.40,
            "url": "https://platform.openai.com/docs/models/o1-mini",
        },
    ),
    ModelSpec(
        model_id="o3-mini",
        name="o3-mini",
        parameter_count_b=0.0,
        context_length=200000,
        supported_engines=("cloud",),
        provider="openai",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 1.10,
            "pricing_output": 4.40,
            "url": "https://platform.openai.com/docs/models/o3-mini",
        },
    ),
    ModelSpec(
        model_id="gpt-4-turbo",
        name="GPT-4 Turbo",
        parameter_count_b=0.0,
        context_length=128000,
        supported_engines=("cloud",),
        provider="openai",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 10.00,
            "pricing_output": 30.00,
            "url": "https://platform.openai.com/docs/models/gpt-4-turbo",
        },
    ),
    # -----------------------------------------------------------------------
    # Cloud models — OpenAI Codex (ChatGPT Plus/Pro subscription)
    # -----------------------------------------------------------------------
    ModelSpec(
        model_id="codex/gpt-4o",
        name="GPT-4o (Codex)",
        parameter_count_b=0.0,
        context_length=128000,
        supported_engines=("cloud",),
        provider="openai-codex",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "auth": "OPENAI_CODEX_API_KEY",
            "pricing_input": 0.0,
            "pricing_output": 0.0,
            "url": "https://platform.openai.com/docs/models/gpt-4o",
        },
    ),
    ModelSpec(
        model_id="codex/gpt-4o-mini",
        name="GPT-4o Mini (Codex)",
        parameter_count_b=0.0,
        context_length=128000,
        supported_engines=("cloud",),
        provider="openai-codex",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "auth": "OPENAI_CODEX_API_KEY",
            "pricing_input": 0.0,
            "pricing_output": 0.0,
            "url": "https://platform.openai.com/docs/models/gpt-4o-mini",
        },
    ),
    ModelSpec(
        model_id="codex/o3-mini",
        name="o3-mini (Codex)",
        parameter_count_b=0.0,
        context_length=200000,
        supported_engines=("cloud",),
        provider="openai-codex",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "auth": "OPENAI_CODEX_API_KEY",
            "pricing_input": 0.0,
            "pricing_output": 0.0,
            "url": "https://platform.openai.com/docs/models",
        },
    ),
    # -----------------------------------------------------------------------
    # Cloud models — Anthropic
    # -----------------------------------------------------------------------
    ModelSpec(
        model_id="claude-3-7-sonnet",
        name="Claude 3.7 Sonnet",
        parameter_count_b=0.0,
        context_length=200000,
        supported_engines=("cloud",),
        provider="anthropic",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 3.00,
            "pricing_output": 15.00,
            "url": "https://docs.anthropic.com/en/docs/about-claude/models",
        },
    ),
    ModelSpec(
        model_id="claude-3-5-sonnet",
        name="Claude 3.5 Sonnet",
        parameter_count_b=0.0,
        context_length=200000,
        supported_engines=("cloud",),
        provider="anthropic",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 3.00,
            "pricing_output": 15.00,
            "url": "https://docs.anthropic.com/en/docs/about-claude/models",
        },
    ),
    ModelSpec(
        model_id="claude-3-5-haiku",
        name="Claude 3.5 Haiku",
        parameter_count_b=0.0,
        context_length=200000,
        supported_engines=("cloud",),
        provider="anthropic",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 0.80,
            "pricing_output": 4.00,
            "url": "https://docs.anthropic.com/en/docs/about-claude/models",
        },
    ),
    ModelSpec(
        model_id="claude-3-opus",
        name="Claude 3 Opus",
        parameter_count_b=0.0,
        context_length=200000,
        supported_engines=("cloud",),
        provider="anthropic",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 15.00,
            "pricing_output": 75.00,
            "url": "https://docs.anthropic.com/en/docs/about-claude/models",
        },
    ),
    # -----------------------------------------------------------------------
    # Cloud models — MiniMax
    # -----------------------------------------------------------------------
    ModelSpec(
        model_id="MiniMax-M3",
        name="MiniMax M3",
        parameter_count_b=0.0,
        context_length=1_000_000,
        supported_engines=("cloud",),
        provider="minimax",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 0.30,
            "pricing_output": 1.20,
            "pricing_long_context_input": 0.60,
            "pricing_long_context_output": 2.40,
            "pricing_long_context_threshold": 512_000,
            "url": "https://platform.minimax.io/docs/api-reference/api-overview",
        },
    ),
    ModelSpec(
        model_id="MiniMax-M2.7",
        name="MiniMax M2.7",
        parameter_count_b=0.0,
        context_length=204_800,
        supported_engines=("cloud",),
        provider="minimax",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 0.30,
            "pricing_output": 1.20,
            "url": "https://platform.minimax.io/docs/api-reference/api-overview",
        },
    ),
    ModelSpec(
        model_id="MiniMax-M2.7-highspeed",
        name="MiniMax M2.7 Highspeed",
        parameter_count_b=0.0,
        context_length=204_800,
        supported_engines=("cloud",),
        provider="minimax",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 0.60,
            "pricing_output": 2.40,
            "url": "https://platform.minimax.io/docs/api-reference/api-overview",
        },
    ),
    ModelSpec(
        model_id="MiniMax-M2.5",
        name="MiniMax M2.5",
        parameter_count_b=0.0,
        context_length=204_800,
        supported_engines=("cloud",),
        provider="minimax",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 0.30,
            "pricing_output": 1.20,
            "url": "https://platform.minimax.io/docs/api-reference/api-overview",
        },
    ),
    ModelSpec(
        model_id="MiniMax-M2.5-highspeed",
        name="MiniMax M2.5 Highspeed",
        parameter_count_b=0.0,
        context_length=204_800,
        supported_engines=("cloud",),
        provider="minimax",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 0.60,
            "pricing_output": 2.40,
            "url": "https://platform.minimax.io/docs/api-reference/api-overview",
        },
    ),
    # -----------------------------------------------------------------------
    # Cloud models — Google
    # -----------------------------------------------------------------------
    ModelSpec(
        model_id="gemini-2.5-pro",
        name="Gemini 2.5 Pro",
        parameter_count_b=0.0,
        context_length=1000000,
        supported_engines=("cloud",),
        provider="google",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 1.25,
            "pricing_output": 10.00,
            "url": "https://ai.google.dev/gemini-api/docs/models#gemini-2.5-pro",
        },
    ),
    ModelSpec(
        model_id="gemini-2.5-flash",
        name="Gemini 2.5 Flash",
        parameter_count_b=0.0,
        context_length=1000000,
        supported_engines=("cloud",),
        provider="google",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 0.30,
            "pricing_output": 2.50,
            "url": "https://ai.google.dev/gemini-api/docs/models#gemini-2.5-flash",
        },
    ),
    ModelSpec(
        model_id="gemini-2.0-flash",
        name="Gemini 2.0 Flash",
        parameter_count_b=0.0,
        context_length=1048576,
        supported_engines=("cloud",),
        provider="google",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 0.10,
            "pricing_output": 0.40,
            "url": "https://ai.google.dev/gemini-api/docs/models#gemini-2.0-flash",
        },
    ),
    ModelSpec(
        model_id="gemini-1.5-pro",
        name="Gemini 1.5 Pro",
        parameter_count_b=0.0,
        context_length=2097152,
        supported_engines=("cloud",),
        provider="google",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 1.25,
            "pricing_output": 5.00,
            "url": "https://ai.google.dev/gemini-api/docs/models#gemini-1.5-pro",
        },
    ),
    ModelSpec(
        model_id="gemini-1.5-flash",
        name="Gemini 1.5 Flash",
        parameter_count_b=0.0,
        context_length=1048576,
        supported_engines=("cloud",),
        provider="google",
        requires_api_key=True,
        metadata={
            "architecture": "proprietary",
            "pricing_input": 0.075,
            "pricing_output": 0.30,
            "url": "https://ai.google.dev/gemini-api/docs/models#gemini-1.5-flash",
        },
    ),
    # -----------------------------------------------------------------------
    # Cloud models — DeepSeek
    # -----------------------------------------------------------------------
    ModelSpec(
        model_id="deepseek-chat",
        name="DeepSeek V3 (Chat)",
        parameter_count_b=0.0,
        context_length=64000,
        supported_engines=("cloud",),
        provider="deepseek",
        requires_api_key=True,
        metadata={
            "architecture": "moe",
            "pricing_input": 0.14,
            "pricing_output": 0.28,
            "url": "https://api-docs.deepseek.com",
        },
    ),
    ModelSpec(
        model_id="deepseek-reasoner",
        name="DeepSeek R1 (Reasoner)",
        parameter_count_b=0.0,
        context_length=64000,
        supported_engines=("cloud",),
        provider="deepseek",
        requires_api_key=True,
        metadata={
            "architecture": "moe",
            "pricing_input": 0.55,
            "pricing_output": 2.19,
            "url": "https://api-docs.deepseek.com",
        },
    ),
]


def resolve_model_id_for_engine(model_id: str, engine_id: str) -> str:
    """Resolve a catalog model ID when an engine has a distinct runtime ID."""
    if engine_id != "mlx":
        return model_id

    for spec in BUILTIN_MODELS:
        if spec.model_id == model_id and engine_id in spec.supported_engines:
            mlx_repo = spec.metadata.get("mlx_repo")
            if isinstance(mlx_repo, str) and mlx_repo:
                return mlx_repo
            break
    return model_id


def register_builtin_models() -> None:
    """Populate ``ModelRegistry`` with well-known models."""
    for spec in BUILTIN_MODELS:
        if not ModelRegistry.contains(spec.model_id):
            ModelRegistry.register_value(spec.model_id, spec)


def merge_discovered_models(engine_key: str, model_ids: List[str]) -> None:
    """Create minimal ``ModelSpec`` entries for models not already in the registry."""
    for model_id in model_ids:
        if not ModelRegistry.contains(model_id):
            spec = ModelSpec(
                model_id=model_id,
                name=model_id,
                parameter_count_b=0.0,
                context_length=0,
                supported_engines=(engine_key,),
            )
            ModelRegistry.register_value(model_id, spec)


__all__ = [
    "BUILTIN_MODELS",
    "merge_discovered_models",
    "register_builtin_models",
    "resolve_model_id_for_engine",
]
