import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { TutorialProvider } from './contexts/TutorialContext';
import { ThemeProvider } from './contexts/ThemeContext';
import { ErrorBoundary } from './components/ErrorBoundary';
import { Tutorial } from './components/Tutorial';
import { ProtectedRoute } from './components/ProtectedRoute';
import { useAuth } from './hooks/useAuth';
import Login from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import CreateTask from './pages/CreateTask';
import TaskDetail from './pages/TaskDetail';
import ResearchPlayground from './pages/ResearchPlayground';
import SecurityCenter from './pages/SecurityCenter';
import ProvenanceExplorer from './pages/ProvenanceExplorer';
import Benchmarks from './pages/Benchmarks';
import NotFound from './pages/NotFound';

function AppContent() {
  const { user } = useAuth();
  const isAuth = !!user;

  return (
    <TutorialProvider isAuth={isAuth}>
      <Tutorial />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/tasks/create"
          element={
            <ProtectedRoute>
              <CreateTask />
            </ProtectedRoute>
          }
        />
        <Route
          path="/tasks/:id"
          element={
            <ProtectedRoute>
              <TaskDetail />
            </ProtectedRoute>
          }
        />
        <Route
          path="/playground"
          element={
            <ProtectedRoute>
              <ResearchPlayground />
            </ProtectedRoute>
          }
        />
        <Route
          path="/security"
          element={
            <ProtectedRoute>
              <SecurityCenter />
            </ProtectedRoute>
          }
        />
        <Route
          path="/provenance"
          element={
            <ProtectedRoute>
              <ProvenanceExplorer />
            </ProtectedRoute>
          }
        />
        <Route
          path="/benchmarks"
          element={
            <ProtectedRoute>
              <Benchmarks />
            </ProtectedRoute>
          }
        />
        <Route path="/404" element={<NotFound />} />
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </TutorialProvider>
  );
}

function App() {
  return (
    <React.Fragment>
      <ErrorBoundary>
        <BrowserRouter>
          <ThemeProvider>
            <AuthProvider>
              <AppContent />
            </AuthProvider>
          </ThemeProvider>
        </BrowserRouter>
      </ErrorBoundary>
    </React.Fragment>
  );
}

export default App;
