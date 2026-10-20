/* 歌词层：最上层、不跟镜头动，按时间显示 window.LYRICS（scripts/srt2js.py 从 lyrics.srt 转出来的）。
   一个字一个字弹出来（每字隔 0.045 秒），下一句开始前 0.24 秒收走。只由 t 决定，拖时间线、多进程渲都一样。
   样式：浅色字 + 深色粗描边 + 硬投影，不发光。位置、字号、颜色在 LYRIC_STYLE 里改。 */
(function () {
  "use strict";
  var S = window.LYRIC_STYLE = Object.assign({ bottom: 70, size: 72, color: "#FFF8E7", ink: "#22263F", font: "sans-serif" }, window.LYRIC_STYLE || {});
  var box;
  function mount(root) {
    box = document.createElement("div");
    box.style.cssText = "position:absolute;left:0;right:0;bottom:" + S.bottom + "px;text-align:center;pointer-events:none;z-index:100;" +
      "font:800 " + S.size + "px " + S.font + ";color:" + S.color + ";-webkit-text-stroke:" + Math.round(S.size / 7) + "px " + S.ink +
      ";paint-order:stroke fill;text-shadow:" + Math.round(S.size / 14) + "px " + Math.round(S.size / 11) + "px 0 " + S.ink + ";white-space:nowrap";
    root.appendChild(box);
  }
  var shown = null;
  function render(t) {
    var L = window.LYRICS || [], cur = null, next = null;
    for (var i = 0; i < L.length; i++) {
      if (t >= L[i][0] && t < L[i][1] + 0.3) { cur = L[i]; next = L[i + 1]; }
    }
    if (cur && next && t > next[0] - 0.24) cur = null;           // 下一句前 0.24 秒收走
    if (cur !== shown) {
      box.innerHTML = cur ? Array.from(cur[2]).map(function (ch) { return '<span style="display:inline-block">' + (ch === " " ? "&nbsp;" : ch) + "</span>"; }).join("") : "";
      shown = cur;
    }
    if (!cur) return;
    var spans = box.children;
    for (var k = 0; k < spans.length; k++) {
      var u = Math.min(1, Math.max(0, (t - cur[0] - k * 0.045) / 0.18));   // 每个字 0.18 秒弹到位
      var s = u <= 0 ? 0 : 1 + 0.25 * Math.sin(Math.PI * u) * (1 - u);     // 先冲过一点再回来
      spans[k].style.transform = "scale(" + s.toFixed(3) + ")";
      spans[k].style.opacity = u > 0 ? 1 : 0;
    }
  }
  window.LYRIC_LAYER = { mount: mount, render: render };
})();
