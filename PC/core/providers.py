import re
import time
import hashlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

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


# --------------------- Verificación de modelos (texto + imagen) ---------------------
# La lista de un proveedor dice qué modelos EXISTEN, no cuáles andan ni qué tan rápidos son
# (p. ej. Nvidia lista modelos sin función desplegada -> 404; algunos Gemini tardan >30 s).
# Por eso probamos cada candidato con una consulta mínima de texto y otra de imagen.

MODEL_CACHE_KEY = "MODEL_CACHE"
MODEL_CACHE_TTL = 7 * 24 * 3600     # 1 semana
_PROBE_TIMEOUT = 15                 # segundos por prueba
_PROBE_MAX_CANDIDATES = 6
_REFRESH_RETRY_AFTER = 3600         # tras un refresco fallido, no reintentar por 1 h

# PNG 32x32 rojo: si el modelo realmente ve la imagen, contesta "rojo"/"red".
_RED_PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAKElEQVR42u3NQQ0AAAgEoNP+nTWFDzcoQE1udQQC"
                "gUAgEAgEAsGTYAGjxAE/G/Q2tQAAAABJRU5ErkJggg==")

_GROQ_SKIP = ("whisper", "orpheus", "guard", "safeguard", "tts", "allam", "embed")
_PROVIDER_URLS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "nvidia": "https://integrate.api.nvidia.com/v1/chat/completions",
}

_refresh_lock = threading.Lock()
_refreshing = set()
_last_refresh_attempt = {}


