import re
import time
import logging

import requests

from utils.config import config_manager
from core.mcp import inject_context_if_needed

# Proveedores soportados, en orden de fallback por defecto.
SUPPORTED_PROVIDERS = ["gemini", "groq", "nvidia"]

_KEY_NAMES = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
}

# Cache de modelos detectados por (proveedor, api_key):
# {"model": id, "name": etiqueta, "multimodal": bool}
_model_cache = {}

# Substrings que identifican modelos multimodales (visión) en Nvidia.
# Solo señales precisas: NO usar familias genéricas como "llama-3.2", porque
# sus variantes -1b/-3b son SOLO texto (únicamente las "-vision-" ven imágenes).
_NVIDIA_VISION_HINTS = (
    "vision", "-vl", "vl-", "vila", "llava", "neva", "paligemma",
    "fuyu", "kosmos", "internvl", "qwen2-vl", "qwen2.5-vl",
)


_NVIDIA_PREFERRED = ("nvidia/nemotron-3.5-super-vl-120b-a12b",)


def _nvidia_is_vision(model_id):
    """True si el id de modelo de Nvidia parece soportar imágenes (visión)."""
    low = model_id.lower()
    return any(hint in low for hint in _NVIDIA_VISION_HINTS)


# Modelo de Groq que actualmente esta habilitado y es multimodal. Se usa como preferido y como valor
# por defecto si la detección no encuentra nada mejor.
GROQ_DEFAULT_MODEL = "qwen/qwen3.8-27b"
_GROQ_VISION_HINTS = ("qwen3", "qwen2.5-vl", "qwen2-vl", "vision", "-vl", "llama-4", "scout", "maverick")


def _groq_is_vision(model_id):
    """True si el id de modelo de Groq parece soportar imágenes (visión)."""
    low = model_id.lower()
    return any(hint in low for hint in _GROQ_VISION_HINTS)


# ----------------------------- Detección de modelo -----------------------------

