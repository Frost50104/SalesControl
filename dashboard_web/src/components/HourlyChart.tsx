import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  BarChart,
  Bar,
} from 'recharts';
import type { HourlyStats } from '../api/types';

interface HourlyChartProps {
  data: HourlyStats[];
}

export default function HourlyChart({ data }: HourlyChartProps) {
  const chartData = data.map((item) => ({
    hour: `${item.hour}:00`,
    'Диалогов': item.dialogues_total,
    'Попыток': item.attempted_yes,
    'Успешных': item.accepted_count,
    'Ср. качество': item.avg_quality,
  }));

  if (chartData.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow p-4">
        <h3 className="text-lg font-semibold text-gray-800 mb-4">По часам</h3>
        <div className="h-64 flex items-center justify-center text-gray-500">
          Нет данных за выбранный период
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h3 className="text-lg font-semibold text-gray-800 mb-4">
        Динамика по часам
      </h3>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div>
          <p className="text-sm text-gray-600 mb-2">Количество диалогов и попыток</p>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="hour" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="Диалогов" fill="#93c5fd" />
              <Bar dataKey="Попыток" fill="#86efac" />
              <Bar dataKey="Успешных" fill="#fcd34d" />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div>
          <p className="text-sm text-gray-600 mb-2">Среднее качество</p>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="hour" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 3]} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="Ср. качество"
                stroke="#8b5cf6"
                strokeWidth={2}
                dot={{ r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
