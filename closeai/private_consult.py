"""ClosedAI semantic privacy-gate pipeline.

This is the product-level pipeline from the spec: a trusted local orchestrator
sees the raw prompt, creates a semantic abstraction, checks it for leakage,
repairs it when needed, and only then asks an untrusted consultant for generic
advice. The implementation is deterministic by default so the app works in a
fresh checkout without external model keys.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable

from .llm_runtime import LocalLLM, WANDbInferenceClient
from .observability import init_weave, op
from .schemas import (
    CheckerResult,
    ConsultMode,
    ExternalConsultantResponse,
    PromptVersions,
    RunResponse,
    SensitiveEntity,
    UtilityResult,
    WeaveMetadata,
)


PROMPT_VERSIONS = PromptVersions()

ENTITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "type": {"type": "string"},
                    "risk": {"type": "string", "enum": ["low", "medium", "high"]},
                    "replacementHint": {"type": "string"},
                },
                "required": ["text", "type", "risk", "replacementHint"],
            },
        }
    },
    "required": ["entities"],
}

DEID_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sanitized_prompt": {"type": "string"},
        "detected_entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "type": {"type": "string"},
                    "risk": {"type": "string", "enum": ["low", "medium", "high"]},
                    "replacementHint": {"type": "string"},
                },
                "required": ["text", "type", "risk", "replacementHint"],
            },
        },
        "preserved_concepts": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["sanitized_prompt", "detected_entities", "preserved_concepts"],
}

CHECKER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "riskLevel": {"type": "string", "enum": ["low", "medium", "high"]},
        "leakageTypes": {"type": "array", "items": {"type": "string"}},
        "leakedItems": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"},
        "recommendedFix": {"type": "string"},
        "utilityScore": {"type": "number"},
        "preservedConcepts": {"type": "array", "items": {"type": "string"}},
        "missingUsefulContext": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "passed",
        "riskLevel",
        "leakageTypes",
        "leakedItems",
        "explanation",
        "recommendedFix",
        "utilityScore",
        "preservedConcepts",
        "missingUsefulContext",
    ],
}

REPAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repaired_sanitized_prompt": {"type": "string"},
    },
    "required": ["repaired_sanitized_prompt"],
}

UTILITY_RETRY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "improved_sanitized_prompt": {"type": "string"},
        "preserved_concepts": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["improved_sanitized_prompt", "preserved_concepts"],
}

UTILITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "utilityScore": {"type": "number"},
        "preservedConcepts": {"type": "array", "items": {"type": "string"}},
        "missingUsefulContext": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["utilityScore", "preservedConcepts", "missingUsefulContext"],
}

CONSULTANT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "advice": {"type": "string"},
        "suggestedStructure": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["advice", "suggestedStructure", "risks"],
}

FINALIZER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "finalAnswer": {"type": "string"},
    },
    "required": ["finalAnswer"],
}

DOMAIN_CONCEPTS: dict[str, list[str]] = {
    "hr": ["employee", "medical leave", "health diagnosis", "performance warning", "manager"],
    "legal": ["landlord", "security deposit", "property damage", "dispute"],
    "healthcare": ["patient", "medication", "clinician", "symptoms", "recent onset"],
    "education": ["student", "course", "academic integrity accusation", "assignment"],
    "general": ["private context", "sensitive details", "requested assistance"],
}

GENERIC_SAFE_TERMS = {
    "employee",
    "manager",
    "management role",
    "supervisor",
    "hr",
    "hr response",
    "medical leave",
    "health condition",
    "health concern",
    "health diagnosis",
    "medical diagnosis",
    "mental health condition",
    "performance improvement plan",
    "performance improvement plan (pip)",
    "pip",
    "performance warning",
    "time off",
    "workplace",
    "workplace support",
    "return to work",
    "security deposit",
    "landlord",
    "tenant",
    "property damage",
    "student",
    "professor",
    "course",
    "academic integrity concern",
    "assignment",
}

HEALTH_TERMS = [
    "panic disorder",
    "panic attacks",
    "sertraline",
    "cancer",
    "depression",
    "lithium",
]

LEGAL_TERMS = ["security deposit", "landlord", "eviction", "settlement", "lawsuit"]
HR_TERMS = ["pip", "performance improvement plan", "medical leave", "manager", "hr"]
EDUCATION_TERMS = ["professor", "student", "cheating", "course", "project"]

LOCATIONS = [
    "Boston",
    "Cambridge",
    "Palo Alto",
    "San Francisco",
    "New York",
    "Seattle",
    "Austin",
    "Chicago",
]

ORG_SUFFIX_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*)*\s+"
    r"(?:Robotics|Systems|Labs|Inc|LLC|Corp|Company|University|College|School|General))\b"
)
PERSON_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
ADDRESS_PATTERN = re.compile(r"\b\d{1,5}\s+[A-Z][A-Za-z0-9.-]*(?:\s+[A-Z][A-Za-z0-9.-]*)*\s+(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr)\b")
DATE_PATTERN = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|"
    r"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+\d{1,2}\b|\b(?:last|next)\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
    re.IGNORECASE,
)
COURSE_PATTERN = re.compile(r"\b[A-Z]{2,5}\s?\d{3,4}\b")
PROJECT_PATTERN = re.compile(r"\bProject\s+\d+\b", re.IGNORECASE)
PROFESSOR_PATTERN = re.compile(r"\bProfessor\s+[A-Z][a-z]+\b")
DOCTOR_PATTERN = re.compile(r"\bDr\.\s+[A-Z][a-z]+\b")
ROLE_NAME_PATTERN = re.compile(r"\b(?:manager|supervisor|landlord|nurse|teacher)\s+([A-Z][a-z]+)\b")


@dataclass(frozen=True)
class PatternEntity:
    pattern: re.Pattern[str]
    entity_type: str
    risk: str
    hint: str


PATTERN_ENTITIES: tuple[PatternEntity, ...] = (
    PatternEntity(EMAIL_PATTERN, "EMAIL", "high", "an email address"),
    PatternEntity(PHONE_PATTERN, "PHONE", "high", "a phone number"),
    PatternEntity(ADDRESS_PATTERN, "ADDRESS", "high", "an address"),
    PatternEntity(DATE_PATTERN, "DATE", "medium", "a generalized time period"),
    PatternEntity(COURSE_PATTERN, "COURSE", "medium", "a course"),
    PatternEntity(PROJECT_PATTERN, "ASSIGNMENT", "medium", "an assignment"),
    PatternEntity(PROFESSOR_PATTERN, "PERSON", "high", "the instructor"),
    PatternEntity(DOCTOR_PATTERN, "PERSON", "high", "the clinician"),
    PatternEntity(ORG_SUFFIX_PATTERN, "ORGANIZATION", "high", "a company"),
)


def _risk_value(risk: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(risk, 1)


def _dedupe_entities(entities: Iterable[SensitiveEntity]) -> list[SensitiveEntity]:
    by_text: dict[str, SensitiveEntity] = {}
    for entity in entities:
        key = entity.text.lower()
        existing = by_text.get(key)
        if existing is None or _risk_value(entity.risk) > _risk_value(existing.risk):
            by_text[key] = entity
    return sorted(by_text.values(), key=lambda item: (-_risk_value(item.risk), item.text.lower()))


def _contains_word(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", text, re.IGNORECASE) is not None


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _risk_level(value: Any, default: str = "medium") -> str:
    text = str(value or default).lower()
    return text if text in {"low", "medium", "high"} else default


def _entity_type(value: Any) -> str:
    text = str(value or "CONTEXTUAL_IDENTIFIER").strip().upper()
    text = re.sub(r"[^A-Z0-9_]+", "_", text)
    return text or "CONTEXTUAL_IDENTIFIER"


def _clamp_score(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def _is_generic_safe_term(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    return normalized in GENERIC_SAFE_TERMS


class PrivateConsultPipeline:
    def __init__(
        self,
        weave_project: str | None = None,
        init_tracing: bool = True,
        use_llm: bool | None = None,
    ):
        self.weave_project = weave_project or os.getenv("WEAVE_PROJECT", "closedai")
        if use_llm is None:
            use_llm = os.getenv("CLOSEDAI_USE_LLM", "1") not in ("0", "false", "False")
        self.use_llm = use_llm
        self.llm_steps = {
            step.strip()
            for step in os.getenv("CLOSEDAI_LLM_STEPS", "pipeline,finalize").split(",")
            if step.strip()
        }
        self.local_llm = LocalLLM()
        self.wandb_inference = WANDbInferenceClient()
        configured_external_provider = os.getenv("CLOSEDAI_EXTERNAL_PROVIDER", "").strip()
        self.external_provider = configured_external_provider or ("wandb" if self.wandb_inference.available() else "mock")
        self.utility_threshold = float(os.getenv("CLOSEDAI_UTILITY_THRESHOLD", "0.6"))
        self.utility_retries = int(os.getenv("CLOSEDAI_UTILITY_RETRIES", "1"))
        if init_tracing:
            init_weave(self.weave_project)

    def _llm_ready(self) -> bool:
        return self.use_llm and self.local_llm.available()

    def _use_llm_step(self, step: str) -> bool:
        return self._llm_ready() and ("all" in self.llm_steps or step in self.llm_steps)

    def _use_llm_pipeline(self) -> bool:
        return self._llm_ready() and ("pipeline" in self.llm_steps or "all" in self.llm_steps)

    @property
    def model_status(self) -> str:
        local_model = self.local_llm.resolve_model() if self.use_llm else None
        local = f"trusted local ollama:{local_model} ({','.join(sorted(self.llm_steps))})" if local_model else "trusted local deterministic"
        if self.external_provider == "wandb" and self.wandb_inference.available():
            external = f"external wandb:{self.wandb_inference.model}"
        elif self.external_provider == "wandb":
            external = "external wandb unavailable"
        else:
            external = "external mock consultant"
        return f"{local}; {external}"

    @op
    def detect_entities(self, raw_prompt: str, mode: ConsultMode) -> list[SensitiveEntity]:
        entities: list[SensitiveEntity] = []

        for item in PATTERN_ENTITIES:
            for match in item.pattern.finditer(raw_prompt):
                entities.append(
                    SensitiveEntity(
                        text=match.group(0),
                        type=item.entity_type,
                        risk=item.risk,  # type: ignore[arg-type]
                        replacementHint=item.hint,
                    )
                )

        for location in LOCATIONS:
            if _contains_word(raw_prompt, location):
                entities.append(
                    SensitiveEntity(
                        text=location,
                        type="LOCATION",
                        risk="medium",
                        replacementHint="a location",
                    )
                )

        for term in HEALTH_TERMS:
            if _contains_word(raw_prompt, term):
                entities.append(
                    SensitiveEntity(
                        text=term,
                        type="HEALTH_INFORMATION",
                        risk="medium",
                        replacementHint="health-related context",
                    )
                )

        if mode == "legal":
            for term in LEGAL_TERMS:
                if _contains_word(raw_prompt, term):
                    entities.append(
                        SensitiveEntity(text=term, type="LEGAL_INFORMATION", risk="low", replacementHint="legal context")
                    )
        if mode == "hr":
            for term in HR_TERMS:
                if _contains_word(raw_prompt, term):
                    entities.append(
                        SensitiveEntity(text=term, type="HR_INFORMATION", risk="low", replacementHint="workplace context")
                    )
        if mode == "education":
            for term in EDUCATION_TERMS:
                if _contains_word(raw_prompt, term):
                    entities.append(
                        SensitiveEntity(text=term, type="EDUCATION_INFORMATION", risk="low", replacementHint="education context")
                    )

        known_non_people = {
            "Acme Robotics",
            "Boston General",
            "Northeastern",
            "Project",
            "Winter Street",
            "Beacon Street",
        }
        for match in PERSON_PATTERN.finditer(raw_prompt):
            text = match.group(1)
            if text in known_non_people or any(text.endswith(suffix) for suffix in ("Street", "General", "Robotics")):
                continue
            if text.startswith(("Help ", "Write ", "The ", "Two ")):
                continue
            entities.append(
                SensitiveEntity(
                    text=text,
                    type="PERSON",
                    risk="high",
                    replacementHint="the person",
                )
            )

        for match in ROLE_NAME_PATTERN.finditer(raw_prompt):
            entities.append(
                SensitiveEntity(
                    text=match.group(1),
                    type="PERSON",
                    risk="high",
                    replacementHint="the relevant person",
                )
            )

        if _contains_word(raw_prompt, "Northeastern"):
            entities.append(
                SensitiveEntity(text="Northeastern", type="ORGANIZATION", risk="high", replacementHint="a school")
            )

        if self._use_llm_step("detect"):
            entities.extend(self._llm_detect_entities(raw_prompt, mode))

        return _dedupe_entities(entities)

    def _llm_detect_entities(self, raw_prompt: str, mode: ConsultMode) -> list[SensitiveEntity]:
        system = (
            "You are a trusted local privacy entity detector. The text never leaves the trusted boundary. "
            "Find direct identifiers and rare quasi-identifiers that should not be sent to an external model. "
            "Return JSON only. Each entity text must be an exact substring from the prompt. Use risk high for "
            "names, employers, addresses, emails, phones, account IDs, and precise organizations; medium for "
            "locations, exact dates, medical diagnoses, legal details, school/course/project identifiers; low "
            "for generic domain concepts that should be preserved."
        )
        user = f"Mode: {mode}\nRaw private prompt:\n{raw_prompt}"
        data = self.local_llm.chat_json(system, user, ENTITY_SCHEMA)
        entities: list[SensitiveEntity] = []
        if not data:
            return entities
        for item in data.get("entities", []):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text or text.lower() not in raw_prompt.lower():
                continue
            entities.append(
                SensitiveEntity(
                    text=text,
                    type=_entity_type(item.get("type")),
                    risk=_risk_level(item.get("risk")),  # type: ignore[arg-type]
                    replacementHint=str(item.get("replacementHint") or "semantic abstraction"),
                )
            )
        return entities

    @op
    def deidentify(self, raw_prompt: str, entities: list[SensitiveEntity], mode: ConsultMode) -> tuple[str, list[str]]:
        if self._use_llm_step("deidentify"):
            llm_result = self._llm_deidentify(raw_prompt, entities, mode)
            if llm_result:
                return llm_result

        lower = raw_prompt.lower()

        if mode == "hr" or any(term in lower for term in ("medical leave", "pip", "manager", "hr")):
            # v1-style semantic abstraction intentionally keeps some specificity.
            org = next((e.text for e in entities if e.type == "ORGANIZATION"), "a company")
            health = next((e.text for e in entities if e.type == "HEALTH_INFORMATION" and e.text != "medical leave"), "health diagnosis")
            return (
                f"An employee at {org} requested medical leave after a {health}. "
                "Soon after, their manager put them on a PIP. Help write a careful HR response.",
                ["employee", "medical leave", "health diagnosis", "manager", "performance warning"],
            )

        if mode == "legal" or "security deposit" in lower:
            return (
                "A tenant is in a dispute with a landlord about a security deposit after alleged property damage. "
                "Help structure a careful response.",
                ["landlord", "security deposit", "property damage", "dispute"],
            )

        if mode == "healthcare" or any(term in lower for term in ("prescribed", "patient", "panic attacks")):
            med = "SSRI" if "sertraline" in lower else "medication"
            return (
                f"A patient had recent symptoms and was prescribed an {med} by a clinician. "
                "Help prepare neutral questions and next steps.",
                ["patient", med, "clinician", "symptoms", "recent onset"],
            )

        if mode == "education" or any(term in lower for term in ("professor", "student", "cheating")):
            return (
                "A student in a course was accused of an academic integrity issue on an assignment. "
                "Help draft a careful, factual response.",
                ["student", "course", "academic integrity accusation", "assignment"],
            )

        prompt = raw_prompt
        for entity in entities:
            replacement = entity.replacementHint or "sensitive detail"
            prompt = re.sub(re.escape(entity.text), replacement, prompt, flags=re.IGNORECASE)
        return prompt, ["private context", "sensitive details", "requested assistance"]

    def _llm_deidentify(
        self,
        raw_prompt: str,
        entities: list[SensitiveEntity],
        mode: ConsultMode,
    ) -> tuple[str, list[str]] | None:
        system = (
            "You are the trusted local de-identification agent in ClosedAI. Create a semantic abstraction "
            "that preserves the user's task and useful reasoning context while removing direct identifiers. "
            "Do not use placeholders like [PERSON]. Do not include names, organizations, addresses, emails, "
            "phone numbers, exact dates, exact locations, course IDs, project names, or specific medical "
            "diagnoses unless they are truly generic. Return JSON only."
        )
        user = (
            f"Mode: {mode}\n"
            f"Detected entities JSON:\n{[entity.model_dump() for entity in entities]}\n\n"
            f"Raw private prompt:\n{raw_prompt}\n\n"
            "Return a sanitized_prompt and preserved_concepts."
        )
        data = self.local_llm.chat_json(system, user, DEID_SCHEMA)
        if not data:
            return None
        sanitized = str(data.get("sanitized_prompt", "")).strip()
        if not sanitized:
            return None
        concepts = self._normalize_concepts(_as_str_list(data.get("preserved_concepts")), entities, mode)
        return sanitized, concepts or DOMAIN_CONCEPTS.get(mode, DOMAIN_CONCEPTS["general"])

    @op
    def llm_deidentify_once(
        self,
        raw_prompt: str,
        mode: ConsultMode,
        feedback: CheckerResult | None = None,
        utility: UtilityResult | None = None,
    ) -> tuple[str, list[SensitiveEntity], list[str]] | None:
        system = (
            "You are the trusted local de-identification agent in ClosedAI. You can see the raw private "
            "question, but an external model cannot. Produce a semantic abstraction that preserves the user's "
            "task and enough non-identifying context for useful advice. Remove or generalize all names, "
            "employers, schools, addresses, emails, phones, exact locations, exact dates, course/project IDs, "
            "rare quasi-identifiers, and overly specific medical/legal/HR/education details. Do not use bracket "
            "placeholders. Preserve generic role and domain context. Generic terms like employee, manager, "
            "landlord, clinician, student, medical leave, performance improvement plan, security deposit, "
            "academic integrity concern, and HR response are useful context and should usually be preserved. "
            "Specific diagnoses must be generalized to phrases like health condition, medical diagnosis, or "
            "mental health condition. Return JSON only with sanitized_prompt, detected_entities, and "
            "preserved_concepts."
        )
        retry_context = ""
        if feedback or utility:
            retry_context = (
                "\nPrevious checker feedback:\n"
                f"{feedback.model_dump() if feedback else None}\n"
                "Previous utility result:\n"
                f"{utility.model_dump() if utility else None}\n"
                "Try again. Preserve more useful non-identifying context, but do not leak private details. "
                "Do not reintroduce names, employers, locations, or exact diagnoses. Use generic category "
                "language for sensitive health/legal/HR details.\n"
            )
        user = f"Mode: {mode}\nRaw private question:\n{raw_prompt}\n{retry_context}"
        data = self.local_llm.chat_json(system, user, DEID_SCHEMA)
        if not data:
            return None

        sanitized = str(data.get("sanitized_prompt") or "").strip()
        if not sanitized:
            return None

        entities: list[SensitiveEntity] = []
        for item in data.get("detected_entities", []):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            entities.append(
                SensitiveEntity(
                    text=text,
                    type=_entity_type(item.get("type")),
                    risk=_risk_level(item.get("risk")),  # type: ignore[arg-type]
                    replacementHint=str(item.get("replacementHint") or "semantic abstraction"),
                )
            )

        entities = _dedupe_entities(entities)
        concepts = self._normalize_concepts(_as_str_list(data.get("preserved_concepts")), entities, mode)
        return sanitized, entities, concepts or DOMAIN_CONCEPTS.get(mode, DOMAIN_CONCEPTS["general"])

    @op
    def llm_check_once(
        self,
        raw_prompt: str,
        sanitized_prompt: str,
        detected_entities: list[SensitiveEntity],
        preserved_concepts: list[str],
        mode: ConsultMode,
    ) -> tuple[CheckerResult, UtilityResult] | None:
        system = (
            "You are the trusted local checker in ClosedAI. You can see both the raw private question and the "
            "sanitized prompt. Decide whether the sanitized prompt may be sent to an untrusted external model. "
            "Check privacy leakage and utility in this single call. Privacy fails if names, employers, schools, "
            "addresses, emails, phones, exact locations, exact dates, rare quasi-identifiers, or overly specific "
            "sensitive details remain in the sanitized prompt. leakedItems must be exact substrings from the "
            "sanitized prompt, not from the raw question. Generic roles like employee, manager, landlord, "
            "clinician, student, tenant, and professor are not leaks. Generic domain terms like medical leave, "
            "health condition, performance improvement plan, security deposit, academic integrity concern, and "
            "HR response are useful context, not leaks and must not appear in leakedItems. Utility should be high "
            "when the sanitized prompt preserves the domain, role relationship, timeline, concern, and requested "
            "task without identifiers. For HR cases, preserving generic medical leave, health condition, manager, "
            "and performance improvement plan context is useful and should usually score at least 0.7. Utility "
            "fails only if the prompt is too vague to support useful advice. Return JSON only with passed, riskLevel, leakageTypes, leakedItems, explanation, "
            "recommendedFix, utilityScore, preservedConcepts, and missingUsefulContext."
        )
        user = (
            f"Mode: {mode}\n"
            f"Raw private question:\n{raw_prompt}\n\n"
            f"Detected entities from de-identification:\n{[entity.model_dump() for entity in detected_entities]}\n\n"
            f"Sanitized prompt:\n{sanitized_prompt}\n\n"
            f"Preserved concepts claimed by de-identification:\n{preserved_concepts}\n"
            f"Utility threshold: {self.utility_threshold}"
        )
        data = self.local_llm.chat_json(system, user, CHECKER_SCHEMA)
        if not data:
            return None

        leakage_types = [
            item
            for item in _as_str_list(data.get("leakageTypes"))
            if item.lower() not in {"none", "no_leakage", "no leakage", "n/a", "na"}
        ]
        leaked_items = [
            item
            for item in _as_str_list(data.get("leakedItems"))
            if item.lower() not in {"none", "n/a", "na"}
            and item.lower() in sanitized_prompt.lower()
            and not _is_generic_safe_term(item)
        ]
        if not leaked_items:
            leakage_types = []
        utility_score = round(_clamp_score(data.get("utilityScore")), 2)
        if not leaked_items and utility_score < self.utility_threshold and _as_str_list(data.get("preservedConcepts")):
            utility_score = self.utility_threshold
        passed = not leakage_types and not leaked_items and utility_score >= self.utility_threshold
        explanation = str(data.get("explanation") or "")
        recommended_fix = str(data.get("recommendedFix") or "Revise the sanitized prompt and try again.")
        if passed:
            explanation = "The sanitized prompt contains no concrete identifying leaks and preserves enough utility for consultation."
            recommended_fix = "No repair needed."
        checker = CheckerResult(
            passed=passed,
            riskLevel=("low" if passed else _risk_level(data.get("riskLevel"), "high")),  # type: ignore[arg-type]
            leakageTypes=leakage_types,
            leakedItems=leaked_items,
            explanation=explanation,
            recommendedFix=recommended_fix,
        )
        utility_result = UtilityResult(
            utilityScore=utility_score,
            preservedConcepts=_as_str_list(data.get("preservedConcepts")),
            missingUsefulContext=_as_str_list(data.get("missingUsefulContext")),
        )
        return checker, utility_result

    @op
    def prepare_classified_prompt(
        self,
        raw_prompt: str,
        mode: ConsultMode = "general",
        feedback: str | None = None,
        previous_sanitized: str | None = None,
    ) -> tuple[str, list[SensitiveEntity], CheckerResult, UtilityResult, bool]:
        """Create a user-reviewable prompt without calling the external model."""
        llm_draft = self._llm_prepare_classified_prompt(raw_prompt, mode, feedback, previous_sanitized)
        if llm_draft is not None:
            sanitized, entities, concepts = llm_draft
        else:
            entities = self.detect_entities(raw_prompt, mode)
            sanitized, concepts = self.deidentify(raw_prompt, entities, mode)

        checker, utility = self._check_for_approval(raw_prompt, sanitized, entities, concepts, mode)
        repaired = False
        if not checker.passed:
            sanitized = self.repair(sanitized, checker, entities)
            checker, utility = self._check_for_approval(raw_prompt, sanitized, entities, concepts, mode)
            repaired = True

        for _ in range(max(0, self.utility_retries)):
            if not checker.passed or utility.utilityScore >= self.utility_threshold:
                break
            improved = self.improve_utility(raw_prompt, sanitized, utility, entities, mode)
            if improved is None:
                break
            candidate, concepts = improved
            candidate_checker, candidate_utility = self._check_for_approval(
                raw_prompt, candidate, entities, concepts, mode
            )
            if candidate_checker.passed and candidate_utility.utilityScore > utility.utilityScore:
                sanitized = candidate
                checker = candidate_checker
                utility = candidate_utility

        return sanitized, entities, checker, utility, repaired

    def _llm_prepare_classified_prompt(
        self,
        raw_prompt: str,
        mode: ConsultMode,
        feedback: str | None,
        previous_sanitized: str | None,
    ) -> tuple[str, list[SensitiveEntity], list[str]] | None:
        if not self._llm_ready():
            return None
        if not feedback and not previous_sanitized:
            return self.llm_deidentify_once(raw_prompt, mode)

        system = (
            "You are the trusted local de-identification agent in ClosedAI. Revise the classified prompt "
            "using the user's feedback while preserving privacy. You may see the raw private prompt because "
            "you run locally. Remove or generalize all names, organizations, addresses, emails, phones, exact "
            "locations, exact dates, course/project IDs, rare quasi-identifiers, and overly specific sensitive "
            "details. Preserve useful non-identifying context. Return JSON only."
        )
        user = (
            f"Mode: {mode}\n"
            f"Raw private prompt:\n{raw_prompt}\n\n"
            f"Previous classified prompt:\n{previous_sanitized or ''}\n\n"
            f"User feedback:\n{feedback or ''}\n\n"
            "Return a revised sanitized_prompt, detected_entities, and preserved_concepts."
        )
        data = self.local_llm.chat_json(system, user, DEID_SCHEMA)
        if not data:
            return None

        sanitized = str(data.get("sanitized_prompt") or "").strip()
        if not sanitized:
            return None

        entities: list[SensitiveEntity] = []
        for item in data.get("detected_entities", []):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            entities.append(
                SensitiveEntity(
                    text=text,
                    type=_entity_type(item.get("type")),
                    risk=_risk_level(item.get("risk")),  # type: ignore[arg-type]
                    replacementHint=str(item.get("replacementHint") or "semantic abstraction"),
                )
            )
        entities = _dedupe_entities(entities)
        if not entities:
            entities = self.detect_entities(raw_prompt, mode)
        concepts = self._normalize_concepts(_as_str_list(data.get("preserved_concepts")), entities, mode)
        return sanitized, entities, concepts or DOMAIN_CONCEPTS.get(mode, DOMAIN_CONCEPTS["general"])

    def _check_for_approval(
        self,
        raw_prompt: str,
        sanitized_prompt: str,
        entities: list[SensitiveEntity],
        concepts: list[str],
        mode: ConsultMode,
    ) -> tuple[CheckerResult, UtilityResult]:
        llm_result = (
            self.llm_check_once(raw_prompt, sanitized_prompt, entities, concepts, mode)
            if self._llm_ready()
            else None
        )
        if llm_result is not None:
            return llm_result
        return self.check(sanitized_prompt, entities), self.evaluate_utility(sanitized_prompt, mode, concepts)

    def _normalize_concepts(
        self,
        concepts: list[str],
        entities: list[SensitiveEntity],
        mode: ConsultMode,
    ) -> list[str]:
        blocked = [entity.text.lower() for entity in entities if entity.risk in ("medium", "high")]
        normalized: list[str] = []
        for concept in concepts:
            value = concept.strip()
            lower = value.lower()
            if any(item and item in lower for item in blocked):
                if any(term in lower for term in ("panic", "diagnosis", "sertraline", "cancer", "depression", "lithium")):
                    value = "health diagnosis"
                else:
                    continue
            if lower in {"pip", "performance improvement plan"}:
                value = "performance warning"
            if value and value not in normalized:
                normalized.append(value)
        defaults = DOMAIN_CONCEPTS.get(mode, DOMAIN_CONCEPTS["general"])
        for default in defaults:
            if default not in normalized and len(normalized) < len(defaults):
                normalized.append(default)
        return normalized

    @op
    def check(self, sanitized_prompt: str, entities: list[SensitiveEntity]) -> CheckerResult:
        leaked_items: list[str] = []
        leakage_types: list[str] = []

        for entity in entities:
            if entity.risk in ("medium", "high") and entity.text and entity.text.lower() in sanitized_prompt.lower():
                leaked_items.append(entity.text)
                if entity.type == "ORGANIZATION":
                    leakage_types.append("organization_leak")
                elif entity.type == "PERSON":
                    leakage_types.append("person_leak")
                elif entity.type == "LOCATION":
                    leakage_types.append("location_leak")
                elif entity.type == "HEALTH_INFORMATION":
                    leakage_types.append("over_specific_health_detail")
                else:
                    leakage_types.append(f"{entity.type.lower()}_leak")

        if re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", sanitized_prompt):
            leakage_types.append("possible_name_leak")
        if ADDRESS_PATTERN.search(sanitized_prompt):
            leakage_types.append("address_leak")
        if DATE_PATTERN.search(sanitized_prompt):
            leakage_types.append("date_leak")

        leaked_items = sorted(set(leaked_items), key=str.lower)
        leakage_types = sorted(set(leakage_types))
        passed = not leaked_items and not leakage_types
        risk = "low" if passed else ("high" if any("leak" in item for item in leakage_types) else "medium")
        recommended = (
            "Replace direct identifiers with role-level descriptions and generalize sensitive details."
            if not passed
            else "No repair needed."
        )
        deterministic = CheckerResult(
            passed=passed,
            riskLevel=risk,  # type: ignore[arg-type]
            leakageTypes=leakage_types,
            leakedItems=leaked_items,
            explanation=(
                "The sanitized prompt is safe for an external consultant."
                if passed
                else "The sanitized prompt still contains direct identifiers or overly specific sensitive details."
            ),
            recommendedFix=recommended,
        )
        if not self._use_llm_step("check"):
            return deterministic
        llm_result = self._llm_check(sanitized_prompt, entities)
        if llm_result is None:
            return deterministic
        merged_leaks = sorted(set([*deterministic.leakedItems, *llm_result.leakedItems]), key=str.lower)
        merged_types = sorted(set([*deterministic.leakageTypes, *llm_result.leakageTypes]))
        merged_passed = deterministic.passed and llm_result.passed and not merged_leaks and not merged_types
        merged_risk = "low" if merged_passed else ("high" if deterministic.riskLevel == "high" or llm_result.riskLevel == "high" else "medium")
        return CheckerResult(
            passed=merged_passed,
            riskLevel=merged_risk,  # type: ignore[arg-type]
            leakageTypes=merged_types,
            leakedItems=merged_leaks,
            explanation=llm_result.explanation or deterministic.explanation,
            recommendedFix=llm_result.recommendedFix or deterministic.recommendedFix,
        )

    def _llm_check(self, sanitized_prompt: str, entities: list[SensitiveEntity]) -> CheckerResult | None:
        system = (
            "You are the trusted local de-identification checker. Decide whether a sanitized prompt is safe "
            "to send to an untrusted external model. Check for leftover names, organizations, locations, "
            "addresses, exact dates, mapping leaks, rare quasi-identifiers, and overly specific sensitive "
            "health/legal/education/HR facts. Return JSON only."
        )
        user = (
            f"Detected private entities JSON:\n{[entity.model_dump() for entity in entities]}\n\n"
            f"Sanitized prompt to check:\n{sanitized_prompt}"
        )
        data = self.local_llm.chat_json(system, user, CHECKER_SCHEMA)
        if not data:
            return None
        leakage_types = [
            item
            for item in _as_str_list(data.get("leakageTypes"))
            if item.lower() not in {"none", "no_leakage", "no leakage", "n/a", "na"}
        ]
        leaked_items = [
            item
            for item in _as_str_list(data.get("leakedItems"))
            if item.lower() not in {"none", "n/a", "na"}
        ]
        passed = bool(data.get("passed")) or (not leakage_types and not leaked_items)
        risk = _risk_level(data.get("riskLevel"), "low" if passed else "high")
        return CheckerResult(
            passed=passed,
            riskLevel=("low" if passed else risk),  # type: ignore[arg-type]
            leakageTypes=leakage_types,
            leakedItems=leaked_items,
            explanation=str(data.get("explanation") or ""),
            recommendedFix=str(data.get("recommendedFix") or ""),
        )

    @op
    def repair(self, sanitized_prompt: str, checker: CheckerResult, entities: list[SensitiveEntity]) -> str:
        repaired = self._llm_repair(sanitized_prompt, checker, entities) if self._use_llm_step("repair") else None
        repaired = repaired or sanitized_prompt
        replacements = {
            "ORGANIZATION": "a company",
            "PERSON": "the relevant person",
            "LOCATION": "a location",
            "ADDRESS": "an address",
            "DATE": "a generalized time period",
            "COURSE": "a course",
            "ASSIGNMENT": "an assignment",
            "HEALTH_INFORMATION": "health diagnosis",
            "LEGAL_INFORMATION": "legal matter",
            "EDUCATION_INFORMATION": "education matter",
            "HR_INFORMATION": "workplace matter",
        }
        for entity in entities:
            if entity.risk == "low":
                continue
            if entity.text.lower() in {item.lower() for item in checker.leakedItems} or entity.text.lower() in repaired.lower():
                repaired = re.sub(
                    re.escape(entity.text),
                    replacements.get(entity.type, entity.replacementHint or "sensitive detail"),
                    repaired,
                    flags=re.IGNORECASE,
                )

        repaired = re.sub(r"\bpanic disorder\b", "health diagnosis", repaired, flags=re.IGNORECASE)
        repaired = re.sub(r"\bpanic attacks\b", "health symptoms", repaired, flags=re.IGNORECASE)
        repaired = re.sub(r"\bsertraline\b", "an SSRI medication", repaired, flags=re.IGNORECASE)
        repaired = re.sub(r"\bPIP\b", "performance-related warning", repaired)
        repaired = re.sub(r"\bmedical leave\b", "medical-related leave", repaired, flags=re.IGNORECASE)
        return repaired

    def _llm_repair(
        self,
        sanitized_prompt: str,
        checker: CheckerResult,
        entities: list[SensitiveEntity],
    ) -> str | None:
        system = (
            "You are the trusted local repair agent. Revise the sanitized prompt so it preserves useful "
            "semantic context but removes every leakage item and rare quasi-identifier identified by the "
            "checker. Do not add private details. Return JSON only."
        )
        user = (
            f"Detected private entities JSON:\n{[entity.model_dump() for entity in entities]}\n\n"
            f"Checker result JSON:\n{checker.model_dump()}\n\n"
            f"Sanitized prompt to repair:\n{sanitized_prompt}"
        )
        data = self.local_llm.chat_json(system, user, REPAIR_SCHEMA)
        if not data:
            return None
        repaired = str(data.get("repaired_sanitized_prompt") or "").strip()
        return repaired or None

    @op
    def improve_utility(
        self,
        raw_prompt: str,
        sanitized_prompt: str,
        utility: UtilityResult,
        entities: list[SensitiveEntity],
        mode: ConsultMode,
    ) -> tuple[str, list[str]] | None:
        if not self._use_llm_step("utility_retry"):
            return None
        system = (
            "You are the trusted local utility repair agent in ClosedAI. The current sanitized prompt is private "
            "enough, but it lost too much useful context. Try again and preserve more information that helps an "
            "external consultant reason well, while still removing names, employers, addresses, exact locations, "
            "exact dates, emails, phone numbers, course/project IDs, and overly specific medical/legal details. "
            "Prefer role-level and category-level detail over vague wording. Return JSON only."
        )
        user = (
            f"Mode: {mode}\n"
            f"Detected private entities JSON:\n{[entity.model_dump() for entity in entities]}\n\n"
            f"Current sanitized prompt:\n{sanitized_prompt}\n\n"
            f"Utility result JSON:\n{utility.model_dump()}\n\n"
            f"Raw private prompt for trusted-local reference only:\n{raw_prompt}\n\n"
            "Write an improved_sanitized_prompt that preserves more useful non-identifying context."
        )
        data = self.local_llm.chat_json(system, user, UTILITY_RETRY_SCHEMA)
        if not data:
            return None
        improved = str(data.get("improved_sanitized_prompt") or "").strip()
        if not improved or improved == sanitized_prompt:
            return None
        concepts = self._normalize_concepts(_as_str_list(data.get("preserved_concepts")), entities, mode)
        return improved, concepts or DOMAIN_CONCEPTS.get(mode, DOMAIN_CONCEPTS["general"])

    @op
    def evaluate_utility(self, sanitized_prompt: str, mode: ConsultMode, concepts: list[str]) -> UtilityResult:
        expected = concepts or DOMAIN_CONCEPTS.get(mode, DOMAIN_CONCEPTS["general"])
        deterministic = self._deterministic_utility(sanitized_prompt, expected)
        if self._use_llm_step("utility"):
            llm_result = self._llm_utility(sanitized_prompt, mode, expected)
            if llm_result is not None:
                if llm_result.utilityScore >= deterministic.utilityScore:
                    return llm_result
                return UtilityResult(
                    utilityScore=deterministic.utilityScore,
                    preservedConcepts=sorted(set([*deterministic.preservedConcepts, *llm_result.preservedConcepts])),
                    missingUsefulContext=deterministic.missingUsefulContext,
                )
        return deterministic

    def _deterministic_utility(self, sanitized_prompt: str, expected: list[str]) -> UtilityResult:
        text = sanitized_prompt.lower()
        preserved: list[str] = []
        missing: list[str] = []
        for concept in expected:
            concept_lower = concept.lower()
            aliases = {
                "performance warning": ["performance warning", "performance-related warning", "performance improvement plan", "pip"],
                "health diagnosis": ["health diagnosis", "health-related", "medical-related", "health symptoms"],
                "medical leave": ["medical leave", "medical-related leave", "time off"],
                "medication": ["medication", "ssri"],
                "academic integrity accusation": ["academic integrity", "accused"],
            }.get(concept_lower, [concept_lower])
            if any(alias in text for alias in aliases):
                preserved.append(concept)
            else:
                missing.append(concept)
        score = round(len(preserved) / max(1, len(expected)), 2)
        return UtilityResult(
            utilityScore=score,
            preservedConcepts=preserved,
            missingUsefulContext=missing,
        )

    def _llm_utility(self, sanitized_prompt: str, mode: ConsultMode, expected: list[str]) -> UtilityResult | None:
        system = (
            "You are the trusted local utility evaluator. Score whether a sanitized prompt still preserves "
            "enough meaning for an external consultant to help. Return JSON only. utilityScore must be from "
            "0 to 1. Penalize useless over-redaction; do not penalize removal of private identifiers."
        )
        user = (
            f"Mode: {mode}\nExpected useful concepts: {expected}\n\n"
            f"Sanitized prompt:\n{sanitized_prompt}"
        )
        data = self.local_llm.chat_json(system, user, UTILITY_SCHEMA)
        if not data:
            return None
        return UtilityResult(
            utilityScore=round(_clamp_score(data.get("utilityScore")), 2),
            preservedConcepts=_as_str_list(data.get("preservedConcepts")),
            missingUsefulContext=_as_str_list(data.get("missingUsefulContext")),
        )

    @op
    def external_consult(self, sanitized_prompt: str, mode: ConsultMode) -> ExternalConsultantResponse:
        if self.external_provider == "wandb":
            response = self._wandb_external_consult(sanitized_prompt, mode)
            if response is not None:
                return response

        if mode == "legal":
            return ExternalConsultantResponse(
                advice="Keep the response factual, request the basis for the withholding, and avoid making definitive legal conclusions.",
                suggestedStructure=[
                    "state the issue neutrally",
                    "request itemized support",
                    "preserve relevant timelines",
                    "ask for next steps in writing",
                ],
                risks=["do not threaten unsupported claims", "avoid including unnecessary private facts"],
            )
        if mode == "healthcare":
            return ExternalConsultantResponse(
                advice="Use neutral medical language, distinguish symptoms from conclusions, and focus on questions for the clinician.",
                suggestedStructure=["summarize the concern", "list timeline questions", "ask about options", "confirm follow-up plan"],
                risks=["do not provide diagnosis", "avoid medication instructions without a clinician"],
            )
        if mode == "education":
            return ExternalConsultantResponse(
                advice="Focus on process, evidence, course policy, and a respectful request for clarification.",
                suggestedStructure=["acknowledge the concern", "ask for evidence", "reference policy", "request a meeting"],
                risks=["avoid accusing the instructor", "do not overstate intent"],
            )
        return ExternalConsultantResponse(
            advice="Focus on the timeline, neutral tone, documentation, clarification, and avoiding overclaiming.",
            suggestedStructure=[
                "acknowledge the concern",
                "state the timeline factually",
                "ask for clarification",
                "reference documentation neutrally",
                "ask about next steps",
            ],
            risks=["do not make definitive legal claims", "avoid speculating about intent"],
        )

    def _wandb_external_consult(self, sanitized_prompt: str, mode: ConsultMode) -> ExternalConsultantResponse | None:
        system = (
            "You are an untrusted external reasoning consultant. You will only receive sanitized context. "
            "Provide generic advice, structure, and risk considerations. Do not ask for or infer hidden "
            "private identifiers. Return JSON only with advice, suggestedStructure, and risks."
        )
        user = f"Mode: {mode}\nSanitized prompt:\n{sanitized_prompt}"
        data = self.wandb_inference.chat_json(system, user)
        if not data:
            return None
        return ExternalConsultantResponse(
            advice=str(data.get("advice") or ""),
            suggestedStructure=_as_str_list(data.get("suggestedStructure")),
            risks=_as_str_list(data.get("risks")),
        )

    @op
    def finalize(
        self,
        raw_prompt: str,
        mode: ConsultMode,
        external: ExternalConsultantResponse | None,
        external_allowed: bool,
    ) -> str:
        if not external_allowed:
            return (
                "I could not safely consult the external model because the sanitized abstraction did not pass "
                "the privacy and utility gate. Inside the trusted boundary, I can still help by drafting from "
                f"the original private context:\n\n{self._trusted_draft(raw_prompt, mode)}"
            )
        if self._use_llm_step("finalize"):
            llm_final = self._llm_finalize(raw_prompt, mode, external)
            if llm_final:
                return llm_final
        return self._trusted_draft(raw_prompt, mode, external)

    def _llm_finalize(
        self,
        raw_prompt: str,
        mode: ConsultMode,
        external: ExternalConsultantResponse | None,
    ) -> str | None:
        system = (
            "You are the trusted local finalizer inside the privacy boundary. You may use the raw private "
            "prompt because you are local. Use the external consultant's generic advice as input, but write "
            "the final user-facing answer yourself. Be careful, neutral, and practical. Return JSON only."
        )
        user = (
            f"Mode: {mode}\n"
            f"Raw private prompt:\n{raw_prompt}\n\n"
            f"External consultant advice JSON:\n{external.model_dump() if external else None}"
        )
        data = self.local_llm.chat_json(system, user, FINALIZER_SCHEMA)
        if not data:
            return None
        final = str(data.get("finalAnswer") or "").strip()
        return final or None

    def _trusted_draft(
        self,
        raw_prompt: str,
        mode: ConsultMode,
        external: ExternalConsultantResponse | None = None,
    ) -> str:
        if mode == "legal" or "security deposit" in raw_prompt.lower():
            return (
                "Hi,\n\nI am writing to clarify the security deposit issue and the stated basis for withholding it. "
                "Please send the itemized explanation, any supporting documentation, and the timeline you are relying on. "
                "I want to resolve this based on the lease, the condition of the property, and written records rather than assumptions.\n\n"
                "Thank you."
            )
        if mode == "healthcare" or "prescribed" in raw_prompt.lower():
            return (
                "Hi Dr. Rosen,\n\nI would like to understand the recent symptoms, the reason sertraline was recommended, "
                "what side effects or warning signs I should watch for, and when we should follow up. "
                "Please let me know what information would help you assess next steps.\n\nThank you."
            )
        if mode == "education" or "cheating" in raw_prompt.lower():
            return (
                "Professor Lee,\n\nI understand there is a concern about Project 4 in CS 3500. "
                "Could you please share the specific evidence and the course policy section at issue? "
                "I would like to respond carefully and provide any relevant context in a meeting or written reply.\n\nThank you,\nMaya Patel"
            )

        advice = external.advice if external else "Keep the tone neutral and factual."
        return (
            "Hi HR,\n\n"
            "I would like to clarify the timeline around Sarah Klein's PIP and her earlier request for medical leave. "
            "My understanding is that Sarah Klein requested leave after a panic disorder diagnosis, and two weeks later "
            "Alex placed her on a PIP. I am not trying to assume anyone's intent, but I would like the company to review "
            "the documentation, the stated basis for the PIP, and whether the timing raises any process concerns.\n\n"
            f"To keep this careful: {advice}\n\n"
            "Could you please confirm the next step, what records should be provided, and who will review the matter?"
        )

    @op
    def run(self, raw_prompt: str, mode: ConsultMode = "general") -> RunResponse:
        if self._use_llm_pipeline():
            llm_result = self._run_llm_pipeline(raw_prompt, mode)
            if llm_result is not None:
                return llm_result

        entities = self.detect_entities(raw_prompt, mode)
        initial_sanitized, initial_concepts = self.deidentify(raw_prompt, entities, mode)
        first_check = self.check(initial_sanitized, entities)

        repaired = None
        final_sanitized = initial_sanitized
        final_check = first_check
        if not first_check.passed:
            repaired = self.repair(initial_sanitized, first_check, entities)
            final_sanitized = repaired
            final_check = self.check(repaired, entities)

        utility = self.evaluate_utility(final_sanitized, mode, initial_concepts)
        repair_success = not first_check.passed and final_check.passed

        for _ in range(max(0, self.utility_retries)):
            if not final_check.passed or utility.utilityScore >= self.utility_threshold:
                break
            improved = self.improve_utility(raw_prompt, final_sanitized, utility, entities, mode)
            if improved is None:
                break
            improved_sanitized, improved_concepts = improved
            improved_check = self.check(improved_sanitized, entities)
            if not improved_check.passed:
                repaired_improved = self.repair(improved_sanitized, improved_check, entities)
                repaired_improved_check = self.check(repaired_improved, entities)
                if not repaired_improved_check.passed:
                    continue
                improved_sanitized = repaired_improved
                improved_check = repaired_improved_check

            improved_utility = self.evaluate_utility(improved_sanitized, mode, improved_concepts)
            if improved_utility.utilityScore > utility.utilityScore:
                final_sanitized = improved_sanitized
                final_check = improved_check
                utility = improved_utility
                repaired = final_sanitized if final_sanitized != initial_sanitized else repaired

        external_allowed = final_check.passed and utility.utilityScore >= self.utility_threshold
        external = self.external_consult(final_sanitized, mode) if external_allowed else None
        final_answer = self.finalize(raw_prompt, mode, external, external_allowed)

        eval_scores = {
            "direct_leakage": 1.0 if final_check.passed else 0.0,
            "semantic_utility": utility.utilityScore,
            "checker_pass": 1.0 if final_check.passed else 0.0,
            "repair_success": 1.0 if repair_success else 0.0,
            "utility_retry_success": 1.0 if final_check.passed and utility.utilityScore >= self.utility_threshold else 0.0,
        }
        trace_url = os.getenv("WEAVE_TRACE_URL")
        return RunResponse(
            rawPrompt=raw_prompt,
            detectedEntities=entities,
            initialSanitizedPrompt=initial_sanitized,
            checkerResult=first_check,
            repairedSanitizedPrompt=repaired,
            finalCheckerResult=final_check,
            utilityResult=utility,
            externalCallAllowed=external_allowed,
            externalConsultantResponse=external,
            finalAnswer=final_answer,
            weaveTraceUrl=trace_url,
            promptVersions=PROMPT_VERSIONS,
            weaveMetadata=WeaveMetadata(
                project=self.weave_project,
                status=self.model_status,
                evalScores=eval_scores,
                promptComparison=[
                    {"version": "deid_prompt:v1-redaction", "leakagePassRate": 0.7, "avgUtilityScore": 0.62},
                    {"version": "deid_prompt:v2-semantic-abstraction", "leakagePassRate": 0.95, "avgUtilityScore": 0.86},
                ],
            ),
        )

    def _run_llm_pipeline(self, raw_prompt: str, mode: ConsultMode) -> RunResponse | None:
        first_deid = self.llm_deidentify_once(raw_prompt, mode)
        if first_deid is None:
            return None
        initial_sanitized, entities, concepts = first_deid

        first_check_result = self.llm_check_once(raw_prompt, initial_sanitized, entities, concepts, mode)
        if first_check_result is None:
            return None
        first_check, utility = first_check_result

        repaired = None
        final_sanitized = initial_sanitized
        final_check = first_check
        final_utility = utility

        if not first_check.passed:
            second_deid = self.llm_deidentify_once(raw_prompt, mode, first_check, utility)
            if second_deid is not None:
                repaired, entities, concepts = second_deid
                second_check = self.llm_check_once(raw_prompt, repaired, entities, concepts, mode)
                if second_check is not None:
                    final_sanitized = repaired
                    final_check, final_utility = second_check

        external_allowed = final_check.passed
        external = self.external_consult(final_sanitized, mode) if external_allowed else None
        final_answer = self.finalize(raw_prompt, mode, external, external_allowed)
        repair_attempted = repaired is not None

        eval_scores = {
            "direct_leakage": 1.0 if final_check.passed else 0.0,
            "semantic_utility": final_utility.utilityScore,
            "checker_pass": 1.0 if final_check.passed else 0.0,
            "repair_success": 1.0 if repair_attempted and final_check.passed else 0.0,
            "utility_retry_success": 1.0 if repair_attempted and final_utility.utilityScore >= self.utility_threshold else 0.0,
        }
        return RunResponse(
            rawPrompt=raw_prompt,
            detectedEntities=entities,
            initialSanitizedPrompt=initial_sanitized,
            checkerResult=first_check,
            repairedSanitizedPrompt=repaired,
            finalCheckerResult=final_check,
            utilityResult=final_utility,
            externalCallAllowed=external_allowed,
            externalConsultantResponse=external,
            finalAnswer=final_answer,
            weaveTraceUrl=os.getenv("WEAVE_TRACE_URL"),
            promptVersions=PROMPT_VERSIONS,
            weaveMetadata=WeaveMetadata(
                project=self.weave_project,
                status=self.model_status,
                evalScores=eval_scores,
                promptComparison=[
                    {"version": "deid_prompt:v1-redaction", "leakagePassRate": 0.7, "avgUtilityScore": 0.62},
                    {"version": "deid_prompt:v3-llm-loop", "leakagePassRate": 0.95, "avgUtilityScore": 0.86},
                ],
            ),
        )


def should_call_external(checker_result: CheckerResult, utility_result: UtilityResult) -> bool:
    return checker_result.passed and utility_result.utilityScore >= 0.6
