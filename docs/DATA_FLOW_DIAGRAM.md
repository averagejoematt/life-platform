# Data Flow Diagrams

> Mermaid diagrams for the full ingestion, compute, and serve pipelines.
> Render in GitHub, VS Code (Mermaid plugin), or at https://mermaid.live
> Last updated: 2026-03-15 (v3.7.30)

---

## 1. Full System Overview

```mermaid
flowchart TD
    subgraph Sources["Data Sources (20)"]
        WH[Whoop]
        ST[Strava]
        GA[Garmin]
        WI[Withings]
        ES[Eight Sleep]
        MF[MacroFactor CSV]
        AH[Apple Health / HAE]
        HA[Habitify]
        NO[Notion Journal]
        TO[Todoist]
        WE[Weather]
        GC[Google Calendar]
        MN[Manual: Labs / DEXA / Genome]
    end

    subgraph Ingest["Ingest Layer"]
        IL[Scheduled Lambdas x13]
        WH_WEB[Health Auto Export Webhook]
        S3_TRIG[S3 Trigger Lambdas]
    end

    subgraph Store["Store Layer"]
        DDB[(DynamoDB\nlife-platform)]
        S3_RAW[S3: raw/]
    end

    subgraph Compute["Compute Layer"]
        DM[daily-metrics-compute]
        DI[daily-insight-compute]
        AM[adaptive-mode-compute]
        CS[character-sheet-compute]
        HE[hypothesis-engine]
        WC[weekly-correlation-compute]
    end

    subgraph Serve["Serve Layer"]
        MCP[MCP Lambda\n88 tools]
        DB[daily-brief]
        WD[weekly-digest]
        MD[monthly-digest]
        OT[other emails x5]
    end

    subgraph Consumers["Consumers"]
        CL[Claude Desktop\nClaude.ai\nClaude Mobile]
        EM[Email Inbox]
        DASH[Dashboard\ndash.averagejoematt.com]
    end

    WH & ST & GA & WI & ES & HA & NO & TO & WE & GC --> IL
    MF --> S3_TRIG
    AH --> WH_WEB
    MN -.->|manual seed| DDB

    IL --> DDB
    IL --> S3_RAW
    WH_WEB --> DDB
    WH_WEB --> S3_RAW
    S3_TRIG --> DDB

    DDB --> DM & DI & AM & CS
    DM & DI & AM & CS --> DDB
    DDB --> HE & WC
    HE & WC --> DDB

    DDB --> MCP
    DDB --> DB & WD & MD & OT
    MCP --> CL
    DB --> EM
    DB --> DASH
    WD & MD & OT --> EM
```

---

## 2. Daily Brief Pipeline (Critical Path)

Times are PDT. Each step must complete before the next begins.

```mermaid
flowchart LR
    subgraph Morning["Morning Ingestion 07:00–09:00 AM"]
        direction TB
        I1[whoop-ingestion\n07:00]
        I2[garmin-ingestion\n07:00]
        I3[notion-ingestion\n07:00]
        I4[withings-ingestion\n07:15]
        I5[habitify-ingestion\n07:15]
        I6[strava-ingestion\n07:30]
        I7[journal-enrichment\n07:30]
        I8[todoist-ingestion\n07:45]
        I9[eightsleep-ingestion\n08:00]
        I10[activity-enrichment\n08:30]
        I11[macrofactor-ingestion\n09:00]
    end

    subgraph Compute["Pre-Brief Compute 10:20–10:45 AM"]
        direction TB
        C1[daily-insight-compute\n10:20 AM]
        C2[daily-metrics-compute\n10:25 AM]
        C3[adaptive-mode-compute\n10:30 AM]
        C4[character-sheet-compute\n10:35 AM]
        C5[freshness-checker\n10:45 AM]
    end

    subgraph Brief["Daily Brief 11:00 AM"]
        DB[daily-brief\n18 sections\n4 Haiku calls]
    end

    subgraph Output["Outputs"]
        EM[Email]
        DASH[Dashboard\ndata.json]
        BUDDY[Buddy page\ndata.json]
    end

    Morning --> Compute
    C1 & C2 & C3 & C4 --> DB
    DB --> EM & DASH & BUDDY

    style Brief fill:#E6F1FB,stroke:#378ADD
    style Output fill:#EAF3DE,stroke:#639922
```

---

## 3. DynamoDB Key Schema

