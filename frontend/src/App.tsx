import { useEffect, useRef, useState } from 'react'

/* ── Types ────────────────────────────────────────────────────────── */
type StreamEvent = { event: string; data: Record<string, unknown> }
type AgentRun = { name: string; purpose: string; summary: string; status?: string }
type ToolRunEntry = { agent: string; tool: string; arguments: Record<string, unknown>; ok: boolean; result_summary: string }
type SearchLink = { label: string; url: string }
type ItineraryDay = { day: number; title: string; items: string[] }
type Recommendation = { name: string; type: string; reason: string }
type ReviewNote = { category: string; note: string; severity: string }
type TripPlan = {
  summary: string
  agents: AgentRun[]
  tool_runs: ToolRunEntry[]
  flights: SearchLink[]
  hotels: SearchLink[]
  itinerary: ItineraryDay[]
  budget: Record<string, unknown>
  visa: string[]
  recommendations: Recommendation[]
  review?: ReviewNote[]
  clarifications?: string[]
  destination_info?: Record<string, unknown>
  llm_enabled?: boolean
}
type Trip = { id: string; origin: string; destination: string; start_date: string; end_date: string; created_at: string }

const API = 'http://localhost:8000'

/* ── SSE parser ──────────────────────────────────────────────────── */
function parseSSE(chunk: string): StreamEvent[] {
  const events: StreamEvent[] = []
  const blocks = chunk.split('\n\n')
  for (const block of blocks) {
    const lines = block.split('\n')
    let eventType = 'message'
    let dataStr = ''
    for (const line of lines) {
      if (line.startsWith('event: ')) eventType = line.slice(7).trim()
      else if (line.startsWith('data: ')) dataStr += line.slice(6)
    }
    if (dataStr) {
      try { events.push({ event: eventType, data: JSON.parse(dataStr) }) } catch { /* skip */ }
    }
  }
  return events
}

