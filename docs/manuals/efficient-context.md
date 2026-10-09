# Efficient CL execution

## State observers
- `workspace.read` returns source/artifact observations; `project(ref,path="/content",start=0,count=400)` reads a field page.
- `context.read(handle,start=0,count=4000,view="source")` reads an integrity-checked archival page in the efficient CLI host.
- `R <procedure> ok +G` records verified exact readback. The host retains these procedure receipts through compaction.
- Terminal snapshots reread NativeActionStore's saved command result and hash; stdout and exit code come from the actual command.

## Typed actions
- `scripts/run_cl_efficient.py --root <owned workspace> --task-file <task> --receipts <fresh directory> --port <48731-48739> --budget <tokens>` runs exact GPT-6 Luna proposals through the production CL gateway.
- `run workspace.create-and-read(path,content)` creates and verifies a file.
- `run workspace.replace-and-read(path,content,replace="replace")` reviews, guards, replaces and verifies an existing file.
- `terminal.exec(command,shell,cwd,timeoutMs,maxOutputChars)` retains the existing permission and action identity checks.
- `done()` checks current observer goals. A caller's `quality_check` runs the requested independent workload and can invalidate completion.

## Executable checks
- `scripts/verify_c4c_context.py` executes actual mixed history/production calls, verifies source paging and failure retention, and refuses a corrupt history reference before a later write.
- `scripts/verify_c4c_terminal.py` executes system Python, independently verifies the saved result, refuses corruption, and preserves an actual nonzero command failure.
- `scripts/verify_c4c_transport.py` reproduces the Windows byte-lock read failure, proves correct queued admission and preserves real UTF-8 command failure output.
- `scripts/verify_c4c_pressure.py --budget 2000 --rep 1 --port 48731` runs the original real bug task with its exact regression workload and independent semantics.
- `scripts/run_c4c.py --run-id <fresh name> --ports 48733 48734 48735 48736 --repetitions 2` executes the 18-task paired matrix; native rows wait for C11 without any input or model call.

## Procedures
- For bounded bug repair, read the module and regression file, replace each with guarded readback, create the requested report, then call `done()` immediately. Repair only its actual failed checks.
- The bug procedure supplies workspace tools. The host runs the exact requested regression workload at `done()`; a separate terminal inspection is unnecessary.
- When a complete result exceeds the cap, follow the displayed source-view `nextStart`. Whole results remain in the archive. A partial page never acknowledges a complete observation baseline.
- For the full ablation, `--full-mechanism-control` disables procedures, diffs, compaction, batching and the short stable prefix; task checks remain identical.

## Judgement points
- A command's successful return is evidence about command completion. Independent semantic checks still decide whether its generated artifact solves the task.
- Creative quality and visual taste require review beyond keyword coverage. Blinded Luna ratings are uncalibrated model judgements.
- Two repetitions produce wide confidence intervals. Report each failure and each unattempted native task.

## Pitfalls
- `run` names a P procedure. A tools, including `terminal.exec`, use plain calls.
- Do not reread every source file after a P `ok +G`; its exact readback already completed. Create missing deliverables and run final acceptance.
- The host budget counts o200k prompt text; hidden CLI instructions and reasoning remain in actual provider usage.
- Cached input is part of input; total tokens equal input plus output. Never add cached input twice.
- A late checker error must retain the completed CL receipt and usage. On Windows, test lock-file size without reading another process's locked byte, and force subprocess UTF-8 output.
- Use only fresh owned roots and explicit C4 ports. Preserve interrupted attempts; never overwrite historical receipts.

## Frontier
- Native journeys wait for the C11 agent desktop; no request for Paul to open an app.
- Obscura renders the actual artifacts and controls. Its OS dark-media emulation is unsupported; dark checks activate the exact authored CSS in a disposable DOM.
- Original date holdout answers and blind preference keys remain unopened. Human preference calibration and the withheld 40-case score remain unverified.
