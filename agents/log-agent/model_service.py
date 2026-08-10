import gc
import os
import threading
import time

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    StoppingCriteria,
    StoppingCriteriaList,
)


JSON_PREFILL = "{"


def complete_json_end(text):
    value = str(text or "")
    start = value.find("{")

    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(value)):
        character = value[index]

        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1

            if depth == 0:
                return index + 1

    return None


def is_complete_json_object(text):
    return complete_json_end(text) is not None


class JsonObjectStoppingCriteria(StoppingCriteria):
    def __init__(self, tokenizer, prompt_length, prefix=JSON_PREFILL):
        self.tokenizer = tokenizer
        self.prompt_length = int(prompt_length)
        self.prefix = str(prefix)

    def __call__(self, input_ids, scores, **kwargs):
        results = []

        for sequence in input_ids:
            generated = sequence[self.prompt_length:]
            text = self.prefix + self.tokenizer.decode(
                generated,
                skip_special_tokens=True,
            )
            results.append(
                [is_complete_json_object(text)]
            )

        return torch.tensor(
            results,
            dtype=torch.bool,
            device=input_ids.device,
        )


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
            96,
            int(os.getenv("MODEL_MAX_NEW_TOKENS", "384")),
        )
        self.max_generation_seconds = max(
            10.0,
            float(os.getenv("MODEL_MAX_GENERATION_SECONDS", "90")),
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
        self.last_generation = None
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
        prefilled_messages = [
            *messages,
            {
                "role": "assistant",
                "content": JSON_PREFILL,
            },
        ]

        inputs = self.tokenizer.apply_chat_template(
            prefilled_messages,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            continue_final_message=True,
            enable_thinking=False,
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
            prompt_length = int(inputs["input_ids"].shape[-1])
            stopping_criteria = StoppingCriteriaList(
                [
                    JsonObjectStoppingCriteria(
                        tokenizer,
                        prompt_length,
                    )
                ]
            )
            torch.manual_seed(self.seed)
            started = time.monotonic()

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
                    stopping_criteria=stopping_criteria,
                    pad_token_id=tokenizer.pad_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                )

            elapsed = time.monotonic() - started
            generated = output[0][prompt_length:]
            generated_tokens = int(generated.shape[-1])
            decoded = tokenizer.decode(
                generated,
                skip_special_tokens=True,
            )
            text = JSON_PREFILL + decoded
            complete_end = complete_json_end(text)
            completed_json = complete_end is not None
            hit_token_limit = generated_tokens >= self.max_new_tokens
            hit_time_limit = elapsed >= self.max_generation_seconds

            self.last_generation = {
                "generated_tokens": generated_tokens,
                "elapsed_seconds": round(elapsed, 3),
                "completed_json": completed_json,
                "hit_token_limit": hit_token_limit,
                "hit_time_limit": hit_time_limit,
            }

            if not completed_json:
                if hit_token_limit:
                    reason = "max_new_tokens"
                elif hit_time_limit:
                    reason = "max_time"
                else:
                    reason = "model_stop"

                raise RuntimeError(
                    "The configured LLM stopped before completing the required JSON object "
                    f"(reason={reason}, generated_tokens={generated_tokens}, elapsed_seconds={elapsed:.3f})."
                )

            text = text[:complete_end].strip()

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
            "last_generation": self.last_generation,
        }


model_service = ModelService()
