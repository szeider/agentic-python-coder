# Changelog

## 4.0.0 (unreleased; release candidate 4.0.0rc1 published 2026-11-15)

Kernel server (`ipython_mcp`): new kernel-id semantics. Tool names, parameter names and types, and existing result keys are unchanged; the Python API (`create_kernel`, `restart_kernel`, ...) keeps its signatures, and `create_kernel(None)` still returns an 8-hex id. The agent side (`coder`, `solve_task`) is unchanged.

### Breaking

- `python_reset` without `kernel_id` (or with `null` or `""`) restarts the default kernel `_default`, the one every call without `kernel_id` uses, and starts it if it is not running. Before, it created a new kernel with an 8-hex id. A client that copies the returned `kernel_id` keeps working, since `"_default"` is accepted by every tool; a client that relied on a new isolated kernel per id-less reset now shares the default kernel and must pass its own `kernel_id`.
- `python_reset(kernel_id="X")` with an id that has no kernel and no crash record creates kernel `X`. Before, it failed with "Kernel X not found". The client chooses the id: 1 to 64 letters, digits, `_`, `-`, `.`, starting with a letter or digit. `default`, `new`, `none`, `null` (any case) and ids starting with `_` other than `_default` are refused with an error that says to omit `kernel_id` for the default kernel.
- `python_reset` replies have a new key `created` on every success: true if the id had neither a live kernel nor a crash record before the call. When a named kernel is created, `message` ends with a sentence that says to pass that `kernel_id` on every later call.
- `packages` in `python_reset`: a non-empty list replaces the kernel's packages; omitted, `null` and `[]` keep them, also for the default kernel. Before, an id-less reset started a new kernel, so there `[]` meant no packages.
- A `python_exec` without `kernel_id` after the default kernel crashed restarts it with its remembered packages and does not run its code. The reply is an error: `"The default kernel had crashed and was started again with packages [...]. Earlier variables, imports and definitions are gone. This code was not executed; send it again."` with `"executed": false`, `"kernel_restarted": true`, `"kernel_busy": false`, `"timed_out": false`. The next call runs normally. This also holds for empty code. Before, the call started a bare kernel without notice and ran the code against the lost state. A default kernel whose process died while idle is detected by the next `python_exec` and handled the same way. If the restart itself fails, the reply is the start error, and the next call tries again.
- `python_exec` and `python_interrupt` with an unknown named id fail with `Kernel "X" not found. Live kernels: [...]. python_reset(kernel_id="X") creates it; omit kernel_id for the default kernel.`, and with a crash record with `Kernel "X" crashed, its state is lost. python_reset(kernel_id="X") restarts it with its packages.` Before, `python_interrupt` answered "No active session to interrupt" in both cases; it still does for the default kernel.
- `python_status` has a new key `crashed` (true when the queried id has a crash record).
- `CODER_MAX_KERNELS` counts named kernels only; the default kernel is neither counted nor refused. At the limit, `python_reset` with a new id fails with `Maximum of N named kernels reached. Live: ... python_reset(kernel_id=<one of these>) reuses that kernel and discards its state; omit kernel_id for the default kernel.`
- Texts that recommend `python_reset` after a crash name the kernel id for a named kernel; for the default kernel they say: "The next python_exec restarts it with the same packages; that call is not executed and must be sent again. python_reset() restarts it as well." The crash-during-execution text is now `Kernel "X" crashed during execution, its state is lost.` plus that hint; a timeout after which the kernel died reads "Execution timed out after Ns. Session crashed." plus the hint. The prefix "Execution timed out after" and the 3.6.0 keys are unchanged.
- A named kernel whose process died while idle is detected by the next `python_exec` or `python_interrupt`, which answer with the "crashed" text above. Before, `python_exec` answered "Session crashed: Kernel X is dead. Call python_reset to restart." and `python_interrupt` answered "Interrupt sent. Session state preserved." For the default kernel, `python_interrupt` now says that it crashed and that the next `python_exec` restarts it (that call is not executed).
- `python_exec` with empty or whitespace-only code goes through the same handling as other code: an unknown named id is an error, a crashed default kernel is restarted (the error reply above), and a default kernel that is not running is started. Before, empty code returned success without touching any kernel.
- `all_kernels` in `python_status` and the kernel lists in the error texts contain only kernels whose process is alive. Before, `all_kernels` also listed a registered kernel that had died until some call noticed it. The Python API's `list_kernels()` is unchanged.
- A failed `python_reset` without `kernel_id` reports `"kernel_id": "_default"` (before: `null`); a refused id is reported in `kernel_id` too.

### Changed/Fixed

