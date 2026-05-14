import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Activity, AlertTriangle, RefreshCw, Search, TreePine, TrendingDown, TrendingUp, X } from 'lucide-react'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import tozsdeMark from './assets/brand/tozsde-ai-mark.svg'
import './styles.css'

const API = 'http://127.0.0.1:8000/api'
const CATEGORY_PRIORITY = {
  'strong buy': 5,
  'strong sell': 5,
  buy: 4,
  sell: 4,
  hold: 1,
}

function App() {
  const [rankings, setRankings] = useState([])
  const [report, setReport] = useState(null)
  const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState(null)
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState('actions')
  const [sortMode, setSortMode] = useState('conviction')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [sourceStatus, setSourceStatus] = useState(null)
  const [issuesOpen, setIssuesOpen] = useState(false)

  useEffect(() => {
    loadAll()
  }, [])

  useEffect(() => {
    if (!selected) return
    fetch(`${API}/stocks/${selected}`)
      .then((res) => res.json())
      .then(setDetail)
      .catch(() => setDetail(null))
  }, [selected])

  async function loadAll() {
    setLoading(true)
    const [rankingRes, reportRes, statusRes] = await Promise.all([
      fetch(`${API}/rankings/latest`),
      fetch(`${API}/reports/latest`),
      fetch(`${API}/config/status`),
    ])
    const rankingData = await rankingRes.json()
    const reportData = await reportRes.json()
    const statusData = await statusRes.json()
    const sorted = sortByConviction(rankingData)
    setRankings(sorted)
    setReport(reportData)
    setSourceStatus(statusData)
    setSelected((current) => current || sorted[0]?.symbol || null)
    setLoading(false)
  }

  async function refreshNow() {
    setRefreshing(true)
    await fetch(`${API}/refresh`, { method: 'POST' })
    await loadAll()
    setRefreshing(false)
  }

  const issues = useMemo(() => systemIssues(sourceStatus, rankings), [sourceStatus, rankings])
  const counts = useMemo(() => countCategories(rankings), [rankings])
  const actionRows = useMemo(() => {
    const rows = rankings.filter((item) => item.category !== 'hold')
    return rows.length ? rows.slice(0, 12) : rankings.slice(0, 12)
  }, [rankings])
  const filtered = useMemo(() => {
    let rows = mode === 'actions' ? rankings.filter((item) => item.category !== 'hold') : mode === 'all' ? rankings : rankings.filter((item) => item.category === mode)
    rows = rows.filter((item) => `${item.symbol} ${item.name} ${item.sector}`.toLowerCase().includes(query.toLowerCase()))
    if (sortMode === 'score') rows = [...rows].sort((a, b) => b.score - a.score)
    return rows
  }, [rankings, query, mode, sortMode])

  return (
    <div className="app">
      <header className="hero">
        <div className="topline">
          <div className="brand">
            <div className="logo-mark"><img src={tozsdeMark} alt="" /></div>
            <div>
              <p className="eyebrow">Személyes portfólió intelligence</p>
              <h1>Tőzsde AI</h1>
              <p className="subtitle">Profi döntési pult 100 kiemelt részvényre: a rendszer a legerősebb vételi és eladási jelzéseket emeli előre, a semleges hold papírokat külön figyelőlistán tartja.</p>
            </div>
          </div>
          <div className="header-actions">
            <button className={`health ${issues.length ? 'bad' : ''}`} onClick={() => setIssuesOpen(true)}>
              {issues.length ? <AlertTriangle size={17} /> : <TreePine size={24} />}
              {issues.length ? `${issues.length} biztos hiba` : <span className="health-tip">Nincs rendszerhiba, minden fő komponens működik.</span>}
            </button>
            <button className="refresh" onClick={refreshNow} disabled={refreshing}>
              <RefreshCw size={18} className={refreshing ? 'spin' : ''} />
              {refreshing ? 'Frissítés...' : 'Frissítés'}
            </button>
          </div>
        </div>
      </header>

      <main className="content">
        <section className="summary">
          <Metric label="Strong buy / Buy" value={(counts['strong buy'] || 0) + (counts.buy || 0)} icon={<TrendingUp size={20} />} tone="buy" />
          <Metric label="Sell / Strong sell" value={(counts.sell || 0) + (counts['strong sell'] || 0)} icon={<TrendingDown size={20} />} tone="sell" />
          <Metric label="Hold" value={counts.hold || 0} icon={<Activity size={20} />} tone="hold" />
          <Metric label="Tickerek" value={rankings.length} icon={<Search size={20} />} tone="neutral" />
        </section>

        <div className="section-head">
          <div>
            <h2>Akciólista</h2>
            <p>Azok a tickerek kerülnek ide, ahol a rendszer a legbátrabban eltér a semleges hold állapottól.</p>
          </div>
        </div>
        <section className="action-grid">
          {actionRows.map((item) => (
            <ActionCard key={item.symbol} item={item} active={selected === item.symbol} onSelect={setSelected} />
          ))}
        </section>

        <section className="workspace">
          <div className="ranking-panel">
            <div className="filters">
              <div className="search">
                <Search size={16} />
                <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Keresés ticker, név vagy szektor szerint" />
              </div>
              <select value={mode} onChange={(event) => setMode(event.target.value)}>
                <option value="actions">Akciók</option>
                <option value="all">Minden ticker</option>
                <option value="strong buy">Strong buy</option>
                <option value="buy">Buy</option>
                <option value="hold">Hold</option>
                <option value="sell">Sell</option>
                <option value="strong sell">Strong sell</option>
              </select>
              <select value={sortMode} onChange={(event) => setSortMode(event.target.value)}>
                <option value="conviction">Meggyőződés</option>
                <option value="score">Pontszám</option>
              </select>
            </div>
            {loading ? <p className="empty">Adatok betöltése...</p> : <RankingTable rows={filtered} selected={selected} onSelect={setSelected} />}
          </div>

          <aside className="detail-panel">
            {detail ? <StockDetail detail={detail} /> : <p className="empty">Válassz egy tickert.</p>}
          </aside>
        </section>

        <section className="report">
          <h2>Napi riport</h2>
          <pre>{report?.content || 'Még nincs riport.'}</pre>
        </section>
      </main>

      {issuesOpen && <IssueModal issues={issues} onClose={() => setIssuesOpen(false)} />}
    </div>
  )
}

