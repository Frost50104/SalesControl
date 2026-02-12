import { useState, useEffect } from 'react';
import { listDevices, updatePointName, updateRegisterName } from '../api/client';
import type { Device } from '../api/types';
import LoadingState from '../components/LoadingState';
import ErrorState from '../components/ErrorState';

export default function DevicesPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingPoint, setEditingPoint] = useState<string | null>(null);
  const [editingRegister, setEditingRegister] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');

  useEffect(() => {
    loadDevices();
    const interval = setInterval(loadDevices, 30000);
    return () => clearInterval(interval);
  }, []);

  const loadDevices = async () => {
    try {
      const data = await listDevices();
      setDevices(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка загрузки устройств');
    } finally {
      setLoading(false);
    }
  };

  const handleEditPoint = (device: Device) => {
    setEditingPoint(device.point_id);
    setEditValue(device.point_name || '');
  };

  const handleEditRegister = (device: Device) => {
    setEditingRegister(device.register_id);
    setEditValue(device.register_name || '');
  };

  const handleSavePoint = async (pointId: string) => {
    if (!editValue.trim()) return;
    try {
      await updatePointName(pointId, editValue.trim());
      setEditingPoint(null);
      await loadDevices();
    } catch (err) {
      alert('Ошибка сохранения: ' + (err instanceof Error ? err.message : 'Неизвестная ошибка'));
    }
  };

  const handleSaveRegister = async (registerId: string) => {
    if (!editValue.trim()) return;
    try {
      await updateRegisterName(registerId, editValue.trim());
      setEditingRegister(null);
      await loadDevices();
    } catch (err) {
      alert('Ошибка сохранения: ' + (err instanceof Error ? err.message : 'Неизвестная ошибка'));
    }
  };

  const getDeviceStatus = (lastSeenAt: string | null): { status: string; color: string } => {
    if (!lastSeenAt) {
      return { status: 'Никогда не подключалось', color: 'text-gray-500' };
    }

    const lastSeen = new Date(lastSeenAt);
    const now = new Date();
    const minutesAgo = (now.getTime() - lastSeen.getTime()) / 1000 / 60;

    if (minutesAgo < 5) {
      return { status: 'Онлайн', color: 'text-green-600' };
    } else if (minutesAgo < 30) {
      return { status: `Онлайн (${Math.floor(minutesAgo)} мин назад)`, color: 'text-yellow-600' };
    } else {
      return { status: 'Оффлайн', color: 'text-red-600' };
    }
  };

  const formatDateTime = (dateStr: string | null): string => {
    if (!dateStr) return '—';
    const date = new Date(dateStr);
    return date.toLocaleString('ru-RU', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (loading && devices.length === 0) {
    return <LoadingState message="Загрузка устройств..." />;
  }

  if (error && devices.length === 0) {
    return <ErrorState message={error} onRetry={loadDevices} />;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Устройства</h1>
          <p className="text-sm text-gray-600 mt-1">
            Подключенные устройства и их статус в реальном времени
          </p>
        </div>
        <button
          onClick={loadDevices}
          disabled={loading}
          className="px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50"
        >
          {loading ? 'Обновление...' : 'Обновить'}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
          {error}
        </div>
      )}

      <div className="bg-white rounded-lg shadow">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Статус
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Точка продаж
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Касса
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Device ID
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Последнее подключение
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Активность
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {devices.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-gray-500">
                    Нет подключенных устройств
                  </td>
                </tr>
              ) : (
                devices.map((device) => {
                  const { status, color } = getDeviceStatus(device.last_seen_at);
                  return (
                    <tr key={device.device_id} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center">
                          <div className={`h-3 w-3 rounded-full ${color.replace('text-', 'bg-')} mr-2`}></div>
                          <span className={`text-sm font-medium ${color}`}>{status}</span>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        {editingPoint === device.point_id ? (
                          <div className="flex items-center gap-2">
                            <input
                              type="text"
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') handleSavePoint(device.point_id);
                                if (e.key === 'Escape') setEditingPoint(null);
                              }}
                              className="px-2 py-1 border border-gray-300 rounded text-sm w-full"
                              autoFocus
                            />
                            <button
                              onClick={() => handleSavePoint(device.point_id)}
                              className="px-2 py-1 bg-green-600 text-white text-xs rounded hover:bg-green-700"
                            >
                              ✓
                            </button>
                            <button
                              onClick={() => setEditingPoint(null)}
                              className="px-2 py-1 bg-gray-400 text-white text-xs rounded hover:bg-gray-500"
                            >
                              ✕
                            </button>
                          </div>
                        ) : (
                          <div
                            onClick={() => handleEditPoint(device)}
                            className="cursor-pointer hover:bg-gray-100 px-2 py-1 rounded"
                          >
                            <div className="text-sm font-medium text-gray-900">
                              {device.point_name || 'Без названия'}
                            </div>
                            <div className="text-xs text-gray-500 font-mono">
                              {device.point_id.split('-')[0]}...
                            </div>
                          </div>
                        )}
                      </td>
                      <td className="px-6 py-4">
                        {editingRegister === device.register_id ? (
                          <div className="flex items-center gap-2">
                            <input
                              type="text"
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') handleSaveRegister(device.register_id);
                                if (e.key === 'Escape') setEditingRegister(null);
                              }}
                              className="px-2 py-1 border border-gray-300 rounded text-sm w-full"
                              autoFocus
                            />
                            <button
                              onClick={() => handleSaveRegister(device.register_id)}
                              className="px-2 py-1 bg-green-600 text-white text-xs rounded hover:bg-green-700"
                            >
                              ✓
                            </button>
                            <button
                              onClick={() => setEditingRegister(null)}
                              className="px-2 py-1 bg-gray-400 text-white text-xs rounded hover:bg-gray-500"
                            >
                              ✕
                            </button>
                          </div>
                        ) : (
                          <div
                            onClick={() => handleEditRegister(device)}
                            className="cursor-pointer hover:bg-gray-100 px-2 py-1 rounded"
                          >
                            <div className="text-sm font-medium text-gray-900">
                              {device.register_name || 'Без названия'}
                            </div>
                            <div className="text-xs text-gray-500 font-mono">
                              {device.register_id.split('-')[0]}...
                            </div>
                          </div>
                        )}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="text-sm font-mono text-gray-600">
                          {device.device_id.split('-')[0]}...
                        </div>
                        <div className="text-xs text-gray-400 font-mono">{device.device_id}</div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="text-sm text-gray-900">
                          {formatDateTime(device.last_seen_at)}
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        {device.is_enabled ? (
                          <span className="px-2 py-1 text-xs font-medium bg-green-100 text-green-800 rounded">
                            Включено
                          </span>
                        ) : (
                          <span className="px-2 py-1 text-xs font-medium bg-red-100 text-red-800 rounded">
                            Отключено
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg
              className="h-5 w-5 text-blue-400"
              fill="currentColor"
              viewBox="0 0 20 20"
            >
              <path
                fillRule="evenodd"
                d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                clipRule="evenodd"
              />
            </svg>
          </div>
          <div className="ml-3">
            <h3 className="text-sm font-medium text-blue-800">Редактирование названий</h3>
            <div className="mt-2 text-sm text-blue-700">
              <p>
                Кликните на название точки продаж или кассы, чтобы изменить его.
                Нажмите Enter для сохранения или Esc для отмены.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
