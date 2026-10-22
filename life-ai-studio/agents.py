"""Server-side AI provider adapters. No browser API keys, no arbitrary user URLs."""
import json
import os
import re
from pathlib import PurePosixPath

import httpx

SERVICES = {
    "chatgpt": {"key": "OPENAI_API_KEY", "model": "OPENAI_MODEL", "label": "ChatGPT / OpenAI"},
    "claude": {"key": "ANTHROPIC_API_KEY", "model": "ANTHROPIC_MODEL", "label": "Claude / Anthropic"},
    "grok": {"key": "XAI_API_KEY", "model": "XAI_MODEL", "label": "Grok / xAI"},
    "hey-jose": {"key": "JOSE_AGENT_KEY", "model": None, "label": "Hey Jose"},
    "custom": {"key": "EXTRA_AGENT_KEY", "model": "EXTRA_AGENT_MODEL", "label": "Custom AI"},
}

SANDBOX_AGENTS = {
    "demo-frontend": {"name":"Sandbox Frontend (simulation)", "path":"src/demo_frontend.js",
                      "source":"export function greeting(name) { return `Hello, ${name}!`; }\\n"},
    "demo-backend": {"name":"Sandbox Backend (simulation)", "path":"src/demo_backend.py",
                     "source":"def health():\\n    return {\'status\': \'ok\'}\\n"},
    "demo-qa": {"name":"Sandbox QA (simulation)", "path":"tests/demo_qa.py",
                "source":"def test_example():\\n    assert 1 + 1 == 2\\n"},
}

def catalog():
    normal = [
        {"id": key, "name": val["label"], "ready": (
            bool(os.getenv("JOSE_AGENT_URL")) if key == "hey-jose" else
            bool(os.getenv("EXTRA_AGENT_URL") and os.getenv("EXTRA_AGENT_MODEL")) if key == "custom" else
            bool(os.getenv(val["key"]) and os.getenv(val["model"]))
        )}
        for key, val in SERVICES.items()
    ]
    if os.getenv("LIFE_STAGING_ONLY") == "1":
        normal.extend({"id": key, "name": value["name"], "ready": True, "simulation": True}
                      for key,value in SANDBOX_AGENTS.items())
    return normal

async def generate(provider, instructions, prompt):
    if provider in SANDBOX_AGENTS and os.getenv("LIFE_STAGING_ONLY") == "1":
        sample=SANDBOX_AGENTS[provider]
        if "For coding tasks respond ONLY" in instructions:
            return json.dumps({"summary":f"[SANDBOX SIMULATION] {sample[\'name\']} proposed one example file",
                               "files":[{"path":sample["path"], "content":sample["source"]}]})
        return f"[SANDBOX SIMULATION] {sample[\'name\']} responds: {prompt[-250:]}."
    if provider not in SERVICES:
        raise ValueError("Unknown AI provider")
    cfg = SERVICES[provider]
    key = os.getenv(cfg["key"], "")
    model = os.getenv(cfg["model"], "") if cfg["model"] else ""
    if provider != "hey-jose" and not (key and model):
        raise ValueError(f"{cfg['label']} is not configured")
    headers = {"Content-Type": "application/json"}
    if provider == "chatgpt":
        url = "https://api.openai.com/v1/responses"
        headers["Authorization"] = f"Bearer {key}"
        body = {"model": model, "instructions": instructions, "input": prompt}
    elif provider == "claude":
        url = "https://api.anthropic.com/v1/messages"
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
        body = {"model": model, "max_tokens": 3000, "system": instructions,
                "messages": [{"role": "user", "content": prompt}]}
    elif provider == "grok":
        url = "https://api.x.ai/v1/chat/completions"
        headers["Authorization"] = f"Bearer {key}"
        body = {"model": model, "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": prompt}]}
    else:
        env_url = "JOSE_AGENT_URL" if provider == "hey-jose" else "EXTRA_AGENT_URL"
        url = os.getenv(env_url, "")
        # Fixed operator-supplied URLs; HTTPS required to avoid leaking secrets.
        if not url.startswith("https://") or "@" in url:
            raise ValueError("Configured agent URL must be HTTPS")
        headers["Authorization"] = f"Bearer {key}"
        body = {"instructions": instructions, "prompt": prompt}
        if model:
            body["model"] = model
    async with httpx.AsyncClient(timeout=70.0, follow_redirects=False) as client:
        response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        data = response.json()
    if provider == "chatgpt":
        result = data.get("output_text", "")
        if not result:
            result = "\n".join(
                item.get("text", "")
                for out in data.get("output", [])
                for item in out.get("content", []) if item.get("type") == "output_text"
            )
    elif provider == "claude":
        result = "\n".join(x.get("text", "") for x in data.get("content", []) if x.get("type") == "text")
    elif provider == "grok":
        result = data["choices"][0]["message"]["content"]
    else:
        result = data.get("output") or data.get("text") or data.get("answer", "")
    if not isinstance(result, str) or not result.strip():
        raise ValueError("Provider returned no text")
    return result[:90000]

def safe_path(name):
    if not isinstance(name, str) or len(name) > 180 or "\\" in name or "\x00" in name:
        raise ValueError("Invalid path")
    path = PurePosixPath(name)
    if (path.is_absolute() or ".." in path.parts or len(path.parts) > 8 or
            not path.parts or any(p.startswith(".") for p in path.parts)):
        raise ValueError("Unsafe file path")
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", name):
        raise ValueError("Unsupported file path")
    return str(path)

def extract_code_proposal(text):
    """Models suggest complete file changes; never execute model-written code."""
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^\x60{3}(?:json)?\s*|\s*\x60{3}$", "", raw, flags=re.I)
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        return None
    result = []
    for item in payload["files"][:8]:
        if not isinstance(item, dict):
            raise ValueError("Invalid file proposal")
        path = safe_path(item.get("path"))
        content = item.get("content")
        if not isinstance(content, str) or len(content.encode()) > 60000:
            raise ValueError("Proposed file is too large")
        if any(x["path"] == path for x in result):
            raise ValueError("Duplicate proposed path")
        result.append({"path": path, "content": content})
    return {"summary": str(payload.get("summary", ""))[:2000], "files": result} if result else None