function ActionCard({ item, active, onSelect }) {
  const summary = consensusText(item)
  return (
    <button className={`action-card ${active ? 'active' : ''}`} onClick={() => onSelect(item.symbol)}>
      <div className="card-top">
        <div>
          <strong className="card-symbol">{item.symbol}</strong>
          <span>{item.name}</span>
        </div>
      </div>
      <div className="card-analysis">
        <span className={`pill ${categoryClass(item.category)}`}>{item.category}</span>
        <h3>{decisionText(item.category)}</h3>
        <p>{summary}</p>
      </div>
      <div className="card-score">
        <Score value={item.score} />
        <span>pont</span>
      </div>
    </button>
  )
}

function IssueModal({ issues, onClose }) {
  return (
    <div className="modal" onClick={(event) => event.target.className === 'modal' && onClose()}>
      <div className="modal-card">
        <div className="modal-head">
          <div>
            <h2>Rendszerállapot</h2>
            <p>Csak biztos API- vagy rendszerhibát jelzünk. Bizonytalan hálózati választ nem minősítünk hibának.</p>
          </div>
          <button className="icon-button" onClick={onClose}><X size={18} /></button>
        </div>
        {issues.length ? issues.map((issue) => (
          <div key={`${issue.source}-${issue.title}`} className={`issue ${issue.severity}`}>
            <strong>{issue.title}</strong>
            <span>{issue.detail}</span>
          </div>
        )) : <p className="empty compact">Nincs biztos API- vagy rendszerhiba. A bizonytalan adatkimaradások csak az érintett tickereknél jelennek meg.</p>}
      </div>
    </div>
  )
}

function Metric({ label, value, icon, tone }) {
  return (
    <div className={`metric ${tone}`}>
      <div className="metric-icon">{icon}</div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  )
}

function RankingTable({ rows, selected, onSelect }) {
  if (!rows.length) return <p className="empty">Nincs találat.</p>
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Javaslat</th>
            <th>Ticker</th>
            <th>Név</th>
            <th>Pont</th>
            <th>AI-összkép</th>
            <th>Kockázat</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.symbol} className={selected === row.symbol ? 'active' : ''} onClick={() => onSelect(row.symbol)}>
              <td><span className={`pill ${categoryClass(row.category)}`}>{row.category}</span></td>
              <td className="symbol">{row.symbol}<span>{row.sector}</span></td>
              <td>{row.name}</td>
              <td><Score value={row.score} /></td>
              <td className="reason">{consensusText(row)}</td>
              <td className="reason">{row.risks?.[0]}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Score({ value }) {
  return <span className={value >= 65 ? 'score high' : value >= 40 ? 'score mid' : 'score low'}>{Number(value).toFixed(1)}</span>
}

