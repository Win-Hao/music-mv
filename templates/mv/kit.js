/* music-mv 的小工具 kit.js：页面接口、拍子、缓动、关键帧、随机数、转场用的遮罩和变形、歌词时间、字体和笔画数据、动态模糊、预览。
   不是框架：镜头怎么排、转场怎么接、歌词长什么样，都在页面自己的 draw / overlay 里写。

   页面里这样用（见 index.html）：
     <script src="kit.js"></script> <script src="song.js"></script> <script src="lyrics.js"></script>
     MV.page({ W: 1920, H: 1080, fps: 30, duration, ready, draw, overlay, blur, shutter, blurMin })   // 竖屏 W: 1080, H: 1920
       ready()        async：字体（MV.font）、笔画数据（MV.glyphs）、烤好的纸和缓存图层。准备完才开始画
       draw(g, t)     画面（可以 async，比如 p5.brush 要等重画）。g 已经缩放成 W×H 的逻辑坐标，每帧从干净的状态画起
       overlay(g, t)  最上层、不跟镜头动、不参与动态模糊的东西：歌词
       blur(t)        这一帧拆成几个子帧做动态模糊（1 = 不开）。按这一帧镜头走了多少像素定（约 4 像素一个，最多 32），只在甩镜、快推、东西飞过时开
       blurMin        开了就至少拆几个（默认 8）：只拆两三个会看到一个个分开的残影，比不开还难看
       shutter        快门（0–1，默认 0.5）：子帧铺在 t 之前多长一段（单位：帧）
   出片：render_frames.mjs 调 window.renderAt(t, { format })，画面大小自动用 W×H；--lyric-check 调 window.lyricCheck 按帧核逐字歌词。
   预览：浏览器直接打开 index.html 就是预览，跟着歌放：先找 song.js 记的那首（analyze_song.py 分析的文件），再找 ../song.mp3、.wav、.m4a……
        地址后面可以加 ?song=../歌.wav 换歌的位置，&start=30 片头是歌的第几秒（不写就用 song.js 的 start），&blur=1 预览时也开动态模糊，&t=12 从第 12 秒看起；
        空格播放，← → 一帧，Shift + ← → 一拍。字体、笔画数据没加载到，播放条上会写出来
   画面只由 t 决定：随机数用 MV.rng('元素名' + 序号)，不用 Math.random()、Date。 */
