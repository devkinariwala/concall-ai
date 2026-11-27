import { useEffect, useState, useCallback } from "react";
import "./App.css";

const API_BASE = "http://localhost:8000";
const WS_URL = "ws://localhost:8000/ws/summaries";

function ClaimList({
  items,
  emptyText = "Not disclosed in the extracted transcript.",
}) {
  if (!items || items.length === 0) {
    return <p className="empty-note">{emptyText}</p>;
  }

  return (
    <ul className="claim-list">
      {items.map((item, idx) => (
        <li key={idx} className="claim-card">
          <div className="claim-header">
            <span className="claim-text">{item.claim}</span>
            <span className="page-badge">Page {item.page}</span>
          </div>
          {item.speaker && item.speaker !== "Not identified" && (
            <div className="speaker-meta">Speaker: {item.speaker}</div>
          )}
          <blockquote className="quote-box">"{item.quote}"</blockquote>
        </li>
      ))}
    </ul>
  );
}

export default function App() {
  const [companies, setCompanies] = useState([]);
  const [summaries, setSummaries] = useState([]);
  const [selectedSymbol, setSelectedSymbol] = useState("ALL");
  const [selectedSummaryId, setSelectedSummaryId] = useState(null);
  const [activeSummary, setActiveSummary] = useState(null);
  const [status, setStatus] = useState(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(false);

  const pushNotification = useCallback((message, type = "info") => {
    const id = Date.now() + Math.random();
    setNotifications((prev) =>
      [
        { id, message, type, time: new Date().toLocaleTimeString() },
        ...prev,
      ].slice(0, 5),
    );
  }, []);

  const fetchData = useCallback(async () => {
    try {
      const [compRes, sumRes, statRes] = await Promise.all([
        fetch(`${API_BASE}/api/companies`),
        fetch(`${API_BASE}/api/summaries`),
        fetch(`${API_BASE}/api/status`),
      ]);
      const compData = await compRes.json();
      const sumData = await sumRes.json();
      const statData = await statRes.json();

      setCompanies(compData.companies || []);
      setSummaries(sumData.summaries || []);
      setStatus(statData);
    } catch (err) {
      pushNotification(`Backend connection failed: ${err.message}`, "error");
    }
  }, [pushNotification]);

  const fetchSummaryDetail = useCallback(
    async (summaryId) => {
      if (!summaryId) return;
      setLoading(true);
      try {
        const res = await fetch(`${API_BASE}/api/summaries/${summaryId}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setActiveSummary(data);
      } catch (err) {
        pushNotification(`Failed to load summary: ${err.message}`, "error");
      } finally {
        setLoading(false);
      }
    },
    [pushNotification],
  );

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (selectedSummaryId) {
      fetchSummaryDetail(selectedSummaryId);
    } else {
      setActiveSummary(null);
    }
  }, [selectedSummaryId, fetchSummaryDetail]);

  useEffect(() => {
    let ws;
    let reconnectTimer;

    const connect = () => {
      ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        setWsConnected(true);
        pushNotification("Connected to real-time WebSocket feed", "success");
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.event === "summary_completed") {
            pushNotification(
              `New summary ready: ${msg.data.company} (${msg.data.quarter})`,
              "success",
            );
            fetchData();
            if (msg.data.id) setSelectedSummaryId(msg.data.id);
          } else if (msg.event === "pipeline_started") {
            pushNotification(`Pipeline started for ${msg.data.symbol}`, "info");
            fetchData();
          } else if (msg.event === "processing_failed") {
            pushNotification(`Pipeline error: ${msg.data.error}`, "error");
            fetchData();
          }
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        setWsConnected(false);
        reconnectTimer = setTimeout(connect, 5000);
      };
    };

    connect();
    return () => {
      clearTimeout(reconnectTimer);
      if (ws) ws.close();
    };
  }, [fetchData, pushNotification]);

  const handleTriggerPipeline = async () => {
    try {
      const query = selectedSymbol !== "ALL" ? `?symbol=${selectedSymbol}` : "";
      const res = await fetch(`${API_BASE}/api/pipeline/trigger${query}`, {
        method: "POST",
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to trigger");
      pushNotification(data.message, "info");
      fetchData();
    } catch (err) {
      pushNotification(err.message, "error");
    }
  };

  const filteredSummaries =
    selectedSymbol === "ALL"
      ? summaries
      : summaries.filter((s) => s.symbol === selectedSymbol);

  useEffect(() => {
    if (filteredSummaries.length === 0) {
      setSelectedSummaryId(null);
      setActiveSummary(null);
      return;
    }

    const stillVisible = filteredSummaries.some(
      (s) => s.id === selectedSummaryId,
    );
    if (!stillVisible) {
      setSelectedSummaryId(filteredSummaries[0].id);
    }
  }, [selectedSymbol, summaries, selectedSummaryId]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <h1>ConcallAI</h1>
          <p className="subtitle">
            Real-Time Indian Earnings Call Intelligence
          </p>
        </div>
        <div className="topbar-controls">
          <span className={`ws-pill ${wsConnected ? "online" : "offline"}`}>
            {wsConnected ? "● Live Feed Connected" : "○ Feed Disconnected"}
          </span>
          <span className="status-pill">
            Status: <strong>{status?.last_run_status || "unknown"}</strong>
          </span>
          <button
            className="trigger-btn"
            onClick={handleTriggerPipeline}
            disabled={status?.is_running}
          >
            {status?.is_running ? "Processing..." : "Run Pipeline"}
          </button>
        </div>
      </header>

      {notifications.length > 0 && (
        <div className="notification-bar">
          {notifications[0].time} — <strong>{notifications[0].message}</strong>
        </div>
      )}

      <div className="layout">
        <aside className="sidebar">
          <h3>Companies</h3>
          <div className="company-filter">
            <button
              className={selectedSymbol === "ALL" ? "active" : ""}
              onClick={() => setSelectedSymbol("ALL")}
            >
              All Companies ({summaries.length})
            </button>
            {companies.map((c) => (
              <button
                key={c.symbol}
                className={selectedSymbol === c.symbol ? "active" : ""}
                onClick={() => setSelectedSymbol(c.symbol)}
              >
                <span>{c.symbol}</span>
                <span className="count-badge">{c.summary_count}</span>
              </button>
            ))}
          </div>

          <h3>Processed Calls</h3>
          <div className="summary-list">
            {filteredSummaries.length === 0 ? (
              <p className="empty-note">No summaries available.</p>
            ) : (
              filteredSummaries.map((s) => (
                <div
                  key={s.id}
                  className={`summary-item ${selectedSummaryId === s.id ? "selected" : ""}`}
                  onClick={() => setSelectedSummaryId(s.id)}
                >
                  <div className="summary-item-title">{s.company}</div>
                  <div className="summary-item-meta">
                    {s.quarter} • {s.call_date}
                  </div>
                  <div className="summary-item-counts">
                    TL;DR: {s.tldr_count} | Q&A: {s.qa_count} | Risks:{" "}
                    {s.risk_count}
                  </div>
                </div>
              ))
            )}
          </div>
        </aside>

        <main className="content">
          {loading ? (
            <p className="empty-note">Loading summary...</p>
          ) : !activeSummary ? (
            <p className="empty-note">
              Select a processed earnings call from the left panel.
            </p>
          ) : (
            <div className="report">
              <div className="report-header">
                <div>
                  <h2>
                    {activeSummary.company} ({activeSummary.symbol})
                  </h2>
                  <p className="report-meta">
                    <strong>Quarter:</strong> {activeSummary.quarter}{" "}
                    &nbsp;|&nbsp; <strong>Call Date:</strong>{" "}
                    {activeSummary.call_date}
                  </p>
                </div>
                <a
                  className="md-link"
                  href={`${API_BASE}/api/summaries/${selectedSummaryId}/markdown`}
                  target="_blank"
                  rel="noreferrer"
                >
                  View Raw Markdown
                </a>
              </div>

              <section>
                <h3>Executive TL;DR</h3>
                <ClaimList items={activeSummary.tldr} />
              </section>

              <section>
                <h3>Financial Performance & Key Metrics</h3>
                <ClaimList items={activeSummary.key_metrics} />
              </section>

              <section>
                <h3>Management Commentary</h3>
                <ClaimList items={activeSummary.management_commentary} />
              </section>

              <section>
                <h3>Segment-wise Performance</h3>
                <ClaimList items={activeSummary.segment_performance} />
              </section>

              <section>
                <h3>Management Guidance & Outlook</h3>
                <ClaimList items={activeSummary.guidance_outlook} />
              </section>

              <section>
                <h3>Strategic Commitments</h3>
                <ClaimList items={activeSummary.strategic_commitments} />
              </section>

              <section>
                <h3>Notable Analyst Q&A</h3>
                {!activeSummary.notable_qa?.length ? (
                  <p className="empty-note">
                    Not disclosed in the extracted transcript.
                  </p>
                ) : (
                  <div className="qa-list">
                    {activeSummary.notable_qa.map((qa, idx) => (
                      <div key={idx} className="qa-card">
                        <div className="claim-header">
                          <strong>
                            {qa.analyst}
                            {qa.firm && qa.firm !== "Not identified"
                              ? ` (${qa.firm})`
                              : ""}
                          </strong>
                          <span className="page-badge">Page {qa.page}</span>
                        </div>
                        <p>
                          <strong>Q:</strong> {qa.question}
                        </p>
                        <p>
                          <strong>A:</strong> {qa.answer}
                        </p>
                        {qa.supporting_quotes?.map((q, qIdx) => (
                          <blockquote key={qIdx} className="quote-box">
                            "{q}"
                          </blockquote>
                        ))}
                      </div>
                    ))}
                  </div>
                )}
              </section>

              <section>
                <h3>Risks & Uncertainties</h3>
                {!activeSummary.risks?.length ? (
                  <p className="empty-note">
                    Not disclosed in the extracted transcript.
                  </p>
                ) : (
                  <div className="risk-list">
                    {activeSummary.risks.map((r, idx) => (
                      <div key={idx} className="risk-card">
                        <div className="claim-header">
                          <div className="risk-tags">
                            <span className="tag cat">
                              {r.risk_category.replaceAll("_", " ")}
                            </span>
                            <span className="tag src">
                              {r.source_type.replaceAll("_", " ")}
                            </span>
                          </div>
                          <span className="page-badge">Page {r.page}</span>
                        </div>
                        <p className="claim-text">{r.risk}</p>
                        <blockquote className="quote-box">
                          "{r.quote}"
                        </blockquote>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              {activeSummary.limitations?.length > 0 && (
                <section>
                  <h3>Limitations & Validation Notes</h3>
                  <ul className="limitations-list">
                    {activeSummary.limitations.map((lim, idx) => (
                      <li key={idx}>{lim}</li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
