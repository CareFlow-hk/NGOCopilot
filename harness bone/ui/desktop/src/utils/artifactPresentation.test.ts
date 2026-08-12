import { describe, expect, it } from 'vitest';
import type { Message } from '../types/message';
import { artifactPresentationForMessage, isLastUserVisibleOutput } from './artifactPresentation';

function message(role: Message['role'], content: Message['content'], userVisible = true): Message {
  return {
    role,
    content,
    created: 1,
    metadata: { userVisible, agentVisible: true },
  };
}

describe('artifact result presentation', () => {
  it('ignores later tool responses when locating the last assistant output', () => {
    const messages = [
      message('assistant', [
        { type: 'text', text: 'File ready: /data/result.xlsx' },
        { type: 'toolRequest', id: 'export-1', toolCall: {} },
      ]),
      message('user', [{ type: 'toolResponse', id: 'export-1', toolResult: { status: 'ok' } }]),
    ];

    expect(isLastUserVisibleOutput(messages, 0)).toBe(true);
  });

  it('keeps every earlier assistant output from using the result wrapper', () => {
    const messages = [
      message('assistant', [{ type: 'text', text: 'First /data/first.xlsx' }]),
      message('assistant', [{ type: 'text', text: 'Last /data/last.xlsx' }]),
    ];

    expect(isLastUserVisibleOutput(messages, 0)).toBe(false);
    expect(isLastUserVisibleOutput(messages, 1)).toBe(true);
  });

  it('does not promote an output when a later user message is visible', () => {
    const messages = [
      message('assistant', [{ type: 'text', text: 'Result /data/result.xlsx' }]),
      message('user', [{ type: 'text', text: 'Make another one' }]),
    ];

    expect(isLastUserVisibleOutput(messages, 0)).toBe(false);
  });

  it('promotes only a completed, non-streaming last output', () => {
    expect(
      artifactPresentationForMessage({
        isStreaming: false,
        isLastUserVisibleOutput: true,
        toolRequestCount: 1,
        completedToolRequestCount: 1,
      })
    ).toBe('result');

    for (const input of [
      {
        isStreaming: true,
        isLastUserVisibleOutput: true,
        toolRequestCount: 1,
        completedToolRequestCount: 1,
      },
      {
        isStreaming: false,
        isLastUserVisibleOutput: false,
        toolRequestCount: 1,
        completedToolRequestCount: 1,
      },
      {
        isStreaming: false,
        isLastUserVisibleOutput: true,
        toolRequestCount: 1,
        completedToolRequestCount: 0,
      },
    ]) {
      expect(artifactPresentationForMessage(input)).toBe('compact');
    }
  });
});
