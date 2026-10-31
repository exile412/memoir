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
  var list = $('list');
  list.innerHTML = '';
  $('listCount').textContent = state.entries.length + ' 条';
  if (!state.entries.length) {
    list.innerHTML = '<div class="empty" style="padding:30px 10px">还没有记录</div>';
    return;
  }
  state.entries.forEach(function (e) {
    var time = (e.ts || '').slice(11, 16);
    var title = e.title || (e.text || '').slice(0, 18);
    var div = document.createElement('div');
    div.className = 'item' + (state.currentId === e.id ? ' active' : '');
    div.innerHTML = '<b>' + esc(title) + '</b><small>' + time + ' · ' +
      esc(kindLabel(e.kind)) + '</small><span class="del" title="删除">✕</span>';
    div.onclick = function (ev) {
      if (ev.target.classList.contains('del')) {
        if (confirm('删除这条记录？')) {
          api('entries/' + e.id, { method: 'DELETE' }).then(loadEntries);
        }
        return;
      }
      state.currentId = e.id;
      clearChat();
      push(bubble('ai', '<div class="txt">这是你记下的：</div>'));
      push(bubble('me', entryInner(e)));
      renderList();
    };
    list.appendChild(div);
  });
}

function loadEntries() {
  var q = $('search').value.trim();
  var url = q ? ('entries?q=' + encodeURIComponent(q)) : 'entries';
  return api(url).then(function (res) {
    state.entries = res.entries || [];
    renderList();
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
    loadEntries();
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
      if (act === 'review') doReview();
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
  $('exportBtn').onclick = function () { window.open('/api/export', '_blank'); };
  $('refreshBtn').onclick = function () { loadEntries(); loadSettings(); };
  $('menuBtn').onclick = function () { toggleSidebar(true); };
  } catch (e) { console.error('startApp bind error', e); }
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

function boot() {
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
