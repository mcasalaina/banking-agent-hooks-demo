import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  ArrowRight,
  Check,
  CircleAlert,
  Clock3,
  Play,
  RefreshCw,
  ShieldCheck,
  ShieldOff,
  ShieldX,
  WalletCards,
  X,
} from 'lucide-react'
import './App.css'

type Scenario = {
  scenario_id: string
  title: string
  summary: string
  amount: string
  beneficiary_id: string
  beneficiary_name: string
  prompt: string
}

type DemoEvent = {
  event_id: string
  type: string
  timestamp: string
  correlation_id: string | null
  origin: string
  [key: string]: unknown
}

type Transaction = {
  transaction_id: string
  amount_cents: number
  beneficiary_id: string
  beneficiary_name: string
  account_suffix: string
  status: string
}

type Ledger = {
  account_label: string
  balance_cents: number
  initial_balance_cents: number
  transactions: Transaction[]
}

type Approval = {
  status: string
  amount_cents: number | null
  beneficiary_id: string
  beneficiary_name: string
  account_suffix: string | null
  policy: string
  policy_version: string
  interception_point: string
  resolved_at?: string
}

type DemoState = {
  hooks_enabled: boolean
  scenario: Scenario | null
  run_status: 'idle' | 'running' | 'awaiting_approval' | 'completed' | 'error'
  correlation_id: string | null
  outcome:
    | 'completed'
    | 'awaiting_approval'
    | 'blocked'
    | 'service_declined'
    | 'error'
    | 'no_tool_invocation'
    | 'not_started'
  no_money_moved: boolean
  assistant_response: string | null
  error: { type: string; message: string } | null
  approval: Approval | null
  ledger: Ledger
  events: DemoEvent[]
}

type Health = {
  project_endpoint: string
  model: string
  runtime_ready: boolean
  missing_modules: string[]
  synthetic_data_only: boolean
}

type ApiError = Error & { status?: number }

const money = (cents: number | null | undefined) =>
  typeof cents === 'number'
    ? new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 2,
      }).format(cents / 100)
    : '—'

const clock = (value?: string) =>
  value
    ? new Intl.DateTimeFormat('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
      }).format(new Date(value))
    : '—'

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch (error) {
    if (init?.signal?.aborted) throw error
    throw new Error('Cannot reach the banking service. Reconnecting automatically; payment controls are disabled until it reconnects.')
  }
  const payload = (await response.json()) as T & { error?: string }
  if (!response.ok) {
    const error = new Error(payload.error ?? `Request failed (${response.status}).`) as ApiError
    error.status = response.status
    throw error
  }
  return payload
}

function lastEvent(events: DemoEvent[], type: string, point?: string) {
  return [...events]
    .reverse()
    .find(
      (event) =>
        event.type === type &&
        (!point || event.interception_point === point),
    )
}

