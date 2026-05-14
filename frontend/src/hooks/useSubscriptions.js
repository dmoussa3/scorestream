import { useState, useEffect, use } from "react";

const STORGAGE_KEY = 'scorestream_subscriptions'

export function useSubscriptions() {
    const [subscriptions, setSubscriptions] = useState(() => {
        try {
            const stored = localStorage.getItem(STORGAGE_KEY)
            return stored ? new Set(JSON.parse(stored)) : new Set()
        } catch {
            return new Set()
        }
    })

    useEffect(() => {
        localStorage.setItem(STORGAGE_KEY, JSON.stringify([...subscriptions]))
    }, [subscriptions])

    const subscribe = (gameId) => setSubscriptions(prev => new Set([...prev, gameId]))
    const unsubscribe = (gameId) => setSubscriptions(prev => {
        const newSet = new Set(prev)
        newSet.delete(gameId)
        return newSet
    })

    const toggle = (gameId) => {
        if (subscriptions.has(gameId)) {
            unsubscribe(gameId)
        } else {
            subscribe(gameId)
        }
    }

    const isSubscribed = (gameId) => subscriptions.has(gameId)

    return { subscriptions, toggle, isSubscribed }
}