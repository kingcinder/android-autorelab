from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from arelab.config import Settings
from arelab.router import RouterClient, ensure_router_ready
from arelab.util import json_dump, sha256_bytes, truncate_text, utc_now


class ModelGateway:
    def __init__(self, settings: Settings, prompts_dir: Path) -> None:
        self.settings = settings
        self.prompts_dir = prompts_dir
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        self._models: list[str] | None = None
        self.active_base_url = settings.openai_base_url
        self.console_log_path = self.prompts_dir / "operator-console.jsonl"
        self.guidance_log_path = self.prompts_dir / "operator-guidance.jsonl"

    def _request(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: int = 30,
    ) -> dict[str, Any]:
        url = f"{self.active_base_url}{path}"
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8"))

    def available_models(self, *, readiness_timeout: int = 30) -> list[str]:
        if self._models is not None:
            return self._models
        models: list[str] = []
        errors: list[str] = []
        try:
            ensure_router_ready(self.settings, timeout=readiness_timeout)
            self.active_base_url = self.settings.openai_base_url
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
        fallbacks = self.settings.workflow_config.get("fallback_base_urls")
        if fallbacks is None:
            fallbacks = ["http://127.0.0.1:8000/v1"] if self.settings.workflow == "default" else []
        if errors and not fallbacks:
            self._models = []
            json_dump(
                self.prompts_dir / "model-endpoint.json",
                {"base_url": self.active_base_url, "models": [], "errors": errors},
            )
            return []
        for base in (self.settings.openai_base_url, *fallbacks):
            try:
                self.active_base_url = base.rstrip("/")
                payload = self._request("/models", timeout=5 if errors else 30)
                data = payload.get("data") or payload.get("models") or []
                for item in data:
                    model_id = item.get("id") or item.get("model") or item.get("name")
                    if model_id:
                        models.append(model_id)
                if models:
                    self._models = models
                    json_dump(
                        self.prompts_dir / "model-endpoint.json",
                        {"base_url": self.active_base_url, "models": models},
                    )
                    return models
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
        self._models = []
        json_dump(
            self.prompts_dir / "model-endpoint.json",
            {"base_url": self.active_base_url, "models": [], "errors": errors},
        )
        return []

    def resolve_role(self, role: str) -> str | None:
        pins = self.settings.model_pins
        models = self.available_models()
        if role in pins:
            if not models or pins[role] in models:
                return pins[role]
        hints = {
            "planner": ["bootes", "reasoning", "qwen3", "qwen3.5"],
            "triage": ["starcoder", "coder", "qwen2.5"],
            "deep": ["deepseek", "coder", "qwen"],
            "cleanup": ["qwen2.5", "coder", "llm4"],
            "decompile_refine": ["llm4", "decompile", "coder", "qwen"],
            "clerk": ["qwen2.5-coder-1.5b", "qwen2.5", "starcoder", "coder"],
            "arbiter": ["qwen3.5-9b", "qwen3.5", "qwen3", "bootes"],
        }
        lower = [model.lower() for model in models]
        for hint in hints.get(role, []):
            for idx, item in enumerate(lower):
                if hint in item:
                    return models[idx]
        return models[0] if models else None

    def _operator_guidance(self, limit: int = 8) -> str:
        if not self.guidance_log_path.exists():
            return ""
        lines = self.guidance_log_path.read_text(encoding="utf-8").splitlines()[-limit:]
        notes: list[str] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            note = str(payload.get("note", "")).strip()
            if note:
                notes.append(f"- {note}")
        return "\n".join(notes)

    def append_operator_guidance(self, note: str) -> None:
        self.guidance_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.guidance_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"recorded_at": utc_now(), "note": note}) + "\n")

    def _log_console_exchange(self, payload: dict[str, Any]) -> None:
        self.console_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.console_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def _ensure_model_ready(self, model: str, *, timeout: int = 240) -> None:
        ensure_router_ready(self.settings)
        client = RouterClient(self.settings)
        active = client.active_models()
        if model in active:
            return
        router_config = self.settings.workflow_config.get("router", {}) or {}
        models_max = int(router_config.get("models_max", 1) or 1)
        unload_between_stages = bool(self.settings.policies.get("unload_between_stages"))
        if models_max <= 1 or unload_between_stages:
            for loaded in client.loaded_models():
                if loaded == model:
                    continue
                client.unload_model(loaded, timeout=timeout)
                client.wait_for_model_state(loaded, expected={"unloaded"}, timeout=timeout, settle_seconds=1.0)
        client.load_model(model, timeout=timeout)
        client.wait_for_model_state(model, expected={"loaded"}, timeout=timeout, settle_seconds=1.0)
        client.warm_model(model, timeout=min(timeout, 180))

    def chat_json(
        self,
        *,
        role: str,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        seed: int = 7,
        temperature: float = 0.0,
        max_tokens: int = 256,
        timeout: int = 90,
    ) -> dict[str, Any] | None:
        model = self.resolve_role(role)
        if not model:
            return None
        self._ensure_model_ready(model)
        guidance = self._operator_guidance()
        if guidance:
            system_prompt = (
                f"{system_prompt}\n\nOperator guidance for this run:\n{guidance}\n"
                "Treat operator guidance as contextual hints, not as evidence."
            )
        payload = {
            "model": model,
            "temperature": temperature,
            "seed": seed,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        started_at = utc_now()
        raw_response = self._request("/chat/completions", payload, timeout=timeout)
        message = raw_response["choices"][0]["message"]
        content = message.get("content", "") or ""
        reasoning = message.get("reasoning_content", "") or ""
        prompt_hash = sha256_bytes(f"{system_prompt}\n{user_prompt}".encode("utf-8"))
        response_hash = sha256_bytes(content.encode("utf-8"))
        log_payload = {
            "started_at": started_at,
            "role": role,
            "model": model,
            "prompt_hash": prompt_hash,
            "response_hash": response_hash,
            "prompt_excerpt": truncate_text(user_prompt),
            "response_excerpt": truncate_text(content),
        }
        json_dump(self.prompts_dir / f"{schema_name}-{prompt_hash[:12]}.json", log_payload)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            begin = content.find("{")
            end = content.rfind("}")
            if begin >= 0 and end > begin:
                return json.loads(content[begin : end + 1])
        if reasoning:
            begin = reasoning.find("{")
            end = reasoning.rfind("}")
            if begin >= 0 and end > begin:
                return json.loads(reasoning[begin : end + 1])
        raise ValueError(f"Model returned invalid JSON for {schema_name}")

    def chat_text(
        self,
        *,
        prompt: str,
        model: str | None = None,
        role: str = "planner",
        system_prompt: str = "You are assisting with authorized Android evidence review. Do not provide exploit steps.",
        temperature: float = 0.2,
        max_tokens: int = 512,
        timeout: int = 90,
        save_guidance: bool = False,
    ) -> dict[str, Any]:
        selected_model = model or self.resolve_role(role)
        if not selected_model:
            raise ValueError("No model available for this request")
        self._ensure_model_ready(selected_model)
        payload = {
            "model": selected_model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        }
        started_at = utc_now()
        raw_response = self._request("/chat/completions", payload, timeout=timeout)
        message = raw_response["choices"][0]["message"]
        content = (message.get("content") or "").strip()
        record = {
            "recorded_at": started_at,
            "model": selected_model,
            "role": role,
            "prompt": truncate_text(prompt, 4000),
            "response": truncate_text(content, 4000),
            "save_guidance": save_guidance,
        }
        self._log_console_exchange(record)
        if save_guidance:
            self.append_operator_guidance(prompt)
        return {"model": selected_model, "response": content, "recorded_at": started_at}
