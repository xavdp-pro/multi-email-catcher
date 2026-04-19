"""
Logique pure (URL / hôte / JSON) — importable sans Groq ni daemon.
Utilisée par agent.py et couverte par les tests unitaires.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse


def host_matches_any_suffix(host: str, suffixes: frozenset[str]) -> bool:
    h = host.lower().strip().rstrip(".")
    if not h:
        return False
    for suf in suffixes:
        if h == suf or h.endswith("." + suf):
            return True
    return False


def url_host_matches_suffix_set(url: str, suffixes: frozenset[str]) -> bool:
    """True si le netloc de l’URL (sans www) est ou finit par un des suffixes."""
    if not url or not isinstance(url, str) or not url.strip().lower().startswith("http"):
        return False
    try:
        host = urlparse(url.strip()).netloc.lower().removeprefix("www.").rstrip(".")
    except Exception:
        return False
    if not host:
        return False
    return host_matches_any_suffix(host, suffixes)


def parse_json_object(text: str) -> dict | None:
    """Extraction tolérante d’un objet JSON depuis une réponse LLM."""
    text = text.strip()
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if m:
            text = m.group(1).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None
