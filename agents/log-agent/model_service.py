import gc
import json
import os
import threading
import time


MODEL_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "s": {"type": "string"},
        "o": {
            "type": "string",
            "enum": [
                "APPLICATION_DEFECT",
                "ENVIRONMENT",
                "TEST_DISCOVERY",
                "EXECUTION",
                "NOT_ESTABLISHED",
            ],
        },
        "r": {
            "type": "string",
            "enum": [
                "LOW",
                "MEDIUM",
                "HIGH",
                "CRITICAL",
                "UNKNOWN",
            ],
        },
        "c": {
            "type": "string",
            "enum": [
                "HIGH",
                "MEDIUM",
                "LOW",
            ],
        },
        "v": {"type": "string"},
        "x": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "f": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "k": {"type": "string"},
                    "o": {
                        "type": "string",
                        "enum": [
                            "APPLICATION_DEFECT",
                            "ENVIRONMENT",
                            "TEST_DISCOVERY",
                            "EXECUTION",
                            "NOT_ESTABLISHED",
                        ],
                    },
                    "c": {"type": "string"},
                    "i": {"type": "string"},
                    "a": {"type": "string"},
                },
                "required": ["f", "k", "o", "c", "i", "a"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["s", "o", "r", "c", "v", "x"],
    "additionalProperties": False,
}



def env_bool(name, default):
    value = os.getenv(name)

    if value is None:
        return bool(default)

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def safe_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


