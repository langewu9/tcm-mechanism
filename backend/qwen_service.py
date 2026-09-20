from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import requests

from .config import QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL


QWEN_MODELS = [
    "qwen-plus",
    "qwen-turbo",
    "qwen-max",
    "qwen-long",
    "qwq-plus",
    "QLUNLP/BianCang-Qwen2.5-7B-Instruct",
]
BIANCANG_MODEL_ID = "QLUNLP/BianCang-Qwen2.5-7B-Instruct"
BIANCANG_LOCAL_BASE_URL = "http://127.0.0.1:8000/v1"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _clean_base_url(base_url: str | None) -> str:
    cleaned = (base_url or QWEN_BASE_URL).strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL 必须是 http/https 地址。")
    return cleaned


def _is_local_base_url(base_url: str) -> bool:
    return urlparse(base_url).hostname in LOCAL_HOSTS


def _key(api_key: str | None) -> str:
    return (api_key or QWEN_API_KEY or "").strip()


def _model(model: str | None) -> str:
    return (model or QWEN_MODEL or QWEN_MODELS[0]).strip()


def status() -> dict[str, Any]:
    return {
        "configured": bool(_key(None)),
        "base_url": QWEN_BASE_URL,
        "model": QWEN_MODEL,
        "env_key_name": "DASHSCOPE_API_KEY",
        "mode": "OpenAI compatible chat/completions",
        "models": QWEN_MODELS,
        "biancang_model": BIANCANG_MODEL_ID,
        "biancang_base_url": BIANCANG_LOCAL_BASE_URL,
    }


def models() -> dict[str, Any]:
    return {
        "items": QWEN_MODELS,
        "default": _model(None),
        "base_url": QWEN_BASE_URL,
        "presets": [
            {
                "id": "dashscope",
                "label": "阿里云百炼 Qwen",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model": "qwen-plus",
                "requires_api_key": True,
            },
            {
                "id": "biancang-local",
                "label": "本地 BianCang-Qwen2.5-7B-Instruct",
                "base_url": BIANCANG_LOCAL_BASE_URL,
                "model": BIANCANG_MODEL_ID,
                "requires_api_key": False,
            },
        ],
    }


def chat(
    messages: list[dict[str, str]],
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    try:
        cleaned_base_url = _clean_base_url(base_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    key = _key(api_key)
    is_local = _is_local_base_url(cleaned_base_url)
    if not key and not is_local:
        return {"ok": False, "error": "未配置 DASHSCOPE_API_KEY 或页面临时 API Key。"}

    endpoint = f"{cleaned_base_url}/chat/completions"
    payload = {
        "model": _model(model),
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    headers = {"Content-Type": "application/json"}
    headers["Authorization"] = f"Bearer {key or 'local-model'}"
    effective_timeout = max(timeout, 180) if is_local else timeout
    try:
        res = requests.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=effective_timeout,
        )
        if not res.ok:
            return {"ok": False, "status_code": res.status_code, "error": res.text[:1000]}
        data = res.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"ok": True, "content": content, "raw": data, "model": payload["model"], "base_url": cleaned_base_url}
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)}


def test_connection(api_key: str | None = None, base_url: str | None = None, model: str | None = None) -> dict[str, Any]:
    return chat(
        [
            {"role": "system", "content": "你是连接测试助手。"},
            {"role": "user", "content": "请用一句话回复：Qwen接口连接成功。"},
        ],
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0,
        max_tokens=32,
        timeout=30,
    )


def scientific_plan_prompt(local_report: dict[str, Any]) -> list[dict[str, str]]:
    compact = json.dumps(local_report, ensure_ascii=False)[:20000]
    system = (
        "你是面向中医药网络药理学的AI Scientist。"
        "必须基于给定证据生成可验证科学假设，不能编造不存在的数据库结果或文献。"
        "请使用中文，结构清晰，突出Problem Statement、Rationale、Technical Details、Datasets、"
        "Paper Title、Paper Abstract、Methods、Experiments、Results、References。"
    )
    user = (
        "下面是本地数据库检索得到的结构化证据。请在不虚构事实的前提下，"
        "将它升级为更像参赛作品的科学假设与研究计划。"
        "References部分只能列出给定来源或写明“待接入文献检索后补充真实论文”。\n\n"
        f"{compact}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
