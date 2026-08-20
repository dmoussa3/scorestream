import { usePoll } from '../hooks/usePoll'
import { useCallback, useEffect, useState } from 'react'

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000'

const STATUS_STYLES = {
    OK: { bg: '#00ff85', text: '#003300', label: 'HEALTHY' },
    ALARM: { bg: '#ef4444', text: '#ffffff', label: 'ALERT' },
    INSUFFICIENT_DATA: { bg: '#f59e0b', text: '#ffffff', label: 'PENDING' },
    MISSING: { bg: '#6b7280', text: '#ffffff', label: 'UNKNOWN' },
}

function ComponentCard({ name, component, theme, lastRefresh }) {
    const colors = STATUS_STYLES[component.state] || STATUS_STYLES.MISSING

    return (
        <div
            style={{
                backgroundColor: theme?.secondary,
                borderColor: component.state === 'ALARM' ? '#ef4444' : theme?.border,
                borderWidth: component.state === 'ALARM' ? '1.5px' : '1px',
            }}
            className="border rounded-xl p-4 flex flex-col gap-3"
        >
            {/* Header row */}
            <div className="flex items-center justify-between">
                <span className="text-white font-semibold text-sm tracking-tight">
                    {component.label || name}
                </span>
                <span
                    className="text-xs font-bold px-2.5 py-1 rounded-full tracking-wider"
                    style={{ backgroundColor: colors.bg, color: colors.text }}
                >
                    {colors.label}
                </span>
            </div>

            {/* Alarm reason */}
            {component.state === 'ALARM' && component.reason && (
                <p className="text-xs text-red-400 bg-red-950 rounded px-2 py-1">
                    {component.reason}
                </p>
            )}

            {/* Producer last poll */}
            {component.last_poll && (() => {
                // Strip microseconds to 3 decimal places for broad JS compatibility
                const normalized = component.last_poll.replace(/(\.\d{3})\d+/, '$1')
                const date = new Date(normalized)
                const display = isNaN(date.getTime())
                    ? component.last_poll
                    : date.toLocaleTimeString('en-US', {
                        hour: 'numeric',
                        minute: '2-digit',
                        second: '2-digit',
                        timeZone: 'America/New_York',
                    }) + ' EDT'

                return (
                    <div className="flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                        <span className="text-xs font-medium" style={{ color: theme?.accent }}>
                            Last poll {display}
                        </span>
                    </div>
                )
            })()}

            {/* Divider */}
            <div style={{ borderColor: theme?.border }} className="border-t opacity-30" />

            {/* Timestamps */}
            <div className="flex flex-col gap-0.5">
                {component.updated && (
                    <div className="flex justify-between items-center">
                        <span className="text-xs opacity-80" style={{ color: theme?.text }}>
                            State changed
                        </span>
                        <span className="text-xs opacity-80" style={{ color: theme?.text }}>
                            {new Date(component.updated).toLocaleTimeString('en-US', {
                                hour: 'numeric',
                                minute: '2-digit',
                                timeZone: 'America/New_York',
                            })} EDT
                        </span>
                    </div>
                )}
                {lastRefresh && (
                    <div className="flex justify-between items-center">
                        <span className="text-xs opacity-80" style={{ color: theme?.text }}>
                            Last checked
                        </span>
                        <span className="text-xs opacity-80" style={{ color: theme?.text }}>
                            {lastRefresh.toLocaleTimeString('en-US', {
                                hour: 'numeric',
                                minute: '2-digit',
                                second: '2-digit',
                                timeZone: 'America/New_York',
                            })} EDT
                        </span>
                    </div>
                )}
            </div>
        </div>
    )
}

export default function PipelineTab({ theme }) {
    const [health, setHealth] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [lastRefresh, setLastRefresh] = useState(null)

    const fetchHealth = useCallback(async () => {
        try {
            const res = await fetch(`${API}/health/pipeline`)
            const data = await res.json()
            setHealth(data)
            setLastRefresh(new Date())
            setError(null)
        } catch (err) {
            setError(err.message || 'Failed to fetch pipeline health')
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => { fetchHealth() }, [fetchHealth])

    useEffect(() => {
        const interval = setInterval(fetchHealth, 30 * 1000)
        return () => clearInterval(interval)
    }, [fetchHealth])

    if (loading) return (
        <div className="p-4" style={{ color: theme?.accent }}>
            Loading pipeline health...
        </div>
    )

    if (error) return (
        <div className="p-4 text-red-400">
            Error: {error}
        </div>
    )

    if (health?.error) return (
        <div className="p-4 text-yellow-400">
            {health.error}
        </div>
    )

    const components = health?.components || {}

    // Group components for layout
    const groups = [
        {
            label: "Compute",
            keys: ["producer", "api"],
        },
        {
            label: "Load Balancer",
            keys: ["alb_errors", "alb_latency"],
        },
        {
            label: "Data Layer",
            keys: ["kafka", "rds_connections", "rds_cpu"],
        },
    ]

    const overallHealthy = health?.overall

    return (
        <div className="max-w-4xl mx-auto space-y-6">

            {/* Overall status banner */}
            <div
                className="border rounded-lg p-4 flex items-center justify-between"
                style={{
                    backgroundColor: overallHealthy ? '#00220f' : '#220000',
                    borderColor: overallHealthy ? '#00ff85' : '#ef4444',
                }}
            >
                <div className="flex items-center gap-3">
                    <span className="text-2xl">
                        {overallHealthy ? '✅' : '🔴'}
                    </span>
                    <div>
                        <p className="text-white font-semibold">
                            {overallHealthy
                                ? 'All systems operational'
                                : 'Pipeline issue detected'}
                        </p>
                        <p className="text-xs opacity-60 text-white">
                            Powered by CloudWatch alarms
                        </p>
                    </div>
                </div>
                <div className="text-right">
                    <button
                        onClick={fetchHealth}
                        style={{ color: theme?.accent }}
                        className="text-xs hover:opacity-80 transition-opacity"
                    >
                        ↻ Refresh
                    </button>
                    {lastRefresh && (
                        <p className="text-xs text-white opacity-40 mt-1">
                            {lastRefresh.toLocaleTimeString('en-US', {
                                hour: 'numeric',
                                minute: '2-digit',
                                second: '2-digit',
                                timeZone: 'America/New_York',
                            })} EDT
                        </p>
                    )}
                </div>
            </div>

            {/* Component groups */}
            {groups.map(group => (
                <div key={group.label}>
                    <div className="flex items-center gap-3 mb-3">
                        <h3
                            className="text-xs font-bold uppercase tracking-widest"
                            style={{ color: theme?.accent }}
                        >
                            {group.label}
                        </h3>
                        <div
                            className="flex-1 h-px opacity-20"
                            style={{ backgroundColor: theme?.accent }}
                        />
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {group.keys.map(key => (
                            components[key] && (
                                <ComponentCard
                                    key={key}
                                    name={key}
                                    component={components[key]}
                                    theme={theme}
                                    lastRefresh={lastRefresh}
                                />
                            )
                        ))}
                    </div>
                </div>
            ))}

            {/* Footer note */}
            <p className="text-xs text-center opacity-40" style={{ color: theme?.text }}>
                Alarm states update every 30 seconds · CloudWatch evaluation period: 5 minutes
            </p>
        </div>
    )
}