/* ── Main App ────────────────────────────────────────────────────── */
export default function App() {
  const [origin, setOrigin] = useState('New York')
  const [destination, setDestination] = useState('Paris')
  const [startDate, setStartDate] = useState('2026-07-10')
  const [endDate, setEndDate] = useState('2026-07-18')
  const [travelers, setTravelers] = useState(1)
  const [budgetUsd, setBudgetUsd] = useState(1500)
  const [interests, setInterests] = useState('sightseeing, food')

  const [events, setEvents] = useState<StreamEvent[]>([])
  const [plan, setPlan] = useState<TripPlan | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [trips, setTrips] = useState<Trip[]>([])

  const streamRef = useRef<HTMLDivElement>(null)

  // Load trip history on mount
  useEffect(() => { loadTrips() }, [])

  // Auto-scroll stream area
  useEffect(() => {
    streamRef.current?.scrollTo({ top: streamRef.current.scrollHeight, behavior: 'smooth' })
  }, [events, plan])

  async function loadTrips() {
    try {
      const res = await fetch(`${API}/trips`)
      if (res.ok) setTrips(await res.json())
    } catch { /* ignore */ }
  }

  /* ── Streaming plan request ────────────────────────────────────── */
  async function handlePlan() {
    setLoading(true)
    setError('')
    setEvents([])
    setPlan(null)

    try {
      const res = await fetch(`${API}/trip/plan/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          origin, destination,
          start_date: startDate, end_date: endDate,
          travelers, budget_usd: budgetUsd,
          interests: interests.split(',').map(s => s.trim()).filter(Boolean),
        }),
      })

      if (!res.ok || !res.body) {
        const body = await res.json().catch(() => null)
        throw new Error(body?.detail || `Request failed (${res.status})`)
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // Parse complete SSE blocks
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''

        for (const part of parts) {
          const parsed = parseSSE(part + '\n\n')
          for (const evt of parsed) {
            if (evt.event === 'plan_ready') {
              setPlan(evt.data as unknown as TripPlan)
            } else if (evt.event === 'error') {
              setError(String(evt.data.error || 'Unknown error'))
            } else {
              setEvents(prev => [...prev, evt])
            }
          }
        }
      }

      // Parse any remaining buffer
      if (buffer.trim()) {
        const parsed = parseSSE(buffer + '\n\n')
        for (const evt of parsed) {
          if (evt.event === 'plan_ready') setPlan(evt.data as unknown as TripPlan)
          else setEvents(prev => [...prev, evt])
        }
      }

      loadTrips()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  /* ── Render ────────────────────────────────────────────────────── */
  return (
    <div className="app-layout">
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <div className="logo-icon">✈</div>
            TravelAI
          </div>
        </div>
        <nav className="sidebar-nav">
          <div className="sidebar-section">
            <div className="sidebar-section-title">Actions</div>
            <button className="sidebar-btn active" onClick={() => { setEvents([]); setPlan(null); setError('') }}>
              <span className="btn-icon">➕</span> New Trip
            </button>
          </div>
          <div className="sidebar-section">
            <div className="sidebar-section-title">Recent Trips</div>
            {trips.length === 0 && <div style={{ padding: '8px 12px', fontSize: 12, color: 'var(--text-muted)' }}>No trips yet</div>}
            {trips.map(t => (
              <button className="trip-item" key={t.id} title={`${t.origin} → ${t.destination}`}>
                <span className="trip-route">{t.origin} → {t.destination}</span>
                <span className="trip-date">{t.start_date} · {t.end_date}</span>
              </button>
            ))}
          </div>
        </nav>
      </aside>

      {/* ── Main ── */}
      <div className="main-content">
        {/* Top bar */}
        <header className="top-bar">
          <h2>
            {loading && <span className="status-dot" />}
            {loading ? 'Agents working...' : plan ? `${destination} Trip Plan` : 'Multi-Agent Trip Planner'}
          </h2>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {events.length > 0 ? `${events.length} events` : 'Ready'}
          </span>
        </header>

        {/* Stream / Results area */}
        <div className="stream-area" ref={streamRef}>
          {/* Empty state */}
          {!loading && events.length === 0 && !plan && !error && (
            <div className="empty-state">
              <div className="empty-icon">🌍</div>
              <div className="empty-title">Plan your perfect trip</div>
              <div className="empty-sub">
                Fill in your trip details below and watch as specialized AI agents
                research, plan, budget, and review your trip in real-time.
              </div>
            </div>
          )}

          {/* Streaming events (Grouped into Agent Blocks) */}
          <div className="events-container">
            {processEvents(events).map((group, i) => {
              if (group.type === 'phase') return <PhaseBlock key={i} event={group.event} />
              if (group.type === 'agent') return <AgentRunBlock key={i} group={group} />
              if (group.type === 'generic' || group.type === 'log') return <EventCard key={i} event={group.event} />
              return null;
            })}
          </div>

          {/* Loading indicator */}
          {loading && events.length === 0 && (
            <div className="event-card" style={{ textAlign: 'center' }}>
              <span className="spinner" /> <span style={{ marginLeft: 8, fontSize: 13, color: 'var(--text-secondary)' }}>Initializing agents...</span>
            </div>
          )}

          {/* Error */}
          {error && <div className="error-banner"><span>⚠</span> {error}</div>}

          {/* Final plan */}
          {plan && <PlanResult plan={plan} />}
        </div>

        {/* Input bar */}
        <div className="input-bar">
          <div className="input-form">
            <div className="input-fields">
              <div className="field">
                <label>Origin</label>
                <input value={origin} onChange={e => setOrigin(e.target.value)} placeholder="New York" />
              </div>
              <div className="field">
                <label>Destination</label>
                <input value={destination} onChange={e => setDestination(e.target.value)} placeholder="Paris" />
              </div>
              <div className="field">
                <label>Start</label>
                <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} />
              </div>
              <div className="field">
                <label>End</label>
                <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} />
              </div>
              <div className="field">
                <label>Travelers</label>
                <input type="number" min={1} max={20} value={travelers} onChange={e => setTravelers(Number(e.target.value))} />
              </div>
              <div className="field">
                <label>Budget $</label>
                <input type="number" min={0} value={budgetUsd} onChange={e => setBudgetUsd(Number(e.target.value))} />
              </div>
              <div className="field wide">
                <label>Interests</label>
                <input value={interests} onChange={e => setInterests(e.target.value)} placeholder="sightseeing, food, art" />
              </div>
            </div>
            <button className="btn-send" onClick={handlePlan} disabled={loading}>
              {loading ? <><span className="spinner" /> Planning...</> : '🚀 Plan Trip'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ── Grouping Logic ──────────────────────────────────────────────── */
function processEvents(events: StreamEvent[]) {
  const groups: any[] = [];
  let currentGroup: any = null;

  for (const evt of events) {
    if (evt.event === 'planning_start' || evt.event === 'phase_start') {
      groups.push({ type: 'phase', event: evt });
    } else if (evt.event === 'agent_start') {
      // If there's an unclosed group, just push it (shouldn't happen usually unless parallel, but if parallel, this naive approach just interleaves them. A better approach groups by agent name, but backend streams sequentially)
      if (currentGroup) groups.push(currentGroup);
      currentGroup = { type: 'agent', startEvent: evt, logs: [], doneEvent: null };
    } else if (evt.event === 'tool_call' || evt.event === 'tool_result' || evt.event === 'agent_warning') {
      if (currentGroup) currentGroup.logs.push(evt);
      else groups.push({ type: 'log', event: evt });
    } else if (evt.event === 'agent_done') {
      if (currentGroup) {
        currentGroup.doneEvent = evt;
        groups.push(currentGroup);
        currentGroup = null;
      } else {
        groups.push({ type: 'log', event: evt });
      }
    } else {
      groups.push({ type: 'generic', event: evt });
    }
  }
  if (currentGroup) groups.push(currentGroup);
  return groups;
}

/* ── Phase Block ─────────────────────────────────────────────────── */
function PhaseBlock({ event: evt }: { event: StreamEvent }) {
  const { event, data } = evt;
  if (event === 'planning_start') {
    return (
      <div className="phase-block">
        <div className="phase-icon">🚀</div>
        <div className="phase-text">{String(data.message || 'Starting...')}</div>
      </div>
    )
  }
  const agents = (data.agents as string[]) || []
  return (
    <div className="phase-block">
      <div className="phase-icon">📋</div>
      <div className="phase-text">Phase {String(data.phase)}: {String(data.label || '')}</div>
      <div className="phase-agents">
        {agents.map(a => <span className="agent-tag" key={a}>{a}</span>)}
      </div>
    </div>
  )
}

/* ── Agent Run Block (IDE-like) ──────────────────────────────────── */
function AgentRunBlock({ group }: { group: any }) {
  const [expanded, setExpanded] = useState(true);
  const startData = group.startEvent.data;
  const isDone = !!group.doneEvent;
  const doneData = group.doneEvent?.data;

  return (
    <div className={`agent-ide-block ${isDone ? 'done' : 'running'}`}>
      <div className="agent-ide-header" onClick={() => setExpanded(!expanded)}>
        <div className="ide-header-left">
          <div className="ide-icon">{isDone ? '⚡' : <span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />}</div>
          <div className="ide-agent-name">{String(startData.agent)}</div>
          <div className="ide-status-badge">{isDone ? 'Completed' : 'Working'}</div>
        </div>
        <div className="ide-header-right">
          <button className="ide-toggle">{expanded ? '▲' : '▼'}</button>
        </div>
      </div>

      {expanded && (
        <div className="agent-ide-body">
          <div className="ide-purpose">Target: {String(startData.purpose || '')}</div>

          {group.logs.length > 0 && (
            <div className="ide-terminal">
              <div className="term-header">
                <span className="term-dot red"></span>
                <span className="term-dot yellow"></span>
                <span className="term-dot green"></span>
                <span className="term-title">bash — {String(startData.agent).toLowerCase().replace(/\s+/g, '-')}-agent</span>
              </div>
              <div className="term-content">
                {group.logs.map((log: StreamEvent, i: number) => {
                  if (log.event === 'tool_call') {
                    return <div key={i} className="term-line cmd"><span className="prompt">$</span> {String(log.data.tool)}()</div>
                  }
                  if (log.event === 'tool_result') {
                    const ok = Boolean(log.data.ok);
                    return <div key={i} className={`term-line out ${ok ? 'ok' : 'err'}`}>↳ {String(log.data.summary || '').slice(0, 180)}</div>
                  }
                  if (log.event === 'agent_warning') {
                    return <div key={i} className="term-line warn">⚠ {String(log.data.message || '')}</div>
                  }
                  return null;
                })}
              </div>
            </div>
          )}

          {isDone && (
            <div className="ide-summary">
              <div className="summary-label">Result Summary</div>
              <div className="summary-text">{String(doneData.summary || '')}</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/* ── Fallback Event Card Component ───────────────────────────────── */
function EventCard({ event: evt }: { event: StreamEvent }) {
  const { event, data } = evt
  return (
    <div className="event-card fallback">
      <div className="event-header">
        <div className="event-icon">📡</div>
        <span className="event-label">{event}</span>
      </div>
      <div className="event-body">{JSON.stringify(data).slice(0, 200)}</div>
    </div>
  )
}

/* ── Plan Result Component ───────────────────────────────────────── */
function PlanResult({ plan }: { plan: TripPlan }) {
  const destInfo = plan.destination_info || {}
  const wiki = destInfo.wikipedia as { summary?: string; url?: string } | undefined
  const weatherSummary = String(destInfo.weather_summary || '')

  return (
    <div className="plan-result">
      <div className="plan-summary">{plan.summary}</div>

      {plan.llm_enabled === false && (
        <div className="error-banner" style={{ marginBottom: 12 }}>
          <span>⚠</span> Some agents ran in fallback mode (LLM unavailable). Check GROQ_API_KEY and GROQ_MODEL.
        </div>
      )}

      {(wiki?.summary || weatherSummary) && (
        <>
          <div className="section-title">🌍 Live Destination Data</div>
          {wiki?.summary && <p style={{ fontSize: 14, lineHeight: 1.5, marginBottom: 8 }}>{wiki.summary}</p>}
          {weatherSummary && <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>🌤 {weatherSummary}</p>}
        </>
      )}

      {/* Agents */}
      {plan.agents.length > 0 && (
        <>
          <div className="section-title">🤖 Agent Execution</div>
          <div className="agent-grid">
            {plan.agents.map(a => (
              <div className="agent-chip" key={a.name}>
                <div className={`agent-dot ${a.status === 'ok' || !a.status ? 'ok' : 'err'}`} />
                <div>
                  <div className="agent-name">{a.name}</div>
                  <div className="agent-summary">{a.summary}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Flights & Hotels */}
      <div className="link-columns" style={{ marginTop: 16 }}>
        <div className="link-card">
          <h3>✈️ Flights</h3>
          {plan.flights.map(f => (
            <a key={f.url} className="search-link" href={f.url} target="_blank" rel="noreferrer">{f.label} ↗</a>
          ))}
        </div>
        <div className="link-card">
          <h3>🏨 Hotels</h3>
          {plan.hotels.map(h => (
            <a key={h.url} className="search-link" href={h.url} target="_blank" rel="noreferrer">{h.label} ↗</a>
          ))}
        </div>
      </div>

      {/* Itinerary */}
      {plan.itinerary.length > 0 && (
        <>
          <div className="section-title">📅 Itinerary</div>
          <div className="itinerary-grid">
            {plan.itinerary.map(day => (
              <article className="day-card" key={day.day}>
                <div className="day-badge">Day {day.day}</div>
                <div className="day-title">{day.title}</div>
                <ul className="day-items">{day.items.map((item, i) => <li key={i}>{item}</li>)}</ul>
              </article>
            ))}
          </div>
        </>
      )}

      {/* Budget */}
      <div className="section-title">💰 Budget Estimate</div>
      <div className="budget-grid">
        <div className="budget-stat"><div className="label">Target</div><div className="value accent">${String(plan.budget.target || 0)}</div></div>
        <div className="budget-stat"><div className="label">Estimated</div><div className="value">${String(plan.budget.estimated_total || 0)}</div></div>
        {plan.budget.per_person_per_day !== undefined && (
          <div className="budget-stat"><div className="label">Per Person/Day</div><div className="value">${String(plan.budget.per_person_per_day)}</div></div>
        )}
        {Object.entries((plan.budget.breakdown as Record<string, number>) || {}).map(([k, v]) => (
          <div className="budget-stat" key={k}><div className="label">{k}</div><div className="value">${v}/day</div></div>
        ))}
      </div>

      {/* Visa */}
      {plan.visa.length > 0 && (
        <>
          <div className="section-title">🛂 Visa & Entry</div>
          <ul className="visa-list">{plan.visa.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </>
      )}

      {/* Recommendations */}
      {plan.recommendations.length > 0 && (
        <>
          <div className="section-title">⭐ Recommendations</div>
          <div className="rec-grid">
            {plan.recommendations.map(r => (
              <div className="rec-card" key={r.name}>
                <div className="rec-type">{r.type}</div>
                <div className="rec-name">{r.name}</div>
                <div className="rec-reason">{r.reason}</div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Review (Phase 4) */}
      {plan.review && plan.review.length > 0 && (
        <>
          <div className="section-title">🔍 Plan Review</div>
          <div className="review-grid">
            {plan.review.map((r, i) => (
              <div className={`review-note ${r.severity}`} key={i}>
                <span className="review-icon">{r.severity === 'warning' ? '⚠️' : r.severity === 'suggestion' ? '💡' : 'ℹ️'}</span>
                <span className="review-text">{r.note}</span>
                <span className="review-category">{r.category}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Clarifications (human-in-the-loop) */}
      {plan.clarifications && plan.clarifications.length > 0 && (
        <>
          <div className="section-title">❓ Clarification Questions</div>
          <div className="clarification-list">
            {plan.clarifications.map((q, i) => (
              <div className="clarification-item" key={i}>💬 {q}</div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
