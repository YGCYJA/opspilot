# Small cart regression example

This is an intentionally constructed example, not a production incident.
The baseline implements a five-test `Decimal` shopping-cart discount rule.
It needs only Python, pytest, and Git; it does not use a model or a network.

From the OpsPilot repository root, run:

```sh
python scripts/reproduce_pytest_demo.py --output-dir var/pytest_demo
```

The script copies these files into a new `project/` Git repository, verifies
that all five tests pass, and commits that baseline with a demonstration-only
identity. It then deliberately replaces `>= 100.00` with `> 100.00` in `cart.py`
and runs the same tests again. The exact-threshold test fails; the four other
tests pass. The modified file remains uncommitted so that a diff against `HEAD`
shows the introduced regression.

Generated evidence in the output directory:

| Path | Contents |
| --- | --- |
| `project/` | Baseline Git commit and modified working tree |
| `baseline.xml`, `baseline.log` | Actual passing pytest run |
| `junit.xml`, `stdout.log` | Actual failing pytest run |
| `change.diff` | Actual working-tree diff against `HEAD` |
| `metadata.json` | Exit codes, test counts, and relative artifact paths |

The script refuses to overwrite a nonempty output directory. Use a different
`--output-dir` to run it again. Reports replace local absolute directory names
with placeholders so the evidence can be shared. They still contain the actual
test result and assertion text.

Analyze the generated failure with:

```sh
opspilot triage --repo var/pytest_demo/project \
  --junit var/pytest_demo/junit.xml --base HEAD \
  --notes var/pytest_demo/project/docs --output var/pytest_demo/report
```

The analysis can point to a likely boundary regression and the documented
inclusive threshold. It is an evidence-based hypothesis: the assistant does
not apply a patch or claim that a proposed fix has passed tests.
