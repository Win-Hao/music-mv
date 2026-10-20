#!/usr/bin/env node
// 逐帧渲画面：打开一个网页，按时间一帧一帧调它的 window.renderAt(t)（可以是 async），存成图片，再接成视频。
// 两个用处：
//   1. 路线 B：画一帧要等的画法（p5.js v2 + p5.brush 这类 WebGL、异步重画、一帧要零点几秒的）先渲成视频，再进 HyperFrames 叠歌词
//   2. 出静态图：画风样图、角色设定图、草图（--times，任何画法都能用）
// 能同步画完的整片（Canvas 2D、SVG、DOM）直接写在 HyperFrames 合成里，不用这个。
//
//   node scripts/render_frames.mjs --page scene.html --fps 30 --duration 58.7 --out frames
//   node scripts/render_frames.mjs --page scene.html --fps 30 --duration 58.7 --out frames --from 12 --to 18 --force   # 只重渲改过的一段
//   node scripts/render_frames.mjs --page scene.html --fps 30 --duration 58.7 --out frames --encode scene.mp4         # 渲完接成视频
//   node scripts/render_frames.mjs --page sketch.html --times 2.1,6.8,11.5 --out sketches                              # 只出这几个时刻的图：sketches/01.png、02.png…
//   node scripts/render_frames.mjs --page "styles.html?style=pixel" --times 0 --out styles --name pixel                 # 一张样图 styles/pixel.png（页面按 ?style= 画）
//
// 网页要求：
//   - 画面大小 = --width × --height（默认 1920×1080），页面左上角对齐
//   - window.sceneReady：true，或者一个 Promise（字体、图片、画布准备好了再 resolve）
//   - window.renderAt = async (t) => { ... }：把 t 秒的画面画好。返回 'data:image/...' 就存它；不返回就截整个视口
//   - 画面只由 t 决定（随机数用 t 做种子），这样能多进程渲、能只重渲一段
// 已经渲好的帧会跳过（断了重跑接着渲），--force 重渲范围内的帧。
// 要 puppeteer：在项目文件夹里 npm i puppeteer-core（小，用本机的 Chrome：装过 Chrome，或者跑过 npx hyperframes 下载过的都能自动找到，
// 找不到就设 CHROME_PATH）；或者 npm i puppeteer（会自己下载一个 Chrome）。
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';
import { spawnSync } from 'child_process';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => {
  if (a.startsWith('--')) acc.push([a.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : true]);
  return acc;
}, []));
const need = (k) => { if (args[k] === undefined) { console.error(`缺 --${k}`); process.exit(1); } return args[k]; };
const [pageFile, pageQuery] = String(need('page')).split('?');
const page = path.resolve(pageFile);
const fps = Number(args.fps || 30);
const times = args.times !== undefined ? String(args.times).split(',').map(Number).filter((x) => !Number.isNaN(x)) : null;
const dur = times ? Math.max(...times) + 1 : Number(need('duration'));
const out = path.resolve(args.out || 'frames');
const W = Number(args.width || 1920), H = Number(args.height || 1080);
const workers = Number(args.workers || 2);
const fmt = args.format === 'png' || (times && args.format !== 'jpg') ? 'png' : 'jpg';
const total = Math.round(dur * fps);
const from = Math.max(0, Math.floor(Number(args.from || 0) * fps));
const to = Math.min(total, args.to !== undefined ? Math.ceil(Number(args.to) * fps) : total);
const name = (n) => path.join(out, (times ? (args.name && times.length === 1 ? String(args.name) : String(n + 1).padStart(2, '0')) : String(n).padStart(6, '0')) + '.' + fmt);
const timeOf = (n) => (times ? times[n] : n / fps);

function loadPuppeteer() {
  const req = createRequire(path.join(process.cwd(), 'noop.js'));
  for (const mod of ['puppeteer', 'puppeteer-core']) {
    try { return { mod, lib: req(mod) }; } catch { /* 试下一个 */ }
  }
  console.error('找不到 puppeteer：在项目文件夹里 npm i puppeteer（装之前问一下用户）');
  process.exit(1);
}
function chromePath() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const sys = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome', '/usr/bin/chromium',
    '/usr/bin/chromium-browser', 'C:/Program Files/Google/Chrome/Application/chrome.exe'].find((p) => fs.existsSync(p));
  if (sys) return sys;
  // npx hyperframes 第一次渲染时下载的无头 Chrome
  const home = process.env.HOME || process.env.USERPROFILE || '';
  const base = path.join(home, '.cache', 'hyperframes', 'chrome', 'chrome-headless-shell');
  if (fs.existsSync(base)) {
    for (const v of fs.readdirSync(base).sort().reverse()) {
      let subs = [];
      try { subs = fs.readdirSync(path.join(base, v)); } catch { continue; }
      for (const d of subs) {
        for (const exe of ['chrome-headless-shell', 'chrome-headless-shell.exe']) {
          const p = path.join(base, v, d, exe);
          if (fs.existsSync(p)) return p;
        }
      }
    }
  }
  return undefined;
}

