/* テロップ一括調整 — パネル側（CEP の HTML/JS） */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var statusEl = $('status');
  var logEl = $('log');

  // CSInterface.js を同梱しなくても動くよう、CEP の内部 API を直接使う
  function evalHost(script) {
    return new Promise(function (resolve) {
      if (!window.__adobe_cep__) {
        resolve({ ok: false, error: 'Premiere Pro の中で開いてください（ブラウザでは動きません）' });
        return;
      }
      window.__adobe_cep__.evalScript(script, function (res) {
        try {
          resolve(JSON.parse(res));
        } catch (e) {
          resolve({ ok: false, error: 'ExtendScript エラー: ' + res });
        }
      });
    });
  }

  function call(fn, arg) {
    return evalHost('telopBatch.' + fn + '(' + (arg === undefined ? '' : JSON.stringify(arg)) + ')');
  }

  function setStatus(msg, isError) {
    statusEl.textContent = msg;
    statusEl.className = isError ? 'error' : 'muted';
  }

  function num(id) {
    var v = parseFloat($(id).value);
    return isNaN(v) ? 0 : v;
  }

  function target() { return $('target').value; }

  function axis() {
    var r = document.querySelector('input[name=axis]:checked');
    return r ? r.value : 'xy';
  }

  // ---------------------------------------------------------------

  function refresh() {
    return call('info', target()).then(function (r) {
      if (!r.ok) { setStatus(r.error, true); $('ref').textContent = ''; return; }
      setStatus(r.count + ' 個のクリップを選択中（' + r.sequence + ' / ' + r.frame[0] + '×' + r.frame[1] + '）');
      var ref = r.ref;
      if (!ref) { $('ref').textContent = ''; return; }
      if (!ref.component) {
        $('ref').textContent = '先頭: ' + ref.name + '（対象エフェクトなし）';
        return;
      }
      var parts = ['先頭: ' + ref.name + ' [' + ref.component + ']'];
      if (ref.position) parts.push('位置 ' + ref.position[0] + ', ' + ref.position[1]);
      if (ref.scale !== null) parts.push('スケール ' + ref.scale + '%');
      $('ref').textContent = parts.join(' / ');
    });
  }

  function run(opts, label) {
    opts.target = target();
    setStatus(label + ' を実行中…');
    return call('apply', opts).then(function (r) {
      if (!r.ok) { setStatus(r.error, true); return; }
      var msg = label + ': ' + r.done + ' / ' + r.total + ' 個に適用';
      if (r.skipped.length) msg += '（対象なし ' + r.skipped.length + ' 個）';
      setStatus(msg, r.errors.length > 0);
      logEl.textContent = r.errors.length ? r.errors.join('\n') : '';
      return refresh().then(function () {
        // refresh で status が上書きされるので結果を戻す
        setStatus(msg, r.errors.length > 0);
      });
    });
  }

  // ---------------------------------------------------------------

  $('refresh').addEventListener('click', refresh);
  $('target').addEventListener('change', refresh);

  var scaleLabels = { set: 'スケール指定', mul: 'スケール倍率', add: 'スケール加算', ref: 'スケールを揃える' };
  Array.prototype.forEach.call(document.querySelectorAll('[data-scale]'), function (b) {
    b.addEventListener('click', function () {
      var mode = b.getAttribute('data-scale');
      run({ op: 'scale', mode: mode, value: num('scaleValue') }, scaleLabels[mode]);
    });
  });

  Array.prototype.forEach.call(document.querySelectorAll('[data-align]'), function (b) {
    b.addEventListener('click', function () {
      run({ op: 'position', mode: 'frame', align: b.getAttribute('data-align'), margin: num('margin') },
        '整列(' + b.textContent + ')');
    });
  });

  Array.prototype.forEach.call(document.querySelectorAll('[data-refpos]'), function (b) {
    b.addEventListener('click', function () {
      run({ op: 'position', mode: 'ref', axis: b.getAttribute('data-refpos') }, b.textContent);
    });
  });

  Array.prototype.forEach.call(document.querySelectorAll('[data-pos]'), function (b) {
    b.addEventListener('click', function () {
      run({ op: 'position', mode: b.getAttribute('data-pos'), axis: axis(), x: num('posX'), y: num('posY') },
        b.textContent);
    });
  });

  $('match').addEventListener('click', function () {
    var fields = Array.prototype.map.call(
      document.querySelectorAll('input[name=match]:checked'), function (c) { return c.value; });
    if (!fields.length) { setStatus('コピーする項目を選んでください', true); return; }
    run({ op: 'match', fields: fields }, '先頭クリップからコピー');
  });

  $('inspect').addEventListener('click', function () {
    call('inspect').then(function (r) {
      if (!r.ok) { setStatus(r.error, true); return; }
      var lines = ['クリップ: ' + r.clip];
      r.components.forEach(function (c) {
        lines.push('■ ' + c.name + '  (' + c.matchName + ')');
        c.params.forEach(function (p) {
          lines.push('   ' + p.i + ': ' + p.name + ' = ' + JSON.stringify(p.value));
        });
      });
      logEl.textContent = lines.join('\n');
    });
  });

  refresh();
})();
