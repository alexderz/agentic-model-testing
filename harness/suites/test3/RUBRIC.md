# Test 3: transcript rubric (scored by Model Master)

Read the case's main session and every mcp-probe session (`oc-data/opencode.db`; `grade-test3.py
--detail` lists the prompts given to the probe). Score each item 0, 1 or 2 and quote the transcript line
that decides it. Total out of 12. The automatic columns (facts right, probe calls, API calls, fix) are
separate and not repeated here.

1. **The brief stands on its own.** The probe knows only what it is told.
   2: each task says what to find, about which entities or domains, and what counts (for example "lights
   whose state is unavailable"). 1: the goal is clear but the probe has to guess scope or definitions.
   0: vague ("check the MCP", "get the data").
2. **It is specific and sized for the probe.** 2: one clear job per task, or a short numbered list the
   probe can finish in one go. 1: workable but sprawling, or split so finely that it costs many sessions.
   0: everything in one undirected request, or the probe asked to do things its tools cannot.
3. **It asks for structured output.** 2: names the shape it wants back (JSON keys, a table, raw tool
   output for numbers) and asks the probe to report tool errors. 1: asks for a summary it then has to
   parse. 0: no request about the answer's form.
4. **It checks what the probe returns.** 2: compares the probe's answers with the REST API and notices
   and follows up on disagreements. 1: checks some facts, or checks but does not act on a mismatch.
   0: takes the probe's answers as true.
5. **It handles a failing probe.** 2: when a probe fails, errors or returns nothing, it finds out why
   (the tool, the server, its own brief) and changes something before trying again. 1: retries with a
   reworded brief only. 0: gives up, or repeats the same brief. (No failure in the run: score 2 if the
   brief told the probe how to report failures, else 1.)
6. **Its trust-or-fix decision fits the evidence.** 2: the decision follows from what it saw; a fix
   targets the cause it found and is re-checked through the probe; a server it trusts gave right answers.
   1: right decision, thin evidence or no re-check. 0: trusts a server that gave wrong answers, or
   "fixes" a working one.

Record per case: the six scores with quotes, the total, and one sentence on how it managed the probe.
