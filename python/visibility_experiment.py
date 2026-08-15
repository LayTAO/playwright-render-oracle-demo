from __future__ import annotations

import io
import json
from dataclasses import dataclass, asdict
from typing import Any

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

HTML = r'''<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; width: 100%; min-height: 100%; font-family: sans-serif; background: white; }
  #stage { position: relative; width: 900px; height: 1800px; padding: 20px; }
  .row { position: relative; height: 90px; border-bottom: 1px solid #ddd; }
  .label { position: absolute; left: 0; top: 8px; width: 190px; font: 13px monospace; color: #222; }
  .host { position: absolute; left: 210px; top: 8px; width: 180px; height: 70px; background: #f7f7f7; border: 1px solid #bbb; }
  .target { position: absolute; left: 10px; top: 10px; width: 120px; height: 48px; background: rgb(220, 40, 40); color: white; border: 2px solid rgb(100,0,0); display: flex; align-items: center; justify-content: center; font-weight: 700; }
  .cover { position: absolute; left: 10px; top: 10px; width: 120px; height: 48px; background: rgb(40,80,220); z-index: 10; }
  .transparent-cover { position: absolute; left: 10px; top: 10px; width: 120px; height: 48px; background: transparent; z-index: 10; pointer-events: auto; }
  #t-display-none { display:none; }
  #t-visibility-hidden { visibility:hidden; }
  #t-opacity-zero { opacity:0; }
  #host-parent-opacity-zero { opacity:0; }
  #host-overflow-full, #host-overflow-partial { overflow:hidden; width:80px; height:60px; }
  #t-overflow-full { left:100px; }
  #t-overflow-partial { left:40px; }
  #t-offscreen { left:1000px; }
  #t-clip-path { clip-path: inset(100%); }
  #t-filter-opacity { filter: opacity(0); }
  #t-transparent-color { background:transparent; border:none; color:transparent; }
  #t-scale-zero { transform: scale(0); }
  #host-content-visibility { content-visibility:hidden; }
  #t-mask-zero { -webkit-mask-image: linear-gradient(transparent, transparent); mask-image: linear-gradient(transparent, transparent); }
  #t-pointer-none { pointer-events:none; }
  #t-empty-canvas { background:transparent; border:none; }
  #t-pseudo { background: transparent; border:none; color:transparent; }
  #t-pseudo::before { content:'PSEUDO'; color:white; background:rgb(220,40,40); padding:10px; }
</style>
</head>
<body>
<div id="stage">
  <div class="row"><div class="label">normal</div><div class="host"><div id="t-normal" class="target">normal</div></div></div>
  <div class="row"><div class="label">display:none</div><div class="host"><div id="t-display-none" class="target">hidden</div></div></div>
  <div class="row"><div class="label">visibility:hidden</div><div class="host"><div id="t-visibility-hidden" class="target">hidden</div></div></div>
  <div class="row"><div class="label">opacity:0</div><div class="host"><div id="t-opacity-zero" class="target">hidden</div></div></div>
  <div class="row"><div class="label">parent opacity:0</div><div id="host-parent-opacity-zero" class="host"><div id="t-parent-opacity-zero" class="target">hidden</div></div></div>
  <div class="row"><div class="label">overflow full clip</div><div id="host-overflow-full" class="host"><div id="t-overflow-full" class="target">clipped</div></div></div>
  <div class="row"><div class="label">overflow partial clip</div><div id="host-overflow-partial" class="host"><div id="t-overflow-partial" class="target">partial</div></div></div>
  <div class="row"><div class="label">off viewport</div><div class="host"><div id="t-offscreen" class="target">offscreen</div></div></div>
  <div class="row"><div class="label">opaque cover</div><div class="host"><div id="t-covered" class="target">covered</div><div class="cover"></div></div></div>
  <div class="row"><div class="label">transparent cover</div><div class="host"><div id="t-transparent-covered" class="target">visible</div><div class="transparent-cover"></div></div></div>
  <div class="row"><div class="label">clip-path</div><div class="host"><div id="t-clip-path" class="target">hidden</div></div></div>
  <div class="row"><div class="label">filter:opacity(0)</div><div class="host"><div id="t-filter-opacity" class="target">hidden</div></div></div>
  <div class="row"><div class="label">transparent content</div><div class="host"><div id="t-transparent-color" class="target">hidden</div></div></div>
  <div class="row"><div class="label">transform:scale(0)</div><div class="host"><div id="t-scale-zero" class="target">hidden</div></div></div>
  <div class="row"><div class="label">ancestor content-visibility:hidden</div><div id="host-content-visibility" class="host"><div id="t-content-visibility" class="target">hidden</div></div></div>
  <div class="row"><div class="label">mask fully transparent</div><div class="host"><div id="t-mask-zero" class="target">hidden</div></div></div>
  <div class="row"><div class="label">pointer-events:none</div><div class="host"><div id="t-pointer-none" class="target">visible</div></div></div>
  <div class="row"><div class="label">empty canvas</div><div class="host"><canvas id="t-empty-canvas" class="target" width="120" height="48"></canvas></div></div>
  <div class="row"><div class="label">pseudo-element content</div><div class="host"><div id="t-pseudo" class="target">base</div></div></div>
</div>
<script>
  // Make canvas explicit but visually empty.
  const c = document.getElementById('t-empty-canvas');
  c.getContext('2d').clearRect(0,0,c.width,c.height);
</script>
</body>
</html>'''