class ModelService:
    def __init__(self):
        self.model_repo = os.getenv(
            "HF_MODEL_REPO",
            "Qwen/Qwen3-1.7B-GGUF",
        ).strip()
        self.model_file = os.getenv(
            "HF_MODEL_FILE",
            "Qwen3-1.7B-Q5_K_M.gguf",
        ).strip()
        self.model_revision = os.getenv(
            "HF_MODEL_REVISION",
            "cd3d34a469f89b12676edce7d272750201959466",
        ).strip()
        self.quantization = os.getenv(
            "MODEL_QUANTIZATION",
            "Q5_K_M",
        ).strip()
        self.primary_model = os.getenv(
            "HF_MODEL",
            f"{self.model_repo}:{self.quantization}",
        ).strip()
        self.cache_dir = os.getenv(
            "MODEL_CACHE_DIR",
            "/opt/huggingface/hub",
        ).strip()
        self.enabled = env_bool("LLM_ENABLED", True)
        self.local_files_only = env_bool(
            "HF_LOCAL_FILES_ONLY",
            False,
        )
        self.max_input_tokens = max(
            512,
            int(os.getenv("MODEL_MAX_INPUT_TOKENS", "2048")),
        )
        self.max_new_tokens = max(
            96,
            int(os.getenv("MODEL_MAX_NEW_TOKENS", "192")),
        )
        self.max_generation_seconds = max(
            10.0,
            float(os.getenv("MODEL_MAX_GENERATION_SECONDS", "105")),
        )
        self.failure_cooldown_seconds = max(
            0.0,
            float(os.getenv("MODEL_FAILURE_COOLDOWN_SECONDS", "180")),
        )
        self.prompt_cache_mb = max(
            0,
            int(os.getenv("MODEL_PROMPT_CACHE_MB", "512")),
        )
        self.context_tokens = max(
            1024,
            int(os.getenv("MODEL_CONTEXT_TOKENS", "4096")),
        )
        self.batch_tokens = max(
            64,
            min(
                self.context_tokens,
                int(os.getenv("MODEL_BATCH_TOKENS", "512")),
            ),
        )
        self.threads = max(
            1,
            int(os.getenv("MODEL_THREADS", "2")),
        )
        self.threads_batch = max(
            1,
            int(os.getenv("MODEL_THREADS_BATCH", str(self.threads))),
        )
        self.temperature = max(
            0.01,
            float(os.getenv("MODEL_TEMPERATURE", "0.7")),
        )
        self.top_p = min(
            1.0,
            max(0.01, float(os.getenv("MODEL_TOP_P", "0.8"))),
        )
        self.top_k = max(
            0,
            int(os.getenv("MODEL_TOP_K", "20")),
        )
        self.min_p = min(
            1.0,
            max(0.0, float(os.getenv("MODEL_MIN_P", "0"))),
        )
        self.presence_penalty = min(
            2.0,
            max(
                0.0,
                float(os.getenv("MODEL_PRESENCE_PENALTY", "1.5")),
            ),
        )
        self.repeat_penalty = max(
            0.01,
            float(os.getenv("MODEL_REPEAT_PENALTY", "1.0")),
        )
        self.seed = int(os.getenv("MODEL_SEED", "17"))
        self.use_mmap = env_bool("MODEL_USE_MMAP", True)
        self.model = None
        self.model_path = None
        self.model_name = None
        self.load_error = None
        self.load_seconds = None
        self.last_generation = None
        self.degraded_until = 0.0
        self.degraded_reason = None
        self.load_lock = threading.Lock()
        self.generation_lock = threading.Lock()

    def _download_model(self):
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as error:
            raise RuntimeError(
                "huggingface_hub is required for the configured GGUF model backend."
            ) from error

        return hf_hub_download(
            repo_id=self.model_repo,
            filename=self.model_file,
            revision=self.model_revision,
            cache_dir=self.cache_dir,
            local_files_only=self.local_files_only,
        )

    def _load_model(self):
        try:
            from llama_cpp import Llama, LlamaRAMCache
        except ImportError as error:
            raise RuntimeError(
                "llama-cpp-python is required for the configured GGUF model backend."
            ) from error

        model_path = self._download_model()
        model = Llama(
            model_path=model_path,
            n_ctx=self.context_tokens,
            n_batch=self.batch_tokens,
            n_threads=self.threads,
            n_threads_batch=self.threads_batch,
            n_gpu_layers=0,
            seed=self.seed,
            use_mmap=self.use_mmap,
            use_mlock=False,
            verbose=False,
        )

        if self.prompt_cache_mb > 0:
            model.set_cache(
                LlamaRAMCache(
                    capacity_bytes=self.prompt_cache_mb
                    * 1024
                    * 1024
                )
            )

        return model_path, model

    def load(self):
        if not self.enabled:
            raise RuntimeError("LLM inference is disabled.")

        if self.model is not None:
            return self.model

        with self.load_lock:
            if self.model is not None:
                return self.model

            started = time.monotonic()

            try:
                model_path, model = self._load_model()
                self.model_path = model_path
                self.model = model
                self.model_name = self.primary_model
                self.load_error = None
                self.load_seconds = round(
                    time.monotonic() - started,
                    3,
                )
                return model
            except Exception as error:
                self.model = None
                self.model_path = None
                self.model_name = None
                self.load_error = repr(error)
                self.load_seconds = round(
                    time.monotonic() - started,
                    3,
                )
                gc.collect()
                raise RuntimeError(self.load_error) from error

    def _cooldown_remaining(self):
        return max(
            0.0,
            self.degraded_until - time.monotonic(),
        )

    def _mark_degraded(self, reason):
        self.degraded_reason = str(reason)
        self.degraded_until = (
            time.monotonic()
            + self.failure_cooldown_seconds
        )

    def _clear_degraded(self):
        self.degraded_until = 0.0
        self.degraded_reason = None

    def _prepare_messages(self, messages):
        prepared = [
            {
                "role": str(message.get("role") or "user"),
                "content": str(message.get("content") or ""),
            }
            for message in messages
        ]

        for message in prepared:
            if message["role"] == "system":
                message["content"] = (
                    message["content"].rstrip()
                    + "\n\n/no_think"
                )
                return prepared

        return [
            {
                "role": "system",
                "content": "/no_think",
            },
            *prepared,
        ]

    def _count_message_tokens(self, model, messages):
        serialized = json.dumps(
            messages,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        try:
            tokens = model.tokenize(
                serialized,
                add_bos=False,
                special=True,
            )
        except TypeError:
            tokens = model.tokenize(
                serialized,
                add_bos=False,
            )

        return len(tokens)

    def _count_text_tokens(self, model, text):
        if not text:
            return 0

        value = str(text).encode("utf-8")

        try:
            tokens = model.tokenize(
                value,
                add_bos=False,
                special=True,
            )
        except TypeError:
            tokens = model.tokenize(
                value,
                add_bos=False,
            )

        return len(tokens)

    def _response_format(self):
        return {
            "type": "json_object",
            "schema": MODEL_RESPONSE_SCHEMA,
        }

    def _create_stream(self, model, messages):
        return model.create_chat_completion(
            messages=messages,
            response_format=self._response_format(),
            max_tokens=self.max_new_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            top_k=self.top_k,
            min_p=self.min_p,
            presence_penalty=self.presence_penalty,
            frequency_penalty=0.0,
            repeat_penalty=self.repeat_penalty,
            seed=self.seed,
            stream=True,
        )

    def generate(self, messages):
        self.last_generation = None
        cooldown_remaining = self._cooldown_remaining()

        if cooldown_remaining > 0:
            self.last_generation = {
                "backend": "llama.cpp",
                "quantization": self.quantization,
                "bypassed": True,
                "bypass_reason": "cooldown",
                "cooldown_remaining_seconds": round(
                    cooldown_remaining,
                    3,
                ),
            }
            raise RuntimeError(
                "LLM inference is temporarily bypassed after a recent backend timeout "
                f"(cooldown_remaining_seconds={cooldown_remaining:.3f})."
            )

        model = self.load()

        with self.generation_lock:
            prepared_messages = self._prepare_messages(messages)
            input_tokens = self._count_message_tokens(
                model,
                prepared_messages,
            )

            if input_tokens > self.max_input_tokens:
                raise RuntimeError(
                    f"Model input contains approximately {input_tokens} tokens, exceeding the configured safe limit of {self.max_input_tokens}; deterministic fallback was selected instead of truncating locked evidence."
                )

            started = time.monotonic()
            parts = []
            finish_reason = None
            timed_out = False
            stream = None
            first_chunk_seconds = None
            first_content_seconds = None

            try:
                stream = self._create_stream(
                    model,
                    prepared_messages,
                )

                for chunk in stream:
                    elapsed = time.monotonic() - started

                    if first_chunk_seconds is None:
                        first_chunk_seconds = elapsed

                    choices = chunk.get("choices") or []

                    if choices:
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        content = delta.get("content")

                        if content:
                            if first_content_seconds is None:
                                first_content_seconds = elapsed
                            parts.append(str(content))

                        if choice.get("finish_reason"):
                            finish_reason = str(
                                choice.get("finish_reason")
                            )

                    if (
                        elapsed >= self.max_generation_seconds
                        and not finish_reason
                    ):
                        timed_out = True
                        break
            finally:
                if timed_out and stream is not None:
                    close = getattr(stream, "close", None)

                    if callable(close):
                        close()

            elapsed = time.monotonic() - started
            text = "".join(parts).strip()
            completion_tokens = self._count_text_tokens(
                model,
                text,
            )
            tokens_per_second = (
                round(completion_tokens / elapsed, 3)
                if elapsed > 0 and completion_tokens
                else 0.0
            )
            self.last_generation = {
                "backend": "llama.cpp",
                "quantization": self.quantization,
                "input_tokens_approx": input_tokens,
                "completion_tokens": completion_tokens,
                "elapsed_seconds": round(elapsed, 3),
                "first_chunk_seconds": (
                    round(first_chunk_seconds, 3)
                    if first_chunk_seconds is not None
                    else None
                ),
                "first_content_seconds": (
                    round(first_content_seconds, 3)
                    if first_content_seconds is not None
                    else None
                ),
                "tokens_per_second": tokens_per_second,
                "finish_reason": finish_reason,
                "timed_out": timed_out,
                "max_generation_seconds": self.max_generation_seconds,
                "max_new_tokens": self.max_new_tokens,
            }

            if timed_out:
                self._mark_degraded("generation_timeout")
                raise RuntimeError(
                    "The configured LLM exceeded the generation time limit "
                    f"(backend=llama.cpp, generated_tokens={completion_tokens}, elapsed_seconds={elapsed:.3f}, tokens_per_second={tokens_per_second:.3f})."
                )

            if not text:
                raise RuntimeError(
                    "The configured LLM returned an empty response."
                )

            try:
                json.loads(text)
            except json.JSONDecodeError as error:
                raise RuntimeError(
                    "The configured GGUF JSON-constrained generation returned invalid JSON."
                ) from error

            if finish_reason == "length":
                raise RuntimeError(
                    "The configured LLM reached the output token limit before completing the requested response."
                )

            self._clear_degraded()
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
            "backend": "llama.cpp",
            "configured_model": self.primary_model,
            "active_model": self.model_name,
            "model_repo": self.model_repo,
            "model_file": self.model_file,
            "model_revision": self.model_revision,
            "quantization": self.quantization,
            "load_error": self.load_error,
            "load_seconds": self.load_seconds,
            "context_tokens": self.context_tokens,
            "batch_tokens": self.batch_tokens,
            "threads": self.threads,
            "threads_batch": self.threads_batch,
            "max_input_tokens": self.max_input_tokens,
            "max_new_tokens": self.max_new_tokens,
            "max_generation_seconds": self.max_generation_seconds,
            "failure_cooldown_seconds": self.failure_cooldown_seconds,
            "cooldown_remaining_seconds": round(
                self._cooldown_remaining(),
                3,
            ),
            "degraded_reason": self.degraded_reason,
            "prompt_cache_mb": self.prompt_cache_mb,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "min_p": self.min_p,
            "presence_penalty": self.presence_penalty,
            "repeat_penalty": self.repeat_penalty,
            "seed": self.seed,
            "use_mmap": self.use_mmap,
            "last_generation": self.last_generation,
        }


model_service = ModelService()