```mermaid
erDiagram
    ITEM {
        string pk "USER#matthew#SOURCE#whoop"
        string sk "DATE#2026-03-15"
        string date "2026-03-15"
        number recovery_score "84"
        number hrv "42.1"
        number resting_heart_rate "48"
        string schema_version "1.0"
    }

    CACHE_ITEM {
        string pk "CACHE#matthew"
        string sk "TOOL#get_health_dashboard"
        string payload "JSON string"
        number ttl "epoch + 26h"
        string computed_at "ISO timestamp"
    }

    PROFILE {
        string pk "USER#matthew"
        string sk "PROFILE#v1"
        object targets "weight, macros, etc."
        object source_of_truth "domain -> source"
    }

    ITEM ||--o{ CACHE_ITEM : "pre-computed from"
    PROFILE ||--o{ ITEM : "configures queries for"
```

---

## 4. MCP Request Flow

```mermaid
sequenceDiagram
    participant C as Claude
    participant B as mcp_bridge.py<br/>(local)
    participant L as life-platform-mcp<br/>(Lambda)
    participant DDB as DynamoDB
    participant SM as Secrets Manager

    C->>B: MCP tool call (stdio)
    B->>L: HTTPS POST (Bearer token)
    L->>SM: GetSecretValue (mcp-api-key)
    SM-->>L: API key
    L->>L: Validate Bearer token (HMAC)
    L->>L: Validate tool args (SEC-3)

    alt Cache hit
        L->>DDB: GetItem (CACHE#matthew)
        DDB-->>L: Cached result (TTL valid)
        L-->>B: JSON result
    else Cache miss
        L->>DDB: Query (SOURCE#<source>)
        DDB-->>L: Items
        L->>L: Compute result
        L-->>B: JSON result
    end

    B-->>C: MCP tool result
```

---

## 5. OAuth Token Refresh Flow

All OAuth sources (Whoop, Strava, Withings, Garmin) use this self-healing pattern:

```mermaid
flowchart TD
    EB[EventBridge trigger] --> LAMBDA[Ingestion Lambda]
    LAMBDA --> SM[Read secret from\nSecrets Manager]
    SM --> API{Call upstream API}
    API -->|Success| WRITE[Write data to DynamoDB + S3]
    API -->|401 Unauthorized| REFRESH[Refresh OAuth token]
    REFRESH --> SM2[Write new tokens\nback to Secrets Manager]
    SM2 --> API2[Retry API call]
    API2 -->|Success| WRITE
    API2 -->|Fail| DLQ[Send to DLQ]
    DLQ --> ALERT[SNS alert →\nawsdev@mattsusername.com]

    style WRITE fill:#EAF3DE,stroke:#639922
    style ALERT fill:#FCEBEB,stroke:#E24B4A
```

**Withings note:** Withings rotates its refresh token on every use. If the Lambda is down for >24h, the token expires and auto-refresh breaks. Re-authenticate with `python3 setup/fix_withings_oauth.py`.

---

## 6. Weekly Email Cadence

```mermaid
gantt
    title Weekly Intelligence Cadence (PDT)
    dateFormat  HH:mm
    axisFormat  %a %H:%M

    section Monday
    monday-compass           :08:00, 30m

    section Daily (all days)
    anomaly-detector         :09:05, 15m
    daily-brief              :11:00, 20m

    section Wednesday
    wednesday-chronicle      :08:00, 30m

    section Friday
    weekly-plate             :19:00, 20m

    section Saturday
    nutrition-review         :10:00, 45m

    section Sunday
    weekly-digest            :09:00, 30m
    hypothesis-engine        :12:00, 45m
```

---

## 7. Alarm Coverage

```mermaid
flowchart LR
    subgraph Lambdas["Lambda Errors (~42 functions)"]
        EACH[Each Lambda has\n≥1 error alarm\n→ SNS]
    end

    subgraph Special["Special Alarms"]
        WI_OAUTH[withings-oauth-consecutive-errors\n2 consecutive days]
        DB_NI[daily-brief-no-invocations\n24h window]
        DB_DUR[daily-brief-duration-high\n>240s]
        MCP_DUR[mcp-server-duration-high\n>240s]
        MCP_AUTH[MCP AuthFailures\n≥5 in 5min]
        COMPUTE[compute-pipeline-stale\ndaily-metrics not fresh]
        CANARY[canary errors\nevery 30min]
        FRESH[freshness-checker errors]
    end

    subgraph Action["Alert Action"]
        SNS[SNS: life-platform-alerts]
        EMAIL[awsdev@mattsusername.com]
    end

    EACH --> SNS
    Special --> SNS
    SNS --> EMAIL
```

Total alarms: ~49. All route to `life-platform-alerts` SNS → email.
