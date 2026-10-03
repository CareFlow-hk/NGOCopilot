import { useEffect, useRef, useState } from 'react';

type Data = Record<string, any>;
export const NGO_TOOLS: Record<string, string> = {
  careflow_paper_forms_to_excel: '紙本表格 → Excel',
  careflow_meeting_notes: '會議／家訪記錄',
  careflow_government_forms: '政府表格填報',
  roster_copilot: '人手排班',
  activity_scheduler: '活動小冊子 → 日曆',
};

const states: Record<string, string> = {
  accepted: '已接收', running: '處理中', pending_review: '待你核對',
  needs_review: '待你核對', awaiting_review: '待你核對', review_required: '待你核對',
  ready: '可核對及匯出', confirmed: '已核對', reviewed: '已核對',
  exported: '文件已產生', published: '已發佈', failed: '未能完成', blocked: '有待處理事項',
};

function apiPath(path: string) {
  return `${String(window.appConfig?.get('NGOPILOT_API_URL') || '').replace(/\/$/, '')}${path}`;
}

async function authenticatedFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  const token = localStorage.getItem('ngopilot.auth.token');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  return fetch(apiPath(path), { ...init, headers, credentials: 'include' });
}

async function request(path: string, init: RequestInit = {}) {
  const response = await authenticatedFetch(path, init);
  const data = await response.json().catch(() => ({ detail: '服務暫時無法回應，請稍後重試。' }));
  if (!response.ok) throw new Error(Array.isArray(data.detail) ? data.detail.map((item: Data) => item.msg).join('；') : data.detail || '未能讀取任務，請重試。');
  return data;
}

function SourceAttachment({ source }: { source: Data }) {
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const image = /\.(png|jpe?g)$/i.test(source.filename);
  useEffect(() => {
    if (!image) return;
    let disposed = false;
    let objectUrl = '';
    void authenticatedFetch(source.url).then(async (response) => {
      if (!response.ok) throw new Error('原始附件暫時無法載入');
      const blob = await response.blob();
      if (!disposed) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl); }
    }).catch((cause) => { if (!disposed) setError(String(cause.message)); });
    return () => { disposed = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [source.url, image]);
  async function open() {
    try {
      const response = await authenticatedFetch(source.url);
      if (!response.ok) throw new Error('原始附件暫時無法載入');
      const objectUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement('a'); link.href = objectUrl; link.download = source.filename; link.click();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
    } catch (cause) { setError(cause instanceof Error ? cause.message : '讀取失敗'); }
  }
  return <div>{image && url ? <a href={url} target="_blank" rel="noreferrer"><img src={url} alt={`原始表格：${source.filename}`} className="max-h-64 max-w-full rounded border border-border-primary" /></a>
    : <button className="text-sm underline" onClick={() => void open()}>{source.filename}</button>}{error && <p role="alert">{error}</p>}</div>;
}

export function workflowResult(value: unknown): Data | null {
  if (!value || typeof value !== 'object') return null;
  const result = value as Data;
  if (result.tool && result.job_id && NGO_TOOLS[result.tool]) return result;
  if (result.structuredContent) {
    const found = workflowResult(result.structuredContent);
    if (found) return found;
  }
  if (result.value) {
    const found = workflowResult(result.value);
    if (found) return found;
  }
  if (Array.isArray(result.content)) {
    for (const item of result.content) {
      if (item.type !== 'text') continue;
      try { const found = workflowResult(JSON.parse(item.text)); if (found) return found; } catch { /* prose */ }
    }
  }
  return null;
}

function initialDraft(job: Data): Data {
  const result = job.result || {};
  if (job.proposed_input && (job.proposed_input.reviews || job.proposed_input.slot_content_final || job.proposed_input.field_values)) return structuredClone(job.proposed_input);
  if (job.tool === 'careflow_paper_forms_to_excel') return {
    reviews: (result.records || []).filter((record: Data) => record.final_fields).map((record: Data) => ({
      record_id: record.id, final_fields: { ...record.final_fields },
    })),
  };
  if (job.tool === 'careflow_meeting_notes') return {
    slot_content_final: { ...(result.slot_content_final || result.slot_content || {}) },
  };
  if (job.tool === 'careflow_government_forms') return {
    field_values: { ...Object.fromEntries((result.preview?.mappings || []).map((field: Data) => [field.key, String(field.value ?? '')])),
      ...(result.reviewed_values || {}) },
  };
  if (job.tool === 'activity_scheduler') return {
    reviews: (result.activities || []).map((record: Data) => ({ id: record.id, revision: record.revision,
      data: structuredClone(record.data), status: record.review_status === 'excluded' ? 'excluded' : 'confirmed', note: '' })),
  };
  return {};
}

