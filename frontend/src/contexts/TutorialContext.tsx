/** Tutorial context for managing tutorial state. */

import { useState, useEffect, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { TutorialContext } from './TutorialContextInstance';

// Routes where tutorial should not appear
const AUTH_ROUTES = ['/login', '/register'];

function isAuthRoute(pathname: string): boolean {
  return AUTH_ROUTES.some(route => pathname.startsWith(route));
}

export function TutorialProvider({ children, isAuth }: { children: ReactNode; isAuth: boolean }) {
  const [showTutorial, setShowTutorial] = useState(false);
  const [step, setStep] = useState(0);
  const location = useLocation();

  useEffect(() => {
    // Don't show tutorial on auth routes
    if (isAuthRoute(location.pathname)) {
      setShowTutorial(false);
      return;
    }

    // Check if this is a new visit/session
    const lastVisit = sessionStorage.getItem('atlasx_last_visit');
    const currentVisit = Date.now().toString();

    // If no last visit or different session, show tutorial
    if (!lastVisit) {
      setShowTutorial(true);
      sessionStorage.setItem('atlasx_last_visit', currentVisit);
    }
  }, [location.pathname, isAuth]);

  const nextStep = () => {
    const maxSteps = isAuth ? 5 : 1;
    if (step < maxSteps - 1) {
      setStep(step + 1);
    } else {
      setShowTutorial(false);
    }
  };

  const prevStep = () => {
    if (step > 0) {
      setStep(step - 1);
    }
  };

  const skipTutorial = () => {
    setShowTutorial(false);
    setStep(0);
  };

  const replayTutorial = () => {
    setStep(0);
    setShowTutorial(true);
  };

  return (
    <TutorialContext.Provider
      value={{
        showTutorial,
        step,
        isAuth,
        setShowTutorial,
        setStep,
        nextStep,
        prevStep,
        skipTutorial,
        replayTutorial,
      }}
    >
      {children}
    </TutorialContext.Provider>
  );
}
