import { useState, useEffect, useCallback, useMemo } from 'react';
import { format } from 'date-fns';
import { fetchDialogues, fetchPoints } from '../api/client';
import type { DialogueAnalysisSummary, PointInfo } from '../api/types';
import DialoguesTable from '../components/DialoguesTable';
import DialogueDrawer from '../components/DialogueDrawer';
import LoadingState from '../components/LoadingState';
import ErrorState from '../components/ErrorState';

export default function DialoguesPage() {
  const [date, setDate] = useState(format(new Date(), 'yyyy-MM-dd'));
  const [pointId, setPointId] = useState('');
  const [attempted, setAttempted] = useState('');
  const [minQuality, setMinQuality] = useState('');
  const [searchText, setSearchText] = useState('');

  const [dialogues, setDialogues] = useState<DialogueAnalysisSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [points, setPoints] = useState<PointInfo[]>([]);

  const [selectedDialogue, setSelectedDialogue] = useState<DialogueAnalysisSummary | null>(null);

  const limit = 50;

  useEffect(() => {
    async function loadPoints() {
      try {
        const response = await fetchPoints();
        setPoints(response.points);
      } catch {
        console.error('Failed to load points');
      }
    }
    loadPoints();
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetchDialogues(date, {
        pointId: pointId || undefined,
        attempted: attempted || undefined,
        minQuality: minQuality ? parseInt(minQuality) : undefined,
        limit,
        offset,
      });

      setDialogues(response.dialogues);
      setTotal(response.total);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Ошибка загрузки данных';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [date, pointId, attempted, minQuality, offset]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Reset offset when filters change
  useEffect(() => {
    setOffset(0);
  }, [date, pointId, attempted, minQuality]);

  // Client-side text filtering
  const filteredDialogues = useMemo(() => {
    if (!searchText.trim()) return dialogues;
    const search = searchText.toLowerCase();
    return dialogues.filter(
      (d) =>
        d.summary.toLowerCase().includes(search) ||
        d.text_snippet?.toLowerCase().includes(search) ||
        d.categories.some((c) => c.toLowerCase().includes(search))
    );
  }, [dialogues, searchText]);

  const totalPages = Math.ceil(total / limit);
  const currentPage = Math.floor(offset / limit) + 1;

  return (
    <div>
      {/* Filters */}
      <div className="bg-white rounded-lg shadow p-4 mb-6">
        <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
          <div>
            <label htmlFor="date" className="block text-sm font-medium text-gray-700 mb-1">
              Дата
            </label>
            <input
              type="date"
              id="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-primary-500 focus:border-primary-500 text-sm"
            />
          </div>

          <div>
            <label htmlFor="point" className="block text-sm font-medium text-gray-700 mb-1">
              Точка
            </label>
            <select
              id="point"
              value={pointId}
              onChange={(e) => setPointId(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-primary-500 focus:border-primary-500 text-sm"
            >
              <option value="">Все точки</option>
              {points.map((point) => (
                <option key={point.point_id} value={point.point_id}>
                  {point.name || point.point_id.slice(0, 8)}...
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="attempted" className="block text-sm font-medium text-gray-700 mb-1">
              Попытка
            </label>
            <select
              id="attempted"
              value={attempted}
              onChange={(e) => setAttempted(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-primary-500 focus:border-primary-500 text-sm"
            >
              <option value="">Все</option>
              <option value="yes">Да</option>
              <option value="no">Нет</option>
              <option value="uncertain">Неясно</option>
            </select>
          </div>

          <div>
            <label htmlFor="quality" className="block text-sm font-medium text-gray-700 mb-1">
              Мин. качество
            </label>
            <select
              id="quality"
              value={minQuality}
              onChange={(e) => setMinQuality(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-primary-500 focus:border-primary-500 text-sm"
            >
              <option value="">Любое</option>
              <option value="1">1+</option>
              <option value="2">2+</option>
              <option value="3">Только 3</option>
            </select>
          </div>

          <div className="md:col-span-2">
            <label htmlFor="search" className="block text-sm font-medium text-gray-700 mb-1">
              Поиск по тексту
            </label>
            <input
              type="text"
              id="search"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              placeholder="Поиск..."
              className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-primary-500 focus:border-primary-500 text-sm"
            />
          </div>
        </div>
      </div>

      {/* Results count */}
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-gray-600">
          Найдено: {total} диалогов
          {searchText && ` (показано: ${filteredDialogues.length})`}
        </p>
      </div>

      {/* Content */}
      {loading && !dialogues.length ? (
        <LoadingState message="Загрузка диалогов..." />
      ) : error ? (
        <ErrorState message={error} onRetry={loadData} />
      ) : (
        <>
          <DialoguesTable
            dialogues={filteredDialogues}
            onRowClick={setSelectedDialogue}
          />

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between mt-4 bg-white rounded-lg shadow p-4">
              <p className="text-sm text-gray-600">
                Страница {currentPage} из {totalPages}
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setOffset(Math.max(0, offset - limit))}
                  disabled={offset === 0}
                  className="px-4 py-2 text-sm bg-gray-100 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed rounded-md transition-colors"
                >
                  Назад
                </button>
                <button
                  onClick={() => setOffset(offset + limit)}
                  disabled={offset + limit >= total}
                  className="px-4 py-2 text-sm bg-gray-100 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed rounded-md transition-colors"
                >
                  Вперед
                </button>
              </div>
            </div>
          )}
        </>
      )}

      <DialogueDrawer
        dialogue={selectedDialogue}
        onClose={() => setSelectedDialogue(null)}
      />
    </div>
  );
}
