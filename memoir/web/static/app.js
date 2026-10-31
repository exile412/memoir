'use strict';

var KIND_LABEL = { event: '事件', thought: '想法', feeling: '情绪', note: '备注' };
var FENCE = String.fromCharCode(96, 96, 96);
var state = { boot: null, entries: [], group: '', currentId: null };
var busy = false;

function $(id) { return document.getElementById(id); }

function api(path, opt) {
  opt = opt || {};
  var init = { method: opt.method || 'GET', headers: { 'Content-Type': 'application/json' } };
  if (opt.body) init.body = JSON.stringify(opt.body);
  return fetch('/api/' + path, init).then(function (r) {
    return r.json().catch(function () { return { error: 'HTTP ' + r.status }; });
  });
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function kindLabel(k) { return KIND_LABEL[k] || k; }

function formatText(text) {
  var parts = String(text).split(FENCE);
  var html = '';
  for (var i = 0; i < parts.length; i++) {
    if (i % 2 === 1) {
      var code = parts[i].replace(/^[a-zA-Z0-9+#-]*\n/, '');
      html += '<pre><code>' + (window.highlightCode ? highlightCode(code) : esc(code)) + '</code></pre>';
    } else if (parts[i].trim()) {
      html += '<span>' + esc(parts[i]).replace(/\n/g, '<br>') + '</span>';
    }
  }
  return html || esc(text);
}

function hasCode(text) {
  if (text.indexOf(FENCE) !== -1) return true;
  return /(^|\n)\s*(def |class |function |const |let |import |from |#include|public |private |SELECT |CREATE TABLE)/.test(text);
}

function bubble(role, inner) {
  var who = role === 'me' ? '你' : 'memoir';
  var av = role === 'me' ? '<div class="avatar me">你</div>' : '<div class="avatar">◈</div>';
  return '<div class="bubble">' + av + '<div class="body"><div class="who">' + who +
    '</div>' + inner + '</div></div>';
}

function entryInner(e) {
  var time = (e.ts || '').slice(11, 16);
  var title = e.title ? '<span>' + esc(e.title) + '</span>' : '';
  return '<div class="card"><div class="meta"><span>' + time + '</span>' +
    '<span class="tag">' + esc(kindLabel(e.kind)) + '</span>' + title + '</div>' +
    '<div class="txt">' + formatText(e.text) + '</div></div>';
}

function push(node) {
  var chat = $('chat');
  var wrap = chat.querySelector('.wrap');
  if (!wrap) { wrap = document.createElement('div'); wrap.className = 'wrap'; chat.appendChild(wrap); }
  wrap.insertAdjacentHTML('beforeend', node);
  chat.scrollTop = chat.scrollHeight;
}

function clearChat() { $('chat').innerHTML = '<div class="wrap"></div>'; }

function renderGreeting() {
  push(bubble('ai', '<div class="txt">今天想要记录什么？<br>' +
    '<span style="color:var(--text-3);font-size:13px">直接写就行，口语也可以。' +
    '需要的话我帮你美化或整理。</span></div>'));
}

function renderList() {
  var chat = document.getElementById('chat');
  if (!chat) return;
  if (!state.entries.length) {
    clearChat();
    push(bubble('ai', '没搜到相关的记录。'))
    return;
  }
  clearChat();
  push(bubble('ai', '搜到 ' + state.entries.length + ' 条：'));
  state.entries.forEach(function (e) {
    var b = document.createElement('div');
    b.className = 'msg ai';
    var when = (e.ts || '').slice(0, 16).replace('T', ' ');
    b.innerHTML = '<div class="bubble">' + formatText(e.text) +
      '<div class="meta">' + when + ' · ' + esc(kindLabel(e.kind)) + '</div></div>';
    chat.appendChild(b);
  });
}
function loadEntries() {
  var q = $('search').value.trim();
  var url = q ? ('entries?q=' + encodeURIComponent(q)) : 'entries';
  return api(url).then(function (res) {
    state.entries = res.entries || [];
    renderList();
    loadTree();
  });
}

function loadGroups() {
  return Promise.all([
    api('byauthor'),
    api('entries?author=me'),
    api('entries?author=ai')
  ]).then(function (res) {
    var c = (res[0] && res[0].counts) || {};
    if ($('cntMe')) $('cntMe').textContent = c.me || 0;
    if ($('cntAi')) $('cntAi').textContent = c.ai || 0;
    var mine = (res[1] && res[1].entries) || [];
    var hers = (res[2] && res[2].entries) || [];
    state.entries = mine;
    state.mine = mine;
    state.hers = hers;
    renderGroup('listMe', mine);
    renderGroup('listAi', hers);
  });
}

function showEntryDetail(e) {
  clearChat();
  var wrap = document.createElement('div');
  wrap.className = 'msg ai';
  var when = fmtWhen(e.ts, true);
  wrap.innerHTML = '<div class="bubble">' + formatText(e.text) +
    '<div class="meta">' + when + ' · ' + esc(kindLabel(e.kind)) + '</div></div>';
  document.getElementById('chat').appendChild(wrap);
}

function renderGroup(id, list) {
  var el = document.getElementById(id);
  if (!el) return;
  if (!list.length) {
    el.innerHTML = '<div class="group-empty">还没有</div>';
    return;
  }
  el.innerHTML = '';
  list.forEach(function (e) {
    var time = (e.ts || '').slice(11, 16);
    var title = e.title || (e.text || '').slice(0, 18);
    var div = document.createElement('div');
    div.className = 'item' + (state.currentId === e.id ? ' active' : '');
    div.innerHTML = '<b>' + esc(title) + '</b><small>' + time + ' · ' + esc(kindLabel(e.kind)) + '</small>';
    div.onclick = function () {
      state.currentId = e.id;
      showEntryDetail(e);
      renderGroup('listMe', state.mine || []);
      renderGroup('listAi', state.hers || []);
    };
    el.appendChild(div);
  });
}
function setBusy(on) {
  busy = on;
  $('sendBtn').disabled = on;
  $('sendBtn').innerHTML = on ? '<span class="loading"></span>处理中' : '发送';
}

function setHint(msg) { $('hint').textContent = msg || ''; }

function autoGrow() {
  var el = $('input');
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 220) + 'px';
}

function send() {
  if (busy) return;
  var text = $('input').value.trim();
  if (!text) return;

  if (hasCode(text) && !state.group) {
    var g = prompt('检测到代码内容，归到哪个分组？（可留空）', '代码');
    if (g === null) return;
    state.group = g.trim();
    $('groupBtn').textContent = state.group ? ('分组：' + state.group) : '分组';
    $('groupBtn').classList.toggle('on', !!state.group);
  }

  var mode = $('mode').value;
  var payload = {
    text: text,
    kind: $('kind').value,
    mode: mode,
    autoTitle: $('titleToggle').dataset.on === '1',
    tags: state.group
  };

  setBusy(true);
  setHint(mode === 'raw' ? '保存中…' : 'AI 处理中，可能要几十秒…');
  push(bubble('me', entryInner({ ts: new Date().toISOString(), kind: payload.kind, text: text })));

  api('entries', { method: 'POST', body: payload }).then(function (res) {
    setBusy(false);
    setHint('');
    if (res.error) {
      push(bubble('ai', '<div class="txt" style="color:#e06c6c">' + esc(res.error) + '</div>'));
      return;
    }
    $('input').value = '';
    autoGrow();
    if (res.entry) push(bubble('ai', entryInner(res.entry)));
    if (res.entry && res.entry.meta && res.entry.meta.original) {
      push(bubble('ai', '<div class="txt" style="color:var(--text-3);font-size:13px">原文已保留，随时可对照。</div>'));
    }
    restoreOpen();
    loadTree();
  }).catch(function (err) {
    setBusy(false);
    setHint('请求失败：' + err);
  });
}

function doReview() {
  $('pageTitle').textContent = '生成复盘';
  clearChat();
  push(bubble('ai', '<div class="txt"><span class="loading"></span>正在回顾今天的记录…</div>'));
  api('review', { method: 'POST', body: {} }).then(function (res) {
    clearChat();
    if (!res.review) {
      push(bubble('ai', '<div class="txt">' + esc(res.message || '今天还没有记录') + '</div>'));
      return;
    }
    var s = res.review.sections || {};
    var labels = {
      events: '今天做了什么', thoughts: '心里话与情绪', thinking: '想法与思维变化',
      character: '性格与状态', closing: '给你的话'
    };
    var html = '<div class="card">';
    Object.keys(labels).forEach(function (k) {
      if (!s[k]) return;
      html += '<div class="review-sec"><h4>' + labels[k] + '</h4><p>' + esc(s[k]) + '</p></div>';
    });
    html += '<div class="meta">依据 ' + res.review.entries + ' 条 · 模型 ' +
      esc(res.review.model) + '</div></div>';
    push(bubble('ai', html));
  });
}

function doPersona() {
  $('pageTitle').textContent = '人格档案';
  clearChat();
  push(bubble('ai', '<div class="txt"><span class="loading"></span>正在读取档案…</div>'));
  api('persona').then(function (res) {
    clearChat();
    push(bubble('ai', '<div class="card"><div class="txt">' + esc(res.text || '还没有档案') + '</div></div>'));
  });
}

function openDrawer() {
  $('drawer').classList.add('open');
  $('scrim').classList.add('show');
  loadSettings();
}
function closeDrawer() {
  $('drawer').classList.remove('open');
  $('scrim').classList.remove('show');
}

function loadSettings() {
  api('settings').then(function (s) {
    $('setBaseUrl').value = s.model.baseUrl || '';
    $('setModel').value = s.model.name || '';
    $('setKey').value = s.model.apiKey || '';
    $('setTemp').value = s.model.temperature;
    $('setTimeout').value = s.model.timeout;
    $('setWallpaperDir').value = s.wallpaperDir || '';
  });
  loadWallpapers();
  api('bootstrap').then(function (b) {
    $('dataNote').textContent = '版本 ' + b.version + ' · 共 ' + b.stats.entries +
      ' 条记录 · ' + b.stats.days + ' 天';
    renderWallpapers(b.wallpapers || []);
  });
}

function saveSettings() {
  var body = {
    model: {
      baseUrl: $('setBaseUrl').value.trim(),
      name: $('setModel').value.trim(),
      apiKey: $('setKey').value,
      temperature: parseFloat($('setTemp').value) || 0.7,
      timeout: parseInt($('setTimeout').value, 10) || 120
    },
    wallpaperDir: $('setWallpaperDir').value.trim()
  };
  api('settings', { method: 'POST', body: body }).then(function (res) {
    $('modelNote').textContent = res.ok ? ('已保存到 ' + res.savedTo) : ('保存失败：' + res.error);
  });
}

function testModel() {
  $('modelNote').innerHTML = '<span class="loading"></span>测试中…';
  api('model/test', { method: 'POST', body: {} }).then(function (res) {
    $('modelNote').textContent = (res.ok ? '可用：' : '不可用：') + (res.detail || '');
  });
}

function renderWallpapers(list) {
  var grid = $('wallGrid');
  grid.innerHTML = '';
  if (!list.length) {
    grid.innerHTML = '<p class="note">没找到壁纸。装 Wallpaper Engine 后会自动读取创意工坊目录，' +
      '也可以在上面指定图片文件夹。</p>';
    return;
  }
  list.forEach(function (w) {
    var url = '/api/wallpaper?id=' + encodeURIComponent(w.id);
    var d = document.createElement('div');
    d.className = 'wall';
    if (w.kind === 'video') {
      d.innerHTML = '<video muted loop playsinline preload="metadata" src="' + url + '"></video>' +
        '<span class="wall-badge">动态</span>';
      d.onmouseenter = function () {
        var v = d.querySelector('video');
        if (v) { v.play().catch(function () {}); }
      };
      d.onmouseleave = function () {
        var v = d.querySelector('video');
        if (v) { v.pause(); v.currentTime = 0; }
      };
    } else {
      d.innerHTML = '<img loading="lazy" src="' + url + '" alt="">';
    }
    d.onclick = function () { applyWallpaper(w.id, w.kind); };
    grid.appendChild(d);
  });
}

function loadWallpapers() {
  api('wallpapers').then(function (res) { renderWallpapers(res.wallpapers || []); });
}

function applyWallpaper(id, kind) {
  var layer = $('wpLayer');
  if (!id) {
    layer.innerHTML = '';
    layer.classList.remove('show');
    document.body.classList.remove('has-wallpaper');
    localStorage.removeItem('memoir.wallpaper');
    return;
  }
  var url = '/api/wallpaper?id=' + encodeURIComponent(id);
  if (kind === 'video') {
    layer.innerHTML = '<video autoplay muted loop playsinline preload="auto" src="' + url + '"></video>';
  } else {
    layer.innerHTML = '<img src="' + url + '" alt="">';
  }
  layer.classList.add('show');
  document.body.classList.add('has-wallpaper');
  localStorage.setItem('memoir.wallpaper', JSON.stringify({ id: id, kind: kind || 'image' }));
}

function applyBright(v) {
  var n = Math.max(30, Math.min(100, parseInt(v, 10) || 68)) / 100;
  document.documentElement.style.setProperty('--wp-brightness', n.toFixed(2));
  // 亮一点就把遮罩也减一点，否则白调
  var veil = Math.max(0.12, 0.5 - n * 0.32).toFixed(2);
  document.documentElement.style.setProperty('--wp-veil', veil);
  localStorage.setItem('memoir.wpBright', String(Math.round(n * 100)));
  if (document.getElementById('wpVal')) {
    document.getElementById('wpVal').textContent = Math.round(n * 100) + '%';
  }
}

function restoreWallpaper() {
  var raw = localStorage.getItem('memoir.wallpaper');
  if (!raw) return;
  try {
    var o = JSON.parse(raw);
    if (o && o.id) applyWallpaper(o.id, o.kind);
  } catch (e) {
    applyWallpaper(raw, 'image');   // 兼容旧的纯字符串
  }
}

function toggleSidebar(open) {
  $('sidebar').classList.toggle('open', open);
  $('scrim').classList.toggle('show', open);
}

function isMobile() { return window.innerWidth <= 860; }

function startApp() {
  restoreWallpaper();
  if (isMobile()) $('input').placeholder = '写点什么，回车发送…';
  api('bootstrap').then(function (b) {
    if (b.error) return;
    state.boot = b;
    clearChat();
    renderGreeting();
    loadEntries();
  });

  try {
  $('sendBtn').onclick = send;
  $('input').addEventListener('input', autoGrow);
  $('input').addEventListener('keydown', function (e) {
    // 回车发送，Shift+回车换行；Ctrl/Cmd+回车也发送（多行时习惯用）
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });

  $('titleToggle').onclick = function () {
    var on = this.dataset.on === '1';
    this.dataset.on = on ? '0' : '1';
    this.classList.toggle('on', !on);
  };
  $('titleToggle').classList.add('on');

  $('groupBtn').onclick = function () {
    var g = prompt('分组名（留空表示不分组）', state.group || '');
    if (g === null) return;
    state.group = g.trim();
    this.textContent = state.group ? ('分组：' + state.group) : '分组';
    this.classList.toggle('on', !!state.group);
  };

  $('search').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') loadEntries();
  });

  $('newBtn').onclick = function () {
    $('input').focus();
    $('pageTitle').textContent = '记忆库';
    closeDrawer();
    toggleSidebar(false);
  };

  Array.prototype.forEach.call(document.querySelectorAll('.foot-btn'), function (b) {
    b.onclick = function () {
      var act = b.dataset.act;
      toggleSidebar(false);
      if (act === 'galaxy') openGalaxy();
      else if (act === 'insights') openInsights();
      else if (act === 'review') doReview();
      else if (act === 'persona') doPersona();
      else openDrawer();
    };
  });

  $('drawerClose').onclick = closeDrawer;
  $('scrim').onclick = closeDrawer;
  $('saveSettings').onclick = saveSettings;
  $('testModel').onclick = testModel;
  $('reloadWallpapers').onclick = loadWallpapers;
  $('clearWallpaper').onclick = function () { applyWallpaper(null); };
  if ($('wpBright')) {
    var saved = localStorage.getItem('memoir.wpBright') || '68';
    $('wpBright').value = saved;
    applyBright(saved);
    $('wpBright').oninput = function () { applyBright(this.value); };
  }
  if ($('launchWE')) $('launchWE').onclick = function () {
    api('wallpaper/launch', { method: 'POST', body: {} }).then(function (r) {
      $('dataNote').textContent = r.ok ? '已请求启动 Wallpaper Engine' : ('启动失败：' + r.error);
    });
  };
  $('exportBtn').onclick = function () { window.open('/api/export', '_blank'); };

  if ($('notesOpen')) $('notesOpen').onclick = function () {
    api('notes/open', { method: 'POST', body: {} }).then(function (r) {
      $('notesNote').textContent = r.ok ? ('已打开：' + r.dir) : ('打开失败：' + r.error);
    });
  };
  if ($('notesExport')) $('notesExport').onclick = function () {
    api('notes/export', { method: 'POST', body: {} }).then(function (r) {
      $('notesNote').textContent = '写出 ' + r.written + ' 个文件到 ' + r.dir;
    });
  };
  if ($('notesSync')) $('notesSync').onclick = function () {
    $('notesNote').textContent = '同步中…';
    api('notes/sync', { method: 'POST', body: {} }).then(function (r) {
      $('notesNote').textContent = '新增 ' + r.added + ' / 更新 ' + r.updated + ' / 删除 ' + r.removed;
      loadTree();
    });
  };
  $('refreshBtn').onclick = function () { loadEntries(); loadSettings(); };
  $('menuBtn').onclick = function () { toggleSidebar(true); };
  } catch (e) { console.error('startApp bind error', e); }
}


function openGalaxy() {
  var layer = document.getElementById('galaxyLayer');
  var frame = document.getElementById('galaxyFrame');
  if (!layer || !frame) return;
  if (!frame.src || frame.src.indexOf('galaxy') < 0) {
    frame.src = '/static/galaxy/index.html?v=' + Date.now();
  }
  layer.classList.add('show');
  if (document.getElementById('galaxyClose')) {
    document.getElementById('galaxyClose').onclick = function () {
      layer.classList.remove('show');
      // 清空 iframe，让 WebView2 回收那块渲染进程
      setTimeout(function () { frame.src = 'about:blank'; }, 120);
    };
  }
}

function openInsights() {
  api('insights?days=30').then(function (d) {
    if (d.error) return;
    var el = document.getElementById('insightStats');
    el.innerHTML = [
      ['总记录', d.total],
      ['连续天数', d.streak + ' 天'],
      ['活跃时段', (function () {
        if (!d.hours.length) return '—';
        var top = d.hours.slice().sort(function (a, b) { return b.count - a.count; })[0];
        return top.hour + ':00';
      })()]
    ].map(function (p) { return '<div><b>' + p[1] + '</b><span>' + p[0] + '</span></div>'; }).join('');

    var max = Math.max.apply(null, d.series.map(function (x) { return x.count; }).concat([1]));
    var bars = document.getElementById('insightBars');
    bars.innerHTML = d.series.map(function (x) {
      var hpx = x.count ? Math.max(4, Math.round(x.count / max * 100)) : 2;
      var mood = x.mood === null ? '' : (x.mood > 0 ? ' 情绪+' + x.mood : ' 情绪' + x.mood);
      return '<i class="' + (x.count ? '' : 'empty') + '" style="height:' + hpx + '%" title="' +
        x.day + '：' + x.count + ' 条' + mood + '"></i>';
    }).join('');

    var foot = document.getElementById('insightFoot');
    var kinds = (d.kinds || []).map(function (k) { return '<span>' + (kindLabel(k.kind)) + ' ' + k.count + '</span>'; });
    foot.innerHTML = kinds.join('') || '<span>还没有记录</span>';

    document.getElementById('insightLayer').classList.add('show');
  });
}
// ---------- 登录 ----------
var authMode = 'login';

function showAuth(sub, note) {
  $('authLayer').classList.add('show');
  $('authSub').textContent = sub || '';
  $('authNote').textContent = note || '';
  $('authPwd2').style.display = (authMode === 'setup') ? 'block' : 'none';
  setTimeout(function () { $('authPwd').focus(); }, 60);
}

function hideAuth() { $('authLayer').classList.remove('show'); }

function loginWith(pwd) {
  $('authBtn').disabled = true;
  return api('auth/login', { method: 'POST', body: { password: pwd } }).then(function (r) {
    $('authBtn').disabled = false;
    if (r.error) { $('authNote').textContent = r.error; return; }
    hideAuth();
    $('authPwd').value = '';
    $('authPwd2').value = '';
    startApp();
  });
}

function doAuth() {
  var pwd = $('authPwd').value;
  var note = $('authNote');
  note.textContent = '';
  if (!pwd) { note.textContent = '密码不能为空'; return; }

  if (authMode === 'setup') {
    var pwd2 = $('authPwd2').value;
    if (pwd.length < 4) { note.textContent = '至少 4 位'; return; }
    if (pwd !== pwd2) { note.textContent = '两次输入不一致'; return; }
    $('authBtn').disabled = true;
    api('auth/setup', { method: 'POST', body: { password: pwd } }).then(function (r) {
      if (r.error) { $('authBtn').disabled = false; note.textContent = r.error; return; }
      authMode = 'login';
      return loginWith(pwd);
    });
    return;
  }
  loginWith(pwd);
}

function checkAuth() {
  return api('auth/status').then(function (s) {
    // 没有设过密码就直接放行——本地工具，不逼用户先设密码。
    // 想加密码的，在设置抽屉里点「设置访问密码」。
    if (!s.enabled) return true;
    return fetch('/api/bootstrap').then(function (r) {
      if (r.status === 401) {
        authMode = 'login';
        showAuth('请输入访问密码', '');
        return false;
      }
      return true;
    });
  });
}

// ---------- 晚间提醒 ----------
function checkReminder() {
  try {
    var now = new Date();
    if (now.getHours() < 20) return;
    var boot = state.boot || {};
    if (!boot.today || !boot.todayCount) return;
    if (sessionStorage.getItem('memoir.remind.dismiss') === boot.today) return;
    api('review?day=' + encodeURIComponent(boot.today)).then(function (r) {
      if (r && r.review) return;
      $('reminder').classList.add('show');
    });
  } catch (e) {}
}



// ---------- 侧栏树 ----------
var treeState = { folders: [], entriesByFolder: {}, open: {}, sel: null, drag: null };

function loadTree() {
  return api('folders').then(function (r) {
    treeState.folders = r.folders || [];
    return fetchEntriesForTree(treeState.folders);
  }).then(function () { renderTree(); });
}

function walkFolders(list, fn) {
  (list || []).forEach(function (f) { fn(f); walkFolders(f.children, fn); });
}

function fetchEntriesForTree(list) {
  var ids = [];
  walkFolders(list, function (f) { ids.push(f.id); });
  return Promise.all(ids.map(function (id) {
    return api('entries?folder=' + id + '&limit=30').then(function (r) {
      treeState.entriesByFolder[id] = r.entries || [];
    });
  }));
}

function saveOpen() {
  try { localStorage.setItem('memoir.treeOpen', JSON.stringify(treeState.open)); } catch (e) {}
}

function restoreOpen() {
  try {
    var raw = localStorage.getItem('memoir.treeOpen');
    treeState.open = raw ? JSON.parse(raw) : {};
  } catch (e) { treeState.open = {}; }
}

function renderTree() {
  var box = document.getElementById('tree');
  if (!box) return;
  box.innerHTML = '';
  if (!treeState.folders.length) {
    box.innerHTML = '<div class="tree-empty">还没有文件夹，点上面「+ 文件夹」新建</div>';
    return;
  }
  treeState.folders.forEach(function (f) { box.appendChild(buildFolderNode(f, 0)); });
}

function buildFolderNode(f, depth) {
  var wrap = document.createElement('div');
  wrap.className = 'tnode';
  wrap.dataset.id = f.id;
  wrap.dataset.type = 'folder';

  var row = document.createElement('div');
  row.className = 'trow' + (treeState.sel && treeState.sel.id === f.id ? ' sel' : '');
  row.dataset.id = f.id;
  row.dataset.type = 'folder';
  row.draggable = true;
  var open = !!treeState.open[f.id];
  row.innerHTML =
    '<span class="tcaret' + (open ? ' open' : '') + '">▶</span>' +
    '<span class="ticon">' + (open ? '📂' : '📁') + '</span>' +
    '<span class="tname">' + esc(f.name) + '</span>' +
    '<span class="tcount">' + (f.count || '') + '</span>';

  row.onclick = function (ev) {
    if (ev.target.classList.contains('tcaret')) {
      treeState.open[f.id] = !treeState.open[f.id];
      saveOpen(); renderTree();
      return;
    }
    treeState.sel = { type: 'folder', id: f.id, name: f.name };
    renderTree();
    showFolderEntries(f);
  };

  row.oncontextmenu = function (ev) {
    ev.preventDefault();
    showCtxMenu(ev.clientX, ev.clientY, f);
  };

  bindDrag(row, { type: 'folder', id: f.id });
  wrap.appendChild(row);

  if (open) {
    var kids = document.createElement('div');
    kids.className = 'tkids';
    (f.children || []).forEach(function (c) { kids.appendChild(buildFolderNode(c, depth + 1)); });
    var list = treeState.entriesByFolder[f.id] || [];
    list.slice(0, 20).forEach(function (e) { kids.appendChild(buildEntryLeaf(e)); });
    if (!kids.children.length) {
      kids.innerHTML = '<div class="tree-empty" style="padding:6px 8px">空</div>';
    }
    wrap.appendChild(kids);
  }
  return wrap;
}

function fmtWhen(ts, full) {
  if (!ts) return '';
  var d = String(ts).slice(0, 10);
  var t = String(ts).slice(11, 16);
  if (full) return d + ' ' + t;
  var thisYear = String(new Date().getFullYear());
  return (d.slice(0, 4) === thisYear ? d.slice(5) : d) + ' ' + t;
}

function buildEntryLeaf(e) {
  var row = document.createElement('div');
  row.className = 'trow tleaf' + (treeState.sel && treeState.sel.type === 'entry' && treeState.sel.id === e.id ? ' sel' : '');
  row.dataset.id = e.id;
  row.dataset.type = 'entry';
  row.draggable = true;
  var when = fmtWhen(e.ts, false);
  var title = e.title || (e.text || '').slice(0, 12);
  row.title = fmtWhen(e.ts, true);
  row.innerHTML = '<span class="tcaret"></span>' +
    '<span class="tname"><b style="font-weight:400;color:var(--text-3)">' + when + '</b> ' +
    esc(title) + '</span>';
  row.onclick = function () {
    treeState.sel = { type: 'entry', id: e.id };
    renderTree();
    showEntryDetail(e);
  };
  bindDrag(row, { type: 'entry', id: e.id });
  return row;
}

function bindDrag(el, info) {
  el.addEventListener('dragstart', function (ev) {
    treeState.drag = info;
    el.classList.add('dragging');
    ev.dataTransfer.effectAllowed = 'move';
    ev.dataTransfer.setData('text/plain', info.type + ':' + info.id);
  });
  el.addEventListener('dragend', function () {
    el.classList.remove('dragging');
    treeState.drag = null;
    Array.prototype.forEach.call(document.querySelectorAll('.drop-into'), function (n) {
      n.classList.remove('drop-into');
    });
  });
  if (info.type !== 'folder') return;

  el.addEventListener('dragover', function (ev) {
    if (!treeState.drag) return;
    ev.preventDefault();
    ev.dataTransfer.dropEffect = 'move';
    el.classList.add('drop-into');
  });
  el.addEventListener('dragleave', function () { el.classList.remove('drop-into'); });
  el.addEventListener('drop', function (ev) {
    ev.preventDefault();
    el.classList.remove('drop-into');
    var d = treeState.drag;
    if (!d) return;
    if (d.type === 'folder') {
      if (d.id === info.id) return;
      api('folders/move', { method: 'POST', body: { id: d.id, parentId: info.id, sort: 0 } })
        .then(function (r) {
          if (r.error) { toast(r.error); return; }
          loadTree();
        });
    } else {
      api('entries/move', { method: 'POST', body: { id: d.id, folderId: info.id } })
        .then(function () { loadTree(); });
    }
  });
}

function showFolderEntries(f) {
  api('entries?folder=' + f.id + '&limit=60').then(function (r) {
    state.entries = r.entries || [];
    state.currentId = null;
    clearChat();
    if (!state.entries.length) {
      push(bubble('ai', '「' + f.name + '」里还没有东西。把条目拖进来，或者直接写一条。'));
      return;
    }
    state.entries.forEach(function (e) {
      var b = document.createElement('div');
      b.className = 'msg ai';
      var when = (e.ts || '').slice(0, 16).replace('T', ' ');
      b.innerHTML = '<div class="bubble">' + formatText(e.text) +
        '<div class="meta">' + when + ' · ' + esc(kindLabel(e.kind)) + '</div></div>';
      document.getElementById('chat').appendChild(b);
    });
  });
}

function showCtxMenu(x, y, f) {
  closeCtxMenu();
  var menu = document.createElement('div');
  menu.className = 'ctx';
  menu.id = 'ctxMenu';
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
  menu.innerHTML =
    '<button data-act="new">新建子文件夹</button>' +
    '<button data-act="rename">重命名</button>' +
    '<button data-act="delete" class="danger">删除</button>';
  document.body.appendChild(menu);
  Array.prototype.forEach.call(menu.querySelectorAll('button'), function (b) {
    b.onclick = function () {
      var act = b.dataset.act;
      closeCtxMenu();
      if (act === 'new') newFolder(f.id);
      else if (act === 'rename') renameFolder(f);
      else if (act === 'delete') deleteFolder(f);
    };
  });
}

function closeCtxMenu() {
  var m = document.getElementById('ctxMenu');
  if (m) m.remove();
}

function newFolder(parentId) {
  var name = prompt('文件夹名字', '新文件夹');
  if (!name) return;
  api('folders/add', { method: 'POST', body: { name: name, parentId: parentId || null } })
    .then(function (r) {
      if (r.error) { toast(r.error); return; }
      if (parentId) treeState.open[parentId] = true;
      saveOpen();
      loadTree();
    });
}

function renameFolder(f) {
  var name = prompt('新名字', f.name);
  if (!name || name === f.name) return;
  api('folders/rename', { method: 'POST', body: { id: f.id, name: name } })
    .then(function () { loadTree(); });
}

function deleteFolder(f) {
  if (!confirm('删除「' + f.name + '」？里面的子文件夹一起删，条目会回到根。')) return;
  api('folders/delete', { method: 'POST', body: { id: f.id } })
    .then(function () { treeState.sel = null; loadTree(); });
}

function toast(msg) {
  var el = document.getElementById('hint');
  if (el) { el.textContent = msg; setTimeout(function () { el.textContent = ''; }, 3000); }
}
function boot() {
  if (document.getElementById('newFolder')) document.getElementById('newFolder').onclick = function () { newFolder(null); };
  if (document.getElementById('treeExpand')) document.getElementById('treeExpand').onclick = function () {
    walkFolders(treeState.folders, function (f) { treeState.open[f.id] = true; });
    saveOpen(); renderTree();
  };
  if (document.getElementById('treeCollapse')) document.getElementById('treeCollapse').onclick = function () {
    treeState.open = {};
    saveOpen(); renderTree();
  };
  document.addEventListener('click', function (e) {
    if (!e.target.closest('.ctx') && !e.target.closest('.trow')) closeCtxMenu();
  });

  Array.prototype.forEach.call(document.querySelectorAll('.group-head'), function (b) {
    b.onclick = function () {
      var box = b.parentElement.querySelector('.list');
      var collapsed = b.classList.toggle('collapsed');
      if (box) box.style.display = collapsed ? 'none' : '';
      b.querySelector('i').textContent = collapsed ? '▸' : '▾';
    };
  });
  if (document.getElementById('insightClose')) document.getElementById('insightClose').onclick = function () {
    document.getElementById('insightLayer').classList.remove('show');
  };
  // 所有 DOM 绑定都包在 try 里：少一个元素也不能拖垮登录流程
  try {
    $('authBtn').onclick = doAuth;
    $('authPwd').addEventListener('keydown', function (e) { if (e.key === 'Enter') doAuth(); });
    $('authPwd2').addEventListener('keydown', function (e) { if (e.key === 'Enter') doAuth(); });
    if ($('reminderGo')) $('reminderGo').onclick = function () {
      $('reminder').classList.remove('show');
      doReview();
    };
    if ($('reminderClose')) $('reminderClose').onclick = function () {
      $('reminder').classList.remove('show');
      if (state.boot && state.boot.today) sessionStorage.setItem('memoir.remind.dismiss', state.boot.today);
    };
  } catch (e) { console.error('boot bind error', e); }

  checkAuth().then(function (ok) {
    if (ok) {
      startApp();
      setTimeout(checkReminder, 1500);
    }
  }).catch(function (e) {
    console.error('auth error', e);
    startApp();
  });
}
document.addEventListener('DOMContentLoaded', boot);
