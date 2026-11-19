# 做整片：一个网页，逐帧渲

整支 MV 是 `mv/index.html` 一个网页。画面、转场、歌词都在里面按时间 t 画，由你按歌的拍点编排；`render_frames.mjs` 用无头浏览器一帧一帧截下来接成视频，`finalize_audio.py` 配上原曲。不用 HyperFrames、Remotion 这类剪辑合成工具：它们按片段拼接，镜头和镜头之间只能淡入淡出、硬切或者套转场块，接出来是僵的。

命令里的 `python3` 在 Windows 上换成 `py -3`（`check_env.py` 最后会打印本机该用哪个）。

## 画面怎么组织

- **画面是时间 t 的函数**：`draw(g, t)` 只看 t，不存上一帧的状态；随机数用 `MV.rng('元素名' + 序号)`、`MV.noise`，不用 `Math.random()`、`Date`。这样能拖着预览、能多进程渲、能只重渲改过的一段
- **一个镜头一个画布**：背景、角色、道具画在同一个画布上，跟同一个镜头 `camera(t) → {x, y, zoom}` 动。**不要**把背景图和单独渲出来的角色视频叠在一起：做过，推拉时层和层对不上，出过重影、叠出四个角色、东西忽隐忽现
- **镜头只有一个数据源**：一个镜头一条镜头曲线、一张机位表，改了背景要跟着改机位
- **分镜 → 代码**：模板里的镜头表 `SHOTS = [{ start, end, draw(g, t) }]`，每个镜头一个画法（镜头多了放进 `mv/shots/03-天台.js` 这样的文件，一个文件三百行以内）。相邻两个镜头的时间重叠一段，重叠的那几拍走 `transition(g, t, a, b)`，两个镜头都在画（见 `transitions.md`「在代码里怎么接」）。共用的：`character.js`、道具、调色板、`kit.js` 的时间工具
- **拍子从歌里来**：`song.js`（`analyze_song.py --js`）给页面一个 `window.SONG`：每一拍、小节第一拍、分段和每段多响、突变点、最重的几下、起音、响度包络。常用：`MV.beatTime(n)` 第 n 拍在几秒（从 0 数）、`MV.beat(t)` 现在第几拍（带小数）、`MV.beatPhase(t)` 这一拍走了多少、`MV.pulse(t, 0.12, SONG.downbeats)` 每小节第一拍一下的衰减脉冲、`MV.env(t, 'low')` 低音有多响（0→1）、`MV.section(t)` 现在是哪段。没有 `song.js` 就写 `MV.tempo(BPM, 第一拍秒数)` 按速度推
- **一直在动的东西**：每个镜头里有些东西一直在动（雪、光点、云、草），角色站着也在呼吸
- **画幅**：横屏 1920×1080（或 1920×1440 的 4:3），竖屏 1080×1920；30fps。页面里改 `W`、`H`，模板的示范按 W、H 摆，横竖都能看；竖屏的构图和歌词位置见 `storyboard.md`「竖屏」。纸纹这类质感最后整片叠一层

## 页面和命令

开工时已经把模板拷进了 `mv/`（SKILL.md「开始之前」）。

```bash
npm i puppeteer-core          # 渲帧用（问过用户再装），用本机的 Chrome、Edge 或 Chromium；都没有就 npm i puppeteer（自己带一个 Chrome）
# 写 mv/index.html：W、H、镜头表 SHOTS、每个镜头的画法、transition、blur(t)、歌词画法（模板开头的注释写了哪些要改）
for f in mv/*.js mv/shots/*.js; do [ -f "$f" ] && node --check "$f"; done   # index.html 里的脚本查不了，渲的时候看「页面报错」
# 预览：浏览器直接打开 mv/index.html（下一节）
node <skill>/scripts/render_frames.mjs --page mv/index.html --fps 30 --out frames --from 20 --to 35 --encode review/try.mp4   # 先渲最难的一段看：只接这一段，接完打印配声音的命令
node <skill>/scripts/render_frames.mjs --page mv/index.html --fps 15 --width 960 --height 540 --out draft --encode review/draft.mp4   # 整片草稿（竖屏 --width 540 --height 960）
node <skill>/scripts/render_frames.mjs --page mv/index.html --fps 30 --out frames --encode render.mp4   # 出片（没有声音），片长用页面的 MV.duration
python3 <skill>/scripts/finalize_audio.py render.mp4 song.mp3 -o mv-r1.mp4   # 只做一段要加 --start <起点>，上一步打印的命令里带好了
```

