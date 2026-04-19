"""Tests sans Groq / gspread — uniquement pure_checks."""
from __future__ import annotations

import pytest

from pure_checks import host_matches_any_suffix, parse_json_object, url_host_matches_suffix_set

PAPPERS = frozenset({"pappers.fr"})
SOCIETE = frozenset({"societe.com"})
MIX = frozenset({"pappers.fr", "societe.com"})


class TestHostMatchesAnySuffix:
    def test_exact(self):
        assert host_matches_any_suffix("pappers.fr", PAPPERS)
        assert not host_matches_any_suffix("autre.fr", PAPPERS)

    def test_subdomain(self):
        assert host_matches_any_suffix("dupont.pappers.fr", PAPPERS)
        assert host_matches_any_suffix("www.pappers.fr", PAPPERS)


class TestUrlHostMatchesSuffixSet:
    def test_misociete_not_false_positive(self):
        """'societe.com' ne doit pas matcher en sous-chaîne dans le host."""
        assert not url_host_matches_suffix_set("https://misociete.com/", SOCIETE)
        assert not url_host_matches_suffix_set("https://www.misociete.com/contact", SOCIETE)

    def test_real_societe_com(self):
        assert url_host_matches_suffix_set("https://www.societe.com/foo", SOCIETE)
        assert url_host_matches_suffix_set("https://sub.societe.com/", SOCIETE)

    def test_pappers_url(self):
        assert url_host_matches_suffix_set("https://www.pappers.fr/entreprise/123", PAPPERS)

    def test_non_http_rejected(self):
        assert not url_host_matches_suffix_set("ftp://pappers.fr/x", PAPPERS)
        assert not url_host_matches_suffix_set("", MIX)
        assert not url_host_matches_suffix_set("not-a-url", MIX)


class TestParseJsonObject:
    def test_raw_object(self):
        assert parse_json_object('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}

    def test_fenced_json(self):
        text = 'Voici le JSON:\n```json\n{"urls": ["https://a.com"]}\n```'
        assert parse_json_object(text) == {"urls": ["https://a.com"]}

    def test_non_dict_returns_none(self):
        assert parse_json_object("[1,2,3]") is None

    def test_brace_fallback(self):
        text = 'Prefix {"official_website": null, "emails_found": []} suffix'
        assert parse_json_object(text) == {"official_website": None, "emails_found": []}
