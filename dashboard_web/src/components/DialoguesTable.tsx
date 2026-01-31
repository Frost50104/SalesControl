import { format } from 'date-fns';
import { toZonedTime } from 'date-fns-tz';
import type { DialogueAnalysisSummary } from '../api/types';

interface DialoguesTableProps {
  dialogues: DialogueAnalysisSummary[];
  onRowClick: (dialogue: DialogueAnalysisSummary) => void;
  compact?: boolean;
}

const TIMEZONE = 'Europe/Belgrade';

function formatTime(isoString: string): string {
  const zonedDate = toZonedTime(new Date(isoString), TIMEZONE);
  return format(zonedDate, 'HH:mm:ss');
}

function formatDateTime(isoString: string): string {
  const zonedDate = toZonedTime(new Date(isoString), TIMEZONE);
  return format(zonedDate, 'dd.MM.yyyy HH:mm');
}

function getDuration(start: string, end: string): string {
  const startDate = new Date(start);
  const endDate = new Date(end);
  const seconds = Math.round((endDate.getTime() - startDate.getTime()) / 1000);
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${minutes}:${secs.toString().padStart(2, '0')}`;
}

function getAttemptedBadge(attempted: string) {
  const classes = {
    yes: 'bg-green-100 text-green-800',
    no: 'bg-red-100 text-red-800',
    uncertain: 'bg-yellow-100 text-yellow-800',
  };
  const labels = {
    yes: 'Да',
    no: 'Нет',
    uncertain: '?',
  };
  return (
    <span
      className={`px-2 py-1 rounded-full text-xs font-medium ${classes[attempted as keyof typeof classes] || 'bg-gray-100 text-gray-800'}`}
    >
      {labels[attempted as keyof typeof labels] || attempted}
    </span>
  );
}

function getQualityBadge(score: number) {
  const colors = ['bg-red-100 text-red-800', 'bg-orange-100 text-orange-800', 'bg-lime-100 text-lime-800', 'bg-green-100 text-green-800'];
  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium ${colors[score]}`}>
      {score}/3
    </span>
  );
}

function getReactionBadge(reaction: string) {
  const classes = {
    accepted: 'bg-green-100 text-green-800',
    rejected: 'bg-red-100 text-red-800',
    unclear: 'bg-gray-100 text-gray-800',
  };
  const labels = {
    accepted: 'Принято',
    rejected: 'Отклонено',
    unclear: 'Неясно',
  };
  return (
    <span
      className={`px-2 py-1 rounded-full text-xs font-medium ${classes[reaction as keyof typeof classes] || 'bg-gray-100 text-gray-800'}`}
    >
      {labels[reaction as keyof typeof labels] || reaction}
    </span>
  );
}

export default function DialoguesTable({
  dialogues,
  onRowClick,
  compact = false,
}: DialoguesTableProps) {
  if (dialogues.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
        Нет диалогов за выбранный период
      </div>
    );
  }

  if (compact) {
    return (
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-200">
          <h3 className="text-lg font-semibold text-gray-800">
            Последние диалоги
          </h3>
        </div>
        <div className="divide-y divide-gray-200 max-h-96 overflow-y-auto">
          {dialogues.map((dialogue) => (
            <div
              key={dialogue.dialogue_id}
              onClick={() => onRowClick(dialogue)}
              className="px-4 py-3 hover:bg-gray-50 cursor-pointer"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-sm text-gray-600">
                    {formatTime(dialogue.start_ts)}
                  </span>
                  {getAttemptedBadge(dialogue.attempted)}
                  {getQualityBadge(dialogue.quality_score)}
                </div>
                <div className="flex items-center gap-2">
                  {dialogue.categories.slice(0, 2).map((cat) => (
                    <span
                      key={cat}
                      className="px-2 py-0.5 bg-blue-50 text-blue-700 text-xs rounded"
                    >
                      {cat}
                    </span>
                  ))}
                </div>
              </div>
              {dialogue.text_snippet && (
                <p className="mt-1 text-sm text-gray-500 truncate">
                  {dialogue.text_snippet}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Время
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Длит.
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Попытка
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Качество
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Категории
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Реакция
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Резюме
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {dialogues.map((dialogue) => (
              <tr
                key={dialogue.dialogue_id}
                onClick={() => onRowClick(dialogue)}
                className="hover:bg-gray-50 cursor-pointer"
              >
                <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900">
                  {formatDateTime(dialogue.start_ts)}
                </td>
                <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-500">
                  {getDuration(dialogue.start_ts, dialogue.end_ts)}
                </td>
                <td className="px-4 py-3 whitespace-nowrap">
                  {getAttemptedBadge(dialogue.attempted)}
                </td>
                <td className="px-4 py-3 whitespace-nowrap">
                  {getQualityBadge(dialogue.quality_score)}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1 max-w-xs">
                    {dialogue.categories.map((cat) => (
                      <span
                        key={cat}
                        className="px-2 py-0.5 bg-blue-50 text-blue-700 text-xs rounded"
                      >
                        {cat}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3 whitespace-nowrap">
                  {getReactionBadge(dialogue.customer_reaction)}
                </td>
                <td className="px-4 py-3 text-sm text-gray-500 max-w-md truncate">
                  {dialogue.summary}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
