import { useEffect, useRef } from 'react';
import { ChevronDown, LogOut, Settings2 } from 'lucide-react';

interface AccountControls {
  name: string;
  email: string;
  role: 'ADMIN' | 'MEMBER';
  openSettings: () => void;
  logout: () => Promise<void>;
}

/** The signed-in local account (provided by the web host): settings and sign-out. */
export function AccountMenu() {
  const account = (window as Window & { ngopilotAccount?: AccountControls }).ngopilotAccount;
  const menu = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (event: Event) => {
      const details = menu.current;
      if (!details?.open) return;
      if (event instanceof KeyboardEvent ? event.key === 'Escape' : !details.contains(event.target as Node)) details.open = false;
    };
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', close);
    return () => { document.removeEventListener('pointerdown', close); document.removeEventListener('keydown', close); };
  }, []);
  if (!account) return null;
  const choose = (action: () => void) => { if (menu.current) menu.current.open = false; action(); };
  return <details className="ngo-account-menu" ref={menu}>
    <summary aria-label="帳號選單"><span className="ngo-account-avatar" aria-hidden="true">{account.name.slice(0, 1)}</span><span className="ngo-account-name">{account.name}</span><ChevronDown size={15} aria-hidden="true" /></summary>
    <div className="ngo-account-list" role="menu">
      <p>{account.email}<span>{account.role === 'ADMIN' ? '管理員' : '成員'}</span></p>
      <button type="button" role="menuitem" onClick={() => choose(account.openSettings)}><Settings2 size={16} />帳號設定</button>
      <button type="button" role="menuitem" onClick={() => choose(() => void account.logout())}><LogOut size={16} />登出</button>
    </div>
  </details>;
}