页面只做一件事：调 `MV.page({ W, H, fps, duration, ready, draw, overlay, blur })`。

| 参数 | 干什么 |
|---|---|
| `ready()` | async：下字体、取笔画数据、烤纸和纹理、缓存图层。准备完才开始画，不然头几帧是空的或者字体不对 |
| `draw(g, t)` | 画面。`g` 已经缩放成 W×H 的逻辑坐标，每帧从干净的状态画起、先铺黑底。可以 async（p5.brush 要等重画） |
| `overlay(g, t)` | 最上层：歌词、整片的纸纹。不跟镜头动，不进动态模糊 |
| `blur(t)` | 这一帧拆几个子帧做动态模糊，1 = 不开（下面「动态模糊」） |

`kit.js` 把这些接到 `window.renderAt(t)`、`window.sceneReady` 上，`render_frames.mjs` 只认这两个，所以页面也可以不用 kit 自己写。

- 画面大小、片长不用给：没写 `--width --height` 时用页面的 `W×H`（开头会打印「画面 1080×1920（页面的 MV.W×MV.H）」），给了就按给的出（草稿缩小用），要接视频时宽高得是偶数；没写 `--duration` 就用页面的 `MV.duration`，给的和页面差半秒以上会提醒（只做一段时片长不是歌长）
- 页面有 `window.PLAN`（转场落点的成片秒：模板按镜头表算，镜头里的甩镜也要加进去；眨眼、收光这种合上再张开的写成 `'起-落'` 或 `[起, 落]` 一段）时，开头会打印「页面的转场落点」，直接贴给 `video_rhythm.py --plan`、`contact_sheet.py --around`
- 页面脚本出错、10 秒内没设好 `window.sceneReady`、`ready()` 出错（包括 `MV.font`、`MV.glyphs` 没加载到），脚本会马上停下，说清是哪种；缺 `lyrics.js`、`song.js`，图片没加载到，会打成「页面提示：…」「加载失败：…」（每个进程的都打，同一句只打一次）。看到就停下修，别等渲完
- 某一帧画的时候出错：这一帧不存，那个进程重新打开页面接着渲；渲完把出错的帧自动补渲两轮（偶发的超时这样就补上了，一帧最多等 10 分钟）。还是失败的，硬盘上这一帧的旧图会删掉（`--force` 重渲时旧图还在，不删会被当成渲好的接进视频），这次不接视频，报出是哪几帧、什么错。修好再跑一次补上
- 已经渲好的帧会跳过，断了重跑接着渲；改了哪段就 `--from --to --force` 只重渲那段，再不带 `--from --to` 跑一遍 `--encode render.mp4` 接整片。改了 `character.js`、调色板、画面大小、`--format` 这类整片共用的东西，旧帧不会自己作废：用到它的镜头都要 `--force` 重渲，拿不准就整片 `--force`
- `--workers` 默认 2。开多了显存不够，会出黑帧或者少了一层（WebGL `CONTEXT_LOST`），`video_rhythm.py` 报的黑帧、计划外的切点能查出来，删掉坏帧再跑一次补上
- 帧默认存 jpg；网点、细线这类怕 JPEG 糊的画风（孔版印刷、一笔画）加 `--format png`
- `--encode` 只接 0 到最后一帧（片子改短了，多出来的旧帧不会混进去）；给了 `--from`、`--to` 就只接这一段（试渲用）。默认 `--preset medium`，要文件小一点用 `--preset slow`（慢不少）。找不到浏览器就设 `CHROME_PATH`；ffmpeg 不在 PATH 里就设 `FFMPEG`，这个只有 `render_frames.mjs` 认，Python 脚本要 ffmpeg 在 PATH 里

