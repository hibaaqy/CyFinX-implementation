# CyFinX — FAA-based Fraud Investigation Assistant

CyFinX is a synthetic-data FYP implementation of the FAA investigation
workflow described in *FAA Framework: A Large Language Model-Based Approach
for Credit Card Fraud Investigations* (Shuster et al., 2025).

## FAA workflow implemented

For each alert, the Fraud Analyst Assistant (FAA) repeats one investigation
step at a time:

1. **Planning:** reviews the alert, transaction, and previous evidence; selects
   one new investigative lead.
2. **Information-Gathering:** generates Python code for the selected lead and
   executes it using the read-only evidence functions exposed by the code
   execution tool.
3. **Analysis:** interprets the new evidence together with previous findings
   and decides whether to continue or stop. The stop decision is made by the
   FAA during Analysis, not by a numeric evidence threshold.

If the FAA stops, the Report-Generating Agent (RGA) creates (1) an unfiltered
step-by-step report and (2) a concise report containing the most important
evidence for assessing transaction legitimacy. The Detective Agent then
assesses the concise RGA report and returns a fraudulent/legitimate decision.

The Vision Agent is activated through the registered `image_to_text`
function-calling tool only when a chart is generated. The code execution tool
enforces a maximum of one chart per investigation step. If the configured
runtime safety cap is reached while the FAA still says `continue`, the case is
paused; no final RGA report or Detective decision is fabricated.

The paper's four-aspect Likert evidence-quality evaluation is available as an
optional post-report evaluation (`--evaluate-evidence`). It is not used as a
numeric stopping rule in the FAA investigation loop.

## Model and runtime

The paper used GPT-4o for its FAA and Vision Agent. CyFinX uses
`google/gemma-4-E2B-it` through Hugging Face Transformers to satisfy the
project's Gemma/Colab requirement; this is a model-provider adaptation while
the investigation phases and agent hand-offs follow the FAA workflow.
Run model inference in a Google Colab GPU runtime (the tested target is a
Tesla T4) while editing source files in VS Code through the Google Colab
notebook connection. Gemma 4's multimodal model interface is used so the same
client can analyse a chart when the Vision Agent is invoked.

The notebook in `notebooks/cyfinx_gemma.ipynb` is the single interactive entry
point for Colab. It expects the project source to be uploaded to
`/content/CyFinX` and the operational database to be available at the path
configured below.

## Operational database

Place the synthetic operational SQLite database at:

`data/database/cyfinx_operational_v1.db`

The `data/` directory and database files are intentionally excluded from Git.
If the database is mounted from Google Drive in Colab, set the environment
variable `CYFINX_OPERATIONAL_DB` to its full path before importing
`app.database.connection`:

```python
import os
os.environ["CYFINX_OPERATIONAL_DB"] = (
    "/content/drive/MyDrive/CyFinX/database/cyfinx_operational_v1.db"
)
```

Set the variable before importing `app.main` or `app.database.connection`.
The investigation code accesses only tables registered in
`app/database/models.py`; the ground-truth/evaluation dataset is not exposed
through the operational evidence tool.

## Colab setup

From the project root in the Colab-connected VS Code notebook:

```python
%cd /content/CyFinX
!pip install -r requirements.txt
```

If PyTorch is already installed in the Colab runtime, do not force a different
PyTorch build. Check the active runtime first:

```python
import torch
print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "No GPU")
```

Run an investigation from a notebook cell:

```python
from app.main import run_investigation

result = run_investigation(
    alert_id="ALT0000089",
    max_steps=12,
)

print(result["status"])
if result["status"] == "completed":
    print(result["reports"]["final_report"])
    print(result["detective_decision"])
```

Or run the module in the Colab runtime terminal:

```bash
python -m app.main --alert-id ALT0000089 --max-steps 12
```

To additionally run the paper's report evidence-quality evaluation:

```bash
python -m app.main --alert-id ALT0000089 --max-steps 12 --evaluate-evidence
```

The model is loaded automatically if a `gemma_client` is not passed to
`run_investigation`. The first model load downloads the model to the Colab
runtime cache.

## Local database preparation

If rebuilding the operational database from the supplied CSV dataset:

```bash
python scripts/create_database.py
python scripts/import_operational_data.py
```

Run dataset validation separately when the source CSV directory is available:

```bash
python scripts/validate_dataset.py
```

`load_dataset.py` is retained as a separate staging/evaluation loader; it is
not used by the live FAA investigation path.

## Project layout

```text
app/
  agents/
    fraud_analyst_assistant.py
    report_generator.py
    vision_agent.py
    detective_agent.py
  database/
    connection.py
    models.py
  llm/
    gemma_client.py
  tools/
    code_execution_tool.py
  main.py
scripts/                 # database and dataset preparation only
dataset_generation/      # reproducible synthetic dataset generation
previous_versions/       # source modules used by the V3 generator
notebooks/               # Colab entry notebook
tests/                   # automated tests
```

## Tests

Run unit tests in an environment with the core dependencies installed:

```bash
pytest -q
```

## Important prototype limitation

The generated-code runner is a restricted project-level execution environment:
it blocks imports, raw SQL, file/network access, dynamic code execution, and
limits generated syntax and execution time in the Colab/Linux runtime. It is
not a hardened security sandbox and must not be used to execute untrusted code
or against production banking data. This is a CyFinX implementation adaptation
of the sandboxed Code Execution Tool described in the FAA paper.
