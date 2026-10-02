const $ = (s) => document.querySelector(s);
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const state = {
  health: null,
  jobs: [],
  tool: null,
  result: null,
  busy: false,
  error: "",
  templates: [],
  op: null,
};
const names = {
  pending_review: "待人工審核",
  reviewed: "已人工審核",
  confirmed: "已人工審核",
  exported: "已匯出",
  blocked: "已阻塞 · 未發布",
  draft: "草稿（未發布）",
  ready: "待發布草稿",
  failed: "處理失敗",
  running: "處理中",
  accepted: "已接收",
  discovery: "範本清單",
};
const labels = {
  elder_name: "長者姓名",
  elder_age: "年齡",
  elder_gender: "性別",
  elder_phone: "電話",
  elder_address: "地址",
  living_alone: "獨居",
  visit_date: "探訪日期",
  volunteer_name: "義工姓名",
  duration_minutes: "探訪分鐘",
  mood: "情緒狀況",
  health_concerns: "健康關注",
  follow_up_needed: "需要跟進",
  follow_up_note: "跟進備註",
  summary: "內容摘要",
  follow_up: "跟進事項",
  meeting_title: "會議名稱",
  meeting_date: "會議日期",
  meeting_purpose: "會議目的",
  confirmed_decisions: "已確認決定",
  action_items_due_dates: "待辦與期限",
  unresolved_questions: "未解決事項",
  attendees: "出席者",
  decisions: "決定事項",
  action_items: "待辦事項",
};
async function api(path, method = "GET", data) {
  const r = await fetch("/api" + path, {
    method,
    headers:
      data && !(data instanceof FormData)
        ? { "Content-Type": "application/json" }
        : undefined,
    body:
      data instanceof FormData ? data : data ? JSON.stringify(data) : undefined,
  });
  const value = await r.json();
  if (!r.ok)
    throw new Error(
      typeof value.detail === "string"
        ? value.detail
        : "資料格式不符，請檢查後重試",
    );
  return value;
}
async function refresh() {
  [state.health, state.jobs] = await Promise.all([
    api("/health"),
    api("/jobs"),
  ]);
}
function frame(content) {
  return `<header class="topbar"><a class="brand" href="/">NGOPilot<span>CARE FLOW · 文件工作台</span></a><div class="status"><span class="pill ${state.health?.models.mock ? "mock" : ""}">${state.health?.models.mock ? "模擬模式 · 非真實 AI 結果" : "本機試用版 · 需人工審核"}</span><span>資料保存在這部電腦</span></div></header><main class="shell">${state.error ? `<div class="error" role="alert">${esc(state.error)}</div>` : ""}${content}<footer class="footer"><span>CareFlow · 讓同工專注於服務</span><details><summary>進階 · 管理員</summary><p>通用 Agent 及雲端服務保留在原有部署目錄。<br/>模型：視覺 ${esc(state.health?.models.vision_model || "未設定")}；文字 ${esc(state.health?.models.text_model || "未設定")}<br/>獨立活動排程：<a href="http://127.0.0.1:8311" target="_blank" rel="noreferrer">CareFlow Scheduler</a><br/>本機工作台不提供對外分享、發布排班或銷毀逐字稿。</p></details></footer></main>`;
}
function render() {
  if (!state.health) return;
  $("#app").innerHTML = frame(state.tool ? workspace() : home());
  bind();
}
function home() {
  return `<div class="eyebrow">每天少一點文書，多一點陪伴</div><h1>今天，想完成哪一項工作？</h1><p class="intro">從一份表格、一段錄音開始。先整理，再由你核對。</p><div class="cards">${Object.entries(
    state.health.workflows,
  )
    .map(
      ([key, w], i) =>
        `<button class="card" data-tool="${key}"><span class="number">0${i + 1}</span><h2>${esc(w.title)}</h2><p>${esc(w.summary)}</p><span class="go">開始工作 →</span></button>`,
    )
    .join(
      "",
    )}</div><div class="privacy-note">文件與結果儲存在本機。使用 AI 的流程會將相關圖片、文字或錄音傳送到已設定的模型服務；請先取得適當同意。請勿用真實服務對象資料作公開示範。未設定的模型不會自動改用模擬結果。</div><section class="history"><div class="section-title"><h2>最近的工作</h2><button id="refresh">重新整理</button></div>${state.jobs.length ? state.jobs.map((j) => `<button class="history-row" data-job="${j.job_id}" style="width:100%;text-align:left"><span>${esc(JSON.parse(j.input_json).title || state.health.workflows[j.tool_name]?.title || j.tool_name)}<small>${esc(state.health.workflows[j.tool_name]?.title)}</small></span><span class="pill ${j.state}">${esc(names[j.state] || j.state)}</span><time>${esc(new Date(j.updated_at).toLocaleString("zh-HK"))}</time></button>`).join("") : '<p class="small">完成第一項工作後，會在這裡保留記錄。</p>'}</section>`;
}
function startForm(kind) {
  if (kind === "paper")
    return `<label>工作名稱<input name="title" placeholder="例如：十月探訪表格"></label><label>表格照片 · JPG／PNG<input name="images" type="file" accept=".jpg,.jpeg,.png" multiple required></label><label>探訪日期（選填）<input name="visit_date" type="date"></label><p class="small">目前針對 CareFlow 義工探訪表格的 13 個欄位。不是任意表格辨識器。</p>`;
  if (kind === "meeting")
    return `<label>記錄名稱<input name="title" required placeholder="例如：義工服務檢討會"></label><label>記錄類型<select name="mode"><option value="internal_meeting">內部會議</option><option value="home_visit">家訪記錄</option></select></label><label>錄音檔<input name="audio" type="file" accept=".wav,.mp3,.m4a,.ogg,.flac,.mp4,.aac" required></label><label>Word 記錄範本<input name="template" type="file" accept=".docx" required></label><p class="small">上載有記錄欄位的 .docx 範本。錄音會送往語音服務，文字會送往整理模型。</p>`;
  if (kind === "government")
    return `<label>表格範本<select name="template_id" required>${state.templates.map((t) => `<option value="${esc(t.id)}">${esc(t.display_name || t.name || t.title || t.id)}</option>`).join("")}</select></label><label>待整理的資料<textarea name="source_text" rows="7" required placeholder="只輸入已有依據、已獲同意使用的資料。未知欄位請留空。"></textarea></label><label class="check-label"><input name="use_llm" type="checkbox" checked>使用模型輔助欄位配對</label><p class="small">文字整理仍會使用模型。產生的是待提交 PDF；沒有替你提交申請，也不代表福利資格獲批。</p>`;
  return `<label>家居照顧工作表<input name="hc" type="file" accept=".xlsx,.xlsm" required></label><label>護送工作表<input name="escort" type="file" accept=".xlsx,.xlsm" required></label><label>該週開始日期<input name="week_start" type="date" required></label><p class="small">使用 RosterCopiilot 的指定工作簿格式。演算法產生草稿與審核事項；不會自動發布。請勿使用含個資的工作表作公開示範。</p>`;
}
function workspace() {
  const w = state.health.workflows[state.tool];
  return `<button class="back" id="back">← 返回工作台</button><div class="eyebrow">${esc(w.title)}</div><h1>把來源，整理成可核對的成果</h1><p class="intro">${esc(w.summary)}</p><div class="workspace"><aside class="form-panel"><h2>1 · 準備資料</h2><p class="hint">每次開始都會建立新工作。原始上載檔案會保留。</p><form id="start-form">${startForm(w.kind)}<button class="primary" type="submit" ${state.busy ? "disabled" : ""}>開始整理</button></form></aside><section class="result-panel">${state.busy ? '<div class="busy" role="status"><span class="spinner"></span>正在處理，請稍候…<p>可以重新整理頁面；已接收的工作仍會繼續。模型回應可能需要數分鐘。</p></div>' : ""}${state.result ? resultView(w.kind) : '<div class="empty"><h2>2 · 核對來源與整理結果</h2><p>完成整理後，會在這裡顯示待確認欄位。<br/>你的確認，是匯出前的必要一步。</p></div>'}</section></div>`;
}
function fields(
  object,
  prefix = [],
  original = object,
  confidence = {},
  labelOverrides = {},
) {
  return Object.entries(object || {})
    .filter(([k]) => !k.startsWith("__"))
    .map(([k, v]) => {
      const path = [...prefix, k],
        label =
          labelOverrides[k] ||
          labels[k] ||
          (/^\d+$/.test(k) ? `第 ${Number(k) + 1} 項` : k),
        o = original?.[k];
      if (v && typeof v === "object")
        return `<div class="wide"><h3>${esc(label)}</h3><div class="field-list">${fields(v, path, o || {}, {}, labelOverrides)}</div></div>`;
      let type = typeof v;
      if (v === null && ["elder_age", "duration_minutes"].includes(k))
        type = "number";
      if (v === null && ["living_alone", "follow_up_needed"].includes(k))
        type = "boolean";
      let conf = confidence[k];
      if (typeof conf === "object") conf = conf?.confidence;
      const low =
        v === null || v === "" || (typeof conf === "number" && conf < 0.8);
      const attrs = `data-field='${esc(JSON.stringify(path))}' data-type="${type}" class="${low ? "low" : ""}"`;
      return `<label class="${typeof v === "string" && v.length > 60 ? "wide" : ""}">${esc(label)}${type === "boolean" ? `<select ${attrs}><option value="" ${v == null ? "selected" : ""}>待確認</option><option value="true" ${v === true ? "selected" : ""}>是</option><option value="false" ${v === false ? "selected" : ""}>否</option></select>` : typeof v === "string" && v.length > 60 ? `<textarea ${attrs}>${esc(v)}</textarea>` : `<input ${attrs} type="${type === "number" ? "number" : "text"}" value="${esc(v)}">`}${low ? '<span class="field-hint">缺少值或信心不足，請對照來源。</span>' : ""}<span class="original">原值：${esc(o ?? "未辨識")}</span></label>`;
    })
    .join("");
}
function reviewControls() {
  return `<div class="review-controls"><label>審核人<input id="reviewer" value="${esc(localStorage.getItem("ngopilot.reviewer") || "")}" placeholder="姓名或同工代號" required></label><label class="check-label"><input type="checkbox" id="human-confirmed">我已核對來源與上述欄位，並確認修正內容。</label><div class="actions"><button id="review" class="primary" ${state.busy ? "disabled" : ""}>確認審核</button></div><span class="small">會記錄審核人及時間。AI 整理或模型互相核對不算人工確認。</span></div>`;
}
function resultView(kind) {
  const j = state.result,
    r = j.result || {},
    ops = j.next_operations || [];
  let content = `<div class="job-heading"><h2>2 · ${esc(names[j.state] || j.state)}</h2><button id="status" ${state.busy ? "disabled" : ""}>更新狀態</button></div>`;
  if (j.error)
    content += `<div class="error">${esc(j.error.message || j.error.code)}</div>`;
  for (const w of j.warnings || [])
    content += `<div class="notice">${esc(typeof w === "string" ? w : w.message || JSON.stringify(w))}</div>`;
  if (kind === "paper") {
    content += (r.records || [])
      .map(
        (rec, index) =>
          `<article class="review-record"><div class="record-head"><h3>第 ${index + 1} 張表格</h3><span class="pill">${rec.is_reviewed ? "已人工審核" : "待人工審核"}</span></div><p class="small">${rec.ai_provider === "mock" ? "模擬資料 · 非真實抽取" : "模型整理"} · ${esc(rec.ai_provider || "未提供")} · ${esc(rec.ai_model || "")}${rec.ai_error ? " · 抽取有錯誤，請檢查來源" : ""}</p><div class="record-layout"><div class="source"><img alt="第 ${index + 1} 張原始表格" src="/api/jobs/${esc(j.job_id)}/source/${rec.id}"><a href="/api/jobs/${esc(j.job_id)}/source/${rec.id}" target="_blank" rel="noreferrer">放大原始表格 ↗</a></div><div class="field-list">${fields(rec.final_fields, ["records", String(index)], { ...rec.ai_extracted, ...rec.qwen_original }, rec.ai_confidence || {})}</div></div>${rec.reviewer ? `<p class="small">審核：${esc(rec.reviewer)} · ${esc(rec.reviewed_at || "")}</p>` : ""}</article>`,
      )
      .join("");
  }
  if (kind === "meeting") {
    content += `<article class="review-record"><h3>${esc(r.title || "記錄內容")}</h3>${r.ai_provider ? `<p class="small">${esc(r.ai_provider)} · ${esc(r.ai_model || "")}</p>` : ""}${r.ai_error ? `<div class="error">${esc(r.ai_error)}</div>` : ""}<p class="small">核對原始錄音</p><audio controls preload="metadata" src="/api/jobs/${esc(j.job_id)}/audio" style="width:100%"></audio><details><summary>來源逐字稿節錄</summary><p class="raw-text">${esc(r.transcript_snippet || "此流程沒有可顯示的節錄。請同時核對原始錄音。")}</p></details><div class="field-list">${fields(r.slot_content_final || r.slot_content || {}, ["slots"], r.slot_content || {}, {}, Object.fromEntries((r.template_contract?.dynamic_slots || []).map((s) => [s.slot_id, labels[s.slot_id] || s.label_hint || s.slot_id])))}</div></article>`;
  }
  if (kind === "government") {
    const values =
      r.reviewed_values ||
      Object.fromEntries(
        (r.preview?.mappings || []).map((m) => [m.key, m.value ?? ""]),
      );
    content += `<article class="review-record"><h3>${esc(r.template?.display_name || r.template?.name || r.template?.title || "表格欄位")}</h3><p class="small">未知資料請留空，不可猜測。匯出前請逐欄核對。範本版本可能過期，請向接收機構核實。</p><details><summary>原始輸入文字</summary><p class="raw-text">${esc(j.source_input?.source?.text || "請對照原始上載資料")}</p></details><div class="field-list">${fields(values, ["government"], Object.fromEntries((r.preview?.mappings || []).map((m) => [m.key, m.value ?? ""])), Object.fromEntries((r.preview?.mappings || []).map((m) => [m.key, m.confidence])), Object.fromEntries((r.preview?.mappings || []).map((m) => [m.key, m.label_zh || m.key])))}</div></article>`;
  }
  if (kind === "roster") {
    const blocks = r.export_block_reasons || [];
    content += `<div class="notice"><strong>排班草稿 · 未發布 · 不得直接用於實際排班</strong><br/>本機工作台不提供發布；請先處理所有阻塞原因。</div><article class="review-record"><h3>檢查結果</h3><p class="small">週開始：${esc(r.week_start || "")} · 審核事項 ${(r.audit_items || []).length} 項 · 未分派 ${(r.unassigned_items || []).length} 項</p>${blocks.map((b) => `<div class="error">${esc(typeof b === "string" ? b : JSON.stringify(b))}</div>`).join("")}<div class="blocked-list">${(r.audit_items || []).map((i) => `<div class="blocked-item"><strong>${i.blocking ? "阻塞" : "待核對"} · ${esc(i.kind)} · ${esc(i.status)}</strong>${esc(i.reason || i.reasons?.join("；") || "請核對來源")}<small>${i.human_note ? "<br/>" + esc(i.human_note) : ""}</small></div>`).join("")}</div>${ops.includes("revalidate") ? '<div class="actions" style="margin-top:18px"><button id="revalidate">重新驗證目前版本</button></div>' : ""}</article>`;
  }
  if (
    (ops.includes("review") || (kind === "paper" && r.records?.length)) &&
    kind !== "roster"
  )
    content += reviewControls();
  if (ops.includes("export") && j.state !== "blocked")
    content += `<div class="actions" style="margin-top:20px"><button id="export" class="primary" ${state.busy ? "disabled" : ""}>${kind === "roster" ? "匯出待審草稿" : "匯出已審核結果"}</button>${kind === "paper" && r.unreviewed_count > 0 ? `<span class="warning">只會匯出已審核的 ${r.reviewed_count} 筆；另有 ${r.unreviewed_count} 筆尚未審核。</span>` : ""}</div>`;
  if (j.artifacts?.length)
    content += `<div class="artifacts"><h3>3 · 下載成果</h3>${j.artifacts.map((a) => `<a href="/api/jobs/${esc(j.job_id)}/artifacts/${esc(a.artifact_id)}">下載 ${esc(a.path.split("/").pop())} ↓</a><small>已驗證 SHA-256 與檔案大小 · ${Math.round(a.size_bytes / 1024)} KB</small>`).join("")}</div>`;
  return content;
}
function collected() {
  const root = {};
  document.querySelectorAll("[data-field]").forEach((el) => {
    const path = JSON.parse(el.dataset.field);
    let target = root;
    for (const k of path.slice(0, -1)) target = target[k] ??= {};
    let value = el.value;
    const type = el.dataset.type;
    if (type === "boolean") value = value === "" ? null : value === "true";
    else if (type === "number") value = value === "" ? null : Number(value);
    else if (type === "object" && value === "") value = null;
    target[path.at(-1)] = value;
  });
  return root;
}
function merge(original, edited) {
  if (Array.isArray(original))
    return original.map((v, i) =>
      edited && String(i) in edited ? merge(v, edited[i]) : v,
    );
  if (original && typeof original === "object") {
    const result = { ...original };
    for (const [k, v] of Object.entries(edited || {}))
      result[k] = merge(original[k], v);
    return result;
  }
  return edited === undefined ? original : edited;
}
async function upload(file) {
  const form = new FormData();
  form.append("file", file);
  return (await api("/uploads", "POST", form)).path;
}
async function call(operation, input = {}, human = false, reviewer = "") {
  state.busy = true;
  state.error = "";
  render();
  try {
    const op = await api(`/tools/${state.tool}/call`, "POST", {
      operation,
      input,
      job_id:
        operation === "start" || operation === "list_templates"
          ? null
          : state.result?.job_id,
      request_id: crypto.randomUUID(),
      human_confirmed: human,
      reviewer,
    });
    state.op = op.operation_id;
    localStorage.setItem(
      "ngopilot.active-operation",
      JSON.stringify({ id: op.operation_id, tool: state.tool }),
    );
    await poll(op.operation_id);
  } catch (e) {
    state.error = e.message;
    state.busy = false;
    render();
  }
}
async function poll(id) {
  try {
    const op = await api("/operations/" + id);
    if (op.status === "running") {
      setTimeout(() => poll(id), 1500);
      return;
    }
    localStorage.removeItem("ngopilot.active-operation");
    state.busy = false;
    if (op.status === "interrupted")
      throw new Error(
        "服務重新啟動，這次操作已中斷。請更新工作狀態，必要時重新開始。",
      );
    if (op.operation === "list_templates") {
      if (op.result?.error) throw new Error(op.result.error.message);
      state.templates = op.result?.result?.templates || [];
    } else state.result = op.result;
    await refresh();
    render();
  } catch (e) {
    state.busy = false;
    state.error = e.message;
    render();
  }
}
function bind() {
  document.querySelectorAll("[data-tool]").forEach(
    (el) =>
      (el.onclick = () => {
        state.tool = el.dataset.tool;
        state.result = null;
        state.error = "";
        render();
        if (state.health.workflows[state.tool].kind === "government")
          call("list_templates");
      }),
  );
  document.querySelectorAll("[data-job]").forEach(
    (el) =>
      (el.onclick = async () => {
        try {
          state.result = await api("/jobs/" + el.dataset.job);
          state.tool = state.result.tool;
          state.error = "";
          render();
        } catch (e) {
          state.error = e.message;
          render();
        }
      }),
  );
  if ($("#back"))
    $("#back").onclick = () => {
      if (state.busy) {
        state.error = "請先等待目前操作完成。";
        render();
        return;
      }
      state.tool = null;
      state.result = null;
      state.error = "";
      refresh().then(render);
    };
  if ($("#refresh"))
    $("#refresh").onclick = () =>
      refresh()
        .then(render)
        .catch((e) => {
          state.error = e.message;
          render();
        });
  if ($("#status")) $("#status").onclick = () => call("status");
  if ($("#export")) $("#export").onclick = () => call("export");
  if ($("#revalidate"))
    $("#revalidate").onclick = () => {
      const r = state.result.result;
      call("revalidate", {
        source_version_id: r.version.id,
        content_hash: r.reconciliation.content_hash,
      });
    };
  if ($("#start-form"))
    $("#start-form").onsubmit = async (e) => {
      e.preventDefault();
      if (state.busy) return;
      const form = e.currentTarget,
        f = new FormData(form),
        kind = state.health.workflows[state.tool].kind;
      state.error = "";
      state.busy = true;
      try {
        let input;
        if (kind === "paper") {
          const files = [...form.elements.images.files];
          input = { image_paths: await Promise.all(files.map(upload)) };
          if (f.get("title")) input.title = f.get("title");
          if (f.get("visit_date")) input.visit_date = f.get("visit_date");
        } else if (kind === "meeting") {
          input = {
            title: f.get("title"),
            mode: f.get("mode"),
            audio_path: await upload(form.elements.audio.files[0]),
            template_path: await upload(form.elements.template.files[0]),
          };
        } else if (kind === "government") {
          input = {
            template_id: f.get("template_id"),
            use_llm: f.get("use_llm") === "on",
            source: { kind: "text", text: f.get("source_text") },
          };
        } else {
          input = {
            hc_workbook_path: await upload(form.elements.hc.files[0]),
            escort_workbook_path: await upload(form.elements.escort.files[0]),
            week_start: f.get("week_start"),
          };
        }
        state.result = null;
        await call("start", input);
      } catch (error) {
        state.error = error.message;
        state.busy = false;
        render();
      }
    };
  if ($("#review"))
    $("#review").onclick = () => {
      const reviewer = $("#reviewer").value.trim(),
        human = $("#human-confirmed").checked;
      if (!reviewer || !human) {
        state.error = "請填寫審核人，並勾選已核對來源。";
        const message = document.createElement("div");
        message.className = "error";
        message.role = "alert";
        message.textContent = state.error;
        $(".review-controls").prepend(message);
        return;
      }
      localStorage.setItem("ngopilot.reviewer", reviewer);
      const data = collected(),
        kind = state.health.workflows[state.tool].kind,
        r = state.result.result;
      let input;
      if (kind === "paper")
        input = {
          reviews: (r.records || []).map((rec, i) => ({
            record_id: rec.id,
            final_fields: merge(rec.final_fields, data.records?.[i]),
          })),
        };
      else if (kind === "meeting")
        input = {
          slot_content_final: merge(
            r.slot_content_final || r.slot_content,
            data.slots,
          ),
        };
      else input = { field_values: data.government };
      call("review", input, human, reviewer);
    };
}
refresh()
  .then(() => {
    const active = localStorage.getItem("ngopilot.active-operation");
    if (active) {
      try {
        const op = JSON.parse(active);
        state.tool = op.tool;
        state.busy = true;
        render();
        poll(op.id);
      } catch {
        localStorage.removeItem("ngopilot.active-operation");
        render();
      }
    } else render();
  })
  .catch((e) => {
    $("#app").innerHTML =
      `<main class="shell"><h1>暫時未能連接工作台</h1><p>${esc(e.message)}</p><button onclick="location.reload()">重試</button></main>`;
  });
