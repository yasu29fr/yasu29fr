/*
 * テロップ一括調整 — ExtendScript 側（Premiere Pro の中で動く部分）
 *
 * パネル(index.html)から evalScript で呼ばれ、結果を JSON 文字列で返す。
 * ExtendScript は ES3 相当なので、const / let / アロー関数 / JSON は使わない。
 */

var telopBatch = (function () {

    // ------------------------------------------------------------------
    // 小さなユーティリティ
    // ------------------------------------------------------------------

    function toJSON(v) {
        if (v === null || v === undefined) return "null";
        var t = typeof v;
        if (t === "number") return isFinite(v) ? String(v) : "null";
        if (t === "boolean") return v ? "true" : "false";
        if (t === "string") {
            return '"' + v.replace(/\\/g, "\\\\").replace(/"/g, '\\"')
                .replace(/\n/g, "\\n").replace(/\r/g, "\\r").replace(/\t/g, "\\t") + '"';
        }
        if (v instanceof Array) {
            var a = [];
            for (var i = 0; i < v.length; i++) a.push(toJSON(v[i]));
            return "[" + a.join(",") + "]";
        }
        var parts = [];
        for (var k in v) {
            if (v.hasOwnProperty(k)) parts.push(toJSON(k) + ":" + toJSON(v[k]));
        }
        return "{" + parts.join(",") + "}";
    }

    function ok(data) { data = data || {}; data.ok = true; return toJSON(data); }
    function fail(msg) { return toJSON({ ok: false, error: String(msg) }); }

    function trim(s) { return String(s).replace(/^\s+|\s+$/g, ""); }

    function round(n, d) { var p = Math.pow(10, d || 0); return Math.round(n * p) / p; }

    // 日本語 UI / 英語 UI どちらでも見つかるように表示名を複数持つ
    var NAMES = {
        position: ["Position", "位置"],
        scale: ["Scale", "スケール", "スケール（高さ）", "スケール (高さ)", "Scale Height"],
        scaleWidth: ["Scale Width", "スケール（幅）", "スケール (幅)", "幅のスケール"],
        uniform: ["Uniform Scale", "縦横比を固定"],
        rotation: ["Rotation", "回転"],
        anchor: ["Anchor Point", "アンカーポイント"]
    };

    // モーションエフェクトのパラメータ並び順（名前で見つからない時の保険）
    var MOTION_INDEX = { position: 0, scale: 1, scaleWidth: 2, uniform: 3, rotation: 4, anchor: 5 };

    // ------------------------------------------------------------------
    // シーケンス / 選択クリップ
    // ------------------------------------------------------------------

    function getSeq() {
        if (!app.project) throw "プロジェクトが開かれていません";
        var seq = app.project.activeSequence;
        if (!seq) throw "アクティブなシーケンスがありません";
        return seq;
    }

    function frameSize(seq) {
        return { w: Number(seq.frameSizeHorizontal), h: Number(seq.frameSizeVertical) };
    }

    // 選択中のビデオクリップを「開始時間 → 上のトラック」順で返す
    function selectedVideoItems(seq) {
        var sel = seq.getSelection();
        var items = [];
        if (!sel) return items;
        for (var i = 0; i < sel.length; i++) {
            var it = sel[i];
            if (!it) continue;
            if (it.mediaType !== undefined && it.mediaType !== "Video") continue;
            if (!it.components) continue;
            items.push(it);
        }
        items.sort(function (a, b) {
            var d = a.start.seconds - b.start.seconds;
            if (Math.abs(d) > 0.0001) return d;
            return trackIndexOf(seq, b) - trackIndexOf(seq, a);
        });
        return items;
    }

    function trackIndexOf(seq, item) {
        try {
            var tracks = seq.videoTracks;
            for (var t = 0; t < tracks.numTracks; t++) {
                var clips = tracks[t].clips;
                for (var c = 0; c < clips.numItems; c++) {
                    if (clips[c].nodeId === item.nodeId) return t;
                }
            }
        } catch (e) { }
        return 0;
    }

    // ------------------------------------------------------------------
    // コンポーネント（エフェクト）とパラメータの取得
    // ------------------------------------------------------------------

    function isMotion(comp) {
        var m = String(comp.matchName || "");
        var d = trim(comp.displayName || "");
        return m === "AE.ADBE Motion" || d === "Motion" || d === "モーション";
    }

    // Premiere の文字ツール / エッセンシャルグラフィックスのテキストレイヤー
    function isTextLayer(comp) {
        var m = String(comp.matchName || "");
        var d = trim(comp.displayName || "");
        if (/Text/i.test(m)) return true;
        return /^(Text|テキスト)/.test(d);
    }

    function listComponents(item, target) {
        var comps = item.components;
        var motion = [], text = [];
        for (var i = 0; i < comps.numItems; i++) {
            var c = comps[i];
            if (isMotion(c)) motion.push(c);
            else if (isTextLayer(c)) text.push(c);
        }
        if (target === "motion") return motion;
        if (target === "text") return text;
        // auto: テキストレイヤーがあればそちら、無ければモーション
        return text.length ? text : motion;
    }

    function findParam(comp, key) {
        var props = comp.properties;
        var names = NAMES[key];
        for (var i = 0; i < props.numItems; i++) {
            var dn = trim(props[i].displayName || "");
            for (var n = 0; n < names.length; n++) {
                if (dn === names[n]) return props[i];
            }
        }
        if (isMotion(comp) && MOTION_INDEX[key] !== undefined && MOTION_INDEX[key] < props.numItems) {
            return props[MOTION_INDEX[key]];
        }
        return null;
    }

    // キーフレームがあれば最初のキーの値、無ければ現在値
    function readValue(param) {
        try {
            if (param.isTimeVarying()) {
                var keys = param.getKeys();
                if (keys && keys.length) return param.getValueAtKey(keys[0]);
            }
        } catch (e) { }
        return param.getValue();
    }

    // 値を変換して書き戻す。キーフレームがある場合は全キーに同じ変換をかける
    function transformParam(param, fn) {
        if (param.isTimeVarying()) {
            var keys = param.getKeys();
            for (var k = 0; k < keys.length; k++) {
                param.setValueAtKey(keys[k], fn(param.getValueAtKey(keys[k])), true);
            }
            return keys.length;
        }
        param.setValue(fn(param.getValue()), true);
        return 1;
    }

    // 位置が 0〜1 の正規化座標か、ピクセル座標かを判定
    // （モーションは常に正規化。テキストレイヤーはバージョンによって異なる可能性があるため推定）
    function isNormalized(comp, v) {
        if (isMotion(comp)) return true;
        return Math.abs(v[0]) <= 4 && Math.abs(v[1]) <= 4;
    }

    function toPx(comp, v, fs) {
        return isNormalized(comp, v) ? [v[0] * fs.w, v[1] * fs.h] : [v[0], v[1]];
    }

    function fromPx(comp, orig, px, fs) {
        return isNormalized(comp, orig) ? [px[0] / fs.w, px[1] / fs.h] : [px[0], px[1]];
    }

    // ------------------------------------------------------------------
    // 各操作
    // ------------------------------------------------------------------

    function scaleFn(opts, refScale) {
        var v = Number(opts.value);
        if (opts.mode === "set") return function () { return v; };
        if (opts.mode === "mul") return function (cur) { return cur * v / 100; };
        if (opts.mode === "add") return function (cur) { return cur + v; };
        if (opts.mode === "ref") return function () { return refScale; };
        throw "不明なスケールモード: " + opts.mode;
    }

    function applyScale(comp, opts, ref) {
        var p = findParam(comp, "scale");
        if (!p) throw "スケールが見つかりません (" + comp.displayName + ")";
        var n = transformParam(p, scaleFn(opts, ref && ref.scale));

        // 縦横比の固定が OFF のときは幅スケールにも同じ操作
        var u = findParam(comp, "uniform");
        var w = findParam(comp, "scaleWidth");
        if (u && w) {
            var uniform = true;
            try { uniform = !!u.getValue(); } catch (e) { }
            if (!uniform) transformParam(w, scaleFn(opts, ref && ref.scaleWidth));
        }
        return n;
    }

    function applyPosition(comp, opts, ref, fs) {
        var p = findParam(comp, "position");
        if (!p) throw "位置が見つかりません (" + comp.displayName + ")";
        var useX = opts.axis !== "y";
        var useY = opts.axis !== "x";
        var margin = Number(opts.margin || 0);

        return transformParam(p, function (cur) {
            var px = toPx(comp, cur, fs);
            var nx = px[0], ny = px[1];

            if (opts.mode === "set") {
                if (useX) nx = Number(opts.x);
                if (useY) ny = Number(opts.y);
            } else if (opts.mode === "offset") {
                if (useX) nx += Number(opts.x);
                if (useY) ny += Number(opts.y);
            } else if (opts.mode === "ref") {
                if (!ref || !ref.positionPx) throw "基準クリップの位置が取れません";
                if (useX) nx = ref.positionPx[0];
                if (useY) ny = ref.positionPx[1];
            } else if (opts.mode === "frame") {
                switch (opts.align) {
                    case "left": nx = margin; break;
                    case "hcenter": nx = fs.w / 2; break;
                    case "right": nx = fs.w - margin; break;
                    case "top": ny = margin; break;
                    case "vcenter": ny = fs.h / 2; break;
                    case "bottom": ny = fs.h - margin; break;
                    default: throw "不明な整列: " + opts.align;
                }
            } else {
                throw "不明な位置モード: " + opts.mode;
            }
            return fromPx(comp, cur, [nx, ny], fs);
        });
    }

    function applyMatch(comp, opts, refComp) {
        var keys = opts.fields || [];
        var n = 0;
        for (var i = 0; i < keys.length; i++) {
            var src = findParam(refComp, keys[i]);
            var dst = findParam(comp, keys[i]);
            if (!src || !dst) continue;
            var v = readValue(src);
            n += transformParam(dst, function () { return v; });
        }
        return n;
    }

    // 基準（先頭）クリップの値を読む
    function readRef(item, target, fs) {
        var comps = listComponents(item, target);
        if (!comps.length) return null;
        var c = comps[0];
        var r = { comp: c, name: item.name, component: c.displayName };
        var p = findParam(c, "position");
        if (p) {
            var v = readValue(p);
            r.positionPx = toPx(c, v, fs);
        }
        var s = findParam(c, "scale");
        if (s) r.scale = Number(readValue(s));
        var w = findParam(c, "scaleWidth");
        if (w) r.scaleWidth = Number(readValue(w));
        return r;
    }

    // ------------------------------------------------------------------
    // 公開 API
    // ------------------------------------------------------------------

    function info(target) {
        try {
            var seq = getSeq();
            var fs = frameSize(seq);
            var items = selectedVideoItems(seq);
            var out = { count: items.length, frame: [fs.w, fs.h], sequence: seq.name };
            if (items.length) {
                var ref = readRef(items[0], target, fs);
                if (ref) {
                    out.ref = {
                        name: ref.name,
                        component: ref.component,
                        position: ref.positionPx ? [round(ref.positionPx[0], 1), round(ref.positionPx[1], 1)] : null,
                        scale: ref.scale !== undefined ? round(ref.scale, 2) : null
                    };
                } else {
                    out.ref = { name: items[0].name, component: null };
                }
            }
            return ok(out);
        } catch (e) {
            return fail(e);
        }
    }

    function apply(opts) {
        try {
            var seq = getSeq();
            var fs = frameSize(seq);
            var items = selectedVideoItems(seq);
            if (!items.length) throw "タイムラインでテロップ（クリップ）を選択してください";

            var ref = readRef(items[0], opts.target, fs);
            var needsRef = opts.mode === "ref" || opts.op === "match";
            if (needsRef && !ref) throw "基準クリップ(" + items[0].name + ")に対象のエフェクトがありません";

            var done = 0, skipped = [], errors = [];
            for (var i = 0; i < items.length; i++) {
                var item = items[i];
                if (needsRef && i === 0) continue; // 基準自身はそのまま
                var comps = listComponents(item, opts.target);
                if (!comps.length) { skipped.push(item.name); continue; }
                for (var c = 0; c < comps.length; c++) {
                    try {
                        if (opts.op === "scale") applyScale(comps[c], opts, ref);
                        else if (opts.op === "position") applyPosition(comps[c], opts, ref, fs);
                        else if (opts.op === "match") applyMatch(comps[c], opts, ref.comp);
                        else throw "不明な操作: " + opts.op;
                    } catch (e2) {
                        errors.push(item.name + ": " + e2);
                    }
                }
                done++;
            }
            return ok({ done: done, total: items.length, skipped: skipped, errors: errors });
        } catch (e) {
            return fail(e);
        }
    }

    // 先頭の選択クリップのエフェクト構成を書き出す（うまく効かない時の調査用）
    function inspect() {
        try {
            var seq = getSeq();
            var items = selectedVideoItems(seq);
            if (!items.length) throw "クリップを 1 つ選択してください";
            var item = items[0];
            var comps = [];
            for (var i = 0; i < item.components.numItems; i++) {
                var c = item.components[i];
                var params = [];
                for (var j = 0; j < c.properties.numItems; j++) {
                    var p = c.properties[j];
                    var val;
                    try { val = p.getValue(); } catch (e) { val = "(取得不可)"; }
                    if (typeof val === "string" && val.length > 80) val = val.substr(0, 80) + "…";
                    params.push({ i: j, name: p.displayName, value: val });
                }
                comps.push({ name: c.displayName, matchName: c.matchName, params: params });
            }
            return ok({ clip: item.name, components: comps });
        } catch (e) {
            return fail(e);
        }
    }

    return { info: info, apply: apply, inspect: inspect };
})();
