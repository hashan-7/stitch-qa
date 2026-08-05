import gc
import os
import threading

import torch
from transformers import AutoConfig, AutoModelForCausalLM, AutoModelForSeq2SeqLM, AutoTokenizer


class ModelService:
    def __init__(self):
        self.primary_model = os.getenv("HF_MODEL", "Qwen/Qwen3-1.7B")
        self.fallback_model = os.getenv("HF_FALLBACK_MODEL", "google/flan-t5-large")
        self.enabled = os.getenv("LLM_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.local_files_only = os.getenv("HF_LOCAL_FILES_ONLY", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.max_input_tokens = int(os.getenv("MODEL_MAX_INPUT_TOKENS", "3072"))
        self.max_new_tokens = int(os.getenv("MODEL_MAX_NEW_TOKENS", "320"))
        self.torch_threads = max(1, int(os.getenv("TORCH_NUM_THREADS", "2")))
        self.dtype_name = os.getenv("MODEL_DTYPE", "float32").strip().lower()
        self.tokenizer = None
        self.model = None
        self.model_name = None
        self.is_encoder_decoder = False
        self.load_error = None
        self.load_lock = threading.Lock()
        self.generation_lock = threading.Lock()
        torch.set_num_threads(self.torch_threads)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass

    def _resolve_dtype(self):
        mapping = {
            "float32": torch.float32,
            "fp32": torch.float32,
            "float16": torch.float16,
            "fp16": torch.float16,
            "bfloat16": torch.bfloat16,
            "bf16": torch.bfloat16,
            "auto": "auto",
        }
        return mapping.get(self.dtype_name, torch.float32)

    def _load_single_model(self, model_name):
        config = AutoConfig.from_pretrained(
            model_name,
            trust_remote_code=False,
            local_files_only=self.local_files_only,
        )
        tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            trust_remote_code=False,
            local_files_only=self.local_files_only,
            use_fast=True,
        )
        model_class = AutoModelForSeq2SeqLM if config.is_encoder_decoder else AutoModelForCausalLM
        kwargs = {
            "low_cpu_mem_usage": True,
            "trust_remote_code": False,
            "local_files_only": self.local_files_only,
        }

        dtype = self._resolve_dtype()
        try:
            model = model_class.from_pretrained(model_name, dtype=dtype, **kwargs)
        except TypeError:
            model = model_class.from_pretrained(model_name, torch_dtype=dtype, **kwargs)

        model.eval()
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        return tokenizer, model, bool(config.is_encoder_decoder)

    def load(self):
        if not self.enabled:
            raise RuntimeError("LLM inference is disabled.")

        if self.tokenizer is not None and self.model is not None:
            return self.tokenizer, self.model

        with self.load_lock:
            if self.tokenizer is not None and self.model is not None:
                return self.tokenizer, self.model

            candidates = [self.primary_model]
            if self.fallback_model and self.fallback_model != self.primary_model:
                candidates.append(self.fallback_model)

            errors = []
            for candidate in candidates:
                try:
                    tokenizer, model, is_encoder_decoder = self._load_single_model(candidate)
                    self.tokenizer = tokenizer
                    self.model = model
                    self.model_name = candidate
                    self.is_encoder_decoder = is_encoder_decoder
                    self.load_error = None
                    return tokenizer, model
                except Exception as error:
                    errors.append(f"{candidate}: {error!r}")
                    self.tokenizer = None
                    self.model = None
                    gc.collect()

            self.load_error = " | ".join(errors)
            raise RuntimeError(self.load_error)

    def _build_inputs(self, messages):
        if self.is_encoder_decoder:
            prompt = "\n\n".join(
                f"{item.get('role', 'user').upper()}: {item.get('content', '')}"
                for item in messages
            )
            return self.tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=self.max_input_tokens,
            )

        try:
            prompt = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        except TypeError:
            prompt = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        return self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_input_tokens,
        )

    def generate(self, messages):
        tokenizer, model = self.load()
        with self.generation_lock:
            inputs = self._build_inputs(messages)
            with torch.inference_mode():
                if self.is_encoder_decoder:
                    output = model.generate(
                        **inputs,
                        max_new_tokens=self.max_new_tokens,
                        do_sample=False,
                        num_beams=2,
                        no_repeat_ngram_size=3,
                    )
                    generated = output[0]
                else:
                    output = model.generate(
                        **inputs,
                        max_new_tokens=self.max_new_tokens,
                        do_sample=True,
                        temperature=0.2,
                        top_p=0.8,
                        top_k=20,
                        repetition_penalty=1.05,
                        pad_token_id=tokenizer.pad_token_id,
                        eos_token_id=tokenizer.eos_token_id,
                    )
                    generated = output[0][inputs["input_ids"].shape[-1]:]

            return tokenizer.decode(generated, skip_special_tokens=True).strip()

    def status(self):
        return {
            "enabled": self.enabled,
            "loaded": self.model is not None,
            "configured_model": self.primary_model,
            "active_model": self.model_name,
            "fallback_model": self.fallback_model,
            "load_error": self.load_error,
            "torch_threads": self.torch_threads,
            "dtype": self.dtype_name,
        }


model_service = ModelService()
