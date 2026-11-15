# Changelog

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