(function () {
  'use strict';
  const MV = (window.MV = {});
  // 出片（render_frames 的无头浏览器，navigator.webdriver 为真）还是在浏览器里预览（地址加 ?preview 也算预览）
  MV.rendering = !!navigator.webdriver && !new URLSearchParams(location.search).has('preview');
  // 出了问题要让人看见：预览时写在播放条上（也打进控制台）；出片时 MV.fail 直接报错，render_frames 会停下说清是什么
  MV.warnings = [];
  MV.warn = (msg) => { if (MV.warnings.includes(msg)) return; MV.warnings.push(msg); console.warn(msg); };   // 同一句只说一次
  MV.fail = (msg) => { if (MV.rendering) throw new Error(msg); MV.warn(msg); };

  // ───────── 数学 ─────────
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, u) => a + (b - a) * u;
  const seg = (t, a, b) => clamp((t - a) / (b - a));        // t 在 a→b 之间走到哪（0→1）
  Object.assign(MV, { clamp, lerp, seg });

  // ───────── 缓动：输入 0→1。推拉平移用 inOut，落位用 back，不用 linear 起停 ─────────
  MV.ease = {
    linear: (u) => clamp(u),
    in: (u) => Math.pow(clamp(u), 3),
    out: (u) => 1 - Math.pow(1 - clamp(u), 3),
    inOut: (u) => { u = clamp(u); return u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2; },
    smooth: (u) => { u = clamp(u); return u * u * (3 - 2 * u); },
    back: (u, s = 1.7) => { u = clamp(u); return 1 + (s + 1) * Math.pow(u - 1, 3) + s * Math.pow(u - 1, 2); },   // 冲过头再回来
    spring: (u, f = 2.5, d = 6) => { u = clamp(u); return 1 - Math.exp(-d * u) * Math.cos(2 * Math.PI * f * u); },  // 落位后抖几下
  };

  // 关键帧：MV.keys(t, [[0, 0], [1.2, 300, 'inOut'], [2, 300], [2.5, [10, 20], 'back'], [3, { x: 40, y: 8 }]])
  // 关键帧表是数组，每项也是数组 [时刻, 值, 走到这一项用的缓动（默认 inOut）]，按时刻从小到大排；
  // 值是数、数组（几个数一起补）或 { x, y } 这样的对象（数字属性一起补），前后几项的值要同一种；第一项之前、最后一项之后停住
  MV.keys = function (t, ks) {
    if (!Array.isArray(ks) || !ks.length || !Array.isArray(ks[0]))
      throw new TypeError('MV.keys(t, 关键帧表)：关键帧表写成 [[时刻, 值, 缓动], …]，每项是数组，不是 { t, v } 对象');
    if (t <= ks[0][0]) return ks[0][1];
    for (let i = 1; i < ks.length; i++) {
      const [t1, v1, e] = ks[i], [t0, v0] = ks[i - 1];
      if (t <= t1) {
        const u = (MV.ease[e] || MV.ease.inOut)(seg(t, t0, t1));
        if (Array.isArray(v0)) return v0.map((a, j) => lerp(a, v1[j], u));
        if (v0 && typeof v0 === 'object') return Object.fromEntries(Object.keys(v0).map((k) => [k, typeof v0[k] === 'number' ? lerp(v0[k], v1[k], u) : v0[k]]));
        return lerp(v0, v1, u);
      }
    }
    return ks[ks.length - 1][1];
  };

  // ───────── 固定种子的随机数和噪声 ─────────
  MV.hash = (s) => { s = String(s); let h = 2166136261 >>> 0; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; };
  MV.rng = (key) => {                                       // 同一个 key 永远拿到同一串数
    let a = MV.hash(key);
    return () => { a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  };
  const lattice = (key, i) => MV.rng(key + ':' + i)() * 2 - 1;
  MV.noise = (key, x) => {                                  // 平滑的一维噪声，-1→1：手持晃动、漂浮、风
    const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f);
    return lerp(lattice(key, i), lattice(key, i + 1), u);
  };

  // ───────── 转场用的几个小工具（怎么用见 references/transitions.md「在代码里怎么接」）─────────
  MV.lerpLog = (a, b, u) => a * Math.pow(b / a, u);        // 对数插值：推拉、缩放的倍数用它，每帧放大的比例一样，看着才匀

  // 穿越推进：B 画在 A 画面上的一扇「窗」里（win = { x, y, w, h }，A 画面上的坐标；不用在正中，宽高比也不用和画面一样），
  // 镜头朝窗里推：倍数按对数插值，绕一个不动点推，窗一边放大一边挪到正中。u = 1 时窗正好盖满画面，画出来就是 B 本身（逐像素一样），
  // 落位以后只画 B 就接得上。u 一般是 MV.ease.inOut(MV.seg(t, 起, 落))；drawA(m)、drawB(m) 照常画各自的镜头，可以 async（要 await）。
  // 位图放大会糊：p5.brush 这类在别的画布上画好再拷过来的，别用它推，见 references/transitions.md「穿越推进」
  MV.pushInto = (g, win, u, drawA, drawB) => {
    const W = MV.W, H = MV.H, s1 = Math.max(W / win.w, H / win.h);        // 推到底的倍数：窗的短边盖满画面
    if (Math.abs(s1 - 1) < 1e-9) return drawB(g);
    const cx = W / 2 - s1 * (win.x + win.w / 2), cy = H / 2 - s1 * (win.y + win.h / 2);   // 推到底：x → s1·x + c，窗心落在画面中心
    const px = cx / (1 - s1), py = cy / (1 - s1), s = Math.pow(s1, clamp(u));             // 不动点 P；现在推到 s 倍（对数插值）
    g.save(); g.translate(px * (1 - s), py * (1 - s)); g.scale(s, s);
    const inner = () => {                                   // 窗里画 B：先抵掉推到底的那个变换，u = 1 时整体就是原样
      g.beginPath(); g.rect(win.x, win.y, win.w, win.h); g.clip();
      g.translate(-cx / s1, -cy / s1); g.scale(1 / s1, 1 / s1);
      return drawB(g);
    };
    let r;
    try { r = drawA(g); } catch (e) { g.restore(); throw e; }
    if (r && typeof r.then === 'function') return r.then(() => later(inner(), () => g.restore(), () => g.restore()), (e) => { g.restore(); throw e; });
    let r2;
    try { r2 = inner(); } catch (e) { g.restore(); throw e; }
    return later(r2, () => g.restore(), () => g.restore());
  };

  // 在遮罩里画另一个镜头：mask(m) 往路径里加形状（不用 beginPath），draw(m) 画那个镜头。都用 g 当前的坐标（外面套了什么缩放就跟着什么）
  // feather：边缘羽化多少像素，0 = 硬边（最快）。羽化会把画面边上也吃掉一半，遮罩要伸出画面外一截
  // draw 是同步的，MV.reveal 就同步画完；draw 是 async 的（p5.brush），要 await MV.reveal(…)
  const pool = [];
  let depth = 0;
  const later = (r, done, fail) => (r && typeof r.then === 'function' ? r.then(done, (e) => { fail(); throw e; }) : done());
  MV.reveal = (g, mask, draw, feather = 0) => {
    if (!(feather > 0)) {
      g.save(); g.beginPath(); mask(g); g.clip();
      let r;
      try { r = draw(g); } catch (e) { g.restore(); throw e; }
      return later(r, () => g.restore(), () => g.restore());
    }
    const c = g.canvas, T = g.getTransform();
    const buf = pool[depth] || (pool[depth] = document.createElement('canvas'));
    if (buf.width !== c.width || buf.height !== c.height) { buf.width = c.width; buf.height = c.height; }
    const b = buf.getContext('2d');
    b.setTransform(1, 0, 0, 1, 0, 0); b.globalCompositeOperation = 'source-over'; b.globalAlpha = 1; b.filter = 'none';
    b.clearRect(0, 0, buf.width, buf.height);
    b.setTransform(T); b.save();
    depth++;
    const undo = () => { depth--; b.restore(); };
    let r;
    try { r = draw(b); } catch (e) { undo(); throw e; }
    return later(r, () => {
      undo();
      b.globalCompositeOperation = 'destination-in'; b.filter = `blur(${(feather * Math.hypot(T.a, T.b)) / 2}px)`;
      b.fillStyle = '#000'; b.beginPath(); mask(b); b.fill();
      b.filter = 'none'; b.globalCompositeOperation = 'source-over';
      g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over'; g.drawImage(buf, 0, 0); g.restore();
    }, undo);
  };

  // 不规则的圆（墨晕开、水渍、撕开的洞、不规则的收光）：半径上叠几个随机相位的波，首尾自然接上。rough 越大越毛
  MV.blob = (g, cx, cy, R, key = 'blob', rough = 0.15, n = 160) => {
    const r = MV.rng(key), waves = [2, 3, 5, 8, 13, 21, 34].map((f) => [f, r() * Math.PI * 2, (0.5 + r()) / Math.sqrt(f)]);
    for (let i = 0; i <= n; i++) {
      const a = (i / n) * Math.PI * 2;
      let k = 1;
      for (const [f, p, w] of waves) k += rough * w * Math.sin(f * a + p);
      const x = cx + Math.cos(a) * R * k, y = cy + Math.sin(a) * R * k;
      if (i === 0) g.moveTo(x, y); else g.lineTo(x, y);
    }
    g.closePath();
  };

  // 变形：两个闭合形状（点列 [[x, y], …]）各按长度均匀取 n 个点、对齐起点和绕向，再逐点插值。返回中间形状的点列
  function resample(P, n) {
    const m = P.length, len = [], out = [];
    let L = 0;
    for (let i = 0; i < m; i++) { const q = P[(i + 1) % m], d = Math.hypot(q[0] - P[i][0], q[1] - P[i][1]); len.push(d); L += d; }
    for (let k = 0, i = 0, acc = 0; k < n; k++) {
      const d = (k / n) * L;
      while (i < m - 1 && acc + len[i] < d) acc += len[i++];
      const f = len[i] ? (d - acc) / len[i] : 0, p = P[i], q = P[(i + 1) % m];
      out.push([lerp(p[0], q[0], f), lerp(p[1], q[1], f)]);
    }
    return out;
  }
  const area = (P) => P.reduce((s, p, i) => { const q = P[(i + 1) % P.length]; return s + p[0] * q[1] - q[0] * p[1]; }, 0);
  MV.morph = (A, B, u, n = 240) => {
    const a = resample(A, n), b = resample(area(A) * area(B) < 0 ? B.slice().reverse() : B, n);
    let best = 0, bd = Infinity;
    for (let s = 0; s < n; s++) {
      let d = 0;
      for (let i = 0; i < n; i += 6) { const q = b[(i + s) % n]; d += (a[i][0] - q[0]) ** 2 + (a[i][1] - q[1]) ** 2; }
      if (d < bd) { bd = d; best = s; }
    }
    return a.map((p, i) => { const q = b[(i + best) % n]; return [lerp(p[0], q[0], u), lerp(p[1], q[1], u)]; });
  };

  // 变速、定格：镜头里的时间 = 播放速度从 t0 积分到 t（speed(t)：1 正常、0.3 慢放、0 定格、2 快放）。画这个镜头时用 t0 + MV.retime(…)
  MV.retime = (t, t0, speed) => {
    let tau = 0;
    const dt = 1 / 240;
    for (let x = t0; x < t; x += dt) { const h = Math.min(dt, t - x); tau += speed(x + h / 2) * h; }
    return tau;
  };

  // ───────── 歌：window.SONG 来自 analyze_song.py --js；没有就按 MV.tempo(BPM, 第一拍) 往后推 ─────────
  let BPM = 120, OFF = 0;
  MV.tempo = (bpm, off = 0) => { BPM = bpm; OFF = off; };
  const song = () => window.SONG || null;
  const beats = () => { const s = song(); return s && s.beats && s.beats.length > 1 ? s.beats : null; };
  const timeOf = (e) => (Array.isArray(e) ? e[0] : (e && typeof e === 'object' ? e.t : e));
  function lastIndex(list, t) {                             // 最后一个时间 ≤ t 的下标，没有就 -1
    let lo = -1, hi = list.length;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (timeOf(list[m]) <= t) lo = m; else hi = m; }
    return lo;
  }
  // 第几拍（小数）：3.25 = 第 3 拍过了四分之一（从 0 数）。拍点之间按真实间隔走，歌长了也不漂
  MV.beat = (t) => {
    const b = beats();
    if (!b) return (t - OFF) / (60 / BPM);
    const n = b.length, avg = (b[n - 1] - b[0]) / (n - 1);
    if (t < b[0]) return (t - b[0]) / (b[1] - b[0]);
    if (t >= b[n - 1]) return n - 1 + (t - b[n - 1]) / avg;
    const i = lastIndex(b, t);
    return i + (t - b[i]) / (b[i + 1] - b[i]);
  };
  MV.beatTime = (x) => {                                    // 反过来：第 x 拍在几秒
    const b = beats();
    if (!b) return OFF + x * 60 / BPM;
    const n = b.length, avg = (b[n - 1] - b[0]) / (n - 1);
    if (x <= 0) return b[0] + x * (b[1] - b[0]);
    if (x >= n - 1) return b[n - 1] + (x - (n - 1)) * avg;
    const i = Math.floor(x);
    return lerp(b[i], b[i + 1], x - i);
  };
  MV.beatPhase = (t) => { const x = MV.beat(t); return x - Math.floor(x); };
  // 冲击：拍点那一刻是 1，之后按 decay 秒衰减。list 可以换成 SONG.downbeats、SONG.onsets（带强度）、SONG.hits、SONG.events
  MV.pulse = (t, decay = 0.15, list) => {
    const L = list || beats();
    if (!L) { if (t < OFF) return 0; const last = MV.beatTime(Math.floor(MV.beat(t))); return Math.exp(-(t - last) / decay); }
    const i = lastIndex(L, t);
    if (i < 0) return 0;
    const e = L[i], s = Array.isArray(e) ? e[1] : 1;
    return s * Math.exp(-(t - timeOf(e)) / decay);
  };
  MV.env = (t, which = 'all') => {                          // 响度包络 0→1（'all' 整体、'low' 低音）
    const s = song(); if (!s || !s.env || !s.env[which]) return 0;
    const a = s.env[which], x = t * s.env.fps, i = Math.floor(x);
    if (i < 0) return a[0] || 0;
    if (i >= a.length - 1) return a[a.length - 1] || 0;
    return lerp(a[i], a[i + 1], x - i);
  };
  MV.section = (t) => { const s = song(); return s ? (s.sections || []).find((x) => t >= x.start && t < x.end) || null : null; };

  // ───────── 歌词：window.LYRICS = [[开始, 结束, "这句"], …]（srt2js.py）；有逐字时间的句子多一项 [第 1 个字开唱的秒, …]（srt2js.py --words）─────────
  // 字位：中文一个字一个，连着的英文字母、数字一个词一个；空格、标点不占（和 srt2js.py 一样的拆法），逐字时间按字位一个对一个
  const LATIN = /[A-Za-z0-9][A-Za-z0-9'’]*/y, SKIP = /[\s\p{P}\p{S}]/u;
  function tokens(text, words) {                            // → [{ ch, timed }]：words 为真时英文按词拆，否则一个字符一个
    const out = [];
    for (let i = 0; i < text.length;) {
      LATIN.lastIndex = i;
      const m = words ? LATIN.exec(text) : null;
      if (m) { out.push({ ch: m[0], timed: true }); i += m[0].length; continue; }
      const ch = String.fromCodePoint(text.codePointAt(i));
      out.push({ ch, timed: words ? !SKIP.test(ch) : !/\s/.test(ch) });   // 没有逐字时间时只有空格不占时间（标点照旧占）
      i += ch.length;
    }
    return out;
  }
  MV.lyricUnits = (text) => tokens(text, true).filter((x) => x.timed).map((x) => x.ch);
  MV.lyricText = () => (window.LYRICS || []).map((l) => l[2]).join('');   // 全部歌词的字：MV.font、MV.glyphs 只下用到的字
  let HIDE = null;                                          // lyricCheck 用：[第几句, 第几个字位] 这个字当成还没唱到
  // 第 i 句每个字（含空格、标点）什么时候开唱：有逐字时间用它（t1 = 下一个字开唱，最后一个字到句尾），没有就从句首起每字隔 per 秒
  function charTimes(i, per) {
    const [s, e, text, times] = window.LYRICS[i];
    if (Array.isArray(times) && times.length) {
      const toks = tokens(text, true), n = toks.filter((x) => x.timed).length;
      if (n === times.length) {
        const T0 = times.map((x) => +(Array.isArray(x) ? x[0] : x));
        const T1 = times.map((x, j) => (Array.isArray(x) && x[1] != null ? +x[1] : j + 1 < T0.length ? T0[j + 1] : e));
        let j = -1;
        return { timed: true, chars: toks.map((x, k) => { if (x.timed) j++; const jj = Math.max(0, j); return { ch: x.ch, k, j: jj, timed: x.timed, t0: T0[jj], t1: T1[jj] }; }) };
      }
      MV.warn(`lyrics.js 第 ${i + 1} 句：逐字时间 ${times.length} 个，字位 ${n} 个，对不上，这句照旧按固定间隔出字（重跑 srt2js.py --words）`);
    }
    let j = -1;
    return { timed: false, chars: tokens(text, false).map((x, k) => { if (x.timed) j++; const jj = Math.max(0, j); return { ch: x.ch, k, j: jj, timed: x.timed, t0: s + jj * per, t1: s + (jj + 1) * per }; }) };
  }
  // 现在该显示哪句、每个字出来多少（u：0→1），这句结束后留 tail 秒，下一句前 gap 秒收走。chars[k] = { ch, k, u, t0, t1, timed }
  // - 有逐字时间：每个字在自己开唱前 lead 秒（默认 0.04，规矩是最多早 0.08）开始弹、pop 秒到位：开唱那一帧已经看得见，不会晚一帧
  // - 没有：一个字一个字按固定间隔出（每字隔 per 秒）；空格不占时间
  // 写字类画风按 t0、t1 控制写一个字用多久（写完不超过这个字唱的时长），按 u 或者 MV.seg(t, c.t0, c.t1) 画到哪
  MV.lyricAt = (t, o = {}) => {
    const L = window.LYRICS || [], per = o.per ?? 0.045, pop = o.pop ?? 0.18, tail = o.tail ?? 0.3, gap = o.gap ?? 0.24, lead = o.lead ?? 0.04;
    const i = lastIndex(L, t);
    if (i < 0) return null;
    const [s, e, text] = L[i], next = L[i + 1];
    if (t >= e + tail || (next && t > next[0] - gap)) return null;
    const ct = charTimes(i, per), back = ct.timed ? lead : 0;
    const chars = ct.chars.map((c) => {
      const t0 = HIDE && HIDE[0] === i && HIDE[1] === c.j && c.timed ? Infinity : c.t0;
      return { ch: c.ch, k: c.k, t0: c.t0, t1: c.t1, timed: c.timed, u: clamp((t - (t0 - back)) / pop) };
    });
    return { i, text, start: s, end: e, age: t - s, u: seg(t, s, e), chars, timed: ct.timed };
  };
  // 一个通用的画法：浅色字 + 深色粗描边 + 硬投影，一个字一个字弹出来。画风有自己的歌词画法（对话框、纸条、题跋）就换掉它
  // 竖屏（H > W）时默认往上挪到画面高度约 77% 处、字号 64：抖音下面约五分之一是标题和文案（见 references/storyboard.md「竖屏」）
  // 一行超过画面宽度的 80% 就从中间折成两行，还放不下就缩字
  // 字体：网页加载的思源黑体（Noto Sans SC），模板里 <link> 了它的 800 字重，ready 里 MV.font 等它下好。不用系统字体：Windows 和 Mac 的不一样，折行也会变
  const LYRIC0 = { bottom: 70, size: 72 };
  MV.lyricStyle = { ...LYRIC0, color: '#FFF8E7', ink: '#22263F', weight: 800, font: '"Noto Sans SC","PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif' };
  MV.drawLyric = (g, t, style) => {
    const st = Object.assign({}, MV.lyricStyle, style || {}), L = MV.lyricAt(t);
    if (!L) return;
    g.save();
    let size = st.size;
    g.font = `${st.weight} ${size}px ${st.font}`;
    g.textBaseline = 'middle'; g.lineJoin = 'round';
    let ws = L.chars.map((c) => g.measureText(c.ch).width);
    const maxW = MV.W * 0.8, total = ws.reduce((a, b) => a + b, 0), n = L.chars.length;
    let lines = [[...Array(n).keys()]];
    if (total > maxW && n > 1) {
      let acc = 0, cut = 1;
      for (let k = 0; k < n; k++) { acc += ws[k]; if (acc >= total / 2) { cut = k + 1; break; } }
      cut = Math.min(Math.max(1, cut), n - 1);
      lines = [[...Array(cut).keys()], [...Array(n - cut).keys()].map((i) => i + cut)];
    }
    const widest = Math.max(...lines.map((ln) => ln.reduce((a, k) => a + ws[k], 0)));
    if (widest > maxW) { const f = maxW / widest; size *= f; ws = ws.map((w) => w * f); g.font = `${st.weight} ${size}px ${st.font}`; }
    const lineH = size * 1.3, yLast = MV.H - st.bottom - size / 2;
    lines.forEach((ln, li) => {
      let x = MV.W / 2 - ln.reduce((a, k) => a + ws[k], 0) / 2;
      const y = yLast - (lines.length - 1 - li) * lineH;
      for (const k of ln) {
        const c = L.chars[k], w = ws[k];
        if (c.u > 0) {
          const s = 1 + 0.25 * Math.sin(Math.PI * c.u) * (1 - c.u);   // 先冲过一点再回来
          g.save(); g.translate(x + w / 2, y); g.scale(s, s);
          g.lineWidth = size / 7;
          g.strokeStyle = g.fillStyle = st.ink;
          g.strokeText(c.ch, -w / 2 + size / 14, size / 11); g.fillText(c.ch, -w / 2 + size / 14, size / 11);   // 硬投影
          g.strokeText(c.ch, -w / 2, 0);
          g.fillStyle = st.color; g.fillText(c.ch, -w / 2, 0);
          g.restore();
        }
        x += w;
      }
    });
    g.restore();
  };

  // ───────── 网页字体、汉字笔画数据：在 ready 里等它们准备好 ─────────
  // 等网页字体下好：spec 是 CSS 的 font 写法（'800 64px "Noto Sans SC"'），text 是要用到的字（中文网页字体按字分成很多小文件，只下用到的；默认全部歌词）。
  // 看 document.fonts.load 的结果：里面真有这个字体、而且都下好了才算好。document.fonts.check 靠不住：页面上根本没有这个字体时它也返回 true。
  // 没下到：出片时报错停下（悄悄换成系统字体，Windows 和 Mac 渲出来就不一样），预览时写在播放条上。optional: true 只提醒不报错。返回 true / false
  MV.font = async (spec, text = MV.lyricText(), { timeout = 30000, optional = false } = {}) => {
    let faces = null, why = '';
    try {
      faces = await Promise.race([document.fonts.load(spec, text || ' '),
        new Promise((_, rej) => setTimeout(() => rej(new Error(`等了 ${timeout / 1000} 秒还没下完`)), timeout))]);
    } catch (e) { why = String((e && e.message) || e); }
    const ok = Array.isArray(faces) && faces.length > 0 && faces.every((f) => f.status === 'loaded');
    if (!ok) {
      if (!why) why = !faces || !faces.length ? '页面上没有这个字体：<link> 的字体样式表没加载到，或者字体名写错了' : '字体文件没下载到';
      (optional ? MV.warn : MV.fail)(`字体没加载到：${spec}（${why}）`);
    }
    return ok;
  };
  // 汉字的笔画中线（写字类画风按笔顺一笔一笔写歌词用）：hanzi-writer-data 每个字一个 JSON，取里面的 medians。返回 { 字: medians }。
  // 先用页面里的 window.GLYPHS（scripts/glyphs.py 预先存的 glyphs.js：渲染时不联网，几个进程拿到的一模一样），缺的再从 jsDelivr 取（每个字试 3 次）。
  // 网络问题取不到：出片时报错停下，不然有的进程取到了、有的没取到，同一个字前后帧不一样；数据里本来就没有的字（标点、英文、少数生僻字）不在返回里，页面自己决定怎么画
  MV.glyphs = async (text = MV.lyricText(), { url = 'https://cdn.jsdelivr.net/npm/hanzi-writer-data@2.0.1/', tries = 3, timeout = 20000 } = {}) => {
    const out = {}, have = window.GLYPHS || {}, need = [], lost = [], none = [];
    for (const ch of new Set(Array.from(text))) {
      if (!/\p{Script=Han}/u.test(ch)) continue;
      if (have[ch]) out[ch] = have[ch].medians || have[ch]; else need.push(ch);
    }
    const one = async (ch) => {
      for (let k = 0; k < tries; k++) {
        const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), timeout);
        try {
          const res = await fetch(url + encodeURIComponent(ch) + '.json', { signal: ctl.signal });
          if (res.status === 404) { none.push(ch); return; }
          if (!res.ok) throw new Error('HTTP ' + res.status);
          out[ch] = (await res.json()).medians;
          return;
        } catch (e) { if (k === tries - 1) lost.push(ch); } finally { clearTimeout(timer); }
      }
    };
    for (let i = 0; i < need.length; i += 8) await Promise.all(need.slice(i, i + 8).map(one));   // 一次最多取 8 个
    if (none.length) MV.warn(`笔画数据里没有 ${none.length} 个字（第一个是「${none[0]}」），这几个字要另外画`);
    if (lost.length) MV.fail(`笔画数据有 ${lost.length} 个字没取到（第一个是「${lost[0]}」，网络问题）。先跑 scripts/glyphs.py 存成本地的 glyphs.js，渲染时就不联网了`);
    return out;
  };

  // ───────── 页面：画布、渲染接口、动态模糊、预览 ─────────
  const BAR = 44;
  MV.page = function (o) {
    const W = (MV.W = o.W || 1920), H = (MV.H = o.H || 1080), fps = (MV.fps = o.fps || 30);
    MV.duration = o.duration || (song() && song().duration) || 60;
    if (H > W && MV.lyricStyle.bottom === LYRIC0.bottom && MV.lyricStyle.size === LYRIC0.size) Object.assign(MV.lyricStyle, { bottom: Math.round(H * 0.23), size: 64 });
    const shutter = o.shutter ?? 0.5, blurMin = Math.max(1, o.blurMin ?? 8);
    // 浏览器里直接打开就是预览；render_frames（无头浏览器，navigator.webdriver 为真）出图时不开
    const q = new URLSearchParams(location.search), preview = q.has('preview') || !navigator.webdriver;
    const out = document.createElement('canvas'), tmp = document.createElement('canvas');
    out.style.display = 'block';
    document.body.appendChild(out);
    const g = out.getContext('2d'), gt = tmp.getContext('2d');
    let k = 1, ox = 0, oy = 0;
    function size() {                                       // 画布跟窗口走，画面按 W×H 等比放进去；每帧都对一下，视口改了也跟得上
      const vw = Math.max(16, Math.round(innerWidth || W)), vh = Math.max(16, Math.round((innerHeight || H) - (preview ? BAR : 0)));
      if (out.width !== vw || out.height !== vh) { out.width = tmp.width = vw; out.height = tmp.height = vh; }
      k = Math.min(vw / W, vh / H); ox = (vw - W * k) / 2; oy = (vh - H * k) / 2;
    }
    size();
    // 每帧从干净的状态画起：上一帧画到一半出错、没 restore 的裁剪和变换，不会带到后面的帧
    const fresh = (ctx) => {
      if (ctx.reset) ctx.reset(); else for (let i = 0; i < 64; i++) ctx.restore();
      ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over'; ctx.filter = 'none';
    };
    async function paint(ctx, t, fn) {
      if (fn === o.draw) { fresh(ctx); ctx.fillStyle = '#000'; ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height); }
      else { ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over'; ctx.filter = 'none'; }
      ctx.setTransform(k, 0, 0, k, ox, oy);
      ctx.save(); ctx.beginPath(); ctx.rect(0, 0, W, H); ctx.clip();
      try { await fn(ctx, t); } finally { ctx.restore(); ctx.setTransform(1, 0, 0, 1, 0, 0); }
    }
    async function frame(t, useBlur = true) {
      size();
      let n = useBlur && o.blur ? Math.max(1, Math.round(o.blur(t)) || 1) : 1;
      if (n > 1) n = Math.max(n, blurMin);                  // 开了就至少 blurMin 个子帧：只有两三个会看到一个个分开的残影
      if (n === 1) await paint(g, t, o.draw);
      else {
        // 动态模糊：快门开着的这一小段（t 之前 shutter 帧）里均匀取 n 个时刻，各画一张，逐张平均叠进来
        fresh(g);
        for (let i = 0; i < n; i++) {
          await paint(gt, t - (shutter / fps) * (1 - (i + 0.5) / n), o.draw);
          g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = 'source-over';
          g.globalAlpha = 1 / (i + 1); g.drawImage(tmp, 0, 0); g.globalAlpha = 1;
        }
      }
      if (o.overlay) await paint(g, t, o.overlay);
    }
    const ready = (async () => { if (o.ready) await o.ready(); return true; })();
    window.sceneReady = ready;
    window.renderAt = async (t, opt = {}) => { await ready; await frame(t); return out.toDataURL(opt.format || 'image/png', 0.92); };
    window.drawAt = async (t, useBlur = true) => { await ready; await frame(t, useBlur); };
    // 按帧核逐字歌词（render_frames.mjs --lyric-check 调它）：只画 overlay（歌词层），每个字在「开唱那一帧」（离开唱最近的那一帧）画一张，
    // 再把这个字当成还没唱到画一张，两张差出来的就是这个字自己的笔画。开唱那一帧它要已经看得见（不然就是晚了），开唱前 0.08 秒以前要看不见（不然太早）。
    // 只核有逐字时间的句子；只认用 MV.lyricAt 出字、画在 overlay 里的页面，自己另算时间的页面差不出东西，报「核不了」
    window.lyricCheck = async ({ from = 0, to = MV.duration, scale = 0.5 } = {}) => {
      await ready;
      const L = window.LYRICS || [];
      if (!o.overlay) return { error: '页面没有 overlay（歌词要画在 overlay 里才核得了）' };
      if (!L.length) return { error: '没有 window.LYRICS' };
      const c = document.createElement('canvas'); c.width = Math.max(16, Math.round(W * scale)); c.height = Math.max(16, Math.round(H * scale));
      const x = c.getContext('2d', { willReadFrequently: true }), cache = new Map();
      const snap = async (n, hide) => {
        const key = n + ':' + (hide ? hide.join(',') : '');
        if (cache.has(key)) return cache.get(key);
        HIDE = hide;
        try {
          fresh(x); x.clearRect(0, 0, c.width, c.height); x.setTransform(scale, 0, 0, scale, 0, 0);
          x.save(); x.beginPath(); x.rect(0, 0, W, H); x.clip();
          try { await o.overlay(x, n / fps); } finally { x.restore(); }
        } finally { HIDE = null; }
        const d = x.getImageData(0, 0, c.width, c.height).data;
        if (!hide) cache.set(key, d);
        return d;
      };
      const diff = (a, b) => { let m = 0; for (let i = 0; i < a.length; i += 4) if (Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]) + Math.abs(a[i + 3] - b[i + 3]) > 48) m++; return m; };
      const own = async (n, i, j) => diff(await snap(n, null), await snap(n, [i, j]));   // 这个字自己在这一帧画出来多少像素
      const res = { fps, from, to, lines: 0, untimed: 0, chars: 0, ok: 0, late: [], early: [], unknown: [] };
      for (let i = 0; i < L.length; i++) {
        if (L[i][1] < from || L[i][0] > to) continue;
        const ct = charTimes(i, 0.045), next = L[i + 1];
        if (!ct.timed) { res.untimed++; continue; }          // 没有逐字时间的句子没有「开唱」可对，不核
        res.lines++;
        for (const ch of ct.chars) {
          if (!ch.timed || ch.t0 < from || ch.t0 > to) continue;
          res.chars++;
          const F = Math.ceil((ch.t0 - 0.5 / fps) * fps - 1e-9);               // 开唱那一帧：时间离开唱最近的那一帧
          const end = Math.min(L[i][1] + 0.25, next ? next[0] - 0.25 : Infinity);
          const R = Math.round(Math.max(ch.t0 + 2 / fps, Math.min(ch.t0 + 0.3, end)) * fps);   // 参照：开唱后约 0.3 秒，这个字该出来了
          const nR = await own(R, i, ch.j);
          if (nR < 6) { res.unknown.push({ line: i + 1, char: ch.j + 1, t: +ch.t0.toFixed(3) }); continue; }
          const thr = Math.max(6, 0.04 * nR);
          if ((await own(F, i, ch.j)) >= thr) res.ok++;
          else {
            let late = null;
            for (let k = 1; k <= 15 && F + k <= R; k++) if ((await own(F + k, i, ch.j)) >= thr) { late = k; break; }
            res.late.push({ line: i + 1, char: ch.j + 1, t: +ch.t0.toFixed(3), frame: F, frames: late });
          }
          const E = Math.ceil((ch.t0 - 0.08) * fps - 1e-9) - 1;                  // 开唱前 0.08 秒以前的最后一帧
          if (E >= 0 && (await own(E, i, ch.j)) >= thr) res.early.push({ line: i + 1, char: ch.j + 1, t: +ch.t0.toFixed(3), frame: E });
        }
      }
      return res;
    };
    if (preview) ready.then(() => previewBar(frame, size, q));
  };

  // ───────── 预览：跟着歌播放、拖时间、按拍跳（只给人看，不影响出片）─────────
  const fmt = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(2).padStart(5, '0')}`;
  function previewBar(frame, size, q) {
    document.body.style.background = '#000';
    // 歌：地址里给了 ?song= 就用它；不然先找 song.js 记的那首（analyze_song.py 分析的文件，在歌的文件夹里），再找 song.mp3、wav、m4a……
    const SONGS = q.get('song') ? [q.get('song')] : [...new Set([window.SONG && SONG.file && '../' + SONG.file, ...['mp3', 'wav', 'm4a', 'flac', 'aac', 'ogg'].map((x) => '../song.' + x)].filter(Boolean))];
    const audio = new Audio(); audio.preload = 'auto';
    let songAt = 0, songOk = false;
    audio.addEventListener('loadedmetadata', () => { songOk = true; dirty = true; });
    audio.addEventListener('error', () => { if (!songOk && songAt < SONGS.length) audio.src = SONGS[songAt++]; else if (!songOk) { note = ` · 没找到歌（试了 ${SONGS.join('、')}），静音放；歌在别处就在地址后面加 ?song=路径`; dirty = true; } });
    audio.src = SONGS[songAt++];
    const useBlur = q.get('blur') === '1';
    const START = q.has('start') ? Number(q.get('start')) || 0 : (window.SONG && SONG.start) || 0;   // 片头在歌里的秒数：默认用 song.js 的 start（analyze_song.py --offset 写进去的）
    const bar = document.createElement('div');
    bar.style.cssText = `position:fixed;left:0;right:0;bottom:0;height:${BAR}px;display:flex;align-items:center;gap:10px;padding:0 12px;` +
      'background:#16181d;color:#e8e6e1;font:13px/1 system-ui,sans-serif;box-sizing:border-box';
    bar.innerHTML = '<button style="width:64px">播放</button><input type="range" min="0" step="0.001" style="flex:1">' +
      '<span style="min-width:360px;font-variant-numeric:tabular-nums;white-space:nowrap"></span>';
    document.body.appendChild(bar);
    const [btn, pos, info] = bar.children;
    pos.max = MV.duration;
    let cur = Number(q.get('t')) || 0, busy = false, ms = 0, dirty = true, note = '';
    let clock = null;                                       // 没有歌（示范页、还没放歌）时按时钟静音放
    const seek = (t) => { cur = clamp(t, 0, MV.duration); if (clock) clock = { t0: performance.now(), c0: cur }; if (!audio.paused) audio.currentTime = cur + START; dirty = true; };
    btn.onclick = () => {
      if (clock) { clock = null; btn.textContent = '播放'; dirty = true; return; }
      if (!audio.paused) { audio.pause(); return; }
      if (!songOk) { clock = { t0: performance.now(), c0: cur }; btn.textContent = '暂停'; dirty = true; return; }   // 没有歌：按时钟静音放
      audio.currentTime = cur + START;
      audio.play().catch(() => {
        note = ` · 歌放不出来（${audio.src}），静音放`;
        clock = { t0: performance.now(), c0: cur }; btn.textContent = '暂停';
      });
    };
    audio.onplay = () => { btn.textContent = '暂停'; note = ''; };
    audio.onpause = () => { btn.textContent = '播放'; dirty = true; };
    pos.oninput = () => seek(Number(pos.value));
    addEventListener('keydown', (e) => {
      if (e.code === 'Space') { e.preventDefault(); btn.onclick(); return; }
      if (e.code === 'Home') { seek(0); return; }
      if (e.code !== 'ArrowRight' && e.code !== 'ArrowLeft') return;
      e.preventDefault();
      const dir = e.code === 'ArrowRight' ? 1 : -1, b = MV.beat(cur);
      seek(e.shiftKey ? MV.beatTime(dir > 0 ? Math.floor(b + 1e-6) + 1 : Math.ceil(b - 1e-6) - 1) : cur + dir / MV.fps);
    });
    addEventListener('resize', () => { size(); dirty = true; });
    async function tick() {
      if (!busy && (dirty || !audio.paused || clock)) {
        busy = true; dirty = false;
        if (!audio.paused) { cur = audio.currentTime - START; if (cur >= MV.duration) { audio.pause(); cur = MV.duration; } }
        if (clock) { cur = clock.c0 + (performance.now() - clock.t0) / 1000; if (cur >= MV.duration) { clock = null; cur = MV.duration; btn.textContent = '播放'; } }
        const t0 = performance.now();
        await frame(cur, useBlur);
        ms = performance.now() - t0;
        pos.value = cur;
        const sec = MV.section(cur);
        info.textContent = `${fmt(cur)} / ${fmt(MV.duration)} · 拍 ${MV.beat(cur).toFixed(2)}` +   // 就是 MV.beat(t)，从 0 数，走到 8.00 的那一刻 = MV.beatTime(8)
          (sec ? ` · 第 ${SONG.sections.indexOf(sec) + 1} 段（${sec.level}）` : '') + ` · 画一帧 ${ms.toFixed(0)} ms` + (useBlur ? ' · 动态模糊开' : '') + note +
          (MV.warnings.length ? ` · ⚠ ${MV.warnings[0]}` + (MV.warnings.length > 1 ? `（还有 ${MV.warnings.length - 1} 条，见控制台）` : '') : '');
        busy = false;
      }
      requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }
})();
