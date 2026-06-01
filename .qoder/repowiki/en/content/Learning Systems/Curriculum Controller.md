# Curriculum Controller

<cite>
**Referenced Files in This Document**
- [learning/curriculum.py](file://learning/curriculum.py)
- [api/endpoints/curriculum.py](file://api/endpoints/curriculum.py)
- [api/dependencies.py](file://api/dependencies.py)
- [config.py](file://config.py)
- [tests/test_curriculum.py](file://tests/test_curriculum.py)
- [learning/jepa.py](file://learning/jepa.py)
- [learning/concept_learning.py](file://learning/concept_learning.py)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)

## Introduction
The Curriculum Controller is the central orchestrator of the autonomic learning system, enforcing a three-stage curriculum architecture that governs educational progression and operational capabilities. The system operates on two complementary criteria: density (minimum concept counts) and stability (JEPA prediction error tolerance). This document explains the LITERACY → NUMERACY → REASONING progression, prerequisite gating, configuration parameters, persistence mechanisms, and integration patterns with the broader learning system.

## Project Structure
The Curriculum Controller spans several modules:
- Core controller logic resides in the learning module
- API endpoints expose status, progression evaluation, and gated operations
- Dependencies manage global state, JEPA error tracking, and curriculum phases
- Configuration defines tunable parameters for progression stability
- Tests validate progression rules, prerequisites, and API integration

```mermaid
graph TB
subgraph "Learning Layer"
CTRL["CurriculumController<br/>learning/curriculum.py"]
CONCEPT["ConceptLearner<br/>learning/concept_learning.py"]
JEPAM["JEPAModel<br/>learning/jepa.py"]
end
subgraph "API Layer"
DEPS["Dependencies<br/>api/dependencies.py"]
API["Curriculum Endpoints<br/>api/endpoints/curriculum.py"]
end
subgraph "Config"
CFG["Configuration<br/>config.py"]
end
TESTS["Unit Tests<br/>tests/test_curriculum.py"]
API --> DEPS
DEPS --> CTRL
DEPS --> CONCEPT
DEPS --> JEPAM
CTRL --> CONCEPT
CTRL --> JEPAM
TESTS --> CTRL
TESTS --> API
CFG --> DEPS
```

**Diagram sources**
- [learning/curriculum.py:1-296](file://learning/curriculum.py#L1-L296)
- [api/endpoints/curriculum.py:1-211](file://api/endpoints/curriculum.py#L1-L211)
- [api/dependencies.py:100-120](file://api/dependencies.py#L100-L120)
- [config.py:48-51](file://config.py#L48-L51)
- [tests/test_curriculum.py:1-450](file://tests/test_curriculum.py#L1-L450)

**Section sources**
- [learning/curriculum.py:1-296](file://learning/curriculum.py#L1-L296)
- [api/endpoints/curriculum.py:1-211](file://api/endpoints/curriculum.py#L1-L211)
- [api/dependencies.py:100-120](file://api/dependencies.py#L100-L120)
- [config.py:48-51](file://config.py#L48-L51)
- [tests/test_curriculum.py:1-450](file://tests/test_curriculum.py#L1-L450)

## Core Components
- CurriculumController: Monotonic stage manager with density and stability checks, prerequisite gating, observability, and persistence
- API endpoints: Expose status, reset, math operations with prerequisite checks, and curriculum progression evaluation
- Dependencies: Global state wiring, JEPA error deque, and curriculum phase orchestration
- Configuration: Tunable parameters for error tolerance and stability window
- Tests: Comprehensive coverage of progression rules, prerequisites, and API behavior

**Section sources**
- [learning/curriculum.py:92-296](file://learning/curriculum.py#L92-L296)
- [api/endpoints/curriculum.py:8-211](file://api/endpoints/curriculum.py#L8-L211)
- [api/dependencies.py:100-120](file://api/dependencies.py#L100-L120)
- [config.py:48-51](file://config.py#L48-L51)
- [tests/test_curriculum.py:1-450](file://tests/test_curriculum.py#L1-L450)

## Architecture Overview
The Curriculum Controller enforces a strict, monotonic progression across three stages:
- Stage 0 (LITERACY): minimum concepts 5, arithmetic disallowed
- Stage 1 (NUMERACY): minimum concepts 15, arithmetic allowed
- Stage 2 (REASONING): minimum concepts 30, arithmetic and abstraction allowed

Progression requires both:
- Density: learned concept count meets or exceeds the next stage threshold
- Stability: average recent JEPA prediction error remains below the configured tolerance

```mermaid
flowchart TD
Start(["Start Evaluation"]) --> CheckMax["Already at Max Stage?"]
CheckMax --> |Yes| ReturnMax["Return: Already at maximum stage"]
CheckMax --> |No| NextDef["Load Next Stage Definition"]
NextDef --> Density["Compute Density: concept_count >= min_concepts"]
Density --> |No| NotMet["Return: Density not met"]
Density --> |Yes| Stability["Compute Average JEPA Error<br/>Compare to Error Tolerance"]
Stability --> |Stable| Advance["Advance Stage<br/>Set last_stage_up_time"]
Stability --> |Unstable| Block["Block: High Latent Uncertainty"]
Advance --> Report["Return: Advanced"]
Block --> ReportBlocked["Return: Blocked"]
NotMet --> ReportNo["Return: No Advance"]
```

**Diagram sources**
- [learning/curriculum.py:128-202](file://learning/curriculum.py#L128-L202)

**Section sources**
- [learning/curriculum.py:128-202](file://learning/curriculum.py#L128-L202)

## Detailed Component Analysis

### CurriculumController Class
The controller encapsulates:
- Stage definitions and monotonic progression
- Density and stability evaluation
- Prerequisite gating for tasks
- Status reporting and observability
- Persistence to JSON for curriculum state

Key behaviors:
- evaluate_progression: Applies density and stability conditions, returns structured results
- check_prerequisite: Enforces stage-based access control for tasks
- get_status_report: Provides human-readable progress and blocking status
- save/load: Persists and restores controller state

```mermaid
classDiagram
class CurriculumController {
+int current_stage
+float error_tolerance
+int stability_window
+float last_stage_up_time
+string stage_label
+evaluate_progression(concept_count, recent_errors) dict
+check_prerequisite(task) void
+get_status_report(concept_count) dict
+get_abstraction_gate() bool
+reset() void
+save(path) void
+load(path) void
}
class PrerequisiteNotMetError {
+int required_stage
+int current_stage
+string operation
}
CurriculumController --> PrerequisiteNotMetError : "raises"
```

**Diagram sources**
- [learning/curriculum.py:92-296](file://learning/curriculum.py#L92-L296)

**Section sources**
- [learning/curriculum.py:92-296](file://learning/curriculum.py#L92-L296)

### API Integration and Prerequisite Gating
The API layer wires the controller into REST endpoints:
- GET /curriculum/status: Reports current stage and progress
- POST /curriculum/reset: Resets to stage 0
- POST /learn/process: Evaluates progression and returns results
- POST /math/calculate: Gates arithmetic operations by stage
- POST /learn/curriculum/phase/{phase}: Enforces prerequisite phases for curriculum phases

```mermaid
sequenceDiagram
participant Client as "Client"
participant API as "Curriculum Endpoints"
participant Deps as "Dependencies"
participant Ctrl as "CurriculumController"
participant Concept as "ConceptLearner"
participant JEPA as "JEPAModel"
Client->>API : POST /learn/process
API->>Deps : _concept_learner.learn()
Deps->>Concept : learn()
Concept-->>Deps : concepts[]
API->>Ctrl : evaluate_progression(len(concepts), _jepa_recent_errors)
Ctrl->>JEPA : recent_errors (deque)
Ctrl-->>API : {advanced, blocked, reason, avg_jepa_error}
API-->>Client : Response with curriculum status
```

**Diagram sources**
- [api/endpoints/curriculum.py:57-74](file://api/endpoints/curriculum.py#L57-L74)
- [api/dependencies.py:95-110](file://api/dependencies.py#L95-L110)
- [learning/curriculum.py:128-202](file://learning/curriculum.py#L128-L202)

**Section sources**
- [api/endpoints/curriculum.py:8-211](file://api/endpoints/curriculum.py#L8-L211)
- [api/dependencies.py:95-110](file://api/dependencies.py#L95-L110)
- [learning/curriculum.py:128-202](file://learning/curriculum.py#L128-L202)

### Stage Definitions and Allowed Operations
- LITERACY (Stage 0): Allows basic curriculum phases; arithmetic operations are blocked
- NUMERACY (Stage 1): Enables arithmetic operations; abstraction remains blocked
- REASONING (Stage 2): Enables arithmetic and abstraction operations

Prerequisite mapping:
- arithmetic requires stage ≥ 1
- abstraction requires stage ≥ 2

```mermaid
flowchart TD
S0["Stage 0: LITERACY<br/>min_concepts=5<br/>allows_arithmetic=False"] --> S1["Stage 1: NUMERACY<br/>min_concepts=15<br/>allows_arithmetic=True"]
S1 --> S2["Stage 2: REASONING<br/>min_concepts=30<br/>allows_arithmetic=True<br/>allows_abstraction=True"]
```

**Diagram sources**
- [learning/curriculum.py:32-54](file://learning/curriculum.py#L32-L54)
- [learning/curriculum.py:57-60](file://learning/curriculum.py#L57-L60)

**Section sources**
- [learning/curriculum.py:32-60](file://learning/curriculum.py#L32-L60)

### Progression Criteria and Stability Window
- Density requirement: concept_count ≥ next-stage min_concepts
- Stability requirement: average recent JEPA MSE loss ≤ error_tolerance
- Stability window: controls how many recent updates contribute to the average

```mermaid
flowchart TD
A["Concept Count"] --> B{">= Next Threshold?"}
B --> |No| C["Density Not Met"]
B --> |Yes| D["Average JEPA Error"]
D --> E{"<= Error Tolerance?"}
E --> |Yes| F["Advance Stage"]
E --> |No| G["Block: High Latent Uncertainty"]
```

**Diagram sources**
- [learning/curriculum.py:157-202](file://learning/curriculum.py#L157-L202)
- [config.py:48-51](file://config.py#L48-L51)

**Section sources**
- [learning/curriculum.py:157-202](file://learning/curriculum.py#L157-L202)
- [config.py:48-51](file://config.py#L48-L51)

### Practical Examples

#### Example 1: Advancing from LITERACY to NUMERACY
- Scenario: Learned 15 concepts; recent JEPA errors average to 0.3
- Outcome: Stage advances to NUMERACY; blocking reason cleared

#### Example 2: Blocking Due to High Latent Uncertainty
- Scenario: Learned 15 concepts; recent JEPA errors average to 0.7 (> error tolerance)
- Outcome: Stage remains at LITERACY; blocking reason indicates instability

#### Example 3: Arithmetic Blocked at Stage 0
- Scenario: Attempt to POST /math/calculate at stage 0
- Outcome: HTTP 403 Forbidden with prerequisite violation message

**Section sources**
- [tests/test_curriculum.py:67-124](file://tests/test_curriculum.py#L67-L124)
- [api/endpoints/curriculum.py:29-54](file://api/endpoints/curriculum.py#L29-L54)

### Monitoring and Observability
The controller exposes:
- Status report with current stage, progress percentage, blocking status, and last stage up time
- Blocking reason when stability prevents advancement
- Abstraction gate indicator for downstream systems

**Section sources**
- [learning/curriculum.py:228-252](file://learning/curriculum.py#L228-L252)

### Persistence Mechanisms
- save(path): Writes current stage, last stage up time, error tolerance, and stability window to JSON
- load(path): Restores state from JSON; logs restored stage and label

**Section sources**
- [learning/curriculum.py:265-296](file://learning/curriculum.py#L265-L296)

## Dependency Analysis
The Curriculum Controller interacts with:
- ConceptLearner: Supplies concept count for density evaluation
- JEPAModel: Provides recent MSE losses for stability evaluation
- Dependencies: Maintains global state, JEPA error deque, and curriculum phase orchestration
- Configuration: Supplies error tolerance and stability window defaults

```mermaid
graph TB
CTRL["CurriculumController"]
CONCEPT["ConceptLearner"]
JEPAM["JEPAModel"]
DEPS["Dependencies"]
CFG["Configuration"]
DEPS --> CTRL
DEPS --> CONCEPT
DEPS --> JEPAM
CTRL --> CONCEPT
CTRL --> JEPAM
CFG --> DEPS
```

**Diagram sources**
- [api/dependencies.py:95-110](file://api/dependencies.py#L95-L110)
- [config.py:48-51](file://config.py#L48-L51)
- [learning/curriculum.py:102-108](file://learning/curriculum.py#L102-L108)

**Section sources**
- [api/dependencies.py:95-110](file://api/dependencies.py#L95-L110)
- [config.py:48-51](file://config.py#L48-L51)
- [learning/curriculum.py:102-108](file://learning/curriculum.py#L102-L108)

## Performance Considerations
- Stability window sizing affects progression responsiveness; larger windows smooth out noise but delay advancement
- Error tolerance determines how aggressively the system blocks progression under uncertainty
- JEPA error computation is lightweight; ensure recent_errors deque is efficiently maintained

[No sources needed since this section provides general guidance]

## Troubleshooting Guide

Common issues and resolutions:
- Progression stuck at NUMERACY despite sufficient concepts
  - Cause: High latent uncertainty (average JEPA error exceeds tolerance)
  - Resolution: Allow more stabilization; reduce error tolerance if justified by system behavior
- Arithmetic operations blocked at stage 0
  - Cause: Prerequisite gating requires stage ≥ 1
  - Resolution: Complete prerequisite curriculum phases to reach NUMERACY
- Abstraction operations blocked at stage 1
  - Cause: Prerequisite gating requires stage ≥ 2
  - Resolution: Continue to REASONING stage
- API returns internal server error
  - Cause: Unhandled exceptions in endpoints
  - Resolution: Check logs and ensure dependencies are initialized

Operational tips:
- Use GET /curriculum/status to monitor blocking reasons and progress
- Use POST /curriculum/reset to return to LITERACY for controlled restarts
- Verify JEPA recent errors deque length matches stability window configuration

**Section sources**
- [api/endpoints/curriculum.py:8-211](file://api/endpoints/curriculum.py#L8-L211)
- [tests/test_curriculum.py:355-446](file://tests/test_curriculum.py#L355-L446)

## Conclusion
The Curriculum Controller provides a robust, autonomic framework for educational progression. By combining density and stability criteria, it ensures meaningful and reliable advancement across LITERACY, NUMERACY, and REASONING. The prerequisite gating system aligns operational capabilities with cognitive readiness, while persistence and observability enable reliable deployment and monitoring.