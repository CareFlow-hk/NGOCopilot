import React, { useEffect, useState } from 'react';
import { IpcRendererEvent } from 'electron';
import { Outlet, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Footprints, Menu, PanelLeft } from 'lucide-react';
import { defineMessages, useIntl } from '../../i18n';
import { Button } from '../ui/button';
import ChatSessionsContainer from '../ChatSessionsContainer';
import { useChatContext } from '../../contexts/ChatContext';
import { NavigationProvider, useNavigationContext } from './NavigationContext';
import { Navigation } from './NavigationPanel';
import { NAV_DIMENSIONS, Z_INDEX } from './constants';
import { cn } from '../../utils';
import { FoundryStatus } from '../ngo/FoundryStatus';
import { AccountMenu } from '../ngo/AccountMenu';
import { UserInput } from '../../types/message';

const i18n = defineMessages({
  openNavigation: {
    id: 'appLayout.openNavigation',
    defaultMessage: 'Open navigation',
  },
  collapseNavigation: {
    id: 'appLayout.collapseNavigation',
    defaultMessage: 'Collapse navigation',
  },
});

interface AppLayoutContentProps {
  activeSessions: Array<{
    sessionId: string;
    initialMessage?: UserInput;
    noAutoSubmit?: boolean;
  }>;
}

const AppLayoutContent: React.FC<AppLayoutContentProps> = ({ activeSessions }) => {
  const intl = useIntl();
  const ngoHome = window.appConfig?.get("NGOPILOT_AGENT_HOME") === true;
  const location = useLocation();
  const safeIsMacOS = (window?.electron?.platform || 'darwin') === 'darwin';
  const chatContext = useChatContext();
  const isOnPairRoute = location.pathname === '/pair';

  const [isFullScreen, setIsFullScreen] = useState(false);

  useEffect(() => {
    if (!safeIsMacOS) return;
    window.electron
      .getIsFullScreen()
      .then(setIsFullScreen)
      .catch(() => {});
    const handler = (_event: IpcRendererEvent, ...args: unknown[]) => {
      setIsFullScreen(Boolean(args[0]));
    };
    window.electron.on('fullscreen-change', handler);
    return () => window.electron.off('fullscreen-change', handler);
  }, [safeIsMacOS]);

  const { isNavExpanded, setIsNavExpanded } = useNavigationContext();

  if (!chatContext) {
    throw new Error('AppLayoutContent must be used within ChatProvider');
  }

  const { setChat } = chatContext;

  const needsTrafficLightInset = safeIsMacOS && !isFullScreen;
  const headerPadding = needsTrafficLightInset ? 'pl-[96px]' : 'pl-4';
  const headerTop = needsTrafficLightInset ? 'top-[14px]' : 'top-[11px]';
  const navToggleTitle = intl.formatMessage(
    isNavExpanded ? i18n.collapseNavigation : i18n.openNavigation
  );

  return (
    <div className={cn("flex flex-1 w-full h-full relative animate-fade-in bg-background-primary flex-row", ngoHome && "ngo-shell")}>
      {ngoHome && <header className="ngo-app-header">
        <button className="ngo-nav-toggle" aria-label={navToggleTitle} onClick={() => setIsNavExpanded(!isNavExpanded)}><PanelLeft size={20} /></button>
        <a className="ngo-brand" href="#/"><span className="ngo-brand-symbol"><Footprints size={21} strokeWidth={1.8} /></span><strong>CareFlow <span>Pilot</span></strong></a>
        <span className="ngo-header-divider" /><span className="ngo-product-name">NGO 工作助手</span><FoundryStatus /><AccountMenu />
      </header>}
      <div
        style={{ zIndex: Z_INDEX.HEADER }}
        className={cn('absolute flex items-center gap-1', headerPadding, headerTop, 'ml-1.5', ngoHome && 'hidden')}
      >
        <Button
          onClick={() => setIsNavExpanded(!isNavExpanded)}
          className="no-drag hover:!bg-background-tertiary"
          variant="ghost"
          size="xs"
          title={navToggleTitle}
          aria-label={navToggleTitle}
        >
          {isNavExpanded ? <PanelLeft className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </Button>
      </div>

      {/* Main content with navigation. Shared white canvas; the sidebar is a
          rounded outlined card floating on it with breathing room. */}
      <div className="ngo-workspace flex flex-1 w-full h-full min-h-0 flex-row">
        <motion.div
          key="nav"
          initial={false}
          animate={{ width: isNavExpanded ? (ngoHome ? 240 : NAV_DIMENSIONS.NAV_WIDTH) : 0 }}
          transition={{ type: 'spring', stiffness: 400, damping: 40 }}
          style={{ height: '100%' }}
          className={cn("relative flex-shrink-0 overflow-hidden h-full", ngoHome ? "ngo-sidebar" : "p-2")}
        >
          <div className={cn("w-full h-full overflow-hidden", !ngoHome && "rounded-xl border border-border-primary")}>
            <Navigation />
          </div>
        </motion.div>

        {/* Main content — no border / no card; just flows on the canvas. */}
        <div className="flex-1 overflow-hidden min-h-0">
          <Outlet />
          {/* Always render ChatSessionsContainer to keep SSE connections alive.
              When navigating away from /pair, hide it with CSS */}
          <div className={isOnPairRoute ? 'contents' : 'hidden'}>
            <ChatSessionsContainer setChat={setChat} activeSessions={activeSessions} />
          </div>
        </div>
      </div>
    </div>
  );
};

interface AppLayoutProps {
  activeSessions: Array<{
    sessionId: string;
    initialMessage?: UserInput;
    noAutoSubmit?: boolean;
  }>;
}

export const AppLayout: React.FC<AppLayoutProps> = ({ activeSessions }) => {
  return (
    <NavigationProvider>
      <AppLayoutContent activeSessions={activeSessions} />
    </NavigationProvider>
  );
};
