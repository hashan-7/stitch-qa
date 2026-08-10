import gc
import os
import threading

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


class ModelService:
    def __init__(self):
        self.primary_model = os.getenv("HF_MODEL", "Qwen/Qwen3-1.7B")
        self.enabled = os.getenv("LLM_ENABLED", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.local_files_only = os.getenv(
            "HF_LOCAL_FILES_ONLY",
            "false",
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.max_input_tokens = max(
            512,
            int(os.getenv("MODEL_MAX_INPUT_TOKENS", "3072")),
        )
        self.max_new_tokens = max(
            64,
            int(os.getenv("MODEL_MAX_NEW_TOKENS", "512")),
        )
        self.max_generation_seconds = max(
            10.0,
            float(os.getenv("MODEL_MAX_GENERATION_SECONDS", "80")),
        )
        self.torch_threads = max(
            1,
            int(os.getenv("TORCH_NUM_THREADS", "2")),
        )
        self.dtype_name = os.getenv("MODEL_DTYPE", "float32").strip().lower()
        self.temperature = max(0.01, float(os.getenv("MODEL_TEMPERATURE", "0.7")))
        self.top_p = min(1.0, max(0.01, float(os.getenv("MODEL_TOP_P", "0.8"))))
        self.top_k = max(0, int(os.getenv("MODEL_TOP_K", "20")))
        self.repetition_penalty = max(
            0.01,
            float(os.getenv("MODEL_REPETITION_PENALTY", "1.05")),
        )
        self.seed = int(os.getenv("MODEL_SEED", "17"))
        self.tokenizer = None
        self.model = None
        self.model_name = None
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

    def _load_model(self):
        tokenizer = AutoTokenizer.from_pretrained(
            self.primary_model,
            trust_remote_code=False,
            local_files_only=self.local_files_only,
            use_fast=True,
        )
        kwargs = {
            "low_cpu_mem_usage": True,
            "trust_remote_code": False,
            "local_files_only": self.local_files_only,
        }
        dtype = self._resolve_dtype()

        try:
            model = AutoModelForCausalLM.from_pretrained(
                self.primary_model,
                dtype=dtype,
                **kwargs,
            )
        except TypeError:
            model = AutoModelForCausalLM.from_pretrained(
                self.primary_model,
                torch_dtype=dtype,
                **kwargs,
            )

        model.eval()

        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token

        return tokenizer, model

    def load(self):
        if not self.enabled:
            raise RuntimeError("LLM inference is disabled.")

        if self.tokenizer is not None and self.model is not None:
            return self.tokenizer, self.model

        with self.load_lock:
            if self.tokenizer is not None and self.model is not None:
                return self.tokenizer, self.model

            try:
                tokenizer, model = self._load_model()
                self.tokenizer = tokenizer
                self.model = model
                self.model_name = self.primary_model
                self.load_error = None
                return tokenizer, model
            except Exception as error:
                self.tokenizer = None
                self.model = None
                self.model_name = None
                self.load_error = repr(error)
                gc.collect()
                raise RuntimeError(self.load_error) from error

    def _build_inputs(self, messages):
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

        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=False,
        )
        input_tokens = int(inputs["input_ids"].shape[-1])

        if input_tokens > self.max_input_tokens:
            raise RuntimeError(
                f"Model input contains {input_tokens} tokens, exceeding the configured safe limit of {self.max_input_tokens}; deterministic fallback was selected instead of truncating locked evidence."
            )

        return inputs

    def generate(self, messages):
        tokenizer, model = self.load()

        with self.generation_lock:
            inputs = self._build_inputs(messages)
            torch.manual_seed(self.seed)

            with torch.inference_mode():
                output = model.generate(
                    **inputs,
                    max_new_tokens=self.max_new_tokens,
                    max_time=self.max_generation_seconds,
                    do_sample=True,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    top_k=self.top_k,
                    repetition_penalty=self.repetition_penalty,
                    pad_token_id=tokenizer.pad_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                )

            generated = output[0][inputs["input_ids"].shape[-1]:]
            text = tokenizer.decode(
                generated,
                skip_special_tokens=True,
            ).strip()

            if not text:
                raise RuntimeError("The configured LLM returned an empty response.")

            return text

    def status(self):
        if not self.enabled:
            state = "disabled"
        elif self.model is not None:
            state = "loaded"
        elif self.load_error:
            state = "load_failed"
        else:
            state = "not_loaded"

        return {
            "enabled": self.enabled,
            "loaded": self.model is not None,
            "state": state,
            "configured_model": self.primary_model,
            "active_model": self.model_name,
            "load_error": self.load_error,
            "torch_threads": self.torch_threads,
            "dtype": self.dtype_name,
            "max_input_tokens": self.max_input_tokens,
            "max_new_tokens": self.max_new_tokens,
            "max_generation_seconds": self.max_generation_seconds,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repetition_penalty": self.repetition_penalty,
            "seed": self.seed,
        }


model_service = ModelService()
