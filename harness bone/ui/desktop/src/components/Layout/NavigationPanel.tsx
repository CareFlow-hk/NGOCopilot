import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { ChevronDown, ChevronRight, Ellipsis, Trash2 } from 'lucide-react';
import { motion } from 'framer-motion';
import { toast } from 'react-toastify';
import { useNavigationContext } from './NavigationContext';
import { useConfig } from '../ConfigContext';
import { useNavigationSessions } from '../../hooks/useNavigationSessions';
import {
  NAV_ITEMS,
  SETTINGS_NAV_ITEM,
  getNavItemLabel,
  type NavItem,
} from '../../hooks/useNavigationItems';
import { AppEvents } from '../../constants/events';
import { InlineEditText } from '../common/InlineEditText';
import { SessionIndicators } from '../SessionIndicators';
import { acpDeleteSession, acpRenameSession, type SessionListItem } from '../../acp/sessions';
import { acpChatSessionActions } from '../../acp/chatSessionStore';
import { cancelAcpPermissionRequestsForSession } from '../../acp/permissionRequests';
import { cancelAcpElicitationRequestsForSession } from '../../acp/elicitationRequests';
import { cn } from '../../utils';
import { errorMessage } from '../../utils/conversionUtils';
import type { ProjectGroup } from '../../utils/projectSessions';
import { defineMessages, useIntl } from '../../i18n';
import { ConfirmationModal } from '../ui/ConfirmationModal';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';

type StreamState = 'idle' | 'loading' | 'streaming' | 'error';

interface SessionStatus {
  streamState: StreamState;
  hasUnreadActivity: boolean;
}

const i18n = defineMessages({
  chats: {
    id: 'navigationPanel.chats',
    defaultMessage: 'Chats',
  },
  noChats: {
    id: 'navigationPanel.noChats',
    defaultMessage: 'No recent chats',
  },
  untitledSession: {
    id: 'navigationPanel.untitledSession',
    defaultMessage: 'Untitled session',
  },
  deleteSession: {
    id: 'sessions.action.delete',
    defaultMessage: 'Delete session',
  },
  deleteTitle: {
    id: 'sessions.delete.title',
    defaultMessage: 'Delete Session',
  },
  deleteMessage: {
    id: 'sessions.delete.message',
    defaultMessage:
      'Delete the session "{name}" and its uploaded and generated files? This action cannot be undone.',
  },
  deleteSuccess: {
    id: 'sessions.toast.deleted',
    defaultMessage: 'Session deleted successfully',
  },
  deleteFailed: {
    id: 'sessions.toast.deleteFailed',
    defaultMessage: 'Failed to delete session "{name}": {error}',
  },
  cancel: {
    id: 'sessions.cancel',
    defaultMessage: 'Cancel',
  },
});

const navItemClass = (active: boolean) =>
  cn(
    'flex flex-row items-center gap-3 outline-none no-drag w-full',
    'rounded-full px-3 py-2 text-sm font-medium transition-colors',
    active
      ? 'bg-background-tertiary text-text-primary'
      : 'text-text-primary hover:bg-background-tertiary/60'
  );

interface NavRowProps {
  item: NavItem;
  active: boolean;
  onClick: () => void;
}

const NavRow: React.FC<NavRowProps> = ({ item, active, onClick }) => {
  const intl = useIntl();
  const Icon = item.icon;
  return (
    <button onClick={onClick} className={navItemClass(active)}>
      <Icon className="w-5 h-5 flex-shrink-0 text-text-secondary" />
      <span className="text-left flex-1 truncate">{getNavItemLabel(item, intl)}</span>
      {item.getTag && (
        <span className="text-xs font-mono text-text-secondary">{item.getTag()}</span>
      )}
    </button>
  );
};

interface SessionRowProps {
  session: SessionListItem;
  active: boolean;
  status: SessionStatus | undefined;
  onClick: () => void;
  onRenamed: () => void;
  onDelete: (session: SessionListItem) => void;
  isDeleting: boolean;
}

