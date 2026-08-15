from __future__ import annotations

import json
import time
from playwright.sync_api import expect, sync_playwright

HTML = '''<!doctype html><meta charset="utf-8">
<button id="trigger">trigger</button>
<div id="target" style="width:120px;height:48px;background:red">target</div>
<script>
trigger.onclick = () => {
  target.style.visibility = 'hidden';
  setTimeout(() => { target.style.visibility = 'visible'; }, 250);
};
</script>'''

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    page = browser.new_page()
    page.set_content(HTML)
    target = page.locator('#target')
    page.locator('#trigger').click()

    immediate_visible = target.is_visible()
    start = time.perf_counter()
    expect(target).to_be_visible(timeout=1000)
    elapsed_ms = (time.perf_counter() - start) * 1000

    result = {
        'immediate_locator_is_visible': immediate_visible,
        'web_first_expect_passed': True,
        'expect_elapsed_ms': round(elapsed_ms, 1),
        'explanation': 'expect() retried until the element recovered',
    }
    print(json.dumps(result, indent=2))
    with open('/mnt/data/playwright_autoretry_result.json', 'w') as f:
        json.dump(result, f, indent=2)
    browser.close()
