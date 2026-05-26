# Mid-Project Review: TaskOrbit Conversational Agent

## 1. Project Context & Structure (The AMOS Perspective)
TaskOrbit is a scalable, hallucination-resistant multi-task voice agent.

*   **Frontend (React/TypeScript):**
    *   **Operator Interface:** Used for configuring and managing agent personas and workflows.
    *   **Client Interface:** The conversational UI for end-users.
*   **Backend (Python/FastAPI):** Chosen for robust support of AI/LLM libraries and async performance.
*   **Orchestration Layer:** The core "brain" of the system. It manages the lifecycle of a call, handles audio streaming via **LiveKit**, and enforces strict **Guardrails** on LLM outputs.
*   **Schema Foundation:** A centralized JSON schema (`schemas/agent-task.schema.json`) ensures the Frontend, Backend, and Database all adhere to the exact same contract for what constitutes an "Agent" and a "Task".
*   **Infrastructure (Terraform/GCP):** Infrastructure as Code (IaC) ensures a reproducible, scalable production environment on Google Cloud Run.

---

## 2. Key Contributions & Ticket History (Shikhar Thakur)

### Ticket #5: First UI for Conversational Agent
*   **What I built:** Established the foundational frontend architecture.
*   **Details:** Implemented the app shell, routing, theming (Shadcn UI), and the core state-machine logic for the conversational "call" interface.

### Ticket #33: Basic Agent Runtime
*   **What I built:** Core orchestration logic.
*   **Details:** Developed the asynchronous pipeline that manages the flow of data between the user, the LLM, and the system's internal state machine, including timeout handling and mocked LLM integration for testing.

### Ticket #58: Agent Configuration API
*   **What I built:** Full-stack CRUD operations for agent management.
*   **Details:** Implemented the backend endpoints (POST, GET, PUT, DELETE) and wired them to the frontend UI, allowing operators to seamlessly create, update, and manage different agent personas.

### Ticket #69: Persona Guardrails (Recent)
*   **What I built:** Hallucination resistance and domain restriction.
*   **Details:**
    *   **Implementation:** Injected imperative `CORE CONSTRAINTS` (Scope, Forbidden Topics, Refusal Template) into the system prompt.
    *   **Impact:** Forces the LLM to stay "in character" and politely redirect off-topic requests (e.g., medical or legal advice) without breaking persona.
    *   **Full Stack:** Ensured these guardrails are configurable via the UI, persisted in the DB, and enforced across both text and voice (LiveKit) orchestration paths.

---

## 3. Likely Review Questions & Answers

**Q: How do you ensure the agent doesn't hallucinate or go off-topic?**
> A: We implemented **Persona Guardrails** (#69). By injecting imperative 'CORE CONSTRAINTS' into the system prompt, we explicitly define the agent's allowed scope and provide a mandatory refusal template for out-of-scope requests. This prevents the LLM from role-switching.

**Q: Why did the team choose LiveKit for audio?**
> A: LiveKit provides a low-latency, WebRTC-based SFU (Selective Forwarding Unit). This is critical for achieving the minimal lag required for a natural, full-duplex conversational voice experience.

**Q: How do you manage configuration across different environments and prevent broken deployments?**
> A: We recently instituted a strict **`main` -> `prod` branching strategy**.
> *   `main` serves as our staging and testing ground.
> *   Deployments to production only occur via a Merge Request to `prod` after team confirmation.
> *   Pushing to `prod` automatically triggers the CI/CD pipeline (build, push, deploy to Cloud Run).
> *   Additionally, any code changes involving environment variables must include corresponding Terraform updates in the same PR to prevent configuration drift.

**Q: What is the role of the Schema in your project?**
> A: The schema (`agent-task.schema.json`) is our absolute Source of Truth. It prevents decoupling between the frontend and backend. By strictly validating against this schema, we guarantee that any agent configuration saved via the UI is 100% executable by the backend runtime.

---

## 4. Notes on #69 Persona Guardrails (AC Mapping)

*   **AC1, AC2, AC3 are met:** Guardrails are successfully injected on every turn via `with_persona_guardrails()` and the constraint structure is robust.
*   **AC4 is met:** The recent PR review highlighted a structural mismatch where `persona_constraints` was nested incorrectly in the schema. This has been **fixed and merged**, ensuring frontend-serialized configs pass canonical schema validation.
*   **AC5 is met:** Wiki scenarios (happy path and edge cases) are fully documented.
