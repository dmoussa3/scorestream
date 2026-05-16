import { useRef, useEffect, useState, useCallback } from "react"

const WS_URL = process.env.REACT_APP_WS_URL || "ws://localhost:8000/ws"

export function useWebSocket(onUpdate) {
	const ws = useRef(null)
	const [isConnected, setIsConnected] = useState(false)
	const reconnectTimer = useRef(null)
	const onUpdateRef = useRef(onUpdate)

	useEffect(() => {
		onUpdateRef.current = onUpdate
	}, [onUpdate])

	const connect = useCallback(() => {
		if (ws.current?.readyState === WebSocket.OPEN) { return }

		ws.current = new WebSocket(WS_URL)

		ws.current.onopen = () => {
			console.log("[useWebSocket] Connected to WebSocket")
			setIsConnected(true)

			if (reconnectTimer.current) {
				clearTimeout(reconnectTimer.current)
				reconnectTimer.current = null
			}
		}

		ws.current.onmessage = (event) => {
			try {
				const msg = JSON.parse(event.data)
				onUpdateRef.current(msg)
			} catch (err) {
				console.error("[useWebSocket] Failed to parse message:", err)
			}
		}

		ws.current.onclose = () => {
			setIsConnected(false)
			console.log("[useWebSocket] WebSocket connection closed, attempting to reconnect in 3s")

			reconnectTimer.current = setTimeout(connect, 3000)
		}

		ws.current.onerror = (err) => {
			console.error("[useWebSocket] WebSocket error:", err)
			ws.current.close()
		}
	}, [])

	useEffect(() => {
		connect()
		return () => {
			if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
			ws.current?.close()
		}
	}, [connect])

	useEffect(() => {
		const check = setInterval(() => {
			const isOpen = ws.current?.readyState === WebSocket.OPEN
			setIsConnected(prev => prev !== isOpen ? isOpen : prev)
		}, 1000)
		return () => clearInterval(check)
	}, [])

	useEffect(() => {
		const ping = setInterval(() => {
			if (ws.current?.readyState === WebSocket.OPEN) {
				ws.current.send("ping")
			}
		}, 3000)
		return () => clearInterval(ping)
	}, [])

	return { isConnected}
}