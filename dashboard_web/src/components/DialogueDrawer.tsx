import { useEffect, useState } from 'react';
import { format } from 'date-fns';
import { toZonedTime } from 'date-fns-tz';
import { fetchDialogueDetail, createReview, rerunAnalysis } from '../api/client';
import type { DialogueDetail, DialogueAnalysisSummary, ReviewReason, CorrectedAnalysis } from '../api/types';
import LoadingState from './LoadingState';
import ErrorState from './ErrorState';

interface DialogueDrawerProps {
  dialogue: DialogueAnalysisSummary | null;
  onClose: () => void;
  onUpdate?: () => void;
}

const TIMEZONE = 'Europe/Belgrade';

const REVIEW_REASONS: { value: ReviewReason; label: string }[] = [
  { value: 'bad_asr', label: 'Плохое распознавание речи' },
  { value: 'llm_missed_upsell', label: 'LLM пропустила допродажу' },
  { value: 'llm_false_positive', label: 'LLM ложно-положительный' },
  { value: 'wrong_quality', label: 'Неверная оценка качества' },
  { value: 'wrong_category', label: 'Неверная категория' },
  { value: 'other', label: 'Другое' },
];

function formatDateTime(isoString: string): string {
  const zonedDate = toZonedTime(new Date(isoString), TIMEZONE);
  return format(zonedDate, 'dd.MM.yyyy HH:mm:ss');
}

function getDuration(start: string, end: string): string {
  const startDate = new Date(start);
  const endDate = new Date(end);
  const seconds = Math.round((endDate.getTime() - startDate.getTime()) / 1000);
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${minutes} мин ${secs} сек`;
}

function highlightQuotes(text: string, quotes: string[]): React.ReactNode {
  if (!quotes || quotes.length === 0) return text;

  const parts: { text: string; highlighted: boolean }[] = [];
  let currentIndex = 0;

  const quotePositions: { quote: string; start: number; end: number }[] = [];
  for (const quote of quotes) {
    const index = text.toLowerCase().indexOf(quote.toLowerCase());
    if (index !== -1) {
      quotePositions.push({ quote, start: index, end: index + quote.length });
    }
  }
  quotePositions.sort((a, b) => a.start - b.start);

  for (const { start, end } of quotePositions) {
    if (start > currentIndex) {
      parts.push({ text: text.slice(currentIndex, start), highlighted: false });
    }
    if (start >= currentIndex) {
      parts.push({ text: text.slice(start, end), highlighted: true });
      currentIndex = end;
    }
  }
  if (currentIndex < text.length) {
    parts.push({ text: text.slice(currentIndex), highlighted: false });
  }

  return (
    <>
      {parts.map((part, i) =>
        part.highlighted ? (
          <mark key={i} className="bg-yellow-200 px-0.5 rounded">
            {part.text}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        )
      )}
    </>
  );
}

function getReviewStatusBadge(status: string) {
  const styles = {
    NONE: 'bg-gray-100 text-gray-600',
    FLAGGED: 'bg-orange-100 text-orange-700',
    RESOLVED: 'bg-green-100 text-green-700',
  };
  const labels = {
    NONE: 'Не проверен',
    FLAGGED: 'Спорный',
    RESOLVED: 'Проверен',
  };
  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium ${styles[status as keyof typeof styles] || styles.NONE}`}>
      {labels[status as keyof typeof labels] || status}
    </span>
  );
}

