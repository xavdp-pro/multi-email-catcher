"""
Tests qui importent agent (nécessite groq, gspread, bs4, etc.).
Ignorés automatiquement si les dépendances ne sont pas installées.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("groq")
pytest.importorskip("gspread")
pytest.importorskip("bs4", reason="beautifulsoup4")

os.environ.setdefault("GROQ_API_KEY", "gsk_test_dummy_key_for_pytest_only")

import agent as ag  # noqa: E402


class TestExtractEmailsDeobfuscate:
    def test_bracket_at_in_mentions_legales(self):
        html = "<p>E-mail : contact[at]arbrenciel.com</p>"
        out = ag.extract_emails(html, "E-mail : contact[at]arbrenciel.com", site_url="https://www.arbrenciel.com")
        assert out and "contact@arbrenciel.com" in out

    def test_at_and_dot_spelled_out(self):
        html = "<p>foo AT bar DOT com</p>"
        out = ag.extract_emails(html, "foo AT bar DOT com", site_url="https://bar.com")
        assert out and "foo@bar.com" in out


class TestCleanEmails:
    def test_rejects_annuaire_host(self):
        assert ag._clean_emails(["contact@dupont.pappers.fr"]) == []

    def test_notexample_not_rejected_by_example_placeholder(self):
        """Régression : ne pas rejeter notexample.com comme example.com."""
        out = ag._clean_emails(["hello@notexample.com"])
        assert "hello@notexample.com" in out

    def test_rejects_placeholder_host(self):
        assert ag._clean_emails(["x@example.com"]) == []

    def test_rejects_legal_publisher_host(self):
        assert ag._clean_emails(["contact@lextenso.fr"]) == []
        assert ag._clean_emails(["a@actu-juridique.fr"]) == []

    def test_rejects_placeholder_full_address(self):
        assert ag._clean_emails(["votreadresse@email.com"]) == []

    def test_disallowed_official_announces_lefigaro(self):
        assert ag._is_disallowed_official_site_url(
            "https://annonces-legales.lefigaro.fr/annonces-legales/foo/",
        )

    def test_tier1_serp_not_homonym(self):
        """BRUNIER + site Honeywell : @brunier-bois.com ne doit pas passer le filtre SERP."""
        site = "https://www.honeywellsafety.com"
        em = "info@brunier-bois.com"
        assert ag._email_site_alignment_tier(em, site, "BRUNIER") == 1
        assert not ag._tier1_email_plausible_for_site(em, site)

    def test_tier1_same_group_ok(self):
        site = "https://www.samsic.fr/agences/proprete-marne-la-vallee"
        assert ag._tier1_email_plausible_for_site("contact@samsic-facility.fr", site)

    def test_filter_serp_fallback_keeps_site_domain(self):
        site = "https://client.fr"
        out = ag._filter_emails_for_serp_fallback(
            ["a@gmail.com", "x@client.fr"],
            site,
            "CLIENT SAS",
        )
        assert out == ["x@client.fr"]

    def test_rank_prefers_site_domain(self):
        site = "https://www.dupont-isolation.fr"
        out = ag._clean_emails(
            ["a@gmail.com", "z@dupont-isolation.fr", "b@dupont-isolation.fr"],
            site_url=site,
            company_name="DUPONT ISOLATION",
        )
        assert out[0] == "b@dupont-isolation.fr"
        assert out[1] == "z@dupont-isolation.fr"
        assert out[-1] == "a@gmail.com"


class TestPickHeuristicSkipsDirectoryHosts:
    def test_infobel_not_chosen_as_official(self):
        rows = [
            {
                "url": "https://www.infobel.com/fr/france/infoplus_telemedias/x.aspx",
                "title": "INFOPLUS TELEMEDIAS — Infobel",
                "snippet": "",
            },
            {
                "url": "https://infoplus-media.com/",
                "title": "Infoplus médias accueil",
                "snippet": "",
            },
        ]
        picked = ag._pick_first_result_heuristic("INFOPLUS TELEMEDIAS", rows)
        assert picked and "infobel.com" not in picked.lower()

    def test_lagazette_not_chosen_as_official(self):
        rows = [
            {
                "url": "https://entreprises.lagazettefrance.fr/entreprise/arc-en-ciel-sud-ouest-845181296",
                "title": "ARC EN CIEL SUD OUEST - fiche entreprise",
                "snippet": "",
            },
            {
                "url": "https://arc-en-ciel-sud-ouest.example.org",
                "title": "Site ARC EN CIEL SUD OUEST",
                "snippet": "",
            },
        ]
        picked = ag._pick_first_result_heuristic("ARC EN CIEL SUD OUEST", rows)
        assert picked and "lagazettefrance" not in picked.lower()

    def test_generic_tokens_not_enough_for_media_site(self):
        rows = [
            {
                "url": "https://www.sudouest.fr/",
                "title": "Sud Ouest - actualités",
                "snippet": "",
            },
            {
                "url": "https://www.example.com/",
                "title": "Site web",
                "snippet": "",
            },
        ]
        picked = ag._pick_first_result_heuristic("ARC EN CIEL SUD OUEST", rows)
        assert picked is None

    def test_net1901_not_chosen_as_official(self):
        rows = [
            {
                "url": "https://www.net1901.org/entreprise/INFOPLUS-TELEMEDIAS,40472235700013.html",
                "title": "INFOPLUS TELEMEDIAS - net1901",
                "snippet": "",
            },
            {
                "url": "https://www.infoplus-media.com/",
                "title": "Infoplus media",
                "snippet": "",
            },
        ]
        picked = ag._pick_first_result_heuristic("INFOPLUS TELEMEDIAS", rows)
        assert picked and "net1901.org" not in picked.lower()


class TestSerpSkipDirectories:
    def test_iter_serp_urls_skips_annuaires(self):
        rows = [
            {"url": "https://www.pappers.fr/entreprise/x"},
            {"url": "https://www.societe.com/a.html"},
            {"url": "https://client-reel.fr/contact"},
            {"url": "https://annuaire-entreprises.data.gouv.fr/y"},
        ]
        out = list(ag._iter_serp_urls_skip_directories(rows, max_pages=4))
        assert out == ["https://client-reel.fr/contact"]


class TestSameRegistrableDomain:
    def test_www_vs_bare(self):
        assert ag._same_registrable_domain(
            "https://www.example.com/",
            "https://example.com/contact",
        )
        assert ag._same_registrable_domain(
            "https://example.com/",
            "https://www.example.com/a",
        )

    def test_different_sites(self):
        assert not ag._same_registrable_domain("https://a.com", "https://b.com")
