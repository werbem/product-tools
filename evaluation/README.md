# Competitive Intelligence MCP Evaluation Framework

This directory defines the evaluation assets for the Competitive Intelligence
MCP without embedding scoring logic into the production service.

## Structure

```text
evaluation/
├── cases/                 # benchmark tasks
├── metrics/               # metric definitions
├── templates/             # report template
└── README.md
```

## Case Format

Each case contains:

- `input`
  - `our_company`
  - `competitor_company`
  - `product`
  - `objective`
- `expected`
  - `required_dimensions`
  - `expected_insights`
  - `expected_outputs`

Optional fields include `tool`, `output_level`, `intelligence`, and
`expected_status`.

## Current Scope

This phase only defines datasets, metrics, and the report template. Automatic
scoring and LLM-as-a-judge are intentionally deferred.
