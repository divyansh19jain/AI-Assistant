"""
Web-submission task — fill & submit a form on an external portal after approval.

🔒 **PHI EGRESS.** This sends patient answers to a third-party / government portal, so
it is deliberately gated:
  1. it only runs when a form's workflow includes a ``web_submit`` task (per-form opt-in),
  2. only after the human **approval gate** (see app/workflows/router.py), and
  3. every run is audited and its evidence recorded.

Driver selection (factory, mirroring the EMR adapter):
  - **MockWebDriver (default)** — a SAFE DRY-RUN that records *what would be submitted*
    (field count, target URL) and returns a fake confirmation, with **no network call**.
    This keeps dev/tests offline and means web_submit can never accidentally egress PHI.
  - **BrowserlessWebDriver** — a real Playwright-over-Browserless submission, selected
    ONLY when ``WEB_SUBMIT_DRIVER=browserless`` AND ``BROWSERLESS_URL`` is set. Reuses an
    existing Browserless endpoint (CDP) so no local browser is needed.

A submission **recipe** describes the target: ``{portal_url, field_selectors: {field_key:
css}, submit_selector, confirmation_selector, steps?}``. It comes from the task config or
the form pack's ``workflow.yaml`` ``web:`` block.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class WebSubmissionDriver(ABC):
    @abstractmethod
    def submit(self, recipe: dict, answers: dict) -> dict:
        """Submit ``answers`` to the portal described by ``recipe``; return evidence dict."""
        ...


class MockWebDriver(WebSubmissionDriver):
    """Dry-run driver: records what would be submitted, performs NO network call."""

    def submit(self, recipe: dict, answers: dict) -> dict:
        return {
            "driver": "mock",
            "dry_run": True,
            "portal_url": recipe.get("portal_url"),
            "submitted_field_count": len(answers or {}),
            "confirmation": "MOCK-CONFIRM",
        }


class BrowserlessWebDriver(WebSubmissionDriver):
    """Real submission via Playwright connected to a Browserless (CDP) endpoint.

    Only used when explicitly configured. Defensive throughout: any missing dependency
    or runtime error is returned as ``{"error": ...}`` so the workflow records a failed
    task rather than crashing. Evidence captures the confirmation text (and could capture
    a screenshot to the BlobStore — left as a hook).
    """

    def __init__(self, browserless_url: str):
        self._url = browserless_url

    def submit(self, recipe: dict, answers: dict) -> dict:
        portal_url = recipe.get("portal_url")
        if not portal_url:
            return {"driver": "browserless", "error": "recipe has no portal_url"}
        try:
            from playwright.sync_api import sync_playwright  # lazy: only when configured
        except Exception:
            return {"driver": "browserless", "error": "playwright not installed"}

        selectors: dict = recipe.get("field_selectors", {}) or {}
        submit_selector = recipe.get("submit_selector")
        confirmation_selector = recipe.get("confirmation_selector")
        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(self._url)
                page = browser.new_page()
                page.goto(portal_url, wait_until="domcontentloaded")
                filled = 0
                for field_key, css in selectors.items():
                    value = answers.get(field_key)
                    if value in (None, "", "__skipped__"):
                        continue
                    try:
                        page.fill(css, str(value))
                        filled += 1
                    except Exception:
                        logger.warning("web_submit: could not fill selector for %s", field_key)
                if submit_selector:
                    page.click(submit_selector)
                confirmation = ""
                if confirmation_selector:
                    try:
                        confirmation = page.inner_text(confirmation_selector, timeout=10000)
                    except Exception:
                        confirmation = ""
                browser.close()
                return {
                    "driver": "browserless",
                    "dry_run": False,
                    "portal_url": portal_url,
                    "submitted_field_count": filled,
                    "confirmation": confirmation or "submitted",
                }
        except Exception as exc:
            logger.warning("Browserless web submission failed.", exc_info=True)
            return {"driver": "browserless", "error": str(exc)}


def get_web_driver() -> WebSubmissionDriver:
    """Select the submission driver from settings. Defaults to the safe dry-run mock."""
    from app.core.config import get_settings

    settings = get_settings()
    driver = (getattr(settings, "WEB_SUBMIT_DRIVER", "mock") or "mock").lower()
    browserless = getattr(settings, "BROWSERLESS_URL", "") or ""
    if driver == "browserless" and browserless:
        return BrowserlessWebDriver(browserless)
    return MockWebDriver()


def submit_web(recipe: dict, answers: dict) -> dict:
    """Submit answers via the configured driver and return the evidence dict."""
    return get_web_driver().submit(recipe or {}, answers or {})
