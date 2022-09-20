import json
import html

from utils import main
from pretransforms import support_extensions

import code_ast
from code_ast.visitor import ASTVisitor, ResumingVisitorComposition

ERROR_FUNCS = ["reach_error", "__VERIFIER_error"]


def instrument(program_file : str, output_file : str):
    
    with open(program_file, "r") as f:
        source_code = f.read()

    # Run instrumentation
    transformed_code = support_extensions(source_code, _instrument)

    with open(output_file, "w") as o:
        o.write("#include <stdio.h>\n")
        o.write(transformed_code)


def _instrument(source_code):
    program_ast = code_ast.ast(source_code, lang = "c")

    # Run instrumentation
    instrumenter = ProgramInstrumenter(program_ast)
    program_ast.visit(instrumenter)

    return instrumenter.code()

# Instrumentation ----------------------------------------------------------------

class AnalysisState:
    def __init__(self, ast):
        self.ast = ast
    
    def __getattr__(self, name):
        return self.__dict__.get(name, None)


class ProgramInstrumenter(ResumingVisitorComposition):
    
    def __init__(self, ast):
        self._state = AnalysisState(ast)
        self._state.instrumentation = []

        self._location_analysis = LocationAnalysis(self._state)
        self._instrumenter      = Instrumenter(self._state)

        super().__init__(self._location_analysis, self._instrumenter)

    def code(self):
        
        source_lines    = self._state.ast.source_lines
        instrumentation = sorted(self._state.instrumentation, key = lambda x: x[0])
        if len(instrumentation) == 0: return "\n".join(source_lines)

        output = []

        instrumentation.append(((len(source_lines), 0), ""))

        current_pos = [0, 0]
        for pos, annotation in instrumentation:
            if tuple(current_pos) < pos:
                while current_pos[0] < pos[0]:
                    output.append(source_lines[current_pos[0]][current_pos[1]:] + "\n")
                    current_pos[0] += 1
                    current_pos[1] = 0

                if current_pos[1] < pos[1]:
                    output.append(source_lines[current_pos[0]][current_pos[1]:pos[1]])
                    current_pos[1] = pos[1]
            
            output.append(annotation)

        return "".join(output)


class LocationAnalysis(ASTVisitor):

    def __init__(self, state):
        self._state = state

        self._state.line        = 0
        self._state.line_offset = 0

    def on_visit(self, node):
        start_point = node.start_point
        assert (self._state.line, self._state.line_offset) <= start_point
        self._state.line = start_point[0]
        self._state.line_offset = start_point[1]
        return super().on_visit(node)
    
    def on_leave(self, node):
        end_point = node.end_point
        self._state.line = end_point[0]
        self._state.line_offset = end_point[1]
        return super().on_leave(node)