CASES = [
    "normal", "display-none", "visibility-hidden", "opacity-zero", "parent-opacity-zero",
    "overflow-full", "overflow-partial", "offscreen", "covered", "transparent-covered",
    "clip-path", "filter-opacity", "transparent-color", "scale-zero", "content-visibility",
    "mask-zero", "pointer-none", "empty-canvas", "pseudo"
]


def count_changed_pixels(before: bytes, after: bytes) -> tuple[int, int]:
    a = Image.open(io.BytesIO(before)).convert("RGBA")
    b = Image.open(io.BytesIO(after)).convert("RGBA")
    diff = ImageChops.difference(a, b)
    # Count pixels where any channel differs.
    data = diff.getdata()
    changed = sum(1 for px in data if any(px))
    return changed, a.width * a.height


def main() -> None:
    results: list[dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 900, "height": 1800}, device_scale_factor=1)
        page.set_content(HTML, wait_until="load")

        for name in CASES:
            selector = f"#t-{name}"
            locator = page.locator(selector)
            pw_visible = locator.is_visible()

            metrics = locator.evaluate("""el => new Promise(resolve => {
              const rect = el.getBoundingClientRect();
              const cs = getComputedStyle(el);
              const chain = [];
              let n = el;
              let opacityProduct = 1;
              while (n && n.nodeType === 1) {
                const s = getComputedStyle(n);
                opacityProduct *= Number.isFinite(parseFloat(s.opacity)) ? parseFloat(s.opacity) : 1;
                chain.push({
                  tag: n.tagName,
                  id: n.id,
                  display: s.display,
                  visibility: s.visibility,
                  opacity: s.opacity,
                  overflowX: s.overflowX,
                  overflowY: s.overflowY,
                  clipPath: s.clipPath,
                  filter: s.filter,
                  contentVisibility: s.contentVisibility,
                  pointerEvents: s.pointerEvents,
                });
                n = n.parentElement;
              }

              const points = [];
              const cols = 5, rows = 5;
              let hit = 0, sampled = 0;
              if (rect.width > 0 && rect.height > 0) {
                for (let yi=0; yi<rows; yi++) {
                  for (let xi=0; xi<cols; xi++) {
                    const x = rect.left + (xi + .5) * rect.width / cols;
                    const y = rect.top + (yi + .5) * rect.height / rows;
                    if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
                    sampled++;
                    const stack = document.elementsFromPoint(x,y);
                    const owns = stack.some(e => e === el || el.contains(e));
                    if (owns && (stack[0] === el || el.contains(stack[0]))) hit++;
                    points.push({x,y,top: stack[0]?.id || stack[0]?.className || stack[0]?.tagName || null, ownsTop: owns && (stack[0] === el || el.contains(stack[0]))});
                  }
                }
              }

              let checkVisibility = null;
              if (typeof el.checkVisibility === 'function') {
                checkVisibility = el.checkVisibility({
                  opacityProperty: true,
                  visibilityProperty: true,
                  contentVisibilityAuto: true,
                });
              }

              const io = new IntersectionObserver(entries => {
                const e = entries[0];
                io.disconnect();
                resolve({
                  rect: {x:rect.x,y:rect.y,width:rect.width,height:rect.height,top:rect.top,right:rect.right,bottom:rect.bottom,left:rect.left},
                  display: cs.display,
                  visibility: cs.visibility,
                  opacity: cs.opacity,
                  opacityProduct,
                  clipPath: cs.clipPath,
                  filter: cs.filter,
                  contentVisibility: cs.contentVisibility,
                  pointerEvents: cs.pointerEvents,
                  checkVisibility,
                  intersectionRatio: e.intersectionRatio,
                  intersectionRect: {x:e.intersectionRect.x,y:e.intersectionRect.y,width:e.intersectionRect.width,height:e.intersectionRect.height},
                  hitRatio: sampled ? hit/sampled : 0,
                  sampled,
                  centerTop: points[Math.floor(points.length/2)]?.top ?? null,
                  chain,
                });
              }, {threshold:[0, .01, .25, .5, .75, 1]});
              io.observe(el);
            })""")

            before = page.screenshot(full_page=False)
            # Opacity probe preserves layout and hides the entire target subtree/pseudo-elements.
            prior = locator.evaluate("""el => ({value: el.style.getPropertyValue('opacity'), priority: el.style.getPropertyPriority('opacity')})""")
            locator.evaluate("""el => el.style.setProperty('opacity', '0', 'important')""")
            # Force style/paint flush.
            page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
            after = page.screenshot(full_page=False)
            locator.evaluate("""(el, prior) => {
              if (prior.value) el.style.setProperty('opacity', prior.value, prior.priority);
              else el.style.removeProperty('opacity');
            }""", prior)
            page.evaluate("() => new Promise(r => requestAnimationFrame(r))")
            changed, total = count_changed_pixels(before, after)
            metrics["pwVisible"] = pw_visible
            metrics["paintChangedPixels"] = changed
            metrics["paintChangedRatioViewport"] = changed / total
            results.append({"case": name, **metrics})

        browser.close()

    out_json = "/mnt/data/playwright_visibility_results.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    cols = [
        "case", "pwVisible", "checkVisibility", "intersectionRatio", "hitRatio",
        "paintChangedPixels", "opacityProduct", "display", "visibility", "opacity", "clipPath", "filter", "contentVisibility", "pointerEvents"
    ]
    print("\t".join(cols))
    for r in results:
        vals = []
        for c in cols:
            v = r.get(c)
            if isinstance(v, float):
                vals.append(f"{v:.3f}")
            else:
                vals.append(str(v))
        print("\t".join(vals))
    print(f"\nJSON: {out_json}")


if __name__ == "__main__":
    main()
