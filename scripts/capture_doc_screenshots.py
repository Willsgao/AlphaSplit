# -*- coding: utf-8 -*-
"""截取技术文档用 Demo 界面图（需先启动 python -m engine.api.main）。"""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "figures"
BASE = "http://127.0.0.1:8000"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(BASE, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1500)

        # 回测页全景（Hero + Agent 面板）
        page.screenshot(path=str(OUT / "fig5-4a_backtest_home.png"), full_page=False)

        # 触发路演演示
        demo_btn = page.locator("#btnBacktestDemo")
        if demo_btn.count():
            demo_btn.click()
            page.wait_for_timeout(30000)

        conclusion = page.locator("#backtestConclusion")
        if conclusion.count():
            conclusion.scroll_into_view_if_needed()
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "fig5-4b_backtest_conclusion.png"), full_page=True)

        # 人工确认（路演 UI 隐藏顶栏 Tab，用步进器切换）
        page.evaluate("switchToTab('negotiate')")
        page.wait_for_timeout(500)
        # 注入演示回测结果，供双轨表与五角色协商截图
        page.evaluate("""
            async () => {
              const r = await fetch('/api/backtest/demo');
              const d = await r.json();
              state.backtestResult = d;
              if (typeof renderDualPoolPanel === 'function') renderDualPoolPanel();
            }
        """)
        page.wait_for_timeout(1200)
        dual = page.locator("#dualPoolPanel")
        if dual.count():
            dual.scroll_into_view_if_needed()
        page.screenshot(path=str(OUT / "fig5-4c_dual_pool.png"), full_page=False)

        page.evaluate("runNegotiate()")
        page.wait_for_timeout(8000)
        page.screenshot(path=str(OUT / "fig5-4d_five_role_negotiate.png"), full_page=True)

        page.evaluate("switchToTab('backtest')")
        page.wait_for_timeout(500)
        agent_panel = page.locator("#agentPanel")
        if agent_panel.count():
            agent_panel.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            agent_panel.screenshot(path=str(OUT / "fig5-4e_agent_panel.png"))

        browser.close()
        print("screenshots saved to", OUT)


if __name__ == "__main__":
    main()
