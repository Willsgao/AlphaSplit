const { chromium } = require('C:/Users/1/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path = require('path');
const fs = require('fs');

(async () => {
  const outDir = path.resolve('决赛答辩PPT_高玉伟三页_HTML', 'rendered_slides');
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
  await page.goto('http://127.0.0.1:8784/', { waitUntil: 'networkidle' });
  for (let index = 0; index < 3; index += 1) {
    if (index > 0) {
      await page.keyboard.press('ArrowRight');
      await page.waitForTimeout(250);
    }
    const slide = page.locator('.slide.active');
    const pageNo = await slide.getAttribute('data-page');
    await slide.screenshot({ path: path.join(outDir, `slide-${pageNo}.png`) });
    const issues = await slide.evaluate((root) => {
      const bounds = root.getBoundingClientRect();
      const outside = [];
      for (const element of root.querySelectorAll('*')) {
        if (element.tagName === 'TEMPLATE') continue;
        const style = getComputedStyle(element);
        if (style.display === 'none' || style.visibility === 'hidden') continue;
        const rect = element.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        if (rect.left < bounds.left - 1 || rect.top < bounds.top - 1 || rect.right > bounds.right + 1 || rect.bottom > bounds.bottom + 1) {
          outside.push({ tag: element.tagName, className: element.className, rect: [rect.left, rect.top, rect.right, rect.bottom] });
        }
      }
      return outside;
    });
    if (issues.length) {
      throw new Error(`Slide ${pageNo} has ${issues.length} out-of-bounds elements: ${JSON.stringify(issues.slice(0, 5))}`);
    }
    const textIssues = await slide.evaluate((root) => {
      const selector = '.terminal,.principle,.stage-no,.stage-core,.stage-output,.track-label,.track-boundary,.layer-name,.cap-items span,.layer-items span,.trust-list span,.business-chain span,.formula-label,.formula,.rule,.decision-node small';
      return [...root.querySelectorAll(selector)]
        .filter((element) => element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1)
        .map((element) => ({ tag: element.tagName, className: element.className, text: element.textContent.trim().slice(0, 80) }));
    });
    if (textIssues.length) {
      throw new Error(`Slide ${pageNo} has ${textIssues.length} text overflow issues: ${JSON.stringify(textIssues.slice(0, 5))}`);
    }
    process.stdout.write(`slide-${pageNo}: bounds and text fit OK\n`);
  }
  await browser.close();
})();