function StockDetail({ detail }) {
  const ranking = detail.ranking
  const chartData = detail.prices.map((item) => ({ ...item, date: String(item.date).slice(5) }))
  const article = buildArticle(detail, ranking)
  return (
    <div>
      <div className="detail-head">
        <div>
          <p className="eyebrow">{detail.exchange} / {detail.sector}</p>
          <h2>{detail.symbol}</h2>
          <p>{detail.name}</p>
        </div>
        {ranking && <Score value={ranking.score} />}
      </div>

      {ranking && <><span className={`pill ${categoryClass(ranking.category)}`}>{ranking.category}</span><p className="decision">{decisionText(ranking.category)}</p></>}

      <div className="chart">
        <ResponsiveContainer width="100%" height={210}>
          <LineChart data={chartData}>
            <XAxis dataKey="date" minTickGap={28} />
            <YAxis domain={['dataMin', 'dataMax']} width={48} />
            <Tooltip />
            <Line type="monotone" dataKey="close" stroke="#2f6fed" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {ranking && (
        <>
          <div className="component-grid">
            {Object.entries(ranking.components || {}).map(([key, value]) => (
              <div key={key}>
                <span>{key}</span>
                <strong>{Number(value).toFixed(1)}</strong>
              </div>
            ))}
          </div>
          <section className="article">
            <h3>{article.title}</h3>
            <p>{article.lead}</p>
            <ul className="clean-list">
              {article.bullets.map((item) => <li key={item}>{item}</li>)}
            </ul>
          </section>
          <h3>Agent konszenzus</h3>
          <div className="agent-list">
            {(ranking.agent_debate || []).map((agent) => (
              <div key={agent.agent}>
                <strong>{agent.agent}</strong>
                <span>{agent.stance} · {Number(agent.score).toFixed(1)}</span>
                <p>{agent.thesis}</p>
              </div>
            ))}
          </div>
          <h3>Kockázatok és hiányzó adatok</h3>
          <ul className="clean-list">
            {(ranking.risks || []).map((risk) => <li key={risk}>{risk}</li>)}
            {(ranking.missing_data || []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </>
      )}

      <h3>Friss filingek</h3>
      <ul className="filings">
        {detail.filings.length ? detail.filings.map((filing) => (
          <li key={filing.accession_number}>
            <strong>{filing.form}</strong>
            <span>{String(filing.filing_date)}</span>
            {filing.report_url && <a href={filing.report_url} target="_blank" rel="noreferrer">SEC</a>}
          </li>
        )) : <li>Nincs friss filing adat.</li>}
      </ul>
    </div>
  )
}

function categoryClass(category) {
  return String(category).replaceAll('/', '-').replaceAll(' ', '-')
}

function decisionText(category) {
  if (category === 'strong buy' || category === 'buy') return 'Vételi oldalon vizsgálandó jelzés.'
  if (category === 'strong sell' || category === 'sell') return 'Felülvizsgálatra / csökkentésre jelölt pozíció.'
  return 'Nincs sürgős akció; figyelőlistán tartandó.'
}

function consensusText(item) {
  if (item.consensus_summary) return item.consensus_summary
  const components = item.components || {}
  const parts = [
    `Végső döntés: ${item.category}, ${Number(item.score || 0).toFixed(1)} pont.`,
    `Részpontok: momentum ${Number(components.momentum || 0).toFixed(1)}, értékeltség ${Number(components.valuation || 0).toFixed(1)}, kockázat ${Number(components.risk || 0).toFixed(1)}.`,
  ]
  if (item.risks?.[0]) parts.push(`Fő kockázat: ${item.risks[0]}`)
  return parts.join(' ')
}

function conviction(item) {
  return Math.abs(Number(item.score || 0) - 50)
}

function sortByConviction(items) {
  return [...items].sort((a, b) => {
    const priority = (CATEGORY_PRIORITY[b.category] || 0) - (CATEGORY_PRIORITY[a.category] || 0)
    if (priority) return priority
    return conviction(b) - conviction(a)
  })
}

function countCategories(items) {
  return items.reduce((acc, item) => {
    acc[item.category] = (acc[item.category] || 0) + 1
    return acc
  }, {})
}

function systemIssues(sourceStatus, rankings) {
  const issues = []
  if (!sourceStatus) return issues
  Object.entries(sourceStatus).forEach(([key, item]) => {
    if (!item.configured) {
      issues.push({
        severity: 'critical',
        source: key,
        title: `${key} nincs beállítva`,
        detail: item.fallback || 'A kapcsolódó adatforrás fallback módban fut.',
      })
    }
  })
  return issues
}

function buildArticle(detail, ranking) {
  if (!ranking) {
    return { title: `Napi elemzés: ${detail.symbol}`, lead: 'Ehhez a tickerhez még nincs friss rangsor.', bullets: [] }
  }
  return {
    title: `Napi elemzés: ${detail.symbol} - ${ranking.category}`,
    lead: `${detail.symbol} jelenlegi besorolása ${ranking.category}. A jegyzet a letárolt árfolyam-, filing-, célár- és score-adatokból készült, nem kitalált hírekből.`,
    bullets: [
      decisionText(ranking.category),
      ranking.reasons?.[1] || ranking.reasons?.[0] || 'Nincs külön indoklás.',
      ranking.risks?.[0] || 'Nincs kiugró kockázati jel.',
      (detail.filings || []).length ? `Friss SEC filingek száma: ${detail.filings.length}.` : 'Nincs friss filing adat.',
    ],
  }
}

createRoot(document.getElementById('root')).render(<App />)
