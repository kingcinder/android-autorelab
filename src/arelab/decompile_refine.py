from __future__ import annotations

from arelab.model_gateway import ModelGateway


def refine_pseudocode(gateway: ModelGateway, function_name: str, pseudocode: str) -> dict[str, str]:
    if not pseudocode.strip():
        return {"cleaned_code": "", "summary": ""}
    payload = gateway.chat_json(
        role="decompile_refine",
        system_prompt=(
            "You are a defensive reverse-engineering assistant. "
            "Clean up decompiler output into stable C-like code, keep behavior faithful, "
            "do not add exploit steps, and return JSON only."
        ),
        user_prompt=(
            "Return JSON with keys cleaned_code and summary.\n"
            f"Function: {function_name}\n"
            "Pseudocode:\n"
            f"{pseudocode}"
        ),
        schema_name=f"refine-{function_name}",
        max_tokens=384,
        timeout=120,
    )
    if not payload:
        return {"cleaned_code": pseudocode, "summary": "model unavailable"}
    return {
        "cleaned_code": payload.get("cleaned_code", pseudocode),
        "summary": payload.get("summary", ""),
    }