class Instrumenter(ASTVisitor):

    def __init__(self, state):
        self._state = state
        self.ast    = state.ast

        self.scope   = []
        self.control = None

    def instrument(self, text, pos = None):
        pos = pos or (self._state.line, self._state.line_offset)

        self._state.instrumentation.append(
            (pos, text)
        )

    def printf(self, text, track_args = None, pos = None):
        
        text = text.encode("utf-8").decode("unicode-escape")
        text = text.replace("\n", "\\n").replace("\"", '\\"')

        if track_args is None or len(track_args) == 0:
            track_args = ""
        else:
            track_args = "," + ",".join(track_args)

        printf_text = f'\nfprintf(stderr, "{text}\\n"{track_args});\n'
        self.instrument(printf_text, pos = pos)

    def printf_json(self, object, track_args = None, pos = None):
        if "sourcecode" in object: object["sourcecode"] = html.escape(object["sourcecode"])
        self.printf(json.dumps(object), track_args = track_args, pos = pos)
    
    # Visitor functions -----------------------------

    def visit_function_definition(self, node):

       # Decide scope
       declarator = node.child_by_field_name("declarator")
       func_name  = declarator.child_by_field_name("declarator")
       assert func_name.type == "identifier", func_name.type

       func_name = self.ast.match(func_name)
       self.scope.append(func_name)

       if func_name in ERROR_FUNCS: return False 
    

    def leave_function_definition(self, node):
        self.scope.pop(-1)

    # Statement visitors -----------------------------

    def _handle_error(self, node):
        start_line = node.start_point[0]
        end_line   = node.end_point[0]
        source_code = self.ast.match(node)

        output = {
            "sourcecode": source_code,
            "startline" : 1 + start_line,
            "endline"   : 1 + end_line
        }

        return self.printf_json(
            output,
            pos = node.start_point
        )

    def visit_expression_statement(self, node):
        statement = node.children[0]
        if statement.type == "call_expression":
            called_function = self.ast.match(statement.child_by_field_name("function"))
            if called_function in ERROR_FUNCS:
                self._handle_error(node)
        return True

    def leave_expression_statement(self, node):

        # Obtain changed variables
        written_vars = VariableVisitor()
        written_vars.walk(node)
        written_vars = set(self.ast.match(n) for n in written_vars.vars)

        start_line = node.start_point[0]
        end_line   = node.end_point[0]
        source_code = self.ast.match(node)

        output = {
            "sourcecode": source_code,
            "startline" : 1 + start_line,
            "endline"   : 1 + end_line
        }

        if len(written_vars) > 0:
            output["assumption"] = ";".join(
                [f"{var} == (%d)" for var in written_vars] + [""])
            output["assumption.scope"] = ".".join(self.scope)

        return self.printf_json(
            output,
            track_args = written_vars,
            pos = node.end_point
        )


    def _write_condition(self, condition, true_branch = True, changed_vars = [], pos = None, startline = -1, endline = -1):

        if startline == -1: startline = pos[0]
        if endline   == -1: endline   = startline
        source_code = "[%s]" % ("!(%s)" % condition if not true_branch else condition)

        output = {
            "sourcecode": source_code,
            "startline" : 1 + startline,
            "endline"   : 1 + endline,
            "control"   : "condition-%s" % ("true" if true_branch else "false")
        }

        if len(changed_vars) > 0:
            output["assumption"] = ";".join(
                [f"{var} == (%d)" for var in changed_vars] + [""])
            output["assumption.scope"] = ".".join(self.scope)

        return self.printf_json(
            output,
            track_args = changed_vars,
            pos = pos
        )


    def _write_condition_node(self, condition_node, consequence_node, true_branch = False, skip = False):
        condition = self.ast.match(condition_node)
        reads     = VariableVisitor()
        reads.walk(condition_node)
        reads     = set(self.ast.match(n) for n in reads.vars)

        # Ensure every statement in compound
        self._write_condition(condition, 
                                true_branch = true_branch,
                                changed_vars = reads, 
                                pos = consequence_node.start_point if not skip else consequence_node.end_point,
                                startline = condition_node.start_point[0],
                                endline = condition_node.end_point[0])



    def visit_if_statement(self, node):
        condition_node = node.child_by_field_name("condition")

        # Ensure every statement in compound
        consequence = node.child_by_field_name("consequence")
        if consequence is not None: 
            if consequence.type != "compound_statement":
                self.instrument("{\n", pos = consequence.start_point)
            else:
                consequence = consequence.children[1]
            
            self._write_condition_node(condition_node, consequence, True)

        alternative = node.child_by_field_name("alternative") 
        if alternative is not None: 
            if alternative.type != "compound_statement":
                self.instrument("{\n", pos = alternative.start_point)
            else:
                alternative = alternative.children[1]
            
            self._write_condition_node(condition_node, alternative, False)
    

    def leave_if_statement(self, node):
        # Ensure every statement in compound
        consequence = node.child_by_field_name("consequence")
        if consequence is not None: 
            if consequence.type != "compound_statement":
                self.instrument("\n}", pos = consequence.end_point)
        
        alternative = node.child_by_field_name("alternative") 
        if alternative is not None: 
            if alternative.type != "compound_statement":
                self.instrument("\n}", pos = alternative.end_point)
        
    
    def visit_for_statement(self, node):
        condition_node = node.child_by_field_name("condition")

        consequence = node.children[-1]
        if consequence is not None: 
            if consequence.type != "compound_statement":
                self.instrument("{\n", pos = consequence.end_point)
            else:
                consequence = consequence.children[1]

        self._write_condition_node(condition_node, consequence, True)


    def leave_for_statement(self, node):
        # Ensure every statement in compound
        consequence = node.children[-1]
        if consequence is not None: 
            if consequence.type != "compound_statement":
                self.instrument("\n}", pos = consequence.end_point)

        condition_node = node.child_by_field_name("condition")
        self._write_condition_node(condition_node, consequence, False, skip = True)


    def visit_while_statement(self, node):
        condition_node = node.child_by_field_name("condition")

        consequence = node.children[-1]
        if consequence is not None: 
            if consequence.type != "compound_statement":
                self.instrument("{\n", pos = consequence.end_point)
            else:
                consequence = consequence.children[1]

        self._write_condition_node(condition_node, consequence, True)


    def leave_while_statement(self, node):
        # Ensure every statement in compound
        consequence = node.children[-1]
        if consequence is not None: 
            if consequence.type != "compound_statement":
                self.instrument("\n}", pos = consequence.end_point)

        condition_node = node.child_by_field_name("condition")
        self._write_condition_node(condition_node, consequence, False, skip = True)

    
    def visit_do_statement(self, node):
        condition_node = node.child_by_field_name("condition")

        consequence = node.child_by_field_name("body")
        if consequence is not None: 
            if consequence.type != "compound_statement":
                self.instrument("{\n", pos = consequence.end_point)
            else:
                consequence = consequence.children[1]

        self._write_condition_node(condition_node, consequence, True)


    def leave_do_statement(self, node):
        # Ensure every statement in compound
        consequence = node.child_by_field_name("body")
        if consequence is not None: 
            if consequence.type != "compound_statement":
                self.instrument("\n}", pos = consequence.end_point)

        condition_node = node.child_by_field_name("condition")
        self._write_condition_node(condition_node, consequence, False, skip = True)


    # Ignore statements -------------------------------------

    def visit_attributed_statement(self, node):
        return True

    def visit_labeled_statement(self, node):
        return True

    def visit_compound_statement(self, node):
        return True

    def visit_return_statement(self, node):
        return True

    def visit_switch_statement(self, node):
        # Ignore for now. Should we adress this?
        pass

    # We can safely ignore control statements
    def visit_goto_statement(self, node):
        return True

    def visit_continue_statement(self, node):
        return True
    
    def visit_break_statement(self, node):
        return True

    def visit(self, node):
        if node.type.endswith("statement"):
            print("[Dbg] No instrumentation for %s" % node.type)


