/* 记忆银河 —— Canvas 2D 伪 3D 星图，零依赖 */
(function () {
  var canvas = document.getElementById('sky');
  var ctx = canvas.getContext('2d');

  var state = {
    points: [],
    kinds: [],
    stats: {},
    spin: true,
    glow: true,
    labels: true,
    angle: 0,
    tilt: 0.42,
    zoom: 1,
    dragging: false,
    lastX: 0,
    lastY: 0,
    cutoff: 1,
    filter: '',
    dpr: Math.min(window.devicePixelRatio || 1, 2),
  };

  function fit() {
    canvas.width = innerWidth * state.dpr;
    canvas.height = innerHeight * state.dpr;
    canvas.style.width = innerWidth + 'px';
    canvas.style.height = innerHeight + 'px';
    ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
  }
  window.addEventListener('resize', fit);
  fit();

  // ---------- 数据 ----------
  function load() {
    fetch('/api/galaxy').then(function (r) { return r.json(); }).then(function (d) {
      state.points = d.points || [];
      state.kinds = d.kinds || [];
      state.stats = d.stats || {};
      layout();
      paintPanels();
    }).catch(function () {
      document.getElementById('hud').textContent = '数据没拉到，检查服务是否在跑';
    });
  }

  function layout() {
    var n = state.points.length;
    if (!n) return;
    var tMin = Infinity, tMax = -Infinity;
    state.points.forEach(function (p) {
      var t = Date.parse(p.ts) || 0;
      p._t = t;
      if (t < tMin) tMin = t;
      if (t > tMax) tMax = t;
    });
    var span = Math.max(1, tMax - tMin);
    var twoPi = Math.PI * 2;
    state.points.forEach(function (p, i) {
      // 时间决定半径（越新越靠外），角度散开，y 做薄盘
      var age = (tMax - p._t) / span;          // 0 最新，1 最老
      var r = 60 + (1 - age) * 300;
      var a = (i / n) * twoPi * 7 + Math.random() * 0.6;
      p.x = Math.cos(a) * r + (Math.random() - 0.5) * 40;
      p.z = Math.sin(a) * r + (Math.random() - 0.5) * 40;
      p.y = (Math.random() - 0.5) * (18 + age * 40);
      p._r = Math.random();
      p._label = i % 17 === 0;
    });
  }

  // ---------- 背景星空 ----------
  var bgStars = [];
  function seedBg() {
    bgStars = [];
    for (var i = 0; i < 560; i++) {
      // 极坐标 + 旋转，做出银河带的密度感
      var ang = Math.random() * Math.PI * 2;
      var rad = Math.pow(Math.random(), 1.7) * 0.52;
      var cx = 0.5 + Math.cos(ang) * rad;
      var cy = 0.54 + Math.sin(ang) * rad * 0.46;
      bgStars.push({
        x: cx + (Math.random() - 0.5) * 0.06,
        y: cy + (Math.random() - 0.5) * 0.05,
        r: Math.random() * 1.3 + 0.25,
        p: Math.random() * 6.2832,
        speed: 0.0004 + Math.random() * 0.0012,
        w: rad,
      });
    }
  }
  seedBg();
  window.addEventListener('resize', seedBg);

  function drawBg(t) {
    for (var i = 0; i < bgStars.length; i++) {
      var s = bgStars[i];
      var fade = Math.max(0.15, 1 - s.w * 1.6);
      var a = (0.10 + 0.16 * (0.5 + 0.5 * Math.sin(t * s.speed + s.p))) * fade;
      ctx.fillStyle = 'rgba(200,220,255,' + a.toFixed(3) + ')';
      ctx.beginPath();
      ctx.arc(s.x * innerWidth, s.y * innerHeight, s.r, 0, 6.2832);
      ctx.fill();
    }
  }

  // ---------- 渲染 ----------
  var frames = 0, fpsT = 0, fps = 0;

  function project(p) {
    var ca = Math.cos(state.angle), sa = Math.sin(state.angle);
    var x1 = p.x * ca - p.z * sa;
    var z1 = p.x * sa + p.z * ca;
    var y1 = p.y * Math.cos(state.tilt) - z1 * Math.sin(state.tilt);
    var z2 = p.y * Math.sin(state.tilt) + z1 * Math.cos(state.tilt);
    var focal = 620;
    var scale = focal / (focal + z2 + 420) * state.zoom;
    return {
      x: innerWidth / 2 + x1 * scale,
      y: innerHeight / 2 - y1 * scale - 30,
      s: scale,
      z: z2,
      depth: (z2 + 420) / 840,
    };
  }

  function visible(p) {
    if (p._age === undefined) {
      p._age = 0;
    }
    return state.cutoff >= 1 || p._norm <= state.cutoff;
  }

  function draw() {
    var w = innerWidth, h = innerHeight;
    // 背景
    var g = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.max(w, h) * 0.75);
    g.addColorStop(0, '#0a1220');
    g.addColorStop(0.55, '#060a13');
    g.addColorStop(1, '#03050a');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);
    drawBg(performance.now());

    var pts = state.points;
    var proj = [];
    for (var i = 0; i < pts.length; i++) {
      var p = pts[i];
      if (!visible(p)) continue;
      var s = project(p);
      if (s.x < -60 || s.x > w + 60 || s.y < -60 || s.y > h + 60) continue;
      s.p = p;
      proj.push(s);
    }
    proj.sort(function (a, b) { return b.z - a.z; });

    for (var k = 0; k < proj.length; k++) {
      var q = proj[k];
      var p = q.p;
      var base = 0.9 + p._r * 1.9;
      var size = Math.max(1.7, base * Math.max(0.35, q.s));
      var bright = 0.35 + (1 - Math.max(0, Math.min(1, q.depth))) * 0.75;

      if (state.filter && (p.text || '').indexOf(state.filter) < 0 && (p.kind || '').indexOf(state.filter) < 0) {
        bright *= 0.18;
      }

      if (state.glow && size > 1.4) {
        var gg = ctx.createRadialGradient(q.x, q.y, 0, q.x, q.y, size * 4);
        gg.addColorStop(0, 'rgba(160,200,255,' + (0.32 * bright) + ')');
        gg.addColorStop(1, 'rgba(120,170,255,0)');
        ctx.fillStyle = gg;
        ctx.beginPath();
        ctx.arc(q.x, q.y, size * 4, 0, 6.2832);
        ctx.fill();
      }

      ctx.fillStyle = 'rgba(' + (p.kind === 'thought' ? '190,220,255' : p.kind === 'feeling' ? '255,215,170' : '225,238,255') + ',' + bright + ')';
      ctx.beginPath();
      ctx.arc(q.x, q.y, size, 0, 6.2832);
      ctx.fill();
    }

    // 标签
    if (state.labels) {
      ctx.font = '12px "Microsoft YaHei UI", sans-serif';
      var shown = 0;
      for (var j = proj.length - 1; j >= 0 && shown < 10; j--) {
        var q2 = proj[j];
        var txt = (q2.p.text || '').slice(0, 14);
        if (!txt.trim()) continue;
        if (q2.s < 0.75) continue;
        written(q2, txt);
        shown++;
      }
    }

    frames++;
    var now = performance.now();
    if (now - fpsT > 500) {
      fps = Math.round(frames * 1000 / (now - fpsT));
      frames = 0;
      fpsT = now;
      document.getElementById('hud').textContent =
        '拖拽旋转 · 滚轮缩放 · 点击看条目 · ' + proj.length + ' 点 · ' + fps + ' fps';
    }

    if (state.spin && !state.dragging) state.angle += 0.0016;
    if (document.hidden) {
      pauseChain();
      return;
    }
    requestAnimationFrame(draw);
  }

  var paused = false;
  function pauseChain() {
    if (paused) return;
    paused = true;
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden && paused) {
        paused = false;
        requestAnimationFrame(draw);
      }
    }, { once: true });
  }

  function written(q, txt) {
    ctx.fillStyle = 'rgba(150,180,235,0.72)';
    ctx.fillText(txt, q.x + 7, q.y + 3.5);
    ctx.strokeStyle = 'rgba(120,160,255,0.28)';
    ctx.beginPath();
    ctx.arc(q.x, q.y, 3.2, 0, 6.2832);
    ctx.stroke();
  }

  // ---------- 面板 ----------
  var KIND_CN = { event: '事件', thought: '想法', feeling: '情绪', note: '备注' };

  function paintPanels() {
    var s = state.stats || {};
    document.getElementById('sTotal').textContent = s.total || 0;
    document.getElementById('sMood').textContent = s.avgMood || 0;
    document.getElementById('sDays').textContent = s.days || 0;
    document.getElementById('sFolders').textContent = s.folders || 0;

    document.getElementById('levels').innerHTML = state.kinds.map(function (k) {
      return '<li><i></i>' + (KIND_CN[k.kind] || k.kind) + '<b>' + k.count + '</b></li>';
    }).join('') || '<li>还没有记录</li>';

    document.getElementById('meta').innerHTML =
      '记忆点 <b>' + (s.total || 0) + '</b> · 跨 <b>' + (s.days || 0) + '</b> 天<br>' +
      '平均情绪 <b>' + (s.avgMood || 0) + '</b> · 文件夹 <b>' + (s.folders || 0) + '</b> 个';

    var recent = state.points.slice(-8).reverse();
    document.getElementById('recent').innerHTML = recent.map(function (p) {
      return '<li>' + (p.text || '').slice(0, 40).replace(/</g, '&lt;') + '</li>';
    }).join('') || '<li>还没有</li>';
  }

  // ---------- 交互 ----------
  canvas.addEventListener('mousedown', function (e) {
    state.dragging = true;
    state.lastX = e.clientX;
    state.lastY = e.clientY;
  });
  window.addEventListener('mouseup', function () { state.dragging = false; });
  window.addEventListener('mousemove', function (e) {
    if (!state.dragging) return;
    state.angle += (e.clientX - state.lastX) * 0.006;
    state.tilt = Math.max(-1.2, Math.min(1.2, state.tilt + (e.clientY - state.lastY) * 0.004));
    state.lastX = e.clientX;
    state.lastY = e.clientY;
  });
  canvas.addEventListener('wheel', function (e) {
    e.preventDefault();
    state.zoom = Math.max(0.4, Math.min(3, state.zoom * (e.deltaY > 0 ? 0.92 : 1.08)));
  }, { passive: false });

  canvas.addEventListener('click', function (e) {
    var best = null, bestD = 14;
    for (var i = 0; i < state.points.length; i++) {
      var p = state.points[i];
      if (!visible(p)) continue;
      var q = project(p);
      var d = Math.hypot(q.x - e.clientX, q.y - e.clientY);
      if (d < bestD) { bestD = d; best = p; }
    }
    var tip = document.getElementById('tip');
    if (best) {
      tip.style.display = 'block';
      tip.style.left = Math.min(e.clientX + 14, innerWidth - 300) + 'px';
      tip.style.top = Math.min(e.clientY + 14, innerHeight - 140) + 'px';
      tip.innerHTML = '<b>' + (best.ts || '').slice(0, 16).replace('T', ' ') + '</b><br>' +
        (best.text || '').slice(0, 90).replace(/</g, '&lt;');
      setTimeout(function () { tip.style.display = 'none'; }, 4200);
    }
  });

  // 按钮
  var bSpin = document.getElementById('btnSpin');
  var bGlow = document.getElementById('btnGlow');
  var bLabel = document.getElementById('btnLabel');
  bSpin.onclick = function () { state.spin = !state.spin; bSpin.classList.toggle('on', state.spin); };
  bGlow.onclick = function () { state.glow = !state.glow; bGlow.classList.toggle('on', state.glow); };
  bLabel.onclick = function () { state.labels = !state.labels; bLabel.classList.toggle('on', state.labels); };
  document.getElementById('btnTop').onclick = function () { state.tilt = 1.15; };
  document.getElementById('btnReset').onclick = function () {
    state.tilt = 0.42; state.zoom = 1; state.angle = 0;
    state.cutoff = 1;
    document.getElementById('tl').value = 100;
    document.getElementById('rangeLabel').textContent = '全部';
  };

  // 时间轴
  var tl = document.getElementById('tl');
  tl.oninput = function () {
    state.cutoff = tl.value / 100;
    var n = state.points.length;
    var from = Math.round(n * (1 - state.cutoff));
    document.getElementById('rangeLabel').textContent =
      state.cutoff >= 1 ? '全部' : ('最近 ' + Math.round(state.cutoff * 100) + '%');
    if (n) {
      var t = state.points[from] ? state.points[from].ts : '';
      document.getElementById('hud').textContent = '从 ' + (t || '').slice(0, 10) + ' 之后';
    }
  };

  // 搜索
  var si = document.getElementById('search');
  si.oninput = function () {
    state.filter = si.value.trim();
    var box = document.getElementById('hits');
    if (!state.filter) { box.innerHTML = ''; return; }
    var hit = state.points.filter(function (p) {
      return (p.text || '').indexOf(state.filter) >= 0 || (p.kind || '').indexOf(state.filter) >= 0;
    }).slice(-12).reverse();
    box.innerHTML = hit.map(function (p) {
      return '<div>' + (p.ts || '').slice(5, 16).replace('T', ' ') + ' ' +
        (p.text || '').slice(0, 24).replace(/</g, '&lt;') + '</div>';
    }).join('') || '<div>没找到</div>';
  };

  // 先把点的“新旧归一化”算好，供时间轴过滤
  function normalize() {
    var n = state.points.length;
    state.points.forEach(function (p, i) { p._norm = n <= 1 ? 0 : i / (n - 1); });
  }

  load();
  var timer = setInterval(function () {
    if (state.points.length) { normalize(); clearInterval(timer); }
  }, 300);

  requestAnimationFrame(draw);
})();
