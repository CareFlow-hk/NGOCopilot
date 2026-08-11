import { describe, expect, it } from 'vitest';
import { findArtifactPaths, findDownloadableArtifactPaths } from './artifactPaths';

describe('artifact path discovery', () => {
  const artifactPath =
    '/data/tenants/e6300d72-5803-4b89-b56d-d63da2934748/workflow/jobs/careflow_paper_forms_to_excel/job_82560afe60fb47c99598dcf7464a6d0c/outputs/ff3f0f660050_batch_4_20260806_135134.xlsx';

  it('resolves a native CareFlow download path to the promoted Excel artifact', () => {
    const text = [
      '**Download**: /api/files/exports/batch_4_20260806_135134.xlsx',
      `**Local path**: ${artifactPath}`,
    ].join('\n');

    expect(findDownloadableArtifactPaths(text)).toEqual([
      expect.objectContaining({
        path: artifactPath,
        filename: 'batch_4_20260806_135134.xlsx',
      }),
      expect.objectContaining({
        path: artifactPath,
        filename: 'ff3f0f660050_batch_4_20260806_135134.xlsx',
      }),
    ]);
  });

  it('does not make a native route clickable without one unambiguous artifact', () => {
    const nativePath = '/api/files/exports/report.xlsx';
    const first = '/data/tenants/user/workflow/jobs/job-1/outputs/a_report.xlsx';
    const second = '/data/tenants/user/workflow/jobs/job-2/outputs/b_report.xlsx';

    expect(findDownloadableArtifactPaths(nativePath)).toEqual([]);
    expect(findDownloadableArtifactPaths(`${nativePath}\n${first}\n${second}`)).toEqual(
      findArtifactPaths(`${nativePath}\n${first}\n${second}`)
    );
  });
});
