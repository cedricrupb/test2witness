from utils import main

import json
import os

BASE_DIR = os.path.dirname(os.path.realpath(__file__))

def _resolve_path(path):
    if os.path.exists(path): return path
    return os.path.join(BASE_DIR, path)

import sys
sys.path.append(_resolve_path("./test-suite-validator/"))
import suite_validation

from suite_validation import execution as exe
from suite_validation import execution_utils as eu

from instrument import instrument
from witness    import create_empty_witness


def test2witness(program_path : str, test_path : str,
                    output : str = "witness.graphml",
                    machine_model : str = "m64",
                    timelimit : int = 900,
                    spec : str = "",
                    producer: str = "Test2Witness"):

    name, ext = os.path.splitext(program_path)
    instrumented_path = name + "-instrumented" + ext

    # Instrument the code
    instrument(program_path, instrumented_path)

    try:
        exec_info = execute_test(
            instrumented_path,
            test_path,
            machine_model = machine_model,
            timelimit = timelimit
        )
    finally:
        os.remove(instrumented_path)
        if os.path.exists("a.out"): os.remove("a.out")
        if os.path.exists("harness.c"): os.remove("harness.c")

    if exec_info.returncode == 0:
        print("Error location was not reached. Abort.")
        return
    
    o = exec_info.stderr.decode("utf-8")
    witness = create_empty_witness(
        program_path,
        specification_path = None if len(spec) == 0 else spec,
        is_violation = True,
        producer = producer,
        is_32 = machine_model == "m32"
    )

    _populate_witness(witness, o)

    witness.toxml(output)

    print("Success.")



def execute_test(program_path, test_path,
                    machine_model : str = "m64",
                    timelimit : int = 900):
    
    # Load test case
    with open(test_path, "rb") as l:
        xml_lines = l.readlines()

    test_vector = exe.convert_to_vector_if_testcase(test_path, xml_lines)
    if test_vector is None:
        raise ValueError("Test vector %s is not readable" % str(test_vector))

    runner = exe.ExecutionRunner(
        "-%s" % machine_model, timelimit
    )

    result = runner.run(program_path, test_vector)
    
    verdict = result.verdict
    
    if verdict == eu.ERROR:
        raise ValueError("Error during executing program...")

    if verdict == eu.ABORTED:
        raise ValueError("Execution stopped before the program finished...")

    return result.execution_info


# Writing the witness -----------------------------------------------------------------

def _parse_observations(exec_output):
    observations = []
    
    for line in exec_output.splitlines():
        try:
            observation = json.loads(line)
        except Exception:
            continue

        observations.append(observation)
    
    return observations

def _populate_witness(witness, exec_output):
    observations = _parse_observations(exec_output)

    init_node = witness.node()
    init_node.entry = True
    current_node = init_node

    for observation in observations:
        target_node = witness.node()
        edge = witness.edge(current_node, target_node)
        
        # Necessaries
        edge.sourcecode = observation["sourcecode"]
        edge.startline  = observation["startline"]
        edge.endline    = observation["endline"]

        # Optionals
        edge.assumption         = observation.get("assumption", None)
        edge.assumption_scope   = observation.get("assumption.scope", None)
        edge.control            = observation.get("control", None)
        edge.enterFunction      = observation.get("enterFunction", None)
        edge.returnFromFunction = observation.get("returnFromFunction", None)

        current_node = target_node


    current_node.violation = True

    return witness



if __name__ == '__main__':
    main(test2witness)