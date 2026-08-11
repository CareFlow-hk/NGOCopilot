const TENANT_FILE_PATH_PATTERN = /\/data\/tenants\/[^\r\n"'`<>[\]{}|\\]+/g;
const NATIVE_DOWNLOAD_PATH_PATTERN = /\/api\/files\/[^\s"'`<>[\]{}|\\]+/g;
const TRAILING_PROSE_PUNCTUATION = /[),.;:!?]+$/;
const INTERNAL_WORKFLOW_PATH_SEGMENTS = [
  '/inputs/',
  '/intermediate/',
  '/logs/',
  '/runtimes/',
  '/app-data/',
];

export interface ArtifactPathMatch {
  path: string;
  filename: string;
  start: number;
  end: number;
}

export function artifactDownloadsEnabled(): boolean {
  return window.appConfig?.get('NGOPILOT_CLOUD') === true;
}

export function artifactFilename(path: string): string {
  const encoded = path.split('/').pop() || 'download';
  try {
    return decodeURIComponent(encoded);
  } catch {
    return encoded;
  }
}

export function artifactFilesystemPath(path: string): string {
  try {
    return decodeURIComponent(path);
  } catch {
    return path;
  }
}

export function findArtifactPaths(text: string): ArtifactPathMatch[] {
  const matches: ArtifactPathMatch[] = [];

  for (const match of text.matchAll(TENANT_FILE_PATH_PATTERN)) {
    const matchedText = match[0];
    const path = matchedText.trimEnd().replace(TRAILING_PROSE_PUNCTUATION, '');
    const start = match.index ?? 0;
    const filename = artifactFilename(path);

    if (INTERNAL_WORKFLOW_PATH_SEGMENTS.some((segment) => path.includes(segment))) continue;

    matches.push({
      path,
      filename,
      start,
      end: start + path.length,
    });
  }

  return matches;
}

function nativeDownloadPaths(text: string): ArtifactPathMatch[] {
  return [...text.matchAll(NATIVE_DOWNLOAD_PATH_PATTERN)].map((match) => {
    const matchedText = match[0];
    const path = matchedText.replace(TRAILING_PROSE_PUNCTUATION, '');
    const start = match.index ?? 0;
    return {
      path,
      filename: artifactFilename(path),
      start,
      end: start + path.length,
    };
  });
}

function resolveNativeDownload(
  nativePath: ArtifactPathMatch,
  artifacts: ArtifactPathMatch[]
): ArtifactPathMatch | null {
  const candidates = artifacts.filter(
    (artifact) =>
      artifact.filename === nativePath.filename ||
      artifact.filename.endsWith(`_${nativePath.filename}`)
  );
  return candidates.length === 1 ? candidates[0] : null;
}

/**
 * Find links that the cloud host can actually download. Native `/api/files/...`
 * routes are resolved only when the same response contains one unambiguous
 * promoted tenant artifact, so stale or fabricated native URLs never become links.
 */
export function findDownloadableArtifactPaths(
  text: string,
  artifacts: ArtifactPathMatch[] = findArtifactPaths(text)
): ArtifactPathMatch[] {
  const matches = [...findArtifactPaths(text)];
  for (const nativePath of nativeDownloadPaths(text)) {
    const artifact = resolveNativeDownload(nativePath, artifacts);
    if (!artifact) continue;
    matches.push({
      ...nativePath,
      path: artifact.path,
    });
  }
  return matches.sort((left, right) => left.start - right.start);
}

export function isArtifactPath(value: string): boolean {
  const matches = findArtifactPaths(value);
  return matches.length === 1 && matches[0].start === 0 && matches[0].end === value.length;
}