function Field({ label, value, onChange, kind, options }: { label: string; value: any; onChange: (value: any) => void; kind?: string; options?: string[] }) {
  const style = 'w-full rounded-md border border-border-primary bg-background-primary px-2 py-1.5 text-sm text-text-primary';
  if (options?.length) return <label className="block text-sm"><span className="mb-1 block text-text-secondary">{label}</span><select className={style} value={String(value ?? '')} onChange={(e) => onChange(e.target.value || null)}><option value="">未提供</option>{options.map((option) => <option key={option} value={option}>{option}</option>)}</select></label>;
  if (typeof value === 'boolean' || kind === 'boolean' || kind === 'bool') return (
    <label className="block text-sm"><span className="mb-1 block text-text-secondary">{label}</span><select className={style} value={value === true ? 'yes' : value === false ? 'no' : 'unknown'} onChange={(e) => onChange(e.target.value === 'unknown' ? null : e.target.value === 'yes')}><option value="unknown">未確定</option><option value="yes">是</option><option value="no">否</option></select></label>
  );
  return <label className="block text-sm"><span className="mb-1 block text-text-secondary">{label}</span>
    <textarea className={style} rows={typeof value === 'string' && value.length > 90 ? 3 : 1}
      value={typeof value === 'object' && value !== null ? JSON.stringify(value, null, 2) : String(value ?? '')}
      onChange={(e) => {
        const text = e.target.value;
        if (typeof value === 'number' || kind === 'number' || kind === 'integer') onChange(text === '' ? null : Number.isFinite(Number(text)) ? Number(text) : text);
        else if (value !== null && typeof value === 'object') { try { onChange(JSON.parse(text)); } catch { /* keep a valid structured value */ } }
        else onChange(text);
      }} />
  </label>;
}

