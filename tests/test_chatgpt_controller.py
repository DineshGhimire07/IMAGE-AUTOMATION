"""Unit tests for resilient ChatGPT controller methods and overlay dismissal."""
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.browser.chatgpt_controller import ChatGPTController, ChatGPTControllerError


@pytest.mark.asyncio
async def test_find_prompt_input_succeeds_when_visible():
    """Verify find_prompt_input returns locator when visible."""
    page = MagicMock()
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()
    page.evaluate = AsyncMock(return_value=None)

    # Mock locator
    mock_loc = MagicMock()
    mock_loc.count = AsyncMock(return_value=1)
    mock_first = MagicMock()
    mock_first.is_visible = AsyncMock(return_value=True)
    mock_loc.first = mock_first
    mock_loc.nth = MagicMock(return_value=mock_first)

    page.locator = MagicMock(return_value=mock_loc)

    found = await ChatGPTController.find_prompt_input(page, timeout_seconds=1.0)
    assert found is not None
    assert found == mock_first


@pytest.mark.asyncio
async def test_find_prompt_input_recovers_via_dom_fallback():
    """Verify find_prompt_input uses DOM presence fallback if locator initially not marked visible."""
    page = MagicMock()
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()

    mock_loc = MagicMock()
    mock_loc.count = AsyncMock(return_value=1)
    mock_first = MagicMock()
    mock_first.is_visible = AsyncMock(return_value=False)
    mock_loc.first = mock_first
    mock_loc.nth = MagicMock(return_value=mock_first)
    page.locator = MagicMock(return_value=mock_loc)

    # DOM evaluate returns true (element exists in DOM)
    page.evaluate = AsyncMock(return_value=True)

    found = await ChatGPTController.find_prompt_input(page, timeout_seconds=1.0)
    assert found is not None
    assert found == mock_first


@pytest.mark.asyncio
async def test_dismiss_overlays_handles_exceptions_gracefully():
    """Verify dismiss_overlays handles modal dismissals and does not raise."""
    page = MagicMock()
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock(side_effect=Exception("Keyboard error"))
    page.evaluate = AsyncMock(side_effect=Exception("JS error"))
    page.locator = MagicMock(side_effect=Exception("Locator error"))

    # Should not raise exception
    await ChatGPTController.dismiss_overlays(page)
