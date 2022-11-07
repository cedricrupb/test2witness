# Test2Witness
The tool test2witness converts a test case to a violation witness.
In fact, test2witness parses a test case (in the TestComp format)
and executes the test case. Visited branches and valuations
of variables are tracked dynamically to create a violation witness
(in the GraphML format). We employ the official test-suite-validator
for safe execution.

## License
MIT License