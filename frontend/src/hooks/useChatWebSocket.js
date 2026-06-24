import { useState, useEffect, useRef, useCallback } from 'react'

const WS_URL = process.env.REACT_APP_WS_CHAT_URL || 'ws://localhost:8000/ws/chat'

export function useChatWebSocket() {
    const callBackRef = useRef(null)
    const [isConnected, setIsConnected] = useState(false)
    const wsRef = useRef(null)

    useEffect(() => {
        wsRef.current = new WebSocket(WS_URL)

        wsRef.current.onopen = () => {
            console.log('[useChatWebSocket] WebSocket connected')
            setIsConnected(true)
        }

        wsRef.current.onclose = () => {
            console.log('[useChatWebSocket] WebSocket disconnected')
            setIsConnected(false)
        }

        wsRef.current.onmessage = (event) => {
            const message = JSON.parse(event.data)
            console.log('[useChatWebSocket] received message:', message)
            const cb = callBackRef.current
            console.log('[useChatWebSocket] current callbacks:', cb)

            if (message.type === 'sql' && cb.onSql) cb.onSql(message.sql)
            if (message.type === 'answer_start' && cb.onAnswerStart) cb.onAnswerStart()
            if (message.type === 'answer_chunk' && cb.onChunk) cb.onChunk(message.chunk)
            if (message.type === 'done' && cb.onDone) cb.onDone(message)
            if (message.type === 'error' && cb.onError) cb.onError(message.message)
        }

        return () => wsRef.current?.close()
    }, [])

    const sendQuestion = useCallback((question, conversation, callbacks) => {
        console.log('[useChatWebSocket] sendQuestion called, callbacks:', callbacks)  // ← add this

        callBackRef.current = callbacks
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ question, conversation }))
        } else {
            console.log('[useChatWebSocket] WebSocket not open, readyState:', wsRef.current?.readyState)  // ← add this
        }
    }, [])

    return { isConnected, sendQuestion }
}