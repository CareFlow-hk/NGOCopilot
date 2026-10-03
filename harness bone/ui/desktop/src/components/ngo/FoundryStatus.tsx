import { useRef } from 'react';
import { Settings2, X } from 'lucide-react';

export function FoundryStatus({ banner = false }: { banner?: boolean }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const configured = window.appConfig?.get('NGOPILOT_MODEL_CONFIGURED') !== false;
  return <>
    {banner ? !configured && <div className="ngo-setup-notice" role="status">
      <div><strong>完成模型設定後，即可開始對話</strong><p>歷史記錄與已產生的文件仍可查看。請由管理員填入 Foundry API Key。</p></div>
      <button onClick={() => dialog.current?.showModal()}>查看設定方式</button>
    </div> : <button className={`ngo-model-status ${configured ? '' : 'is-pending'}`} onClick={() => dialog.current?.showModal()} aria-label="Foundry 模型設定">
      <span className="ngo-status-dot" /> <span>Luna <span className="ngo-model-detail">· {configured ? '已配置' : '待配置'}</span></span><Settings2 size={15} />
    </button>}
    <dialog ref={dialog} className="ngo-config-dialog">
      <div className="ngo-dialog-title"><h2>Foundry 模型設定</h2><button aria-label="關閉模型設定" onClick={() => dialog.current?.close()}><X size={20} /></button></div>
      <p>聊天、文字整理與圖片辨識使用同一個部署。API Key 只保存在伺服器，不會在此頁輸入或顯示。</p>
      <dl><dt>部署名稱</dt><dd>{String(window.appConfig?.get('NGOPILOT_MODEL_NAME') || 'gpt-6-luna')}</dd><dt>本機設定檔</dt><dd><code>.local-agent/foundry.env</code></dd><dt>需要填寫</dt><dd><code>FOUNDRY_API_KEY</code></dd></dl>
      <p>填入後，在 NGOPilot 目錄執行 <code>scripts/restart-agent.sh</code>，再重新整理此頁。未配置時不會呼叫模型，也不會改用其他供應商。</p>
      <p className="ngo-config-note">錄音請先轉為 TXT 或 DOCX 文字稿；Luna 不提供錄音轉寫。</p>
      <button className="ngo-primary-button" onClick={() => dialog.current?.close()}>知道了</button>
    </dialog>
  </>;
}
