import { usePoll } from '../hooks/usePoll'

const STATUS_STYLES = {
    healthy: { dot: 'bg-[#00ff85]', badge: 'bg-[#00ff85]/20 text-[#00ff85]', label: 'Healthy' },
    success: { dot: 'bg-[#00ff85]', badge: 'bg-[#00ff85]/20 text-[#00ff85]', label: 'Success' },
    stale:   { dot: 'bg-yellow-500', badge: 'bg-yellow-900 text-yellow-300', label: 'Stale'    },
    error:   { dot: 'bg-red-500',    badge: 'bg-red-900 text-red-300',       label: 'Error'    },
    failed:  { dot: 'bg-red-500',    badge: 'bg-red-900 text-red-300',       label: 'Failed'   },
    running: { dot: 'bg-blue-500',   badge: 'bg-blue-900 text-blue-300',     label: 'Running'  },
    unknown: { dot: 'bg-purple-500', badge: 'bg-purple-900 text-purple-300', label: 'Unknown' },
}

const getStyle = (status) => STATUS_STYLES[status] || STATUS_STYLES.unknown

const timeAgo = (isoString) => {
    if (!isoString) return 'never'
    
    const utcString = isoString.endsWith('Z') || isoString.includes('+')
        ? isoString
        : `${isoString}Z`
    
    const seconds = Math.floor((Date.now() - new Date(utcString)) / 1000)
    
    if (seconds < 0)     return 'just now'          // clock skew safety net
    if (seconds < 60)    return `${seconds}s ago`
    if (seconds < 3600)  return `${Math.floor(seconds / 60)}m ago`
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
    return `${Math.floor(seconds / 86400)}d ago`
}

function StatusCard({ title, status, metrics }) {
    const style = getStyle(status)
    return (
        <div className="bg-[#2d0032] border border-purple-800 rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${style.dot} ${status === 'healthy' || status === 'success' ? 'animate-pulse' : ''}`} />
                    <span className="text-sm font-semibold text-white">{title}</span>
                </div>
                <span className={`text-xs px-2 py-0.5 rounded font-medium ${style.badge}`}>
                    {style.label}
                </span>
            </div>
            <div className="space-y-1.5">
                {metrics.map(({ label, value }) => (
                    <div key={label} className="flex justify-between text-xs">
                        <span className="text-purple-400">{label}</span>
                        <span className="text-purple-200 font-medium">{value ?? '—'}</span>
                    </div>
                ))}
            </div>
        </div>
    )
}

export default function PipelineTab() {
    const { data, loading, error } = usePoll('/health/pipeline', 60000)

    if (loading) return <div className="text-[#37003c] p-4">Loading pipeline status...</div>
    if (error)   return <div className="text-[#37003c] p-4">Error loading pipeline health: {error}</div>
    if (!data)   return null

    const { postgres, kafka, airflow, producer } = data

    return (
        <div className="space-y-6">

            {/* Page header */}
            <div>
                <h2 className="text-lg font-semibold text-[#37003c]">Pipeline Health</h2>
                <p className="text-sm text-[#37003c] opacity-60 mt-0.5">
                    Real-time status of all ScoreStream pipeline components — updates every 60s
                </p>
            </div>

            {/* Producer */}
            <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[#37003c] mb-3">
                    Ingestion
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    <StatusCard
                        title="ESPN Producer"
                        status={producer.status}
                        metrics={[
                            { label: 'Last poll',  value: timeAgo(producer.last_poll) },
                            { label: 'Poll interval', value: '30s' },
                            { label: 'Source', value: 'ESPN Public API' },
                        ]}
                    />
                </div>
            </section>

            {/* Kafka */}
            <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[#37003c] mb-3">
                    Message Broker — Kafka
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {Object.entries(kafka).map(([topic, info]) => (
                        <StatusCard
                            key={topic}
                            title={topic}
                            status={info.status}
                            metrics={[
                                { label: 'Total messages', value: info.message_count.toLocaleString() },
                                { label: 'Partitions',     value: '1' },
                                { label: 'Retention',      value: '24h' },
                            ]}
                        />
                    ))}
                </div>
            </section>

            {/* PostgreSQL tables */}
            <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[#37003c] mb-3">
                    Storage — PostgreSQL
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {Object.entries(postgres).map(([table, info]) => (
                        <StatusCard
                            key={table}
                            title={`${table} table`}
                            status={info.status}
                            metrics={[
                                { label: 'Row count',     value: info.count.toLocaleString() },
                                { label: 'Last updated',  value: timeAgo(info.last_updated) },
                            ]}
                        />
                    ))}
                </div>
            </section>

            {/* Airflow DAGs */}
            <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-[#37003c] mb-3">
                    Orchestration — Airflow
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {Object.entries(airflow).map(([dag, info]) => (
                        <StatusCard
                            key={dag}
                            title={dag.replace(/_/g, ' ')}
                            status={info.status}
                            metrics={[
                                { label: 'Last run',  value: timeAgo(info.last_run) },
                                { label: 'State',     value: info.state },
                                { label: 'Schedule',  value: dag.includes('refresh') ? 'Every 30min' : 'Daily midnight' },
                            ]}
                        />
                    ))}
                </div>
            </section>
        </div>
    )
}