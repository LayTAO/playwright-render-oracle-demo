from __future__ import annotations

import io
import json
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

HTML = r'''<!doctype html><meta charset="utf-8">
<style>
*{box-sizing:border-box}html,body{margin:0;background:white;font-family:sans-serif}
.row{position:relative;height:140px;padding:20px}.host{position:relative;width:180px;height:70px;overflow:hidden;border:1px solid #999;background:#eee}
.target{position:absolute;left:10px;top:10px;width:120px;height:48px;background:#dc2828;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:bold}
</style>
<div class="row"><div id="flicker-host" class="host"><div id="flicker" class="target">flicker</div></div></div>
<div class="row"><div id="slide-host" class="host"><div id="slide" class="target">slide</div></div></div>
<script>
window.animations = {};
window.animations.flicker = document.querySelector('#flicker').animate([
  {opacity:1, offset:0}, {opacity:1, offset:.4}, {opacity:0, offset:.5}, {opacity:1, offset:.6}, {opacity:1, offset:1}
], {duration:1000, fill:'both'});
window.animations.slide = document.querySelector('#slide').animate([
  {transform:'translateX(0px)', offset:0},
  {transform:'translateX(220px)', offset:.5},
  {transform:'translateX(0px)', offset:1}
], {duration:1000, fill:'both'});
for (const a of Object.values(window.animations)) a.pause();
</script>'''


def changed_pixels(before: bytes, after: bytes) -> int:
    a = Image.open(io.BytesIO(before)).convert('RGBA')
    b = Image.open(io.BytesIO(after)).convert('RGBA')
    d = ImageChops.difference(a,b)
    return sum(1 for px in d.getdata() if any(px))


def sample(page, name: str, t: int) -> dict:
    page.evaluate("([name,t]) => { const a = window.animations[name]; a.currentTime=t; a.pause(); }", [name,t])
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    loc = page.locator(f'#{name}')
    metrics = loc.evaluate("""el => new Promise(resolve => {
      const r=el.getBoundingClientRect();
      const s=getComputedStyle(el);
      let sampled=0, hit=0;
      for(let yi=0;yi<5;yi++) for(let xi=0;xi<5;xi++) {
        const x=r.left+(xi+.5)*r.width/5, y=r.top+(yi+.5)*r.height/5;
        if(x<0||y<0||x>=innerWidth||y>=innerHeight) continue;
        sampled++;
        const top=document.elementsFromPoint(x,y)[0];
        if(top===el||el.contains(top)) hit++;
      }
      const io=new IntersectionObserver(es=>{const e=es[0];io.disconnect();resolve({
        pwVisible:null,
        opacity:parseFloat(s.opacity),
        rect:{x:r.x,y:r.y,width:r.width,height:r.height},
        intersectionRatio:e.intersectionRatio,
        hitRatio:sampled?hit/sampled:0,
        checkVisibility:el.checkVisibility({opacityProperty:true,visibilityProperty:true,contentVisibilityAuto:true})
      })},{threshold:[0,.01,.25,.5,.75,1]});io.observe(el);
    })""")
    metrics['pwVisible'] = loc.is_visible()
    before = page.screenshot()
    prior = loc.evaluate("el => ({v:el.style.getPropertyValue('opacity'),p:el.style.getPropertyPriority('opacity')})")
    loc.evaluate("el => el.style.setProperty('opacity','0','important')")
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    after = page.screenshot()
    loc.evaluate("(el,p)=>{if(p.v)el.style.setProperty('opacity',p.v,p.p);else el.style.removeProperty('opacity')}", prior)
    metrics['paintChangedPixels'] = changed_pixels(before, after)
    metrics['timeMs'] = t
    metrics['case'] = name
    return metrics


def main():
    times=[0,100,200,300,400,450,500,550,600,700,800,900,1000]
    rows=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':500,'height':320},device_scale_factor=1)
        page.set_content(HTML)
        for name in ['flicker','slide']:
            for t in times:
                rows.append(sample(page,name,t))
        browser.close()
    with open('/mnt/data/playwright_animation_results.json','w') as f:json.dump(rows,f,indent=2)
    print('case\ttime\tpwVisible\tcheckVisibility\topacity\tintersection\thit\tpaintPixels\tx')
    for r in rows:
        print(f"{r['case']}\t{r['timeMs']}\t{r['pwVisible']}\t{r['checkVisibility']}\t{r['opacity']:.2f}\t{r['intersectionRatio']:.3f}\t{r['hitRatio']:.2f}\t{r['paintChangedPixels']}\t{r['rect']['x']:.1f}")

if __name__=='__main__':main()