## 预览

浏览器直接打开 `mv/index.html` 就是预览：画面下面一条播放条，跟着歌放（`render_frames.mjs` 出图时不出现）：先找 `song.js` 记的那首（`analyze_song.py` 分析的文件），再找 `../song.mp3`、`.wav`、`.m4a`、`.flac`……；都找不到就按时钟静音放，播放条上会写一句。字体、笔画数据没加载到，播放条上也会写出来。`examples/` 里的示范页也能这样打开看。

- 空格播放 / 暂停，← → 走一帧，Shift + ← → 跳一拍，Home 回开头，拖进度条
- 地址后面可以加：`?t=32` 从 32 秒看起；`&blur=1` 预览也开动态模糊（会慢）；`&song=` 歌在别处。只做歌的一段时，预览自动从 `song.js` 记的起点放歌，`&start=30` 可以改
- 播放条右边：时间、`拍 7.62`（就是 `MV.beat(t)`，从 0 数，走到 8.00 的那一刻就是 `MV.beatTime(8)`）、第几段（多响）、画一帧用了几毫秒
- 画得慢的页面（p5.brush）预览会掉帧，只用来看大概；准不准以 `render_frames.mjs --times` 出的图和草稿视频为准
- 页面要读本地的 JSON、图片（`fetch`）时，直接双击打开会被浏览器拦，在歌的文件夹里 `python3 -m http.server 8000`，打开 `http://localhost:8000/mv/index.html`

## 转场和动态模糊

转场怎么在代码里接，见 `transitions.md`「在代码里怎么接」：两个镜头在转场那几拍都画、镜头速度连续、拍前起步拍上落位、不用匀速。

动态模糊：`blur(t)` 返回大于 1 的数 n，这一帧就拆成 n 个子帧（铺在这一帧之前半帧的时间里，`shutter` 改长短）平均起来，快速移动的东西拉出拖影；歌词在 `overlay` 里，不会糊。

- 子帧数按镜头这一帧走了多少像素定，大约每 4 像素一个，最多 32（模板的 `blur(t)` 就是这么算的）。开了的帧 kit 至少拆 8 个（`MV.page` 的 `blurMin`）：子帧太少会看到一个个分开的残影，比不开还难看（做过：快动的人偶只分到两三个子帧，出了一串残影）
- 只在甩镜、快推、东西飞过的那几帧开；镜头不动的时候返回 1。开了的帧慢 n 倍
- 角色跟着镜头一起走时，角色自己是清楚的，背景糊，这是对的

## 歌词上屏

模板用 `MV.drawLyric(g, t)`：最上层、不跟镜头动，一个字一个字弹出来，这句唱完留 0.3 秒，下一句前 0.24 秒收走；一行超过画面宽度的 80% 就从中间折成两行，还放不下就缩字。样式在 `MV.lyricStyle` 改（`bottom`、`size`、`color`、`ink`、`weight`、`font`）；竖屏时默认自动挪到画面约四分之三高的地方、字号 64，躲开平台下面的标题和文案。

