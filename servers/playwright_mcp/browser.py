from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from .settings import Settings


async def validate_url(url: str, settings: Settings) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only HTTP and HTTPS URLs are supported")
    if settings.allow_private_networks:
        return
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Could not resolve target host") from exc
    for address in {item[4][0] for item in addresses}:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("Private and local network targets are disabled")


class BrowserCapture:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def capture(
        self,
        url: str,
        artifact_type: str,
        selector: str | None,
        full_page: bool,
        navigation_timeout_ms: int | None = None,
        wait_until: str | None = None,
        block_third_party_requests: bool | None = None,
    ) -> bytes:
        await validate_url(url, self.settings)
        from playwright.async_api import async_playwright

        timeout = navigation_timeout_ms or self.settings.navigation_timeout_ms
        if timeout < 1 or timeout > self.settings.max_navigation_timeout_ms:
            raise ValueError(f"navigation_timeout_ms must be between 1 and {self.settings.max_navigation_timeout_ms}")
        wait_state = (wait_until or self.settings.navigation_wait_until).lower()
        if wait_state not in {"commit", "domcontentloaded", "load", "networkidle"}:
            raise ValueError("wait_until must be commit, domcontentloaded, load, or networkidle")
        block_third_party = self.settings.block_third_party_requests if block_third_party_requests is None else block_third_party_requests
        source_host = urlparse(url).hostname

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context()
                if block_third_party:
                    async def block_external(route):
                        request_host = urlparse(route.request.url).hostname
                        if request_host and source_host and request_host != source_host and not request_host.endswith(f".{source_host}"):
                            await route.abort()
                        else:
                            await route.continue_()
                    await context.route("**/*", block_external)
                page = await context.new_page()
                await page.goto(url, wait_until=wait_state, timeout=timeout)
                target = page.locator(selector).first if selector else page.locator("html")
                if selector and await target.count() == 0:
                    raise ValueError(f"Selector did not match any element: {selector}")
                if artifact_type == "html":
                    return (await target.inner_html()).encode("utf-8")
                if artifact_type == "pdf":
                    return await page.pdf(format="A4", print_background=True)
                if selector:
                    return await target.screenshot(type="jpeg" if artifact_type == "jpeg" else "png")
                return await page.screenshot(type="jpeg" if artifact_type == "jpeg" else "png", full_page=full_page)
            finally:
                await browser.close()
