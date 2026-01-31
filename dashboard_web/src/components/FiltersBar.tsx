import { useEffect, useState } from 'react';
import { fetchPoints } from '../api/client';
import type { PointInfo } from '../api/types';

interface FiltersBarProps {
  date: string;
  pointId: string;
  autoRefresh: boolean;
  onDateChange: (date: string) => void;
  onPointChange: (pointId: string) => void;
  onAutoRefreshChange: (enabled: boolean) => void;
}

export default function FiltersBar({
  date,
  pointId,
  autoRefresh,
  onDateChange,
  onPointChange,
  onAutoRefreshChange,
}: FiltersBarProps) {
  const [points, setPoints] = useState<PointInfo[]>([]);
  const [loadingPoints, setLoadingPoints] = useState(true);

  useEffect(() => {
    async function loadPoints() {
      try {
        const response = await fetchPoints();
        setPoints(response.points);
      } catch {
        console.error('Failed to load points');
      } finally {
        setLoadingPoints(false);
      }
    }
    loadPoints();
  }, []);

  return (
    <div className="bg-white rounded-lg shadow p-4 mb-6">
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <label htmlFor="date" className="text-sm font-medium text-gray-700">
            Дата:
          </label>
          <input
            type="date"
            id="date"
            value={date}
            onChange={(e) => onDateChange(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-primary-500 focus:border-primary-500 text-sm"
          />
        </div>

        <div className="flex items-center gap-2">
          <label htmlFor="point" className="text-sm font-medium text-gray-700">
            Точка:
          </label>
          <select
            id="point"
            value={pointId}
            onChange={(e) => onPointChange(e.target.value)}
            disabled={loadingPoints}
            className="px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-primary-500 focus:border-primary-500 text-sm min-w-[200px]"
          >
            <option value="">Все точки</option>
            {points.map((point) => (
              <option key={point.point_id} value={point.point_id}>
                {point.name || point.point_id.slice(0, 8)}... ({point.dialogue_count})
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2 ml-auto">
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => onAutoRefreshChange(e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-primary-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary-600"></div>
            <span className="ml-3 text-sm font-medium text-gray-700">
              Автообновление (60 сек)
            </span>
          </label>
        </div>
      </div>
    </div>
  );
}