- **逐字时间**：`lyrics.js` 里一句是 `[开始, 结束, "这句"]`；带上逐字时间的句子多一项：每个字开唱的秒 `[开始, 结束, "这句", [t1, t2, …]]`（`srt2js.py --words` 写，也可以手写 `[开始, 结束]` 一对）。字位：中文一个字一个，连着的英文字母、数字一个词一个，空格、标点不占（`MV.lyricUnits` 和 `srt2js.py` 同一套拆法）。有逐字时间，`MV.lyricAt` 让每个字在开唱前 0.04 秒（`lead`，规矩是最多早 0.08 秒）开始弹：开唱那一帧已经看得见，不晚一帧；没有就照旧从句首起每 0.045 秒（`per`）一个字，空格不占时间。没有逐字时间的老 `lyrics.js`、老页面不用改
- **逐字时间从哪来**：Whisper 加 `--word_timestamps True --output_format json`，出来的 json 直接给 `--words`（一个词几个字就平分这个词的时间，再按字和 `lyrics.srt` 每句比对：对上的用它的时间，Whisper 听错的、srt 改过的字按前后插值，`srt2js.py` 会打印每句几个字是插出来的，那几句对着歌核一下）；或者自己整理的 `lyrics-words.json`：`{"lines": [{"chars": [{"text": "字", "t0": 12.34}, …]}, …]}`，一句一项、和 `lyrics.srt` 同样的句数，时间和 srt 一样是歌里的秒。整句时间别自动「吸到最近的起音、卡到拍上」：弱起、拖拍的唱法会吸错，做过一次整片晚了约 0.5 秒
- **按帧核**：`node <skill>/scripts/render_frames.mjs --page mv/index.html --lyric-check`（只做一段加 `--from --to`）：每个字在开唱那一帧（离开唱最近的那一帧）画一张歌词层、再当这个字还没唱到画一张，差出来的就是这个字自己：开唱那一帧要看得见，开唱前 0.08 秒以前要看不见。打印晚了几帧、早了的是第几句第几个字（不打歌词）。只认用 `MV.lyricAt` 出字、画在 overlay 里的页面；写字、印字这类一开始只出一点点的画法，第一帧画得太少也算晚（做过：印上去的字第一帧几乎是空的，等于晚一帧）
- 浅色字 + 深色粗描边 + 硬投影，不发光；副歌可以换个颜色、放大一点
- 字号：1920 宽时 64–78 px、竖屏 1080 宽时 56–68 px 是好读的范围（手机上看得清，又不抢画面）；画风自己的歌词写法（题跋、字卡）按它那一节的字号
- 会压到脸的那几句挪开：横屏往右下，竖屏往左上（竖屏右下是点赞评论那一列按钮）
- 画风有自己的写法（对话框、纸条、题跋、一笔一笔写出来）就自己画：`MV.lyricAt(t)` 给出现在是哪句、每个字出来了多少（`chars[k].u` 0→1）、这个字开唱和唱完的秒（`chars[k].t0`、`t1`：写字类画风写一个字的时间不超过它唱的时长），照着画就行
- **字体用网页加载的开源字体**，在 `ready` 里 `await MV.font('800 64px "字体名"', 用到的字)` 等它下好：模板默认 `<link>` 了思源黑体（Noto Sans SC），`MV.lyricStyle.font` 写的就是它。没下到 `MV.font` 会报出来：出片时停下，预览时写在播放条上。不用系统字体（PingFang、微软雅黑）：Windows 和 Mac 渲出来不一样，折行也会变，草稿和成片在两台电脑上渲就对不上。别用 `document.fonts.check()` 判断：页面上根本没有这个字体时它也返回 true
- **写字类画风的笔画数据**（蜡笔、水墨、一笔画按笔顺写歌词，hanzi-writer-data 的笔画中线）：先 `python3 <skill>/scripts/glyphs.py lyrics.srt -o mv/glyphs.js`，页面里 `<script src="glyphs.js"></script>`，`ready` 里 `await MV.glyphs(歌词)` 先用它。渲染时现从网上取，网慢时有的进程取到、有的没取到，同一个字前后帧不一样，取不到还会退回系统字体
- 用户不要歌词：去掉 `lyrics.js` 那行和 `overlay`

## 出静态图：样图、设定图、草图

