import React, { useMemo, useState } from 'react';
import { Download } from 'lucide-react';
import { defineMessages, useIntl } from '../i18n';
import {
  artifactDownloadsEnabled,
  artifactExtension,
  artifactFilename,
  artifactFilesystemPath,
  artifactReadableName,
  findDownloadableArtifactPaths,
} from '../utils/artifactPaths';

const i18n = defineMessages({
  download: {
    id: 'artifactPathLink.download',
    defaultMessage: 'Download {filename}',
  },
  action: {
    id: 'artifactPathLink.action',
    defaultMessage: 'Download',
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
  typeExcel: { id: 'artifactPathLink.typeExcel', defaultMessage: 'Excel workbook' },
  typeWord: { id: 'artifactPathLink.typeWord', defaultMessage: 'Word document' },
  typePdf: { id: 'artifactPathLink.typePdf', defaultMessage: 'PDF document' },
  typeCalendar: { id: 'artifactPathLink.typeCalendar', defaultMessage: 'Calendar file (ICS)' },
  typeCsv: { id: 'artifactPathLink.typeCsv', defaultMessage: 'CSV table' },
  typeFile: { id: 'artifactPathLink.typeFile', defaultMessage: 'Generated file' },
});

type ArtifactMessage = (typeof i18n)[keyof typeof i18n];

// The web build ships no compiled catalogs, so react-intl would fall back to
// English for zh-HK users. These mirror messages/zh-TW.json; a loaded catalog
// still takes precedence.
const TRADITIONAL_CHINESE: Record<string, string> = {
  'artifactPathLink.download': '下載 {filename}',
  'artifactPathLink.action': '下載',
  'artifactPathLink.preparing': '正在準備下載…',
  'artifactPathLink.failedTitle': '下載失敗',
  'artifactPathLink.failedMessage':
    '未能下載已產生的文件。文件可能已被清除或失效，請在對話中要求重新匯出。',
  'artifactPathLink.typeExcel': 'Excel 試算表',
  'artifactPathLink.typeWord': 'Word 文件',
  'artifactPathLink.typePdf': 'PDF 文件',
  'artifactPathLink.typeCalendar': '日曆檔（ICS）',
  'artifactPathLink.typeCsv': 'CSV 表格',
  'artifactPathLink.typeFile': '已產生的文件',
};

function useArtifactMessages() {
  const intl = useIntl();
  const traditional = /^zh-(hk|tw|mo|hant)\b/i.test(intl.locale);
  return (message: ArtifactMessage, values?: Record<string, string>) => {
    const fallback = TRADITIONAL_CHINESE[message.id];
    if (traditional && fallback && !intl.messages[message.id]) {
      return intl.formatMessage({ id: message.id, defaultMessage: fallback }, values);
    }
    return intl.formatMessage(message, values);
  };
}

const TYPE_MESSAGES: Record<string, ArtifactMessage> = {
  xlsx: i18n.typeExcel,
  xls: i18n.typeExcel,
  docx: i18n.typeWord,
  doc: i18n.typeWord,
  pdf: i18n.typePdf,
  ics: i18n.typeCalendar,
  csv: i18n.typeCsv,
};

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
  const t = useArtifactMessages();
  const [isDownloading, setIsDownloading] = useState(false);
  const filesystemPath = artifactFilesystemPath(path);
  const filename = artifactFilename(filesystemPath);
  const linkText = typeof children === 'string' ? children.trim() : '';
  const displayFilename = linkText || filename;
  const extension = artifactExtension(filename);
  const typeLabel = t(TYPE_MESSAGES[extension] ?? i18n.typeFile);
  // Storage names carry hashes and timestamps; show the file type plus any
  // readable part of the name, and keep the exact path in the tooltip.
  const readableName =
    linkText && !linkText.includes('/') && linkText !== filename
      ? linkText
      : artifactReadableName(filename);

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
        title: t(i18n.failedTitle),
        message: t(i18n.failedMessage),
        detail: filename,
      });
    } finally {
      setIsDownloading(false);
    }
  };

  const variant = compact ? (inverted ? 'is-compact is-inverted' : 'is-compact') : 'is-result';

  return (
    <a
      href={filesystemPath}
      title={filename}
      aria-label={t(i18n.download, { filename: displayFilename })}
      aria-busy={isDownloading}
      aria-disabled={isDownloading}
      data-artifact-path={filesystemPath}
      className={`artifact-link ${variant}`}
      onClick={(event) => void handleDownload(event)}
    >
      {compact ? (
        <>
          <Download className="artifact-link-icon" aria-hidden="true" />
          <span className="artifact-link-label">
            {isDownloading
              ? t(i18n.preparing)
              : readableName
                ? `${typeLabel} · ${readableName}`
                : typeLabel}
          </span>
        </>
      ) : (
        <>
          <span className="artifact-link-type" aria-hidden="true">
            {extension.toUpperCase() || '—'}
          </span>
          <span className="artifact-link-text">
            <strong>{typeLabel}</strong>
            {readableName && <small>{readableName}</small>}
          </span>
          <span className="artifact-link-action" aria-hidden="true">
            <Download className="artifact-link-icon" />
            {isDownloading ? t(i18n.preparing) : t(i18n.action)}
          </span>
        </>
      )}
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
    content.push(
      <ArtifactPathLink key={`${match.start}:${match.path}`} path={match.path} compact />
    );
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
    <div className="artifact-link-list">
      {matches.map((match) => (
        <ArtifactPathLink key={match.path} path={match.path} compact inverted />
      ))}
    </div>
  );
}
