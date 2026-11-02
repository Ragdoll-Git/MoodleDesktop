"""Tests del router de proveedores: detección de modelo y fallback multimodal."""
import pytest

from core import providers


@pytest.fixture(autouse=True)
def _clear_model_cache():
    providers._model_cache.clear()
    providers.config_manager.config.pop(providers.MODEL_CACHE_KEY, None)
    providers._last_refresh_attempt.clear()
    yield
    providers._model_cache.clear()
    providers.config_manager.config.pop(providers.MODEL_CACHE_KEY, None)


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


# ----------------------------- Detección de modelo -----------------------------

def test_detect_gemini_prefiere_flash_mas_nuevo(monkeypatch):
    payload = {"models": [
        {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-3.5-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
        {"name": "models/imagen-3.0", "supportedGenerationMethods": ["generateContent"]},
    ]}
    monkeypatch.setattr(providers.requests, "get", lambda *a, **k: _Resp(payload))

    info = providers._detect_gemini_model("KEY")
    assert info["model"] == "gemini-3.5-flash"
    assert info["multimodal"] is True


def test_detect_gemini_sin_candidatos_falla(monkeypatch):
    payload = {"models": [
        {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
    ]}
    monkeypatch.setattr(providers.requests, "get", lambda *a, **k: _Resp(payload))
    with pytest.raises(Exception):
        providers._detect_gemini_model("KEY")


def test_detect_nvidia_prefiere_vision(monkeypatch):
    payload = {"data": [
        {"id": "meta/llama-3.1-70b-instruct"},
        {"id": "meta/llama-3.2-90b-vision-instruct"},
    ]}
    monkeypatch.setattr(providers.requests, "get", lambda *a, **k: _Resp(payload))

    info = providers._detect_nvidia_model("KEY")
    assert "vision" in info["model"]
    assert info["multimodal"] is True


def test_detect_nvidia_sin_vision_es_solo_texto(monkeypatch):
    payload = {"data": [{"id": "meta/llama-3.1-70b-instruct"}]}
    monkeypatch.setattr(providers.requests, "get", lambda *a, **k: _Resp(payload))

    info = providers._detect_nvidia_model("KEY")
    assert info["multimodal"] is False


# Catálogo realista de Nvidia: la clasificación de visión debe ser precisa.
NVIDIA_VISION_CASES = [
    # --- Multimodales (visión) ---
    ("meta/llama-3.2-90b-vision-instruct", True),
    ("meta/llama-3.2-11b-vision-instruct", True),
    ("microsoft/phi-3.5-vision-instruct", True),
    ("microsoft/phi-3-vision-128k-instruct", True),
    ("nvidia/neva-22b", True),
    ("nvidia/vila", True),
    ("google/paligemma", True),
    ("adept/fuyu-8b", True),
    ("microsoft/kosmos-2", True),
    ("qwen/qwen2-vl-7b-instruct", True),
    ("opengvlab/internvl2-26b", True),
    # --- Solo texto (NO deben marcarse como visión) ---
    ("meta/llama-3.2-3b-instruct", False),   # el bug que se corrigió
    ("meta/llama-3.2-1b-instruct", False),
    ("meta/llama-3.1-405b-instruct", False),
    ("meta/llama-3.3-70b-instruct", False),
    ("microsoft/phi-3.5-mini-instruct", False),
    ("mistralai/mistral-7b-instruct-v0.3", False),
    ("nvidia/nemotron-4-340b-instruct", False),
    ("deepseek-ai/deepseek-r1", False),
    ("google/gemma-2-27b-it", False),
]


@pytest.mark.parametrize("model_id,is_vision", NVIDIA_VISION_CASES)
def test_nvidia_clasificacion_vision(model_id, is_vision):
    assert providers._nvidia_is_vision(model_id) is is_vision


def test_detect_nvidia_catalogo_grande_elige_vision(monkeypatch):
    # Lista grande con texto y visión mezclados; debe elegir un modelo de visión
    # y NUNCA un llama-3.2 de texto (1b/3b).
    payload = {"data": [{"id": mid} for mid, _ in NVIDIA_VISION_CASES]}
    monkeypatch.setattr(providers.requests, "get", lambda *a, **k: _Resp(payload))

    info = providers._detect_nvidia_model("KEY")
    assert info["multimodal"] is True
    assert providers._nvidia_is_vision(info["model"])
    assert info["model"] not in ("meta/llama-3.2-3b-instruct", "meta/llama-3.2-1b-instruct")


def test_detect_nvidia_catalogo_solo_texto(monkeypatch):
    solo_texto = [mid for mid, vis in NVIDIA_VISION_CASES if not vis]
    payload = {"data": [{"id": mid} for mid in solo_texto]}
    monkeypatch.setattr(providers.requests, "get", lambda *a, **k: _Resp(payload))

    info = providers._detect_nvidia_model("KEY")
    assert info["multimodal"] is False


def test_detect_groq_prefiere_modelo_conocido(monkeypatch):
    payload = {"data": [
        {"id": "openai/gpt-oss-120b"},
        {"id": providers.GROQ_DEFAULT_MODEL},
    ]}
    monkeypatch.setattr(providers.requests, "get", lambda *a, **k: _Resp(payload))

    info = providers._detect_groq_model("KEY")
    assert info["model"] == providers.GROQ_DEFAULT_MODEL
    assert info["multimodal"] is True


def test_detect_groq_usa_otro_multimodal_si_no_esta_el_conocido(monkeypatch):
    payload = {"data": [
        {"id": "openai/gpt-oss-120b"},
    ]}
    monkeypatch.setattr(providers.requests, "get", lambda *a, **k: _Resp(payload))

    info = providers._detect_groq_model("KEY")
    # Sin el modelo conocido, cae al default
    assert info["model"] == providers.GROQ_DEFAULT_MODEL


def test_detect_groq_default_si_falla_la_red(monkeypatch):
    def boom(*a, **k):
        raise Exception("sin red")
    monkeypatch.setattr(providers.requests, "get", boom)

    info = providers._detect_groq_model("KEY")
    assert info["model"] == providers.GROQ_DEFAULT_MODEL
    assert info["multimodal"] is True


def test_detect_gemini_catalogo_grande(monkeypatch):
    # Mezcla realista: embeddings, imagen, tts, varias versiones de flash/pro.
    payload = {"models": [
        {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
        {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
        {"name": "models/imagen-3.0-generate-002", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-1.5-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-3.5-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-2.0-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/aqa", "supportedGenerationMethods": ["generateAnswer"]},
    ]}
    monkeypatch.setattr(providers.requests, "get", lambda *a, **k: _Resp(payload))

    info = providers._detect_gemini_model("KEY")
    assert info["model"] == "gemini-3.5-flash"   # flash más nuevo
    assert info["multimodal"] is True


# ----------------------------- Fallback multimodal -----------------------------

def test_call_provider_saltea_modelo_no_multimodal(monkeypatch):
    monkeypatch.setattr(providers.config_manager, "get",
                        lambda k, d=None: "KEY" if k.endswith("_API_KEY") else d)
    monkeypatch.setattr(providers, "_resolve_model",
                        lambda prov, key: {"model": "solo-texto", "name": "N", "multimodal": False})
    # Con imagen requerida, un modelo solo-texto debe lanzar (para saltearse).
    with pytest.raises(Exception):
        providers._call_provider("nvidia", "q", "BASE64", needs_image=True)


def test_fallback_sticky_fija_proveedor(monkeypatch):
    monkeypatch.setattr(providers, "inject_context_if_needed", lambda q, m: q)

    def fake_call(prov, question, image, needs_image):
        if prov == "gemini":
            raise Exception("gemini caído")
        if prov == "groq":
            return "respuesta", "Groq (qwen/qwen3.6-27b)"
        raise Exception("nvidia tampoco")

    monkeypatch.setattr(providers, "_call_provider", fake_call)

    text, label = providers.process_question("q", "BASE64", "gemini", False)
    assert text == "respuesta"
    assert label.startswith("Fallback")
    # Se queda fijado en el proveedor que funcionó.
    assert providers.config_manager.get("preferredProvider") == "groq"


def test_preferido_ok_no_marca_fallback(monkeypatch):
    monkeypatch.setattr(providers, "inject_context_if_needed", lambda q, m: q)

    def fake_call(prov, question, image, needs_image):
        if prov == "gemini":
            return "ok", "Gemini (gemini-3.5-flash)"
        raise Exception("no debería llegar")

    monkeypatch.setattr(providers, "_call_provider", fake_call)

    text, label = providers.process_question("q", "BASE64", "gemini", False)
    assert text == "ok"
    assert not label.startswith("Fallback")


def test_todos_los_proveedores_fallan(monkeypatch):
    monkeypatch.setattr(providers, "inject_context_if_needed", lambda q, m: q)

    def fake_call(prov, question, image, needs_image):
        raise Exception(f"{prov} boom")

    monkeypatch.setattr(providers, "_call_provider", fake_call)

    with pytest.raises(Exception):
        providers.process_question("q", "BASE64", "gemini", False)


# ------------------- Verificación (texto + imagen) y cache de 1 semana -------------------

def _fake_ask(answers):
    """answers: {(model, con_imagen): texto | Exception}"""
    def fake(provider, key, model, question, b64, timeout, max_tokens=500):
        r = answers[(model, bool(b64))]
        if isinstance(r, Exception):
            raise r
        return r
    return fake


def test_probe_distingue_texto_e_imagen(monkeypatch):
    monkeypatch.setattr(providers, "_ask_raw", _fake_ask({
        ("a", False): "OK", ("a", True): "Rojo",
        ("b", False): "OK", ("b", True): "no puedo ver imágenes",
        ("c", False): Exception("404"), }))
    assert providers._probe_model("groq", "K", "a") == (True, True)
    assert providers._probe_model("groq", "K", "b") == (True, False)
    assert providers._probe_model("groq", "K", "c") == (False, False)


def test_detect_verified_elige_primer_multimodal_en_orden(monkeypatch):
    monkeypatch.setattr(providers, "_candidates", lambda p, k: ["roto", "solo-texto", "bueno", "otro"])
    monkeypatch.setattr(providers, "_ask_raw", _fake_ask({
        ("roto", False): Exception("404"),
        ("solo-texto", False): "OK", ("solo-texto", True): "?",
        ("bueno", False): "OK", ("bueno", True): "red",
        ("otro", False): "OK", ("otro", True): "rojo"}))
    info = providers._detect_verified("groq", "K")
    assert info["model"] == "bueno" and info["multimodal"] and info["verified"]


def test_detect_verified_sin_multimodal_usa_solo_texto(monkeypatch):
    monkeypatch.setattr(providers, "_candidates", lambda p, k: ["roto", "txt"])
    monkeypatch.setattr(providers, "_ask_raw", _fake_ask({
        ("roto", False): Exception("x"), ("txt", False): "OK", ("txt", True): "nada"}))
    info = providers._detect_verified("groq", "K")
    assert info["model"] == "txt" and not info["multimodal"] and info["verified"]


def test_detect_verified_cae_a_heuristica_si_no_hay_red(monkeypatch):
    def boom(p, k):
        raise Exception("sin red")
    monkeypatch.setattr(providers, "_candidates", boom)
    monkeypatch.setattr(providers.requests, "get", lambda *a, **k: (_ for _ in ()).throw(Exception("sin red")))
    info = providers._detect_verified("groq", "K")
    assert info["model"] == providers.GROQ_DEFAULT_MODEL and info["verified"] is False


def test_cache_disco_evita_redetectar_y_no_guarda_lo_no_verificado(monkeypatch):
    calls = []
    def detect(p, k):
        calls.append(p)
        return {"model": "m1", "name": "G (m1)", "multimodal": True, "verified": True}
    monkeypatch.setattr(providers, "_detect_verified", detect)
    assert providers._resolve_model("groq", "K")["model"] == "m1"
    providers._model_cache.clear()                       # simula reiniciar la app
    assert providers._resolve_model("groq", "K")["model"] == "m1"
    assert calls == ["groq"]                             # la 2da salió del disco
    providers._model_cache.clear()
    assert len(calls) == 1 and providers._resolve_model("groq", "OTRA-KEY") and len(calls) == 2  # otra key -> redetecta


def test_cache_no_persiste_heuristica_sin_verificar(monkeypatch):
    monkeypatch.setattr(providers, "_detect_verified",
                        lambda p, k: {"model": "h", "name": "h", "multimodal": True, "verified": False})
    providers._resolve_model("groq", "K")
    assert providers._disk_get("groq", "K") is None


def test_cache_vencido_usa_el_viejo_y_refresca_en_segundo_plano(monkeypatch):
    providers._disk_set("groq", "K", {"model": "viejo", "name": "v", "multimodal": True, "verified": True})
    providers.config_manager.config[providers.MODEL_CACHE_KEY]["groq"]["ts"] -= providers.MODEL_CACHE_TTL + 5
    refreshed = []
    monkeypatch.setattr(providers, "_refresh_async", lambda p, k: refreshed.append(p))
    monkeypatch.setattr(providers, "_detect_verified", lambda p, k: pytest.fail("no debe bloquear"))
    assert providers._resolve_model("groq", "K")["model"] == "viejo"
    assert refreshed == ["groq"]


def test_error_de_modelo_invalida_y_reintenta(monkeypatch):
    monkeypatch.setattr(providers.config_manager, "get",
                        lambda k, d=None: "KEY" if k.endswith("_API_KEY") else providers.config_manager.config.get(k, d))
    infos = iter([{"model": "viejo", "name": "v", "multimodal": True},
                  {"model": "nuevo", "name": "n", "multimodal": True}])
    monkeypatch.setattr(providers, "_resolve_model", lambda p, k: next(infos))
    monkeypatch.setattr(providers, "_invalidate_model_cache", lambda p: None)

    def ask(url, model, *a, **k):
        if model == "viejo":
            raise Exception("The model `viejo` does not exist")
        return "ok"
    monkeypatch.setattr(providers, "_ask_openai_compatible", ask)
    assert providers._call_provider("groq", "q", "img", True) == ("ok", "n")


def test_error_de_red_no_invalida_cache(monkeypatch):
    assert not providers._is_model_error(Exception("Read timed out"))
    assert not providers._is_model_error(Exception("Rate limit reached (429)"))
    assert providers._is_model_error(Exception("Gemini Error: 404"))
    assert providers._is_model_error(Exception("Status 404"))
