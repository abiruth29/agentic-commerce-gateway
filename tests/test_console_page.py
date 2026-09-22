"""Tests for the page the hosted link opens.

Not a rendering test — there is no browser here. These check the contract
between the page and the app: that the files are served, that the page asks
for the endpoints that exist, and above all that the caveats cannot be
detached from the numbers they qualify.

That last one is the reason this file exists. The hosted deployment runs with
Layer 2 stubbed, so the page will show injection cases as ALLOW. A reviewer
seeing that without the caption would reasonably conclude the gateway is
broken, when what is actually true is that the model is not running. The
caption is therefore served by the app, not written into the HTML by hand
where it could drift out of step with the deployment it describes.
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acg.main import WEB_DIR

PAGE = (Path(WEB_DIR) / "index.html").read_text(encoding="utf-8")
SCRIPT = (Path(WEB_DIR) / "console.js").read_text(encoding="utf-8")


def _without_comments(source: str) -> str:
    """The script with comments removed.

    Scanning the raw text for a dangerous sink finds the comment that promises
    not to use it, which is how the first version of these tests failed: it
    matched the sentence "never innerHTML" and reported the page unsafe.
    """
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


CODE = _without_comments(SCRIPT)
RESULTS = json.loads((Path(WEB_DIR) / "results.json").read_text(encoding="utf-8"))


class TestTheFilesAreServed:
    @pytest.mark.parametrize(
        "path", ["/", "/index.html", "/console.js", "/results.json"]
    )
    def test_the_page_and_its_assets_load(self, client: TestClient, path: str) -> None:
        assert client.get(path).status_code == 200

    def test_the_root_serves_the_page(self, client: TestClient) -> None:
        assert "Agentic Commerce Gateway" in client.get("/").text

    def test_the_results_file_is_valid_json(self, client: TestClient) -> None:
        assert client.get("/results.json").json()["version"] == 1


class TestThePageAsksForEndpointsThatExist:
    def test_every_fetched_path_is_routable(self, client: TestClient) -> None:
        # A page calling an endpoint that was renamed fails only in a browser,
        # which no test here opens. This catches it in the suite instead.
        paths = sorted(set(re.findall(r'(?:load|fetch)\(\s*"(/[^"]+)"', CODE)))
        assert paths, "no fetched paths found; the scan is not working"

        for path in paths:
            if path == "/api/evaluate":
                response = client.post(path, json={})
            else:
                response = client.get(path)
            assert response.status_code < 400, f"{path} -> {response.status_code}"

    def test_the_script_is_actually_referenced(self) -> None:
        assert 'src="/console.js"' in PAGE

    def test_the_page_reads_the_published_results(self) -> None:
        assert '"/results.json"' in SCRIPT


class TestTheCaveatsCannotBeDetached:
    def test_the_page_has_somewhere_to_put_the_mock_warning(self) -> None:
        assert 'id="mock-banner"' in PAGE
        assert 'id="mode"' in PAGE

    def test_the_mock_warning_is_driven_by_the_results_file(self) -> None:
        # Not hand-written into the HTML, where it could survive a real run
        # or go missing from a mock one.
        assert "semantic_numbers_are_reportable" in SCRIPT

    def test_the_mode_caption_is_driven_by_the_app(self) -> None:
        assert "renderMode" in SCRIPT
        assert '"/api/rules"' in SCRIPT

    def test_the_current_results_carry_the_flag(self) -> None:
        assert RESULTS["semantic_numbers_are_reportable"] is False

    def test_the_app_reports_a_stubbed_layer_2(self, client: TestClient) -> None:
        screener = client.get("/api/rules").json()["screener"]
        assert screener["is_mock"] is True
        assert "GEMINI_API_KEY" in screener["note"]


class TestTheLimitationsAreOnThePage:
    @pytest.mark.parametrize(
        "phrase",
        [
            "not built",
            "cannot be expressed by the corpus at all",
            "unmeasured, not zero",
            "trusts the merchant",
            "I wrote it",
            "no cryptography here",
        ],
    )
    def test_each_known_gap_is_stated(self, phrase: str) -> None:
        # Stated before a reviewer finds them, which is the whole posture of
        # the page. A limitation that only lives in the README is not stated.
        assert phrase in PAGE


class TestTheProtocolPositioning:
    """The page must not repeat the launch-day framing of AP2.

    Most write-ups still describe an Intent / Cart / Payment mandate triple.
    The v0.2 specification defines a Checkout Mandate and a Payment Mandate,
    and citing the superseded names to someone who has read the spec is the
    cheapest possible way to lose their confidence.
    """

    def test_the_page_names_the_mandates_the_spec_defines(self) -> None:
        assert "Checkout Mandate" in PAGE
        assert "Payment Mandate" in PAGE

    def test_the_page_does_not_repeat_the_superseded_names(self) -> None:
        assert not re.search(r"Intent Mandate", PAGE)
        assert not re.search(r"Cart Mandate", PAGE)

    def test_the_page_quotes_ap2_with_its_source(self) -> None:
        assert "potential attackers" in PAGE
        assert "security_and_privacy_considerations.md" in PAGE

    def test_the_page_points_at_the_cited_comparison(self) -> None:
        assert "docs/protocols.md" in PAGE

    def test_the_comparison_document_exists(self) -> None:
        doc = Path(WEB_DIR).parent / "docs" / "protocols.md"
        assert doc.exists()
        assert "Checkout Mandate" in doc.read_text(encoding="utf-8")


class TestUntrustedTextIsNeverMarkup:
    def test_the_script_does_not_use_innerhtml(self) -> None:
        # Half of what this page renders is attack text written to be
        # interpreted by whatever reads it. Rendering it as markup would be
        # the same mistake the gateway exists to stop, made on the page that
        # claims to stop it.
        assert not re.search(r"\.innerHTML\s*=", CODE)
        assert not re.search(r"\.outerHTML\s*=", CODE)
        assert "insertAdjacentHTML" not in CODE
        assert "document.write" not in CODE

    def test_the_script_does_not_evaluate_strings(self) -> None:
        assert not re.search(r"\beval\s*\(", CODE)
        assert "new Function" not in CODE

    def test_rendering_goes_through_one_helper(self) -> None:
        assert "textContent" in SCRIPT


class TestThePageAgreesWithTheResultsItShows:
    def test_the_classes_the_page_lists_are_the_classes_measured(self) -> None:
        labels = CODE.split("CLASS_ORDER")[0]
        listed = set(re.findall(r"\b([OI][1-4]):", labels))
        measured = set(RESULTS["configs"]["C1"]["asr_by_class"])

        assert listed == measured

    def test_the_corpus_size_on_the_page_matches_the_run(self) -> None:
        assert RESULTS["configs"]["C1"]["asr_overall"]["denominator"] == 120
        assert "120 attacks" in PAGE or "120 attacks" in SCRIPT

    def test_the_benign_count_on_the_page_matches_the_run(self) -> None:
        assert RESULTS["configs"]["C1"]["false_block_rate"]["denominator"] == 60
        assert "60 benign flows" in SCRIPT or "60 benign flows" in PAGE
