/* 轻量语法高亮：不引第三方库，按字符扫描一遍。
   支持 // 与 # 注释、单双引号字符串、数字、常见关键字。 */
var KEYWORDS = /^(def|class|function|return|if|else|elif|for|while|import|from|const|let|var|new|async|await|try|catch|finally|throw|public|private|static|void|int|float|string|bool|true|false|null|None|True|False|print|self|this|SELECT|FROM|WHERE|CREATE|TABLE|INSERT|UPDATE|DELETE|package|fn|use|struct|impl)$/;

function highlightCode(code) {
  var out = '';
  var i = 0;
  var n = code.length;
  while (i < n) {
    var ch = code.charAt(i);
    if (ch === '#' || (ch === '/' && code.charAt(i + 1) === '/')) {
      var nl = code.indexOf('\n', i);
      if (nl < 0) { nl = n; }
      out += '<span style="color:#6b7a90;font-style:italic">' + esc(code.slice(i, nl)) + '</span>';
      i = nl;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === '`') {
      var q = ch, k = i + 1;
      while (k < n && code.charAt(k) !== q) {
        if (code.charAt(k) === '\\') { k++; }
        k++;
      }
      k = Math.min(k + 1, n);
      out += '<span style="color:#c3e88d">' + esc(code.slice(i, k)) + '</span>';
      i = k;
      continue;
    }
    if (ch >= '0' && ch <= '9') {
      var m = /^[0-9][0-9._a-fA-FxX]*/.exec(code.slice(i));
      if (m) {
        out += '<span style="color:#f78c6c">' + esc(m[0]) + '</span>';
        i += m[0].length;
        continue;
      }
    }
    if (/[a-zA-Z_$]/.test(ch)) {
      var m2 = /^[a-zA-Z_$][\w$]*/.exec(code.slice(i));
      var word = m2 ? m2[0] : ch;
      out += KEYWORDS.test(word) ? ('<span style="color:#c792ea">' + esc(word) + '</span>') : esc(word);
      i += word.length;
      continue;
    }
    out += esc(ch);
    i++;
  }
  return out;
}
