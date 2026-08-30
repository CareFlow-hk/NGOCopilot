import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  FileUp,
  LoaderCircle,
  MapPin,
  Plus,
  Search,
  Trash2,
  X,
} from 'lucide-react';
import './activity-scheduler.css';

type Session = {
  id?: string;
  session_date: string;
  start_time: string | null;
  end_time: string | null;
  raw_date_text?: string | null;
};

type Activity = {
  id: string;
  name: string;
  description: string | null;
  location: string | null;
  activity_code: string | null;
  sessions: Session[];
};

type Member = { id: string; name: string };
type ScheduleItem = { activity_id: string; name: string; location: string | null; sessions: Session[] };
type Draft = { source_filename: string; activities: Omit<Activity, 'id'>[] };
type ImportJob = {
  job_id?: string;
  status: 'processing' | 'ready' | 'failed';
  source_filename?: string;
  activities?: Omit<Activity, 'id'>[];
  detail?: string;
};
type ConflictResult = {
  status?: string;
  has_conflict: boolean;
  has_time_uncertainty: boolean;
  conflicts: Array<{ existing_activity?: string; new_session: Session; existing_session: Session }>;
};

const PRODUCTION_API_URL = 'https://ngopilot-api-production.up.railway.app';
const API_BASE = (import.meta.env.VITE_API_URL || (import.meta.env.PROD ? PRODUCTION_API_URL : '')).replace(/\/+$/, '');
const token = () => localStorage.getItem('ngopilot.auth.token');
const wait = (milliseconds: number) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const accessToken = token();
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: 'include' });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string' ? body.detail : 'Unable to complete this request');
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const timeLabel = (session: Session) =>
  session.start_time && session.end_time ? `${session.start_time.slice(0, 5)}-${session.end_time.slice(0, 5)}` : 'Time needs review';
const dateLabel = (value: string) =>
  new Intl.DateTimeFormat('en-HK', { month: 'short', day: 'numeric', year: 'numeric' }).format(
    new Date(`${value}T12:00:00`),
  );
const monthLabel = (value: Date) => new Intl.DateTimeFormat('en-HK', { month: 'long', year: 'numeric' }).format(value);
const isoDate = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;