function App() {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [selectedScenarioId, setSelectedScenarioId] = useState('routine')
  const [hooksEnabled, setHooksEnabled] = useState(true)
  const [state, setState] = useState<DemoState | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [errorMessage, setErrorMessage] = useState('')
  const [connectionError, setConnectionError] = useState('')
  const [busyAction, setBusyAction] = useState('')
  const stateRevision = useRef(0)

  useEffect(() => {
    const controller = new AbortController()
    let timer: number | undefined
    let initialized = false
    const poll = async () => {
      const revision = stateRevision.current
      try {
        const init = { signal: controller.signal }
        const [nextScenarios, nextState, nextHealth] = await Promise.all([
          requestJson<Scenario[]>('/api/scenarios', init),
          requestJson<DemoState>('/api/state', init),
          requestJson<Health>('/api/health', init),
        ])
        if (controller.signal.aborted) return
        setScenarios(nextScenarios)
        setHealth(nextHealth)
        if (revision === stateRevision.current) {
          setState(nextState)
          if (!initialized) {
            setSelectedScenarioId(nextState.scenario?.scenario_id ?? 'routine')
            setHooksEnabled(nextState.hooks_enabled)
            initialized = true
          }
        }
        setConnectionError('')
      } catch (error) {
        if (controller.signal.aborted) return
        setConnectionError(error instanceof Error ? error.message : 'The banking service could not be reached.')
      }
      if (!controller.signal.aborted) timer = window.setTimeout(() => void poll(), 500)
    }
    void poll()
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [])

  const selectedScenario = useMemo(
    () =>
      state?.scenario ??
      scenarios.find((scenario) => scenario.scenario_id === selectedScenarioId) ??
      null,
    [scenarios, selectedScenarioId, state?.scenario],
  )

  const events = state?.events ?? []
  const requestEvent = lastEvent(events, 'request_received')
  const proposalEvent = lastEvent(events, 'model_proposed_transfer')
  const hookEvent = lastEvent(events, 'hook_interception', 'pre_tool_call')
  const toolEvent = lastEvent(events, 'payment_tool_started')
  const receiptEvent = lastEvent(events, 'receipt_created')
  const approval = state?.approval
  const pendingApproval =
    state?.run_status === 'awaiting_approval' && state.approval?.status === 'pending'
  const isBusy = state?.run_status === 'running' || pendingApproval
  const connected = Boolean(state && health && !connectionError)
  const controlsDisabled = !connected || !health?.runtime_ready || isBusy || busyAction !== ''
  const displayHooksEnabled = state?.scenario ? state.hooks_enabled : hooksEnabled
  const scenarioHasRun = Boolean(requestEvent)
  const terminalStatus = state?.run_status === 'completed' || state?.run_status === 'error'

  const gateStatus = !displayHooksEnabled
    ? 'off'
    : pendingApproval
    ? 'pending'
    : hookEvent?.verdict === 'deny'
      ? 'blocked'
      : hookEvent?.verdict === 'allow'
        ? 'allowed'
        : state?.run_status === 'error'
          ? 'error'
          : 'ready'

  const gateLabel = {
    off: 'HOOKS OFF',
    pending: 'AWAITING APPROVAL',
    blocked: 'BLOCKED',
    allowed: 'ALLOWED',
    error: 'RUN ERROR',
    ready: 'READY',
  }[gateStatus]

  const gateReason =
    (!displayHooksEnabled && 'Tool calls go directly to the payment service.') ||
    (typeof hookEvent?.message === 'string' && hookEvent.message) ||
    (hookEvent?.reason === 'saved_beneficiary_within_limit'
      ? 'Saved beneficiary and amount are within the bank policy limits.'
      : typeof hookEvent?.reason === 'string' && hookEvent.reason) ||
    (pendingApproval
      ? 'This transfer is paused until a presenter approves or rejects it.'
      : gateStatus === 'ready'
        ? 'The bank policy hook runs before the payment tool.'
        : state?.error?.message) ||
    'The policy hook returned an explicit verdict.'

  const runScenario = async (scenarioId: string) => {
    setSelectedScenarioId(scenarioId)
    setBusyAction('run')
    setErrorMessage('')
    try {
      const nextState = await requestJson<DemoState>('/api/run', {
        method: 'POST',
        body: JSON.stringify({ scenario_id: scenarioId, hooks_enabled: hooksEnabled }),
      })
      setState(nextState)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not start the scenario.')
    } finally {
      setBusyAction('')
    }
  }

  const reset = async (nextHooksEnabled = hooksEnabled) => {
    stateRevision.current += 1
    setBusyAction('reset')
    setErrorMessage('')
    try {
      const nextState = await requestJson<DemoState>('/api/reset', {
        method: 'POST',
        body: JSON.stringify({ hooks_enabled: nextHooksEnabled }),
      })
      setState(nextState)
      setHooksEnabled(nextState.hooks_enabled)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not reset the demo.')
    } finally {
      stateRevision.current += 1
      setBusyAction('')
    }
  }

  const decide = async (decision: 'approve' | 'reject') => {
    setBusyAction(decision)
    setErrorMessage('')
    try {
      const nextState = await requestJson<DemoState>('/api/approval', {
        method: 'POST',
        body: JSON.stringify({ decision }),
      })
      setState(nextState)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not resolve approval.')
    } finally {
      setBusyAction('')
    }
  }

  const flowState = (step: string) => {
    if (!scenarioHasRun) return 'future'
    if (step === 'request') return requestEvent ? 'done' : 'future'
    if (step === 'proposal') return proposalEvent ? 'done' : isBusy ? 'current' : terminalStatus ? 'blocked' : 'future'
    if (step === 'hook') {
      if (pendingApproval) return 'pending'
      return hookEvent ? (hookEvent.verdict === 'deny' ? 'blocked' : 'done') : isBusy ? 'current' : terminalStatus ? 'blocked' : 'future'
    }
    if (step === 'tool') {
      if (toolEvent) return 'done'
      return gateStatus === 'blocked' || pendingApproval || terminalStatus ? 'blocked' : 'future'
    }
    if (step === 'receipt') {
      if (receiptEvent) return 'done'
      return gateStatus === 'blocked' || pendingApproval || terminalStatus ? 'blocked' : 'future'
    }
    return 'future'
  }

  const outcomeCard = () => {
    if (!scenarioHasRun) {
      return (
        <div className="outcome empty-outcome">
          <div className="outcome-icon"><WalletCards size={26} /></div>
          <div>
            <strong>Ready for a scenario</strong>
            <p>Choose a request to see the payment service and ledger respond.</p>
          </div>
        </div>
      )
    }
    if (receiptEvent && state?.ledger.transactions.length) {
      const receipt = state.ledger.transactions.at(-1)
      return (
        <div className="outcome success-outcome">
          <div className="outcome-icon"><Check size={26} /></div>
          <div>
            <strong>PAYMENT COMPLETED</strong>
            <p>{money(receipt?.amount_cents)} sent to {receipt?.beneficiary_name}.</p>
            <span className="receipt-id">Receipt {receipt?.transaction_id}</span>
          </div>
        </div>
      )
    }
    if (pendingApproval) {
      return (
        <div className="outcome pending-outcome">
          <div className="outcome-icon"><Clock3 size={26} /></div>
          <div>
            <strong>NO MONEY MOVED</strong>
            <p>The payment tool has not run. Ledger is unchanged while approval is pending.</p>
          </div>
        </div>
      )
    }
    if (state?.outcome === 'blocked') {
      return (
        <div className="outcome danger-outcome">
          <div className="outcome-icon"><ShieldX size={26} /></div>
          <div>
            <strong>NO MONEY MOVED</strong>
            <p>PAYMENT TOOL NOT EXECUTED · Bank ledger unchanged.</p>
          </div>
        </div>
      )
    }
    if (state?.outcome === 'service_declined') {
      return (
        <div className="outcome danger-outcome">
          <div className="outcome-icon"><CircleAlert size={26} /></div>
          <div>
            <strong>PAYMENT DECLINED BY SERVICE</strong>
            <p>The backend validation rejected the request; no ledger mutation occurred.</p>
          </div>
        </div>
      )
    }
    if (state?.run_status === 'error') {
      const toolStarted = events.some((event) => event.type === 'payment_tool_started')
      return (
        <div className="outcome danger-outcome">
          <div className="outcome-icon"><CircleAlert size={26} /></div>
          <div>
            <strong>{toolStarted ? 'RUN ERROR · VERIFY PAYMENT RESULT' : 'NO MONEY MOVED'}</strong>
            <p>{state.error?.type}: {state.error?.message}</p>
          </div>
        </div>
      )
    }
    if (state?.run_status === 'completed') {
      return (
        <div className="outcome warning-outcome">
          <div className="outcome-icon"><CircleAlert size={26} /></div>
          <div>
            <strong>NO PAYMENT TOOL INVOCATION</strong>
            <p>No transfer was recorded by the payment service. The assistant's prose is not treated as proof of payment.</p>
          </div>
        </div>
      )
    }
    return (
      <div className="outcome pending-outcome">
        <div className="outcome-icon"><Activity size={26} /></div>
        <div>
          <strong>PAYMENT NOT YET CONFIRMED</strong>
          <p>Waiting for the framework and payment service events.</p>
        </div>
      </div>
    )
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark"><WalletCards size={23} /></div>
          <div>
            <h1>Banking Agent</h1>
          </div>
        </div>
        <div className="topbar-right">
          <button className="icon-button reset-button" type="button" onClick={() => void reset()} disabled={controlsDisabled}>
            <RefreshCw size={17} className={busyAction === 'reset' ? 'spin' : ''} />
            <span>Reset</span>
          </button>
        </div>
      </header>

      {connected && health && !health.runtime_ready && (
        <div className="runtime-banner" role="status">
          <CircleAlert size={18} />
          <span>
            Runtime dependencies are missing: {health.missing_modules.join(', ') || 'unknown'}. Install the Python dependencies and restart the banking service.
          </span>
        </div>
      )}
      {Boolean(connectionError || errorMessage || state?.error) && (
        <div className="error-banner" role="alert">
          <CircleAlert size={18} />
          <span>{connectionError || errorMessage || `${state?.error?.type}: ${state?.error?.message}`}</span>
          {errorMessage && <button type="button" aria-label="Dismiss error" onClick={() => setErrorMessage('')}><X size={17} /></button>}
        </div>
      )}
      {connectionError && (
        <div className="api-warning">
          <strong>Banking service unavailable</strong>
          <p>{state ? 'The displayed ledger is the last received snapshot, not a current confirmation.' : 'No payment action has been attempted.'} The page will reconnect automatically.</p>
        </div>
      )}

      <div className="scenario-controls">
        <label htmlFor="scenario">Scenario</label>
        <select
          id="scenario"
          value={selectedScenarioId}
          onChange={(event) => setSelectedScenarioId(event.target.value)}
          disabled={controlsDisabled}
        >
          {scenarios.map((scenario) => (
            <option key={scenario.scenario_id} value={scenario.scenario_id}>{scenario.title}</option>
          ))}
        </select>
        <label className="hooks-toggle" title="Changing hooks clears the current run">
          <input
            type="checkbox"
            role="switch"
            aria-label="Use Agent Hooks for the next run"
            checked={hooksEnabled}
            onChange={(event) => void reset(event.target.checked)}
            disabled={controlsDisabled}
          />
          <span>Hooks {hooksEnabled ? 'on' : 'off'}</span>
        </label>
        <button className="icon-button run-button" type="button" onClick={() => void runScenario(selectedScenarioId)} disabled={controlsDisabled}>
          {isBusy || busyAction === 'run' ? <span className="loading-dot" /> : <Play size={15} />}
          <span>Run</span>
        </button>
      </div>

      <section className={`stage-grid ${displayHooksEnabled ? '' : 'stage-grid-no-hooks'}`} aria-label="Payment execution stage">
        <article className="stage-panel request-panel">
          <div className="panel-heading">
            <div className="panel-icon request-icon"><Activity size={18} /></div>
            <div>
              <span className="eyebrow">01 · CUSTOMER REQUEST</span>
              <h2>What the customer asked</h2>
            </div>
          </div>
          <div className="request-bubble">
            {selectedScenario?.prompt ?? 'Select one of the scenarios above to begin.'}
          </div>
          <div className="proposal-card">
            <div className="proposal-topline">
              <span className="eyebrow">MODEL TOOL PROPOSAL</span>
              <span className={`event-tag ${proposalEvent ? 'tag-live' : 'tag-idle'}`}>
                {proposalEvent ? 'FROM TOOL CALL' : 'AWAITING'}
              </span>
            </div>
            {proposalEvent ? (
              <>
                <div className="proposal-amount">{money(proposalEvent.amount_cents as number | null)}</div>
                <div className="proposal-beneficiary">
                  <span className="avatar-mark">{String(proposalEvent.beneficiary_name ?? '?').slice(0, 1)}</span>
                  <span>
                    <strong>{String(proposalEvent.beneficiary_name ?? 'Unknown beneficiary')}</strong>
                    <small>Beneficiary {String(proposalEvent.beneficiary_id ?? '—')} · Account •• {String(proposalEvent.account_suffix ?? '—')}</small>
                  </span>
                </div>
              </>
            ) : (
              <div className="proposal-placeholder">
                <span className="placeholder-line" />
                <span className="placeholder-line short" />
                <small>A proposal appears only when the framework emits a payment tool call.</small>
              </div>
            )}
          </div>
        </article>

        {displayHooksEnabled && <article className={`stage-panel policy-panel gate-${gateStatus}`}>
          <div className="panel-heading">
            <div className="panel-icon policy-icon"><ShieldCheck size={18} /></div>
            <div>
              <span className="eyebrow">02 · POLICY CHECKPOINT</span>
              <h2>Agent Hooks</h2>
            </div>
            <span className={`enforcement-badge ${displayHooksEnabled ? '' : 'badge-off'}`}>{displayHooksEnabled ? 'ENFORCE' : 'OFF'}</span>
          </div>
          <div className={`verdict-card verdict-${gateStatus}`}>
            <div className="verdict-symbol">
              {gateStatus === 'off' ? <ShieldOff size={34} /> :
                gateStatus === 'allowed' ? <Check size={34} /> :
                gateStatus === 'blocked' || gateStatus === 'error' ? <ShieldX size={34} /> :
                  gateStatus === 'pending' ? <Clock3 size={34} /> : <ShieldCheck size={34} />}
            </div>
            <div className="verdict-copy">
              <span className="eyebrow">PRE-TOOL CALL DECISION</span>
              <strong>{gateLabel}</strong>
            </div>
            <span className="verdict-status-dot" />
          </div>
          <p className="policy-reason">{gateReason}</p>
          {displayHooksEnabled && <div className="policy-metadata">
            <div>
              <span>POLICY</span>
              <strong>{String(hookEvent?.policy ?? 'synthetic-bank-payment-policy')}</strong>
            </div>
            <div>
              <span>VERSION</span>
              <strong>{String(hookEvent?.policy_version ?? state?.approval?.policy_version ?? '1.0.0')}</strong>
            </div>
            <div>
              <span>INTERCEPTION</span>
              <strong>{String(hookEvent?.interception_point ?? state?.approval?.interception_point ?? 'pre_tool_call')}</strong>
            </div>
            <div>
              <span>RECORDED</span>
              <strong>{clock(String(hookEvent?.timestamp ?? state?.approval?.resolved_at ?? ''))}</strong>
            </div>
          </div>}
          {pendingApproval && approval ? (
            <div className="approval-card">
              <div className="approval-heading">
                <Clock3 size={18} />
                <strong>Presenter approval required</strong>
              </div>
              <p>{money(approval.amount_cents)} to {approval.beneficiary_name} · •• {approval.account_suffix}</p>
              <div className="approval-actions">
                <button className="approve-button" type="button" onClick={() => void decide('approve')} disabled={!connected || busyAction !== ''}>
                  <Check size={17} /> Approve transfer
                </button>
                <button className="reject-button" type="button" onClick={() => void decide('reject')} disabled={!connected || busyAction !== ''}>
                  <X size={17} /> Reject
                </button>
              </div>
              <small>Approval resolves the hook's liftable deny; ledger mutation remains after approval only.</small>
            </div>
          ) : null}
        </article>}

        <article className="stage-panel outcome-panel">
          <div className="panel-heading">
            <div className="panel-icon outcome-icon-heading"><WalletCards size={18} /></div>
            <div>
              <span className="eyebrow">{displayHooksEnabled ? '03' : '02'} · BANK OUTCOME</span>
              <h2>Payment service & ledger</h2>
            </div>
          </div>
          {outcomeCard()}
          <div className="balance-card">
            <div className="balance-heading">
              <span>{state?.ledger.account_label ?? 'Demo checking •• 1042'}</span>
              <span className="ledger-live"><span /> LEDGER</span>
            </div>
            <div className="balance-value">{money(state?.ledger.balance_cents ?? 5_000_000)}</div>
            <div className="balance-footer">
              <span>Available balance</span>
              <span>{state?.ledger.transactions.length ?? 0} posted {state?.ledger.transactions.length === 1 ? 'payment' : 'payments'}</span>
            </div>
          </div>
          <div className="ledger-list">
            <div className="ledger-list-heading">
              <span>RECENT ACTIVITY</span>
              <span>{state?.ledger.transactions.length ?? 0} ITEMS</span>
            </div>
            {state?.ledger.transactions.length ? (
              [...state.ledger.transactions].reverse().map((transaction) => (
                <div className="ledger-row" key={transaction.transaction_id}>
                  <span className="ledger-check"><Check size={15} /></span>
                  <span className="ledger-row-main">
                    <strong>{transaction.beneficiary_name}</strong>
                    <small>{transaction.transaction_id} · {transaction.status.toUpperCase()}</small>
                  </span>
                  <strong className="ledger-amount">−{money(transaction.amount_cents)}</strong>
                </div>
              ))
            ) : (
              <div className="ledger-empty">
                <span className={`empty-state-icon ${state?.no_money_moved && scenarioHasRun ? 'empty-state-confirmed' : ''}`}>
                  {state?.no_money_moved && scenarioHasRun ? <ShieldX size={17} /> : <WalletCards size={17} />}
                </span>
                <span>
                  <strong>{state?.no_money_moved && scenarioHasRun ? 'NO MONEY MOVED' : 'No payment posted'}</strong>
                  <small>{state?.no_money_moved && scenarioHasRun ? 'Balance matches the pre-run ledger.' : 'Transactions appear only after the payment service executes.'}</small>
                </span>
              </div>
            )}
          </div>
        </article>
      </section>

      <section className="execution-section" aria-label="Execution path">
        <div className="execution-header">
          <div>
            <h2>Execution path</h2>
          </div>
        </div>
        <div className="execution-path">
          {[
            { id: 'request', label: 'Request received', Icon: Play },
            { id: 'proposal', label: 'Model proposes transfer', Icon: Activity },
            { id: 'hook', label: 'Hook checks policy', Icon: ShieldCheck },
            { id: 'tool', label: 'Payment tool', Icon: WalletCards },
            { id: 'receipt', label: 'Receipt & ledger', Icon: Check },
          ].filter((step) => displayHooksEnabled || step.id !== 'hook').map(({ id, label, Icon }, index, steps) => {
            const stepState = flowState(id)
            return (
              <div className="flow-fragment" key={id}>
                <div className={`flow-step step-${stepState}`}>
                  <span className="flow-icon"><Icon size={17} /></span>
                  <span className="flow-label">{label}</span>
                  <small>
                    {stepState === 'done' ? 'EVENT RECORDED' :
                      stepState === 'pending' ? 'WAITING' :
                        stepState === 'blocked' ? (id === 'hook' && hookEvent ? 'DENIED' : 'NOT EXECUTED') :
                          stepState === 'current' ? 'IN PROGRESS' : 'READY'}
                  </small>
                </div>
                {index < steps.length - 1 && (
                  <span className={`flow-connector ${stepState === 'done' ? 'connector-done' : ''}`}><ArrowRight size={17} /></span>
                )}
              </div>
            )
          })}
        </div>
        {state?.assistant_response && (
          <div className="agent-response">
            <span className="eyebrow">AGENT RESPONSE · NOT PAYMENT EVIDENCE</span>
            <p>{state.assistant_response}</p>
          </div>
        )}
      </section>

      <footer className="footer-note">
        <span>Synthetic demo data. No real payments.</span>
      </footer>
    </main>
  )
}

export default App
