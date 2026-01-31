import { useState, useEffect, useCallback } from 'react';
import { format } from 'date-fns';
import { fetchDaily, fetchDialogues } from '../api/client';
import type { DailyAnalyticsResponse, DialogueAnalysisSummary } from '../api/types';
import FiltersBar from '../components/FiltersBar';
import StatCards from '../components/StatCards';
import HourlyChart from '../components/HourlyChart';
import CategoryChart from '../components/CategoryChart';
import QualityChart from '../components/QualityChart';
import DialoguesTable from '../components/DialoguesTable';
import DialogueDrawer from '../components/DialogueDrawer';
import LoadingState from '../components/LoadingState';
import ErrorState from '../components/ErrorState';

export default function OverviewPage() {
  const [date, setDate] = useState(format(new Date(), 'yyyy-MM-dd'));
  const [pointId, setPointId] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(false);

  const [dailyData, setDailyData] = useState<DailyAnalyticsResponse | null>(null);
  const [recentDialogues, setRecentDialogues] = useState<DialogueAnalysisSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedDialogue, setSelectedDialogue] = useState<DialogueAnalysisSummary | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [daily, dialogues] = await Promise.all([
        fetchDaily(date, pointId || undefined),
        fetchDialogues(date, {
          pointId: pointId || undefined,
          limit: 20,
        }),
      ]);

      setDailyData(daily);
      setRecentDialogues(dialogues.dialogues);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Ошибка загрузки данных';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [date, pointId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    if (!autoRefresh) return;

    const interval = setInterval(() => {
      loadData();
    }, 60000);

    return () => clearInterval(interval);
  }, [autoRefresh, loadData]);

  if (loading && !dailyData) {
    return (
      <div className="py-12">
        <LoadingState message="Загрузка данных..." />
      </div>
    );
  }

  return (
    <div>
      <FiltersBar
        date={date}
        pointId={pointId}
        autoRefresh={autoRefresh}
        onDateChange={setDate}
        onPointChange={setPointId}
        onAutoRefreshChange={setAutoRefresh}
      />

      {error && (
        <div className="mb-6">
          <ErrorState message={error} onRetry={loadData} />
        </div>
      )}

      {dailyData && (
        <>
          <StatCards data={dailyData} />

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            <CategoryChart data={dailyData.top_categories} />
            <QualityChart distribution={dailyData.quality_distribution} />
          </div>

          <div className="mb-6">
            <HourlyChart data={dailyData.hourly} />
          </div>

          <DialoguesTable
            dialogues={recentDialogues}
            onRowClick={setSelectedDialogue}
            compact
          />
        </>
      )}

      <DialogueDrawer
        dialogue={selectedDialogue}
        onClose={() => setSelectedDialogue(null)}
      />
    </div>
  );
}