# Variable write visitor -------
    

class VariableVisitor(ASTVisitor):

    def __init__(self):
        self.vars = []

    def visit_identifier(self, node):
        self.vars.append(node)

    def visit_call_expression(self, node):
        self.walk(node.child_by_field_name("arguments"))
        return False

    def visit_subscript_expression(self, node):
        self.walk(node.child_by_field_name("index"))
        self.vars.append(node)
        return False

    def visit_conditional_expression(self, node):
        return True

    def visit_assignment_expression(self, node):
        return True

    def visit_binary_expression(self, node):
        return True

    def visit_unary_expression(self, node):
        return True

    def visit_update_expression(self, node):
        return True

    def visit_cast_expression(self, node):
        self.walk(node.children[-1])
        return False

    def visit_pointer_expression(self, node):
        return False # TODO: For safety, might need revisit

    def visit_sizeof_expression(self, node):
        self.walk(node.child_by_field_name("value"))
        return False

    def visit_field_expression(self, node):
        self.vars.append(node)
        return False

    def visit_compound_literal_expression(self, node):
        return False

    def visit_number_literal(self, node):
        return False

    def visit_string_literal(self, node):
        return False

    def visit_true(self, node):
        return False

    def visit_false(self, node):
        return False

    def visit_null(self, node):
        return False

    def visit_concatenated_string(self, node):
        return False

    def visit_char_literal(self, node):
        return False

    def visit_parenthesized_expression(self, node):
        return True

    def visit(self, node):
        if node.type.endswith("expression"):
            print("[Dbg] No instrumentation for %s" % node.type)



if __name__ == '__main__':
    main(instrument)