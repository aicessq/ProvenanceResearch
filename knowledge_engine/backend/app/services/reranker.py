"""本地 Reranker 服务（Qwen3 Reranker 进程内加载）。

Phase 5 先完成：
- 本地模型目录加载
- query + candidates 的统一调用接口
- 返回与输入候选一一对应的分数列表

注意：
- 本阶段只做真实服务封装，不接入查询链路；
- 为便于仓库在无模型权重环境下保持可测试，可显式允许 deterministic fallback；
- 默认仍要求优先加载本地真实模型。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import torch
from app.config import get_settings

try:  # pragma: no cover - 依赖安装与否取决于运行环境
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer
except ImportError:  # pragma: no cover
    transformers = None  # type: ignore[assignment]
    AutoModelForCausalLM = None  # type: ignore[assignment]
    AutoTokenizer = None  # type: ignore[assignment]


class RerankerModelProtocol(Protocol):
    """统一约束底层 reranker 模型的最小能力。"""

    def predict(self, sentences: list[tuple[str, str]], *, batch_size: int, show_progress_bar: bool) -> object: ...


class RerankerServiceError(RuntimeError):
    """Reranker 服务异常。"""


@dataclass(slots=True)
class RerankResult:
    """单条 rerank 结果。"""

    text: str
    score: float


class DeterministicRerankerModel:
    """测试 / 无模型权重场景下的确定性回退 reranker。"""

    def predict(self, sentences: list[tuple[str, str]], *, batch_size: int, show_progress_bar: bool) -> list[float]:
        del batch_size, show_progress_bar
        return [self._score_pair(query, candidate) for query, candidate in sentences]

    @staticmethod
    def _score_pair(query: str, candidate: str) -> float:
        digest = hashlib.sha256(f"{query}\n{candidate}".encode("utf-8")).digest()
        raw_value = int.from_bytes(digest[:8], byteorder="big", signed=False)
        return raw_value / 2**64


class Qwen3RerankerModel:
    """按 Qwen3 官方 yes/no next-token logits 方式打分。"""

    _INSTRUCTION = "Given a web search query, retrieve relevant passages that answer the query"
    _PREFIX = (
        '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the '
        'Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
    )
    _SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"

    def __init__(self, tokenizer, model, *, device: torch.device, max_length: int) -> None:
        if max_length <= 0:
            raise RerankerServiceError("reranker max_length 必须为正数")
        self.tokenizer = tokenizer
        self.device = device
        self.max_length = max_length
        self.tokenizer.padding_side = "left"
        if self.tokenizer.pad_token is None:
            if self.tokenizer.eos_token is None:
                raise RerankerServiceError("reranker tokenizer 缺少 pad/eos token")
            self.tokenizer.pad_token = self.tokenizer.eos_token
        no_tokens = self.tokenizer.encode("no", add_special_tokens=False)
        yes_tokens = self.tokenizer.encode("yes", add_special_tokens=False)
        if len(no_tokens) != 1 or len(yes_tokens) != 1:
            raise RerankerServiceError("reranker tokenizer 的 yes/no 必须各自编码为单 token")
        self.no_token_id = no_tokens[0]
        self.yes_token_id = yes_tokens[0]
        unk_token_id = getattr(self.tokenizer, "unk_token_id", None)
        if (
            self.no_token_id == self.yes_token_id
            or min(self.no_token_id, self.yes_token_id) < 0
            or self.no_token_id == unk_token_id
            or self.yes_token_id == unk_token_id
        ):
            raise RerankerServiceError("reranker tokenizer 的 yes/no token ID 无效")
        self.model = model.eval()
        self.prefix_tokens = self.tokenizer.encode(self._PREFIX, add_special_tokens=False)
        self.suffix_tokens = self.tokenizer.encode(self._SUFFIX, add_special_tokens=False)
        if len(self.prefix_tokens) + len(self.suffix_tokens) >= self.max_length:
            raise RerankerServiceError("reranker max_length 无法容纳官方 prompt")

    def predict(self, sentences: list[tuple[str, str]], *, batch_size: int, show_progress_bar: bool) -> list[float]:
        del show_progress_bar
        if batch_size <= 0:
            raise RerankerServiceError("reranker batch_size 必须为正数")
        scores: list[float] = []
        for start in range(0, len(sentences), batch_size):
            pairs = sentences[start : start + batch_size]
            texts = [
                f"<Instruct>: {self._INSTRUCTION}\n<Query>: {query}\n<Document>: {document}"
                for query, document in pairs
            ]
            inputs = self.tokenizer(
                texts,
                padding=False,
                truncation="longest_first",
                return_attention_mask=False,
                max_length=self.max_length - len(self.prefix_tokens) - len(self.suffix_tokens),
            )
            inputs["input_ids"] = [
                self.prefix_tokens + token_ids + self.suffix_tokens for token_ids in inputs["input_ids"]
            ]
            inputs = self.tokenizer.pad(
                inputs,
                padding=True,
                return_tensors="pt",
            ).to(self.device)
            try:
                with torch.inference_mode():
                    final_logits = self.model(**inputs).logits[:, -1, :]
                    binary_logits = torch.stack(
                        [final_logits[:, self.no_token_id], final_logits[:, self.yes_token_id]], dim=1
                    )
                    scores.extend(torch.softmax(binary_logits, dim=1)[:, 1].float().cpu().tolist())
            except Exception as exc:  # noqa: BLE001 - 统一转换底层 tokenizer/model/device 异常
                raise RerankerServiceError("reranker 模型推理失败") from exc
        return scores


class RerankerService:
    """本地 reranker 服务封装。"""

    def __init__(self, model: RerankerModelProtocol, *, batch_size: int) -> None:
        if batch_size <= 0:
            raise RerankerServiceError("reranker batch_size 必须为正数")
        self.model = model
        self.batch_size = batch_size

    @classmethod
    def from_local_model(
        cls,
        *,
        model_path: str | Path | None = None,
        batch_size: int | None = None,
        allow_fallback: bool = False,
    ) -> "RerankerService":
        """从本地目录加载 reranker 模型。"""
        settings = get_settings()
        resolved_path = Path(model_path or settings.reranker_model_path)
        resolved_batch_size = batch_size or settings.reranker_batch_size

        if AutoTokenizer is None or AutoModelForCausalLM is None:
            if allow_fallback:
                return cls(DeterministicRerankerModel(), batch_size=resolved_batch_size)
            raise RerankerServiceError("transformers 未安装，无法加载本地 reranker 模型")

        if not resolved_path.exists() or not resolved_path.is_dir():
            if allow_fallback:
                return cls(DeterministicRerankerModel(), batch_size=resolved_batch_size)
            raise RerankerServiceError(f"reranker 模型目录不存在: {resolved_path}")

        try:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            dtype = torch.float16 if device.type == "cuda" else torch.float32
            tokenizer = AutoTokenizer.from_pretrained(
                str(resolved_path), local_files_only=True, padding_side="left"
            )
            model_kwargs = {"local_files_only": True}
            dtype_key = "dtype" if int(transformers.__version__.split(".", 1)[0]) >= 5 else "torch_dtype"
            model_kwargs[dtype_key] = dtype
            model = AutoModelForCausalLM.from_pretrained(
                str(resolved_path), **model_kwargs
            ).to(device)
            configured_max_length = int(getattr(tokenizer, "model_max_length", 8192))
            max_length = min(configured_max_length, 8192)
            model = Qwen3RerankerModel(tokenizer, model, device=device, max_length=max_length)
        except Exception as exc:  # noqa: BLE001
            if allow_fallback:
                return cls(DeterministicRerankerModel(), batch_size=resolved_batch_size)
            raise RerankerServiceError(f"reranker 模型加载失败: {resolved_path}") from exc

        return cls(model, batch_size=resolved_batch_size)

    def rerank(self, query: str, candidates: list[str]) -> list[RerankResult]:
        """返回与输入候选等长的打分结果。"""
        if not query.strip():
            raise RerankerServiceError("rerank query 不能为空")
        if not candidates:
            return []
        if any(not candidate.strip() for candidate in candidates):
            raise RerankerServiceError("rerank candidates 中存在空文本")

        pairs = [(query, candidate) for candidate in candidates]
        try:
            raw_scores = self.model.predict(
                pairs,
                batch_size=self.batch_size,
                show_progress_bar=False,
            )
            scores = [float(score) for score in raw_scores]  # type: ignore[arg-type]
        except RerankerServiceError:
            raise
        except Exception as exc:  # noqa: BLE001 - 统一转换底层 tokenizer/model/device 异常
            raise RerankerServiceError("reranker 模型推理失败") from exc
        if len(scores) != len(candidates):
            raise RerankerServiceError(
                f"reranker 输出数量不匹配，期望 {len(candidates)}，实际 {len(scores)}"
            )
        return [RerankResult(text=text, score=score) for text, score in zip(candidates, scores, strict=True)]


@lru_cache
def get_reranker_service(*, allow_fallback: bool = False) -> RerankerService:
    """返回 reranker 服务单例。"""
    return RerankerService.from_local_model(allow_fallback=allow_fallback)
