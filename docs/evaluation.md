# Validation and evaluation

The main workflow is evaluated against files a user can inspect: a pytest result, a source tree, a Git comparison, and the generated report. A report with valid structure is not automatically a correct diagnosis.

## Reproduce one real regression

```bash
python scripts/reproduce_pytest_demo.py --output-dir var/evaluation_demo
opspilot triage --repo var/evaluation_demo/project \
  --junit var/evaluation_demo/junit.xml --base HEAD \
  --notes var/evaluation_demo/project/docs \
  --output var/evaluation_demo/report
```

pytest documents [JUnit XML generation](https://docs.pytest.org/en/stable/how-to/output.html#creating-junitxml-format-files) and its [exit-code meanings](https://docs.pytest.org/en/stable/reference/exit-codes.html). A failing test run normally exits with code 1 while still producing the requested result file. These pytest conventions describe the input workflow, not OpsPilot diagnosis quality.

The generator creates a small cart project, commits a passing baseline, and then changes the discount boundary from `>= 100` to `> 100`. It actually runs pytest for both versions. The passing baseline has five passing tests; the changed working tree has one failed and four passed tests. The generated Git repository keeps the passing baseline as `HEAD`.

The output directory contains the project, `baseline.xml`, `junit.xml`, `baseline.log`, `stdout.log`, `change.diff`, and `metadata.json`. These artifacts let a reader compare the report with the actual test execution and code change. The script refuses to overwrite an existing non-empty directory; use a fresh output path for another run.

Check the resulting report manually:

1. Does the failed test match the failure recorded in `junit.xml`?
2. Does the source evidence point to existing lines inside the generated project?
3. Does the comparison show the actual boundary edit?
4. Does the retrieved note state the relevant discount rule?
5. Does the report keep a possible explanation separate from an observed fact?
6. Is the reproduction command presented as unexecuted?

This example is designed to be understandable. It is a constructed demonstration and does not estimate performance on arbitrary repositories.

## Automated checks

```bash
python -m pytest -q
```

Regression tests exercise parsing, invalid inputs, source-path boundaries, Git argument handling, missing context, report rendering, and optional model failures. Model checks use controlled adapters to validate response handling; they are not a benchmark of a real model's reasoning. Default tests do not require model weights or paid requests.

A CPU smoke run with local Qwen3-0.6B on the cart example fell back after model-output validation. The deterministic report remained available. This checks backend integration and fallback behavior, not the quality of model explanations. Remote-model explanation quality has not been evaluated.

When changing distribution files, also build a wheel and check it outside the source checkout:

```bash
python -m pip install build
python -m build
```

Use a fresh environment to install the resulting wheel and analyze explicitly supplied demo paths. This catches accidental dependence on the working directory or unshipped development files.

## What to measure next

For a larger evaluation, collect a separate set of small, reproducible regressions. Keep the passing version, failing version, test command, JUnit XML, and a verified explanation for each one. Include environment problems, assertion failures, import errors, missing files, unrelated diffs, and cases with insufficient evidence.

Measure distinct outcomes rather than a single “accuracy” value:

| Check | Question |
|---|---|
| Failure extraction | Was the correct failed/error test selected? |
| Source mapping | Do paths and line ranges correspond to the actual project? |
| Evidence validity | Do referenced IDs and quotes exist in the report? |
| Context usefulness | Did the report include the code or rule needed for the next check? |
| Hypothesis quality | Does a human reviewer judge the suggested explanation testable and supported? |
| Model outcome | Did the optional model succeed, fail validation, or remain unused? |

Keep deterministic and model-assisted results separate, retain unsuccessful cases, and record the source revision and model configuration. A valid quote, a passing schema check, or `analysis_ready` does not establish that a root cause was found. No general diagnosis accuracy or production performance claim is published here.