fs.mkdirSync(out, { recursive: true });
const todo = [];
if (times) times.forEach((_, n) => todo.push(n));
else for (let n = from; n < to; n++) if (args.force || !fs.existsSync(name(n))) todo.push(n);
console.log(times ? `出 ${times.length} 张图：${times.join('、')} 秒` : `共 ${total} 帧（${dur} 秒 × ${fps}），这次渲 ${todo.length} 帧，${workers} 个进程`);

if (todo.length) {
  const { mod, lib } = loadPuppeteer();
  const opts = { headless: true, args: ['--allow-file-access-from-files', '--ignore-gpu-blocklist', '--enable-gpu-rasterization'] };
  if (mod === 'puppeteer-core') {
    opts.executablePath = chromePath();
    if (!opts.executablePath) { console.error('puppeteer-core 要用本机的 Chrome：设 CHROME_PATH'); process.exit(1); }
  }
  const browser = await lib.launch(opts);
  let done = 0, failed = 0;
  const t0 = Date.now();
  const queue = todo.slice();
  async function worker(id) {
    const p = await browser.newPage();
    p.on('pageerror', (e) => console.error(`[进程${id}] 页面报错：${e.message}`));
    await p.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
    await p.goto('file://' + page + (pageQuery ? '?' + pageQuery : ''), { waitUntil: 'load', timeout: 180000 });
    await p.addStyleTag({ content: 'html, body { margin: 0 !important; padding: 0 !important; overflow: hidden; }' });   // 浏览器默认 8px 边距会让画面错位
    await p.waitForFunction(() => window.sceneReady === true || (window.sceneReady && typeof window.sceneReady.then === 'function'), { timeout: 180000 });
    await p.evaluate(async () => { if (window.sceneReady !== true) await window.sceneReady; });
    while (queue.length) {
      const n = queue.shift();
      const t = timeOf(n);
      try {
        const url = await p.evaluate(async (tt, f) => {
          const r = await window.renderAt(tt);
          return typeof r === 'string' && r.startsWith('data:image') ? r : null;
        }, t, fmt);
        if (url) fs.writeFileSync(name(n), Buffer.from(url.split(',')[1], 'base64'));
        else await p.screenshot({ path: name(n), type: fmt === 'png' ? 'png' : 'jpeg', quality: fmt === 'png' ? undefined : 92, clip: { x: 0, y: 0, width: W, height: H } });
      } catch (e) {
        failed++;
        console.error(`第 ${n} 帧（${t.toFixed(3)} 秒）失败：${e.message}`);
      }
      done++;
      if (done % 50 === 0 || !queue.length) {
        const s = (Date.now() - t0) / 1000;
        process.stdout.write(`\r${done}/${todo.length} 帧，${(s / done).toFixed(2)} 秒/帧，还要约 ${Math.round(s / done * (todo.length - done) / 60)} 分钟   `);
      }
    }
    await p.close();
  }
  await Promise.all(Array.from({ length: Math.max(1, workers) }, (_, i) => worker(i + 1)));
  await browser.close();
  console.log(`\n渲完 ${done - failed} ${times ? '张' : '帧'}${failed ? `，失败 ${failed} 张（再跑一次会补上）` : ''}${times ? '：' + out : ''}`);
}

if (args.encode && !times) {
  const missing = [];
  for (let n = 0; n < total; n++) if (!fs.existsSync(name(n))) missing.push(n);
  if (missing.length) { console.error(`还缺 ${missing.length} 帧（第一个是第 ${missing[0]} 帧），先补渲再接`); process.exit(1); }
  const dst = path.resolve(args.encode);
  // 只接 0..total-1（片子改短了，多出来的旧帧不会混进去）；每秒一个关键帧，HyperFrames 抽帧才不会出黑屏
  const r = spawnSync('ffmpeg', ['-v', 'error', '-y', '-framerate', String(fps), '-i', path.join(out, '%06d.' + fmt), '-frames:v', String(total),
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-pix_fmt', 'yuv420p', '-g', String(Math.round(fps)), '-keyint_min', String(Math.round(fps)),
    '-movflags', '+faststart', dst], { stdio: 'inherit' });
  if (r.status) process.exit(r.status);
  console.log(`接好了：${dst}`);
}
