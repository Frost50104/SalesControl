import { useState, useEffect, useCallback } from 'react';
import { format } from 'date-fns';
import { toZonedTime } from 'date-fns-tz';
import { fetchReviews, resolveReview, fetchPoints } from '../api/client';
import { getToken, getBaseUrl } from '../auth/tokenStore';
import type { ReviewWithDialogue, PointInfo, ReviewReason, ReviewStatus, DialogueAnalysisSummary } from '../api/types';
import DialogueDrawer from '../components/DialogueDrawer';
import LoadingState from '../components/LoadingState';
import ErrorState from '../components/ErrorState';

const TIMEZONE = 'Europe/Belgrade';

const REASON_LABELS: Record<ReviewReason, string> = {
  bad_asr: 'Плохое ASR',
  llm_missed_upsell: 'Пропущена допродажа',
  llm_false_positive: 'Ложное срабатывание',
  wrong_quality: 'Неверное качество',
  wrong_category: 'Неверная категория',
  other: 'Другое',
};

function formatDateTime(isoString: string): string {
  const zonedDate = toZonedTime(new Date(isoString), TIMEZONE);
  return format(zonedDate, 'dd.MM.yyyy HH:mm');
}

function getReasonBadge(reason: string) {
  const colors: Record<string, string> = {
    bad_asr: 'bg-red-100 text-red-700',
    llm_missed_upsell: 'bg-orange-100 text-orange-700',
    llm_false_positive: 'bg-yellow-100 text-yellow-700',
    wrong_quality: 'bg-purple-100 text-purple-700',
    wrong_category: 'bg-blue-100 text-blue-700',
    other: 'bg-gray-100 text-gray-700',
  };
  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium ${colors[reason] || colors.other}`}>
      {REASON_LABELS[reason as ReviewReason] || reason}
    </span>
  );
}

function getStatusBadge(status: string) {
  const styles: Record<string, string> = {
    FLAGGED: 'bg-orange-100 text-orange-700',
    RESOLVED: 'bg-green-100 text-green-700',
  };
  const labels: Record<string, string> = {
    FLAGGED: 'Спорный',
    RESOLVED: 'Проверен',
  };
  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium ${styles[status] || 'bg-gray-100 text-gray-700'}`}>
      {labels[status] || status}
    </span>
  );
}

