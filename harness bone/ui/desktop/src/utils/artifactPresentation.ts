import type { Message } from '../types/message';

export function isLastUserVisibleOutput(messages: Message[], index: number): boolean {
  return !messages
    .slice(index + 1)
    .some(
      (candidate) =>
        candidate.metadata.userVisible &&
        !candidate.content.every((content) => content.type === 'toolResponse')
    );
}

export function artifactPresentationForMessage({
  isStreaming,
  isLastUserVisibleOutput,
  toolRequestCount,
  completedToolRequestCount,
}: {
  isStreaming: boolean;
  isLastUserVisibleOutput: boolean;
  toolRequestCount: number;
  completedToolRequestCount: number;
}): 'compact' | 'result' {
  const toolCallsComplete =
    toolRequestCount === 0 || completedToolRequestCount === toolRequestCount;
  return !isStreaming && isLastUserVisibleOutput && toolCallsComplete ? 'result' : 'compact';
}