def _detect_gemini_model(api_key):
    """Lista los modelos de Gemini y elige uno multimodal apto (prefiere flash)."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key.strip()}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    candidates = []
    for m in resp.json().get("models", []):
        name = m.get("name", "").replace("models/", "")
        methods = m.get("supportedGenerationMethods", [])
        low = name.lower()
        if "generateContent" not in methods or not low.startswith("gemini"):
            continue
        if any(x in low for x in ("embedding", "aqa", "imagen", "tts", "image-generation")):
            continue
        candidates.append(name)

    if not candidates:
        raise Exception("No se encontró un modelo Gemini compatible.")

    candidates.sort(key=_gemini_rank, reverse=True)
    # Los flash más nuevos (p. ej. 3.8) piensan ~30 s por consulta y vencen el timeout:
    # preferimos uno rápido conocido y, si no está, el mejor rankeado.
    chosen = next((m for m in _GEMINI_PREFERRED if m in candidates), candidates[0])
    # Todos los modelos Gemini con generateContent (1.5+/2.x/3.x) son multimodales.
    return {"model": chosen, "name": f"Gemini ({chosen})", "multimodal": True}


# Modelos rápidos preferidos (en orden). Ver _detect_gemini_model.
_GEMINI_PREFERRED = ("gemini-3.5-flash", "gemini-2.5-flash")


def _gemini_rank(name):
    low = name.lower()
    ver_match = re.search(r"(\d+(?:\.\d+)?)", low)
    ver = float(ver_match.group(1)) if ver_match else 0.0
    kind = 2 if "flash" in low else (1 if "pro" in low else 0)
    return (kind, ver)


def _detect_nvidia_model(api_key):
    """Lista los modelos de Nvidia (API compatible con OpenAI) y prefiere uno de visión."""
    url = "https://integrate.api.nvidia.com/v1/models"
    headers = {"Authorization": f"Bearer {api_key.strip()}", "Accept": "application/json"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    ids = [m.get("id", "") for m in resp.json().get("data", []) if m.get("id")]
    if not ids:
        raise Exception("No se encontró ningún modelo en Nvidia.")

    # Varios modelos de visión del catálogo ya no tienen función desplegada (404);
    # preferimos uno que funciona y descartamos los de embeddings.
    vision = [i for i in ids if _nvidia_is_vision(i) and "embed" not in i.lower()]
    preferred = next((m for m in _NVIDIA_PREFERRED if m in vision), None)
    if preferred or vision:
        chosen = preferred or vision[0]
        return {"model": chosen, "name": f"Nvidia ({chosen})", "multimodal": True}
    # Sin modelo de visión: queda como solo-texto (se saltea en consultas con imagen).
    return {"model": ids[0], "name": f"Nvidia ({ids[0]})", "multimodal": False}


def _detect_groq_model(api_key):
    """Lista los modelos de Groq (API compatible con OpenAI) y prefiere uno
    multimodal. Si no puede detectar, usa el modelo conocido (Qwen 3.6 27B)."""
    try:
        url = "https://api.groq.com/openai/v1/models"
        headers = {"Authorization": f"Bearer {api_key.strip()}", "Accept": "application/json"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        ids = [m.get("id", "") for m in resp.json().get("data", []) if m.get("id")]
    except Exception:
        ids = []

    if GROQ_DEFAULT_MODEL in ids:
        chosen = GROQ_DEFAULT_MODEL          # el conocido sigue disponible
    else:
        vision = [i for i in ids if _groq_is_vision(i)]
        chosen = vision[0] if vision else GROQ_DEFAULT_MODEL
    return {"model": chosen, "name": f"Groq ({chosen})", "multimodal": True}


def _resolve_model(provider, api_key):
    cache_key = (provider, api_key.strip())
    if cache_key in _model_cache:
        return _model_cache[cache_key]

    if provider == "gemini":
        info = _detect_gemini_model(api_key)
    elif provider == "nvidia":
        info = _detect_nvidia_model(api_key)
    elif provider == "groq":
        info = _detect_groq_model(api_key)
    else:
        raise Exception(f"Proveedor no soportado: {provider}")

    _model_cache[cache_key] = info
    return info


def _invalidate_model_cache(provider):
    for key in [k for k in _model_cache if k[0] == provider]:
        _model_cache.pop(key, None)


# ----------------------------- Llamadas a la API -----------------------------

def _fetch_gemini_with_retry(model, payload, api_key, retries=1):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key.strip()}"
    headers = {"Content-Type": "application/json"}
    last = None
    for attempt in range(retries + 1):
        try:
            last = requests.post(url, json=payload, headers=headers, timeout=30)
            if last.status_code in (429, 500, 503):
                raise Exception(f"Server Error {last.status_code}")
            return last
        except Exception:
            if attempt < retries:
                time.sleep(1 * (2 ** attempt))
    return last


def _ask_gemini(question, base64_image, api_key, model):
    payload = {
        "contents": [{
            "parts": [
                {"text": question},
                {"inlineData": {"mimeType": "image/png", "data": base64_image}},
            ]
        }]
    }
    resp = _fetch_gemini_with_retry(model, payload, api_key)
    if not resp or resp.status_code != 200:
        status = resp.status_code if resp else "sin respuesta"
        raise Exception(f"Gemini Error: {status}")
    data = resp.json()
    return (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "Sin respuesta.")
    )


def _ask_openai_compatible(url, model, question, base64_image, api_key, with_image):
    content = [{"type": "text", "text": question}]
    if with_image and base64_image:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{base64_image}"},
        })
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.4,
        "max_tokens": 4000,
    }
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    if resp.status_code != 200:
        try:
            err = resp.json().get("error", {}).get("message", f"Status {resp.status_code}")
        except Exception:
            err = f"Status {resp.status_code}"
        raise Exception(err)
    return resp.json()["choices"][0]["message"]["content"]


def _call_provider(provider, question, base64_image, needs_image):
    key = config_manager.get(_KEY_NAMES[provider])
    if not key:
        raise Exception(f"Falta la API Key de {provider}.")

    info = _resolve_model(provider, key)
    if needs_image and not info["multimodal"]:
        raise Exception(
            f"El modelo {info['model']} no soporta imágenes; se omite {provider}."
        )

    if provider == "gemini":
        text = _ask_gemini(question, base64_image, key, info["model"])
    elif provider == "groq":
        text = _ask_openai_compatible(
            "https://api.groq.com/openai/v1/chat/completions",
            info["model"], question, base64_image, key, needs_image)
    elif provider == "nvidia":
        text = _ask_openai_compatible(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            info["model"], question, base64_image, key, needs_image)
    else:
        raise Exception(f"Proveedor no soportado: {provider}")

    return text, info["name"]


# ----------------------------- Router con fallback -----------------------------

def process_question(question, base64_image, provider, use_mcp):
    """Procesa la pregunta con fallback multimodal entre proveedores.

    Intenta el proveedor preferido; si falla (o su modelo no soporta imágenes
    cuando hace falta), va probando los demás. Al primero que funciona se queda
    fijado como preferido hasta que vuelva a fallar.
    """
    final_question = inject_context_if_needed(question, use_mcp)
    needs_image = bool(base64_image)

    # Cadena: preferido primero, luego el resto de soportados.
    chain = [provider] + [p for p in SUPPORTED_PROVIDERS if p != provider]
    chain = [p for p in chain if p in SUPPORTED_PROVIDERS]
    if not chain:
        chain = list(SUPPORTED_PROVIDERS)

    errors = []
    for index, prov in enumerate(chain):
        try:
            text, name = _call_provider(prov, final_question, base64_image, needs_image)
            if index != 0:
                # Nos quedamos en el proveedor que funcionó (sticky).
                config_manager.set("preferredProvider", prov)
                return text, f"Fallback: {name}"
            return text, name
        except Exception as exc:
            logging.warning(f"Proveedor '{prov}' falló: {exc}")
            errors.append(f"{prov}: {exc}")
            _invalidate_model_cache(prov)  # por si el modelo cambió/expiró

    raise Exception("Todos los proveedores fallaron. " + " | ".join(errors))
