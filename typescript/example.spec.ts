import { expect, test } from '@playwright/test';
import {
  measurePaintContribution,
  observeRenderState,
  startFrameRecorder,
} from './render-oracle';

test('the list remains painted, unclipped, and usable while scrolling', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', error => pageErrors.push(error.message));

  await page.goto('http://127.0.0.1:4173');

  // Health and trigger guards: a blank/broken harness must never count as a fix.
  const trigger = page.getByRole('button', { name: 'Open menu' });
  await expect(trigger).toBeEnabled();
  await trigger.click();

  const list = page.getByRole('listbox');
  await expect(list).toHaveCount(1);
  await expect(list).toBeVisible();
  await expect(list.getByRole('option')).not.toHaveCount(0);

  // Start observing before the second action, so transient failures are retained.
  const recorder = await startFrameRecorder(page, list, 800);
  const box = await list.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.mouse.wheel(0, 600);
  const frames = await recorder.collect();

  expect(frames.length).toBeGreaterThan(2);
  expect(frames.every(frame => frame.connected)).toBe(true);
  expect(Math.min(...frames.map(frame => frame.approxClipRatio))).toBeGreaterThanOrEqual(0.95);
  expect(Math.min(...frames.map(frame => frame.topHitRatio))).toBeGreaterThanOrEqual(0.60);
  expect(frames.every(frame => frame.checkVisibility !== false)).toBe(true);

  // A checkpoint vector helps diagnosis but should not assert implementation details.
  const observation = await observeRenderState(page, list);
  expect(observation.intersectionRatio).toBeGreaterThanOrEqual(0.95);
  expect(observation.topHitRatio).toBeGreaterThanOrEqual(0.60);

  // Pixel evidence without a VLM or a reference screenshot: hiding the target
  // should measurably change the final rendered viewport.
  const paint = await measurePaintContribution(page, list);
  expect(paint.changedPixels).toBeGreaterThan(100);

  expect(pageErrors).toEqual([]);
});