第 2、3、5 步要的 PNG 都用 `render_frames.mjs --times` 出：页面用 `MV.page`（就有了 `window.sceneReady` 和 `window.renderAt(t)`），它在给的时刻各截一张，大小按页面的 W×H。这几个页面要你自己写：

- **样图**：每种画风一页 `styles/<画风>.html`，引用 `../mv/kit.js`，画同一个开场画面；笔刷画风那页从 `templates/mv/p5brush.html` 改
- **设定图**：`mv/sheet.html`，和 `index.html` 共用 `kit.js`、`character.js`，`MV.page({ W: 2400, H: 1600, … })` 把三视图、表情、动作排在一张大画布上
- **草图**：直接从 `mv/index.html` 出。镜头表先搭好，每个镜头先只画最能说明问题的那一瞬，用户确认了再补动作，画的就是正片会出的样子

```bash
node <skill>/scripts/render_frames.mjs --page styles/pixel.html --times 0 --out styles --name pixel
node <skill>/scripts/render_frames.mjs --page mv/sheet.html --times 0 --out . --name character-sheet
node <skill>/scripts/render_frames.mjs --page mv/index.html --times 2.1,6.8,11.5,15.0 --out sketches   # sketches/01.png、02.png…
python3 <skill>/scripts/contact_sheet.py --images sketches -o storyboard.png --cols 4 --width 480
```

## 声音

`render.mp4` 没有声音。`finalize_audio.py` 把原曲按原音量配上去（画面不重新压缩），打印原曲和成片的响度，差 1 dB 以上就是哪里被压小了。结尾要淡出加 `--fade-out 2`。用别的软件导出过的片子也一样，最后都过一遍它。成片比歌短、又没加 `--start` 时，它会提醒一句。

## 只做歌的一段

抖音、视频号常常只做副歌那 30–60 秒。起点、终点是歌里的秒数，写在 `song.md` 开头；成片秒 = 歌里的秒 − 起点，片长 = 终点 − 起点。

| 用在哪 | 怎么带 |
|---|---|
| `analyze_song.py` | `--offset -<起点> --end <终点>`：`song.js` 的时间都换成成片秒，`duration` 是片长，`start` 记下起点；打印的时刻后面括号里是成片秒。`song-analysis.json` 仍是歌里的秒。拍点沿用整首测的（片段改长改短，段里的拍点不变）；这段自己测的速度和整首差 2% 以上（中途变速、几段接起来的歌）会改用这段的，并打印出来。`hits` 是整首最重的 8 下截到这段里，页面要某一下当锚点按时间窗取，别取「最后一个」；`last_hit` 是这段自己的最后一下重音 |
| `srt2js.py` | `--offset -<起点>`（`--words` 的时间跟着一起挪） |
| 页面、预览、`render_frames.mjs` | 不用带：片长读 `MV.duration`，预览按 `song.js` 的 `start` 放歌，接完打印的配声音命令带好 `--start` |
| `finalize_audio.py` | `--start <起点>`，`render_frames.mjs` 接完打印的命令里带好了；试渲的一段带的是起点加这段在片子里的开始秒，也打印好了。确实从歌头开始写 `--start 0`，不再提醒 |
| `contact_sheet.py --srt` | `--offset -<起点>`（`lyrics.srt` 是歌里的秒） |
| `video_rhythm.py --analysis` | 分析里记了起点，自己会用；从歌头开始的写 `--offset 0`，成片比歌短也不再提醒 |
| 分镜、`--plan`、`--around`、`--times` | 一律写成片秒 |

## 拍子不对

