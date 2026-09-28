import React, { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Send,
  Square,
  Bot,
  User,
  ShieldAlert,
  Plus,
  MessageSquare,
} from 'lucide-react'
import { api } from '../services/api'
import type { CopilotQueryResponse, SourceCitation } from '../types'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: SourceCitation[]
  latencies?: {
    total: number
    embed: number
    retrieval: number
    generation: number
  }
  insufficientEvidence?: boolean
  model?: string | null
  offline?: boolean
}

export const CopilotPage: React.FC = () => {
  const queryClient = useQueryClient()
  const [question, setQuestion] = useState('')
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [selectedSource, setSelectedSource] = useState<SourceCitation | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Fetch conversations
  const { data: conversations, isLoading: convsLoading } = useQuery({
    queryKey: ['conversations'],
    queryFn: () => api.listConversations(30),
  })

  // Load conversation details when activeConversationId changes
  useEffect(() => {
    if (!activeConversationId) {
      setMessages([])
      return
    }
    api.getConversation(activeConversationId).then((detail) => {
      if (detail && detail.messages) {
        setMessages(
          detail.messages.map((m) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            sources: m.sources || undefined,
          }))
        )
      }
    }).catch((err) => {
      console.error('Failed to load conversation messages:', err)
    })
  }, [activeConversationId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Copilot Query Mutation
  const queryMutation = useMutation({
    mutationFn: (q: string) => {
      const controller = new AbortController()
      abortControllerRef.current = controller
      return api.queryCopilot(
        {
          question: q,
          conversation_id: activeConversationId,
          max_sources: 5,
        },
        controller.signal
      )
    },
    onSuccess: (data: CopilotQueryResponse) => {
      if (!activeConversationId && data.conversation_id) {
        setActiveConversationId(data.conversation_id)
        queryClient.invalidateQueries({ queryKey: ['conversations'] })
      }

      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: data.answer,
        sources: data.sources,
        latencies: {
          total: data.total_latency_ms ?? (data as any).total_duration_ms ?? 0,
          embed: data.embedding_latency_ms ?? (data as any).embed_duration_ms ?? 0,
          retrieval: data.retrieval_latency_ms ?? (data as any).retrieval_duration_ms ?? 0,
          generation: data.generation_latency_ms ?? (data as any).generation_duration_ms ?? 0,
        },
        insufficientEvidence: data.insufficient_evidence,
        model: data.model_used,
        offline: data.offline_mode,
      }

      setMessages((prev) => [...prev, assistantMsg])
      abortControllerRef.current = null
    },
    onError: (err: any) => {
      if (err.name === 'AbortError') return
      const errorMsg: ChatMessage = {
        id: `err-${Date.now()}`,
        role: 'assistant',
        content: `Query Error: ${err.message || 'Unable to execute grounded retrieval over local memory.'}`,
      }
      setMessages((prev) => [...prev, errorMsg])
      abortControllerRef.current = null
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = question.trim()
    if (!trimmed || queryMutation.isPending) return

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: trimmed,
    }
    setMessages((prev) => [...prev, userMsg])
    setQuestion('')
    queryMutation.mutate(trimmed)
  }

  const handleCancel = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
  }

  const handleNewChat = () => {
    handleCancel()
    setActiveConversationId(null)
    setMessages([])
  }

  return (
    <div className="flex flex-col lg:flex-row gap-6 h-[calc(100vh-8.5rem)]">
      {/* Conversations History Sidebar */}
      <aside className="w-full lg:w-64 flex flex-col bg-industrial-900/70 border border-white/10 rounded-xl p-3 shrink-0">
        <button
          onClick={handleNewChat}
          className="flex items-center justify-center gap-2 w-full py-2 px-3 rounded-lg bg-sky-500/15 border border-sky-500/30 hover:bg-sky-500/25 text-sky-300 text-xs font-semibold transition-all mb-3"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>New Session</span>
        </button>

        <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500 px-2 mb-1">
          Recent Conversations
        </div>

        <div className="flex-1 overflow-y-auto space-y-1 pr-1">
          {convsLoading ? (
            <div className="text-xs text-slate-500 text-center py-4 font-mono">Loading sessions...</div>
          ) : !conversations || conversations.length === 0 ? (
            <div className="text-xs text-slate-600 text-center py-6 font-mono">No previous sessions</div>
          ) : (
            conversations.map((conv) => (
              <button
                key={conv.id}
                onClick={() => setActiveConversationId(conv.id)}
                className={`w-full text-left p-2 rounded-lg text-xs font-mono transition-colors flex items-center gap-2 truncate ${
                  activeConversationId === conv.id
                    ? 'bg-sky-500/20 text-sky-200 border border-sky-500/40 font-semibold'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-white/5 border border-transparent'
                }`}
              >
                <MessageSquare className="w-3.5 h-3.5 shrink-0 opacity-60" />
                <span className="truncate">{conv.title || 'Technical Inquiry'}</span>
              </button>
            ))
          )}
        </div>
      </aside>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col bg-industrial-900/80 border border-white/10 rounded-xl overflow-hidden shadow-2xl">
        {/* Messages Stream */}
        <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center p-8 max-w-md mx-auto">
              <div className="p-3 rounded-2xl bg-sky-500/10 border border-sky-500/20 text-sky-400 mb-4">
                <Bot className="w-8 h-8" />
              </div>
              <h2 className="text-base font-semibold text-slate-100">Industrial Grounded AI Copilot</h2>
              <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                Queries are answered exclusively using local Qdrant Edge memory chunks and verified SQLite documents. No external cloud calls required.
              </p>
              <div className="mt-6 flex flex-wrap gap-2 justify-center">
                <button
                  onClick={() => setQuestion('What are the pump overheating parameters?')}
                  className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-slate-300 font-mono transition-colors"
                >
                  "Pump overheating parameters?"
                </button>
                <button
                  onClick={() => setQuestion('Bearing inspection procedure')}
                  className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-slate-300 font-mono transition-colors"
                >
                  "Bearing inspection procedure"
                </button>
              </div>
            </div>
          ) : (
            messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex gap-3.5 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                {msg.role === 'assistant' && (
                  <div className="w-7 h-7 rounded-lg bg-sky-500/20 border border-sky-500/30 text-sky-400 flex items-center justify-center shrink-0 mt-0.5">
                    <Bot className="w-4 h-4" />
                  </div>
                )}

                <div
                  className={`max-w-2xl rounded-xl p-4 text-xs leading-relaxed space-y-3 ${
                    msg.role === 'user'
                      ? 'bg-sky-600 text-white font-medium rounded-br-none'
                      : 'bg-industrial-950/70 border border-white/10 text-slate-200 rounded-bl-none'
                  }`}
                >
                  {/* Insufficient Evidence Warning Banner */}
                  {msg.insufficientEvidence && (
                    <div className="flex items-center gap-2 p-2 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 text-[11px]">
                      <ShieldAlert className="w-3.5 h-3.5 shrink-0" />
                      <span>
                        Insufficient Evidence: No local memory chunk exceeded retrieval threshold. Hallucination prevention applied.
                      </span>
                    </div>
                  )}

                  <div className="whitespace-pre-wrap font-sans text-sm">{msg.content}</div>

                  {/* Latency and Telemetry Bar */}
                  {msg.latencies && (
                    <div className="pt-2 border-t border-white/10 flex flex-wrap items-center gap-3 text-[10px] font-mono text-slate-400">
                      <span>Total: <strong className="text-slate-200">{(msg.latencies.total ?? 0).toFixed(0)}ms</strong></span>
                      <span>Embed: <strong className="text-slate-300">{(msg.latencies.embed ?? 0).toFixed(0)}ms</strong></span>
                      <span>Qdrant: <strong className="text-slate-300">{(msg.latencies.retrieval ?? 0).toFixed(0)}ms</strong></span>
                      <span>LLM: <strong className="text-slate-300">{(msg.latencies.generation ?? 0).toFixed(0)}ms</strong></span>
                      {msg.model && <span className="text-sky-400">Model: {msg.model}</span>}
                    </div>
                  )}

                  {/* Sources / Citations Section */}
                  {msg.sources && msg.sources.length > 0 && (
                    <div className="pt-2 border-t border-white/10 space-y-2">
                      <div className="text-[10px] font-mono font-semibold uppercase tracking-wider text-slate-400">
                        Verified Sources ({msg.sources.length}):
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {msg.sources.map((src, i) => {
                          const docName = src.filename || (src as any).document_filename || src.document_title || 'Document Chunk'
                          const scoreVal = src.relevance_score ?? (src as any).score ?? 0
                          const previewText = src.content_preview || (src as any).text || ''
                          const pageNum = src.page_start ?? (src as any).page_number
                          return (
                            <button
                              key={i}
                              type="button"
                              onClick={() => setSelectedSource(src)}
                              className="text-left p-2 rounded-lg bg-black/40 border border-white/5 hover:border-sky-500/30 transition-colors flex flex-col justify-between"
                            >
                              <div className="flex items-center justify-between w-full">
                                <span className="font-mono text-[10px] font-semibold text-slate-300 truncate max-w-[140px]">
                                  {docName}
                                </span>
                                <span className="text-[10px] font-mono text-emerald-400 font-bold">
                                  {(scoreVal * 100).toFixed(0)}%
                                </span>
                              </div>
                              {pageNum !== undefined && (
                                <div className="text-[10px] font-mono text-slate-500 mt-0.5">
                                  Page {pageNum} • Score: {scoreVal.toFixed(2)}
                                </div>
                              )}
                              <p className="text-[11px] text-slate-400 line-clamp-2 mt-1">
                                {previewText}
                              </p>
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>

                {msg.role === 'user' && (
                  <div className="w-7 h-7 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 flex items-center justify-center shrink-0 mt-0.5">
                    <User className="w-4 h-4" />
                  </div>
                )}
              </div>
            ))
          )}

          {queryMutation.isPending && (
            <div className="flex gap-3">
              <div className="w-7 h-7 rounded-lg bg-sky-500/20 border border-sky-500/30 text-sky-400 flex items-center justify-center shrink-0">
                <Bot className="w-4 h-4" />
              </div>
              <div className="bg-industrial-950/70 border border-white/10 rounded-xl p-4 text-xs font-mono text-slate-400 flex items-center gap-3">
                <div className="w-2 h-2 rounded-full bg-sky-400 animate-ping" />
                <span>Running grounded retrieval and local Ollama inference...</span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar */}
        <form onSubmit={handleSubmit} className="p-3 bg-industrial-950/80 border-t border-white/10 flex items-center gap-3">
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask maintenance or operating procedures..."
            disabled={queryMutation.isPending}
            className="flex-1 bg-industrial-900 border border-white/10 rounded-xl px-4 py-2.5 text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-sky-500/40 font-mono transition-colors disabled:opacity-50"
          />

          {queryMutation.isPending ? (
            <button
              type="button"
              onClick={handleCancel}
              className="p-2.5 rounded-xl bg-rose-600 hover:bg-rose-500 text-white transition-colors"
              title="Cancel Generation"
            >
              <Square className="w-4 h-4" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!question.trim()}
              className="p-2.5 rounded-xl bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold disabled:opacity-40 transition-colors shadow-md shadow-sky-500/20"
              title="Send Inquiry"
            >
              <Send className="w-4 h-4" />
            </button>
          )}
        </form>
      </div>

      {/* Source Citation Modal */}
      {selectedSource && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/80 backdrop-blur-sm" onClick={() => setSelectedSource(null)} />
          <div className="relative bg-industrial-900 border border-white/10 rounded-xl max-w-lg w-full p-6 shadow-2xl z-10 space-y-4">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <div>
                <span className="text-[10px] font-mono uppercase text-sky-400 font-semibold block mb-0.5">
                  Source Evidence Traceability
                </span>
                <h3 className="text-sm font-semibold text-slate-100">
                  {selectedSource.filename || (selectedSource as any).document_filename || 'Source Reference'}
                </h3>
                <span className="text-[11px] font-mono text-slate-400">
                  Chunk ID: {selectedSource.chunk_id || 'unknown'}
                </span>
              </div>
              <button
                type="button"
                onClick={() => setSelectedSource(null)}
                className="text-slate-500 hover:text-slate-300 p-1"
              >
                ✕
              </button>
            </div>

            <div className="p-3 bg-black/40 border border-white/5 rounded-lg text-xs font-mono text-slate-200 leading-relaxed max-h-60 overflow-y-auto whitespace-pre-wrap">
              {selectedSource.content_preview || (selectedSource as any).text}
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs font-mono text-slate-400 pt-2 border-t border-white/10">
              <div>Relevance: <strong className="text-emerald-400">{(((selectedSource.relevance_score ?? (selectedSource as any).score) || 0) * 100).toFixed(1)}%</strong></div>
              <div>Page: <strong className="text-slate-200">{selectedSource.page_start || (selectedSource as any).page_number || 'N/A'}</strong></div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
