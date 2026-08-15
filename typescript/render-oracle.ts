import type { Locator, Page } from '@playwright/test';
import pixelmatch from 'pixelmatch';
import { PNG } from 'pngjs';

export type Rect = {
  x: number;
  y: number;
  width: number;
  height: number;
  top: number;
  right: number;
  bottom: number;
  left: number;
};

export type RenderObservation = {
  attached: boolean;
  playwrightVisible: boolean;
  checkVisibility: boolean | null;
  intersectionRatio: number;
  intersectionRect: Rect;
  ioV2Supported: boolean;
  ioV2Visible: boolean | null;
  topHitRatio: number;
  sampledPoints: number;
  opacityProduct: number;
  rect: Rect;
  computedStyle: {
    display: string;
    visibility: string;
    opacity: string;
    overflowX: string;
    overflowY: string;
    clipPath: string;
    filter: string;
    maskImage: string;
    transform: string;
    contentVisibility: string;
    pointerEvents: string;
  };
  clippingAncestors: Array<{
    tag: string;
    id: string;
    className: string;
    overflowX: string;
    overflowY: string;
    clipPath: string;
    rect: Rect;
  }>;
};

export type PaintContribution = {
  changedPixels: number;
  changedRatio: number;
  width: number;
  height: number;
};

export type FrameSample = {
  timeMs: number;
  connected: boolean;
  checkVisibility: boolean | null;
  opacityProduct: number;
  approxClipRatio: number;
  topHitRatio: number;
  rect: Rect;
};

const rectToObject = (rect: DOMRect | DOMRectReadOnly): Rect => ({
  x: rect.x,
  y: rect.y,
  width: rect.width,
  height: rect.height,
  top: rect.top,
  right: rect.right,
  bottom: rect.bottom,
  left: rect.left,
});

/**
 * Captures one deterministic browser-observation checkpoint.
 * It deliberately separates geometric visibility, composited visibility,
 * and pointer actionability because they are not equivalent.
 */
export async function observeRenderState(
  page: Page,
  locator: Locator,
  gridSize = 5,
): Promise<RenderObservation> {
  const count = await locator.count();
  if (count !== 1) {
    if (count === 0) {
      return {
        attached: false,
        playwrightVisible: false,
        checkVisibility: false,
        intersectionRatio: 0,
        intersectionRect: { x: 0, y: 0, width: 0, height: 0, top: 0, right: 0, bottom: 0, left: 0 },
        ioV2Supported: false,
        ioV2Visible: null,
        topHitRatio: 0,
        sampledPoints: 0,
        opacityProduct: 0,
        rect: { x: 0, y: 0, width: 0, height: 0, top: 0, right: 0, bottom: 0, left: 0 },
        computedStyle: {
          display: '', visibility: '', opacity: '', overflowX: '', overflowY: '',
          clipPath: '', filter: '', maskImage: '', transform: '', contentVisibility: '', pointerEvents: '',
        },
        clippingAncestors: [],
      };
    }
    throw new Error(`Render oracle requires exactly one target, but locator matched ${count}.`);
  }

  const playwrightVisible = await locator.isVisible();

  const browserMetrics = await locator.evaluate(async (element, args) => {
    const el = element as HTMLElement;
    const toRect = (r: DOMRect | DOMRectReadOnly) => ({
      x: r.x, y: r.y, width: r.width, height: r.height,
      top: r.top, right: r.right, bottom: r.bottom, left: r.left,
    });

    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const checkVisibility = typeof el.checkVisibility === 'function'
      ? el.checkVisibility({
          opacityProperty: true,
          visibilityProperty: true,
          contentVisibilityAuto: true,
        } as CheckVisibilityOptions)
      : null;

    let opacityProduct = 1;
    const clippingAncestors: Array<{
      tag: string;
      id: string;
      className: string;
      overflowX: string;
      overflowY: string;
      clipPath: string;
      rect: ReturnType<typeof toRect>;
    }> = [];

    for (let current: HTMLElement | null = el; current; current = current.parentElement) {
      const currentStyle = getComputedStyle(current);
      const opacity = Number.parseFloat(currentStyle.opacity);
      if (Number.isFinite(opacity)) opacityProduct *= opacity;
      const clips = /(hidden|clip|auto|scroll)/.test(
        `${currentStyle.overflowX} ${currentStyle.overflowY}`,
      ) || currentStyle.clipPath !== 'none';
      if (current !== el && clips) {
        clippingAncestors.push({
          tag: current.tagName.toLowerCase(),
          id: current.id,
          className: current.className,
          overflowX: currentStyle.overflowX,
          overflowY: currentStyle.overflowY,
          clipPath: currentStyle.clipPath,
          rect: toRect(current.getBoundingClientRect()),
        });
      }
    }

    let sampledPoints = 0;
    let topHits = 0;
    if (rect.width > 0 && rect.height > 0) {
      for (let row = 0; row < args.gridSize; row += 1) {
        for (let col = 0; col < args.gridSize; col += 1) {
          const x = rect.left + ((col + 0.5) * rect.width) / args.gridSize;
          const y = rect.top + ((row + 0.5) * rect.height) / args.gridSize;
          if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
          sampledPoints += 1;
          const top = document.elementsFromPoint(x, y)[0];
          if (top === el || (top instanceof Node && el.contains(top))) topHits += 1;
        }
      }
    }

    const v1 = await new Promise<IntersectionObserverEntry>((resolve) => {
      const observer = new IntersectionObserver(([entry]) => {
        observer.disconnect();
        resolve(entry);
      }, { threshold: [0, 0.01, 0.25, 0.5, 0.75, 1] });
      observer.observe(el);
    });

    let ioV2Supported = false;
    let ioV2Visible: boolean | null = null;
    try {
      const v2 = await new Promise<IntersectionObserverEntry>((resolve) => {
        const observer = new IntersectionObserver(([entry]) => {
          observer.disconnect();
          resolve(entry);
        }, {
          threshold: [0, 1],
          trackVisibility: true,
          delay: 100,
        } as IntersectionObserverInit);
        observer.observe(el);
      });
      ioV2Supported = 'isVisible' in v2;
      ioV2Visible = ioV2Supported
        ? Boolean((v2 as IntersectionObserverEntry & { isVisible?: boolean }).isVisible)
        : null;
    } catch {
      // IntersectionObserver v2 is currently Chromium-specific in many setups.
    }

    return {
      checkVisibility,
      intersectionRatio: v1.intersectionRatio,
      intersectionRect: toRect(v1.intersectionRect),
      ioV2Supported,
      ioV2Visible,
      topHitRatio: sampledPoints > 0 ? topHits / sampledPoints : 0,
      sampledPoints,
      opacityProduct,
      rect: toRect(rect),
      computedStyle: {
        display: style.display,
        visibility: style.visibility,
        opacity: style.opacity,
        overflowX: style.overflowX,
        overflowY: style.overflowY,
        clipPath: style.clipPath,
        filter: style.filter,
        maskImage: style.maskImage || style.webkitMaskImage,
        transform: style.transform,
        contentVisibility: style.contentVisibility,
        pointerEvents: style.pointerEvents,
      },
      clippingAncestors,
    };
  }, { gridSize });

  return {
    attached: true,
    playwrightVisible,
    ...browserMetrics,
  };
}

