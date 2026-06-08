import { useState, useEffect, useRef } from 'react';
import {
    BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
    XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine
} from 'recharts'

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const SUGGESTED_QUESTIONS = [
    "Who scored in Arsenal's last game?",
    "Which games are live right now?",
    "Show me the Bundesliga top 5",
    "How many goals were scored today?",
    "Which team has the best goal difference in Serie A?",
    "Did anyone score a penalty in Ligue 1 today?",
]

function ChatChart({ chart, theme }) {

    // Parse data if it came back as a string
    const data = typeof chart.data === 'string'
        ? JSON.parse(chart.data)
        : chart.data

    if (!chart?.should_chart || !data?.length) return null

    const firstRow = data[0]
    const allKeys = Object.keys(firstRow)

    // Use config keys if they exist in data, otherwise auto-detect
    const xKey = (chart.x_key && firstRow[chart.x_key] !== undefined)
        ? chart.x_key
        : allKeys.find(k => typeof firstRow[k] === 'string')

    const yKey = (chart.y_key && firstRow[chart.y_key] !== undefined)
        ? chart.y_key
        : allKeys.find(k => typeof firstRow[k] === 'number' && k !== xKey)


    console.log('[ChatChart] type:', chart.chart_type)
    console.log('[ChatChart] xKey:', xKey, 'yKey:', yKey)
    console.log('[ChatChart] data:', data)
    console.log('[ChatChart] first row keys:', Object.keys(data?.[0] || {}))

    const COLORS = [
        theme.accent, '#8b5cf6', '#3b82f6', '#ef4444',
        '#f97316', '#10b981', '#f59e0b', '#06b6d4'
    ]

    if (chart.chart_type === 'bar') {
        const hasNegatives = data.some(d => d[yKey] < 0)

        return (
            <div style={{ width: '100%', height: 220 }}>
                <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data} margin={{ top: 5, right: 20, left: 40, bottom: 40 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                        <XAxis
                            dataKey={xKey}
                            type="category"
                            tick={{ fill: 'rgba(255,255,255,0.6)', fontSize: 10 }}
                            tickLine={false}
                            interval={0}              // ← force every label to show
                            angle={-35}               // ← angle to prevent overlap
                            textAnchor="end"          // ← anchor text correctly when angled
                            height={60}               // ← give more room for angled labels
                        />
                        <YAxis
                            tick={{ fill: 'rgba(255,255,255,0.6)', fontSize: 10 }}
                            tickLine={false}
                            axisLine={false}
                            domain={['auto', 'auto']}
                        />
                        <Tooltip
                            contentStyle={{
                                backgroundColor: theme.primary,
                                border: `1px solid ${theme.border}`,
                                borderRadius: '8px',
                                fontSize: '12px',
                                color: '#ffffff',
                            }}
                            labelStyle={{ color: theme.accent }}
                            itemStyle={{ color: '#ffffff' }}
                        />
                        {hasNegatives && (
                            <ReferenceLine y={0} stroke="rgba(255,255,255,0.3)" strokeWidth={1} />
                        )}
                        <Bar dataKey={yKey} radius={[4, 4, 0, 0]}>
                            {data.map((entry, i) => (
                                <Cell
                                    key={i}
                                    fill={entry[yKey] >= 0 ? theme.accent : '#ef4444'}
                                />
                            ))}
                        </Bar>
                    </BarChart>
                </ResponsiveContainer>
            </div>
        )
    }

    if (chart.chart_type === 'line') {
        return (
            <div style={{ width: '100%', height: 280 }}>
                <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={data} margin={{ top: 5, right: 20, left: 40, bottom: 40 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                        <XAxis
                            dataKey={xKey}
                            tick={{ fill: 'rgba(255,255,255,0.6)', fontSize: 10 }}
                            tickLine={false}
                            interval={0}              // ← force every label to show
                            angle={-35}               // ← angle to prevent overlap
                            textAnchor="end"          // ← anchor text correctly when angled
                            height={60}               // ← give more room for angled labels
                        />
                        <YAxis
                            tick={{ fill: 'rgba(255,255,255,0.6)', fontSize: 10 }}
                            tickLine={false}
                            axisLine={false}
                            domain={['auto', 'auto']}
                        />
                        <Tooltip
                            contentStyle={{
                                backgroundColor: theme.primary,
                                border: `1px solid ${theme.border}`,
                                borderRadius: '8px',
                                fontSize: '12px',
                                color: '#ffffff'
                            }}
                            labelStyle={{ color: theme.accent }}
                            itemStyle={{ color: '#ffffff' }}
                        />
                        <Line
                            type="monotone"
                            dataKey={yKey}
                            stroke={chart.color || theme.secondary}
                            strokeWidth={2}
                            dot={{ fill: chart.color || theme.secondary, r: 4 }}
                            activeDot={{ r: 6 }}
                        />
                    </LineChart>
                </ResponsiveContainer>
            </div>
        )
    }

    if (chart.chart_type === 'pie') {
        return (
            <div style={{ width: '100%', height: 240 }}>
                <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                        <Pie
                            data={data}
                            dataKey={yKey}
                            nameKey={xKey}
                            cx="50%"
                            cy="50%"
                            outerRadius={80}
                            label={({ name, percent }) =>
                                `${name} ${(percent * 100).toFixed(0)}%`
                            }
                            labelLine={false}
                        >
                            {data.map((_, i) => (
                                <Cell key={i} fill={COLORS[i % COLORS.length]} />
                            ))}
                        </Pie>
                        <Tooltip
                            contentStyle={{
                                backgroundColor: theme.primary,
                                border: `1px solid ${theme.border}`,
                                borderRadius: '8px',
                                fontSize: '12px',
                                color: '#ffffff'
                            }}
                            labelStyle={{ color: theme.accent }}
                            itemStyle={{ color: '#ffffff' }}
                        />
                        <Legend
                            wrapperStyle={{ fontSize: '11px', color: 'rgba(255,255,255,0.6)' }}
                        />
                    </PieChart>
                </ResponsiveContainer>
            </div>
        )
    }

    return null
}

export default function ChatTab({ theme }) {
    const [messages, setMessages] = useState([{
        role: "assistant",
        content: "Hi! I'm your football assistant. Ask me anything about live scores, goal scorers, or current standings in the Top 5 European Leagues, and I'll do my best to help you out!"
    }]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const messagesEndRef = useRef(null);
    const [showSql, setShowSql] = useState({})
    const toggleSql = (index) => setShowSql(prev => ({ ...prev, [index]: !prev[index] }))

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    const sendMessage = async (question) => {
        const q = question || input.trim();
        if (!q || loading) return;

        const newMessage = { role: "user", content: q };
        const updatedMessages = [...messages, newMessage];
        setMessages(updatedMessages);
        setInput('');
        setLoading(true);

        const history = updatedMessages
            .filter(m => !(m.role === 'assistant' && m.content.startsWith("Hi!")))  // exclude initial greeting
            .map(m => ({ role: m.role, content: m.content }));

        try {
            const response = await fetch(`${API}/chat`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ question: q, conversation: history.slice(0, -1) })
            });
            const data = await response.json()
            setMessages(prev => [...prev, { role: "assistant", content: data.answer, chart: data.chart || null, sql: data.sql || null }]);
        } catch (error) {
            console.error('Error sending message:', error);

            let chart = data.chart || null
            if (chart) {
                chart = {
                    ...chart,
                    x_key: chart.x_key || chart.x_axis || chart.xKey || chart.x || null,
                    y_key: chart.y_key || chart.y_axis || chart.yKey || chart.y || null,
                }
            }

            setMessages(prev => [...prev, { role: "assistant", content: data.answer, chart: data.chart || null, sql: data.sql || null }]);
        } finally {
            setLoading(false);
        }
    }

    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    }

    return (
        <div className="max-w-6xl mx-auto flex flex-col" style={{ height: 'calc(100vh - 180px)' }}>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto space-y-4 pb-4">
                {messages.map((msg, i) => (
                    <div key={i} className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>

                        {/* Text bubble */}
                        <div
                            style={msg.role === 'user'
                                ? { backgroundColor: theme.accent, color: theme.primary, borderColor: theme.primary }
                                : { backgroundColor: theme.secondary, color: 'white', borderColor: theme.primary }
                            }
                            className={`max-w-xs lg:max-w-md px-4 py-3 border rounded-2xl text-sm ${
                                msg.role === 'assistant' ? 'border' : ''
                            }`}
                        >
                            {msg.content.split('\n').map((line, j) => (
                                <span key={j}>
                                    {line}
                                    {j < msg.content.split('\n').length - 1 && <br />}
                                </span>
                            ))}
                        </div>

                        {/* Chart — full width, outside the bubble */}
                        {msg.role === 'assistant' && msg.chart?.should_chart && (
                            <div
                                style={{ backgroundColor: theme.secondary, borderColor: theme.primary }}
                                className="border rounded-2xl mt-2 p-4 w-full"
                            >
                                <ChatChart chart={msg.chart} theme={theme} />
                            </div>
                        )}

                        {/* SQL toggle — below chart */}
                        {msg.role === 'assistant' && msg.sql && (
                            <button
                                onClick={() => toggleSql(i)}
                                style={{ color: theme.secondary }}
                                className="text-xs mt-1 opacity-60 hover:opacity-100 transition-opacity self-start"
                            >
                                {showSql[i] ? 'hide query' : 'show query'}
                            </button>
                        )}

                        {msg.sql && showSql[i] && (
                            <pre
                                style={{ backgroundColor: theme.primary, borderColor: theme.border, color: theme.accent }}
                                className="text-xs mt-1 p-3 rounded-lg border overflow-x-auto w-full"
                            >
                                {msg.sql}
                            </pre>
                        )}

                    </div>
                ))}

                {loading && (
                    <div className="flex justify-start">
                        <div
                            style={{ backgroundColor: theme.secondary, borderColor: theme.border }}
                            className="border px-4 py-3 rounded-2xl text-sm text-gray-400"
                        >
                            <span className="animate-pulse">Thinking...</span>
                        </div>
                    </div>
                )}

                <div ref={messagesEndRef} />
            </div>

            {/* Suggested questions — only show at start */}
            {messages.length === 1 && (
                <div className="flex flex-wrap gap-2 mb-4">
                    {SUGGESTED_QUESTIONS.map((q, i) => (
                        <button
                            key={i}
                            onClick={() => sendMessage(q)}
                            style={{ borderColor: theme.border, color: theme.accent, backgroundColor: theme.secondary }}
                            className="text-xs px-3 py-1.5 rounded-full border hover:opacity-80 transition-opacity"
                        >
                            {q}
                        </button>
                    ))}
                </div>
            )}

            {/* Input */}
            <div
                style={{ backgroundColor: theme.secondary, borderColor: theme.border }}
                className="flex items-center gap-3 border rounded-xl px-4 py-3"
            >
                <input
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Ask about scores, standings, or goal scorers..."
                    className="flex-1 bg-transparent text-white text-sm outline-none placeholder-white"
                />
                <button
                    onClick={() => sendMessage()}
                    disabled={!input.trim() || loading}
                    style={{ backgroundColor: theme.accent, color: theme.primary }}
                    className="px-4 py-1.5 rounded-lg text-sm font-semibold disabled:opacity-50 transition-opacity"
                >
                    Send
                </button>
            </div>
        </div>
    )
}