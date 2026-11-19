# 第三方工具和库

本项目不打包下面这些，用到时由 pip、npm 或 CDN 获取，各自遵守自己的许可：

- p5.js（LGPL-2.1，模板从 jsDelivr 加载）：<https://github.com/processing/p5.js>
- p5.brush（MIT，模板从 jsDelivr 加载）：<https://github.com/acamposuribe/p5.brush>
- librosa（ISC）：<https://github.com/librosa/librosa>
- NumPy（BSD-3-Clause）、Pillow（MIT-CMU）
- FFmpeg（LGPL / GPL，看你装的版本）：<https://ffmpeg.org>
- Whisper（MIT，可选）：<https://github.com/openai/whisper>
- Puppeteer（Apache-2.0，逐帧渲染用）：<https://github.com/puppeteer/puppeteer>
- 思源黑体 Noto Sans SC（OFL-1.1，模板歌词的默认字体，从 jsDelivr 的 @fontsource/noto-sans-sc 加载）：<https://fontsource.org/fonts/noto-sans-sc>
- hanzi-writer-data（汉字笔顺数据，Arphic Public License）：`scripts/glyphs.py` 和 `kit.js` 的 `MV.glyphs` 从 jsDelivr 取，存下来的 `glyphs.js` 留在你自己的项目里用：<https://github.com/chanind/hanzi-writer-data>

`examples/` 里的示范页面另外从 jsDelivr 加载：

- 缝合像素字体 Fusion Pixel Font（OFL-1.1，像素风的字）：<https://github.com/TakWolf/fusion-pixel-font>
- 霞鹜文楷 LXGW WenKai（字体 OFL-1.1，网页字体包 MIT，拼贴风、纸艺立体书的歌词）：<https://github.com/lxgw/LxgwWenKai>
- hanzi-writer-data（汉字笔顺数据，Arphic Public License，蜡笔风、中国水墨、一笔画按笔顺一笔笔写歌词）：<https://github.com/chanind/hanzi-writer-data>
- 站酷庆科黄油体 ZCOOL QingKe HuangYou（OFL-1.1，1930s 橡皮管卡通的字卡）：<https://fontsource.org/fonts/zcool-qingke-huangyou>
- 思源宋体 Noto Serif SC（OFL-1.1，浮世绘的题签、皮影戏的刻字牌）：<https://fontsource.org/fonts/noto-serif-sc>
- 得意黑 Smiley Sans（字体 OFL-1.1，中文网字计划的网页字体包 `@chinese-fonts/dyh` 是 MIT，Risograph 孔版印刷的歌词）：<https://github.com/atelier-anchor/smiley-sans>

歌曲、歌词、参考视频的版权归各自的作者。本工具只在你的电脑上处理你提供的文件。

## README 里的示例画面

`docs/mv-*.gif` 来自作者用这套流程做的两支 MV（《每一秒初吻》《把回忆拼好给你》），没有声音。画面里的方块角色是 Clawd，Anthropic 为 Claude Code 设计的形象；这里是非官方的同人画法，与 Anthropic 没有隶属或背书关系。Claude、Claude Code、Clawd 相关商标和形象归 Anthropic 所有。skill 本身不含 Clawd 的素材，做 MV 时用你自己的角色。画面里的歌词归歌曲的原作者。

`docs/style-pixel.gif`、`style-collage.gif`、`style-crayon.gif`、`style-diorama.gif`、`style-ink-wash.gif`、`style-shadow-puppet.gif`、`style-risograph.gif` 来自作者用这个 skill 做的七支 MV（依次是《心墙》《把回忆拼好给你》《雨爱》《如果可以》《咏春》《西厢寻他》《寂寞烟火》），各截 6 秒，没有声音。角色是为这几支 MV 画的；画面里的歌词归歌曲的原作者。

`docs/style-ukiyoe.gif`、`style-rubber-hose.gif`、`style-one-line.gif` 和 `examples/` 里的场景、角色和歌词是本项目原创的，十个示范的歌词依次是：「冲过水洼，海风都追不上我」「一路小跑，追上早晨」「一起把雨踩成彩虹」「提着灯，走回你的门口」「一篙点破晨雾，白鹭飞成一笔」「锣鼓一响，狮子醒了」「雨停在桥的那一头」「晚风在晾衣绳上打拍子」「趁咖啡还热，转个圈吧」「窗台那朵花，飞到你指尖」。
