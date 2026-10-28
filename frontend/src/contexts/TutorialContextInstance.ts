/** Tutorial context instance (non-component) for Fast Refresh compatibility. */

import { createContext } from 'react';

interface TutorialContextType {
  showTutorial: boolean;
  step: number;
  isAuth: boolean;
  setShowTutorial: (show: boolean) => void;
  setStep: (step: number) => void;
  nextStep: () => void;
  prevStep: () => void;
  skipTutorial: () => void;
  replayTutorial: () => void;
}

export const TutorialContext = createContext<TutorialContextType | undefined>(undefined);
