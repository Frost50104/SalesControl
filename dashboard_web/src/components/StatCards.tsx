import type { DailyAnalyticsResponse } from '../api/types';

interface StatCardsProps {
  data: DailyAnalyticsResponse;
}

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  color?: 'blue' | 'green' | 'yellow' | 'red' | 'purple';
}

function StatCard({ title, value, subtitle, color = 'blue' }: StatCardProps) {
  const colorClasses = {
    blue: 'bg-blue-50 border-blue-200 text-blue-700',
    green: 'bg-green-50 border-green-200 text-green-700',
    yellow: 'bg-yellow-50 border-yellow-200 text-yellow-700',
    red: 'bg-red-50 border-red-200 text-red-700',
    purple: 'bg-purple-50 border-purple-200 text-purple-700',
  };

  return (
    <div className={`rounded-lg border p-4 ${colorClasses[color]}`}>
      <p className="text-sm font-medium opacity-80">{title}</p>
      <p className="text-2xl font-bold mt-1">{value}</p>
      {subtitle && <p className="text-xs opacity-70 mt-1">{subtitle}</p>}
    </div>
  );
}

export default function StatCards({ data }: StatCardsProps) {
  const attemptedRate = (data.attempted_rate * 100).toFixed(1);
  const acceptedRate = (data.accepted_rate * 100).toFixed(1);

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <StatCard
        title="Всего диалогов"
        value={data.dialogues_total}
        subtitle={`Обработано: ${data.dialogues_analyzed}`}
        color="blue"
      />
      <StatCard
        title="Попыток допродажи"
        value={data.attempted_yes}
        subtitle={`${attemptedRate}% от обработанных`}
        color="green"
      />
      <StatCard
        title="Среднее качество"
        value={data.avg_quality.toFixed(2)}
        subtitle="из 3.00"
        color="purple"
      />
      <StatCard
        title="Принято клиентом"
        value={data.accepted_count}
        subtitle={`${acceptedRate}% успешности`}
        color="yellow"
      />
    </div>
  );
}
