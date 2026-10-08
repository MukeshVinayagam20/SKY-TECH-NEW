"""One place that talks to the AI model (Gemini cloud or Ollama local).

.env settings:
    AI_PROVIDER=ollama            # who READS the image: ollama or gemini
    TEXT_PROVIDER=gemini          # who WRITES/TRANSLATES the report (optional, defaults to AI_PROVIDER)
    OLLAMA_MODEL=qwen2.5vl:7b     # vision model for reading documents
    OLLAMA_TEXT_MODEL=            # optional separate text model (defaults to OLLAMA_MODEL)
    GEMINI_API_KEY=...
    GEMINI_MODELS=gemini-flash-latest,gemini-flash-lite-latest
    USE_OLLAMA_FALLBACK=true      # if Gemini is busy/unreachable, use Ollama
"""
import json, os, time
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()
PROVIDER = os.getenv("AI_PROVIDER", "ollama").lower()
TEXT_PROVIDER = (os.getenv("TEXT_PROVIDER") or PROVIDER).lower()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5vl:7b")
OLLAMA_TEXT_MODEL = os.getenv("OLLAMA_TEXT_MODEL") or OLLAMA_MODEL
USE_OLLAMA_FALLBACK = os.getenv("USE_OLLAMA_FALLBACK", "true").lower() == "true"
GEMINI_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_MODELS", "gemini-flash-latest,gemini-flash-lite-latest").split(",") if m.strip()]


class AIBusyError(Exception):
    pass


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


def _call_ollama(prompt: str, images: list[bytes], schema: dict, model: str) -> str:
    import ollama
    message = {"role": "user", "content": prompt}
    if images:
        message["images"] = images
    t0 = time.time()
    resp = ollama.chat(
        model=model,
        messages=[message],
        format=schema,                       # forces JSON in this shape
        options={"temperature": 0, "num_ctx": 8192},
        keep_alive="30m",                    # keep the model in memory between calls
    )
    print(f"[llm] used Ollama model: {model} ({time.time() - t0:.0f}s)")
    return resp["message"]["content"]


def _clean_json(text: str) -> str:
    text = text.strip().removeprefix("```json").removesuffix("```").strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end != -1 else text


def call_llm_json(prompt: str, model_cls: type[BaseModel],
                  images: list[bytes] | None = None, task: str = "vision") -> BaseModel:
    """Send prompt (+ optional images) and get back a validated Pydantic object.
    task="vision" for reading documents, task="text" for writing/translating."""
    images = images or []
    schema = model_cls.model_json_schema()
    full_prompt = (prompt + "\n\nReturn ONLY valid JSON matching this schema, no other text:\n"
                   + json.dumps(schema))
    provider = PROVIDER if task == "vision" else TEXT_PROVIDER
    ollama_model = OLLAMA_MODEL if task == "vision" else OLLAMA_TEXT_MODEL

    if provider == "gemini":
        try:
            text = _call_gemini(full_prompt, images)
        except Exception as e:
            if not USE_OLLAMA_FALLBACK or isinstance(e, ValueError):
                raise
            print(f"[llm] Gemini failed ({e}) -> falling back to Ollama")
            text = _call_ollama(full_prompt, images, schema, OLLAMA_MODEL if images else ollama_model)
    else:
        text = _call_ollama(full_prompt, images, schema, ollama_model)

    return model_cls.model_validate_json(_clean_json(text))