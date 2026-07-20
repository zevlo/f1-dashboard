import { beforeEach, describe, expect, it } from 'vitest'
import { useAgentStore } from './agentStore'

beforeEach(() => {
  useAgentStore.getState().clear()
})

describe('agentStore', () => {
  it('pushes a user message and enters thinking state', () => {
    useAgentStore.getState().pushUserMessage('why is VER slow?')
    const s = useAgentStore.getState()
    expect(s.messages).toHaveLength(1)
    expect(s.messages[0].role).toBe('user')
    expect(s.messages[0].text).toBe('why is VER slow?')
    expect(s.thinking).toBe(true)
  })

  it('streams tokens into a single assistant message', () => {
    const { pushUserMessage, beginAssistantStream, appendToken, finalizeStream } =
      useAgentStore.getState()
    pushUserMessage('hello')
    beginAssistantStream('msg-1')
    appendToken('msg-1', 'Hello ')
    appendToken('msg-1', 'world')
    expect(useAgentStore.getState().messages[1].text).toBe('Hello world')
    expect(useAgentStore.getState().messages[1].streaming).toBe(true)
    expect(useAgentStore.getState().streamingId).toBe('msg-1')
    finalizeStream('msg-1')
    expect(useAgentStore.getState().messages[1].streaming).toBe(false)
    expect(useAgentStore.getState().streamingId).toBeNull()
  })

  it('beginAssistantStream clears thinking state', () => {
    const { pushUserMessage, beginAssistantStream } = useAgentStore.getState()
    pushUserMessage('hi')
    expect(useAgentStore.getState().thinking).toBe(true)
    beginAssistantStream('msg-1')
    expect(useAgentStore.getState().thinking).toBe(false)
  })

  it('marks error and clears streaming on agent.error', () => {
    const { beginAssistantStream, markError } = useAgentStore.getState()
    beginAssistantStream('msg-1')
    useAgentStore.getState().appendToken('msg-1', 'partial…')
    markError('msg-1', 'upstream timeout')
    const m = useAgentStore.getState().messages[0]
    expect(m.text).toBe('partial…') // keeps partial text
    expect(m.streaming).toBe(false)
    expect(useAgentStore.getState().streamingId).toBeNull()
    expect(useAgentStore.getState().thinking).toBe(false)
  })

  it('appendToken ignores messages that arent the active stream', () => {
    const { beginAssistantStream, appendToken } = useAgentStore.getState()
    beginAssistantStream('msg-1')
    appendToken('msg-OTHER', 'should be ignored')
    expect(useAgentStore.getState().messages[0].text).toBe('')
  })

  it('clear resets all state', () => {
    const { pushUserMessage, beginAssistantStream } = useAgentStore.getState()
    pushUserMessage('hi')
    beginAssistantStream('msg-1')
    useAgentStore.getState().clear()
    expect(useAgentStore.getState().messages).toEqual([])
    expect(useAgentStore.getState().streamingId).toBeNull()
    expect(useAgentStore.getState().thinking).toBe(false)
  })
})
