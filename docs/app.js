"use strict";

/**
 * Threads 投稿予約 — GitHub 上の投稿キュー (posts/queue.jsonl) を編集する画面。
 *
 * 投稿そのものは GitHub Actions が行う。この画面がするのは、キューの読み書きと、
 * 添付画像をリポジトリに置いて公開 URL を作ることだけ。
 */
(() => {
  const QUEUE_PATH = "posts/queue.jsonl";
  const STATE_PATH = "state/posted.json";
  const IMAGE_DIR = "assets/images";
  const MAX_TEXT = 500;
  const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
  const STORE_KEY = "threads-bot.settings";
  const ANTHROPIC_URL = "https://api.anthropic.com/v1/messages";
  const ANTHROPIC_VERSION = "2023-06-01";
  const PROOFREAD_MODEL = "claude-opus-5";
  const JST = "Asia/Tokyo";

  function el(id) {
    const node = document.getElementById(id);
    // HTML と JS のどちらかだけが古いキャッシュだと、ここで初めて食い違いが出る。
    // 黙って例外にすると初期化が丸ごと止まるので、原因が分かる形で投げる。
    if (!node) throw new Error(`画面の要素 #${id} が見つかりません（表示が古い可能性があります）`);
    return node;
  }

  /** 画面の状態。queue.sha は書き込み時の衝突検出に使う。 */
  const app = {
    cfg: { repo: "", branch: "", token: "", anthropicKey: "" },
    queue: { header: [], items: [], sha: null },
    posted: {},
    editingId: null,
    pendingImage: null, // { file, dataUrl }
  };

  // ---------------------------------------------------------------- 設定

  function guessRepo() {
    // GitHub Pages なら https://<owner>.github.io/<repo>/ で配信される
    const host = location.hostname;
    const owner = host.endsWith(".github.io") ? host.split(".")[0] : "";
    const segment = location.pathname.split("/").filter(Boolean)[0] || "";
    if (owner && segment) return `${owner}/${segment}`;
    if (owner) return `${owner}/${owner}.github.io`;
    return "";
  }

  function loadSettings() {
    let stored = {};
    try {
      stored = JSON.parse(localStorage.getItem(STORE_KEY) || "{}");
    } catch (_) {
      stored = {};
    }
    app.cfg = {
      repo: stored.repo || guessRepo(),
      branch: stored.branch || "",
      token: stored.token || "",
      anthropicKey: stored.anthropicKey || "",
    };
  }

  function saveSettings() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(app.cfg));
    } catch (_) {
      banner("このブラウザでは設定を保存できませんでした（プライベートモードなど）。", "error");
    }
  }

  // ------------------------------------------------------------ GitHub API

  async function gh(path, options = {}) {
    const response = await fetch(`https://api.github.com${path}`, {
      ...options,
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${app.cfg.token}`,
        "X-GitHub-Api-Version": "2022-11-28",
        ...(options.headers || {}),
      },
    });
    if (response.status === 204) return null;
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(body.message || `GitHub API エラー (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return body;
  }

  const encodePath = (path) => path.split("/").map(encodeURIComponent).join("/");

  async function getFile(path) {
    const query = app.cfg.branch ? `?ref=${encodeURIComponent(app.cfg.branch)}` : "";
    try {
      const body = await gh(`/repos/${app.cfg.repo}/contents/${encodePath(path)}${query}`);
      return { text: decodeBase64(body.content || ""), sha: body.sha };
    } catch (error) {
      if (error.status === 404) return { text: null, sha: null };
      throw error;
    }
  }

  async function putFile(path, base64, sha, message) {
    return gh(`/repos/${app.cfg.repo}/contents/${encodePath(path)}`, {
      method: "PUT",
      body: JSON.stringify({
        message,
        content: base64,
        branch: app.cfg.branch || undefined,
        sha: sha || undefined,
      }),
    });
  }

  function encodeBase64(text) {
    const bytes = new TextEncoder().encode(text);
    let binary = "";
    bytes.forEach((byte) => {
      binary += String.fromCharCode(byte);
    });
    return btoa(binary);
  }

  function decodeBase64(base64) {
    const binary = atob(base64.replace(/\s/g, ""));
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  }

  // ---------------------------------------------------------------- 校正

  const PROOFREAD_SYSTEM = `あなたは日本語の SNS 投稿（Threads）の校正者です。
投稿者本人の言葉づかいを尊重してください。書き手が別人になったように感じる直しはしません。

見るのは次の 3 点です。
1. 誤字脱字・変換ミス・表記ゆれ
2. 読みやすさ・簡潔さ（回りくどい言い回し、削っても意味が通る部分）
3. 絵文字（内容に合うものを控えめに。多くても 2 つまで。合わないなら足さない）

守ること:
- 事実を足さない。書かれていないことを補わない
- 校正後の本文は 500 文字以内
- 直すところがなければ、本文はそのままにして指摘を空にする

出力は次の形の JSON だけを返してください。前後に説明やコードフェンスを付けないこと。
{"revised": "校正後の本文", "notes": [{"kind": "誤字|表記|簡潔さ|絵文字", "detail": "何をどう直したか一文で"}]}`;

  /** レスポンスから JSON を取り出す。コードフェンスや前後の文章が付いても拾えるようにする。 */
  function extractJson(text) {
    const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
    const body = fenced ? fenced[1] : text;
    const start = body.indexOf("{");
    const end = body.lastIndexOf("}");
    if (start < 0 || end <= start) throw new Error("校正結果を読み取れませんでした。");
    return JSON.parse(body.slice(start, end + 1));
  }

  async function requestProofread(text) {
    let response;
    try {
      response = await fetch(ANTHROPIC_URL, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-api-key": app.cfg.anthropicKey,
          "anthropic-version": ANTHROPIC_VERSION,
          // ブラウザから直接叩くための許可。これがないと CORS で弾かれる。
          "anthropic-dangerous-direct-browser-access": "true",
        },
        body: JSON.stringify({
          model: PROOFREAD_MODEL,
          max_tokens: 4000,
          output_config: { effort: "low" },
          system: PROOFREAD_SYSTEM,
          messages: [{ role: "user", content: text }],
        }),
      });
    } catch (_) {
      throw new Error("Claude に接続できませんでした。通信環境を確認してください。");
    }

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = (data.error && data.error.message) || `HTTP ${response.status}`;
      if (response.status === 401) throw new Error("Anthropic の API キーが無効です。");
      if (response.status === 429) throw new Error("回数の上限に達しました。少し待ってからお試しください。");
      throw new Error(`校正に失敗しました: ${message}`);
    }
    if (data.stop_reason === "refusal") {
      throw new Error("この内容の校正は見送られました。");
    }

    // thinking ブロックが混ざるので text ブロックだけを拾う
    const body = (data.content || [])
      .filter((block) => block.type === "text")
      .map((block) => block.text)
      .join("");
    const parsed = extractJson(body);
    if (typeof parsed.revised !== "string" || !parsed.revised.trim()) {
      throw new Error("校正結果が空でした。");
    }
    return { revised: parsed.revised, notes: Array.isArray(parsed.notes) ? parsed.notes : [] };
  }

  async function onProofread() {
    const text = el("f-text").value.trim();
    if (!text) {
      banner("先に本文を書いてください。", "error");
      return;
    }
    const button = el("proofread");
    const status = el("proofread-status");
    button.disabled = true;
    status.textContent = "Claude が読んでいます…";
    el("proofread-result").hidden = true;
    try {
      const result = await requestProofread(text);
      renderProofread(result, text);
      status.textContent = "";
    } catch (error) {
      status.textContent = "";
      banner(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  function renderProofread(result, original) {
    el("proofread-text").textContent = result.revised;
    const list = el("proofread-notes");
    list.innerHTML = "";
    if (result.revised === original && result.notes.length === 0) {
      const item = document.createElement("li");
      item.textContent = "直すところは見つかりませんでした。";
      list.append(item);
    }
    for (const note of result.notes) {
      const item = document.createElement("li");
      const kind = document.createElement("span");
      kind.className = "kind";
      kind.textContent = `${note.kind || "指摘"}: `;
      item.append(kind, document.createTextNode(note.detail || ""));
      list.append(item);
    }
    el("proofread-result").hidden = false;
  }

  function applyProofread() {
    el("f-text").value = el("proofread-text").textContent;
    updateCounter();
    el("proofread-result").hidden = true;
  }

  /** キーが登録されているときだけ校正ボタンを出す。 */
  function updateProofreadVisibility() {
    el("proofread-bar").hidden = !app.cfg.anthropicKey;
    if (!app.cfg.anthropicKey) el("proofread-result").hidden = true;
  }

  // -------------------------------------------------------------- キュー

  function parseQueue(text) {
    const header = [];
    const items = [];
    if (!text) return { header, items };
    let inHeader = true;
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      if (trimmed.startsWith("#")) {
        if (inHeader) header.push(line);
        continue;
      }
      inHeader = false;
      try {
        items.push(JSON.parse(trimmed));
      } catch (_) {
        // 壊れた行は落とさずそのまま残す（意図しない削除を避ける）
        items.push({ __raw: line });
      }
    }
    return { header, items };
  }

  function serializeQueue() {
    const lines = [...app.queue.header];
    for (const item of app.queue.items) {
      lines.push(item.__raw !== undefined ? item.__raw : JSON.stringify(item));
    }
    return lines.join("\n") + "\n";
  }

  async function reload() {
    const [queue, posted] = await Promise.all([getFile(QUEUE_PATH), getFile(STATE_PATH)]);
    const parsed = parseQueue(queue.text || "");
    app.queue = { header: parsed.header, items: parsed.items, sha: queue.sha };
    try {
      app.posted = JSON.parse(posted.text || "{}").posted || {};
    } catch (_) {
      app.posted = {};
    }
    render();
  }

  async function commitQueue(message) {
    const response = await putFile(QUEUE_PATH, encodeBase64(serializeQueue()), app.queue.sha, message);
    app.queue.sha = response.content.sha;
  }

  // ------------------------------------------------------------ 日時 (JST)

  const jstFormatter = new Intl.DateTimeFormat("ja-JP", {
    timeZone: JST,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });

  /** Date → "YYYY-MM-DDTHH:MM"（日本時間の壁掛け時計の値） */
  function toJstInputValue(date) {
    const parts = {};
    for (const part of jstFormatter.formatToParts(date)) parts[part.type] = part.value;
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
  }

  /** "YYYY-MM-DDTHH:MM"（日本時間） → ISO 8601 のオフセット付き文字列 */
  const fromJstInputValue = (value) => `${value}:00+09:00`;

  /** 日時の選択は 10 分刻み。端数は次の 10 分に切り上げる。 */
  const STEP_MINUTES = 10;

  function roundUpToStep(date) {
    const step = STEP_MINUTES * 60000;
    return new Date(Math.ceil(date.getTime() / step) * step);
  }

  /** 初期値は「現在時刻の 1 時間後」。 */
  const defaultScheduledAt = () => roundUpToStep(new Date(Date.now() + 60 * 60000));

  /**
   * 時刻のプルダウンを 10 分刻みで組み直す。
   *
   * datetime-local の step 属性はスマホの日時ピッカーで無視されるため、
   * 時刻だけ独立した select にして刻みを確実にしている。手書きの JSONL に
   * 10 分刻みでない予約があった場合は、その値だけ選択肢に足して元の時刻を保つ。
   */
  function buildTimeOptions(selected) {
    const values = [];
    for (let minutes = 0; minutes < 24 * 60; minutes += STEP_MINUTES) {
      values.push(
        `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`,
      );
    }
    if (selected && !values.includes(selected)) {
      values.push(selected);
      values.sort();
    }
    const select = el("f-time");
    select.innerHTML = "";
    for (const value of values) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.append(option);
    }
    if (selected) select.value = selected;
  }

  /** 入力欄（日付 + 時刻）に日時を入れる。 */
  function setScheduledInput(date) {
    const [day, time] = toJstInputValue(date).split("T");
    el("f-date").value = day;
    buildTimeOptions(time);
  }

  /** 入力欄の値 → ISO 8601。どちらか空なら null。 */
  function readScheduledInput() {
    const day = el("f-date").value;
    const time = el("f-time").value;
    if (!day || !time) return null;
    return fromJstInputValue(`${day}T${time}`);
  }

  function formatJst(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    return jstFormatter.format(date).replace(/\//g, "/") + "（日本時間）";
  }

  // ---------------------------------------------------------------- 描画

  function banner(message, kind) {
    const node = el("banner");
    node.textContent = message;
    node.className = `banner${kind ? ` banner-${kind}` : ""}`;
    node.hidden = !message;
    if (kind === "ok") setTimeout(() => { node.hidden = true; }, 4000);
  }

  function sortedPending() {
    const scheduled = app.queue.items
      .filter((item) => item.scheduled_at && !isPosted(item))
      .sort((a, b) => new Date(a.scheduled_at) - new Date(b.scheduled_at));
    // 日時のない項目は投稿されない。埋もれないよう末尾に出して注意を促す。
    const stranded = app.queue.items.filter((item) => !item.scheduled_at && !isPosted(item));
    return [...scheduled, ...stranded];
  }

  const isPosted = (item) => Boolean(item.id && app.posted[item.id]);

  function render() {
    renderQueue();
    renderHistory();
  }

  function renderQueue() {
    const list = el("queue-list");
    const pending = sortedPending();
    el("queue-count").textContent = String(pending.length);
    list.innerHTML = "";
    el("queue-empty").hidden = pending.length > 0;

    const now = Date.now();
    for (const item of pending) {
      const card = document.createElement("div");
      card.className = "card";

      const when = document.createElement("div");
      if (item.scheduled_at) {
        const due = new Date(item.scheduled_at).getTime() <= now;
        when.className = `card-when${due ? " due" : ""}`;
        when.textContent = due
          ? `${formatJst(item.scheduled_at)} — まもなく投稿されます`
          : formatJst(item.scheduled_at);
      } else {
        when.className = "card-when due";
        when.textContent = "日時が未設定 — このままでは投稿されません";
      }
      card.append(when);

      const text = document.createElement("div");
      text.className = "card-text";
      text.textContent = item.__raw !== undefined ? item.__raw : item.text || "";
      card.append(text);

      if (item.image_url) {
        const image = document.createElement("img");
        image.className = "attached";
        image.src = item.image_url;
        image.alt = item.alt_text || "添付画像";
        card.append(image);
      }

      const notes = [];
      if (item.thread && item.thread.length) notes.push(`連投 ${item.thread.length + 1} 件`);
      if (item.link_attachment) notes.push("リンクあり");
      if (notes.length) {
        const meta = document.createElement("div");
        meta.className = "card-meta";
        meta.textContent = notes.join(" ・ ");
        card.append(meta);
      }

      const actions = document.createElement("div");
      actions.className = "card-actions";
      actions.append(
        button("編集", () => startEdit(item)),
        button("複製", () => duplicate(item)),
        button("削除", () => remove(item), "btn-danger"),
      );
      card.append(actions);
      list.append(card);
    }
  }

  function renderHistory() {
    const list = el("history-list");
    const entries = Object.entries(app.posted).sort(
      (a, b) => new Date(b[1].posted_at) - new Date(a[1].posted_at),
    );
    list.innerHTML = "";
    el("history-empty").hidden = entries.length > 0;

    const byId = new Map(app.queue.items.filter((i) => i.id).map((i) => [i.id, i]));
    for (const [id, record] of entries) {
      const card = document.createElement("div");
      card.className = "card";

      const when = document.createElement("div");
      when.className = "card-when";
      when.textContent = formatJst(record.posted_at);
      card.append(when);

      const text = document.createElement("div");
      text.className = "card-text";
      text.textContent = (byId.get(id) || {}).text || "(本文はキューから削除されています)";
      card.append(text);

      if (record.permalink) {
        const meta = document.createElement("div");
        meta.className = "card-meta";
        const link = document.createElement("a");
        link.href = record.permalink;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = "Threads で開く";
        meta.append(link);
        card.append(meta);
      }
      list.append(card);
    }
  }

  function button(label, onClick, extraClass = "") {
    const node = document.createElement("button");
    node.type = "button";
    node.className = `btn btn-ghost ${extraClass}`.trim();
    node.textContent = label;
    node.addEventListener("click", onClick);
    return node;
  }

  // ------------------------------------------------------------ 編集操作

  function newId() {
    const stamp = toJstInputValue(new Date()).replace(/[-T:]/g, "");
    return `p-${stamp}-${Math.random().toString(36).slice(2, 6)}`;
  }

  function threadInputs() {
    return Array.from(document.querySelectorAll("#thread-parts textarea"));
  }

  function addThreadPart(value = "") {
    const wrapper = document.createElement("div");
    wrapper.className = "thread-part";
    const textarea = document.createElement("textarea");
    textarea.rows = 2;
    textarea.maxLength = MAX_TEXT;
    textarea.value = value;
    textarea.placeholder = "続きの投稿";
    wrapper.append(textarea, button("×", () => wrapper.remove()));
    el("thread-parts").append(wrapper);
  }

  function resetComposer() {
    app.editingId = null;
    app.pendingImage = null;
    el("composer").reset();
    el("thread-parts").innerHTML = "";
    el("image-preview").hidden = true;
    el("proofread-result").hidden = true;
    el("composer-title").textContent = "新しい投稿";
    el("submit").textContent = "キューに入れる";
    el("cancel-edit").hidden = true;
    el("count-text").textContent = "0";
    el("count-text").parentElement.classList.remove("over");
    setScheduledInput(defaultScheduledAt());
  }

  function startEdit(item) {
    resetComposer();
    app.editingId = item.id || null;
    el("f-text").value = item.text || "";
    el("f-link").value = item.link_attachment || "";
    el("f-alt").value = item.alt_text || "";
    el("f-reply-control").value = item.reply_control || "";
    for (const part of item.thread || []) addThreadPart(part);
    if (item.image_url) {
      app.pendingImage = { url: item.image_url };
      el("image-preview").hidden = false;
      el("image-thumb").src = item.image_url;
      el("image-name").textContent = item.image_url;
    }
    setScheduledInput(
      item.scheduled_at ? new Date(item.scheduled_at) : defaultScheduledAt(),
    );
    updateCounter();
    el("composer-title").textContent = "投稿を編集";
    el("submit").textContent = "保存する";
    el("cancel-edit").hidden = false;
    switchTab("compose");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function duplicate(item) {
    const copy = { ...item, id: newId() };
    delete copy.scheduled_at;
    app.queue.items.push(copy);
    await withBusy("複製しています…", async () => {
      await commitQueue("chore(queue): 投稿を複製");
      render();
      banner("複製しました。日時はまだ入っていません。", "ok");
    });
  }

  async function remove(item) {
    const head = (item.text || "").slice(0, 20);
    if (!confirm(`この投稿を削除しますか？\n\n${head}…`)) return;
    app.queue.items = app.queue.items.filter((candidate) => candidate !== item);
    await withBusy("削除しています…", async () => {
      await commitQueue("chore(queue): 投稿を削除");
      render();
      banner("削除しました。", "ok");
    });
  }

  async function uploadImage(file) {
    const buffer = await file.arrayBuffer();
    let binary = "";
    new Uint8Array(buffer).forEach((byte) => {
      binary += String.fromCharCode(byte);
    });
    const stamp = toJstInputValue(new Date()).replace(/[-T:]/g, "");
    const safeName = file.name.replace(/[^\w.-]/g, "_");
    const path = `${IMAGE_DIR}/${stamp}-${safeName}`;
    await putFile(path, btoa(binary), null, "chore(queue): 画像を追加");
    const branch = app.cfg.branch || "main";
    return `https://raw.githubusercontent.com/${app.cfg.repo}/refs/heads/${branch}/${encodePath(path)}`;
  }

  async function onSubmit(event) {
    event.preventDefault();
    if (!app.cfg.token) {
      banner("先に設定でトークンを登録してください。", "error");
      return;
    }
    const text = el("f-text").value.trim();
    if (!text) {
      banner("本文が空です。", "error");
      return;
    }
    if (text.length > MAX_TEXT) {
      banner(`本文が ${MAX_TEXT} 文字を超えています。`, "error");
      return;
    }

    const scheduledAt = readScheduledInput();
    if (!scheduledAt) {
      banner("投稿日時を選んでください。", "error");
      return;
    }

    await withBusy("保存しています…", async () => {
      let imageUrl = app.pendingImage && app.pendingImage.url;
      if (app.pendingImage && app.pendingImage.file) {
        imageUrl = await uploadImage(app.pendingImage.file);
      }

      const item = { id: app.editingId || newId(), text, scheduled_at: scheduledAt };
      const thread = threadInputs().map((input) => input.value.trim()).filter(Boolean);
      if (thread.length) item.thread = thread;
      if (imageUrl) item.image_url = imageUrl;
      const alt = el("f-alt").value.trim();
      if (alt && imageUrl) item.alt_text = alt;
      const link = el("f-link").value.trim();
      if (link && !imageUrl) item.link_attachment = link;
      const replyControl = el("f-reply-control").value;
      if (replyControl) item.reply_control = replyControl;

      const index = app.queue.items.findIndex((candidate) => candidate.id === item.id);
      if (index >= 0) app.queue.items[index] = item;
      else app.queue.items.push(item);

      await commitQueue(
        index >= 0 ? "chore(queue): 投稿を更新" : "chore(queue): 投稿を追加",
      );
      resetComposer();
      render();
      banner(`${formatJst(item.scheduled_at)} に投稿されます。`, "ok");
      switchTab("queue");
    });
  }

  /** 通信中はボタンを止め、衝突は読み直しを促す。 */
  async function withBusy(message, work) {
    const submit = el("submit");
    submit.disabled = true;
    banner(message);
    try {
      await work();
    } catch (error) {
      if (error.status === 409 || error.status === 422) {
        banner("別の場所でキューが更新されていました。読み直します。", "error");
        await reload().catch(() => {});
      } else {
        banner(error.message || "保存に失敗しました。", "error");
      }
    } finally {
      submit.disabled = false;
    }
  }

  // ---------------------------------------------------------------- 画面

  function switchTab(name) {
    for (const tab of document.querySelectorAll(".tab")) {
      tab.classList.toggle("is-active", tab.dataset.tab === name);
    }
    for (const panel of document.querySelectorAll(".tabpanel")) {
      panel.hidden = panel.id !== `tab-${name}`;
    }
  }

  function updateCounter() {
    const length = el("f-text").value.length;
    el("count-text").textContent = String(length);
    el("count-text").parentElement.classList.toggle("over", length > MAX_TEXT);
  }

  function applyQuick(kind) {
    const now = new Date();
    if (kind === "tomorrow9" || kind === "tomorrow19") {
      const tomorrow = new Date(now.getTime() + 24 * 3600 * 1000);
      el("f-date").value = toJstInputValue(tomorrow).slice(0, 10);
      buildTimeOptions(kind === "tomorrow9" ? "09:00" : "19:00");
      return;
    }
    setScheduledInput(roundUpToStep(new Date(now.getTime() + Number(kind) * 60000)));
  }

  function onImageChange(event) {
    const file = event.target.files[0];
    if (!file) {
      app.pendingImage = null;
      el("image-preview").hidden = true;
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      banner("画像が 8MB を超えています。小さくしてから添付してください。", "error");
      event.target.value = "";
      return;
    }
    app.pendingImage = { file };
    el("image-name").textContent = `${file.name}（${Math.round(file.size / 1024)} KB）`;
    el("image-thumb").src = URL.createObjectURL(file);
    el("image-preview").hidden = false;
  }

  function fillSettingsForm() {
    el("cfg-repo").value = app.cfg.repo;
    el("cfg-branch").value = app.cfg.branch;
    el("cfg-token").value = app.cfg.token;
    el("cfg-anthropic").value = app.cfg.anthropicKey;
    if (app.cfg.repo) {
      el("pat-link").href = "https://github.com/settings/personal-access-tokens/new";
    }
  }

  async function connect() {
    if (!app.cfg.repo || !app.cfg.token) {
      el("conn").textContent = "未接続";
      el("conn").className = "badge badge-off";
      el("settings").hidden = false;
      return;
    }
    try {
      const repo = await gh(`/repos/${app.cfg.repo}`);
      if (!app.cfg.branch) app.cfg.branch = repo.default_branch;
      const conn = el("conn");
      conn.textContent = `${app.cfg.repo.split("/").pop()} @ ${app.cfg.branch}`;
      conn.title = `${app.cfg.repo} @ ${app.cfg.branch}`;
      conn.className = "badge badge-on";
      el("settings").hidden = true;
      await reload();
      banner("", null);
    } catch (error) {
      el("conn").textContent = "接続できません";
      el("conn").className = "badge badge-off";
      el("settings").hidden = false;
      banner(
        error.status === 401 || error.status === 403
          ? "トークンが無効か、権限が足りません（Contents: Read and write が必要です）。"
          : error.message,
        "error",
      );
    }
  }

  function init() {
    loadSettings();
    fillSettingsForm();

    el("open-settings").addEventListener("click", () => {
      el("settings").hidden = !el("settings").hidden;
    });
    el("save-settings").addEventListener("click", async () => {
      app.cfg = {
        repo: el("cfg-repo").value.trim(),
        branch: el("cfg-branch").value.trim(),
        token: el("cfg-token").value.trim(),
        anthropicKey: el("cfg-anthropic").value.trim(),
      };
      saveSettings();
      updateProofreadVisibility();
      await connect();
      fillSettingsForm();
    });
    el("clear-settings").addEventListener("click", () => {
      app.cfg.token = "";
      app.cfg.anthropicKey = "";
      saveSettings();
      fillSettingsForm();
      updateProofreadVisibility();
      connect();
      banner("トークンとキーをこのブラウザから消しました。", "ok");
    });

    for (const tab of document.querySelectorAll(".tab")) {
      tab.addEventListener("click", () => switchTab(tab.dataset.tab));
    }
    for (const chip of document.querySelectorAll("[data-quick]")) {
      chip.addEventListener("click", () => applyQuick(chip.dataset.quick));
    }
    el("f-text").addEventListener("input", updateCounter);
    el("add-thread").addEventListener("click", () => addThreadPart());
    el("f-image").addEventListener("change", onImageChange);
    el("remove-image").addEventListener("click", () => {
      app.pendingImage = null;
      el("f-image").value = "";
      el("image-preview").hidden = true;
    });
    el("proofread").addEventListener("click", onProofread);
    el("apply-proofread").addEventListener("click", applyProofread);
    el("dismiss-proofread").addEventListener("click", () => {
      el("proofread-result").hidden = true;
    });
    el("cancel-edit").addEventListener("click", resetComposer);
    el("composer").addEventListener("submit", onSubmit);

    setScheduledInput(defaultScheduledAt());
    updateProofreadVisibility();
    connect();
  }

  /** 初期化が失敗しても白紙にせず、何が起きたかを画面に出す。 */
  function start() {
    try {
      init();
    } catch (error) {
      const node = document.getElementById("banner");
      if (node) {
        node.textContent = `画面の準備に失敗しました: ${error.message}`;
        node.className = "banner banner-error";
        node.hidden = false;
      }
      throw error;
    }
  }

  window.addEventListener("error", (event) => {
    const node = document.getElementById("banner");
    if (node && node.hidden) {
      node.textContent = `エラー: ${event.message}`;
      node.className = "banner banner-error";
      node.hidden = false;
    }
  });

  // スクリプトは body の末尾にあるため、読み込み済みならそのまま初期化する
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
