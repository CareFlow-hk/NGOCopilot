import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IntlTestWrapper } from '../../i18n/test-utils';
import { AppEvents } from '../../constants/events';
import { Navigation } from './NavigationPanel';

const mocks = vi.hoisted(() => ({
  deleteSession: vi.fn(),
  deleteSnapshot: vi.fn(),
  cancelPermissions: vi.fn(),
  cancelElicitations: vi.fn(),
  fetchSessions: vi.fn(),
}));

vi.mock('react-router-dom', () => ({
  useLocation: () => ({ pathname: '/' }),
}));

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
      <div {...props}>{children}</div>
    ),
  },
}));

vi.mock('../ConfigContext', () => ({
  useConfig: () => ({ extensionsList: [] }),
}));

vi.mock('./NavigationContext', () => ({
  useNavigationContext: () => ({ isNavExpanded: true }),
}));

vi.mock('../../hooks/useNavigationSessions', () => ({
  useNavigationSessions: () => ({
    recentSessions: [
      {
        id: 'session-1',
        name: 'Field report',
        workingDir: '/data',
        updatedAt: '2026-08-12T00:00:00Z',
        messageCount: 3,
        createdAt: '2026-08-12T00:00:00Z',
      },
    ],
    recentSessionsByProject: [],
    activeSessionId: 'session-1',
    fetchSessions: mocks.fetchSessions,
    handleNavClick: vi.fn(),
    handleSessionClick: vi.fn(),
  }),
}));

vi.mock('../common/InlineEditText', () => ({
  InlineEditText: ({ value }: { value: string }) => <span>{value}</span>,
}));

vi.mock('../SessionIndicators', () => ({
  SessionIndicators: () => null,
}));

vi.mock('../ui/dropdown-menu', () => ({
  DropdownMenu: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  DropdownMenuTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  DropdownMenuContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuItem: ({
    children,
    onSelect,
    disabled,
  }: {
    children: React.ReactNode;
    onSelect?: () => void;
    disabled?: boolean;
  }) => (
    <button type="button" onClick={onSelect} disabled={disabled}>
      {children}
    </button>
  ),
}));

vi.mock('../ui/ConfirmationModal', () => ({
  ConfirmationModal: ({
    isOpen,
    message,
    onConfirm,
  }: {
    isOpen: boolean;
    message: string;
    onConfirm: () => void;
  }) =>
    isOpen ? (
      <div>
        <p>{message}</p>
        <button type="button" onClick={onConfirm}>
          Confirm deletion
        </button>
      </div>
    ) : null,
}));

vi.mock('../../acp/sessions', () => ({
  acpDeleteSession: mocks.deleteSession,
  acpRenameSession: vi.fn(),
}));

vi.mock('../../acp/chatSessionStore', () => ({
  acpChatSessionActions: { deleteSnapshot: mocks.deleteSnapshot },
}));

vi.mock('../../acp/permissionRequests', () => ({
  cancelAcpPermissionRequestsForSession: mocks.cancelPermissions,
}));

vi.mock('../../acp/elicitationRequests', () => ({
  cancelAcpElicitationRequestsForSession: mocks.cancelElicitations,
}));

vi.mock('react-toastify', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe('Navigation session deletion', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.deleteSession.mockResolvedValue(undefined);
    window.innerWidth = 1200;
  });

  it('confirms sidebar deletion and clears session-scoped client state', async () => {
    const deleted = vi.fn();
    window.addEventListener(AppEvents.SESSION_DELETED, deleted);

    render(<Navigation />, { wrapper: IntlTestWrapper });

    const deleteButtons = screen.getAllByRole('button', { name: 'Delete session' });
    fireEvent.click(deleteButtons[deleteButtons.length - 1]);
    expect(
      screen.getByText(
        'Delete the session "Field report" and its uploaded and generated files? This action cannot be undone.'
      )
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Confirm deletion' }));

    await waitFor(() => expect(mocks.deleteSession).toHaveBeenCalledWith('session-1'));
    expect(deleted).toHaveBeenCalledOnce();
    expect(mocks.cancelPermissions).toHaveBeenCalledWith('session-1');
    expect(mocks.cancelElicitations).toHaveBeenCalledWith('session-1');
    expect(mocks.deleteSnapshot).toHaveBeenCalledWith('session-1');

    window.removeEventListener(AppEvents.SESSION_DELETED, deleted);
  });

  it('keeps the confirmation open when durable deletion fails so the user can retry', async () => {
    mocks.deleteSession.mockRejectedValueOnce(new Error('GCS is temporarily unavailable'));

    render(<Navigation />, { wrapper: IntlTestWrapper });

    const deleteButtons = screen.getAllByRole('button', { name: 'Delete session' });
    fireEvent.click(deleteButtons[deleteButtons.length - 1]);
    fireEvent.click(screen.getByRole('button', { name: 'Confirm deletion' }));

    await waitFor(() => expect(mocks.deleteSession).toHaveBeenCalledWith('session-1'));
    expect(screen.getByRole('button', { name: 'Confirm deletion' })).toBeInTheDocument();
    expect(mocks.deleteSnapshot).not.toHaveBeenCalled();
  });
});
