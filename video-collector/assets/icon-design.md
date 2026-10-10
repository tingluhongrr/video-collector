# 视频采集器图标

使用内置 image_gen 工具生成，未使用 CLI/API 后备模式。
蓝色圆角底，白色播放键、下载箭头与托盘，透明背景。

- 原图：video-collector.png
- 窗口图标：video-collector-window.png（256 × 256）
- Windows 图标：video-collector.ico（16、24、32、48、64、128、256 像素）

PNG 原图保留生成结果和透明通道。窗口 PNG 与 ICO 使用 Pillow 缩放、转换格式。
构建脚本自动嵌入 ICO；窗口和任务栏使用相同设计。

## 最终生成提示词

Use case: logo-brand. Asset type: finished Windows desktop app icon for a video collection and download app. Create one polished, beautifully simple square app icon, 1024x1024. A bold white play triangle combined harmoniously with a white downward download arrow and short receiving tray, inside a cobalt blue rounded-square tile with a subtle rich blue-to-azure gradient. Strong optical balance, generous thick shapes, instantly legible at 32px, refined soft bevel highlights but essentially flat and clean, front facing, no perspective. Tile fills about 90% of canvas with consistent margins. Outside the rounded tile is genuinely transparent alpha, not a checkerboard pattern. No words, letters, numbers, watermark, branded platform logos, extra badges, mockup, or surrounding scene. Only the single finished icon.

## 使用

新版程序：dist/VideoCollector-Icon.exe。
如果旧快捷方式仍显示 Python 图标，可在快捷方式的“属性 → 快捷方式 → 更改图标”中选择此 ICO 或新版 EXE；新版 EXE 的快捷方式会使用内嵌图标。
