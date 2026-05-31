import type { DemoExample, RunResponse } from "@/lib/types";

export const examples: DemoExample[] = [
  {
    label: "HR leave",
    prompt:
      "Sarah Klein at Acme Robotics in Boston requested medical leave after a panic disorder diagnosis. Two weeks later, her manager Alex put her on a PIP. Help me write a careful HR response."
  },
  {
    label: "Legal deposit",
    prompt:
      "My landlord Mark Benson at 45 Winter Street in Cambridge says he will keep my security deposit because of damage from March 7. Help me write a response."
  },
  {
    label: "Healthcare",
    prompt:
      "John Smith lives at 14 Beacon Street and was prescribed sertraline by Dr. Rosen after panic attacks began in April. Help me prepare questions."
  },
  {
    label: "Education",
    prompt:
      "Maya Patel, a Northeastern student in CS 3500, says Professor Lee accused her of cheating on Project 4. Help draft a careful reply."
  },
  {
    label: "Blocked gate",
    prompt: "A person had a situation. Help write a response."
  }
];

export const fallbackResponse: RunResponse = {
  rawPrompt: examples[0].prompt,
  detectedEntities: [
    { text: "Sarah Klein", type: "PERSON", risk: "high", replacementHint: "the employee" },
    { text: "Acme Robotics", type: "ORGANIZATION", risk: "high", replacementHint: "a company" },
    { text: "Boston", type: "LOCATION", risk: "medium", replacementHint: "a location" },
    { text: "Alex", type: "PERSON", risk: "high", replacementHint: "the manager" },
    { text: "panic disorder", type: "HEALTH_INFORMATION", risk: "medium", replacementHint: "health diagnosis" }
  ],
  initialSanitizedPrompt:
    "An employee at Acme Robotics requested medical leave after a panic disorder diagnosis. Soon after, their manager put them on a PIP. Help write a careful HR response.",
  checkerResult: {
    passed: false,
    riskLevel: "high",
    leakageTypes: ["organization_leak", "over_specific_health_detail"],
    leakedItems: ["Acme Robotics", "panic disorder"],
    explanation: "The organization name remains, and the diagnosis is more specific than the external consultant needs.",
    recommendedFix: "Replace the organization with 'a company' and the diagnosis with 'health diagnosis'."
  },
  repairedSanitizedPrompt:
    "An employee at a company requested medical-related leave after a health diagnosis. Soon after, the employee received a performance-related warning from their manager. Help structure a careful HR response that is neutral, evidence-based, and avoids overclaiming.",
  finalCheckerResult: {
    passed: true,
    riskLevel: "low",
    leakageTypes: [],
    leakedItems: [],
    explanation: "No direct identifiers or over-specific sensitive facts remain."
  },
  utilityResult: {
    utilityScore: 0.86,
    preservedConcepts: ["employee", "medical leave", "health diagnosis", "performance warning", "manager"],
    missingUsefulContext: ["exact timeline is generalized"]
  },
  externalCallAllowed: true,
  externalConsultantResponse: {
    advice:
      "Focus on the timeline, neutral tone, documentation, clarification, and avoiding legal conclusions. Ask for the specific basis of the warning and avoid speculating about intent.",
    outputFormat: "Format the final answer as a concise email to HR.",
    finalizerInstructions:
      "Use the original names and private timeline locally, ask for clarification and documentation, and avoid making legal conclusions.",
    suggestedStructure: [
      "acknowledge the concern",
      "state the timeline neutrally",
      "ask for the basis of the warning",
      "request review of documentation",
      "ask about next steps"
    ],
    risks: ["do not make definitive legal claims", "avoid accusing the manager of intent"]
  },
  finalAnswer:
    "Hi HR,\n\nI would like to clarify the timeline around Sarah Klein's PIP and her earlier request for medical leave. My understanding is that Sarah Klein requested leave after a panic disorder diagnosis, and two weeks later Alex placed her on a PIP. I am not trying to assume anyone's intent, but I would like the company to review the documentation, the stated basis for the PIP, and whether the timing raises any process concerns.\n\nCould you please confirm the next step, what records should be provided, and who will review the matter?",
  weaveTraceUrl: null,
  promptVersions: {
    deidPrompt: "deid_prompt:v2-semantic-abstraction",
    checkerPrompt: "checker_prompt:v2-privacy-gate",
    repairPrompt: "repair_prompt:v1-generalize-leaks"
  },
  weaveMetadata: {
    traceName: "closedai-private-consult-run",
    project: "closedai",
    status: "offline-compatible",
    evalScores: {
      direct_leakage: 1,
      semantic_utility: 0.86,
      checker_pass: 1,
      repair_success: 1
    },
    promptComparison: [
      { version: "deid_prompt:v1-redaction", leakagePassRate: 0.7, avgUtilityScore: 0.62 },
      { version: "deid_prompt:v2-semantic-abstraction", leakagePassRate: 0.95, avgUtilityScore: 0.86 }
    ]
  }
};
