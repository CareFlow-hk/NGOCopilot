import React, { useMemo, useState } from 'react';
import { Download } from 'lucide-react';
import { defineMessages, useIntl } from '../i18n';
import {
  artifactDownloadsEnabled,
  artifactFilename,
  artifactFilesystemPath,
  findDownloadableArtifactPaths,
} from '../utils/artifactPaths';

const i18n = defineMessages({
  download: {
    id: 'artifactPathLink.download',
    defaultMessage: 'Download {filename}',
  },
  preparing: {
    id: 'artifactPathLink.preparing',
    defaultMessage: 'Preparing download...',
  },
  failedTitle: {
    id: 'artifactPathLink.failedTitle',
    defaultMessage: 'Download Failed',
  },
  failedMessage: {
    id: 'artifactPathLink.failedMessage',
    defaultMessage: 'The generated file could not be downloaded.',
  },
});

interface ArtifactPathLinkProps {
  path: string;
  children?: React.ReactNode;
  compact?: boolean;
  inverted?: boolean;
}

export function ArtifactPathLink({
  path,
  children,
  compact = false,
  inverted = false,
}: ArtifactPathLinkProps) {
  const intl = useIntl();
  const [isDownloading, setIsDownloading] = useState(false);
  const filesystemPath = artifactFilesystemPath(path);
  const filename = artifactFilename(filesystemPath);
  const displayFilename = typeof children === 'string' && children.trim() ? children : filename;
  const appearance = compact
    ? inverted
      ? 'border-gray-600 bg-gray-800 text-gray-100 hover:bg-gray-700 focus-visible:ring-gray-400'
      : 'border-border-primary bg-background-secondary text-text-primary hover:bg-background-primary focus-visible:ring-border-primary'
    : 'border-cinnabar-600 bg-cinnabar-600 text-paper-50 hover:border-cinnabar-700 hover:bg-cinnabar-700 active:border-cinnabar-700 active:bg-cinnabar-700 focus-visible:ring-cinnabar-400 focus-visible:ring-offset-2 focus-visible:ring-offset-background-primary';
  const sizing = compact
    ? 'my-0.5 gap-1.5 px-2 py-1 text-xs'
    : 'my-2 min-h-12 w-fit gap-3 px-4 py-3 text-sm sm:text-base';

  const handleDownload = async (event: React.MouseEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (isDownloading) return;

    setIsDownloading(true);
    try {
      await window.electron.openExternal(filesystemPath);
    } catch {
      await window.electron.showMessageBox({
        type: 'error',
        buttons: ['OK'],
        title: intl.formatMessage(i18n.failedTitle),
        message: intl.formatMessage(i18n.failedMessage),
        detail: filename,
      });
    } finally {
      setIsDownloading(false);
    }
  };

  return (
    <a
      href={filesystemPath}
      title={filesystemPath}
      aria-label={intl.formatMessage(i18n.download, { filename: displayFilename })}
      aria-busy={isDownloading}
      aria-disabled={isDownloading}
      data-artifact-path={filesystemPath}
      className={`inline-flex max-w-full cursor-pointer items-center rounded-md border align-middle font-sans font-semibold no-underline transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 aria-disabled:pointer-events-none aria-disabled:opacity-70 ${sizing} ${appearance}`}
      onClick={(event) => void handleDownload(event)}
    >
      <span
        className={
          compact
            ? 'flex h-5 w-5 flex-shrink-0 items-center justify-center'
            : 'flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md bg-paper-50/15'
        }
        aria-hidden="true"
      >
        <Download className={compact ? 'h-3.5 w-3.5' : 'h-5 w-5'} />
      </span>
      <span className={compact ? 'truncate' : 'min-w-0 overflow-wrap-anywhere text-left'}>
        {isDownloading
          ? intl.formatMessage(i18n.preparing)
          : intl.formatMessage(i18n.download, {
              filename: children ?? filename,
            })}
      </span>
    </a>
  );
}

export function ArtifactText({ text }: { text: string }) {
  const matches = useMemo(
    () => (artifactDownloadsEnabled() ? findDownloadableArtifactPaths(text) : []),
    [text]
  );

  if (matches.length === 0) return <>{text}</>;

  const content: React.ReactNode[] = [];
  let cursor = 0;
  for (const match of matches) {
    if (match.start > cursor) content.push(text.slice(cursor, match.start));
    content.push(<ArtifactPathLink key={`${match.start}:${match.path}`} path={match.path} />);
    cursor = match.end;
  }
  if (cursor < text.length) content.push(text.slice(cursor));

  return <>{content}</>;
}

export function ArtifactLinkList({ text }: { text: string }) {
  const matches = useMemo(() => {
    if (!artifactDownloadsEnabled()) return [];
    const unique = new Map<string, ReturnType<typeof findDownloadableArtifactPaths>[number]>();
    for (const match of findDownloadableArtifactPaths(text)) unique.set(match.path, match);
    return [...unique.values()];
  }, [text]);

  if (matches.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 border-b border-gray-700 bg-gray-800 px-3 py-2 font-sans text-xs text-gray-200">
      {matches.map((match) => (
        <ArtifactPathLink key={match.path} path={match.path} compact inverted />
      ))}
    </div>
  );
}