/**
 * Estimates whether the target contributes pixels to the final viewport.
 * The target is temporarily made fully transparent without changing layout,
 * then two screenshots are compared. Run this only in a frozen, deterministic page.
 */
export async function measurePaintContribution(
  page: Page,
  locator: Locator,
  clip?: { x: number; y: number; width: number; height: number },
): Promise<PaintContribution> {
  if (await locator.count() !== 1) {
    throw new Error('Paint probe requires exactly one attached target.');
  }

  const screenshotOptions = {
    ...(clip ? { clip } : {}),
    animations: 'allow' as const,
    caret: 'hide' as const,
  };

  const before = await page.screenshot(screenshotOptions);
  const previous = await locator.evaluate((el) => {
    const node = el as HTMLElement;
    const read = (name: string) => ({
      value: node.style.getPropertyValue(name),
      priority: node.style.getPropertyPriority(name),
    });
    const state = {
      opacity: read('opacity'),
      transition: read('transition'),
      animationPlayState: read('animation-play-state'),
    };
    node.style.setProperty('transition', 'none', 'important');
    node.style.setProperty('animation-play-state', 'paused', 'important');
    node.style.setProperty('opacity', '0', 'important');
    return state;
  });

  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));

  const after = await page.screenshot(screenshotOptions);

  await locator.evaluate((el, saved) => {
    const node = el as HTMLElement;
    const restore = (
      name: string,
      property: { value: string; priority: string },
    ) => {
      if (property.value) node.style.setProperty(name, property.value, property.priority);
      else node.style.removeProperty(name);
    };
    restore('opacity', saved.opacity);
    restore('transition', saved.transition);
    restore('animation-play-state', saved.animationPlayState);
  }, previous);

  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));

  const beforePng = PNG.sync.read(before);
  const afterPng = PNG.sync.read(after);
  if (beforePng.width !== afterPng.width || beforePng.height !== afterPng.height) {
    throw new Error('Screenshot dimensions changed during paint probe.');
  }

  const changedPixels = pixelmatch(
    beforePng.data,
    afterPng.data,
    undefined,
    beforePng.width,
    beforePng.height,
    { threshold: 0.1 },
  );
  const total = beforePng.width * beforePng.height;
  return {
    changedPixels,
    changedRatio: total > 0 ? changedPixels / total : 0,
    width: beforePng.width,
    height: beforePng.height,
  };
}

