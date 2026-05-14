import os
import requests
import json

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-268a499837ea4c84ac863c5c972fda14")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are a professional translator. Translate the following text from any language "
    "into Simplified Chinese. Only output the translation, no explanations, no notes. "
    "Keep the same tone and meaning as the original."
)


def translate_to_chinese(text):
    if not text.strip():
        return ""

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
    }

    resp = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()
