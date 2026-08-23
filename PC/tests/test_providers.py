"""Tests del router de proveedores: detección de modelo y fallback multimodal."""
import pytest

from core import providers


@pytest.fixture(autouse=True)
def _clear_model_cache():
    providers._model_cache.clear()
    yield
    providers._model_cache.clear()


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
        {"id": "qwen/qwen3.6-27b"},
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