def _list_ids(provider, api_key):
    """IDs de modelos que expone el proveedor."""
    if provider == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key.strip()}"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return [m["name"].replace("models/", "") for m in resp.json().get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", []) and m.get("name")]
    url = ("https://api.groq.com/openai/v1/models" if provider == "groq"
           else "https://integrate.api.nvidia.com/v1/models")
    headers = {"Authorization": f"Bearer {api_key.strip()}", "Accept": "application/json"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return [m["id"] for m in resp.json().get("data", []) if m.get("id")]


def _candidates(provider, api_key):
    """Modelos a probar, en orden de preferencia (máx. _PROBE_MAX_CANDIDATES)."""
    ids = _list_ids(provider, api_key)
    if provider == "gemini":
        ok = [i for i in ids if i.lower().startswith("gemini")
              and not any(x in i.lower() for x in ("embedding", "aqa", "imagen", "tts", "image",
                                                   "transcribe", "robotics", "computer-use", "lyria"))]
        ordered = [m for m in _GEMINI_PREFERRED if m in ok] + sorted(ok, key=_gemini_rank, reverse=True)
    elif provider == "groq":
        ok = [i for i in ids if not any(x in i.lower() for x in _GROQ_SKIP)]
        ordered = ([GROQ_DEFAULT_MODEL] if GROQ_DEFAULT_MODEL in ok else []) \
            + [i for i in ok if _groq_is_vision(i)] + ok
    elif provider == "nvidia":
        vision = [i for i in ids if _nvidia_is_vision(i) and "embed" not in i.lower()]
        ordered = [m for m in _NVIDIA_PREFERRED if m in vision] + vision
    else:
        raise Exception(f"Proveedor no soportado: {provider}")
    seen, out = set(), []
    for m in ordered:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out[:_PROBE_MAX_CANDIDATES]


def _ask_raw(provider, api_key, model, question, base64_image, timeout, max_tokens=500):
    if provider == "gemini":
        return _ask_gemini(question, base64_image, api_key, model, timeout=timeout, retries=0)
    return _ask_openai_compatible(_PROVIDER_URLS[provider], model, question, base64_image,
                                  api_key, bool(base64_image), timeout=timeout, max_tokens=max_tokens)


def _probe_model(provider, api_key, model):
    """Devuelve (anda_con_texto, ve_imagenes) con dos consultas mínimas."""
    try:
        text = _ask_raw(provider, api_key, model, "Responde solo con la palabra OK.", None, _PROBE_TIMEOUT)
        if not text or not text.strip():
            return False, False
    except Exception as exc:
        logging.info(f"Prueba de texto falló en {provider}/{model}: {exc}")
        return False, False
    try:
        ans = _ask_raw(provider, api_key, model, "¿De qué color es esta imagen? Responde en una palabra.",
                       _RED_PNG_B64, _PROBE_TIMEOUT)
        return True, any(w in (ans or "").lower() for w in ("rojo", "red"))
    except Exception as exc:
        logging.info(f"Prueba de imagen falló en {provider}/{model}: {exc}")
        return True, False


def _detect_verified(provider, api_key):
    """Elige el primer modelo que responde texto e imagen; si ninguno ve imágenes, el
    primero que responde texto (multimodal=False). Si no se pudo verificar nada
    (sin red, sin cuota...), cae a la heurística de la lista (sin verificar)."""
    labels = {"gemini": "Gemini", "groq": "Groq", "nvidia": "Nvidia"}
    try:
        cands = _candidates(provider, api_key)
        if cands:
            # Probamos todos en paralelo pero decidimos en orden de preferencia: apenas el
            # mejor candidato que ve imágenes responde, salimos sin esperar a los lentos.
            pool = ThreadPoolExecutor(max_workers=len(cands))
            try:
                futures = [pool.submit(_probe_model, provider, api_key, m) for m in cands]
                text_only = None
                for model, fut in zip(cands, futures):
                    text_ok, vision_ok = fut.result()
                    if vision_ok:
                        return {"model": model, "name": f"{labels[provider]} ({model})",
                                "multimodal": True, "verified": True}
                    if text_ok and text_only is None:
                        text_only = model
                if text_only:
                    return {"model": text_only, "name": f"{labels[provider]} ({text_only})",
                            "multimodal": False, "verified": True}
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
    except Exception as exc:
        logging.warning(f"No se pudo verificar modelos de {provider}: {exc}")

    detect = {"gemini": _detect_gemini_model, "groq": _detect_groq_model, "nvidia": _detect_nvidia_model}
    info = dict(detect[provider](api_key))
    info["verified"] = False
    return info


# ----------------------------- Cache (memoria + disco, 1 semana) -----------------------------

def _fingerprint(api_key):
    return hashlib.sha256(api_key.strip().encode()).hexdigest()[:12]


def _disk_get(provider, api_key):
    entry = (config_manager.get(MODEL_CACHE_KEY) or {}).get(provider)
    if not isinstance(entry, dict) or entry.get("fp") != _fingerprint(api_key) or "model" not in entry:
        return None
    return entry


def _disk_set(provider, api_key, info):
    cache = dict(config_manager.get(MODEL_CACHE_KEY) or {})
    cache[provider] = {**info, "fp": _fingerprint(api_key), "ts": time.time()}
    config_manager.set(MODEL_CACHE_KEY, cache)


def _store(provider, api_key, info):
    _model_cache[(provider, api_key.strip())] = info
    # Solo persistimos resultados verificados: una heurística sin probar no debe
    # quedar fijada una semana.
    if info.get("verified"):
        _disk_set(provider, api_key, info)


def _refresh_async(provider, api_key):
    """Re-verifica los modelos en un hilo, sin demorar la respuesta al usuario."""
    now = time.time()
    with _refresh_lock:
        if provider in _refreshing or now - _last_refresh_attempt.get(provider, 0) < _REFRESH_RETRY_AFTER:
            return
        _refreshing.add(provider)
        _last_refresh_attempt[provider] = now

    def run():
        try:
            info = _detect_verified(provider, api_key)
            if info.get("verified"):
                _store(provider, api_key, info)
        except Exception as exc:
            logging.warning(f"Refresco de modelos de {provider} falló: {exc}")
        finally:
            with _refresh_lock:
                _refreshing.discard(provider)

    threading.Thread(target=run, daemon=True).start()


def _resolve_model(provider, api_key):
    cache_key = (provider, api_key.strip())
    if cache_key in _model_cache:
        return _model_cache[cache_key]

    if provider not in SUPPORTED_PROVIDERS:
        raise Exception(f"Proveedor no soportado: {provider}")

    entry = _disk_get(provider, api_key)
    if entry:
        info = {k: v for k, v in entry.items() if k not in ("fp", "ts")}
        _model_cache[cache_key] = info
        if time.time() - entry.get("ts", 0) > MODEL_CACHE_TTL:
            _refresh_async(provider, api_key)   # usamos el viejo ya, actualizamos de fondo
        return info

    info = _detect_verified(provider, api_key)
    _store(provider, api_key, info)
    return info


def _invalidate_model_cache(provider):
    for key in [k for k in _model_cache if k[0] == provider]:
        _model_cache.pop(key, None)
    cache = dict(config_manager.get(MODEL_CACHE_KEY) or {})
    if cache.pop(provider, None) is not None:
        config_manager.set(MODEL_CACHE_KEY, cache)


_MODEL_ERROR_HINTS = ("404", "not found", "not_found", "does not exist", "no existe",
                      "decommission", "deprecated", "no longer", "not supported")


def _is_model_error(exc):
    """True si el error indica que el modelo ya no existe/anda (no un corte de red o cuota)."""
    low = str(exc).lower()
    return any(h in low for h in _MODEL_ERROR_HINTS)


# ----------------------------- Llamadas a la API -----------------------------

def _fetch_gemini_with_retry(model, payload, api_key, retries=1, timeout=30):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key.strip()}"
    headers = {"Content-Type": "application/json"}
    last = None
    for attempt in range(retries + 1):
        try:
            last = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if last.status_code in (429, 500, 503):
                raise Exception(f"Server Error {last.status_code}")
            return last
        except Exception:
            if attempt < retries:
                time.sleep(1 * (2 ** attempt))
    return last


