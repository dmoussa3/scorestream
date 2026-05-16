import { useState, useEffect, useRef } from 'react'

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000'

export function usePoll(path, intervalMs = 30000, active = true) {
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const intervalRef = useRef(null)

    useEffect(() => {
        if (!path || !active) {
            setData(null)
            setLoading(false)
            return
        }

        let cancelled = false

        const fetchData = async () => {
            try {
                const res = await fetch(`${API}${path}`)
                if (!res.ok) throw new Error(`HTTP ${res.status}`)
                const json = await res.json()
                if (!cancelled) {
                    setData(json)
                    setError(null)
                    setLoading(false)
                }
            } catch (e) {
                if (!cancelled) {
                    setError(e.message)
                    setLoading(false)
                }
            }
        }

        fetchData()
        intervalRef.current = setInterval(fetchData, intervalMs)

        return () => {
            cancelled = true
            clearInterval(intervalRef.current)
        }
    }, [path, intervalMs, active])

    return { data, loading, error }
}