- **BPM 按拍点算**：`analyze_song.py` 打印的 BPM 是拍点按序号拟合出来的，和拍点间隔对得上；librosa 自己估的那个数按帧取整，满拍的 DJ 歌上差 1–3 BPM（做过：128 报成 129.2，133.2 报成 136.0）
- **差一倍、锁成 3:4**：网上查到的 BPM 和测的差一倍或者 3:4、4:3，加 `--tempo-hint <查到的 BPM>`：只在它上下 8% 里找（原来只当起点，锁到 3:4 拉不回来；一首 75 BPM 的歌只测后半段时锁成 99.4，限定范围以后测出 74.8）
- **慢歌测成两倍**：减半以后，librosa 在两套隔一拍的拍点里挑起音更强的那套，常挑到军鼓那一半，拍点整体落在反拍上。减半后在预览里看小球是不是落在重拍上；落在反拍，就保留测出来的两倍那套，页面里每两拍当一拍用（`MV.beatTime(2 * n)`），小节按八拍算
- **小节第一拍按 4/4 猜**：常差 1–3 拍，「最重的几下」有时是军鼓的反拍。副歌、大转场的落点以「突然变化的地方」和自己听为准，别全信 `downbeats`
- **先查歌是不是原样的一首**：DJ 版、翻唱、上传者剪的版本很常见。做过的几种：一段约 29 秒的片段循环了 4 遍、接缝没接在拍上；前 69 秒是变速变调的剪辑、后面接原速原版；整首比原版慢 2.7%。听、看波形，量前后几段的速度和音高对不对得上，有接缝、有循环就记进 `song.md`，选段避开接缝或者自己重拼；只做一段时 `analyze_song.py` 会按这段自己测速度（见上一节）

## 速度参考

- Canvas 2D：很快。简单画面 960×540 渲 12 秒（360 帧）约 5 秒；1920×1080 约 0.06 秒一帧
- 带逐像素合成的 Canvas 2D（孔版印刷的网点、皮影戏的透光、水墨的洇）：1920×1080 一帧连存图约 0.1–0.45 秒（存网点 PNG 最慢）。开页面要先下字体、烤纸和纹理、缓存图层，约 3–7 秒
- p5.brush：慢在笔画多。笔画少的水彩画面 1920×1440 约 0.3 秒一帧；角色多、排线涂色的蜡笔画面在 4 核电脑上 1.5–2 秒一帧，转场那几拍两个镜头都要现画，能到 6 秒一帧。省时间：`templates/mv/p5brush.html` 已经按出图像素开 p5 画布、静背景按抖动版本缓存（镜头在慢推慢移时按盖住整段的机位画一张，贴的时候放大挪过去；推得多的镜头别缓存）、草稿 `--fps 12`、先只渲关键的几段
- 开了动态模糊的帧，n 个子帧就慢 n 倍
- 整支 MV 从开始到做完 7–10 小时（含用户看片提意见），改 4–9 版
- 先渲最难的 10–20 秒给用户看手感，再渲整片
- 几个 agent 共用一台机器渲染时（一般限同时 2 个渲染），排队可能等十几分钟（做过：一次等了约 12 分钟）：带时限的出图、试渲把排队时间算进去，长的渲染放后台

## 踩坑

