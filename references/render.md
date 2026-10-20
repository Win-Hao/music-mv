# 做整片：渲染

## 画面怎么组织

- **画面是时间 t 的函数**：`drawFrame(t)` 只看 t，不存上一帧的状态；随机数用「元素名 + 序号」做种子，不用 `Math.random()`。这样能拖时间线预览、能多进程渲、能只重渲改过的一段
- **一个镜头一个画布**：背景、角色、道具画在同一个画布上，跟同一个镜头 `camera(t) → {x, y, zoom}` 动。**不要**把背景图和单独渲出来的角色视频叠在一起：做过，推拉时层和层对不上，出过重影、叠出四个角色、东西忽隐忽现
- **镜头只有一个数据源**：机位表只放一份，改了背景要跟着改机位
- **分镜 → 代码**：`SHOTS = [{ start, end, draw(g, u, t) }]`，每个镜头一个函数（一个文件三百行以内），`u` 是镜头内进度 0→1。共用的：`character.js`、道具、调色板、`camera(t)`、时间工具（`beatPhase(t)`、`ease`、`lerp`、关键帧插值）
- **拍子**：BPM 和第一拍写在开头，所有拍点由 `(t - OFF) / BEAT` 算出来
- **一直在动的东西**：每个镜头里有些东西一直在动（雪、光点、云、草），角色站着也在呼吸
- **画幅**：横屏 1920×1080（或 1920×1440 的 4:3），竖屏 1080×1920；30fps。纸纹这类质感最后整片叠一层

## 两条渲染路线

| | 路线 A：直接在 HyperFrames 里画 | 路线 B：先逐帧渲画面，再叠歌词 |
|---|---|---|
| 用在 | 一帧能同步画完：Canvas 2D、SVG、DOM（像素风、纸艺拼贴、扁平绘本、纸艺立体书） | 一帧要等：p5.js v2 + p5.brush（蜡笔、水彩）、WebGL、一帧零点几秒的 |
| 模板 | `templates/hf-canvas/index.html` + `templates/lyrics-layer.js` | `templates/frames/scene.html` → `scripts/render_frames.mjs` → `templates/hf-overlay/index.html` |
| 为什么 | 最简单，一个工程，能在 HyperFrames Studio 里拖着看 | HyperFrames 每帧调用是同步的，不等 p5 v2 的异步重画，会抓到没画完的帧（第一帧空白） |

### 路线 A

```bash
npx hyperframes init mv --non-interactive --example=blank     # 第一次会下载渲染器和一个无头 Chrome；会顺带生成它自己的 AGENTS.md、CLAUDE.md（HyperFrames 的说明，留着就行）
cp <skill>/templates/hf-canvas/index.html <skill>/templates/lyrics-layer.js mv/
cp song.mp3 mv/ && python3 <skill>/scripts/srt2js.py lyrics.srt -o mv/lyrics.js
# 改 index.html：DURATION 和两处 data-duration（#root、audio）改成歌长，BPM、OFF，drawFrame(t) 换成分镜（模板开头的注释写了哪些要改）
cd mv && npx hyperframes lint && npx hyperframes preview          # 浏览器里拖时间线看
npx hyperframes render --quality draft --output ../review/draft.mp4                # 快速看
npx hyperframes render --quality delivery --output ../render.mp4                   # 出片
cd .. && python3 <skill>/scripts/finalize_audio.py render.mp4 song.mp3 -o mv-r1.mp4
```

### 路线 B

```bash
cp <skill>/templates/frames/scene.html .        # 改 DURATION、BPM、OFF、drawWorld(p, t)
npm i puppeteer-core                             # 渲帧用（问过用户再装）。自动用本机 Chrome 或 npx hyperframes 下载过的；都没有就 npm i puppeteer
node <skill>/scripts/render_frames.mjs --page scene.html --fps 30 --duration 58.7 --out frames --from 20 --to 35   # 先渲最难的一段看
node <skill>/scripts/render_frames.mjs --page scene.html --fps 30 --duration 58.7 --out frames --encode mv/scene.mp4
# mv/ 用 templates/hf-overlay/index.html（叠歌词、配歌），然后同路线 A 的 render、finalize_audio
```

- p5 必须用**实例模式**（`new p5(p => …)`，`brush.instance(p)`）。全局模式在 HyperFrames 里 `setup()` 根本不会被调用，在渲帧页面里也容易和 p5 的全局函数撞名（`blue`、`mix`）
- 已经渲好的帧会跳过，断了重跑接着渲；改了哪段就 `--from --to --force` 只重渲那段
- `--workers` 默认 2。开多了显存不够，会出黑帧或者少了一层（WebGL `CONTEXT_LOST`），`video_rhythm.py` 的黑帧和帧差里突然一串 40 左右的跳变能查出来，删掉坏帧再跑一次补上
- `--encode` 只接 0 到最后一帧（片子改短了，多出来的旧帧不会混进去），每秒一个关键帧（交给 HyperFrames 的视频关键帧太稀会抽帧失败、出黑屏）

## HyperFrames 要点