export default function ActivityScheduler(): React.ReactElement {
  const inputRef = useRef<HTMLInputElement>(null);
  const [activities, setActivities] = useState<Activity[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [memberId, setMemberId] = useState('');
  const [schedule, setSchedule] = useState<ScheduleItem[]>([]);
  const [search, setSearch] = useState('');
  const [filterDate, setFilterDate] = useState('');
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const [selected, setSelected] = useState<Activity | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [newMemberName, setNewMemberName] = useState('');
  const [conflict, setConflict] = useState<ConflictResult | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadActivities = async () => {
    const query = new URLSearchParams();
    if (search.trim()) query.set('search', search.trim());
    if (filterDate) query.set('date', filterDate);
    const result = await api<{ activities: Activity[] }>(`/api/activities${query.size ? `?${query}` : ''}`);
    setActivities(result.activities);
  };
  const loadMembers = async () => {
    const result = await api<{ members: Member[] }>('/api/members');
    setMembers(result.members);
    setMemberId((current) => current || result.members[0]?.id || '');
  };
  const loadSchedule = async (id = memberId) => {
    if (!id) return setSchedule([]);
    const result = await api<{ items: ScheduleItem[] }>(`/api/members/${id}/schedule`);
    setSchedule(result.items);
  };
  const refresh = async () => {
    setError(null);
    try {
      await Promise.all([loadActivities(), loadMembers()]);
      await loadSchedule();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to load activities');
    }
  };

  useEffect(() => { void loadActivities().catch((cause) => setError(cause.message)); }, [search, filterDate]);
  useEffect(() => { void loadMembers().catch((cause) => setError(cause.message)); }, []);
  useEffect(() => { void loadSchedule().catch((cause) => setError(cause.message)); }, [memberId]);

  const calendarSessions = useMemo(
    () => activities.flatMap((activity) => activity.sessions.map((session) => ({ activity, session }))),
    [activities],
  );
  const days = useMemo(() => {
    const start = new Date(month.getFullYear(), month.getMonth(), 1);
    const first = (start.getDay() + 6) % 7;
    const total = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
    return Array.from({ length: Math.ceil((first + total) / 7) * 7 }, (_, index) => {
      const day = index - first + 1;
      return day >= 1 && day <= total ? new Date(month.getFullYear(), month.getMonth(), day) : null;
    });
  }, [month]);

  const upload = async (file: File) => {
    setIsImporting(true); setError(null); setNotice(null);
    try {
      const body = new FormData(); body.set('file', file);
      const started = await api<ImportJob>('/api/activity-import/jobs', { method: 'POST', body });
      if (!started.job_id) throw new Error('The extraction job did not start');
      let transientFailures = 0;
      for (let attempt = 0; attempt < 180; attempt += 1) {
        await wait(1000);
        let job: ImportJob;
        try {
          job = await api<ImportJob>(`/api/activity-import/jobs/${started.job_id}`);
          transientFailures = 0;
        } catch (cause) {
          transientFailures += 1;
          if (transientFailures < 5) continue;
          throw cause;
        }
        if (job.status === 'failed') throw new Error(job.detail || 'Unable to extract this file');
        if (job.status === 'ready') {
          if (!job.source_filename || !job.activities) throw new Error('The extraction result is incomplete');
          setDraft({ source_filename: job.source_filename, activities: job.activities });
          return;
        }
      }
      throw new Error('Activity extraction timed out. Please try again.');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Unable to extract this file'); }
    finally { setIsImporting(false); if (inputRef.current) inputRef.current.value = ''; }
  };
  const updateDraft = (activityIndex: number, sessionIndex: number | null, field: string, value: string) => {
    setDraft((current) => {
      if (!current) return current;
      const next = structuredClone(current);
      if (sessionIndex === null) (next.activities[activityIndex] as Record<string, unknown>)[field] = value || null;
      else (next.activities[activityIndex].sessions[sessionIndex] as Record<string, unknown>)[field] = value || null;
      return next;
    });
  };
  const confirmImport = async () => {
    if (!draft) return;
    setIsConfirming(true); setError(null);
    try {
      const result = await api<{ imported: number }>('/api/activity-import/confirm', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(draft),
      });
      setDraft(null); setNotice(`${result.imported} activities imported and ready to schedule.`); await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Unable to confirm import'); }
    finally { setIsConfirming(false); }
  };
  const addMember = async () => {
    if (!newMemberName.trim()) return;
    try {
      const member = await api<Member>('/api/members', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: newMemberName }) });
      setNewMemberName(''); await loadMembers(); setMemberId(member.id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Unable to add member'); }
  };
  const addToSchedule = async (override = false) => {
    if (!selected || !memberId) return;
    try {
      const result = await api<ConflictResult>(`/api/members/${memberId}/schedule`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ activity_id: selected.id, override_conflicts: override }),
      });
      if (result.status === 'needs_confirmation') { setConflict(result); return; }
      setConflict(null); setNotice(`${selected.name} was added to the member schedule.`); await loadSchedule();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Unable to update schedule'); }
  };
  const removeFromSchedule = async (activityId: string) => {
    if (!memberId) return;
    try { await api<void>(`/api/members/${memberId}/schedule/${activityId}`, { method: 'DELETE' }); await loadSchedule(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Unable to remove activity'); }
  };

  return <main className="activity-scheduler">
    <input ref={inputRef} type="file" accept=".txt,.csv,.md,.html,.htm,.pdf,.png,.jpg,.jpeg,.webp,text/plain,text/csv,application/pdf,image/png,image/jpeg,image/webp" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); }} />
    <header className="activity-header">
      <div><p className="activity-kicker">Scheduler / Activities</p><h1>Community activities</h1><p>Review activity notices, then plan with the member in view.</p></div>
      <button className="activity-primary" onClick={() => inputRef.current?.click()} disabled={isImporting}>{isImporting ? <LoaderCircle className="spin" /> : <FileUp />} {isImporting ? 'Extracting' : 'Import activities'}</button>
    </header>
    {error && <div className="activity-alert danger"><AlertTriangle />{error}<button onClick={() => setError(null)} aria-label="Dismiss error"><X /></button></div>}
    {notice && <div className="activity-alert success">{notice}<button onClick={() => setNotice(null)} aria-label="Dismiss notice"><X /></button></div>}
    <section className="activity-controls" aria-label="Activity filters">
      <label><Search /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search activity name" /></label>
      <label className="date-filter"><span>Date</span><input type="date" value={filterDate} onChange={(event) => setFilterDate(event.target.value)} /></label>
      <div className="member-control"><span>Member</span><select value={memberId} onChange={(event) => setMemberId(event.target.value)}><option value="">Select member</option>{members.map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select></div>
      <div className="member-create"><input value={newMemberName} onChange={(event) => setNewMemberName(event.target.value)} placeholder="New member name" onKeyDown={(event) => { if (event.key === 'Enter') void addMember(); }} /><button onClick={() => void addMember()} title="Add member" aria-label="Add member"><Plus /></button></div>
    </section>
    <section className="activity-workspace">
      <div className="calendar-panel">
        <div className="calendar-heading"><div><CalendarDays /><strong>{monthLabel(month)}</strong></div><div><button onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))} aria-label="Previous month"><ChevronLeft /></button><button onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))} aria-label="Next month"><ChevronRight /></button></div></div>
        <div className="calendar-grid">{['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map((day) => <div className="weekday" key={day}>{day}</div>)}{days.map((day, index) => <div className={`calendar-day${day ? '' : ' blank'}${day && isoDate(day) === isoDate(new Date()) ? ' today' : ''}`} key={index}>{day && <><span>{day.getDate()}</span><div className="calendar-events">{calendarSessions.filter(({ session }) => session.session_date === isoDate(day!)).slice(0, 3).map(({ activity, session }) => <button key={`${activity.id}-${session.id || session.session_date}`} onClick={() => setSelected(activity)} title={`${activity.name}, ${timeLabel(session)}`}>{activity.name}</button>)}</div></>}</div>)}</div>
      </div>
      <aside className="member-panel"><div className="member-panel-title"><span>Member schedule</span>{memberId && <small>{members.find((member) => member.id === memberId)?.name}</small>}</div>{!memberId ? <p className="empty">Select or add a member to see their schedule.</p> : schedule.length === 0 ? <p className="empty">No activities yet.</p> : <div className="schedule-list">{schedule.map((item) => <article key={item.activity_id}><div><strong>{item.name}</strong>{item.location && <small><MapPin />{item.location}</small>}</div><button onClick={() => void removeFromSchedule(item.activity_id)} title={`Remove ${item.name}`} aria-label={`Remove ${item.name}`}><Trash2 /></button><ul>{item.sessions.map((session) => <li key={session.id || `${session.session_date}-${session.start_time}`} className={!session.start_time || !session.end_time ? 'needs-review' : ''}>{dateLabel(session.session_date)} · {timeLabel(session)}</li>)}</ul></article>)}</div>}</aside>
    </section>
    {selected && <aside className="activity-drawer" aria-label="Activity details"><button className="drawer-close" onClick={() => { setSelected(null); setConflict(null); }} aria-label="Close activity details"><X /></button><p className="activity-kicker">Activity details</p><h2>{selected.name}</h2>{selected.location && <p className="detail-location"><MapPin />{selected.location}</p>}{selected.description && <p className="detail-description">{selected.description}</p>}<h3>Sessions</h3><ul className="detail-sessions">{selected.sessions.map((session) => <li key={session.id || `${session.session_date}-${session.start_time}`} className={!session.start_time || !session.end_time ? 'needs-review' : ''}><strong>{dateLabel(session.session_date)}</strong><span>{timeLabel(session)}</span></li>)}</ul>{conflict && <div className="conflict-warning"><AlertTriangle /><div><strong>{conflict.has_conflict ? 'Schedule conflict' : 'Time information is insufficient'}</strong>{conflict.conflicts.map((item, index) => <p key={index}>{dateLabel(item.new_session.session_date)} {timeLabel(item.new_session)} overlaps {item.existing_activity} ({timeLabel(item.existing_session)}).</p>)}{conflict.has_time_uncertainty && <p>One or more sessions are missing a start or end time, so a conflict cannot be confirmed.</p>}</div><div className="conflict-actions"><button onClick={() => setConflict(null)}>Cancel</button><button className="activity-primary" onClick={() => void addToSchedule(true)}>Add anyway</button></div></div>}<button className="activity-primary drawer-add" disabled={!memberId} onClick={() => void addToSchedule()}>{memberId ? 'Add to member schedule' : 'Select a member first'}</button></aside>}
    {draft && <div className="import-overlay" role="dialog" aria-modal="true" aria-label="Review imported activities"><section className="import-review"><header><div><p className="activity-kicker">Review before import</p><h2>{draft.source_filename}</h2><p>Correct any extracted details before they are saved to the activity library.</p></div><button onClick={() => setDraft(null)} aria-label="Close review"><X /></button></header><div className="review-table">{draft.activities.map((activity, activityIndex) => <section key={activityIndex}><div className="review-activity"><label>Activity name<input value={activity.name || ''} onChange={(event) => updateDraft(activityIndex, null, 'name', event.target.value)} /></label><label>Location<input value={activity.location || ''} onChange={(event) => updateDraft(activityIndex, null, 'location', event.target.value)} /></label></div>{activity.sessions.length === 0 ? <p className="needs-review">No dated sessions were found. Add details in a later import if needed.</p> : activity.sessions.map((session, sessionIndex) => <div className="review-session" key={sessionIndex}><label>Date<input type="date" value={session.session_date} onChange={(event) => updateDraft(activityIndex, sessionIndex, 'session_date', event.target.value)} /></label><label>Start<input type="time" value={session.start_time || ''} onChange={(event) => updateDraft(activityIndex, sessionIndex, 'start_time', event.target.value)} /></label><label>End<input type="time" value={session.end_time || ''} onChange={(event) => updateDraft(activityIndex, sessionIndex, 'end_time', event.target.value)} /></label></div>)}</section>)}</div><footer><button onClick={() => setDraft(null)}>Cancel</button><button className="activity-primary" onClick={() => void confirmImport()} disabled={isConfirming}>{isConfirming ? <LoaderCircle className="spin" /> : null}{isConfirming ? 'Importing' : 'Confirm import'}</button></footer></section></div>}
  </main>;
}
