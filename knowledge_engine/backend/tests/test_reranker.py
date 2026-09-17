"""Phase 5 reranker 服务测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from app.services.reranker import (
    DeterministicRerankerModel,
    Qwen3RerankerModel,
    RerankerService,
    RerankerServiceError,
    get_reranker_service,
)


def test_reranker_service_loads_from_local_directory_with_fallback(tmp_path: Path) -> None:
    model_dir = tmp_path / "reranker-model"
    model_dir.mkdir()

    service = RerankerService.from_local_model(
        model_path=model_dir,
        batch_size=4,
        allow_fallback=True,
    )

    assert isinstance(service.model, DeterministicRerankerModel)
    assert service.batch_size == 4


def test_reranker_service_returns_scores_for_each_candidate() -> None:
    service = RerankerService(DeterministicRerankerModel(), batch_size=4)

    results = service.rerank(
        "什么是纵深防御",
        ["纵深防御是一种分层安全策略", "日志审计可以帮助溯源"],
    )

    assert len(results) == 2
    assert results[0].text == "纵深防御是一种分层安全策略"
    assert all(isinstance(item.score, float) for item in results)


def test_qwen3_reranker_uses_official_prompt_batches_and_yes_probability() -> None:

    class Batch(dict):
        def to(self, device):
            assert str(device) == "cpu"
            return self

    class FakeTokenizer:
        padding_side = "right"
        pad_token = None
        eos_token = "<eos>"
        model_max_length = 32

        def __init__(self) -> None:
            self.seen: list[list[str]] = []

        def convert_tokens_to_ids(self, token: str) -> int:
            return {"no": 3, "yes": 7}[token]

        def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
            assert add_special_tokens is False
            if text in {"no", "yes"}:
                return [{"no": 3, "yes": 7}[text]]
            if text.startswith("<|im_start|>system"):
                return [10, 11]
            return [12, 13]

        def __call__(self, texts, **kwargs):
            assert kwargs == {
                "padding": False,
                "truncation": "longest_first",
                "return_attention_mask": False,
                "max_length": 28,
            }
            self.seen.append(list(texts))
            return {"input_ids": [[20, index] for index, _ in enumerate(texts)]}

        def pad(self, inputs, **kwargs):
            assert kwargs == {"padding": True, "return_tensors": "pt"}
            rows = inputs["input_ids"]
            return Batch(
                input_ids=torch.tensor(rows),
                attention_mask=torch.ones((len(rows), len(rows[0])), dtype=torch.long),
            )

    class FakeModel:
        device = torch.device("cpu")

        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def eval(self):
            return self

        def __call__(self, **inputs):
            batch = inputs["input_ids"].shape[0]
            self.batch_sizes.append(batch)
            logits = torch.zeros((batch, inputs["input_ids"].shape[1], 8))
            for index in range(batch):
                logits[index, -1, 3] = 2.0 - index
                logits[index, -1, 7] = float(index)
            return SimpleNamespace(logits=logits)

    tokenizer = FakeTokenizer()
    model = FakeModel()
    service = RerankerService(
        Qwen3RerankerModel(tokenizer, model, device=torch.device("cpu"), max_length=32),
        batch_size=2,
    )

    results = service.rerank("什么是个人信息", ["定义条款", "第四十条", "其他条款"])

    assert model.batch_sizes == [2, 1]
    assert tokenizer.padding_side == "left"
    assert tokenizer.pad_token == "<eos>"
    assert "<Instruct>: Given a web search query" in tokenizer.seen[0][0]
    assert "<Query>: 什么是个人信息" in tokenizer.seen[0][0]
    assert "<Document>: 定义条款" in tokenizer.seen[0][0]
    assert results[1].score > results[0].score
    assert 0.0 < results[2].score < 1.0


def test_qwen3_reranker_rejects_invalid_yes_no_tokens() -> None:

    class BadTokenizer:
        eos_token = "<eos>"
        pad_token = None
        model_max_length = 32

        def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
            return [0]

    with pytest.raises(RerankerServiceError, match="yes/no"):
        Qwen3RerankerModel(BadTokenizer(), object(), device=torch.device("cpu"), max_length=32)


def test_qwen3_reranker_requires_yes_and_no_to_each_be_one_token() -> None:
    class SplitTokenizer:
        eos_token = "<eos>"
        pad_token = None
        unk_token_id = 99

        def convert_tokens_to_ids(self, token: str) -> int:
            return {"no": 3, "yes": 7}[token]

        def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
            if text == "yes":
                return [7, 8]
            if text == "no":
                return [3]
            return [10]

    with pytest.raises(RerankerServiceError, match="单 token"):
        Qwen3RerankerModel(SplitTokenizer(), object(), device=torch.device("cpu"), max_length=32)


def test_qwen3_reranker_wraps_inference_errors() -> None:
    class Batch(dict):
        def to(self, device):
            return self

    class Tokenizer:
        eos_token = "<eos>"
        pad_token = None
        unk_token_id = 99

        def convert_tokens_to_ids(self, token: str) -> int:
            return {"no": 3, "yes": 7}[token]

        def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
            if text in {"yes", "no"}:
                return [{"no": 3, "yes": 7}[text]]
            return [10]

        def __call__(self, texts, **kwargs):
            return {"input_ids": [[20] for _ in texts]}

        def pad(self, inputs, **kwargs):
            return Batch(input_ids=torch.tensor(inputs["input_ids"]))

    class BrokenModel:
        def eval(self):
            return self

        def __call__(self, **inputs):
            raise RuntimeError("device mismatch")

    service = RerankerService(
        Qwen3RerankerModel(Tokenizer(), BrokenModel(), device=torch.device("cpu"), max_length=32),
        batch_size=2,
    )

    with pytest.raises(RerankerServiceError, match="推理失败") as exc_info:
        service.rerank("查询", ["候选"])
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_reranker_service_rejects_wrong_score_count() -> None:
    class WrongCountModel:
        def predict(self, sentences, *, batch_size: int, show_progress_bar: bool):
            return []

    service = RerankerService(WrongCountModel(), batch_size=2)

    with pytest.raises(RerankerServiceError, match="数量不匹配"):
        service.rerank("查询", ["候选"])


def test_reranker_service_validates_batch_size() -> None:
    with pytest.raises(RerankerServiceError, match="batch_size"):
        RerankerService(DeterministicRerankerModel(), batch_size=0)


def test_fallback_cache_does_not_mask_strict_model_loading(monkeypatch, tmp_path: Path) -> None:
    import app.services.reranker as reranker_module

    missing_dir = tmp_path / "missing-reranker-model"
    monkeypatch.setattr(reranker_module, "get_settings", lambda: SimpleNamespace(
        reranker_model_path=str(missing_dir), reranker_batch_size=2
    ))
    get_reranker_service.cache_clear()
    try:
        fallback = get_reranker_service(allow_fallback=True)
        assert isinstance(fallback.model, DeterministicRerankerModel)
        with pytest.raises(RerankerServiceError, match="目录不存在"):
            get_reranker_service(allow_fallback=False)
    finally:
        get_reranker_service.cache_clear()


def test_reranker_service_loads_cpu_model_with_float32(monkeypatch, tmp_path: Path) -> None:
    import app.services.reranker as reranker_module

    model_dir = tmp_path / "reranker-model"
    model_dir.mkdir()
    tokenizer = SimpleNamespace(model_max_length=8192)
    loaded: dict[str, object] = {}

    class LoadedModel:
        def to(self, device):
            loaded["device"] = device
            return self

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(
        reranker_module.AutoTokenizer,
        "from_pretrained",
        lambda *args, **kwargs: tokenizer,
    )

    def load_model(*args, **kwargs):
        loaded["kwargs"] = kwargs
        return LoadedModel()

    monkeypatch.setattr(reranker_module.AutoModelForCausalLM, "from_pretrained", load_model)
    monkeypatch.setattr(
        reranker_module,
        "Qwen3RerankerModel",
        lambda tokenizer, model, *, device, max_length: DeterministicRerankerModel(),
    )

    RerankerService.from_local_model(model_path=model_dir, batch_size=2)

    dtype_key = "dtype" if int(reranker_module.transformers.__version__.split(".", 1)[0]) >= 5 else "torch_dtype"
    assert loaded["kwargs"][dtype_key] == torch.float32
    assert str(loaded["device"]) == "cpu"


def test_reranker_service_loads_cuda_model_with_float16(monkeypatch, tmp_path: Path) -> None:
    import app.services.reranker as reranker_module

    model_dir = tmp_path / "reranker-model"
    model_dir.mkdir()
    tokenizer = SimpleNamespace(model_max_length=8192)
    loaded: dict[str, object] = {}

    class LoadedModel:
        def to(self, device):
            loaded["device"] = device
            return self

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(
        reranker_module.AutoTokenizer,
        "from_pretrained",
        lambda *args, **kwargs: tokenizer,
    )

    def load_model(*args, **kwargs):
        loaded["kwargs"] = kwargs
        return LoadedModel()

    monkeypatch.setattr(reranker_module.AutoModelForCausalLM, "from_pretrained", load_model)
    monkeypatch.setattr(
        reranker_module,
        "Qwen3RerankerModel",
        lambda tokenizer, model, *, device, max_length: DeterministicRerankerModel(),
    )

    RerankerService.from_local_model(model_path=model_dir, batch_size=2)

    dtype_key = "dtype" if int(reranker_module.transformers.__version__.split(".", 1)[0]) >= 5 else "torch_dtype"
    assert loaded["kwargs"][dtype_key] == torch.float16
    assert str(loaded["device"]) == "cuda"


def test_reranker_service_raises_when_model_path_missing_without_fallback(tmp_path: Path) -> None:
    missing_dir = tmp_path / "missing-reranker-model"

    with pytest.raises(RerankerServiceError):
        RerankerService.from_local_model(
            model_path=missing_dir,
            batch_size=4,
            allow_fallback=False,
        )