export default function ReviewsPage() {
  const [date, setDate] = useState('');
  const [pointId, setPointId] = useState('');
  const [status, setStatus] = useState<ReviewStatus | ''>('FLAGGED');
  const [reason, setReason] = useState<ReviewReason | ''>('');

  const [reviews, setReviews] = useState<ReviewWithDialogue[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [points, setPoints] = useState<PointInfo[]>([]);

  const [selectedDialogue, setSelectedDialogue] = useState<DialogueAnalysisSummary | null>(null);

  // Export modal
  const [showExportModal, setShowExportModal] = useState(false);
  const [exportFrom, setExportFrom] = useState(format(new Date(Date.now() - 7 * 24 * 60 * 60 * 1000), 'yyyy-MM-dd'));
  const [exportTo, setExportTo] = useState(format(new Date(), 'yyyy-MM-dd'));
  const [exportFormat, setExportFormat] = useState<'csv' | 'json'>('json');

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
      const response = await fetchReviews({
        date: date || undefined,
        pointId: pointId || undefined,
        status: status as ReviewStatus || undefined,
        reason: reason as ReviewReason || undefined,
        limit,
        offset,
      });

      setReviews(response.reviews);
      setTotal(response.total);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Ошибка загрузки данных';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [date, pointId, status, reason, offset]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    setOffset(0);
  }, [date, pointId, status, reason]);

  const handleResolve = async (reviewId: string, resolved: boolean) => {
    try {
      await resolveReview(reviewId, resolved);
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update review');
    }
  };

  const handleOpenDialogue = (review: ReviewWithDialogue) => {
    setSelectedDialogue({
      dialogue_id: review.dialogue_id,
      start_ts: review.dialogue_start_ts,
      end_ts: review.dialogue_end_ts,
      quality_score: review.quality_score || 0,
      attempted: review.attempted || '',
      categories: review.categories || [],
      customer_reaction: review.customer_reaction || '',
      closing_question: false,
      summary: '',
      text_snippet: review.text_snippet,
    });
  };

  const handleExport = () => {
    const baseUrl = getBaseUrl();
    const token = getToken();
    if (!baseUrl || !token) return;

    // Create download link with auth header via fetch
    const url = `${baseUrl}/api/v1/exports/reviews?from=${exportFrom}&to=${exportTo}&format=${exportFormat}`;

    fetch(url, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    })
      .then((response) => response.blob())
      .then((blob) => {
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = `reviews_${exportFrom}_${exportTo}.${exportFormat}`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(downloadUrl);
        a.remove();
        setShowExportModal(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Export failed');
      });
  };

  const totalPages = Math.ceil(total / limit);
  const currentPage = Math.floor(offset / limit) + 1;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Проверка диалогов</h1>
        <button
          onClick={() => setShowExportModal(true)}
          className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
        >
          Экспорт датасета
        </button>
      </div>

      {/* Filters */}
      <div className="bg-white rounded-lg shadow p-4 mb-6">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div>
            <label htmlFor="date" className="block text-sm font-medium text-gray-700 mb-1">
              Дата
            </label>
            <input
              type="date"
              id="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
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
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
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
            <label htmlFor="status" className="block text-sm font-medium text-gray-700 mb-1">
              Статус
            </label>
            <select
              id="status"
              value={status}
              onChange={(e) => setStatus(e.target.value as ReviewStatus | '')}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
            >
              <option value="">Все</option>
              <option value="FLAGGED">Спорные</option>
              <option value="RESOLVED">Проверенные</option>
            </select>
          </div>

          <div>
            <label htmlFor="reason" className="block text-sm font-medium text-gray-700 mb-1">
              Причина
            </label>
            <select
              id="reason"
              value={reason}
              onChange={(e) => setReason(e.target.value as ReviewReason | '')}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
            >
              <option value="">Все причины</option>
              {Object.entries(REASON_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>

          <div className="flex items-end">
            <button
              onClick={() => {
                setDate('');
                setPointId('');
                setStatus('FLAGGED');
                setReason('');
              }}
              className="w-full px-3 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-md text-sm"
            >
              Сбросить
            </button>
          </div>
        </div>
      </div>

      {/* Results count */}
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-gray-600">Найдено: {total} записей</p>
      </div>

      {/* Content */}
      {loading && !reviews.length ? (
        <LoadingState message="Загрузка..." />
      ) : error ? (
        <ErrorState message={error} onRetry={loadData} />
      ) : reviews.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
          Нет записей для проверки
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Время диалога
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Причина
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Статус
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  LLM результат
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Заметки
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Действия
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {reviews.map((review) => (
                <tr key={review.review_id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 whitespace-nowrap text-sm">
                    <div className="font-medium text-gray-900">
                      {formatDateTime(review.dialogue_start_ts)}
                    </div>
                    <div className="text-gray-500 text-xs">
                      {review.point_id.slice(0, 8)}...
                    </div>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    {getReasonBadge(review.reason)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    {getStatusBadge(review.review_status)}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <div className="flex items-center gap-2">
                      <span className={`font-medium ${
                        review.attempted === 'yes' ? 'text-green-600' :
                        review.attempted === 'no' ? 'text-red-600' : 'text-yellow-600'
                      }`}>
                        {review.attempted === 'yes' ? 'Да' :
                         review.attempted === 'no' ? 'Нет' : '?'}
                      </span>
                      <span className="text-gray-400">|</span>
                      <span>{review.quality_score}/3</span>
                    </div>
                    {review.corrected && (
                      <div className="text-xs text-orange-600 mt-1">
                        Исправлено: {review.corrected.attempted}, {review.corrected.quality_score}/3
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500 max-w-xs truncate">
                    {review.notes || '-'}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-sm">
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleOpenDialogue(review)}
                        className="px-2 py-1 bg-blue-100 text-blue-700 rounded hover:bg-blue-200 text-xs"
                      >
                        Открыть
                      </button>
                      {review.review_status === 'FLAGGED' ? (
                        <button
                          onClick={() => handleResolve(review.review_id, true)}
                          className="px-2 py-1 bg-green-100 text-green-700 rounded hover:bg-green-200 text-xs"
                        >
                          Resolve
                        </button>
                      ) : (
                        <button
                          onClick={() => handleResolve(review.review_id, false)}
                          className="px-2 py-1 bg-orange-100 text-orange-700 rounded hover:bg-orange-200 text-xs"
                        >
                          Reopen
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t">
              <p className="text-sm text-gray-600">
                Страница {currentPage} из {totalPages}
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setOffset(Math.max(0, offset - limit))}
                  disabled={offset === 0}
                  className="px-4 py-2 text-sm bg-gray-100 hover:bg-gray-200 disabled:opacity-50 rounded-md"
                >
                  Назад
                </button>
                <button
                  onClick={() => setOffset(offset + limit)}
                  disabled={offset + limit >= total}
                  className="px-4 py-2 text-sm bg-gray-100 hover:bg-gray-200 disabled:opacity-50 rounded-md"
                >
                  Вперед
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Export Modal */}
      {showExportModal && (
        <>
          <div
            className="fixed inset-0 bg-black bg-opacity-50 z-40"
            onClick={() => setShowExportModal(false)}
          />
          <div className="fixed inset-0 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
              <h3 className="text-lg font-semibold mb-4">Экспорт датасета</h3>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Дата с
                  </label>
                  <input
                    type="date"
                    value={exportFrom}
                    onChange={(e) => setExportFrom(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Дата по
                  </label>
                  <input
                    type="date"
                    value={exportTo}
                    onChange={(e) => setExportTo(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Формат
                  </label>
                  <select
                    value={exportFormat}
                    onChange={(e) => setExportFormat(e.target.value as 'csv' | 'json')}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md"
                  >
                    <option value="json">JSON</option>
                    <option value="csv">CSV</option>
                  </select>
                </div>
              </div>

              <div className="flex justify-end gap-3 mt-6">
                <button
                  onClick={() => setShowExportModal(false)}
                  className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
                >
                  Отмена
                </button>
                <button
                  onClick={handleExport}
                  className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
                >
                  Скачать
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      <DialogueDrawer
        dialogue={selectedDialogue}
        onClose={() => setSelectedDialogue(null)}
        onUpdate={loadData}
      />
    </div>
  );
}
