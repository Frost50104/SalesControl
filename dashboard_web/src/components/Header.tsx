import { NavLink } from 'react-router-dom';
import clsx from 'clsx';

interface HeaderProps {
  onLogout: () => void;
}

export default function Header({ onLogout }: HeaderProps) {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    clsx(
      'px-3 py-2 rounded-md text-sm font-medium transition-colors',
      isActive
        ? 'bg-primary-700 text-white'
        : 'text-primary-100 hover:bg-primary-500 hover:text-white'
    );

  return (
    <header className="bg-primary-600 shadow-lg">
      <div className="container mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center space-x-8">
            <h1 className="text-xl font-bold text-white">SalesControl</h1>
            <nav className="flex space-x-2">
              <NavLink to="/" className={linkClass}>
                Обзор
              </NavLink>
              <NavLink to="/dialogues" className={linkClass}>
                Диалоги
              </NavLink>
              <NavLink to="/reviews" className={linkClass}>
                Проверка
              </NavLink>
              <NavLink to="/devices" className={linkClass}>
                Устройства
              </NavLink>
              <NavLink to="/users" className={linkClass}>
                Пользователи
              </NavLink>
            </nav>
          </div>
          <button
            onClick={onLogout}
            className="px-3 py-2 text-sm text-primary-100 hover:text-white hover:bg-primary-500 rounded-md transition-colors"
          >
            Выйти
          </button>
        </div>
      </div>
    </header>
  );
}
