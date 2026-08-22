# Threat Model

## Data Flow Diagram

```mermaid
%%{init: {'theme': 'base', 'themeVariables': { 'background': '#ffffff', 'primaryColor': '#ffffff', 'lineColor': '#666666' }}}%%
flowchart LR
    classDef process fill:#6baed6,stroke:#2171b5,stroke-width:2px,color:#000000
    classDef external fill:#fdae61,stroke:#d94701,stroke-width:2px,color:#000000
    classDef datastore fill:#74c476,stroke:#238b45,stroke-width:2px,color:#000000

    Browser["Browser"]:::external
    Operator["Operator"]:::external
    ApprovedSources["Approved public sources"]:::external
    Discord["Discord webhook"]:::external
    DeepSeek["DeepSeek synthetic spike"]:::external

    subgraph Application["Application / loopback Compose"]
        NextJS(("NextJS dashboard/BFF")):::process
        FastAPI(("FastAPI")):::process
        PostgreSQL[("PostgreSQL")]:::datastore
        FastEmbed(("FastEmbed local model")):::process
    end
    subgraph CrawlerSandbox["Optional crawler sandbox"]
        CLI(("CLI crawler/worker")):::process
    end

    Browser <-->|"DF01: loopback HTTP UI/BFF"| NextJS
    NextJS <-->|"DF02: loopback HTTP REST JSON"| FastAPI
    FastAPI <-->|"DF03: SQL/pgvector persistence"| PostgreSQL
    FastAPI <-->|"DF04: local embedding inference"| FastEmbed
    Operator <-->|"DF05: local CLI control"| CLI
    CLI <-->|"DF06: HTTPS approved source fetch"| ApprovedSources
    CLI <-->|"DF07: SQL run/job persistence"| PostgreSQL
    CLI <-->|"DF08: HTTPS synthetic-only provider spike"| DeepSeek
    FastAPI <-->|"DF09: HTTPS Discord delivery"| Discord

    style Application fill:none,stroke:#e31a1c,stroke-width:3px,stroke-dasharray: 5 5
    style CrawlerSandbox fill:none,stroke:#e31a1c,stroke-width:3px,stroke-dasharray: 5 5

    linkStyle default stroke:#666666,stroke-width:2px
```

## Element Table

| Element | Type | TMT Category | Description | Trust Boundary |
|---------|------|--------------|-------------|----------------|
| Browser | External Interactor | SE.EI.TMCore.Browser | Local browser user agent rendering Next.js | External |
| Operator | External Interactor | SE.EI.TMCore.User | Single operator controlling local runs/secrets | External |
| ApprovedSources | External Interactor | SE.EI.TMCore.WebSvc | Allow-listed public job sources | External |
| Discord | External Interactor | SE.EI.TMCore.WebSvc | Discord webhook endpoint | External |
| DeepSeek | External Interactor | SE.EI.TMCore.WebSvc | Synthetic-only V3 provider | External |
| NextJS | Process | SE.P.TMCore.WebApp | App Router dashboard and BFF | Application |
| FastAPI | Process | SE.P.TMCore.WebSvc | REST API, gates and domain operations | Application |
| PostgreSQL | Data Store | SE.DS.TMCore.SQL | Canonical and derived persistence | Application |
| FastEmbed | Process | SE.P.TMCore.OSProcess | Local fixed-revision embedding inference | Application |
| CLI | Process | SE.P.TMCore.OSProcess | Ingestion/worker entrypoint | CrawlerSandbox |

## Data Flow Table

| ID | Source | Target | Protocol | Description |
|----|--------|--------|----------|-------------|
| DF01 | Browser | NextJS | HTTP loopback | UI and same-origin BFF requests. |
| DF02 | NextJS | FastAPI | HTTP JSON loopback | REST calls with owner header when protected. |
| DF03 | FastAPI | PostgreSQL | SQL/TCP | Parameterized reads and writes, including pgvector. |
| DF04 | FastAPI | FastEmbed | Local call | Structured profile/query embedding without external provider. |
| DF05 | Operator | CLI | Local process | Operator invokes bounded crawler/worker commands. |
| DF06 | CLI | ApprovedSources | HTTPS | Allow-listed source fetch with SSRF/redirect policy. |
| DF07 | CLI | PostgreSQL | SQL/TCP | CrawlRun, snapshot and Job persistence. |
| DF08 | CLI | DeepSeek | HTTPS | Opt-in synthetic evaluation only. |
| DF09 | FastAPI | Discord | HTTPS | Bounded alert message with DB idempotency key header. |

## Trust Boundary Table

| Boundary | Description | Contains |
|----------|-------------|----------|
| Application | Loopback-hosted Next.js/API/database/model Compose services | NextJS, FastAPI, PostgreSQL, FastEmbed |
| CrawlerSandbox | Optional non-root browser/crawler container with sandbox profile | CLI |
| External | Browser/operator actors and third-party HTTP endpoints | Browser, Operator, ApprovedSources, Discord, DeepSeek |
