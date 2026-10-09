"""Task-local raw Playwright MCP for native-alone runs. No manual or CL adapter."""
from __future__ import annotations
import argparse
from pathlib import Path
from urllib.parse import urlsplit
from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--root", type=Path, required=True)
args = parser.parse_args()
parsed = urlsplit(args.url)
if parsed.hostname != "127.0.0.1" or parsed.port not in range(48281, 48290):
    raise ValueError("Only the owned CL11 fixture origin is allowed")
origin = f"{parsed.scheme}://{parsed.netloc}"
root = args.root.resolve()
mcp = FastMCP("Playwright")
page = browser = runtime = None


async def current_page():
    global page, browser, runtime
    if page is None:
        runtime = await async_playwright().start()
        browser = await runtime.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=False, service_workers="block")
        async def scoped(route):
            target = urlsplit(route.request.url)
            if f"{target.scheme}://{target.netloc}" == origin:
                await route.continue_()
            else:
                await route.abort()
        await context.route("**/*", scoped)
        page = await context.new_page()
        await page.goto(args.url)
    return page


@mcp.tool()
async def browser_snapshot() -> str:
    """Read the current browser page accessibility tree."""
    return await (await current_page()).locator("body").aria_snapshot()


@mcp.tool()
async def browser_evaluate(function: str) -> dict:
    """Evaluate a JavaScript function on the owned current page."""
    return {"value": await (await current_page()).evaluate(function)}


@mcp.tool()
async def browser_click(selector: str) -> dict:
    """Click a CSS selector on the owned current page."""
    await (await current_page()).locator(selector).click()
    return {"ok": True}


@mcp.tool()
async def browser_fill(selector: str, value: str) -> dict:
    """Fill a CSS selector on the owned current page."""
    await (await current_page()).locator(selector).fill(value)
    return {"ok": True}


@mcp.tool()
async def browser_navigate(url: str) -> dict:
    """Navigate within this session's granted origin."""
    target = urlsplit(url)
    if f"{target.scheme}://{target.netloc}" != origin:
        raise ValueError("Navigation outside fixture origin refused")
    await (await current_page()).goto(url)
    return {"url": url}


@mcp.tool()
async def browser_screenshot(filename: str = "browser.png") -> dict:
    """Save a screenshot inside the disposable fixture root."""
    destination = (root / filename).resolve()
    if not destination.is_relative_to(root):
        raise ValueError("Screenshot must stay inside the fixture")
    await (await current_page()).screenshot(path=str(destination), full_page=True)
    return {"path": str(destination)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
