import React, { useState, useCallback, useMemo } from 'react'
import { HydraFlowProvider, useHydraFlow } from './context/HydraFlowContext'
import { Header } from './components/Header'
import { HumanInputBanner } from './components/HumanInputBanner'
import { HITLTable } from './components/HITLTable'
import { SystemPanel } from './components/SystemPanel'
import { OutcomesPanel } from './components/IssueHistoryPanel'
import { StreamView } from './components/StreamView'
import { SessionSidebar } from './components/SessionSidebar'
import { theme } from './theme'

const TABS = ['issues', 'hitl', 'outcomes', 'system']

const TAB_LABELS = {
  issues: 'Work Stream',
  outcomes: 'Outcomes',
  hitl: 'HITL',
  system: 'System',
}

function SystemAlertBanner({ alert }) {
  if (!alert) return null
  return (
    <div style={styles.alertBanner}>
      <span style={styles.alertIcon}>!</span>
      <span>{alert.message}</span>
      {alert.source && <span style={styles.alertSource}>Source: {alert.source}</span>}
    </div>
  )
}

function SessionFilterBanner({ session, onClear, liveStats }) {
  if (!session) return null
  const d = new Date(session.started_at)
  const startDate = Number.isNaN(d.getTime()) ? '-' : d.toLocaleString()
  const succeeded = liveStats?.issues_succeeded ?? session.issues_succeeded ?? 0
  const failed = liveStats?.issues_failed ?? session.issues_failed ?? 0
  const issueCount = liveStats?.issues_processed_count ?? (session.issues_processed?.length ?? 0)
  return (
    <div style={styles.sessionBanner}>
      <span style={session.status === 'active' ? styles.sessionDotActive : styles.sessionDotCompleted} />
      <span style={styles.sessionBannerText}>
        Session from {startDate}
      </span>
      <span style={styles.sessionBannerMeta}>
        {issueCount} {issueCount === 1 ? 'issue' : 'issues'}
        {succeeded > 0 && ` · ${succeeded} passed`}
        {failed > 0 && ` · ${failed} failed`}
      </span>
      <span role="button" tabIndex={0} onClick={onClear} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClear() } }} style={styles.sessionBannerClear}>Clear filter</span>
    </div>
  )
}

function AppContent() {
  const {
    connected, orchestratorStatus, workers, prs,
    hitlItems, humanInputRequests, submitHumanInput, refreshHitl,
    backgroundWorkers, systemAlert, intents, toggleBgWorker, updateBgWorkerInterval,
    selectedSession, selectSession,
    currentSessionId,
    stageStatus,
    requestChanges,
  } = useHydraFlow()
  const [activeTab, setActiveTab] = useState('issues')
  const [expandedStages, setExpandedStages] = useState({})


  const handleRequestChanges = useCallback(async (issueNumber, feedback, stage) => {
    const ok = await requestChanges(issueNumber, feedback, stage)
    if (ok) {
      setActiveTab('hitl')
    }
    return ok
  }, [requestChanges])

  const selectedSessionLiveStats = useMemo(() => {
    if (!selectedSession || selectedSession.status !== 'active') return null
    if (selectedSession.id !== currentSessionId) return null
    const done = stageStatus?.workload?.done ?? 0
    const failed = stageStatus?.workload?.failed ?? 0
    return {
      issues_processed_count: done + failed,
      issues_succeeded: done,
      issues_failed: failed,
    }
  }, [selectedSession, currentSessionId, stageStatus])

  return (
    <div style={styles.layout}>
      <Header
        connected={connected}
        orchestratorStatus={orchestratorStatus}
      />

      <div style={styles.body}>
      <SessionSidebar />

      <div style={styles.main}>
        <SessionFilterBanner
          session={selectedSession}
          onClear={() => selectSession(null)}
          liveStats={selectedSessionLiveStats}
        />
        <SystemAlertBanner alert={systemAlert} />
        <HumanInputBanner requests={humanInputRequests} onSubmit={submitHumanInput} />

        <div style={styles.tabs} data-testid="main-tabs" role="tablist">
          {TABS.map((tab) => (
            <div
              key={tab}
              role="tab"
              tabIndex={0}
              aria-selected={activeTab === tab}
              onClick={() => setActiveTab(tab)}
              onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setActiveTab(tab) } }}
              style={activeTab === tab ? tabActiveStyle : tabInactiveStyle}
            >
              {tab === 'hitl' ? (
                <>HITL{hitlItems?.length > 0 && <span style={hitlBadgeStyle}>{hitlItems.length}</span>}</>
              ) : TAB_LABELS[tab]}
            </div>
          ))}
        </div>

        <div style={styles.tabContent}>
          {activeTab === 'issues' && (
            <StreamView
              intents={intents}
              expandedStages={expandedStages}
              onToggleStage={setExpandedStages}
              onRequestChanges={handleRequestChanges}
            />
          )}
          {activeTab === 'outcomes' && <OutcomesPanel />}
          {activeTab === 'hitl' && <HITLTable items={hitlItems} onRefresh={refreshHitl} />}
          {activeTab === 'system' && (
            <SystemPanel
              backgroundWorkers={backgroundWorkers}
              onToggleBgWorker={toggleBgWorker}
              onUpdateInterval={updateBgWorkerInterval}
            />
          )}
        </div>
      </div>

      </div>
    </div>
  )
}

