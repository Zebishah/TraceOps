# Workspace evaluation reports

The dashboard selects an organization from the signed-in account's `/api/v1/auth/me` memberships. Requests carry that ID in the organization API path, and the backend checks membership and the owner/admin role. `EVALUATION_ORGANIZATION_ID` is no longer required for reading or generating reports.

## Generate a report

From `ops-pilot/backend`, with the backend dependencies and AI/retrieval configuration available:

```sh
uv run python scripts/run_evaluations.py --backend-url https://ops-pilot-bjmb.onrender.com
```

The script prompts for your IncidentIQ account email and password. Password input is hidden. It signs in and calls `/auth/me`, keeping the access token only in memory. A single owner/admin workspace is selected automatically. If several are available, choose a listed workspace number; no UUID needs to be entered or placed in an environment file.

The six existing suites still run normally, including model and retrieval calls using the existing evaluation configuration. The authenticated organization's UUID supplies the retrieval scope. Results are written atomically to:

```text
evaluation-results/<discovered-organization-uuid>/report.json
```

The envelope includes `organization_id`, `generated_at`, and `report`. The report must be available at that path on the running backend for the dashboard to read it. Running the script on your laptop does not upload the resulting file to Render.

## Isolation and legacy files

The endpoint reads only the verified membership's directory and validates the organization ID inside the file. A report for another workspace, or a global legacy `evaluation-results/report.json` without proven ownership, is never assigned to the current workspace automatically. Re-run the evaluator to publish a scoped report. The legacy report is preserved.

Opening the Quality page only reads the published file; it does not invoke model evaluations. A missing report is shown as an empty state. No database migration is required.