/**
 * Records a continuous invariant over requestAnimationFrame frames. This avoids
 * web-first assertions waiting until a transient disappearance has recovered.
 */
export async function startFrameRecorder(
  page: Page,
  locator: Locator,
  durationMs: number,
  gridSize = 5,
): Promise<{ collect: () => Promise<FrameSample[]> }> {
  if (await locator.count() !== 1) {
    throw new Error('Frame recorder requires exactly one attached target.');
  }
  const id = `render-oracle-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  await locator.evaluate((element, args) => {
    type RecorderStore = Record<string, { done: Promise<FrameSample[]> }>;
    const win = window as Window & { __renderOracleRecorders?: RecorderStore };
    win.__renderOracleRecorders ??= {};
    const el = element as HTMLElement;

    const toRect = (r: DOMRect): Rect => ({
      x: r.x, y: r.y, width: r.width, height: r.height,
      top: r.top, right: r.right, bottom: r.bottom, left: r.left,
    });
    const intersect = (a: Rect, b: Rect): Rect => {
      const left = Math.max(a.left, b.left);
      const top = Math.max(a.top, b.top);
      const right = Math.min(a.right, b.right);
      const bottom = Math.min(a.bottom, b.bottom);
      return {
        x: left,
        y: top,
        left,
        top,
        right,
        bottom,
        width: Math.max(0, right - left),
        height: Math.max(0, bottom - top),
      };
    };

    const done = new Promise<FrameSample[]>((resolve) => {
      const samples: FrameSample[] = [];
      const start = performance.now();

      const frame = () => {
        const now = performance.now();
        const rawRect = el.getBoundingClientRect();
        const rect = toRect(rawRect);
        let clipped = intersect(rect, {
          x: 0, y: 0, left: 0, top: 0,
          right: innerWidth, bottom: innerHeight,
          width: innerWidth, height: innerHeight,
        });
        let opacityProduct = 1;

        for (let current: HTMLElement | null = el; current; current = current.parentElement) {
          const style = getComputedStyle(current);
          const opacity = Number.parseFloat(style.opacity);
          if (Number.isFinite(opacity)) opacityProduct *= opacity;
          if (current !== el && /(hidden|clip|auto|scroll)/.test(`${style.overflowX} ${style.overflowY}`)) {
            clipped = intersect(clipped, toRect(current.getBoundingClientRect()));
          }
        }

        let sampled = 0;
        let topHits = 0;
        if (rect.width > 0 && rect.height > 0) {
          for (let row = 0; row < args.gridSize; row += 1) {
            for (let col = 0; col < args.gridSize; col += 1) {
              const x = rect.left + ((col + 0.5) * rect.width) / args.gridSize;
              const y = rect.top + ((row + 0.5) * rect.height) / args.gridSize;
              if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
              sampled += 1;
              const top = document.elementsFromPoint(x, y)[0];
              if (top === el || (top instanceof Node && el.contains(top))) topHits += 1;
            }
          }
        }

        const area = rect.width * rect.height;
        const clippedArea = clipped.width * clipped.height;
        samples.push({
          timeMs: now - start,
          connected: el.isConnected,
          checkVisibility: typeof el.checkVisibility === 'function'
            ? el.checkVisibility({
                opacityProperty: true,
                visibilityProperty: true,
                contentVisibilityAuto: true,
              } as CheckVisibilityOptions)
            : null,
          opacityProduct,
          approxClipRatio: area > 0 ? clippedArea / area : 0,
          topHitRatio: sampled > 0 ? topHits / sampled : 0,
          rect,
        });

        if (now - start >= args.durationMs || !el.isConnected) resolve(samples);
        else requestAnimationFrame(frame);
      };
      requestAnimationFrame(frame);
    });

    win.__renderOracleRecorders[args.id] = { done };
  }, { id, durationMs, gridSize });

  return {
    collect: async () => page.evaluate(async (recorderId) => {
      type RecorderStore = Record<string, { done: Promise<FrameSample[]> }>;
      const win = window as Window & { __renderOracleRecorders?: RecorderStore };
      const recorder = win.__renderOracleRecorders?.[recorderId];
      if (!recorder) throw new Error(`Unknown render recorder: ${recorderId}`);
      const samples = await recorder.done;
      delete win.__renderOracleRecorders?.[recorderId];
      return samples;
    }, id),
  };
}
