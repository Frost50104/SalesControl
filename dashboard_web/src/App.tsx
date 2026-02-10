import { Routes, Route, Navigate } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { getToken, getBaseUrl } from './auth/tokenStore';
import Header from './components/Header';
import LoginPage from './pages/LoginPage';
import OverviewPage from './pages/OverviewPage';
import DialoguesPage from './pages/DialoguesPage';
import ReviewsPage from './pages/ReviewsPage';
import UsersPage from './pages/UsersPage';

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  useEffect(() => {
    const token = getToken();
    const baseUrl = getBaseUrl();
    setIsAuthenticated(!!token && !!baseUrl);
  }, []);

  const handleLogin = () => {
    setIsAuthenticated(true);
  };

  const handleLogout = () => {
    sessionStorage.removeItem('adminToken');
    sessionStorage.removeItem('apiBaseUrl');
    setIsAuthenticated(false);
  };

  if (!isAuthenticated) {
    return <LoginPage onLogin={handleLogin} />;
  }

  return (
    <div className="min-h-screen bg-gray-100">
      <Header onLogout={handleLogout} />
      <main className="container mx-auto px-4 py-6">
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/dialogues" element={<DialoguesPage />} />
          <Route path="/reviews" element={<ReviewsPage />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