export default function DialogueDrawer({ dialogue, onClose, onUpdate }: DialogueDrawerProps) {
  const [detail, setDetail] = useState<DialogueDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Review form state
  const [showReviewForm, setShowReviewForm] = useState(false);
  const [reviewReason, setReviewReason] = useState<ReviewReason>('other');
  const [reviewNotes, setReviewNotes] = useState('');
  const [showCorrection, setShowCorrection] = useState(false);
  const [corrected, setCorrected] = useState<CorrectedAnalysis>({});
  const [submittingReview, setSubmittingReview] = useState(false);
  const [reviewSuccess, setReviewSuccess] = useState(false);

  // Rerun state
  const [rerunning, setRerunning] = useState(false);
  const [rerunSuccess, setRerunSuccess] = useState(false);

  useEffect(() => {
    if (!dialogue) {
      setDetail(null);
      setShowReviewForm(false);
      setReviewSuccess(false);
      setRerunSuccess(false);
      return;
    }

    async function loadDetail() {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchDialogueDetail(dialogue!.dialogue_id);
        setDetail(data);
        // Initialize corrected with current values
        setCorrected({
          attempted: data.attempted,
          quality_score: data.quality_score,
          categories: data.categories,
          closing_question: data.closing_question,
          customer_reaction: data.customer_reaction,
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load dialogue');
      } finally {
        setLoading(false);
      }
    }

    loadDetail();
  }, [dialogue]);

  const handleCopyText = () => {
    if (detail?.text) {
      navigator.clipboard.writeText(detail.text);
    }
  };

  const handleCopyJson = () => {
    if (detail) {
      navigator.clipboard.writeText(JSON.stringify(detail, null, 2));
    }
  };

  const handleSubmitReview = async () => {
    if (!detail) return;
    setSubmittingReview(true);
    setError(null);

    try {
      await createReview(detail.dialogue_id, {
        reason: reviewReason,
        notes: reviewNotes || undefined,
        corrected: showCorrection ? corrected : undefined,
      });
      setReviewSuccess(true);
      setShowReviewForm(false);
      // Reload detail to get updated review_status
      const data = await fetchDialogueDetail(detail.dialogue_id);
      setDetail(data);
      onUpdate?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit review');
    } finally {
      setSubmittingReview(false);
    }
  };

  const handleRerun = async () => {
    if (!detail) return;
    setRerunning(true);
    setError(null);

    try {
      await rerunAnalysis(detail.dialogue_id);
      setRerunSuccess(true);
      onUpdate?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to trigger rerun');
    } finally {
      setRerunning(false);
    }
  };

  if (!dialogue) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black bg-opacity-50 z-40"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed inset-y-0 right-0 w-full max-w-2xl bg-white shadow-xl z-50 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-gray-900">
              Детали диалога
            </h2>
            {detail && getReviewStatusBadge(detail.review_status)}
          </div>
          <button
            onClick={onClose}
            className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-full"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading && <LoadingState message="Загрузка..." />}
          {error && <ErrorState message={error} />}
          {detail && (
            <div className="space-y-6">
              {/* Success messages */}
              {reviewSuccess && (
                <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded-lg">
                  Диалог отмечен как спорный
                </div>
              )}
              {rerunSuccess && (
                <div className="bg-blue-50 border border-blue-200 text-blue-700 px-4 py-3 rounded-lg">
                  Переанализ запущен. Результат появится через несколько секунд.
                </div>
              )}

              {/* Metadata */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm text-gray-500">Время начала</p>
                  <p className="font-medium">{formatDateTime(detail.start_ts)}</p>
                </div>
                <div>
                  <p className="text-sm text-gray-500">Длительность</p>
                  <p className="font-medium">{getDuration(detail.start_ts, detail.end_ts)}</p>
                </div>
                <div>
                  <p className="text-sm text-gray-500">Точка</p>
                  <p className="font-medium font-mono text-sm">{detail.point_id.slice(0, 8)}...</p>
                </div>
                <div>
                  <p className="text-sm text-gray-500">Касса</p>
                  <p className="font-medium font-mono text-sm">{detail.register_id.slice(0, 8)}...</p>
                </div>
              </div>

              {/* Analysis */}
              <div className="bg-gray-50 rounded-lg p-4">
                <h3 className="font-semibold text-gray-900 mb-3">Анализ</h3>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <p className="text-sm text-gray-500">Попытка допродажи</p>
                    <p className={`font-medium ${
                      detail.attempted === 'yes' ? 'text-green-600' :
                      detail.attempted === 'no' ? 'text-red-600' : 'text-yellow-600'
                    }`}>
                      {detail.attempted === 'yes' ? 'Да' : detail.attempted === 'no' ? 'Нет' : 'Неясно'}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500">Качество</p>
                    <p className="font-medium">{detail.quality_score}/3</p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500">Реакция клиента</p>
                    <p className={`font-medium ${
                      detail.customer_reaction === 'accepted' ? 'text-green-600' :
                      detail.customer_reaction === 'rejected' ? 'text-red-600' : 'text-gray-600'
                    }`}>
                      {detail.customer_reaction === 'accepted' ? 'Принял' :
                       detail.customer_reaction === 'rejected' ? 'Отклонил' : 'Неясно'}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500">Закрывающий вопрос</p>
                    <p className="font-medium">{detail.closing_question ? 'Да' : 'Нет'}</p>
                  </div>
                </div>

                {detail.categories.length > 0 && (
                  <div className="mb-4">
                    <p className="text-sm text-gray-500 mb-1">Категории</p>
                    <div className="flex flex-wrap gap-2">
                      {detail.categories.map((cat) => (
                        <span
                          key={cat}
                          className="px-2 py-1 bg-blue-100 text-blue-800 text-sm rounded"
                        >
                          {cat}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <p className="text-sm text-gray-500 mb-1">Резюме</p>
                  <p className="text-gray-700">{detail.summary}</p>
                </div>

                {detail.confidence !== null && (
                  <div className="mt-4">
                    <p className="text-sm text-gray-500">
                      Уверенность модели: {(detail.confidence * 100).toFixed(0)}%
                    </p>
                  </div>
                )}
              </div>

              {/* Review Form */}
              {showReviewForm && (
                <div className="bg-orange-50 rounded-lg p-4 border border-orange-200">
                  <h3 className="font-semibold text-gray-900 mb-3">Отметить как спорный</h3>

                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        Причина *
                      </label>
                      <select
                        value={reviewReason}
                        onChange={(e) => setReviewReason(e.target.value as ReviewReason)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md"
                      >
                        {REVIEW_REASONS.map((r) => (
                          <option key={r.value} value={r.value}>{r.label}</option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        Заметки
                      </label>
                      <textarea
                        value={reviewNotes}
                        onChange={(e) => setReviewNotes(e.target.value)}
                        rows={2}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md"
                        placeholder="Дополнительные комментарии..."
                      />
                    </div>

                    <div>
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={showCorrection}
                          onChange={(e) => setShowCorrection(e.target.checked)}
                          className="rounded"
                        />
                        <span className="text-sm text-gray-700">Указать правильные значения</span>
                      </label>
                    </div>

                    {showCorrection && (
                      <div className="bg-white rounded p-3 space-y-3">
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className="block text-xs font-medium text-gray-600 mb-1">
                              Попытка допродажи
                            </label>
                            <select
                              value={corrected.attempted || ''}
                              onChange={(e) => setCorrected({ ...corrected, attempted: e.target.value })}
                              className="w-full px-2 py-1 text-sm border rounded"
                            >
                              <option value="yes">Да</option>
                              <option value="no">Нет</option>
                              <option value="uncertain">Неясно</option>
                            </select>
                          </div>
                          <div>
                            <label className="block text-xs font-medium text-gray-600 mb-1">
                              Качество (0-3)
                            </label>
                            <select
                              value={corrected.quality_score ?? ''}
                              onChange={(e) => setCorrected({ ...corrected, quality_score: parseInt(e.target.value) })}
                              className="w-full px-2 py-1 text-sm border rounded"
                            >
                              <option value="0">0</option>
                              <option value="1">1</option>
                              <option value="2">2</option>
                              <option value="3">3</option>
                            </select>
                          </div>
                          <div>
                            <label className="block text-xs font-medium text-gray-600 mb-1">
                              Реакция клиента
                            </label>
                            <select
                              value={corrected.customer_reaction || ''}
                              onChange={(e) => setCorrected({ ...corrected, customer_reaction: e.target.value })}
                              className="w-full px-2 py-1 text-sm border rounded"
                            >
                              <option value="accepted">Принял</option>
                              <option value="rejected">Отклонил</option>
                              <option value="unclear">Неясно</option>
                            </select>
                          </div>
                          <div>
                            <label className="block text-xs font-medium text-gray-600 mb-1">
                              Закрывающий вопрос
                            </label>
                            <select
                              value={corrected.closing_question ? 'true' : 'false'}
                              onChange={(e) => setCorrected({ ...corrected, closing_question: e.target.value === 'true' })}
                              className="w-full px-2 py-1 text-sm border rounded"
                            >
                              <option value="true">Да</option>
                              <option value="false">Нет</option>
                            </select>
                          </div>
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-gray-600 mb-1">
                            Категории (через запятую)
                          </label>
                          <input
                            type="text"
                            value={corrected.categories?.join(', ') || ''}
                            onChange={(e) => setCorrected({
                              ...corrected,
                              categories: e.target.value.split(',').map(s => s.trim()).filter(Boolean)
                            })}
                            className="w-full px-2 py-1 text-sm border rounded"
                            placeholder="напиток, десерт"
                          />
                        </div>
                      </div>
                    )}

                    <div className="flex gap-2">
                      <button
                        onClick={handleSubmitReview}
                        disabled={submittingReview}
                        className="px-4 py-2 bg-orange-600 text-white rounded hover:bg-orange-700 disabled:opacity-50"
                      >
                        {submittingReview ? 'Сохранение...' : 'Сохранить'}
                      </button>
                      <button
                        onClick={() => setShowReviewForm(false)}
                        className="px-4 py-2 bg-gray-200 text-gray-700 rounded hover:bg-gray-300"
                      >
                        Отмена
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Action Buttons */}
              {!showReviewForm && (
                <div className="flex gap-2">
                  <button
                    onClick={() => setShowReviewForm(true)}
                    className="px-4 py-2 bg-orange-100 text-orange-700 rounded hover:bg-orange-200 text-sm"
                  >
                    Отметить спорным
                  </button>
                  <button
                    onClick={handleRerun}
                    disabled={rerunning}
                    className="px-4 py-2 bg-blue-100 text-blue-700 rounded hover:bg-blue-200 text-sm disabled:opacity-50"
                  >
                    {rerunning ? 'Запуск...' : 'Переанализировать'}
                  </button>
                </div>
              )}

              {/* Transcript */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h3 className="font-semibold text-gray-900">Текст диалога</h3>
                  <div className="flex gap-2">
                    <button
                      onClick={handleCopyText}
                      className="px-3 py-1 text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 rounded"
                    >
                      Копировать текст
                    </button>
                    <button
                      onClick={handleCopyJson}
                      className="px-3 py-1 text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 rounded"
                    >
                      Копировать JSON
                    </button>
                  </div>
                </div>
                <div className="bg-gray-50 rounded-lg p-4 whitespace-pre-wrap text-sm leading-relaxed">
                  {highlightQuotes(detail.text, detail.evidence_quotes)}
                </div>
              </div>

              {/* Evidence quotes */}
              {detail.evidence_quotes && detail.evidence_quotes.length > 0 && (
                <div>
                  <h3 className="font-semibold text-gray-900 mb-2">
                    Подтверждающие цитаты
                  </h3>
                  <ul className="space-y-2">
                    {detail.evidence_quotes.map((quote, i) => (
                      <li
                        key={i}
                        className="bg-yellow-50 border-l-4 border-yellow-400 pl-3 py-2 text-sm"
                      >
                        "{quote}"
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