const SessionRow: React.FC<SessionRowProps> = ({
  session,
  active,
  status,
  onClick,
  onRenamed,
  onDelete,
  isDeleting,
}) => {
  const intl = useIntl();
  const [isEditing, setIsEditing] = useState(false);
  const isStreaming = status?.streamState === 'streaming';
  const hasError = status?.streamState === 'error';
  const hasUnread = status?.hasUnreadActivity ?? false;

  return (
    <div
      onClick={() => !isEditing && !isDeleting && onClick()}
      className={cn(
        'group flex items-center gap-1 px-3 py-1.5 rounded-full cursor-pointer text-sm',
        'hover:bg-background-tertiary/60 transition-colors',
        active && 'bg-background-tertiary',
        isDeleting && 'opacity-60 cursor-wait'
      )}
    >
      <InlineEditText
        value={session.name}
        onSave={async (newName) => {
          await acpRenameSession(session.id, newName);
          window.dispatchEvent(
            new CustomEvent(AppEvents.SESSION_RENAMED, {
              detail: { sessionId: session.id, newName, userInitiated: true },
            })
          );
          onRenamed();
        }}
        placeholder={intl.formatMessage(i18n.untitledSession)}
        disabled={isStreaming}
        singleClickEdit={false}
        className="truncate text-text-primary flex-1 !px-0 !py-0 hover:bg-transparent"
        editClassName="!text-sm"
        onEditStart={() => setIsEditing(true)}
        onEditEnd={() => setIsEditing(false)}
      />
      <SessionIndicators isStreaming={isStreaming} hasUnread={hasUnread} hasError={hasError} />
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            onClick={(event) => event.stopPropagation()}
            aria-label={intl.formatMessage(i18n.deleteSession)}
            title={intl.formatMessage(i18n.deleteSession)}
            className={cn(
              'flex size-7 shrink-0 items-center justify-center rounded-full text-text-secondary',
              'opacity-100 transition-opacity hover:bg-background-secondary hover:text-text-primary',
              'focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-background-accent',
              '[@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100',
              '[@media(hover:hover)]:group-focus-within:opacity-100 data-[state=open]:opacity-100',
              active && '[@media(hover:hover)]:opacity-100'
            )}
          >
            <Ellipsis className="size-4" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" side="right" onClick={(event) => event.stopPropagation()}>
          <DropdownMenuItem
            variant="destructive"
            disabled={isStreaming || isDeleting}
            onSelect={() => onDelete(session)}
          >
            <Trash2 />
            {intl.formatMessage(i18n.deleteSession)}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
};

export const Navigation: React.FC<{ className?: string }> = ({ className }) => {
  const intl = useIntl();
  const { isNavExpanded } = useNavigationContext();
  const location = useLocation();
  const { extensionsList } = useConfig();

  const appsExtensionEnabled = !!extensionsList?.find((ext) => ext.name === 'apps')?.enabled;

  const visibleItems = useMemo<NavItem[]>(() => {
    return NAV_ITEMS.filter((item) => {
      if (item.path === '/apps') return appsExtensionEnabled;
      return true;
    });
  }, [appsExtensionEnabled]);

  const isActive = useCallback((path: string) => location.pathname === path, [location.pathname]);

  const {
    recentSessions,
    recentSessionsByProject,
    activeSessionId,
    fetchSessions,
    handleNavClick,
    handleSessionClick,
  } = useNavigationSessions();

  const [sessionStatuses, setSessionStatuses] = useState<Map<string, SessionStatus>>(new Map());
  const [sessionToDelete, setSessionToDelete] = useState<SessionListItem | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const handleConfirmDelete = useCallback(async () => {
    if (!sessionToDelete || isDeleting) return;
    setIsDeleting(true);
    try {
      await acpDeleteSession(sessionToDelete.id);
      window.dispatchEvent(
        new CustomEvent(AppEvents.SESSION_DELETED, {
          detail: { sessionId: sessionToDelete.id },
        })
      );
      cancelAcpPermissionRequestsForSession(sessionToDelete.id);
      cancelAcpElicitationRequestsForSession(sessionToDelete.id);
      acpChatSessionActions.deleteSnapshot(sessionToDelete.id);
      toast.success(intl.formatMessage(i18n.deleteSuccess));
      setSessionToDelete(null);
    } catch (error) {
      console.error('Error deleting session:', error);
      toast.error(
        intl.formatMessage(i18n.deleteFailed, {
          name: sessionToDelete.name,
          error: errorMessage(error, 'Unknown error'),
        })
      );
    } finally {
      setIsDeleting(false);
    }
  }, [intl, isDeleting, sessionToDelete]);

  useEffect(() => {
    const handleStatusUpdate = (event: Event) => {
      const { sessionId, streamState } = (event as CustomEvent).detail;
      setSessionStatuses((prev) => {
        const existing = prev.get(sessionId);
        const shouldMarkUnread = existing?.streamState === 'streaming' && streamState === 'idle';
        const next = new Map(prev);
        next.set(sessionId, {
          streamState,
          hasUnreadActivity: existing?.hasUnreadActivity || shouldMarkUnread,
        });
        return next;
      });
    };

    window.addEventListener(AppEvents.SESSION_STATUS_UPDATE, handleStatusUpdate);
    return () => window.removeEventListener(AppEvents.SESSION_STATUS_UPDATE, handleStatusUpdate);
  }, []);

  const clearUnread = useCallback((sessionId: string) => {
    setSessionStatuses((prev) => {
      const status = prev.get(sessionId);
      if (status?.hasUnreadActivity) {
        const next = new Map(prev);
        next.set(sessionId, { ...status, hasUnreadActivity: false });
        return next;
      }
      return prev;
    });
  }, []);

  const navFocusRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isNavExpanded) {
      fetchSessions();
      requestAnimationFrame(() => navFocusRef.current?.focus());
    }
  }, [isNavExpanded, fetchSessions]);

  const [isChatsExpanded, setIsChatsExpanded] = useState(true);
  const [collapsedProjects, setCollapsedProjects] = useState<Set<string>>(new Set());

  const toggleProjectCollapsed = useCallback((path: string) => {
    setCollapsedProjects((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  if (!isNavExpanded) return null;

  return (
    <motion.div
      ref={navFocusRef}
      tabIndex={-1}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
      className={cn('bg-background-primary outline-none flex flex-col h-full', className)}
    >
      <div className="h-[48px] no-drag" />

      <div className="px-2 flex flex-col gap-0.5">
        {visibleItems.map((item) => (
          <NavRow
            key={item.id}
            item={item}
            active={isActive(item.path)}
            onClick={() => handleNavClick(item.path)}
          />
        ))}
      </div>

      <div className="flex-1 min-h-0 flex flex-col mt-3">
        <button
          onClick={() => setIsChatsExpanded((v) => !v)}
          className="flex items-center gap-1 px-4 py-1 text-xs font-semibold uppercase tracking-wider text-text-secondary hover:text-text-primary transition-colors self-start"
        >
          {isChatsExpanded ? (
            <ChevronDown className="w-3 h-3" />
          ) : (
            <ChevronRight className="w-3 h-3" />
          )}
          <span>{intl.formatMessage(i18n.chats)}</span>
        </button>
        {isChatsExpanded && (
          <div className="flex-1 min-h-0 overflow-y-auto px-2 pb-2 mt-1">
            {recentSessions.length === 0 ? (
              <div className="px-3 py-2 text-xs text-text-secondary">
                {intl.formatMessage(i18n.noChats)}
              </div>
            ) : recentSessionsByProject.length > 1 ? (
              recentSessionsByProject.map((group: ProjectGroup) => {
                const isCollapsed = collapsedProjects.has(group.path);
                return (
                  <React.Fragment key={group.path}>
                    <button
                      onClick={() => toggleProjectCollapsed(group.path)}
                      aria-expanded={!isCollapsed}
                      className="flex items-center gap-1 w-full px-3 pt-2 pb-0.5 text-[10px] uppercase tracking-wider text-text-tertiary hover:text-text-secondary transition-colors"
                      title={group.path}
                    >
                      {isCollapsed ? (
                        <ChevronRight className="w-3 h-3 flex-shrink-0" />
                      ) : (
                        <ChevronDown className="w-3 h-3 flex-shrink-0" />
                      )}
                      <span className="truncate">{group.label}</span>
                    </button>
                    {!isCollapsed &&
                      group.sessions.map((session) => (
                        <SessionRow
                          key={session.id}
                          session={session}
                          active={session.id === activeSessionId}
                          status={sessionStatuses.get(session.id)}
                          onClick={() => {
                            clearUnread(session.id);
                            handleSessionClick(session.id);
                          }}
                          onRenamed={fetchSessions}
                          onDelete={setSessionToDelete}
                          isDeleting={isDeleting && sessionToDelete?.id === session.id}
                        />
                      ))}
                  </React.Fragment>
                );
              })
            ) : (
              recentSessions.map((session) => (
                <SessionRow
                  key={session.id}
                  session={session}
                  active={session.id === activeSessionId}
                  status={sessionStatuses.get(session.id)}
                  onClick={() => {
                    clearUnread(session.id);
                    handleSessionClick(session.id);
                  }}
                  onRenamed={fetchSessions}
                  onDelete={setSessionToDelete}
                  isDeleting={isDeleting && sessionToDelete?.id === session.id}
                />
              ))
            )}
          </div>
        )}
      </div>

      <div className="px-2 pt-2 pb-2 border-t border-border-secondary">
        <NavRow
          item={SETTINGS_NAV_ITEM}
          active={isActive(SETTINGS_NAV_ITEM.path)}
          onClick={() => handleNavClick(SETTINGS_NAV_ITEM.path)}
        />
      </div>
      <ConfirmationModal
        isOpen={sessionToDelete !== null}
        title={intl.formatMessage(i18n.deleteTitle)}
        message={intl.formatMessage(i18n.deleteMessage, {
          name: sessionToDelete?.name ?? '',
        })}
        confirmLabel={intl.formatMessage(i18n.deleteTitle)}
        cancelLabel={intl.formatMessage(i18n.cancel)}
        confirmVariant="destructive"
        isSubmitting={isDeleting}
        onConfirm={() => void handleConfirmDelete()}
        onCancel={() => {
          if (!isDeleting) setSessionToDelete(null);
        }}
      />
    </motion.div>
  );
};
