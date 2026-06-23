import os
import uuid

import requests


AZURE_TRANSLATOR_ENDPOINT = os.environ.get(
    "AZURE_TRANSLATOR_ENDPOINT",
    "https://api.cognitive.microsofttranslator.com",
).rstrip("/")
AZURE_TRANSLATOR_KEY = os.environ.get("AZURE_TRANSLATOR_KEY")
AZURE_TRANSLATOR_REGION = os.environ.get("AZURE_TRANSLATOR_REGION")
TRANSLATION_PROVIDER = os.environ.get("TRANSLATION_PROVIDER", "azure").strip().lower()
TRANSLATION_FALLBACK_PROVIDER = os.environ.get("TRANSLATION_FALLBACK_PROVIDER", "").strip().lower()


class TranslationError(RuntimeError):
    pass


def translate_to_chinese(text):
    text = text.strip()
    if not text:
        return ""

    errors = []
    providers = [TRANSLATION_PROVIDER]
    if TRANSLATION_FALLBACK_PROVIDER and TRANSLATION_FALLBACK_PROVIDER not in providers:
        providers.append(TRANSLATION_FALLBACK_PROVIDER)

    for provider in providers:
        try:
            if provider == "azure":
                return translate_with_azure(text)
            if provider in ("google_free", "google-free", "google"):
                return translate_with_google_free(text)
            errors.append(f"{provider}: unsupported translation provider")
        except Exception as e:
            errors.append(f"{provider}: {e}")

    raise TranslationError("; ".join(errors))


def translate_with_azure(text):
    if not AZURE_TRANSLATOR_KEY:
        raise TranslationError("AZURE_TRANSLATOR_KEY is not configured")

    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_TRANSLATOR_KEY,
        "Content-Type": "application/json",
        "X-ClientTraceId": str(uuid.uuid4()),
    }
    if AZURE_TRANSLATOR_REGION:
        headers["Ocp-Apim-Subscription-Region"] = AZURE_TRANSLATOR_REGION

    resp = requests.post(
        f"{AZURE_TRANSLATOR_ENDPOINT}/translate",
        params={"api-version": "3.0", "to": "zh-Hans"},
        headers=headers,
        json=[{"text": text}],
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data[0]["translations"][0]["text"].strip()


def translate_with_google_free(text):
    resp = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={
            "client": "gtx",
            "sl": "auto",
            "tl": "zh-CN",
            "dt": "t",
            "q": text,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(part[0] for part in data[0] if part and part[0]).strip()
