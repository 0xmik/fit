"""Food macro estimation via the Anthropic API (text and/or photo).

Estimates are approximate by design — good enough for trend and awareness.
"""
import base64
import json

import anthropic

import config

SYSTEM = """You estimate calories and protein for food a single user logs.
Return STRICT JSON only — no prose, no markdown fences. Schema:
{"items": [{"name": str, "grams": number|null, "raw_or_cooked": "raw"|"cooked"|null,
"kcal": integer, "protein_g": number, "meal": "breakfast"|"lunch"|"dinner"|"snack"|"none"}]}
Rules:
- grams is the amount EATEN. If the user gives grams, use them; otherwise estimate.
- If raw/cooked is stated, keep it; otherwise infer or use null.
- If no meal is given, infer it from the local time provided.
- Reasonable, realistic estimates. When unsure, estimate slightly high on kcal.
- If the input is not food at all, return {"items": []}."""


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _parse(text: str) -> list[dict]:
    text = text.strip()
    if text.startswith("```"):  # tolerate fenced output despite instructions
        text = text.strip("`")
        text = text[text.find("{"):]
    if "{" in text:
        text = text[text.index("{"): text.rindex("}") + 1]
    data = json.loads(text)
    items = data["items"]
    out = []
    for it in items:
        out.append({
            "name": str(it["name"]),
            "grams": float(it["grams"]) if it.get("grams") is not None else None,
            "raw_or_cooked": it.get("raw_or_cooked"),
            "kcal": int(round(float(it["kcal"]))),
            "protein_g": round(float(it["protein_g"]), 1),
            "meal": it.get("meal") or "none",
        })
    return out


def estimate(text: str | None, image_bytes: bytes | None,
             local_time_str: str) -> list[dict]:
    """Returns a list of food item dicts. Raises ValueError if unparseable."""
    content: list[dict] = []
    if image_bytes:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.b64encode(image_bytes).decode(),
            },
        })
    prompt = f"Local time: {local_time_str}\n"
    prompt += f"Food log entry: {text}" if text else "Estimate the food in this photo (amount eaten)."
    content.append({"type": "text", "text": prompt})

    msg = _client().messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=1500,
        system=SYSTEM,
        messages=[{"role": "user", "content": content}],
    )
    raw = "".join(b.text for b in msg.content if b.type == "text")
    try:
        return _parse(raw)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        raise ValueError(f"could not parse model output: {e}") from e
