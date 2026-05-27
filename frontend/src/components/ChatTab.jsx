import { useState, useEffect, useRef } from 'react';

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const SUGGESTED_QUESTIONS = [
    "Who scored in Arsenal's last game?",
    "Which games are live right now?",
    "Show me the Bundesliga top 5",
    "How many goals were scored today?",
    "Which team has the best goal difference in Serie A?",
    "Did anyone score a penalty in Ligue 1 today?",
]

export default function ChatTab({ theme }) {
    const [messages, setMessages] = useState([{
        role: "assistant",
        content: "Hi! I'm your football assistant. Ask me anything about live scores, goal scorers, or current standings in the Top 5 European Leagues, and I'll do my best to help you out!"
    }]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const messagesEndRef = useRef(null);

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

            const data = await response.json();
            setMessages(prev => [...prev, { role: "assistant", content: data.answer }]);
        } catch (error) {
            console.error('Error sending message:', error);
            setMessages(prev => [...prev, { role: "assistant", content: "Sorry, something went wrong. Please try again." }]);
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
        <div className="max-w-4xl mx-auto flex flex-col" style={{ height: 'calc(100vh - 180px)' }}>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto space-y-4 pb-4">
                {messages.map((msg, i) => (
                    <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                        <div
                            style={msg.role === 'user'
                                ? { backgroundColor: theme.accent, color: theme.primary }
                                : { backgroundColor: theme.secondary, color: 'white', borderColor: theme.border }
                            }
                            className={`max-w-xs lg:max-w-md px-4 py-3 rounded-2xl text-sm ${
                                msg.role === 'assistant' ? 'border' : ''
                            }`}
                        >
                            {msg.content.split('\n').map((line, i) => (
                                <span key={i}>
                                    {line}
                                    {i < msg.content.split('\n').length - 1 && <br />}
                                </span>
                            ))}
                        </div>
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
                    className="flex-1 bg-transparent text-white text-sm outline-none placeholder-gray-500"
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