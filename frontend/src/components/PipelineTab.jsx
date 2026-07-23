import { usePoll } from '../hooks/usePoll'
import { useCallback, useEffect, useState } from 'react'

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000'

const STATUS_STYLES = {
    OK: { bg: '#00ff85', text: '#003300', label: 'HEALTHY' },
    ALARM: { bg: '#ef4444', text: '#ffffff', label: 'ALERT' },
    INSUFFICIENT_DATA: { bg: '#f59e0b', text: '#ffffff', label: 'PENDING' },
    MISSING: { bg: '#6b7280', text: '#ffffff', label: 'UNKNOWN' },
}

function ComponentCard({ name, component, theme }) {
    const colors = STATUS_STYLES[component.state] || STATUS_STYLES.MISSING

    return (
        <div
            style={{ backgroundColor: theme?.secondary, borderColor: theme?.border }}
            className="border rounded-lg p-4 flex flex-col gap-2"
        >
            <div className="flex items-center justify-between">
                <span className="text-white font-medium text-sm">
                    {component.label || name}
                </span>
                <span
                    className="text-xs font-semibold px-2 py-0.5 rounded-full"
                    style={{ backgroundColor: colors.bg, color: colors.text }}
                >
                    {colors.label}
                </span>
            </div>

            {/* State detail */}
            {component.state === 'ALARM' && component.reason && (
                <p className="text-xs text-red-400 opacity-80">
                    {component.reason}
                </p>
            )}

            {/* Producer-specific: last poll info */}
            {component.last_poll && (
                <div className="text-xs text-purple-300 space-y-0.5">
                    <div>
                        Last poll: {new Date(component.last_poll).toLocaleTimeString('en-US', {
                            hour: 'numeric',
                            minute: '2-digit',
                            second: '2-digit',
                            timeZone: 'America/New_York',
                        })} EDT
                    </div>
                    {component.stale && (
                        <div className="text-yellow-400">
                            ⚠ Poll appears stale ({Math.floor(component.poll_age_seconds / 60)}m ago)
                        </div>
                    )}
                </div>
            )}

            {/* Last state change */}
            {component.updated && (
                <p className="text-xs opacity-40" style={{ color: theme?.text }}>
                    Updated {new Date(component.updated).toLocaleTimeString('en-US', {
                        hour: 'numeric',
                        minute: '2-digit',
                        timeZone: 'America/New_York',
                    })} EDT
                </p>
            )}
        </div>
    )
}

export default function PipelineTab({ theme }) {
    const [health, setHealth]   = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError]     = useState(null)
    const [lastRefresh, setLastRefresh] = useState(null)

    const fetchHealth = useCallback(async () => {
        try {
            const res  = await fetch(`${API}/health/pipeline`)
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
                    <h3
                        className="text-xs font-semibold uppercase tracking-wider mb-3"
                        style={{ color: theme?.accent, opacity: 0.7 }}
                    >
                        {group.label}
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {group.keys.map(key => (
                            components[key] && (
                                <ComponentCard
                                    key={key}
                                    name={key}
                                    component={components[key]}
                                    theme={theme}
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