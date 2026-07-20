# F1 Race Engineer Agent — Amazon Bedrock AgentCore

**Created:** June 2026
**Phase:** Layered on after the F1 Telemetry Dashboard core is live
**Approach:** AgentCore Runtime + Gateway + Code Interpreter
**Purpose:** A natural-language "race engineer" layered on top of the live F1 dashboard — ask it questions about driver/lap performance and it queries the telemetry, runs the math, and returns analysis + plots.

**Status:** Agent layer of the F1 Telemetry Dashboard project.

---

## 1. What You're Building

Instead of forcing a user to dig through telemetry graphs to compare a driver's lap performance, this agent lets them ask natural-language questions — e.g., *"Where is Driver A losing time to Driver B in Sector 2?"* or *"Compare Hamilton's lap 12 and 13 into Turn 4."* The agent parses the question, pulls the raw telemetry from the dashboard's database, runs the calculations in an isolated sandbox, and returns a formatted analysis with a chart.

**Why this project matters:**
- Proves production AI agent deployment with real tool integrations (not a chatbot wrapper)
- Built on real infrastructure — it queries the actual F1 dashboard you built and deployed
- AgentCore is AWS's newest agent platform — early experience is a differentiator
- Dogfoods your own work — the agent reasons over the telemetry pipeline you engineered

**What it is NOT:**
- Not a chatbot wrapper — it has real tool integrations that query live data and execute code
- Not an LLM demo — it returns computed analysis (delta times, trace lines), not paraphrased text

---

## 2. Core AgentCore Components

| Component | Role in the Race Engineer |
|-----------|---------------------------|
| **AgentCore Runtime** | Hosts the agent, orchestrates the parse → query → compute → respond flow |
| **AgentCore Gateway** | Bridges the LLM securely to the F1 dashboard's DynamoDB via a tool (Lambda) |
| **Code Interpreter** | Spins up a secure microVM to run Python (fastf1, numpy, pandas, matplotlib) on raw telemetry arrays |

---

## 3. Architecture

```
[ User Chat UI ] ──> [ AgentCore Runtime ]
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
[ AgentCore Gateway ]            [ Code Interpreter ]
        │                                 │
(Queries F1 DynamoDB)            (Calculates lap deltas,
        │                          trace lines, plots)
        │                                 │
        └────────────────┬────────────────┘
                         ▼
             [ Formatted Analysis + Chart ]
```

**Datastore:** Queries the F1 dashboard's **existing DynamoDB** tables (Sessions, Positions, Laps, RaceControl). No new datastore — the telemetry is already ingested by the live pipeline. (Timestream was considered for time-series fidelity but rejected to avoid a parallel ingest path and scope creep.)

---

## 4. Workflow of a Telemetry Query

1. **Natural-language parsing (Runtime):** User submits *"Compare Hamilton's lap 12 and lap 13 into Turn 4."* The Runtime extracts entity parameters — Driver: HAM, Laps: [12, 13], Location: Turn 4.
2. **Data extraction (Gateway):** The agent calls a tool exposed via the Gateway. The tool invokes an AWS Lambda that pulls arrays of time-series records (Distance, Speed, Throttle, Brake) for those specific laps from DynamoDB.
3. **Isolated math & plotting (Code Interpreter):** Raw arrays pass to the Code Interpreter. Inside a secure microVM sandbox, a Python script (fastf1, pandas, numpy, matplotlib) aligns the two laps by distance and calculates the braking-point delta and throttle-application timing. It renders a comparison line graph.
4. **Insight generation (UI):** The script saves the chart to a transient path. AgentCore packages the text analysis alongside the chart asset and streams both back to the dashboard UI.

---

## 5. Build Phases

### Phase 1: Gateway + DynamoDB tool
- Stand up AgentCore Runtime + Gateway
- Build the Lambda tool: query Positions/Laps tables, return telemetry arrays for a given driver/lap/sector
- Wire the Gateway tool to the Runtime; verify end-to-end query flow

### Phase 2: Code Interpreter + analysis
- Author the Code Interpreter Python script (fastf1/numpy for delta math, matplotlib for plots)
- Test the parse → query → compute path on real dashboard data
- Lap-delta and braking-point calculations validated

### Phase 3: UI + polish
- Chat UI placeholder: dashboard right column (`AgentChatPanel`, 320px) with stub replies — swap in for the former Race Control feed
- Wire the panel to AgentCore streaming responses + chart assets (replacing stubs)
- Hardening: error handling, parameter extraction edge cases, transient asset cleanup
- Record demo; write the Projects-section write-up
