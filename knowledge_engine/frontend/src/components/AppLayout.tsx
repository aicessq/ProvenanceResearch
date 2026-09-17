import { NavLink } from 'react-router-dom';
import type { ReactNode } from 'react';

const navItems = [
  { to: '/', label: 'Dashboard' },
  { to: '/upload', label: 'Upload' },
  { to: '/retrieve', label: 'Retrieve' },
  { to: '/rewrite', label: 'Rewrite' },
  { to: '/answer', label: 'Answer' },
  { to: '/eval', label: 'Eval' },
];

export function AppLayout({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <p className="eyebrow">CyberSec RAG Agent</p>
          <h1>Frontend MVP</h1>
          <p className="brand-copy">面向当前 FastAPI 后端的工程演示前端。</p>
        </div>
        <nav className="nav-list">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="main-panel">{children}</main>
    </div>
  );
}
