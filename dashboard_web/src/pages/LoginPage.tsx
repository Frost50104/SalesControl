import { useState } from 'react';
import { setToken, setBaseUrl } from '../auth/tokenStore';
import { checkHealth, validateToken } from '../api/client';

interface LoginPageProps {
  onLogin: () => void;
}

export default function LoginPage({ onLogin }: LoginPageProps) {
  const [token, setTokenValue] = useState('');
  const [baseUrl, setBaseUrlValue] = useState('http://localhost:8000');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    // Normalize URL
    let normalizedUrl = baseUrl.trim();
    if (normalizedUrl.endsWith('/')) {
      normalizedUrl = normalizedUrl.slice(0, -1);
    }

    // Save credentials temporarily to test
    setToken(token.trim());
    setBaseUrl(normalizedUrl);

    try {
      // Check if API is reachable
      const healthy = await checkHealth();
      if (!healthy) {
        setError('API недоступен. Проверьте URL.');
        setLoading(false);
        return;
      }

      // Validate token
      const valid = await validateToken();
      if (!valid) {
        setError('Неверный токен (401 Unauthorized)');
        setLoading(false);
        return;
      }

      onLogin();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Неизвестная ошибка';
      setError(`Ошибка подключения: ${message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-primary-600 to-primary-800 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-2xl p-8 w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-gray-900">SalesControl</h1>
          <p className="text-gray-600 mt-2">Введите данные для входа</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          <div>
            <label
              htmlFor="baseUrl"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              URL API
            </label>
            <input
              type="url"
              id="baseUrl"
              value={baseUrl}
              onChange={(e) => setBaseUrlValue(e.target.value)}
              placeholder="http://localhost:8000"
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              required
            />
          </div>

          <div>
            <label
              htmlFor="token"
              className="block text-sm font-medium text-gray-700 mb-1"
            >
              Admin Token
            </label>
            <input
              type="password"
              id="token"
              value={token}
              onChange={(e) => setTokenValue(e.target.value)}
              placeholder="Введите токен"
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
              required
            />
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 px-4 bg-primary-600 text-white font-medium rounded-lg hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? (
              <span className="flex items-center justify-center">
                <svg
                  className="animate-spin -ml-1 mr-3 h-5 w-5 text-white"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                Проверка...
              </span>
            ) : (
              'Войти'
            )}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-gray-500">
          Токен хранится только в sessionStorage браузера
        </p>
      </div>
    </div>
  );
}
