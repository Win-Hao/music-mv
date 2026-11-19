#!/usr/bin/env node
// 逐帧渲画面：用无头 Chrome 打开一个网页，按时间一帧一帧调它的 window.renderAt(t)（可以是 async），存成图片，再接成视频。
// 整支 MV 就是这么出来的：画面、转场、歌词都在页面里画好，这里只负责截图和接视频；配歌用 finalize_audio.py。
// 也用来出静态图：画风样图、角色设定图、草图（--times）。
//
//   node scripts/render_frames.mjs --page mv/index.html --out frames --encode render.mp4                     # 片长不给就用页面的 MV.duration
//   node scripts/render_frames.mjs --page mv/index.html --fps 30 --duration 16 --out frames --encode render.mp4   # 给了 --duration 就按它渲（只做歌的一段时写片长，不是歌长）
//   node scripts/render_frames.mjs --page mv/index.html --out frames --from 20 --to 35                       # 先渲最难的一段看
//   node scripts/render_frames.mjs --page mv/index.html --out frames --from 12 --to 18 --force               # 只重渲改过的一段
//   node scripts/render_frames.mjs --page mv/index.html --out frames --from 12 --to 18 --encode review/part.mp4   # 只把这一段接成视频，打印带 --start 的配声音命令
//   node scripts/render_frames.mjs --page mv/index.html --fps 15 --width 960 --height 540 --out draft --encode review/draft.mp4   # 草稿：半分辨率、15 fps（竖屏 --width 540 --height 960）
//   node scripts/render_frames.mjs --page mv/index.html --out frames --encode render.mp4 --preset slow       # 定稿想更小一点（慢）
//   node scripts/render_frames.mjs --page mv/index.html --times 2.1,6.8,11.5 --out sketches                 # 只出这几个时刻的图：sketches/01.png、02.png…
//   node scripts/render_frames.mjs --page styles/pixel.html --times 0 --out styles --name pixel              # 一张样图 styles/pixel.png（--name 只在一个时刻时有用）
//   node scripts/render_frames.mjs --page "styles/all.html?style=pixel" --times 0 --out styles --name pixel  # ? 后面的查询参数是给页面自己读的（页面里用 location.search 取）
//   node scripts/render_frames.mjs --page mv/index.html --lyric-check                                       # 按帧核逐字歌词：每个字开唱那一帧看不看得见（不出图）
//
// 网页要求：
//   - 画面大小：给了 --width/--height 就用它；没给就用页面的 MV.W × MV.H（MV.page 竖屏的页面自动出 1080×1920）；都没有就 1920×1080。页面左上角对齐
//   - 片长：给了 --duration 就用它；没给就用页面的 MV.duration（MV.page 设的）。--from/--to 都是成片秒
//   - window.SONG.start、SONG.file（analyze_song.py --js 写的片头在歌里的秒数、分析的是哪个音频）：接完打印配声音的命令用它们
//   - window.PLAN（可选，转场落点的成片秒）：每项是一个数（落点），或者 '起-落' / [起, 落] 一段（眨眼、收光这种合上再张开的）。开头打印出来，给 video_rhythm.py --plan、contact_sheet.py --around 用
//   - window.sceneReady：true，或者一个 Promise（字体、图片、画布准备好了再 resolve）。10 秒内要设上，不然当页面坏了
//   - window.renderAt = async (t, { format }) => { ... }：把 t 秒的画面画好。返回 'data:image/...' 就存它（格式不对会自动转）；不返回就截整个视口
//   - 画面只由 t 决定（随机数用「元素名 + 序号」做种子），这样能多进程渲、能只重渲一段
// 页面的警告、报错、没加载到的文件（lyrics.js、song.js、字体……）会打在终端里，每个进程的都打，同一句只打一次。
// 某一帧出错，这个进程会重新打开页面再接着渲；渲完把出错的帧再补渲两轮（偶发的超时这样就补上了）。还是失败的帧不存，
// 硬盘上这一帧的旧图也删掉（不然下次会被当成渲好的跳过），这次不接视频；修好再跑一次会补上。
// --encode 接视频：x264，crf 16，--preset 默认 medium（slow 更小但慢很多）。给了 --from/--to 就只接这一段（只要这段的帧齐），不给就接整片。
// 帧默认存 jpg（小、快）；网点、细线这类怕 JPEG 糊的画风用 --format png。
// 已经渲好的帧会跳过（断了重跑接着渲），--force 重渲范围内的帧。
// 要 puppeteer：在项目文件夹里 npm i puppeteer-core（小，用本机的 Chrome、Edge 或 Chromium，找不到就设 CHROME_PATH）；
// 或者 npm i puppeteer（会自己下载一个 Chrome）。接视频要 ffmpeg（不在 PATH 里就设 FFMPEG）。
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';
import { pathToFileURL, fileURLToPath } from 'url';
import { spawnSync } from 'child_process';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => {
  if (a.startsWith('--')) acc.push([a.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : true]);
  return acc;
}, []));
const need = (k) => { if (args[k] === undefined) { console.error(`缺 --${k}`); process.exit(1); } return args[k]; };
const pageArg = String(need('page'));
const qi = pageArg.indexOf('?');
const pageFile = qi < 0 ? pageArg : pageArg.slice(0, qi), pageQuery = qi < 0 ? '' : pageArg.slice(qi + 1);
const page = path.resolve(pageFile);
if (!fs.existsSync(page)) { console.error(`找不到页面：${page}`); process.exit(1); }
const pageUrl = pathToFileURL(page).href + (pageQuery ? '?' + pageQuery : '');
const fps = Number(args.fps || 30);
const times = args.times !== undefined ? String(args.times).split(',').map(Number).filter((x) => !Number.isNaN(x)) : null;
const durArg = args.duration !== undefined && args.duration !== true ? Number(args.duration) : null;
if (durArg !== null && !(durArg > 0)) { console.error('--duration 要写成片的秒数（正数）'); process.exit(1); }
const out = path.resolve(args.out || 'frames');
let W = args.width ? Number(args.width) : 0, H = args.height ? Number(args.height) : 0;
const workers = Number(args.workers || 2);
const fmt = args.format === 'png' || (times && args.format !== 'jpg') ? 'png' : 'jpg';
const mime = fmt === 'png' ? 'image/png' : 'image/jpeg';
const part = !times && (args.from !== undefined || args.to !== undefined);   // 只渲 / 只接一段
const preset = String(args.preset || 'medium');
if (args.encode && !times && W && H && (W % 2 || H % 2)) { console.error('宽高要是偶数（视频编码要求）'); process.exit(1); }
if (times && args.name && times.length > 1) console.warn('⚠ --name 只在一个时刻时有用，多张按 01、02… 编号');
const showUrl = (u) => { try { return decodeURI(u); } catch { return u; } };
const name = (n) => path.join(out, (times ? (args.name && times.length === 1 ? String(args.name) : String(n + 1).padStart(2, '0')) : String(n).padStart(6, '0')) + '.' + fmt);
const timeOf = (n) => (times ? times[n] : n / fps);
const secs = (x) => String(+Number(x).toFixed(3));   // 秒数写短：16、24.5、7.033
let dur = 0, total = 0, from = 0, to = 0;   // 页面就绪后定（没给 --duration 时要读页面的 MV.duration）
const rel = (p) => { const r = path.relative(process.cwd(), p); return (r && !path.isAbsolute(r) ? r : p).split(path.sep).join('/'); };
const quote = (s) => (/[\s#&()]/.test(s) ? `"${s}"` : s);

// window.PLAN 的一项 → video_rhythm.py --plan 的写法：一个数是落点，'起-落' 或 [起, 落] 是一段（眨眼、收光）；看不懂的返回 null
function planItem(p) {
  if (typeof p === 'number') return Number.isFinite(p) ? secs(p) : null;
  if (Array.isArray(p) && p.length === 2 && p.every((x) => x !== null && x !== '' && Number.isFinite(Number(x)))) return `${secs(p[0])}-${secs(p[1])}`;
  if (typeof p === 'string') {
    const s = p.trim(), m = s.match(/^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$/);
    if (m) return `${secs(m[1])}-${secs(m[2])}`;
    if (/^\d+(?:\.\d+)?$/.test(s)) return secs(s);
  }
  return null;
}
// 配声音的命令里写哪个 Python：激活着的虚拟环境 > 当前文件夹往上找到的 .venv > Windows 的 py -3、别的系统的 python3
function pyCmd() {
  const win = process.platform === 'win32', exe = (d) => path.join(d, win ? 'Scripts/python.exe' : 'bin/python');
  const cand = process.env.VIRTUAL_ENV ? [exe(process.env.VIRTUAL_ENV)] : [];
  for (let d = process.cwd(), i = 0; i < 6; i++) { cand.push(exe(path.join(d, '.venv'))); const up = path.dirname(d); if (up === d) break; d = up; }
  const hit = cand.find((p) => fs.existsSync(p));
  return hit ? quote(rel(hit)) : win ? 'py -3' : 'python3';
}
// 配哪首歌：页面 SONG.file（analyze_song.py 分析的那个文件）在当前文件夹里就用它，不然找 song.mp3、wav、m4a…；都没有就留个空让人填
function songArg(file) {
  const hit = [file, ...['mp3', 'wav', 'm4a', 'flac', 'aac', 'ogg'].map((x) => 'song.' + x)].filter(Boolean).find((f) => fs.existsSync(path.resolve(f)));
  return hit ? quote(rel(path.resolve(hit))) : '<歌的路径>';
}
// 配好声音的成片叫什么：render.mp4 → mv-r1.mp4（交给用户的每一版存一个，已有的往后排）；render-xxx.mp4 → mv-xxx.mp4；别的 → 原名-audio.mp4
function finalName(dst) {
  const dir = path.dirname(dst), base = path.basename(dst).replace(/\.[^.]+$/, '');
  if (base === 'render') { let k = 1; while (fs.existsSync(path.join(dir, `mv-r${k}.mp4`))) k++; return path.join(dir, `mv-r${k}.mp4`); }
  return path.join(dir, (base.startsWith('render') ? 'mv' + base.slice(6) : base + '-audio') + '.mp4');
}

function loadPuppeteer() {
  const req = createRequire(path.join(process.cwd(), 'noop.js'));
  for (const mod of ['puppeteer', 'puppeteer-core']) {
    try { return { mod, lib: req(mod) }; } catch { /* 试下一个 */ }
  }
  console.error('找不到 puppeteer：在项目文件夹里 npm i puppeteer-core（用本机的 Chrome / Edge），或 npm i puppeteer（装之前问一下用户）');
  process.exit(1);
}
function chromePath() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const pf = process.env.ProgramFiles || 'C:/Program Files', pf86 = process.env['ProgramFiles(x86)'] || 'C:/Program Files (x86)';
  const local = process.env.LOCALAPPDATA || '';
  return [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/microsoft-edge',
    path.join(pf, 'Google/Chrome/Application/chrome.exe'), path.join(pf86, 'Google/Chrome/Application/chrome.exe'),
    local && path.join(local, 'Google/Chrome/Application/chrome.exe'),
    path.join(pf86, 'Microsoft/Edge/Application/msedge.exe'), path.join(pf, 'Microsoft/Edge/Application/msedge.exe'),
  ].find((p) => p && fs.existsSync(p));
}

fs.mkdirSync(out, { recursive: true });
const todo = [];
let songStart = 0;   // 片头在歌里的秒数（页面的 SONG.start），配声音的 --start 用

class PageFail extends Error {}

// 打开页面并等它就绪：先等 window.sceneReady 出现（最多 10 秒，期间页面脚本报错就立刻放弃），再等它 resolve（最多 180 秒）
async function openPage(p, errs) {
  errs.length = 0;
  await p.goto(pageUrl, { waitUntil: 'load', timeout: 180000 });
  await p.addStyleTag({ content: 'html, body { margin: 0 !important; padding: 0 !important; overflow: hidden; }' });   // 浏览器默认 8px 边距会让画面错位
  const t0 = Date.now();
  for (;;) {
    if (errs.length) throw new PageFail(`页面脚本报错，没能就绪：${errs[0]}`);
    if (await p.evaluate(() => 'sceneReady' in window)) break;
    if (Date.now() - t0 > 10000) throw new PageFail('页面 10 秒内没有设置 window.sceneReady：多半是脚本语法错误、CDN 没加载到，或者页面没调 MV.page');
    await new Promise((r) => setTimeout(r, 100));
  }
  const err = await p.evaluate(async () => {
    const ready = Promise.resolve(window.sceneReady);
    const timeout = new Promise((_, rej) => setTimeout(() => rej(new Error('等了 180 秒还没好')), 180000));
    try { await Promise.race([ready, timeout]); return null; } catch (e) { return String(e && e.message || e); }
  });
  if (err) throw new PageFail(`页面准备（ready）出错：${err}`);
}

const { mod, lib } = loadPuppeteer();
// protocolTimeout：一帧最多等 10 分钟（puppeteer 默认 3 分钟，机器忙、画面重时偶尔有一帧超时）
const opts = { headless: true, protocolTimeout: 600000, args: ['--allow-file-access-from-files', '--ignore-gpu-blocklist', '--enable-gpu-rasterization'] };
if (mod === 'puppeteer-core') {
  opts.executablePath = chromePath();
  if (!opts.executablePath) { console.error('puppeteer-core 要用本机的 Chrome / Edge / Chromium：没找到，设 CHROME_PATH 指向它'); process.exit(1); }
}
const browser = await lib.launch(opts);
let code = 0, encodeOk = true;
let songFile = '', hasSong = false;   // 页面的 SONG.file（analyze_song.py 分析的是哪个音频）、页面有没有 window.SONG
try {
  const pages = [];
  const said = new Set();
  const say = (msg) => { if (!said.has(msg)) { said.add(msg); console.error(msg); } };   // 几个进程报同一句只打一次
  async function newPage(id) {
    const p = await browser.newPage();
    const errs = [];
    p.on('pageerror', (e) => { errs.push(e.message); console.error(`[进程${id}] 页面报错：${e.message}`); });
    // 每个进程的提示都转发（第 2 个进程字体没加载到也看得见），同一句只打一次
    p.on('console', (m) => {
      const ty = m.type();
      if (!['warning', 'warn', 'error'].includes(ty) || m.text().startsWith('Failed to load resource')) return;   // 加载失败下面单独报
      say(`页面提示：${m.text()}`);
    });
    p.on('requestfailed', (r) => say(`加载失败：${showUrl(r.url())}（${r.failure()?.errorText || '原因不明'}）`));
    p.on('response', (r) => { if (r.status() >= 400) say(`加载失败：${showUrl(r.url())}（HTTP ${r.status()}）`); });
    return { p, errs, id };
  }
  // 第 1 个进程先打开页面，读页面的 MV.W × MV.H、MV.duration、SONG.start、PLAN（帧都渲好了、只接视频时也要读：片长和配声音的 --start 靠它）
  const first = await newPage(1);
  await first.p.setViewport({ width: W || 1920, height: H || 1080, deviceScaleFactor: 1 });
  await openPage(first.p, first.errs);
  const info = await first.p.evaluate(() => {
    const mv = window.MV, song = window.SONG;
    return {
      size: mv && mv.W && mv.H ? [Number(mv.W), Number(mv.H)] : null,
      dur: mv && Number(mv.duration) > 0 ? Number(mv.duration) : null,
      start: song && Number(song.start) > 0 ? Number(song.start) : 0,
      song: !!song, file: song && typeof song.file === 'string' ? song.file : '',
      plan: Array.isArray(window.PLAN) ? JSON.parse(JSON.stringify(window.PLAN)) : null,
    };
  });
  songStart = info.start; songFile = info.file; hasSong = info.song;
  if (info.plan && info.plan.length) {
    const items = info.plan.map(planItem), bad = info.plan.filter((_, i) => items[i] === null);
    console.log(`页面的转场落点（--plan、--around 用）：${items.filter(Boolean).join(',')}`);
    if (bad.length) console.warn(`⚠ window.PLAN 里有 ${bad.length} 项看不懂（${JSON.stringify(bad[0])}）：一个落点写数，一段写 '起-落' 或 [起, 落]`);
  }
  if (args['lyric-check']) {
    // 按帧核逐字歌词：页面（kit.js 的 window.lyricCheck）只画歌词层，看每个字开唱那一帧是不是已经出来、开唱前 0.08 秒以前是不是还没出来。不出图
    const o = { from: args.from !== undefined ? Number(args.from) : 0 };
    if (args.to !== undefined) o.to = Number(args.to);
    const r = await first.p.evaluate(async (oo) => (window.lyricCheck ? window.lyricCheck(oo)
      : { error: '页面没有 window.lyricCheck：页面用的 kit.js 是旧的（从 templates/mv 重新拷一份），或者页面没用 MV.page' }), o);
    if (r.error) throw new PageFail(`核不了逐字歌词：${r.error}`);
    const pos = (x) => `第 ${x.line} 句第 ${x.char} 字（开唱 ${secs(x.t)} 秒）`;
    console.log(`逐字歌词按帧核（${r.fps} fps，成片 ${secs(r.from)}–${secs(r.to)} 秒）：有逐字时间的 ${r.lines} 句、${r.chars} 个字，开唱那一帧已经看得见的 ${r.ok} 个`);
    if (r.late.length) {
      console.log(`- 晚了 ${r.late.length} 个（开唱那一帧还没有，或者只画出一点点）：`);
      for (const x of r.late.slice(0, 20)) console.log(`  ${pos(x)}：第 ${x.frame} 帧还没有，${x.frames ? `晚 ${x.frames} 帧才出来` : '之后几帧也没出来'}`);
      if (r.late.length > 20) console.log(`  ……还有 ${r.late.length - 20} 个`);
    }
    if (r.early.length) {
      console.log(`- 早了 ${r.early.length} 个（开唱前 0.08 秒以前就出来了）：`);
      for (const x of r.early.slice(0, 20)) console.log(`  ${pos(x)}：第 ${x.frame} 帧就有了`);
    }
    if (r.unknown.length) console.log(`- 核不了 ${r.unknown.length} 个（这个字在歌词层里差不出来：页面没用 MV.lyricAt 出字，或者歌词没画在 overlay 里），第一个是${pos(r.unknown[0])}`);
    if (r.untimed) console.log(`- 没有逐字时间的 ${r.untimed} 句没核（照旧按固定间隔出字；要逐字就用 srt2js.py --words 重出 lyrics.js）`);
    if (r.late.length || r.early.length) code = 1;
  } else {
    if (times) dur = Math.max(...times) + 1;
    else if (durArg) {
      dur = durArg;
      if (info.dur && Math.abs(info.dur - dur) >= 0.5) console.warn(`⚠ 页面的片长是 ${secs(info.dur)} 秒，你给的是 ${secs(dur)} 秒（只做一段时写片长，不是歌长）`);
    } else if (info.dur) {
      dur = info.dur;
      console.log(`片长 ${dur.toFixed(2)} 秒（页面的 MV.duration）`);
    } else throw new PageFail('缺 --duration（页面没有 MV.duration）');
    total = Math.round(dur * fps);
    from = Math.max(0, Math.floor(Number(args.from || 0) * fps + 1e-6));
    to = Math.min(total, args.to !== undefined ? Math.ceil(Number(args.to) * fps - 1e-6) : total);
    if (!times && to <= from) throw new PageFail(`--from/--to 之间没有帧（片长 ${secs(dur)} 秒）`);
    if (times) times.forEach((_, n) => todo.push(n));
    else for (let n = from; n < to; n++) if (args.force || !fs.existsSync(name(n))) todo.push(n);
    console.log(times ? `出 ${times.length} 张图：${times.join('、')} 秒`
      : `共 ${total} 帧（${secs(dur)} 秒 × ${fps}），这次渲 ${todo.length} 帧` + (todo.length ? `，${workers} 个进程` : '（范围里的帧都渲好了）'));
  }

  if (todo.length) {
    let src = '--width/--height';
    if (!W || !H) {
      if (info.size) { W = W || info.size[0]; H = H || info.size[1]; src = '页面的 MV.W×MV.H'; } else { W = W || 1920; H = H || 1080; src = '默认'; }
    }
    console.log(`画面 ${W}×${H}（${src}）`);
    if (args.encode && !times && (W % 2 || H % 2)) throw new PageFail('宽高要是偶数（视频编码要求）');
    const vp = first.p.viewport();
    if (vp.width !== W || vp.height !== H) { await first.p.setViewport({ width: W, height: H, deviceScaleFactor: 1 }); await openPage(first.p, first.errs); }
    pages.push(first);
    for (let id = 2; id <= Math.max(1, workers); id++) {
      const pg = await newPage(id);
      await pg.p.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
      pages.push(pg);
    }
    await Promise.all(pages.slice(1).map((pg) => openPage(pg.p, pg.errs)));

    const failed = new Map();   // 帧号 → 最后一次的错
    let queue = todo.slice(), done = 0;
    const t0 = Date.now();
    async function worker({ p, errs }, show) {
      while (queue.length) {
        const n = queue.shift();
        const t = timeOf(n);
        try {
          const url = await p.evaluate(async (tt, mt) => {
            const r = await window.renderAt(tt, { format: mt });
            if (typeof r !== 'string' || !r.startsWith('data:image')) return null;
            if (r.startsWith('data:' + mt)) return r;
            // 页面给的格式和要存的不一样（比如给 PNG、要存 jpg）：在页面里转一下，免得文件后缀和内容对不上、ffmpeg 接不起来
            const img = new Image(); img.src = r; await img.decode();
            const c = document.createElement('canvas'); c.width = img.naturalWidth; c.height = img.naturalHeight;
            const g = c.getContext('2d');
            if (mt === 'image/jpeg') { g.fillStyle = '#000'; g.fillRect(0, 0, c.width, c.height); }
            g.drawImage(img, 0, 0);
            return c.toDataURL(mt, 0.92);
          }, t, mime);
          if (url) fs.writeFileSync(name(n), Buffer.from(url.split(',')[1], 'base64'));
          else await p.screenshot({ path: name(n), type: fmt === 'png' ? 'png' : 'jpeg', quality: fmt === 'png' ? undefined : 92, clip: { x: 0, y: 0, width: W, height: H } });
          failed.delete(n);
        } catch (e) {
          failed.set(n, e.message);
          console.error(`\n第 ${n} 帧（${t.toFixed(3)} 秒）失败：${e.message}`);
          // 出过错的页面状态不可信：重新打开、等就绪，再接着渲后面的帧
          await openPage(p, errs);
        }
        if (!show) continue;
        done++;
        if (done % 50 === 0 || !queue.length) {
          const s = (Date.now() - t0) / 1000;
          process.stdout.write(`\r${done}/${todo.length} 帧，${(s / done).toFixed(2)} 秒/帧，还要约 ${Math.round(s / done * (todo.length - done) / 60)} 分钟   `);
        }
      }
    }
    await Promise.all(pages.map((pg) => worker(pg, true)));
    // 出错的帧再补渲两轮：偶发的超时、显存不够这样就补上了，不用整条命令重跑
    for (let round = 1; round <= 2 && failed.size; round++) {
      console.log(`\n补渲出错的 ${failed.size} ${times ? '张' : '帧'}（第 ${round} 轮）`);
      queue = [...failed.keys()];
      await Promise.all(pages.map((pg) => worker(pg, false)));
    }
    const unit = times ? '张' : '帧';
    console.log(`\n渲完 ${todo.length - failed.size} ${unit}${times ? '：' + out : ''}`);
    if (failed.size) {
      // 还是失败的：硬盘上这一帧的旧图删掉（--force 重渲时旧图还在，不删就会被当成渲好的、接进视频里），这次不接视频
      const bad = [...failed.keys()].sort((a, b) => a - b);
      let stale = 0;
      for (const n of bad) if (fs.existsSync(name(n))) { fs.rmSync(name(n)); stale++; }
      console.error(`⚠ 补渲两轮还是失败 ${bad.length} ${unit}：${bad.slice(0, 12).map((n) => `第 ${n} ${unit}（${timeOf(n).toFixed(3)} 秒）`).join('、')}${bad.length > 12 ? '……' : ''}`);
      console.error(`  最后一次的错：${failed.get(bad[0])}`);
      if (stale) console.error(`  这些${unit}硬盘上之前渲的旧图删掉了 ${stale} 张（不然下次会被当成渲好的跳过、接进视频里）`);
      console.error(`  修好再跑一次同样的命令会补上${args.encode && !times ? '；这次不接视频' : ''}`);
      encodeOk = false;
      code = 1;
    }
  }
} catch (e) {
  console.error(e instanceof PageFail ? e.message : `渲染出错：${e.message}`);
  code = 1; encodeOk = false;
} finally {
  await browser.close().catch(() => {});
}
if (code) process.exit(code);

if (args.encode && !times && !args['lyric-check']) {
  // 给了 --from/--to 只接这一段，不然接 0..total-1（片子改短了，多出来的旧帧不会混进去）
  const r0 = part ? from : 0, r1 = part ? to : total;
  const missing = [];
  for (let n = r0; n < r1; n++) if (!fs.existsSync(name(n))) missing.push(n);
  if (missing.length) { console.error(`还缺 ${missing.length} 帧（第一个是第 ${missing[0]} 帧），先补渲再接`); process.exit(1); }
  const dst = path.resolve(args.encode);
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  // 接出来没有声音，下一步 finalize_audio.py 配上原曲
  const r = spawnSync(process.env.FFMPEG || 'ffmpeg', ['-v', 'error', '-y', '-framerate', String(fps), '-start_number', String(r0), '-i', path.join(out, '%06d.' + fmt),
    '-frames:v', String(r1 - r0),
    '-c:v', 'libx264', '-preset', preset, '-crf', '16', '-pix_fmt', 'yuv420p', '-g', String(Math.round(fps * 2)),
    '-movflags', '+faststart', dst], { stdio: 'inherit' });
  if (r.error) { console.error(`跑不了 ffmpeg：${r.error.message}（装上 ffmpeg，或者设 FFMPEG 指向它）`); process.exit(1); }
  if (r.status) process.exit(r.status);
  // 配声音的命令照这台电脑、这个文件夹写好：Python、歌的文件名、起点、成片名都按实际的来，直接复制能跑
  const py = pyCmd(), song = songArg(songFile);
  const fin = quote(rel(path.join(path.dirname(fileURLToPath(import.meta.url)), 'finalize_audio.py')));
  const st = songStart + (part ? r0 / fps : 0);
  const o = part ? rel(dst).replace(/\.[^./]+$/, '') + '-audio.mp4' : rel(finalName(dst));
  console.log(part ? `接好了：${dst}（只接了成片 ${secs(r0 / fps)}–${secs(r1 / fps)} 秒这段，${r1 - r0} 帧，没有声音）` : `接好了：${dst}（没有声音）`);
  const startArg = hasSong || part ? ` --start ${secs(st)}` : '';   // 页面没有 SONG 不知道起点：整片不写 --start，让 finalize_audio.py 按片长提醒
  console.log(`${part ? '配声音' : '下一步'}：${py} ${fin} ${quote(rel(dst))} ${song} -o ${quote(o)}${startArg}`);
  if (part) console.log(`  --start ${secs(st)} = 片头在歌里的 ${secs(songStart)} 秒（页面的 SONG.start）+ 这段从成片第 ${secs(r0 / fps)} 秒起`);
  else if (songStart > 0) console.log(`  --start ${secs(st)} = 片头在歌里的秒数（页面的 SONG.start）`);
  if (!hasSong) console.log('  页面没有 song.js（window.SONG），不知道片头在歌里第几秒：只做歌的一段就加 --start <片头在歌里的秒数>');
  if (song === '<歌的路径>') console.log('  当前文件夹里没找到歌（song.mp3、song.wav…），把 <歌的路径> 换成你的歌');
}
