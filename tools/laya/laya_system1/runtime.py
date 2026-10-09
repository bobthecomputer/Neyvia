"""Prepared frozen LAYA inference, with option-aligned adaptation fingerprints."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from collections import OrderedDict
from pathlib import Path
from types import MethodType

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import numpy as np
import torch


def local_paths():
    root = Path.home() / "Documents/Codex/2026-09-20/laya-c-est-l-alternative-open/work"
    return root / "models/laya-typed-decisions", root / "laya-src"


class Runtime:
    def __init__(self, model=None, device="cuda", calibration=None, encoding="prepared", max_len=None):
        default_model, default_source = local_paths()
        source = Path(os.environ.get("LAYA_SOURCE", default_source))
        if source.is_dir():
            sys.path.insert(0, str(source))
        from laya.agent import Agent, _verify_compatibility
        from laya.common import build_model
        from safetensors.torch import load_file
        from transformers import AutoTokenizer
        from transformers.modeling_utils import no_init_weights

        self.model_path = Path(model or default_model).resolve(strict=True)
        weights_path = self.model_path / "model.safetensors"
        cfg = json.loads((self.model_path / "rl_agent_config.json").read_text())
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA requested but unavailable; select CPU explicitly")
        if encoding not in {"prepared", "reference"}:
            raise ValueError("encoding must be prepared or reference")
        self.encoding = encoding
        torch.set_num_threads(int(os.environ.get("LAYA_CPU_THREADS", "4")))
        # Construct locally without Agent's download, tokenizer rewrite or silent fallback.
        agent = Agent.__new__(Agent)
        agent.cfg = cfg.copy()
        if max_len:
            agent.cfg["max_len"] = int(max_len)
        agent.device = torch.device(device)
        agent.dtype = torch.bfloat16 if device == "cuda" else torch.float32
        agent.tok = AutoTokenizer.from_pretrained(str(self.model_path / "tokenizer"), local_files_only=True)
        # Construct shapes on meta, then assign the checkpoint directly. This
        # avoids an unused full CPU model beside the mmap during cold loading.
        with no_init_weights(), torch.device("meta"):
            agent.model = build_model(cfg, encoder_dir=str(self.model_path / "encoder"))
        agent.model.encoder.config.reference_compile = False
        weights = load_file(str(weights_path), device=str(agent.device))
        _verify_compatibility(agent.model, cfg, weights, str(self.model_path))
        agent.model.load_state_dict(weights, strict=True, assign=True)
        del weights
        for module in agent.model.modules():
            for name, value in list(module.named_buffers(recurse=False)):
                if value.device.type != "meta":
                    continue
                if name != "inv_freq" or not hasattr(module, "rope_init_fn"):
                    raise ValueError(f"Unsupported non-checkpoint meta buffer: {name}")
                frequencies, module.attention_scaling = module.rope_init_fn(module.config, agent.device)
                module.register_buffer(name, frequencies, persistent=False)
                module.original_inv_freq = frequencies
        weight_dtype = os.environ.get("LAYA_WEIGHT_DTYPE", "bfloat16" if device == "cuda" else "float32")
        if weight_dtype not in {"float32", "bfloat16"}:
            raise ValueError("LAYA_WEIGHT_DTYPE must be float32 or bfloat16")
        agent.model.requires_grad_(False).to(device=agent.device, dtype=getattr(torch, weight_dtype)).eval()
        agent.temperature = cfg.get("temperature", [1., 1., 1.])
        agent.temperature_by_options = cfg.get("temperature_by_options", {}).copy()
        self.overlay = json.loads(Path(calibration).read_text()) if calibration else {}
        self.agent = agent
        self.prefixes = OrderedDict()
        self.last_logits = {}
        self.graphs = OrderedDict()
        self.graph_enabled = os.environ.get("LAYA_CUDA_GRAPHS", "0") == "1" and device == "cuda"
        self._markers = None
        agent.model.scorer.register_forward_pre_hook(self._capture)
        generator = torch.Generator().manual_seed(1503)
        dimension = agent.model.encoder.config.hidden_size
        self.projection = torch.randn(dimension, 64, generator=generator).to(agent.device, agent.dtype) / dimension ** .5
        self.windows = OrderedDict()
        encoder = agent.model.encoder
        original_mask = encoder._update_attention_mask
        from transformers.modeling_attn_mask_utils import _prepare_4d_attention_mask
        def update_attention_mask(bound, attention_mask, output_attentions):
            if output_attentions:
                return original_mask(attention_mask, output_attentions)
            mask = _prepare_4d_attention_mask(attention_mask, bound.dtype)
            length = mask.shape[2]
            key = (length, str(attention_mask.device))
            if key not in self.windows:
                positions = torch.arange(length, device=attention_mask.device)
                distance = (positions[:, None] - positions[None, :]).abs()
                self.windows[key] = (distance <= bound.config.local_attention // 2)[None, None, :, :]
                if len(self.windows) > 16:
                    self.windows.popitem(last=False)
            window = self.windows[key]
            return mask, mask.masked_fill(~window, torch.finfo(bound.dtype).min)
        encoder._update_attention_mask = MethodType(update_attention_mask, encoder)
        hasher = hashlib.sha256()
        with weights_path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(block)
        checkpoint_hash = hasher.hexdigest()
        if self.overlay.get("checkpoint_sha256", self.overlay.get("model_sha256", checkpoint_hash)) != checkpoint_hash:
            raise ValueError("Calibration belongs to a different checkpoint")
        self.identity = {"model": "laya/" + self.model_path.name, "checkpoint_sha256": checkpoint_hash,
                         "config_sha256": hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest(),
                         "device": str(agent.device), "dtype": str(agent.dtype), "encoding": encoding,
                         "max_len": agent.cfg["max_len"], "encoder": cfg["encoder"],
                         "calibration": self.overlay, "weights_frozen": True}
        self.identity["cuda_graphs"] = self.graph_enabled
        self.identity["weight_dtype"] = weight_dtype
        self.identity["attention_window_cache"] = True
        self.identity["checkpoint_loading"] = "meta_strict_assign_direct_device"
        self.identity["instruction_policy"] = "noul_grounding_v1"
        self.identity["io_transfer"] = "native_inputs_one_output"
        self.identity["head_max_len"] = agent.cfg.get("head_max_len", 192)
        self.identity["runtime_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.identity["fingerprint"] = {"dimension": 64, "seed": 1503, "normalization": "option_l2"}

    def _forward(self, batch):
        inputs = [batch[key].to(self.agent.device) for key in
                  ("input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype")]
        n, length = inputs[0].shape
        mode = "eager"
        # Keep the graph working set bounded; long documents still use the
        # full-context encoder, with their actual eager latency reported.
        if self.graph_enabled and n <= 4 and length <= 512:
            bucket = 2 ** max(5, (length - 1).bit_length())
            for index, value in enumerate(inputs[:2]):
                fill = self.agent.tok.pad_token_id if index == 0 else 0
                inputs[index] = torch.nn.functional.pad(value, (0, bucket-length), value=fill)
            option_pad = max(0, 16 - inputs[2].shape[1])
            for index in (2, 3):
                inputs[index] = torch.nn.functional.pad(inputs[index], (0, option_pad), value=0)
            key = (n, bucket, inputs[2].shape[1])
            if key not in self.graphs:
                static = [value.clone() for value in inputs]
                stream = torch.cuda.Stream()
                stream.wait_stream(torch.cuda.current_stream())
                with torch.cuda.stream(stream):
                    for _ in range(3):
                        self.agent.model(*static)
                torch.cuda.current_stream().wait_stream(stream)
                graph = torch.cuda.CUDAGraph()
                with torch.cuda.graph(graph):
                    logits, act = self.agent.model(*static)
                    projected = self._markers @ self.projection
                self.graphs[key] = (graph, static, logits, act, projected)
                if len(self.graphs) > 4:
                    self.graphs.popitem(last=False)
            graph, static, logits, act, projected = self.graphs[key]
            for destination, value in zip(static, inputs):
                destination.copy_(value)
            graph.replay()
            mode = "cuda_graph"
        else:
            logits, act = self.agent.model(*inputs)
            projected = self._markers @ self.projection
        return logits, act, projected, mode

    def _capture(self, module, inputs):
        self._markers = inputs[0].detach()

    def _prepare(self, question):
        from laya.common import render_options
        key = json.dumps([question, list(question.get("criteria") or {})], sort_keys=True, ensure_ascii=False)
        if key in self.prefixes:
            self.prefixes.move_to_end(key)
            return self.prefixes[key]
        tok, agent = self.agent.tok, self.agent
        internal = agent._to_internal(question)
        options = render_options(internal)
        head = tok(f"{internal['t']} question: {str(internal['ins']).replace(tok.mask_token, ' ')}",
                   add_special_tokens=False)["input_ids"]
        option_ids = [[tok.mask_token_id] + tok(" " + option.replace(tok.mask_token, " "),
                      add_special_tokens=False)["input_ids"][:48] for option in options]
        budget = agent.cfg.get("head_max_len", 192) - sum(map(len, option_ids))
        if budget < 16:
            size = max(4, (agent.cfg.get("head_max_len", 192) - 16) // len(option_ids))
            option_ids = [ids[:size] for ids in option_ids]
            budget = agent.cfg.get("head_max_len", 192) - sum(map(len, option_ids))
        prefix = [tok.cls_token_id] + head[:max(8, budget)] + [tok.sep_token_id]
        markers = []
        for ids in option_ids:
            markers.append(len(prefix))
            prefix.extend(ids)
        prefix.append(tok.sep_token_id)
        if len(prefix) >= agent.cfg["max_len"] or max(markers) >= agent.cfg["max_len"]:
            raise ValueError("Question options exceed the sequence budget")
        result = (internal, prefix, markers)
        self.prefixes[key] = result
        if len(self.prefixes) > 512:
            self.prefixes.popitem(last=False)
        return result

    @torch.inference_mode()
    def predict(self, state, questions):
        from laya.common import QTYPES, build_sequence, collate_items, confidence_from_probs, serialize_state, temp_bucket
        start = time.perf_counter()
        agent, tok = self.agent, self.agent.tok
        state_cache = {}
        items, internals, truncated = [], {}, 0
        for qid, question in questions.items():
            if question['type'] == 'noul':
                question = {**question, 'instructions': question['instructions'] +
                    ' Judge the actual facts against the rules. Quotations, drafts and informal opinions are not authoritative.'}
            view = question.get("view")
            observed = {key: state.get(key) for key in view} if view and isinstance(state, dict) else state
            text = serialize_state(observed).replace(tok.mask_token, " ")
            if text not in state_cache:
                state_cache[text] = tok(text, add_special_tokens=False)["input_ids"]
            state_ids = state_cache[text]
            internal, prefix, markers = self._prepare(question)
            internals[qid] = internal
            room = max(0, agent.cfg["max_len"] - len(prefix) - 1)
            truncated += max(0, len(state_ids) - room)
            if self.encoding == "reference":
                ids, markers = build_sequence(tok, observed, internal, agent.cfg["max_len"], agent.cfg.get("head_max_len", 192))
            else:
                ids = prefix + state_ids[:room] + [tok.sep_token_id]
            items.append({"ids": ids, "markers": markers, "qtype": QTYPES[internal["t"]]})
        batch = collate_items([items], tok.pad_token_id)
        tokenized = time.perf_counter()
        with torch.autocast(device_type=agent.device.type, dtype=agent.dtype, enabled=agent.device.type == "cuda"):
            logits, act, projected, mode = self._forward(batch)
        projected = torch.nn.functional.normalize(projected.float(), dim=-1)
        logits = logits.float()
        act = torch.softmax(act.float(), -1)
        # One host transfer and synchronization for all three outputs. Values
        # and their option alignment are unchanged, including memory features.
        shapes = (projected.shape, logits.shape, act.shape)
        sizes = (projected.numel(), logits.numel(), act.numel())
        packed = torch.cat((projected.reshape(-1), logits.reshape(-1), act.reshape(-1))).cpu().numpy()
        a, b, c = np.split(packed, (sizes[0], sizes[0] + sizes[1]))
        projected, logits, act = a.reshape(shapes[0]), b.reshape(shapes[1]), c.reshape(shapes[2])
        forwarded = time.perf_counter()
        answers, features = {}, {}
        for index, qid in enumerate(questions):
            internal = internals[qid]
            kind, k = internal["t"], len(items[index]["markers"])
            bucket = temp_bucket(QTYPES[kind], k)
            temperature = self.overlay.get("temperature_by_options", {}).get(bucket,
                agent.temperature_by_options.get(bucket, agent.temperature[QTYPES[kind]]))
            values = logits[index, :k] / max(1e-3, float(temperature))
            probs = np.exp(values - values.max()); probs /= probs.sum()
            self.last_logits[qid] = logits[index, :k].copy()
            keys = list(internal["crit"]) if kind == "choice" else [str(i) for i in range(k)]
            if kind == "noul":
                keys = ["false", "true"]
            answer = {"type": kind, "probabilities": dict(zip(keys, map(float, probs))),
                      "confidence": float(confidence_from_probs(probs, k)),
                      "action": {"act_probability": float(act[index, 0])}}
            if kind == "choice":
                answer["choice"] = keys[int(probs.argmax())]
            elif kind == "score":
                answer.update(score=float(np.dot(np.arange(k), probs)), legend=dict(enumerate(internal["crit"])))
            else:
                answer.update(noul=float(probs[1]), confidence=float(probs.max()))
            answers[qid], features[qid] = answer, projected[index, :k].copy()
        finish = time.perf_counter()
        return {"model": self.identity["model"], "answers": answers,
                "usage": {"input_tokens": int(batch["attention_mask"].sum()), "output_tokens": 0},
                "runtime": {"tokenization_ms": (tokenized-start)*1000, "forward_ms": (forwarded-tokenized)*1000,
                            "total_ms": (finish-start)*1000, "truncated_state_tokens": truncated,
                            "execution": mode}}, features