export default function App() {
  return (
    <HydraFlowProvider>
      <AppContent />
    </HydraFlowProvider>
  )
}

const styles = {
  layout: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    minWidth: '1080px',
  },
  body: {
    display: 'flex',
    flex: 1,
    overflow: 'hidden',
  },
  main: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  tabs: {
    display: 'flex',
    borderBottom: `1px solid ${theme.border}`,
    background: theme.surface,
  },
  tab: {
    padding: '10px 20px',
    fontSize: 12,
    fontWeight: 600,
    color: theme.textMuted,
    cursor: 'pointer',
    borderBottom: '2px solid transparent',
    transition: 'all 0.15s',
  },
  tabActive: {
    color: theme.accent,
    borderBottom: `2px solid ${theme.accent}`,
  },
  tabContent: {
    flex: 1,
    minWidth: 0,
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
  },
  hitlBadge: {
    background: theme.red,
    color: theme.white,
    fontSize: 10,
    fontWeight: 700,
    borderRadius: 10,
    padding: '1px 6px',
    marginLeft: 6,
  },
  alertBanner: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '8px 16px',
    background: theme.redSubtle,
    borderBottom: `2px solid ${theme.red}`,
    color: theme.red,
    fontSize: 13,
    fontWeight: 600,
  },
  alertIcon: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 20,
    height: 20,
    borderRadius: '50%',
    background: theme.red,
    color: theme.white,
    fontSize: 12,
    fontWeight: 700,
    flexShrink: 0,
  },
  alertSource: {
    marginLeft: 'auto',
    fontSize: 11,
    fontWeight: 400,
    opacity: 0.8,
  },
  sessionBanner: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '8px 16px',
    background: theme.accentSubtle,
    borderBottom: `1px solid ${theme.accent}`,
    fontSize: 12,
  },
  sessionDotActive: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: theme.green,
    flexShrink: 0,
  },
  sessionDotCompleted: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: theme.textMuted,
    flexShrink: 0,
  },
  sessionBannerText: {
    fontWeight: 600,
    color: theme.accent,
  },
  sessionBannerMeta: {
    color: theme.textMuted,
    fontSize: 11,
  },
  sessionBannerClear: {
    marginLeft: 'auto',
    color: theme.accent,
    cursor: 'pointer',
    fontSize: 11,
    fontWeight: 600,
  },
}

// Pre-computed tab style variants (avoids object spread in .map())
export const tabInactiveStyle = styles.tab
export const tabActiveStyle = { ...styles.tab, ...styles.tabActive }
export const hitlBadgeStyle = styles.hitlBadge
