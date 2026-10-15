"""One place that talks to the AI model.

LOCAL  (your computer) -> local Ollama  + qwen2.5vl:7b
SERVER (Render)        -> Ollama Cloud  + gemma4:31b

The app detects the server automatically (Render sets RENDER=true).
You can also force it with APP_ENV=server or APP_ENV=local.

Settings (.env locally, Render -> Environment on the server):
    OLLAMA_API_KEY=               # REQUIRED on the server (Ollama Cloud key)
    APP_ENV=                      # optional: server / local (auto-detected if empty)
    OLLAMA_MODEL=                 # optional override of the vision model
    OLLAMA_TEXT_MODEL=            # optional separate text model (defaults to OLLAMA_MODEL)
    OLLAMA_HOST=                  # optional override of the Ollama address

    # Optional - Gemini support is still here if you ever want it:
    AI_PROVIDER=ollama            # who READS the image: ollama or gemini
    TEXT_PROVIDER=                # who WRITES/TRANSLATES (defaults to AI_PROVIDER)
    GEMINI_API_KEY=
    GEMINI_MODELS=gemini-flash-latest,gemini-flash-lite-latest
    USE_OLLAMA_FALLBACK=true      # if Gemini fails, use Ollama
"""
import json, os, re, time
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv()

# ---------------- Where are we running? ----------------
_app_env = os.getenv("APP_ENV", "").strip().lower()
if _app_env in ("server", "local"):
    IS_SERVER = _app_env == "server"
else:
    IS_SERVER = os.getenv("RENDER", "").lower() == "true"    # Render sets this automatically

LOCAL_DEFAULTS = {"host": "http://localhost:11434", "model": "qwen2.5vl:7b"}
SERVER_DEFAULTS = {"host": "https://ollama.com", "model": "gemma4:31b"}
_defaults = SERVER_DEFAULTS if IS_SERVER else LOCAL_DEFAULTS

# ---------------- Settings ----------------
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY") or None
OLLAMA_HOST = os.getenv("OLLAMA_HOST") or _defaults["host"]
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL") or _defaults["model"]
OLLAMA_TEXT_MODEL = os.getenv("OLLAMA_TEXT_MODEL") or OLLAMA_MODEL
USING_OLLAMA_CLOUD = "ollama.com" in OLLAMA_HOST

PROVIDER = os.getenv("AI_PROVIDER", "ollama").lower()
TEXT_PROVIDER = (os.getenv("TEXT_PROVIDER") or PROVIDER).lower()
USE_OLLAMA_FALLBACK = os.getenv("USE_OLLAMA_FALLBACK", "true").lower() == "true"
GEMINI_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_MODELS", "gemini-flash-latest,gemini-flash-lite-latest").split(",") if m.strip()]

print(f"[llm] running on: {'SERVER' if IS_SERVER else 'LOCAL'} | provider={PROVIDER}/{TEXT_PROVIDER} | "
      f"ollama_host={OLLAMA_HOST} | vision_model={OLLAMA_MODEL} | text_model={OLLAMA_TEXT_MODEL}")

_ollama_client = None


class AIBusyError(Exception):
    pass


def _get_ollama_client():
    global _ollama_client
    if _ollama_client is None:
        if USING_OLLAMA_CLOUD and not OLLAMA_API_KEY:
            raise RuntimeError("OLLAMA_API_KEY is not set. Add it in Render -> Environment "
                               "(needed for Ollama Cloud / Gemma 4).")
        from ollama import Client
        headers = {"Authorization": f"Bearer {OLLAMA_API_KEY}"} if OLLAMA_API_KEY else None
        _ollama_client = Client(host=OLLAMA_HOST, headers=headers, timeout=300)
    return _ollama_client


# ---------------- Gemini (optional) ----------------
def _call_gemini(prompt: str, images: list[bytes]) -> str:
    from google import genai
    from google.genai import types, errors
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    contents = [types.Part.from_bytes(data=img, mime_type="image/jpeg") for img in images]
    contents.append(prompt)

    last_error = None
    for model in GEMINI_MODELS:
        for attempt in range(3):
            try:
                resp = client.models.generate_content(
                    model=model, contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json", temperature=0),
                )
                print(f"[llm] used Gemini model: {model}")
                return resp.text
            except errors.ServerError as e:          # 503 busy
                last_error = e
                time.sleep(2 * (attempt + 1))
            except errors.ClientError as e:
                last_error = e
                if e.code in (404, 429):             # model missing / rate limit -> next model
                    break
                raise
    raise AIBusyError(f"Gemini models are busy. ({last_error})")


# ---------------- Ollama (local qwen / cloud gemma) ----------------
def _call_ollama(prompt: str, images: list[bytes], schema: dict, model: str) -> str:
    message = {"role": "user", "content": prompt}
    if images:
        message["images"] = images
    kwargs = dict(
        model=model,
        messages=[message],
        format=schema,                       # forces JSON in this shape
        # num_predict caps runaway output: small local models can loop on one line
        # (seen with qwen2.5vl on Tamil) until they hit the timeout.
        options={"temperature": 0, "num_ctx": 8192, "num_predict": 3000},
    )
    if not USING_OLLAMA_CLOUD:
        kwargs["keep_alive"] = "30m"         # local only: keep the model in memory between calls

    client = _get_ollama_client()
    t0 = time.time()
    if USING_OLLAMA_CLOUD:
        # Gemma 4 is a "thinking" model - turn thinking off: faster, JSON comes straight back
        try:
            resp = client.chat(think=False, **kwargs)
        except TypeError:                    # older ollama library without "think"
            resp = client.chat(**kwargs)
        except Exception as e:
            if "think" in str(e).lower():    # model does not accept the think option
                resp = client.chat(**kwargs)
            else:
                raise
    else:
        resp = client.chat(**kwargs)
    where = "Ollama Cloud" if USING_OLLAMA_CLOUD else "local Ollama"
    print(f"[llm] used {where} model: {model} ({time.time() - t0:.0f}s)")
    return resp["message"]["content"]


def _clean_json(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end != -1 else text


def _ask(full_prompt: str, images: list[bytes], schema: dict, task: str) -> str:
    provider = PROVIDER if task == "vision" else TEXT_PROVIDER
    ollama_model = OLLAMA_MODEL if task == "vision" else OLLAMA_TEXT_MODEL

    if provider == "gemini":
        try:
            return _call_gemini(full_prompt, images)
        except Exception as e:
            if not USE_OLLAMA_FALLBACK or isinstance(e, ValueError):
                raise
            print(f"[llm] Gemini failed ({e}) -> falling back to Ollama")
            return _call_ollama(full_prompt, images, schema,
                                OLLAMA_MODEL if images else ollama_model)
    return _call_ollama(full_prompt, images, schema, ollama_model)


def call_llm_json(prompt: str, model_cls: type[BaseModel],
                  images: list[bytes] | None = None, task: str = "vision") -> BaseModel:
    """Send prompt (+ optional images) and get back a validated Pydantic object.
    task="vision" for reading documents, task="text" for writing/translating."""
    images = images or []
    schema = model_cls.model_json_schema()
    full_prompt = (prompt + "\n\nReturn ONLY valid JSON matching this schema, no other text:\n"
                   + json.dumps(schema))

    last_error = None
    for attempt in range(2):                 # one retry if the JSON comes back broken
        text = _ask(full_prompt, images, schema, task)
        try:
            return model_cls.model_validate_json(_clean_json(text))
        except ValidationError as e:
            last_error = e
            print(f"[llm] invalid JSON (attempt {attempt + 1}), retrying: {e}")
    raise last_error