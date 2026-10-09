# neyviaOfficeSuiteModel

Provides OFFICE_SUITE_TOOL_IDS, OFFICE_SUITE_DEFAULT_TOOL_ID, OFFICE_COMMON_FIELDS_BY_OPERATION, OFFICE_PANDOC_COMMON_OUTPUT_FORMATS for Neyvia's UI state and behavior.

- **Public API:** `OFFICE_COMMON_FIELDS_BY_OPERATION`, `OFFICE_PANDOC_COMMON_OUTPUT_FORMATS`, `OFFICE_SUITE_DEFAULT_TOOL_ID`, `OFFICE_SUITE_TOOL_IDS`, `buildOfficeSuiteExecutePayload`, `classifyOfficeSuiteOutcome`, `defaultArgumentsForOperation`, `normalizeOfficeExecuteResult`, `normalizeOfficePermissionSummary`, `normalizeOfficeToolDescribe`, `officeOutputFormatChoices`, `officeSuiteOutcomeLabel`, `partitionOfficeFormFields`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `office.classify`, `office.describe`, `office.execute`, `office.payload`.
- **Dependencies:** [surface.neyviaFrontendContracts](../surface.neyviaFrontendContracts/README.md).
- **Owner:** Neyvia / neyviaOfficeSuiteModel.
- **Files:** [web/src/neyvia/neyviaOfficeSuiteModel.js](../../web/src/neyvia/neyviaOfficeSuiteModel.js).