- 合成的根：`<div id="root" data-composition-id="main" data-start="0" data-duration="…" data-width="…" data-height="…" data-fps="30">`
- 一条暂停的 GSAP 时间线推一个 `{t}`，`onUpdate` 里调 `drawFrame(t)`；再监听 `hf-seek` 也调一次；最后 `window.__timelines["main"] = tl`。模板里已经写好
- 歌：`<audio src="song.mp3" data-start="0" data-duration="…" data-media-start="0" data-track-index="10">`；路线 B 的画面：`<video src="scene.mp4" muted data-start="0" data-duration="…" data-media-start="0" data-track-index="1">`
- 别用 CSS `mix-blend-mode`：HyperFrames 会退回慢很多的截图式抓帧。要混色在画布里混
- 装了 HyperFrames 自带的 skill 的话，渲染细节按它的；这支 MV 的步骤和停点按本 skill

## 歌词上屏

`templates/lyrics-layer.js`：最上层、不跟镜头动，一个字一个字弹出来，下一句前 0.24 秒收走。样式在 `window.LYRIC_STYLE` 改（`bottom`、`size`、`color`、`ink`、`font`）。
- 浅色字 + 深色粗描边 + 硬投影，不发光；副歌可以换个颜色、放大一点
- 字号：1920 宽时 64–78 px
- 会压到脸的那几句挪到右下
- 用户不要歌词：去掉 `lyrics.js`、`lyrics-layer.js` 两行和 `LYRIC_LAYER` 的调用

## 出静态图：样图、设定图、草图

第 2、3、5 步要的 PNG 都用 `render_frames.mjs --times` 出：写一个页面，定义 `window.sceneReady` 和 `window.renderAt(t)`（和逐帧渲染一样），它在给的时刻各截一张。页面要从左上角画起（脚本会自动去掉浏览器默认的边距）。

```bash
# 画风样图：页面按 ?style= 画不同画风的同一个开场画面
node <skill>/scripts/render_frames.mjs --page "styles.html?style=pixel" --times 0 --out styles --name pixel
# 角色设定图：页面把三视图、表情表、动作定格排在一张大画布上（--width --height 给画布大小）
node <skill>/scripts/render_frames.mjs --page sheet.html --times 0 --width 2400 --height 1600 --out . --name character-sheet
# 草图：每个镜头挑一个关键时刻（分镜里那个镜头最能说明问题的一瞬），渲出 sketches/01.png、02.png…，再拼成一张
node <skill>/scripts/render_frames.mjs --page sketch.html --times 2.1,6.8,11.5,15.0 --out sketches
python3 <skill>/scripts/contact_sheet.py --images sketches -o storyboard.png --cols 4 --width 480
```

路线 A 的工程里，草图页可以直接引用同一份 `character.js`、镜头代码，画的就是正片会出的样子。

## 声音

渲染器为了不爆音常把歌压小 2–4 dB（HyperFrames 会压到 -1 dBTP 以下）。渲完一律跑 `finalize_audio.py`，把原曲按原音量封回去，它会打印原曲、渲染出来的、封好的三个响度。MV 从歌的中间开始就加 `--start`，结尾要淡出加 `--fade-out 2`。

## 速度参考

- Canvas 2D：很快，几秒渲 10 秒
- p5.brush 水彩，1920×1440：约 0.3 秒一帧，4 个进程约 18 分钟渲 1 分钟成片；HyperFrames 再叠歌词约 2 分钟
- 整支 MV 从开始到做完 7–10 小时（含用户看片提意见），改 4–9 版
- 先渲最难的 10–20 秒给用户看手感，再渲整片

## 踩坑

| 现象 | 原因和办法 |
|---|---|
| HyperFrames 渲出来第一帧空白、某些帧没画完 | 画法是异步的（p5 v2 的 `redraw()`）。走路线 B |
| p5 页面在 HyperFrames 里一直等不到就绪 | 用了 p5 全局模式。改实例模式 |
| 整段渲出来是空的、道具没了 | 往一行代码中间插了 `//` 注释，后半行被注掉。渲染前对每个 js 跑 `node --check` |
| 某几个镜头一开头就报错 | 共用函数没定义、和库的全局名撞了。每个镜头至少抽一帧看 |
| 叠出两个角色、重影、东西忽隐忽现 | 分层叠了单独渲的角色视频，或者两张背景接力时画的东西不一致。改成一个画布一个镜头 |
| 状态切换跳一帧 | 写了 `t < x ? A : B`。改成随时间渐变；闪光也要在 3 帧内亮起来 |
| 角色被关键帧补间拖着横穿画面 | 要瞬移的地方前面加一个停在原地的关键帧 |
| 水彩填色一闪一闪 | 填色的随机种子跟着时间变了。填色用固定种子，只让线条按 12fps 换 |
| 暗角在超宽背景上出现假接缝 | 暗角按画面算，不按背景图算，最后整片叠 |
| 成片比原曲小 2 dB 左右 | 渲染器压了峰值。`finalize_audio.py` |
| 页面加载大图超时 | 资源多时把等待放宽到 180 秒（`render_frames.mjs` 已经是） |
| 在命令或回复里打出整段歌词被拦 | 内容过滤。脚本读文件，回复里只说第几句 |
