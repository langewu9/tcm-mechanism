from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field


MODEL_ID = "QLUNLP/BianCang-Qwen2.5-7B-Instruct"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_DEPS_DIR = os.path.join(PROJECT_ROOT, ".deps", "biancang")
if os.path.isdir(LOCAL_DEPS_DIR):
    sys.path.insert(0, LOCAL_DEPS_DIR)

DEFAULT_LOCAL_MODEL_DIR = os.path.join(PROJECT_ROOT, "models", "BianCang-Qwen2.5-7B-Instruct")
MODEL_DIR = os.getenv("BIANCANG_MODEL_DIR") or (DEFAULT_LOCAL_MODEL_DIR if os.path.isdir(DEFAULT_LOCAL_MODEL_DIR) else MODEL_ID)
MAX_NEW_TOKENS = int(os.getenv("BIANCANG_MAX_NEW_TOKENS", "256"))

app = FastAPI(title="BianCang OpenAI-Compatible Server", version="1.0.0")
tokenizer = None
model = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = MODEL_ID
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float = 0.2
    max_tokens: int | None = None


def load_model() -> tuple[Any, Any]:
    global tokenizer, model
    if tokenizer is not None and model is not None:
        return tokenizer, model

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ModuleNotFoundError as exc:
        missing = exc.name or "required package"
        raise RuntimeError(
            f"{missing} is not installed. Run: D:\\mini\\envs\\py310\\python.exe -m pip install --target .deps\\biancang -r requirements-biancang.txt"
        ) from exc

    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_DIR,
        torch_dtype="auto",
        device_map=os.getenv("BIANCANG_DEVICE_MAP", "auto"),
        trust_remote_code=True,
    )
    model.eval()
    return tokenizer, model


def build_prompt(tok: Any, messages: list[ChatMessage]) -> str:
    payload = [
        message.model_dump() if hasattr(message, "model_dump") else message.dict()
        for message in messages
    ]
    if hasattr(tok, "apply_chat_template"):
        return tok.apply_chat_template(payload, tokenize=False, add_generation_prompt=True)
    return "\n".join(f"{message.role}: {message.content}" for message in messages) + "\nassistant:"


@app.get("/v1/models")
def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [{"id": MODEL_ID, "object": "model", "owned_by": "local"}],
    }


@app.post("/v1/chat/completions")
def chat_completions(payload: ChatCompletionRequest) -> dict[str, Any]:
    tok, llm = load_model()
    prompt = build_prompt(tok, payload.messages)
    inputs = tok([prompt], return_tensors="pt")
    input_device = next(llm.parameters()).device
    inputs = {key: value.to(input_device) for key, value in inputs.items()}

    max_new_tokens = payload.max_tokens or MAX_NEW_TOKENS
    do_sample = payload.temperature > 0
    outputs = llm.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        do_sample=do_sample,
        temperature=max(payload.temperature, 0.01),
        use_cache=True,
        pad_token_id=tok.eos_token_id,
    )
    generated_ids = outputs[0][inputs["input_ids"].shape[-1] :]
    content = tok.decode(generated_ids, skip_special_tokens=True).strip()
    created = int(time.time())
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": created,
        "model": payload.model or MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve BianCang model with an OpenAI-compatible API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
