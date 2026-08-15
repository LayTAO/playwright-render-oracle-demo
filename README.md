# Playwright Render Oracle Demo

这个目录保存了为“交互型视觉缺陷能否不用视觉大模型进行确定性评测”所做的原型实验。

## 已实际运行的环境

- Playwright Python 1.57.0
- Chromium 144.0.7559.96
- Debian GNU/Linux 13
- 视口与 device scale factor 固定

## 实验一：19 类不可见/不可用情况

`python/visibility_experiment.py` 构造了以下情况：`display:none`、`visibility:hidden`、目标或祖先 `opacity:0`、祖先 overflow 完全/部分裁剪、视口外、被不透明/透明层覆盖、`clip-path`、`filter:opacity(0)`、透明文本与背景、`transform:scale(0)`、`content-visibility:hidden`、透明 mask、`pointer-events:none`、空 canvas、伪元素绘制。

每个案例同时测量：

1. Playwright `is_visible()`；
2. `Element.checkVisibility()`；
3. `IntersectionObserver.intersectionRatio`；
4. `IntersectionObserver v2 entry.isVisible`（Chromium 可用）；
5. `document.elementsFromPoint()` 网格命中率；
6. opacity mutation 前后截图的 changed pixels，即目标是否对最终屏幕实际贡献像素。

结果见 `results/visibility_combined.tsv`。没有任何一个单独信号覆盖全部案例；组合信号才能区分“存在”“几何可见”“最终绘制”“可点击”。

## 实验二：瞬时动画缺陷

`python/animation_experiment.py` 构造两个 1 秒动画：

- 元素只在 500 ms 瞬间变成 `opacity:0`，随后恢复；
- 元素在动画中间移动到 `overflow:hidden` 容器外，随后返回。

在两个案例中，Playwright 的普通 visible 判断在所有采样点都可能保持 true；只检查动作结束后的截图也会通过。时间采样中的 `checkVisibility`、intersection ratio、hit ratio 和 paint contribution 能在中间帧检测到失败。

## 实验三：自动重试会掩盖瞬时失败

`python/autoretry_experiment.py` 让元素隐藏 250 ms 后恢复。隐藏后的即时 `locator.is_visible()` 返回 false，但紧接着调用 web-first `expect(locator).to_be_visible()` 最终通过，因为它自动重试到元素恢复。本次运行耗时约 358.5 ms。对闪烁、瞬时裁剪、短暂关闭等缺陷，不能只使用最终可见断言，必须记录时间窗口并检查连续不变量。

## TypeScript 参考实现

`typescript/render-oracle.ts` 提供：

- `observeRenderState()`：一次多通道检查点；
- `measurePaintContribution()`：不需要参考图或 VLM 的实际绘制贡献探针；
- `startFrameRecorder()`：用 requestAnimationFrame 检查连续时间不变量。

`typescript/example.spec.ts` 展示了“打开列表 → 滚动 → 整个过程中列表必须保持绘制、未被裁剪且可命中”的测试结构。选择器和阈值需要按真实 issue 定义，不能把示例中的数值机械用于所有组件。

## 运行 Python 实验

脚本默认使用 `/usr/bin/chromium`。安装 Python 依赖后运行：

```bash
python python/visibility_experiment.py
python python/iov2_experiment.py
python python/animation_experiment.py
```

依赖：`playwright`、`Pillow`，并需要本机 Chromium。

## 使用限制

- paint probe 要在固定环境、冻结动画与动态内容后运行；否则无关像素变化会造成噪声。
- IntersectionObserver v2 的 `isVisible=false` 允许保守的 false negative；它适合作为强证据或诊断信号，不应独立成为所有实例的唯一 oracle。
- 颜色、字体字形、图标内容、canvas/WebGL 绘制、mask、混合模式等纯栅格语义，仍需要 pixel diff 或任务特定断言；不需要 VLM，但不能只靠 DOM。
- benchmark 应断言用户可观察的行为，不应断言“overflow 必须等于 visible”之类具体实现，因为正确修复可能采用 portal、重新定位或其他机制。
