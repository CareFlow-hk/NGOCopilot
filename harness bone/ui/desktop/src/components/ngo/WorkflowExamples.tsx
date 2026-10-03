import { FileSpreadsheet, NotebookPen, FileCheck2, UsersRound, CalendarDays } from 'lucide-react';

export const workflowExamples = [
  { name: '紙本表格', detail: '探訪表格照片，整理成 Excel', prompt: '把這幾張探訪表格整理成 Excel，先讓我核對。', icon: FileSpreadsheet },
  { name: '會議與家訪記錄', detail: '文字稿配合範本，整理成 Word', prompt: '用附上的轉寫文字稿和 Word 範本整理會議記錄，先讓我核對。', icon: NotebookPen },
  { name: '政府表格', detail: '核對申請資料，填入支援的表格', prompt: '幫我填寫長者福利申請表，先列出支援的表格。', icon: FileCheck2 },
  { name: '人手排班', detail: '家居照顧與護送安排，產生草稿', prompt: '根據家居照顧時間表和護送總表，安排下週人手。', icon: UsersRound },
  { name: '活動日曆', detail: '活動小冊子，整理成可匯入的日曆', prompt: '把活動小冊子整理成日曆，先讓我核對日期。', icon: CalendarDays },
];

export function availableExamples() {
  return window.appConfig?.get('NGOPILOT_SCHEDULER_ENABLED') ? workflowExamples : workflowExamples.slice(0, 4);
}