- One lock per kernel id: `python_reset` holds it for the whole call, `python_exec` for its existence check and auto-start. A `python_exec` sent together with a `python_reset` of the same kernel runs in the new kernel afterwards; before, it could fail with "Failed to auto-start session: Kernel _default already exists".
- If a client cancels a `python_reset` or a `python_exec` while its kernel is being started, the kernel's lock stays held until the start has finished, so the next call on that kernel waits for it instead of failing with "already exists".
- A restart that fails (for example an unresolvable package, or an error while shutting down the old kernel) leaves a crash record with the old packages and cwd, and the old kernel process is killed, so `python_reset(kernel_id=...)` without packages, or for the default kernel the next `python_exec`, brings the kernel back. Before, the id was dropped, and an error during the shutdown of the old kernel left the id blocked ("already exists") until the server restarted.
- A restart no longer fails with "Unknown kernel" when a concurrent `python_status` notices at the same moment that the kernel died.
- Python API: `create_kernel` accepts the id grammar above (before: `_default` or 8 hex characters only) and does not count or refuse the default kernel at `MAX_KERNELS`, so `get_kernel()` works at the limit; `restart_kernel` keeps a crash record when the new kernel fails to start, so a second `restart_kernel(id)` brings the kernel back instead of raising `KeyError`.
- `python_interrupt` description: continue with `python_exec` using the same `kernel_id`.
- Tool descriptions of `python_reset`, `python_exec` and `python_status` and the README MCP section describe the new semantics.

### Known limits

- Two clients of one server process that pick the same name share that kernel; `created: false` tells the second one only after its reset.
- A host that restarts the server process loses all kernels and crash records; the next `python_exec` without `kernel_id` then starts a bare default kernel without a signal.
- A `python_exec` that is already running when a `python_reset` of its kernel arrives is ended by the reset, as in 3.6.0.
- A named kernel that died but was not yet noticed by any call still counts against `CODER_MAX_KERNELS`, although it is not listed as live.

## 3.6.1 (2026-11-15)

Kernel server (`ipython_mcp`). No change to tool names, parameters or existing result keys.

### Fixed

- When a kernel that was launched through uv dies during startup (for example because a package cannot be resolved), the error now ends with uv's reason: "Failed to start kernel: Kernel died before replying to kernel_info. uv said: ...". The server obtains it by running the same uv command once more with `python -c pass` (at most 30 s, only after a failed start). Before, the reason appeared only on the server's stderr.
- `python_status`: `packages` lists the packages requested for the kernel first, then the others sorted by name, still cut at 20 entries. The new key `packages_total` gives the number before the cut (`null` while the kernel is busy or not running). Before, the list held the first 20 distributions in directory order, so requested packages could be missing.
- The status probe no longer fails when user code has overwritten `repr`, `sorted`, `len` or `reversed`.

## 3.6.0 (2026-11-14)

Kernel server (`ipython_mcp`). Tool names, parameters and existing result keys are unchanged; the new keys below are additions.

### Fixed

- A `python_exec` that times out now reports whether the code was stopped. The server interrupts, waits up to 2 s for the kernel to become idle, and then answers:
  - code stopped: the error text is as before ("Execution timed out after Ns. Code interrupted but session state preserved."), with `"timed_out": true`, `"kernel_busy": false` and the output collected so far;
  - code still running (it ignores the interrupt): the error starts with "Execution timed out after Ns. The code is still running; the interrupt did not stop it.", with `"timed_out": true`, `"kernel_busy": true`. This reply arrives about 2 s after the timeout.
- A `python_exec` that arrives while earlier, abandoned code is still running in the kernel is refused at once ("Kernel busy with earlier code; this code was not executed.", `"executed": false`, `"kernel_busy": true`). Before, it waited for its own timeout, was reported as timed out, and its code stayed queued in the kernel.
- Parallel `python_exec` calls on one kernel are still run one after the other. A call that waits its whole timeout behind another call is refused without being sent.
- A request that the kernel aborted after an earlier error is reported as not executed (`"executed": false`). Before, it returned success with empty output.
- `python_status` has a new key `"kernel_busy"`. While the kernel is busy, the status is answered at once, without version, packages and variables.
- `python_reset` on a busy kernel ends the kernel process and returns without waiting for the running code (0.5 s instead of 10 s in the reported case). The reply then has `"replaced_busy_kernel": true` and a sentence appended to `message`. A call that is in flight on that kernel is ended by the reset.
- The timeout is kept by one timer. No worker thread holds the kernel after its reply has been sent.

### Changed

- Agent side (`coder`, `solve_task`): results for completed code, Python errors and ordinary timeouts are unchanged. If earlier code is still running when a call starts, the call waits for it within its own deadline, interrupts once more at half the deadline, and then either runs or returns "Earlier code is still running in the kernel; this code was not executed."
- Execute requests are sent with `stop_on_error=False`.
- `.gitignore`: only the top-level `tests/` folder is ignored, so new files under `coder/tests/` are visible to git.
- Tests that call the network carry the pytest marker `network` and are not part of the default run (`uv run pytest -m network coder/tests/` runs them).
- README: `submit_code` added to the tool table.

### Known limits

- If the kernel reports idle for a request and the matching execute reply does not arrive within about 1 s, the request counts as completed with the output collected.
- Not handled: two resets of one kernel at the same time, a request cancelled by the client, and an `python_exec` that arrives during a reset (it gets the "crashed during execution" text).

## 3.5.0 (2026-11-14)

- Requires mcp 2.x.
- `python_status` probes without side effects; crash detection and reset by kernel id; input validation under mcp 2.x; clean startup namespace; no ANSI codes in tracebacks; built-in kernelspec; lower bound on timeouts.
- `python_reset` probes without a namespace leak and reports kept packages; `null` is accepted for optional tool arguments.

## 3.4.4 (2026-11-13)

- Supports mcp 2.x alongside 1.x. Kernel stdout goes to stderr, so native output no longer corrupts the JSON-RPC stream.
