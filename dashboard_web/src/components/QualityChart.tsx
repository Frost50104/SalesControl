import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Legend,
  Tooltip,
} from 'recharts';

interface QualityChartProps {
  distribution: Record<number, number>;
}

const QUALITY_LABELS: Record<number, string> = {
  0: 'Нет попытки (0)',
  1: 'Слабая (1)',
  2: 'Хорошая (2)',
  3: 'Отличная (3)',
};

const QUALITY_COLORS: Record<number, string> = {
  0: '#ef4444',
  1: '#f97316',
  2: '#84cc16',
  3: '#22c55e',
};

export default function QualityChart({ distribution }: QualityChartProps) {
  const data = Object.entries(distribution)
    .map(([score, count]) => ({
      name: QUALITY_LABELS[Number(score)] || `Score ${score}`,
      value: count,
      score: Number(score),
    }))
    .filter((item) => item.value > 0);

  const total = data.reduce((sum, item) => sum + item.value, 0);

  if (total === 0) {
    return (
      <div className="bg-white rounded-lg shadow p-4">
        <h3 className="text-lg font-semibold text-gray-800 mb-4">
          Распределение качества
        </h3>
        <div className="h-64 flex items-center justify-center text-gray-500">
          Нет данных за выбранный период
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h3 className="text-lg font-semibold text-gray-800 mb-4">
        Распределение качества
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            labelLine={false}
            label={({ percent }) =>
              percent > 0.05 ? `${(percent * 100).toFixed(0)}%` : ''
            }
            outerRadius={80}
            fill="#8884d8"
            dataKey="value"
          >
            {data.map((entry) => (
              <Cell
                key={`cell-${entry.score}`}
                fill={QUALITY_COLORS[entry.score]}
              />
            ))}
          </Pie>
          <Tooltip
            formatter={(value: number) => [
              `${value} (${((value / total) * 100).toFixed(1)}%)`,
              'Количество',
            ]}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
