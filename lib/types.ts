export type Mode = "hr" | "legal" | "healthcare" | "education" | "general";
export type Risk = "low" | "medium" | "high";

export type RunRequest = {
  rawPrompt: string;
  mode?: Mode;
};

export type SensitiveEntity = {
  text: string;
  type: string;
  risk: Risk;
  replacementHint?: string;
};

export type CheckerResult = {
  passed: boolean;
  riskLevel: Risk;
  leakageTypes: string[];
  leakedItems: string[];
  explanation?: string;
  recommendedFix?: string;
};

export type UtilityResult = {
  utilityScore: number;
  preservedConcepts: string[];
  missingUsefulContext: string[];
};

export type ExternalConsultantResponse = {
  advice: string;
  suggestedStructure: string[];
  outputFormat?: string | null;
  finalizerInstructions?: string | null;
  risks: string[];
};

export type RunResponse = {
  rawPrompt: string;
  detectedEntities: SensitiveEntity[];
  initialSanitizedPrompt: string;
  checkerResult: CheckerResult;
  repairedSanitizedPrompt?: string | null;
  finalCheckerResult: CheckerResult;
  utilityResult: UtilityResult;
  externalCallAllowed: boolean;
  externalConsultantResponse?: ExternalConsultantResponse | null;
  finalAnswer: string;
  weaveTraceUrl?: string | null;
  promptVersions?: {
    deidPrompt: string;
    checkerPrompt: string;
    repairPrompt: string;
  };
  weaveMetadata?: {
    traceName: string;
    project: string;
    status: string;
    runId?: string | null;
    traceId?: string | null;
    dashboardUrl?: string | null;
    trackingStatus?: string;
    evalScores: Record<string, number>;
    promptComparison: Array<Record<string, number | string>>;
  };
};

export type DemoExample = {
  label: string;
  prompt: string;
};

export type PipelinePatch = Partial<RunResponse>;

export type PipelineEvent = {
  stage: string;
  patch?: PipelinePatch;
  error?: string;
};