def _ask_gemini(question, base64_image, api_key, model, timeout=30, retries=1):
    parts = [{"text": question}]
    if base64_image:
        parts.append({"inlineData": {"mimeType": "image/png", "data": base64_image}})
    payload = {"contents": [{"parts": parts}]}
    resp = _fetch_gemini_with_retry(model, payload, api_key, retries=retries, timeout=timeout)
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


def _ask_openai_compatible(url, model, question, base64_image, api_key, with_image,
                           timeout=30, max_tokens=4000):
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
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        try:
            err = resp.json().get("error", {}).get("message", f"Status {resp.status_code}")
        except Exception:
            err = f"Status {resp.status_code}"
        raise Exception(err)
    return resp.json()["choices"][0]["message"]["content"] or ""


def _call_provider(provider, question, base64_image, needs_image):
    key = config_manager.get(_KEY_NAMES[provider])
    if not key:
        raise Exception(f"Falta la API Key de {provider}.")

    for attempt in (0, 1):
        info = _resolve_model(provider, key)
        if needs_image and not info["multimodal"]:
            raise Exception(
                f"El modelo {info['model']} no soporta imágenes; se omite {provider}."
            )
        try:
            if provider == "gemini":
                text = _ask_gemini(question, base64_image, key, info["model"])
            elif provider in _PROVIDER_URLS:
                text = _ask_openai_compatible(
                    _PROVIDER_URLS[provider], info["model"], question, base64_image, key, needs_image)
            else:
                raise Exception(f"Proveedor no soportado: {provider}")
            return text, info["name"]
        except Exception as exc:
            if attempt == 0 and _is_model_error(exc):
                # El modelo cambió o se retiró: re-detectamos ahora y reintentamos una vez.
                logging.warning(f"{provider}: {exc}. Actualizando modelos y reintentando.")
                _invalidate_model_cache(provider)
                continue
            raise


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

    raise Exception("Todos los proveedores fallaron. " + " | ".join(errors))