export default function WorkflowTaskCard({ initial, append }: { initial: Data; append?: (text: string) => void }) {
  const [job, setJob] = useState<Data>(initial);
  const [draft, setDraft] = useState<Data>(() => initialDraft(initial));
  const [reviewer, setReviewer] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [sent, setSent] = useState(false);
  const [auditId, setAuditId] = useState('');
  const [auditAction, setAuditAction] = useState('approve');
  const [note, setNote] = useState('');
  const dirty = useRef(false);
  const draftRevision = useRef<string | undefined>();
  const proposal = useRef('');
  const card = useRef<HTMLElement>(null);

  useEffect(() => {
    let disposed = false;
    const refresh = async () => {
      try {
        const value = await request(`/api/workflows/${initial.job_id}`);
        if (disposed) return;
        setJob(value);
        setLoadError('');
        const nextProposal = JSON.stringify(value.proposed_input);
        if (!dirty.current && (draftRevision.current !== value.revision || proposal.current !== nextProposal)) {
          setDraft(initialDraft(value));
          draftRevision.current = value.revision;
          setSent(false);
          proposal.current = nextProposal;
        }
      } catch (cause) {
        if (!disposed) setLoadError(cause instanceof Error ? cause.message : '未能讀取任務');
      }
    };
    void refresh();
    const timer = setInterval(refresh, 2500);
    return () => { disposed = true; clearInterval(timer); };
  }, [initial.job_id]);

  const result = job.result || {};
  const isRoster = job.tool === 'roster_copilot';
  const isScheduler = job.tool === 'activity_scheduler';
  const pendingAudits = (result.audit_items || []).filter((item: Data) => item.status === 'pending');
  const selectedAudit = pendingAudits.find((item: Data) => item.id === auditId) || pendingAudits[0];
  const pendingAction = job.pending_action;
  const operation = pendingAction?.operation || (isRoster && !selectedAudit ? 'export' : 'review');
  const canConfirm = (job.next_operations || []).includes(operation) && !sent && !busy;
  const stale = dirty.current && draftRevision.current !== job.revision;

  function edit(next: Data) { dirty.current = true; setDraft(next); setSent(false); }

  async function confirm() {
    if (!append || !reviewer.trim() || stale || window.appConfig?.get('NGOPILOT_MODEL_CONFIGURED') === false) return;
    setBusy(true); setError('');
    try {
      let input: Data = structuredClone(draft);
      if (pendingAction) input = structuredClone(pendingAction.input);
      else if (job.tool === 'careflow_paper_forms_to_excel') input.reviews = input.reviews.map((record: Data) => ({ ...record, reviewer: reviewer.trim() }));
      else if (!isRoster) input.reviewer = reviewer.trim();
      else if (selectedAudit) input = {
        source_version_id: result.version.id, content_hash: result.reconciliation.content_hash,
        idempotency_key: crypto.randomUUID(), actor: reviewer.trim(), action: auditAction,
        audit_id: selectedAudit.id, note: note || null,
      };
      else input = {};
      const approved = await request(`/api/workflows/${job.job_id}/confirm`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ operation, input, reviewer: reviewer.trim(), revision: job.revision }),
      });
      setSent(true); dirty.current = false;
      append(`我已在任務卡核對並按下確認。請用以下已授權的原樣參數調用工具，${pendingAction ? '完成這次操作後回報結果；不要進行其他操作。' : '再完成我要求的文件匯出。這次確認不包含發佈或銷毀資料。'}\n${JSON.stringify(approved)}`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : '未能確認，請重試。'); }
    finally { setBusy(false); }
  }

  async function download(path: string) {
    try {
      const data = await request(`/api/artifacts/url?path=${encodeURIComponent(path)}`);
      const link = document.createElement('a'); link.href = data.url.startsWith('/') ? apiPath(data.url) : data.url;
      link.download = data.filename; link.click();
    } catch (cause) { setError(cause instanceof Error ? cause.message : '下載失敗'); }
  }

  return <section ref={card} className="ngo-task-card my-3 rounded-xl border border-border-primary bg-background-primary p-4" aria-label={`${NGO_TOOLS[job.tool]}任務`}>
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <strong>{NGO_TOOLS[job.tool]}</strong><span role="status" className="rounded-full bg-background-secondary px-3 py-1 text-xs">{states[job.state] || (job.next_operations?.includes('review') ? '待你核對' : job.state)}</span>
    </div>
    {job.sources?.length > 0 && <details className="mb-3" open={job.tool === 'careflow_paper_forms_to_excel'}>
      <summary className="cursor-pointer text-sm text-text-secondary">原始附件（{job.sources.length}）</summary>
      <div className="mt-2 flex flex-wrap gap-3">{job.sources.map((source: Data) => <SourceAttachment key={source.id} source={source} />)}</div>
    </details>}
    {job.error && <p role="alert" className="mb-3 text-red-700">{job.error.message || '工具未能完成。請修正資料後在對話中重試。'}</p>}
    {job.warnings?.length > 0 && <details className="mb-3 text-sm"><summary>處理提示（{job.warnings.length}）</summary><ul>{job.warnings.map((warning: any, index: number) => <li key={index}>{typeof warning === 'string' ? warning : warning.message || warning.code}</li>)}</ul></details>}
    {job.tool === 'careflow_paper_forms_to_excel' && draft.reviews?.map((review: Data, index: number) => <fieldset disabled={job.state === 'exported'} key={review.record_id} className="mb-4 grid gap-3 sm:grid-cols-2">
      <legend className="mb-2 text-sm font-medium">第 {index + 1} 份表格 · 核對辨識內容</legend>
      {(result.field_schema || Object.keys(review.final_fields).map((key) => ({ key, label: key }))).map((field: Data) => <Field key={field.key} label={field.label || field.key} kind={field.type} options={field.options} value={review.final_fields[field.key]} onChange={(value) => edit({ ...draft, reviews: draft.reviews.map((item: Data, i: number) => i === index ? { ...item, final_fields: { ...item.final_fields, [field.key]: value } } : item) })} />)}
    </fieldset>)}
    {job.tool === 'careflow_meeting_notes' && <>
      {result.transcript_snippet && <details className="mb-3 text-sm"><summary>對照轉寫原文</summary><p className="mt-2 whitespace-pre-wrap">{result.transcript_snippet}</p></details>}
      <fieldset disabled={job.state === 'exported'} className="grid gap-3">{Object.entries(draft.slot_content_final || {}).map(([key, value]) => <Field key={key} label={result.template_contract?.dynamic_slots?.find((slot: Data) => slot.slot_id === key)?.label_hint || key} value={value} onChange={(next) => edit({ slot_content_final: { ...draft.slot_content_final, [key]: next } })} />)}</fieldset>
    </>}
    {job.tool === 'careflow_government_forms' && <>
      {result.elder_profile?._extraction?.notes && <p className="mb-3 text-sm text-text-secondary">辨識備註：{result.elder_profile._extraction.notes}</p>}
      <fieldset disabled={job.state === 'exported'} className="grid gap-3 sm:grid-cols-2">{Object.entries(draft.field_values || {}).map(([key, value]) => <Field key={key} label={result.preview?.mappings?.find((field: Data) => field.key === key)?.label_zh || key} value={value} onChange={(next) => edit({ field_values: { ...draft.field_values, [key]: next } })} />)}</fieldset>
    </>}
    {isScheduler && <div className="space-y-3 text-sm">
      <p>本次抽取 {result.activities?.length || 0} 個活動。核對日期和時間後才會產生日曆；這不會替你報名。</p>
      {result.review_url && <div className="flex gap-4"><a className="underline" href={result.review_url} target="_blank" rel="noreferrer">對照小冊子原頁</a><a className="underline" href={result.calendar_url} target="_blank" rel="noreferrer">開啟同一批活動的月曆</a></div>}
      {draft.reviews?.map((review: Data, index: number) => {
        const record = result.activities?.find((item: Data) => item.id === review.id);
        const update = (changes: Data) => edit({ reviews: draft.reviews.map((item: Data, i: number) => i === index ? { ...item, ...changes } : item) });
        const updateData = (changes: Data) => update({ data: { ...review.data, ...changes } });
        return <details key={review.id} open={index === 0} className="rounded border border-border-primary p-3"><summary className="cursor-pointer font-medium">{index + 1}. {review.data.title} · 原頁 {record?.page}</summary>
          <p className="my-2 whitespace-pre-wrap text-text-secondary">{review.data.source_text}</p>
          {record?.issues?.length > 0 && <p className="text-amber-700">{record.issues.join('；')}</p>}
          {review.data.source_warnings?.length > 0 && <p className="text-amber-700">來源疑點：{review.data.source_warnings.join('；')}</p>}
          <fieldset disabled={job.state === 'exported'} className="grid gap-3 sm:grid-cols-2">
            <Field label="活動名稱" value={review.data.title} onChange={(title) => updateData({ title })} />
            <Field label="日期（YYYY-MM-DD，多個日期以逗號分隔）" value={(review.data.recurrence ? record?.expanded_dates || [] : review.data.dates || []).join(', ')} onChange={(value) => updateData({ dates: value.split(',').map((date: string) => date.trim()).filter(Boolean), recurrence: null })} />
            <Field label="開始時間" value={review.data.start_time} onChange={(start_time) => updateData({ start_time })} />
            <Field label="結束時間" value={review.data.end_time} onChange={(end_time) => updateData({ end_time })} />
            <Field label="地點" value={review.data.location} onChange={(location) => updateData({ location })} />
            <Field label="費用（按來源）" value={review.data.fee} onChange={(fee) => updateData({ fee })} />
            <label>名額狀態<select className="ml-2 rounded border p-1" value={review.data.availability} onChange={(e) => updateData({ availability: e.target.value })}><option value="unknown">未確定，需向中心查詢</option><option value="full">已滿</option><option value="cancelled">已取消</option></select></label>
            <label>處理方式<select className="ml-2 rounded border p-1" value={review.status} onChange={(e) => update({ status: e.target.value })}><option value="confirmed">核對並保留</option><option value="excluded">排除此活動</option></select></label>
            <Field label="核對說明（有來源疑點時必填）" value={review.note} onChange={(note) => update({ note })} />
          </fieldset>
        </details>;
      })}
    </div>}
    {isRoster && <div className="space-y-3 text-sm">
      {result.base_data_label && <p className="rounded bg-background-secondary p-2">{result.base_data_label}</p>}
      <p>目標週：{result.week_start} · 待核對項目：{pendingAudits.length} · 未安排：{result.unassigned_items?.length || 0}</p>
      {result.export_block_reasons?.length > 0 && <p className="text-amber-700">匯出限制：{result.export_block_reasons.join('；')}</p>}
      <details><summary className="cursor-pointer">查看排班及待處理事項</summary>
        <div className="max-h-72 overflow-auto"><table className="w-full text-left"><thead><tr><th>日期</th><th>員工</th><th>時段</th><th>備註</th></tr></thead><tbody>{(result.version?.entries || []).map((entry: Data, index: number) => <tr key={entry.id || index}><td>{entry.schedule_date}</td><td>{entry.worker_name || entry.worker_id}</td><td>{entry.start_time}–{entry.end_time}</td><td>{entry.notes || entry.service_code}</td></tr>)}</tbody></table>
          {(result.unassigned_items || []).map((item: Data, index: number) => <p key={index}>{item.message || item.explanation} {item.next_action}</p>)}</div>
      </details>
      {selectedAudit && <><label className="block">核對項目<select className="block w-full rounded border p-2" value={selectedAudit.id} onChange={(e) => { setAuditId(e.target.value); setSent(false); }}>
        {pendingAudits.map((item: Data) => <option key={item.id} value={item.id}>{item.reason || item.kind}</option>)}</select></label>
        <p>{selectedAudit.reason} {(selectedAudit.reasons || []).join?.('；')}</p>
        <label className="block">處理方式<select className="ml-3 rounded border p-1" value={auditAction} onChange={(e) => setAuditAction(e.target.value)}><option value="approve">接受建議</option><option value="reject">拒絕建議</option></select></label>
        <Field label="處理原因／備註" value={note} onChange={setNote} /></>}
      <p className="text-text-secondary">這份是排班草稿。匯出不會發佈。</p>
    </div>}
    {canConfirm && <div className="mt-4 border-t border-border-primary pt-3">
      {pendingAction && <p className="mb-3 text-amber-700">{operation === 'burn' ? '這次操作會銷毀工具保存的轉寫原件，無法復原。對話、摘要和已匯出文件仍會保留。' : '這次操作會把目前版本標記為正式發佈，留下發佈紀錄；不會自動通知員工。'}</p>}
      <label className="block text-sm">核對人<input className="ml-3 rounded border border-border-primary bg-background-primary px-2 py-1" placeholder="填寫你的姓名" value={reviewer} onChange={(e) => setReviewer(e.target.value)} /></label>
      {stale && <p role="alert">任務內容已更新。<button className="underline" onClick={() => { dirty.current = false; draftRevision.current = job.revision; setDraft(initialDraft(job)); }}>載入最新內容重新核對</button></p>}
      <button className="mt-3 rounded-lg bg-text-primary px-4 py-2 text-sm text-background-primary disabled:opacity-40" disabled={!reviewer.trim() || !append || stale || window.appConfig?.get('NGOPILOT_MODEL_CONFIGURED') === false} onClick={() => void confirm()}>{pendingAction ? operation === 'burn' ? '確認銷毀此任務轉寫' : '確認發佈目前排班' : isRoster ? '確認以上排班處理' : '確認內容無誤，繼續產生文件'}</button>
      <p className="mt-2 text-xs text-text-secondary">你可以先修改以上內容。按下確認後，Agent 才能繼續。</p>
    </div>}
    {(busy || sent) && <p role="status" className="mt-3 text-sm">{busy ? '正在記錄你的確認…' : '已收到你的確認，Agent 正在繼續。'}</p>}
    {(error || loadError) && <p role="alert" className="mt-3 text-sm text-red-700">{error || loadError}</p>}
    {job.artifacts?.length > 0 && <div className="mt-4 flex flex-wrap gap-2">{job.artifacts.map((artifact: Data) => <button key={artifact.path} className="rounded-lg border border-border-primary px-3 py-2 text-sm hover:bg-background-secondary" onClick={() => void download(artifact.path)}>下載 {artifact.path.split('/').pop()}</button>)}</div>}
    {job.updated_at && <p className="mt-3 text-xs text-text-secondary">更新：{new Date(job.updated_at).toLocaleString('zh-HK')}</p>}
  </section>;
}
