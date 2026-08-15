from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = Path('/mnt/data')
spec = importlib.util.spec_from_file_location('visibility', BASE / 'playwright_visibility_experiment.py')
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def main() -> None:
    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path='/usr/bin/chromium',
            args=['--no-sandbox'],
        )
        page = browser.new_page(viewport={'width': 900, 'height': 1800}, device_scale_factor=1)
        page.set_content(module.HTML)
        for name in module.CASES:
            result = page.locator(f'#t-{name}').evaluate(
                """el => new Promise(resolve => {
                  try {
                    const observer = new IntersectionObserver(entries => {
                      const entry = entries[0];
                      observer.disconnect();
                      resolve({
                        supported: 'isVisible' in entry,
                        isVisible: entry.isVisible ?? null,
                        intersectionRatio: entry.intersectionRatio,
                        isIntersecting: entry.isIntersecting,
                      });
                    }, { threshold: [0, 1], trackVisibility: true, delay: 100 });
                    observer.observe(el);
                    setTimeout(() => {
                      observer.disconnect();
                      resolve({ timeout: true });
                    }, 500);
                  } catch (error) {
                    resolve({ error: String(error) });
                  }
                })"""
            )
            rows.append({'case': name, **result})
        browser.close()

    out = BASE / 'playwright_iov2_results.json'
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    print('case\tsupported\tisVisible\tintersectionRatio\tisIntersecting')
    for row in rows:
        print(f"{row['case']}\t{row.get('supported')}\t{row.get('isVisible')}\t{row.get('intersectionRatio')}\t{row.get('isIntersecting')}")
    print(f'\nJSON: {out}')


if __name__ == '__main__':
    main()
