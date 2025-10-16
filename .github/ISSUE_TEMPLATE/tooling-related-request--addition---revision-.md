---
name: Tooling-related request (addition / revision)
about: Tooling related request (addition / revision)
title: Tooling-related request (addition / revision)
labels: ''
assignees: ''

---
**Describe the tool you'd like to have support for**
Name of the tool; links, etc.

**Documentation associated with the tool**
Any documentation links, etc.

**Additional context**
Add any other context or screenshots about the tool request here.

## Expected Input(s) to the tool
1. Natural language
2. Tool arguments (function / argument definitions)
3. Configurations (e.g, Kubeconfig, environment variables)
4. In-context Examples

## Process(ing)
Going by the definition: A validator will ensure that your code is syntactically correct, and a linter will ensure that your code is both syntactically and stylistically correct.

### Linting and Validation (e.g., is the syntax correct, format checker)
1. Objective: Linting and validation whether it be queries or the input to the underlying functions

### Semantic validation (e.g., do the entities identified exist and are relevant?)
1. Objective: Generalizable way to look-up in topology / taxonomy (or via an LLM)

### LLM as a judge for input(s) (TBD)

### Output Template(s)

## Expected Output(s)
- Hints to the model of what is expected / not expected
- Hints failed
e.g. Fetching Jaeger for a service which does not exist will return a 200 but it could mean that the service is not online or there is a problem with observablity stack.

### Successful Run
Defer to hint(s).

### Unsuccessful Run
Definition:
1. Retry condition(s) with failed output(s) in context
2. On failure, return template(s) for failed conditions

## Reflection(s) - LLM as a judge for the output(s) (TBD)