| 现象 | 原因和办法 |
|---|---|
| 第一帧空白、某些帧没画完 | 画法是异步的（p5 v2 的 `redraw()`、等图片）却没等。`draw` 写成 async 并 `await`；要准备的东西放 `ready` |
| p5 页面一直等不到就绪、报 `could not resolve an active WEBGL sketch` | p5 进了全局模式：页面里有全局的 `draw`、`setup`、`preload` 函数，p5 就会自己进。用实例模式（`new p5(p => …)`、`brush.instance(p)`），自己的函数别叫这几个名字（模板里叫 `drawFrame`） |
| 转场一顿、像幻灯片换页 | 匀速插值、两个镜头没有重叠、落点不在拍上。照 `transitions.md`「在代码里怎么接」 |
| 甩镜时看到一个个分开的残影 | 动态模糊的子帧太少。按这一帧镜头走了多少像素定，大约 4 像素一个 |
| ffmpeg 接视频报 `Invalid data found` | 帧的扩展名和内容对不上（`.jpg` 里是 PNG）。`render_frames.mjs` 会按 `--format` 转；自己写 `renderAt` 时照传进来的 `{ format }` 出 |
| 找不到浏览器 | 装 Chrome、Edge 或 Chromium，或者设 `CHROME_PATH`；或者 `npm i puppeteer` |
| 竖屏的页面渲成了带黑边的横屏 | 页面没用 `MV.page`（脚本读不到 W×H），又没给 `--width --height`。给上尺寸 |
| 整段渲出来是空的、道具没了 | 往一行代码中间插了 `//` 注释，后半行被注掉。渲染前对每个 js 跑 `node --check`，渲的时候看有没有「页面报错」 |
| 某几个镜头一开头就报错 | 共用函数没定义、和库的全局名撞了。每个镜头至少抽一帧看 |
| 叠出两个角色、重影、东西忽隐忽现 | 分层叠了单独渲的角色视频，或者两张背景接力时画的东西不一致。改成一个画布一个镜头 |
| 状态切换跳一帧 | 连续动的画风里写了 `t < x ? A : B`。改成随时间渐变；闪光也要在 3 帧内亮起来（一秒 12 张的画风逐张换是对的，见 `character.md`） |
| 角色被关键帧补间拖着横穿画面 | 要瞬移的地方前面加一个停在原地的关键帧 |
| 水彩填色一闪一闪 | 填色的随机种子跟着时间变了。填色用固定种子，只让线条按 12fps 换 |
| 同一个 t 单独渲和顺着渲，差几个像素 | 浏览器会给画布开、关 GPU 加速，要读像素的画布结果会差几级。自己开的、要 `getImageData` 的画布用 `getContext('2d', { willReadFrequently: true })` 放在 CPU 上 |
| 暗角在超宽背景上出现假接缝 | 暗角按画面算，不按背景图算，最后整片叠 |
| 成片比原曲小 2 dB 左右 | 导出时被压了峰值。最后一律过 `finalize_audio.py` |
| 页面加载大图超时 | 资源多时等得久，`render_frames.mjs` 最多等 180 秒 |
| 在命令或回复里打出整段歌词被拦 | 内容过滤。脚本读文件，回复里只说第几句 |
| p5.brush 笔触颜色串了 | 同一帧里用 `brush.load()` 换了画布（p5.brush 2.2.3）。分层画时每层自己一块不透明的纸底，画完再叠 |
| p5.brush 某条线没画出来，也不报错 | `brush.spline` 只给两个点时什么都不画，用 `brush.line` |
| 只做一段，成片的声音对不上 | `finalize_audio.py` 没加 `--start`，配上的是歌的开头。照 `render_frames.mjs` 接完打印的命令配 |
| 只做一段，后面一大截全黑 | `--duration` 写成了歌长。不写，用页面的片长 |
| 改了角色、颜色，渲出来还是旧的 | 已经渲好的帧会跳过。用到的镜头 `--force` 重渲 |
| 字体看着对，换台电脑渲出来字不一样、折行变了 | 用了系统字体，或者网页字体没下到悄悄退回了系统字体。用网页字体，`ready` 里 `MV.font` 等它（没下到会报出来）；别用 `document.fonts.check()` 判断 |
| 同一个字有的帧有、有的帧是系统字体 | 笔画数据渲染时现从网上取，有的进程没取到。先 `glyphs.py` 存成本地 `glyphs.js` |
| 歌词里有空格的句子，空格后面的字晚出来 | 老 kit 把空格也算一个字位。换新的 `kit.js` |
| 歌词出得比唱的晚一帧 | 字在开唱那一刻才开始弹，开唱那一帧画得几乎是空的。有逐字时间时 kit 提前 0.04 秒弹；自己画的写法也提前一点，用 `--lyric-check` 核 |
